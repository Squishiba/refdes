import { api } from './api.js';

const banner = document.getElementById('banner');
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

poll();
setInterval(poll, 2000);
