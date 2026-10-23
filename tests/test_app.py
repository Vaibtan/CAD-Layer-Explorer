"""Public HTTP and real child-process acceptance against the running container."""
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pymupdf
import pytest

from fixtures import fixture

BASE = os.environ.get('CAD_TEST_URL', 'http://127.0.0.1:8000')


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE, timeout=30) as client:
        yield client


def upload(client, path, name=None):
    response = client.post('/api/documents', files={'file': (name or path.name, path.read_bytes(), 'text/plain')})
    assert response.status_code in (200,202), response.text
    return response.json()['id']


def ready(client, digest, expected='succeeded'):
    deadline = time.monotonic()+310
    while time.monotonic()<deadline:
        status = client.get(f'/api/documents/{digest}/status').json()
        if status['state'] in ('succeeded','failed','interrupted'):
            assert status['state'] == expected, status
            return client.get(f'/api/documents/{digest}/analysis').json() if expected == 'succeeded' else status
        time.sleep(.1)
    pytest.fail('Analysis timed out')


def render(client, digest, **request):
    response = client.post(f'/api/documents/{digest}/renders', json={'page':1, 'scale':.5, **request})
    assert response.status_code in (200,202), response.text
    deadline = time.monotonic()+25
    while time.monotonic()<deadline:
        result = client.get(response.json()['url'])
        if result.status_code == 202:
            time.sleep(.05)
            continue
        assert result.status_code == 200, result.text
        return result.content, response.json()
    pytest.fail('Render timed out')


def nonwhite(png):
    p = pymupdf.Pixmap(png)
    data = p.samples
    return sum(data[i:i+3] != b'\xff\xff\xff' for i in range(0,len(data),3))


def test_count_semantics_and_empty_states(client, tmp_path):
    digest = upload(client, fixture(tmp_path/'counts.pdf'))
    try:
        manifest = ready(client,digest)
        a,b,empty,unused = manifest['layers']
        assert a['counts'] == {'paths':4,'text_shows':1,'images':3,'shadings':1}
        assert a['source_operations'] == 9
        assert b['counts']['paths'] == 1 and not b['default_visible']
        assert a['name'] == b['name'] and a['id'] != b['id']
        assert empty['referenced_pages'] == [1] and empty['content_pages'] == [] and empty['source_empty']
        assert unused['referenced_pages'] == [] and unused['source_empty']
        for layer in manifest['layers']:
            assert layer['counts'] == {k:sum(p['counts'][k] for p in layer['page_details']) for k in layer['counts']}
        first,_=render(client,digest,mode='solo',layers=[a['id']])
        second,_=render(client,digest,mode='solo',layers=[b['id']])
        again,cached=render(client,digest,mode='solo',layers=[a['id']])
        assert nonwhite(first)>0 and nonwhite(second)>0 and first != second and first==again
        assert cached['state']=='succeeded'
        off,_=render(client,digest,mode='all-off')
        assert nonwhite(off)==0
        assert client.get(f'/api/documents/{digest}/analysis?download=true').content == client.get(f'/api/documents/{digest}/analysis').content
    finally:
        client.delete(f'/api/documents/{digest}')


@pytest.mark.parametrize('kind',['base','conditional','invisible','plain','scan','annotation','rotated','restricted'])
def test_capabilities_and_visibility(client,tmp_path,kind):
    digest=upload(client,fixture(tmp_path/f'{kind}.pdf',kind))
    try:
        manifest=ready(client,digest)
        if kind in ('plain','scan'):
            assert manifest['layers']==[] and not manifest['document']['has_layers']
            png,_=render(client,digest,mode='original');assert nonwhite(png)>0
        elif kind=='base':
            assert manifest['capabilities']['base_content_present'] and not manifest['capabilities']['strict_solo']
            png,_=render(client,digest,mode='all-off');assert nonwhite(png)>0
            assert client.post(f'/api/documents/{digest}/renders',json={'page':1,'mode':'solo','layers':[manifest['layers'][0]['id']]}).status_code==422
        elif kind=='conditional':
            assert not manifest['capabilities']['strict_solo'] and manifest['conditional_content']
            assert manifest['layers'][0]['source_empty'] is None
            assert manifest['layers'][1]['source_empty'] is None
        elif kind=='invisible':
            layer=manifest['layers'][0]
            assert not layer['source_empty'] and layer['counts']=={'paths':3,'text_shows':1,'images':0,'shadings':0}
            assert layer['page_details'][0]['visible_output']['nonwhite_pixels']==0
        elif kind=='annotation':
            assert manifest['document']['annotation_count']==1 and manifest['pages'][0]['layer_annotations']==1
            assert manifest['layers'][0]['counts']['paths']==1 and manifest['layers'][1]['source_empty']
        elif kind=='rotated':
            p=manifest['pages'][0];assert p['rotation']==90 and p['width']==140 and p['height']==220
            a=manifest['layers'][0]['id'];png,_=render(client,digest,mode='solo',layers=[a]);image=pymupdf.Pixmap(png)
            assert image.width==70 and image.height==110
        elif kind=='restricted':
            assert not manifest['capabilities']['custom_visibility']
            assert client.post(f'/api/documents/{digest}/renders',json={'page':1,'mode':'all-on'}).status_code==422
    finally:
        client.delete(f'/api/documents/{digest}')


