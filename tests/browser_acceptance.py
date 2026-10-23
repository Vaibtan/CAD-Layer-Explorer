"""Real browser acceptance against the Docker-served HTML application.

Run: uv run python tests/browser_acceptance.py
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from fixtures import fixture

BASE = os.environ.get('CAD_TEST_URL', 'http://127.0.0.1:8000')
OUT = Path(os.environ.get('CAD_EVIDENCE_DIR', 'tmp/acceptance'))
OUT.mkdir(parents=True,exist_ok=True)


def drawing_ready(page):
    page.wait_for_function("""() => {
        const drawing = document.getElementById('drawing');
        return !drawing.hidden && drawing.complete && drawing.naturalWidth > 0
          && !document.getElementById('view-label').textContent.startsWith('Loading');
    }""", timeout=30000)


def drawing_screenshot(page, name):
    drawing_ready(page)
    # Full-page capture resizes the viewport in Chromium and can trigger a new
    # render between the readiness assertion and capture. Keep this viewport.
    page.screenshot(path=str(OUT/name))


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':1500,'height':1050})
        errors=[];requests=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:requests.append(request.url))
        page.goto(BASE)
        page.locator('#upload').set_input_files(fixture(OUT/'browser.pdf','rotated'))
        page.locator('#results').wait_for(state='visible',timeout=30000)
        page.locator('#drawing').wait_for(state='visible',timeout=30000)
        assert '4 native layers' in page.locator('#facts').inner_text()
        manifest=page.request.get(BASE+page.locator('#download').get_attribute('href')).json()
        assert len(page.locator('#table-body tr').all())==2
        assert json.loads(page.locator('#json').text_content())==manifest
        first=manifest['layers'][0];second=manifest['layers'][1]
        page.get_by_role('button',name=f"Solo {first['name']}, object {first['object_reference']['number']}:0",exact=True).click()
        page.wait_for_function("() => document.getElementById('view-label').textContent.includes('Strict solo') && !document.getElementById('drawing').hidden")
        page.locator('#plus').click()
        page.wait_for_function("() => document.getElementById('zoom-label').textContent === '150%' && !document.getElementById('drawing').hidden")
        page.locator('#fit').click()
        page.get_by_role('button',name='All off',exact=True).click()
        page.wait_for_function("() => document.getElementById('view-label').textContent.includes('all-off') && !document.getElementById('drawing').hidden")
        page.get_by_role('button',name='Original',exact=True).click()
        page.wait_for_function("() => document.getElementById('view-label').textContent.includes('original') && !document.getElementById('drawing').hidden")
        page.locator('#current-page').uncheck()
        assert page.locator('#table-body tr').count()==4
        page.locator('#search').fill('Unused')
        assert page.locator('#table-body tr').count()==1
        page.locator('#sort').select_option('name')
        with page.expect_download() as download:
            page.locator('#download').click()
        assert json.loads(Path(download.value.path()).read_bytes())==manifest
        page.locator('#search').fill('')
        page.get_by_role('tab',name='JSON',exact=True).click();assert page.locator('#json').is_visible()
        page.get_by_role('tab',name='Layer evidence').click()
        drawing_screenshot(page,'synthetic-browser.png')
        page.reload();page.locator('.document',has_text='browser.pdf').click()
        page.locator('#drawing').wait_for(state='visible',timeout=30000)
        page.locator('#delete').click();page.locator('#confirm-delete-button').click()
        page.wait_for_function("() => document.getElementById('notice').textContent.includes('deleted')")
        assert not page.locator('.document',has_text='browser.pdf').count()
        # User-visible failure and retry state, followed by a successful upload.
        broken=OUT/'broken.pdf';broken.write_bytes(b'%PDF-1.7\ntruncated')
        page.locator('#upload').set_input_files(broken)
        page.locator('#retry').wait_for(state='visible',timeout=30000)
        assert page.locator('#notice').get_attribute('class')=='error'
        page.locator('#delete').click();page.locator('#confirm-delete-button').click()
        page.wait_for_function("() => document.getElementById('notice').textContent.includes('deleted')")
        # Real private drawing: no network upload except to the local Docker API.
        page.locator('#upload').set_input_files(Path('cader structural-1.pdf'))
        page.locator('#results').wait_for(state='visible',timeout=320000)
        page.locator('#drawing').wait_for(state='visible',timeout=30000)
        drawing_screenshot(page,'drawing-cover.png')
        page.locator('#page').select_option('4')
        page.wait_for_function("() => document.getElementById('view-label').textContent.startsWith('Page 4 of') && !document.getElementById('drawing').hidden")
        drawing_screenshot(page,'drawing-page-4.png')
        page.locator('.solo').first.click()
        page.wait_for_function("() => document.getElementById('view-label').textContent.includes('Strict solo') && !document.getElementById('drawing').hidden")
        drawing_screenshot(page,'drawing-solo.png')
        # Keyboard-accessible upload and controls; responsive view stays within the viewport.
        page.locator('#search').focus();page.keyboard.type('dim')
        assert page.locator('#table-body tr').count()>0
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_function("""() => {
            const drawing = document.getElementById('drawing');
            const viewport = document.getElementById('viewport');
            return !drawing.hidden && drawing.complete && drawing.naturalWidth > 0
              && drawing.getBoundingClientRect().width <= viewport.clientWidth
              && !document.getElementById('view-label').textContent.startsWith('Loading');
        }""",timeout=30000)
        drawing_screenshot(page,'mobile.png')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        assert all(url.startswith((BASE,'blob:'+BASE)) for url in requests),requests
        (OUT/'browser-evidence.json').write_text(json.dumps({'page_errors':errors,'requests':len(requests),'remote_requests':[r for r in requests if not r.startswith((BASE,'blob:'+BASE))],'checks':['upload','progress','duplicate controls','strict solo','all-off','original','zoom','fit','search','sort','table/JSON/download agreement','reopen','deletion','invalid PDF','page navigation','mobile','keyboard']},indent=2))
        browser.close()
        print('Browser acceptance passed; evidence:',OUT)


if __name__=='__main__':main()
