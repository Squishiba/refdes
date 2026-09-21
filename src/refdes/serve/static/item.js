// The read-only item view: fields, body, links both directions, coverage,
// checks, and diagnostics — everything rendered from what /api/item/<ref>
// returns. The client interprets nothing: no field is hidden or reordered by
// a guess about the schema, and there are no editing controls (that is
// Slice 1 chunk 3). Alongside, the real rendered preview page in an iframe.

import { api } from './api.js';

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

function fieldTable(fields, inherited) {
  const table = el('table', 'fields');
  for (const [name, value] of Object.entries(fields || {})) {
    const tr = el('tr');
    const th = el('th');
    th.textContent = name;
    if (inherited && inherited.includes(name)) {
      th.appendChild(el('span', 'badge inherited', 'inherited'));
    }
    tr.appendChild(th);
    const td = el('td');
    td.textContent = Array.isArray(value) ? value.join(', ') : String(value ?? '');
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
  container.textContent = '';
  container.appendChild(el('p', 'muted', 'Loading item…'));
  let item;
  try {
    item = await api(`/api/item/${encodeURIComponent(handle)}`);
  } catch (err) {
    container.textContent = '';
    container.appendChild(el('p', 'banner bad', `Could not load the item: ${err.message}`));
    return;
  }
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
  container.appendChild(head);

  container.appendChild(fieldTable(item.fields, item.inherited_fields));

  const body = section('Body');
  body.appendChild(el('pre', 'body-text', item.body || '(empty)'));
  container.appendChild(body);

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
  const frame = el('iframe', 'preview-frame');
  frame.src = `/preview/${encodeURIComponent(item.page)}`;
  frame.setAttribute('title', 'Rendered preview of this item');
  preview.appendChild(frame);
  container.appendChild(preview);
}
