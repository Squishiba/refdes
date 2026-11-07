// The editor's Navis panel (design §11, slices N5d-1 + N5d-2): a fixed
// toggle at the top-right of the viewport, a panel of the active rows, and
// a Show-all disclosure like the published site's panel. The data is the
// one served read -- GET /api/navis, the site panel's rows through the
// shared api helper -- and the refresh rides the shell's ONE project-change
// signal: app.js's poller fires `refdes:rebuilt` when the served serial
// moves (a save lands in the same signal on the next poll), and the panel
// re-fetches on it and on every open. No second poller.
//
// N5d-2: keyed active rows gain Archive, archived rows in Show-all gain
// Restore -- the preview panel's actions (navis-preview.js, N5c) over the
// same routes (POST /api/navis/archive|restore) with the same rules, in
// this module's own words: the rows are built here, so the data is in hand
// and each button closes over its own row (no positional DOM mapping), and
// a 200 re-fetches through refresh() and keeps the panel open -- this is
// the SPA, the page never reloads. A non-200 re-enables the clicked button
// and shows the server's `error` in one textContent-only paragraph; a 403
// (--no-write) disables every action button and keeps the message.
//
// Marker text and server error text are untrusted: every node here is
// createElement/textContent, so a hostile string stays literal.

import { api as sharedApi } from './api.js';
import { el } from './dom.js';

const CHANGED_NOTE = 'marker text has changed since archived';
const ORPHAN_TITLE = 'Marker not found -- hand-restore the marker, then it re-links by key';
const MINT_TITLE = 'Writes a key into each unkeyed Navi marker in your item files';
const KEYLESS_TITLE = 'No key yet -- use Mint keys';
const DRAFT_SENTENCE =
  'Item files were edited: an open unsaved draft will ask you to resolve a conflict when you Save.';

function rowNode(row, wire, withArchive) {
  // wire: {act(button, path, key), registry, locked()}, the mount's action
  // plumbing; withArchive marks the top active list (Archive lives in ONE
  // place -- Show-all repeats the active rows and never grows a second
  // button). A locked session (--no-write, set after the first 403) builds
  // every action button disabled, so the lockout survives redraws.
  const li = el('li', 'navis-row');
  const key = el('span', 'navis-key mono', row.key6);
  if (!row.key) key.setAttribute('title', KEYLESS_TITLE); // discoverable reason
  li.appendChild(key);
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
    if (row.key) {
      // a keyless row has nothing the API can address: no button at all
      const restore = el('button', 'navis-restore', 'Restore');
      restore.type = 'button';
      restore.setAttribute('aria-label', `Restore Navi ${row.key6}`);
      if (row.orphan) {
        // §9 row 3: no marker to reactivate -- the server refuses, so say
        // so where the click would have been
        restore.disabled = true;
        restore.setAttribute('title', ORPHAN_TITLE);
      } else {
        restore.setAttribute('title', 'Restore this Navi');
        restore.disabled = wire.locked();
        if (wire) {
          wire.registry.push(restore);
          restore.addEventListener('click', () => wire.act(restore, '/api/navis/restore', row.key));
        }
      }
      li.appendChild(restore);
    }
  } else if (withArchive && wire && row.key) {
    const button = el('button', 'navis-archive', 'Archive');
    button.type = 'button';
    button.setAttribute('aria-label', `Archive Navi ${row.key6}`);
    button.disabled = wire.locked();
    wire.registry.push(button);
    button.addEventListener('click', () => wire.act(button, '/api/navis/archive', row.key));
    li.appendChild(button);
  }
  return li;
}