def test_validation_and_recovery(client,tmp_path):
    assert client.post('/api/documents',files={'file':('fake.pdf',b'not pdf','application/pdf')}).status_code==422
    for kind,code in [('encrypted','encrypted_pdf'),('cycle','content_cycle')]:
        digest=upload(client,fixture(tmp_path/f'{kind}.pdf',kind))
        status=ready(client,digest,'failed'); assert status['error']['code']==code
        assert client.get(f'/api/documents/{digest}/analysis').status_code==409
        client.delete(f'/api/documents/{digest}')
    digest=upload(client,fixture(tmp_path/'valid.pdf','plain'));ready(client,digest)
    try:
        for request in [{'page':2},{'page':0},{'page':1,'layers':['foreign']},{'page':1,'scale':100},{'page':1,'mode':'invalid'}]:
            result=client.post(f'/api/documents/{digest}/renders',json=request)
            assert result.status_code==422 and result.json()['error']['code']
        assert client.get('/api/health').status_code==200
    finally:
        client.delete(f'/api/documents/{digest}')


def test_determinism_deduplication_and_deletion(client,tmp_path):
    path=fixture(tmp_path/'determinism.pdf')
    with ThreadPoolExecutor(3) as pool:
        ids=list(pool.map(lambda name:upload(client,path,name),['a.pdf','b.pdf','c.pdf']))
    assert len(set(ids))==1
    digest=ids[0];ready(client,digest)
    one=client.get(f'/api/documents/{digest}/analysis').content
    _,job=render(client,digest,mode='original',uncached=True)
    assert client.delete(f'/api/documents/{digest}').status_code==204
    assert client.get(job['url']).status_code==404
    assert client.get(f'/api/documents/{digest}/analysis').status_code==404
    assert client.delete(f'/api/documents/{digest}').status_code==204
    upload(client,path,'renamed.pdf');ready(client,digest)
    assert one==client.get(f'/api/documents/{digest}/analysis').content
    client.delete(f'/api/documents/{digest}')


def test_delete_queued_or_running(client,tmp_path):
    path=fixture(tmp_path/'delete-running.pdf')
    digest=upload(client,path)
    assert client.delete(f'/api/documents/{digest}').status_code==204
    time.sleep(.5)
    assert client.get(f'/api/documents/{digest}/status').status_code==404
    upload(client,path);ready(client,digest)
    client.delete(f'/api/documents/{digest}')


@pytest.mark.skipif(os.environ.get('CAD_FULL_ACCEPTANCE')!='1',reason='Set CAD_FULL_ACCEPTANCE=1 for 533 uncached supplied-drawing renders')
def test_supplied_drawing_full_isolation(client):
    path=Path(os.environ.get('CAD_DRAWING','cader structural-1.pdf'))
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='33b334cc2c696c1fa1a03ddfca25838e6c2d483be006870a9aac94549ff17693'
    digest=upload(client,path);manifest=ready(client,digest)
    assert manifest['document']['page_count']==38 and len(manifest['layers'])==38
    assert len({l['name'] for l in manifest['layers']})==30
    assert sum(len(l['referenced_pages']) for l in manifest['layers'])==495
    assert all(6<=len(p['layers'])<=20 for p in manifest['pages'])
    assert manifest['capabilities']['strict_solo']
    for layer in manifest['layers']:
        for pair in layer['page_details']:
            assert pair['visible_output']['nonwhite_pixels']>0
            png,_=render(client,digest,page=pair['page'],mode='solo',layers=[layer['id']],uncached=True)
            assert nonwhite(png)>0,(layer['id'],pair['page'])
    for p in range(1,39):
        png,_=render(client,digest,page=p,mode='all-off',uncached=True)
        assert nonwhite(png)==0,p
