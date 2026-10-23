const $ = id => document.getElementById(id);
let documentId = null, manifest = null, selected = new Set(), mode = 'original', page = 1, zoom = 1;
let renderVersion = 0, documentVersion = 0, renderTimer, imageURL, focusedLayer = null;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function notice(message, error = false) { $('notice').textContent = message; $('notice').classList.toggle('error', error); }
async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) { let body; try { body = await response.json(); } catch {} throw new Error(body?.error?.message || `Request failed (${response.status}).`); }
  return response.status === 204 ? null : response.json();
}
function post(url, body) { return api(url, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) }); }
function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function guard(action) { return async (...args) => { try { await action(...args); } catch (error) { notice(error.message, true); } }; }
async function library() {
  const docs = await api('/api/documents'); $('documents').replaceChildren();
  for (const doc of docs) {
    const button = el('button', undefined, `document${doc.id === documentId ? ' active' : ''}`);
    button.append(el('span', doc.filename), el('small', `${(doc.size / 1024**2).toFixed(1)} MB · ${doc.state}`));
    button.onclick = guard(() => openDocument(doc.id)); $('documents').append(button);
  }
}
function resetView() {
  renderVersion++; clearTimeout(renderTimer); manifest = null; selected = new Set(); focusedLayer = null;
  if (imageURL) { URL.revokeObjectURL(imageURL); imageURL = null; }
  $('drawing').removeAttribute('src');
  $('drawing').hidden = true; $('empty-view').hidden = false; $('results').hidden = true;
  $('layer-list').replaceChildren(); $('layer-count').textContent = ''; $('capabilities').textContent = '';
  $('details').replaceChildren(el('h3', 'Inspect a layer'), el('p', 'Select a layer name to see its evidence, or choose Solo to isolate it.'));
  $('page').replaceChildren(); $('page').disabled = true; $('download').hidden = true;
  $('retry').hidden = true;
  ['prev','next','fit','minus','plus'].forEach(id => $(id).disabled = true);
  $('progress').hidden = true; $('view-label').textContent = 'No drawing open';
}
async function openDocument(id) {
  const version = ++documentVersion; documentId = id; resetView(); mode = 'original'; page = 1; zoom = 1;
  $('delete').disabled = false;
  try {
    await library();
    while (documentId === id && version === documentVersion) {
      const status = await api(`/api/documents/${id}/status`);
      if (version !== documentVersion) return;
      $('filename').textContent = status.filename;
      $('facts').textContent = `${(status.size / 1024**2).toFixed(2)} MB · ${status.state}`;
      $('progress').hidden = status.state === 'succeeded' || ['failed','interrupted'].includes(status.state);
      $('progress-text').textContent = `${status.stage} ${status.total ? `${status.completed} / ${status.total}` : ''}`;
      if (status.total) { $('progress').querySelector('progress').max = status.total; $('progress').querySelector('progress').value = status.completed; }
      else $('progress').querySelector('progress').removeAttribute('value');
      if (status.state === 'succeeded') {
        const result = await api(`/api/documents/${id}/analysis`); if (version !== documentVersion) return;
        manifest = result; selected = new Set(manifest.layers.filter(l => l.default_visible).map(l => l.id));
        $('facts').textContent = `${manifest.document.page_count} pages · ${manifest.layers.length} native layers · ${(status.size / 1024**2).toFixed(2)} MB · ${manifest.document.pdf_version} · ${manifest.document.annotation_count.toLocaleString()} annotations (${manifest.document.shx_annotation_count.toLocaleString()} SHX; overlays off)`;
        $('page').replaceChildren(...manifest.pages.map(p => { const option = el('option', `${p.page}${p.label && p.label !== String(p.page) ? ' / ' + p.label : ''}`); option.value = p.page; return option; }));
        ['page','prev','next','fit','minus','plus'].forEach(x => $(x).disabled = false);
        $('download').hidden = false; $('download').href = `/api/documents/${id}/analysis?download=true`; $('download').download = 'cad-analysis.json';
        $('results').hidden = false; $('json').textContent = JSON.stringify(manifest, null, 2);
        $('capabilities').textContent = !manifest.document.has_layers ? 'No native layers. This PDF remains viewable.' : manifest.capabilities.strict_solo ? 'Solo isolates one native layer. Unrelated layers and annotation overlays are excluded.' : 'Selected views retain base / conditional content. Strict solo is unavailable.';
        if (manifest.warnings.length) $('capabilities').textContent += ' ' + manifest.warnings.join(' ');
        redraw(); scheduleRender(); notice('Analysis ready. Explore layers or download the complete evidence.'); await library(); return;
      }
      if (['failed','interrupted'].includes(status.state)) { $('retry').hidden = false; notice(status.error?.message || 'Analysis interrupted. Retry analysis.', true); await library(); return; }
      notice(`${status.stage}. Your PDF is being processed locally.`); await pause(500);
    }
  } catch (error) {
    // A failed request belongs to the document opening that started it.
    if (version === documentVersion && documentId === id) throw error;
  }
}
function projectedLayers() {
  if (!manifest) return [];
  let result = manifest.layers.filter(l => (!$('current-page').checked || l.referenced_pages.includes(page)) && l.name.toLowerCase().includes($('search').value.toLowerCase()));
  return result.sort($('sort').value === 'name' ? (a,b) => a.name.localeCompare(b.name) || a.source_order-b.source_order : $('sort').value === 'amount' ? (a,b) => b.source_operations-a.source_operations || a.source_order-b.source_order : (a,b) => a.source_order-b.source_order);
}
function showDetails(layer) {
  focusedLayer = layer.id; $('details').replaceChildren(el('h3', layer.name || '(unnamed layer)'), el('p', `Object ${layer.object_reference.number}:${layer.object_reference.generation} · Originally ${layer.default_visible ? 'on' : 'off'}`), el('p', layer.explanation));
  const pair = layer.page_details.find(p => p.page === page);
  $('details').append(el('p', `Content pages: ${layer.content_pages.join(', ') || 'None'}. Source status: ${layer.source_empty === null ? 'unknown / incomplete' : layer.source_empty ? 'empty' : 'has source content'}.`));
  if (pair) $('details').append(el('p', `Page ${page} source operations: ${pair.counts.paths} path paints, ${pair.counts.text_shows} text shows, ${pair.counts.images} image placements, ${pair.counts.shadings} shadings. Bounds are not measured.`));
  $('details').append(el('p', !pair ? `No content referenced on page ${page}.` : pair.visible_output ? `Page ${page}: ${pair.visible_output.nonwhite_pixels.toLocaleString()} nonwhite pixels at 36 DPI (${pair.visible_output.width} × ${pair.visible_output.height}). This is separate from source emptiness.` : `Page ${page}: visibility measurement unavailable because strict isolation is unsupported.`));
}
function redraw() {
  if (!manifest) return;
  const layers = projectedLayers(); $('layer-count').textContent = `${layers.length} / ${manifest.layers.length}`;
  $('layer-list').replaceChildren(); $('table-body').replaceChildren();
  for (const layer of layers) {
    const object = `${layer.object_reference.number}:${layer.object_reference.generation}`;
    const row = el('div', undefined, 'layer'), checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.checked = selected.has(layer.id); checkbox.disabled = !manifest.capabilities.custom_visibility; checkbox.setAttribute('aria-label', `Show ${layer.name}, object ${object}`);
    checkbox.onchange = () => { checkbox.checked ? selected.add(layer.id) : selected.delete(layer.id); mode = 'selected'; redraw(); scheduleRender(); };
    const name = el('button', undefined, 'layer-name'); name.append(el('span', layer.name || '(unnamed layer)'), el('small', `Object ${object} · ${layer.source_operations.toLocaleString()} ops`)); name.onclick = () => showDetails(layer);
    const solo = el('button', 'Solo', 'solo'); solo.disabled = !manifest.capabilities.strict_solo; solo.setAttribute('aria-label', `Solo ${layer.name}, object ${object}`); solo.onclick = () => { selected = new Set([layer.id]); mode = 'solo'; showDetails(layer); redraw(); scheduleRender(); };
    row.append(checkbox, name, solo); $('layer-list').append(row);
    const tr = el('tr'), td = el('td'), link = el('button', layer.name || '(unnamed layer)'); link.onclick = () => showDetails(layer); td.append(link, el('small', `Object ${object} · ${layer.default_visible ? 'Originally on' : 'Originally off'}`)); tr.append(td, el('td', layer.referenced_pages.join(', ') || 'None'));
    for (const category of ['paths','text_shows','images','shadings']) tr.append(el('td', layer.counts[category].toLocaleString()));
    tr.append(el('td', layer.source_empty === null ? 'Unknown / incomplete' : layer.source_empty ? 'Empty' : 'Has source content')); $('table-body').append(tr);
  }
  if (!layers.length) $('layer-list').append(el('p', 'No matching layers on this page. Clear the search or turn off “This page”.', 'hint'));
  document.querySelectorAll('[data-mode]').forEach(button => { button.classList.toggle('active', button.dataset.mode === mode); button.disabled = button.dataset.mode !== 'original' && !manifest.capabilities.custom_visibility; });
  $('page').value = page; $('prev').disabled = page === 1; $('next').disabled = page === manifest.pages.length;
  $('zoom-label').textContent = `${Math.round(zoom*100)}%`;
  if (focusedLayer) showDetails(manifest.layers.find(l => l.id === focusedLayer));
}
function scheduleRender() {
  const version = ++renderVersion; clearTimeout(renderTimer);
  $('drawing').hidden = true;
  $('view-label').textContent = `Loading page ${page} · ${mode}…`;
  renderTimer = setTimeout(() => renderImage(version).catch(error => { if (version === renderVersion) { notice(error.message, true); $('view-label').textContent = 'Preview unavailable'; } }), 160);
}
async function renderImage(version) {
  if (!manifest) return;
  const p = manifest.pages[page-1], viewport = $('viewport');
  const fit = Math.min((viewport.clientWidth-40)/p.width, (viewport.clientHeight-40)/p.height);
  const scale = Math.max(.1, Math.min(fit*zoom*devicePixelRatio, Math.sqrt(3990000 / (p.width*p.height)), 4));
  const snapshot = { page, mode, layers: [...selected], scale, annotations: false };
  const result = await post(`/api/documents/${documentId}/renders`, snapshot);
  while (version === renderVersion) {
    const response = await fetch(result.url);
    if (version !== renderVersion) return;
    if (response.status === 202) { await pause(180); continue; }
    if (!response.ok) { const body = await response.json(); throw new Error(body.error?.message || 'Preview failed.'); }
    const blob = await response.blob(); if (version !== renderVersion) return;
    const url = URL.createObjectURL(blob), image = new Image(); image.src = url; await image.decode();
    if (version !== renderVersion) { URL.revokeObjectURL(url); return; }
    if (imageURL) URL.revokeObjectURL(imageURL); imageURL = url;
    $('drawing').src = url; $('drawing').alt = `Page ${snapshot.page}, ${snapshot.mode} view, ${snapshot.layers.length} selected layers; annotation overlays off`;
    $('drawing').style.width = `${p.width*fit*zoom}px`; $('drawing').style.height = `${p.height*fit*zoom}px`; $('drawing').hidden = false; $('empty-view').hidden = true;
    $('view-label').textContent = `Page ${snapshot.page} of ${manifest.pages.length} · ${snapshot.mode === 'solo' ? 'Strict solo' : snapshot.mode === 'selected' ? `Selected (${snapshot.layers.length})${manifest.capabilities.base_content_present ? ' with base content' : ''}` : snapshot.mode}`;
    return;
  }
}
$('upload').onchange = guard(async event => {
  const file = event.target.files[0]; if (!file) return;
  notice('Uploading locally…'); const data = new FormData(); data.append('file', file);
  // XMLHttpRequest exposes actual upload progress, while analysis is polled separately.
  const result = await new Promise((resolve, reject) => { const xhr = new XMLHttpRequest(); xhr.open('POST','/api/documents'); xhr.upload.onprogress = e => { if (e.lengthComputable) notice(`Uploading locally… ${Math.round(e.loaded/e.total*100)}%`); }; xhr.onerror = () => reject(new Error('Upload failed. Check the local server.')); xhr.onload = () => { let body; try {body = JSON.parse(xhr.responseText);} catch {reject(new Error('Upload failed.'));return;} xhr.status < 300 ? resolve(body) : reject(new Error(body.error?.message || 'Upload failed.')); }; xhr.send(data); });
  event.target.value = ''; await openDocument(result.id);
});
$('page').onchange = () => { page = Number($('page').value); redraw(); scheduleRender(); };
$('prev').onclick = () => { if (page>1) {page--; redraw(); scheduleRender();} };
$('next').onclick = () => { if (manifest && page<manifest.pages.length) {page++; redraw(); scheduleRender();} };
for (const id of ['search','current-page','sort']) $(id).addEventListener(id === 'search' ? 'input' : 'change', redraw);
document.querySelectorAll('[data-mode]').forEach(button => button.onclick = () => { if (!manifest) return; mode = button.dataset.mode; if (mode === 'all-on') selected = new Set(manifest.layers.map(l => l.id)); if (mode === 'all-off') selected.clear(); if (mode === 'original') selected = new Set(manifest.layers.filter(l => l.default_visible).map(l => l.id)); redraw(); scheduleRender(); });
$('fit').onclick = () => {zoom=1; redraw(); scheduleRender();}; $('plus').onclick = () => {zoom=Math.min(4,zoom+.5); redraw(); scheduleRender();}; $('minus').onclick = () => {zoom=Math.max(.5,zoom-.5); redraw(); scheduleRender();};
for (const tab of ['table','json']) $(`${tab}-tab`).onclick = () => { $('table-wrap').hidden = tab !== 'table'; $('json').hidden = tab !== 'json'; $('table-tab').setAttribute('aria-selected', tab === 'table'); $('json-tab').setAttribute('aria-selected',tab === 'json'); };
$('retry').onclick = guard(async () => { await post(`/api/documents/${documentId}/analysis`, {}); await openDocument(documentId); });
$('delete').onclick = () => $('confirm-delete').showModal(); $('cancel-delete').onclick = () => $('confirm-delete').close();
$('confirm-delete-button').onclick = guard(async () => { const id=documentId; $('confirm-delete').close(); await api(`/api/documents/${id}`, {method:'DELETE'}); if(documentId === id) {documentId=null; documentVersion++; resetView(); $('delete').disabled=true; $('filename').textContent='A clearer view of every layer.'; $('facts').textContent='Open a PDF to begin.';} await library(); notice('Drawing and its retained analysis and previews deleted.'); });
let drag;
$('viewport').addEventListener('pointerdown', e => { if(e.button!==0)return; drag={x:e.clientX,y:e.clientY,left:e.currentTarget.scrollLeft,top:e.currentTarget.scrollTop}; e.currentTarget.setPointerCapture(e.pointerId); e.currentTarget.classList.add('dragging'); });
$('viewport').addEventListener('pointermove',e=>{if(drag){e.currentTarget.scrollLeft=drag.left+drag.x-e.clientX;e.currentTarget.scrollTop=drag.top+drag.y-e.clientY;}});
$('viewport').addEventListener('pointerup',()=>{drag=null;$('viewport').classList.remove('dragging');});
let resizeTimer; window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(manifest)scheduleRender();},300);});
guard(library)();
