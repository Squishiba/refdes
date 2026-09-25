// W1 of the thread workbench (docs/design/thread-workbench.md, "pin"): a
// preview page reloads itself when the project rebuilds, so the author never
// refreshes by hand. Same posture as app.js: answers come from the built
// project via /api/revision polling, never a push channel. The serial injected
// into the page at response time names the snapshot this HTML was rendered
// from; when the served serial moves past it, this page is stale. Nothing
// here computes a project fact, and the page stays read-only.

import { api } from './api.js';

const serialMeta = document.querySelector('meta[name="refdes-serial"]');
const renderedSerial = serialMeta ? Number(serialMeta.content) : null;

export function isStale(info) {
  return renderedSerial !== null && info.serial !== renderedSerial;
}

export async function poll() {
  if (renderedSerial === null) return;
  try {
    const info = await api('/api/revision');
    if (isStale(info)) location.reload();
  } catch (err) {
    // Lost contact: keep showing this generation; the next poll retries.
  }
}

// W3 show-values toggle (docs/design/thread-workbench.md §8): each calc
// table on a decorated preview page carries a button that hides or shows
// the inline value attributions page-wide. The badges' content was decided
// by the build; this only flips visibility -- no semantics, no fetch.
export function wireValueToggles(doc = document) {
  for (const btn of doc.querySelectorAll('.refdes-values-toggle')) {
    btn.addEventListener('click', () => {
      const off = doc.documentElement.classList.toggle('refdes-values-off');
      for (const other of doc.querySelectorAll('.refdes-values-toggle')) {
        other.setAttribute('aria-pressed', off ? 'false' : 'true');
      }
    });
  }
}

wireValueToggles();

poll();
setInterval(poll, 2000);
