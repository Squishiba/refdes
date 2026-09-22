// Drafts: what the editor holds before it saves (docs/design/browser-editor.md,
// "Drafts: what the editor holds before it saves"). The live copy is this page's
// memory; a mirror in sessionStorage survives a tab reload and dies with the
// tab. Nothing about a draft touches disk, and nothing survives a browser
// restart -- closing the tab is a discard, which is why `beforeunload` asks.

const PREFIX = 'refdes.draft.v1.';
const memory = new Map();

function emptyDraft() {
  return { revision: null, fields: {}, body: null };
}

function key(handle) {
  return PREFIX + encodeURIComponent(handle);
}

function load(handle) {
  try {
    const raw = sessionStorage.getItem(key(handle));
    if (!raw) return emptyDraft();
    const parsed = JSON.parse(raw);
    return {
      revision: parsed.revision || null,
      fields: parsed.fields || {},
      body: parsed.body === undefined ? null : parsed.body,
    };
  } catch (_) {
    return emptyDraft(); // a private-mode or quota failure costs persistence, not editing
  }
}

function persist(handle, draft) {
  try {
    if (isDirty(draft)) sessionStorage.setItem(key(handle), JSON.stringify(draft));
    else sessionStorage.removeItem(key(handle));
  } catch (_) {
    /* memory only */
  }
}

export function getDraft(handle) {
  if (!memory.has(handle)) memory.set(handle, load(handle));
  return memory.get(handle);
}

export function isDirty(draft) {
  return Object.keys(draft.fields).length > 0 || draft.body !== null;
}

export function hasAnyDraft() {
  for (const draft of memory.values()) if (isDirty(draft)) return true;
  return false;
}

export function setDraftField(handle, name, value) {
  const draft = getDraft(handle);
  draft.fields[name] = value;
  persist(handle, draft);
  return draft;
}

export function setDraftBody(handle, text) {
  const draft = getDraft(handle);
  draft.body = text;
  persist(handle, draft);
  return draft;
}

export function setDraftRevision(handle, revision) {
  const draft = getDraft(handle);
  draft.revision = revision;
  persist(handle, draft);
}

export function clearDraft(handle) {
  memory.set(handle, emptyDraft());
  try {
    sessionStorage.removeItem(key(handle));
  } catch (_) {
    /* nothing to remove where we cannot write */
  }
}

// The design's "an unsaved draft raises a beforeunload prompt". The browser
// shows its own generic text; all we can do is ask.
window.addEventListener('beforeunload', (event) => {
  if (!hasAnyDraft()) return;
  event.preventDefault();
  event.returnValue = '';
});
