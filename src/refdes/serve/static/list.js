// The item list pane. Rows come straight from /api/items — the built
// project, never a client-side guess — and each row links to the item view
// while keeping the current filter query in the URL.

import { filterQuery } from './filters.js';

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function badge(text, kind) {
  return el('span', `badge ${kind || ''}`.trim(), text);
}

function row(item, filters) {
  const li = el('li', 'item-row');
  const link = el('a', 'item-link');
  link.href = `#/items/${encodeURIComponent(item.handle)}${filterQuery(filters)}`;

  const head = el('div', 'item-head');
  head.appendChild(el('span', 'item-id', item.id || item.handle));
  head.appendChild(el('span', 'item-type', item.type));
  if (item.board) head.appendChild(badge(item.board, 'board'));
  if (item.workspace) head.appendChild(badge(item.workspace, 'board'));
  if (item.external) head.appendChild(badge('imported', 'muted-badge'));
  if (item.blocked) head.appendChild(badge('blocked', 'bad'));
  li.appendChild(head);

  li.appendChild(el('div', 'item-title', item.title));

  const meta = el('div', 'item-meta');
  if (item.stage) meta.appendChild(badge(item.stage, `stage-${item.stage}`));
  if (item.check !== 'none') meta.appendChild(badge(`check: ${item.check}`, item.check === 'fail' ? 'bad' : item.check === 'pass' ? 'ok' : 'warn'));
  meta.appendChild(el('span', 'muted', `${item.source_file}:${item.source_line}`));
  li.appendChild(meta);
  return li;
}

export function renderList(container, payload, filters) {
  container.textContent = '';
  const head = el('div', 'list-head');
  head.appendChild(el('strong', null, `${payload.total} item${payload.total === 1 ? '' : 's'}`));
  if (payload.total > payload.items.length) {
    head.appendChild(el('span', 'muted', ` showing first ${payload.items.length}`));
  }
  container.appendChild(head);

  const list = el('ul', 'item-list');
  for (const item of payload.items) list.appendChild(row(item, filters));
  container.appendChild(list);
  if (!payload.items.length) container.appendChild(el('p', 'muted', 'No items match these filters.'));
}
