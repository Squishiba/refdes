// The editor shell: a hash router over #/items[?filters] and
// #/items/<handle>[?filters]. The filter query is the state — reload and
// deep links land on the same view. Everything shown is fetched from the
// API; nothing here computes a project fact.

import { api } from './api.js';
import { parseFilters, filterQuery, renderSidebar } from './filters.js';
import { renderList } from './list.js';
import { renderItem } from './item.js';
import { createForm } from './create.js';

const banner = document.getElementById('banner');
const sidebar = document.getElementById('sidebar');
const listPane = document.getElementById('list');
const detailPane = document.getElementById('detail');

function parseRoute() {
  const hash = location.hash || '#/items';
  const q = hash.indexOf('?');
  const path = q === -1 ? hash : hash.slice(0, q);
  const filters = parseFilters(hash);
  if (path === '#/new') {
    // #/new?type=log&amends=LOG-001 — the amend affordance links here so the
    // form opens pre-filled; the form itself fetches the schema it needs.
    return { name: 'create', handle: null, filters, params: new URLSearchParams(q === -1 ? '' : hash.slice(q + 1)) };
  }
  const m = path.match(/^#\/items(?:\/(.+))?$/);
  if (!m) return { name: 'items', handle: null, filters };
  return { name: 'item', handle: m[1] ? decodeURIComponent(m[1]) : null, filters };
}

let requestSeq = 0;

async function renderRoute() {
  const route = parseRoute();
  const seq = ++requestSeq;
  let payload;
  try {
    payload = await api(`/api/items${filterQuery(route.filters)}`);
  } catch (err) {
    sidebar.textContent = '';
    listPane.textContent = '';
    const p = document.createElement('p');
    p.className = 'banner bad';
    p.textContent = err.status === 400
      ? `Bad filter: ${err.message}`
      : `Could not load items: ${err.message}`;
    listPane.appendChild(p);
    return;
  }
  if (seq !== requestSeq) return; // superseded by a newer navigation
  renderSidebar(sidebar, payload, route.filters, (next) => {
    location.hash = `#/items${filterQuery(next)}`;
  });
  renderList(listPane, payload, route.filters);
  if (route.name === 'create') {
    detailPane.textContent = '';
    detailPane.appendChild(createForm({
      type: route.params.get('type'),
      amends: route.params.get('amends'),
      board: route.params.get('board'),
    }));
  } else if (route.handle) {
    renderItem(detailPane, route.handle);
  } else if (payload.items.length === 1) {
    renderItem(detailPane, payload.items[0].handle);
  } else {
    detailPane.textContent = '';
    const p = document.createElement('p');
    p.className = 'muted';
    p.textContent = 'Select an item.';
    detailPane.appendChild(p);
  }
}

window.addEventListener('hashchange', renderRoute);
renderRoute();

const gitBadge = document.getElementById('git-badge');
let openRevision = null;   // the revision the current view was loaded against

export function currentRevision() { return openRevision; }
export function setOpenRevision(rev) { openRevision = rev; }

function showGit(git) {
  if (!git || !git.available) { gitBadge.hidden = true; return; }
  const dirty = git.worktree_dirty ? ' \u00b7 modified' : '';
  const staged = git.index_dirty ? ' \u00b7 staged' : '';
  gitBadge.textContent = `${git.branch} @ ${git.head}${dirty}${staged}`;
  gitBadge.hidden = false;
}

function showBanner(info) {
  const messages = [];
  if (info.load_error) messages.push(`The project no longer loads: ${info.load_error}`);
  else if (info.stale) messages.push('The project changed on disk; rebuilding\u2026');
  if (openRevision !== null && info.revision !== openRevision) {
    messages.push('The files changed since this page was loaded.');
  }
  banner.textContent = messages.join(' ');
  banner.className = info.load_error ? 'banner bad' : 'banner';
  banner.hidden = messages.length === 0;
}

let lastServed = null;
export async function poll() {
  try {
    const info = await api('/api/revision');
    showGit(info.git);
    showBanner(info);
    if (lastServed !== null && info.serial !== lastServed) {
      window.dispatchEvent(new CustomEvent('refdes:rebuilt', { detail: info }));
    }
    lastServed = info.serial;
  } catch (err) {
    banner.textContent = `Lost contact with refdes serve (${err.message}). It may have been stopped.`;
    banner.className = 'banner bad';
    banner.hidden = false;
  }
}

// A rebuild re-renders the view; an unsaved draft survives it because drafts
// live in drafts.js, not in the DOM the re-render replaces.
window.addEventListener('refdes:rebuilt', renderRoute);

poll();
setInterval(poll, 2000);
