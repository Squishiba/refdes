// The editor's read-only Navis panel (design §11, slice N5d-1): a fixed
// toggle at the top-right of the viewport, a panel of the active rows, and
// a Show-all disclosure like the published site's panel. The data is the
// one served read -- GET /api/navis, the site panel's rows through the
// shared api helper -- and the refresh rides the shell's ONE project-change
// signal: app.js's poller fires `refdes:rebuilt` when the served serial
// moves (a save lands in the same signal on the next poll), and the panel
// re-fetches on it and on every open. No archive/restore actions here
// (N5d-2's slice); no second poller.
//
// Marker text is untrusted: every node here is createElement/textContent.

import { api as sharedApi } from './api.js';

const CHANGED_NOTE = 'marker text has changed since archived';

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function rowNode(row) {
  const li = el('li', 'navis-row');
  li.appendChild(el('span', 'navis-key mono', row.key6));
  if (row.item) {
    // the item's editor route, spelled the way the shell's router reads it
    const link = el('a', 'navis-item', row.item);
    link.href = `#/items/${encodeURIComponent(row.item)}`;
    li.appendChild(link);
  }
  if (row.orphan) li.appendChild(el('span', 'navis-note', `marker not found (${row.file})`));
  li.appendChild(el('span', 'navis-text', row.text));
  if (row.archived) {
    li.appendChild(el('span', 'navis-tag', '[archived]'));
    if (row.changed) li.appendChild(el('span', 'navis-note', CHANGED_NOTE));
  }
  return li;
}

function render(panel, payload) {
  panel.textContent = '';
  const active = payload.navis.filter((row) => !row.archived);
  if (active.length) {
    const list = el('ul', 'navis-list');
    for (const row of active) list.appendChild(rowNode(row));
    panel.appendChild(list);
  } else {
    panel.appendChild(el('p', 'navis-empty', 'No active Navis.'));
  }
  const archived = payload.navis.filter((row) => row.archived);
  if (archived.length) {
    // Show-all lists every row, the site panel's shape: active rows again,
    // archived rows tagged with the snapshot text the API returns.
    const details = el('details', 'navis-all');
    details.appendChild(el('summary', 'navis-all-summary', `Show all (${payload.navis.length})`));
    const list = el('ul', 'navis-list');
    for (const row of payload.navis) list.appendChild(rowNode(row));
    details.appendChild(list);
    panel.appendChild(details);
  }
}

export function mountNavisPanel(root, apiFn = sharedApi) {
  const toggle = el('button', 'navis-toggle');
  toggle.type = 'button';
  toggle.setAttribute('aria-expanded', 'false');
  const panel = el('div', 'navis-panel');
  panel.hidden = true;
  let data = null; // the last good payload; a failed fetch keeps it
  let failed = false;
  let open = false;

  function label() {
    toggle.textContent = `Navis (${data ? data.counts.active : 0})`;
  }

  function draw() {
    if (data) render(panel, data);
    else if (failed) panel.textContent = 'Navis unavailable';
  }

  async function refresh() {
    try {
      data = await apiFn('/api/navis');
      failed = false;
    } catch (_) {
      failed = true; // keep the last good rows; no error spam in the panel
      return;
    }
    label();
    draw();
  }

  function setOpen(next) {
    open = next;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    if (open) {
      draw(); // last good rows first, then the open's own fetch
      refresh();
    }
  }

  toggle.addEventListener('click', () => setOpen(!open));
  window.addEventListener('keydown', (event) => {
    if (open && event.key === 'Escape') {
      setOpen(false);
      toggle.focus();
    }
  });
  window.addEventListener('refdes:rebuilt', () => refresh());

  label();
  refresh();
  root.appendChild(toggle);
  root.appendChild(panel);
}