function render(panel, payload, wire) {
  panel.textContent = '';
  const keyless = payload.navis.filter((row) => !row.key).length;
  const nodes = [];
  if (keyless > 0 && wire) {
    // the mint is project-wide, so it is ONE button for the whole panel,
    // counted from the rows already in hand (a keyless row is `key: ''`).
    const mint = el('button', 'navis-mint', `Mint keys (${keyless})`);
    mint.type = 'button';
    mint.setAttribute('aria-label', `Mint keys for ${keyless} unkeyed Navis`);
    mint.setAttribute('title', MINT_TITLE);
    mint.disabled = wire.locked();
    wire.registry.push(mint);
    mint.addEventListener('click', () => wire.mint(mint));
    nodes.push(mint);
  }
  const active = payload.navis.filter((row) => !row.archived);
  if (active.length) {
    const list = el('ul', 'navis-list');
    for (const row of active) list.appendChild(rowNode(row, wire, true));
    nodes.push(list);
  } else {
    nodes.push(el('p', 'navis-empty', 'No active Navis.'));
  }
  const archived = payload.navis.filter((row) => row.archived);
  if (archived.length) {
    // Show-all lists every row, the site panel's shape: active rows again
    // (no Archive button here), archived rows tagged with the snapshot text
    // the API returns, Restore wired on the keyed ones.
    const details = el('details', 'navis-all');
    details.appendChild(el('summary', 'navis-all-summary', `Show all (${payload.navis.length})`));
    const list = el('ul', 'navis-list');
    for (const row of payload.navis) list.appendChild(rowNode(row, wire, false));
    details.appendChild(list);
    nodes.push(details);
  }
  for (const node of nodes) panel.appendChild(node);
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
  let notice = null; // the one inline alert; render() detaches it, draw() re-adds it
  let noticeShown = false;
  let status = null; // the one status line a mint leaves; rides draw() like the alert
  let statusShown = false;
  let locked = false; // a 403 (--no-write) ends this session's writes for good
  const registry = []; // this render's action buttons, for the 403 lockout
  const wire = { act, mint, registry, locked: () => locked };

  function label() {
    toggle.textContent = `Navis (${data ? data.counts.active : 0})`;
  }

  function draw() {
    // render() clears the panel, so the alert and last render's buttons are
    // gone from the DOM. The alert outlives redraws (a refresh landing after
    // a failed action must not erase the reason it failed); the registry is
    // rebuilt by render, and a locked session builds its buttons disabled.
    registry.length = 0;
    if (data) render(panel, data, wire);
    else if (failed) panel.textContent = 'Navis unavailable';
    if (statusShown && status) panel.insertBefore(status, panel.firstChild);
    if (noticeShown && notice) panel.insertBefore(notice, panel.firstChild);
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

  function showError(text) {
    if (!notice) {
      notice = el('p', 'navis-error');
      notice.setAttribute('role', 'alert');
    }
    notice.textContent = text;
    if (!noticeShown) {
      if (panel.firstChild) panel.insertBefore(notice, panel.firstChild);
      else panel.appendChild(notice);
      noticeShown = true;
    }
  }

  function clearError() {
    if (notice && notice.parentNode) notice.parentNode.removeChild(notice);
    notice = null;
    noticeShown = false;
  }

  function showStatus(text) {
    if (!status) {
      status = el('p', 'navis-note');
      status.setAttribute('role', 'status');
    }
    status.textContent = text;
    if (!statusShown) {
      if (panel.firstChild) panel.insertBefore(status, panel.firstChild);
      else panel.appendChild(status);
      statusShown = true;
    }
  }

  function clearStatus() {
    if (status && status.parentNode) status.parentNode.removeChild(status);
    status = null;
    statusShown = false;
  }

  function mint(button) {
    button.disabled = true;
    apiFn('/api/navis/mint', { method: 'POST', body: {} })
      .then((res) => {
        // the mint is an in-place edit of item files with a forced rebuild
        // before the answer, so the panel's own re-fetch lands keyed; the
        // page never reloads and an open editor draft outlives it (ED-1).
        clearError();
        const minted = (res && res.minted && res.minted.length) || 0;
        const refused = (res && res.still_keyless) || 0;
        const parts = [];
        if (minted > 0) parts.push(`Minted ${minted} key(s).`);
        if (refused > 0) {
          parts.push(
            `${refused} marker(s) could not be keyed -- refdes will not mint into those ` +
              'bodies (for example a YAML list body).'
          );
        }
        if (minted === 0 && refused === 0) parts.push('Nothing to mint.');
        if (minted > 0) parts.push(DRAFT_SENTENCE);
        showStatus(parts.join(' '));
        refresh();
      })
      .catch((err) => {
        button.disabled = false;
        showError(
          (err && err.payload && err.payload.error)
            || (err && err.message)
            || 'the request failed'
        );
        if (err && err.status === 403) {
          locked = true;
          for (const b of registry) b.disabled = true;
        }
      });
  }

  function act(button, path, key) {
    clearStatus(); // a fresh action supersedes the mint's status line
    button.disabled = true;
    apiFn(path, { method: 'POST', body: { navi: key } })
      .then(() => {
        // the server rebuilt synchronously before answering (navis_write's
        // forced refresh), so the panel's own re-fetch lands on the rows
        // that include this action; the panel stays open, the page never
        // reloads -- an open item editor's unsaved draft outlives it
        clearError(); // the last failure's message is stale now
        refresh();
      })
      .catch((err) => {
        button.disabled = false;
        showError(
          (err && err.payload && err.payload.error)
            || (err && err.message)
            || 'the request failed'
        );
        // A --no-write server refuses every write the same way: re-arming
        // the buttons would only invite the same 403 back. The flag lives
        // on the mount, so the buttons a later refresh draws are disabled
        // too -- the lockout is the session's, not one render's.
        if (err && err.status === 403) {
          locked = true;
          for (const b of registry) b.disabled = true;
        }
      });
  }

  function setOpen(next) {
    open = next;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    if (open) {
      draw(); // last good rows first (re-adding any alert), then the open's own fetch
      refresh();
    } else {
      clearError(); // a reopened panel starts clean
      clearStatus();
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
