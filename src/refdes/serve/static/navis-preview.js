// N5c: the Navis panel on a SERVED preview page gains Archive/Restore
// actions (docs/design/editor-vscode-adapter.md §11: the editor is a client
// of the panel's projection, never a second implementation). The published
// page stays exactly as published -- the read-only panel with its disabled
// restore is the floor; this module, loaded only by preview.js, upgrades
// that floor over the serve API (GET /api/navis, POST /api/navis/archive and
// /api/navis/restore) through the one api() transport.
//
// The row model is POSITIONAL, never textual: the list markup carries only
// the 6-char key, so a marker text is not an identity and the panel rows
// must line up with the API rows by index (active list = the non-archived
// rows in API order, Show-all = every row in API order). Counts that
// disagree mean the page is stale; preview.js's serial poll reloads it, so
// wiring stops here without touching anything.
//
// Marker text is untrusted input, so every string this module renders goes
// through textContent/setAttribute -- there is no innerHTML anywhere, and a
// hostile marker stays literal.

import { api } from './api.js';

const ORPHAN_TITLE = 'Marker not found -- hand-restore the marker, then it re-links by key';

export async function wireNavisPanel(doc = document, apiFn = api) {
  const panel = doc.querySelector('details.refdes-navis');
  if (!panel) return;
  let payload;
  try {
    payload = await apiFn('/api/navis');
  } catch (err) {
    return; // no API, no actions: the panel stays exactly as published
  }
  const rows = payload && payload.navis;
  if (!Array.isArray(rows)) return;
  const active = rows.filter((row) => !row.archived);

  const showAll = panel.querySelector('#refdes-navis-all');
  const inAll = (node) => {
    for (let p = node; p; p = p.parentNode) if (p === showAll) return true;
    return false;
  };
  const lists = Array.from(panel.querySelectorAll('ul.refdes-navis-list'));
  const topUl = lists.find((ul) => !inAll(ul)) || null;
  const allUl = showAll ? lists.find(inAll) : null;
  const topLis = topUl ? topUl.querySelectorAll('li') : [];
  const allLis = allUl ? allUl.querySelectorAll('li') : [];
  if (topLis.length !== active.length) return;
  if (showAll) {
    if (!allUl || allLis.length !== rows.length) return;
  } else if (rows.length !== active.length) {
    return;
  }

  let notice = null;
  const showError = (err) => {
    const text = (err && err.payload && err.payload.error)
      || (err && err.message) || 'the request failed';
    if (!notice) {
      notice = doc.createElement('p');
      notice.className = 'refdes-navis-error';
      notice.setAttribute('role', 'alert');
      const host = panel.querySelector('.refdes-navis-panel') || panel;
      host.insertBefore(notice, host.firstChild);
    }
    notice.textContent = text;
  };

  const disableEveryAction = () => {
    for (const b of panel.querySelectorAll('.refdes-navis-archive')) b.disabled = true;
    for (const b of panel.querySelectorAll('.refdes-navis-restore')) b.disabled = true;
  };

  const act = (button, path, key) => {
    button.disabled = true;
    apiFn(path, { method: 'POST', body: { navi: key } })
      .then(() => {
        // The server rebuilt synchronously before answering, so the page
        // this reload lands on is already current.
        location.reload();
      })
      .catch((err) => {
        button.disabled = false;
        showError(err);
        // A --no-write server refuses every write the same way: re-arming
        // the buttons would only invite the same 403 back.
        if (err && err.status === 403) disableEveryAction();
      });
  };

  active.forEach((row, index) => {
    if (!row.key) return; // a keyless marker has nothing the API can address
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'refdes-navis-archive';
    button.setAttribute('aria-label', `Archive Navi ${row.key6}`);
    button.textContent = 'Archive';
    topLis[index].appendChild(button);
    button.addEventListener('click', () => act(button, '/api/navis/archive', row.key));
  });

  rows.forEach((row, index) => {
    if (!row.archived || !row.key) return;
    const restore = allLis[index].querySelector('.refdes-navis-restore');
    if (!restore) return;
    if (row.orphan) {
      restore.setAttribute('title', ORPHAN_TITLE);
      return;
    }
    restore.removeAttribute('disabled');
    restore.setAttribute('title', 'Restore this Navi');
    restore.addEventListener('click', () => act(restore, '/api/navis/restore', row.key));
  });
}
