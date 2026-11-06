// N5c: the Navis panel on a SERVED preview page gains Archive/Restore
// actions (in-prog-logs/navis-design-20261025.md §11: the panel is a
// projection of the Navi store, with the serve surface as its client, never
// a second implementation; endpoints listed in
// docs/design/editor-vscode-adapter.md §3.3). The published
// page stays exactly as published -- the read-only panel with its disabled
// restore is the floor; this module, loaded only by preview.js, upgrades
// that floor over the serve API (GET /api/navis, POST /api/navis/archive and
// /api/navis/restore) through the one api() transport.
//
// M2 (the mint offer, Jared 2026-11-05): keyless rows get no Archive
// button, so the panel offers the mint -- one `Mint keys (N)` pill above
// the list, POSTing {} to /api/navis/mint (the M1 route, src/refdes/serve/
// navis_mint.py). A successful mint rides the same refresh a successful
// archive rides on this surface: a page reload. The status line therefore
// cannot live on the clicked page -- it rides the reload through one-shot
// sessionStorage (consumed once, so a reopen shows nothing), and it clears
// on the next action click. The words mirror the editor panel's (M3)
// exactly; the class names keep this surface's `refdes-` prefix (the CSS
// bar.css ships on the preview page).
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
const KEYLESS_TITLE = 'No key yet -- use Mint keys';
const MINT_TITLE = 'Writes a key into each unkeyed Navi marker in your item files';
const MINT_STATUS_KEY = 'refdes-navis-mint-status';
const REFUSAL_SUFFIX =
  ' -- refdes will not mint into those bodies (for example a YAML list body).';

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

  const host = panel.querySelector('.refdes-navis-panel') || panel;

  // The mint status rides the reload (see the header): stored by the page
  // that minted, rendered once here, then consumed -- a reload of this page
  // (reopen) shows nothing, like the alert.
  const storedStatus = takeStatus();
  let status = null;
  if (storedStatus) {
    status = doc.createElement('p');
    status.className = 'refdes-navis-note';
    status.setAttribute('role', 'status');
    status.textContent = storedStatus;
    host.insertBefore(status, host.firstChild);
  }
  const clearStatus = () => {
    if (status && status.parentNode) status.parentNode.removeChild(status);
    status = null;
  };

  let notice = null;
  const showError = (err) => {
    const text = (err && err.payload && err.payload.error)
      || (err && err.message) || 'the request failed';
    if (!notice) {
      notice = doc.createElement('p');
      notice.className = 'refdes-navis-error';
      notice.setAttribute('role', 'alert');
      host.insertBefore(notice, host.firstChild);
    }
    notice.textContent = text;
  };

  const disableEveryAction = () => {
    for (const b of panel.querySelectorAll('.refdes-navis-archive')) b.disabled = true;
    for (const b of panel.querySelectorAll('.refdes-navis-restore')) b.disabled = true;
    for (const b of panel.querySelectorAll('.refdes-navis-mint')) b.disabled = true;
  };

  const act = (button, path, key) => {
    clearStatus(); // the next action speaks; the mint's status line is stale
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
    if (!row.key) {
      // a keyless marker has nothing the API can address; say why where a
      // button would otherwise be
      const keySpan = topLis[index].querySelector('.mono');
      (keySpan || topLis[index]).setAttribute('title', KEYLESS_TITLE);
      return;
    }
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

  // M2: the mint offer. The count comes from the rows already in hand (a
  // keyless row shows no Archive button -- minting is what makes one
  // addressable); with nothing keyless there is no mint UI at all.
  const keyless = rows.filter((row) => !row.key).length;
  if (keyless > 0) {
    const mint = doc.createElement('button');
    mint.type = 'button';
    mint.className = 'refdes-navis-mint';
    mint.setAttribute('aria-label', `Mint keys for ${keyless} unkeyed Navis`);
    mint.setAttribute('title', MINT_TITLE);
    mint.textContent = `Mint keys (${keyless})`;
    host.insertBefore(mint, host.firstChild);
    mint.addEventListener('click', () => {
      clearStatus();
      mint.disabled = true;
      apiFn('/api/navis/mint', { method: 'POST', body: {} })
        .then((res) => {
          // the M1 route rebuilt synchronously before answering; the page
          // rides the same reload a successful archive rides, and the
          // status line rides the reload with it (module header)
          storeStatus(mintStatusText(res));
          location.reload();
        })
        .catch((err) => {
          mint.disabled = false;
          showError(err);
          if (err && err.status === 403) disableEveryAction();
        });
    });
  }
}

function mintStatusText(payload) {
  const minted = payload && Array.isArray(payload.minted) ? payload.minted.length : 0;
  const refused = payload && typeof payload.still_keyless === 'number'
    ? payload.still_keyless : 0;
  if (minted === 0 && refused === 0) return 'Nothing to mint.';
  if (minted === 0) return `${refused} marker(s) could not be keyed${REFUSAL_SUFFIX}`;
  if (refused === 0) return `Minted ${minted} key(s).`;
  return `Minted ${minted} key(s). ${refused} marker(s) could not be keyed${REFUSAL_SUFFIX}`;
}

function storeStatus(text) {
  try {
    sessionStorage.setItem(MINT_STATUS_KEY, text);
  } catch (_) {
    // private-mode browsers throw on storage: the mint landed (the reload
    // shows the keyed rows); only the status line is lost
  }
}

function takeStatus() {
  try {
    const text = sessionStorage.getItem(MINT_STATUS_KEY);
    if (text !== null) sessionStorage.removeItem(MINT_STATUS_KEY);
    return text;
  } catch (_) {
    return null;
  }
}
