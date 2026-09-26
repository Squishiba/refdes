// The item view: fields, body, links both directions, coverage, checks, and
// diagnostics — everything rendered from what /api/item/<ref> returns. The
// client interprets nothing: no field is hidden or reordered by a guess about
// the schema, and editability comes from the server's `edit` block, not from a
// name the script recognises. Editable scalars get a control, the body gets a
// textarea, and everything read-only says why (editor.js owns the draft).
// Alongside, the real rendered preview page in an iframe.

import { api } from './api.js';
import { createEditor } from './editor.js';
import { captureFocus, collectControls, restoreFocus } from './update.js';

const STAGES = ['open', 'addressed', 'claimed', 'satisfied', 'verified'];

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function section(title) {
  const s = el('section', 'detail-block');
  s.appendChild(el('h2', null, title));
  return s;
}

function fieldTable(item, editor, controls) {
  const table = el('table', 'fields');
  const editInfo = (item.edit && item.edit.fields) || {};
  for (const [name, value] of Object.entries(item.fields || {})) {
    const tr = el('tr');
    const th = el('th');
    th.textContent = name;
    if (item.inherited_fields.includes(name)) {
      th.appendChild(el('span', 'badge inherited', 'inherited'));
    }
    tr.appendChild(th);
    const td = el('td');
    // A control for a field that existed in the previous render is carried
    // over and updated in place (editor.js), not rebuilt: that is what keeps
    // focus and the caret alive across a revision-triggered re-render.
    const control = editor && editor.fieldControl(name, value, controls && controls.get(`field:${name}`));
    if (control) {
      td.appendChild(control);
    } else {
      td.textContent = Array.isArray(value) ? value.join(', ') : String(value ?? '');
      const info = editInfo[name];
      if (info && !info.editable) td.appendChild(el('span', 'badge readonly', info.reason));
      else td.appendChild(el('span', 'badge readonly', 'read only'));
    }
    tr.appendChild(td);
    table.appendChild(tr);
  }
  return table;
}

function linkList(links) {
  const wrap = el('div', 'links');
  const verbs = Object.entries(links || {});
  if (!verbs.length) return Object.assign(wrap, { textContent: 'none' });
  for (const [verb, targets] of verbs) {
    const line = el('div', 'link-line');
    line.appendChild(el('span', 'link-verb', verb));
    line.appendChild(el('span', null, targets.join(', ')));
    wrap.appendChild(line);
  }
  return wrap;
}

function coverageBlock(coverage) {
  const block = section('Coverage');
  if (!coverage) {
    block.appendChild(el('p', 'muted', 'This item is not coverable.'));
    return block;
  }
  const strip = el('div', 'stage-strip');
  STAGES.forEach((stage) => {
    const chip = el('span', `stage-chip stage-${stage}` + (coverage.stage === stage ? ' active' : ''), stage);
    strip.appendChild(chip);
  });
  block.appendChild(strip);
  for (const key of ['addressed_by', 'claimed_by', 'satisfied_by', 'verified_by']) {
    if (coverage[key] && coverage[key].length) {
      const line = el('div', 'coverage-line');
      line.appendChild(el('span', 'link-verb', key));
      line.appendChild(el('span', null, coverage[key].join(', ')));
      block.appendChild(line);
    }
  }
  return block;
}

function diagnosticsBlock(diagnostics) {
  const block = section('Diagnostics');
  if (!diagnostics.length) {
    block.appendChild(el('p', 'muted', 'No diagnostics attributed to this item.'));
    return block;
  }
  const list = el('ul', 'diagnostics');
  for (const d of diagnostics) {
    const li = el('li', `diag diag-${d.level}`);
    li.textContent = `${d.level.toUpperCase()} ${d.message}${d.file ? ` (${d.file}${d.line ? ':' + d.line : ''})` : ''}`;
    list.appendChild(li);
  }
  block.appendChild(list);
  return block;
}

function checksBlock(checks) {
  const block = section('Checks');
  if (!checks.length) {
    block.appendChild(el('p', 'muted', 'This item declares no checks.'));
    return block;
  }
  const list = el('ul', 'checks');
  for (const c of checks) {
    const verdict = c.ok === true ? 'pass' : c.ok === false ? 'fail' : 'unknown';
    const li = el('li', `check check-${verdict}`);
    li.textContent = `${c.value_name} vs ${c.against}: ${verdict}${c.actual ? ` (actual ${c.actual})` : ''}${c.detail ? ` — ${c.detail}` : ''}`;
    list.appendChild(li);
  }
  block.appendChild(list);
  return block;
}

export async function renderItem(container, handle) {
  // A revision-triggered re-render of the item already on screen keeps the
  // old view up while the fresh one is fetched (keystrokes during the fetch
  // still land in the draft), then rebuilds with the old controls carried
  // over: focus and the caret are captured just before the swap and restored
  // into the same logical field afterwards (update.js). A first render, or a
  // different item, still shows the loading line.
  if (container.dataset.renderedHandle !== handle || !container.firstChild) {
    container.textContent = '';
    container.appendChild(el('p', 'muted', 'Loading item…'));
  }
  let item;
  try {
    item = await api(`/api/item/${encodeURIComponent(handle)}`);
  } catch (err) {
    container.textContent = '';
    container.dataset.renderedHandle = '';
    container.appendChild(el('p', 'banner bad', `Could not load the item: ${err.message}`));
    return;
  }
  const focus = captureFocus(container);
  const controls = collectControls(container);
  container.textContent = '';

  const head = section(`${item.id || item.handle} — ${item.title}`);
  const meta = el('div', 'item-meta');
  const add = (text, kind) => { if (text) meta.appendChild(Object.assign(el('span', `badge ${kind || ''}`.trim()), { textContent: text })); };
  add(item.type);
  add(item.board, 'board');
  add(item.workspace, 'board');
  if (item.external) add(`imported${item.origin ? ` from ${item.origin}` : ''}`, 'muted-badge');
  if (item.sealed) add('sealed — read only', 'bad');
  else if (item.append_only) add('append-only, not yet sealed', 'warn');
  head.appendChild(meta);
  head.appendChild(el('p', 'muted', `${item.source_file}:${item.source_line}`));
  if (item.sealed && item.append_only && item.id) {
    // "Amend this sealed log": the correction is a NEW entry carrying an
    // amends: composite; the sealed entry's bytes are never touched.
    const amend = el('a', 'btn amend-log', 'Amend this sealed log');
    amend.href = `#/new?type=${encodeURIComponent(item.type)}&amends=${encodeURIComponent(item.id)}`;
    head.appendChild(amend);
  }
  container.appendChild(head);

  const rerender = () => renderItem(container, handle);
  const editor = createEditor(item, handle, rerender, rerender);

  container.appendChild(fieldTable(item, editor, controls));

  const body = section('Body');
  const bodyArea = editor.bodyControl(item.body, controls.get('body'));
  if (bodyArea) {
    body.appendChild(bodyArea);
    // The image picker inserts into that textarea, so it belongs beside it
    // rather than in the Edit block below (editor.js builds it; the draft it
    // writes is the same one a field edit uses).
    if (editor.imagePicker) body.appendChild(editor.imagePicker);
  } else {
    body.appendChild(el('pre', 'body-text', item.body || '(empty)'));
    const info = item.edit && item.edit.body;
    if (info && !info.editable) body.appendChild(el('p', 'badge readonly', info.reason));
  }
  container.appendChild(body);
  container.appendChild(editor.node);

  const links = section('Links');
  links.appendChild(el('h3', null, 'Outgoing'));
  links.appendChild(linkList(item.links.outgoing));
  links.appendChild(el('h3', null, 'Incoming'));
  links.appendChild(linkList(item.links.incoming));
  container.appendChild(links);

  container.appendChild(coverageBlock(item.coverage));
  container.appendChild(checksBlock(item.checks));
  container.appendChild(diagnosticsBlock(item.diagnostics));

  const preview = section('Rendered preview');
  // W1 of the thread workbench: the item's own preview page, opened beside
  // the editor (a new tab, the same convention as the shell's "Rendered
  // site" nav link). It reloads itself on rebuild (preview.js).
  const open = el('a', 'btn open-preview', 'Open preview');
  open.href = `/preview/${encodeURIComponent(item.page)}`;
  open.target = '_blank';
  open.rel = 'noopener';
  preview.appendChild(open);
  const frame = el('iframe', 'preview-frame');
  frame.src = `/preview/${encodeURIComponent(item.page)}`;
  frame.setAttribute('title', 'Rendered preview of this item');
  preview.appendChild(frame);
  container.appendChild(preview);

  container.dataset.renderedHandle = handle;
  restoreFocus(container, focus);
}
