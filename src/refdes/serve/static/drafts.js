// Drafts: what the editor holds before it saves (docs/design/browser-editor.md,
// "Drafts: what the editor holds before it saves"). The live copy is this page's
// memory; a mirror in sessionStorage survives a tab reload and dies with the
// tab. Nothing about a draft touches disk, and nothing survives a browser
// restart -- closing the tab is a discard, which is why `beforeunload` asks.
// A mirror that exists but cannot be read is never read as a clean slate:
// its bytes are preserved under `refdes.draft.corrupt.v1.` and reported.

const PREFIX = 'refdes.draft.v1.';
// An unreadable mirror is copied here and nothing else ever writes this key,
// so the bytes survive page edits (and a reload) until an explicit discard.
const CORRUPT_PREFIX = 'refdes.draft.corrupt.v1.';
const memory = new Map();
const corruptMirrors = new Map(); // handle -> { raw, reason }: bytes we could not read

function emptyDraft() {
  // links are pending ops, not values: `add`/`remove` map verb -> targets,
  // and a target pending on one side is absent from the other (Slice 2).
  return { revision: null, fields: {}, body: null, pins: [], links: { add: {}, remove: {} } };
}

function key(handle) {
  return PREFIX + encodeURIComponent(handle);
}

function corruptKey(handle) {
  return CORRUPT_PREFIX + encodeURIComponent(handle);
}

function reportCorruptMirror(handle, raw, reason) {
  // Bytes that existed but could not be read are evidence of unsaved work,
  // never a clean slate: keep them in a recovery key, say so in the console
  // and on the page, and let the close prompt stay armed. Editing still
  // proceeds from a fresh draft -- the refusal is to be silent, not to be
  // useful. If even the copy cannot be stored the bytes live in this page
  // only; persistence is lost, but silence never is.
  corruptMirrors.set(handle, { raw, reason });
  let preserved = true;
  try {
    sessionStorage.setItem(corruptKey(handle), raw);
  } catch (_) {
    preserved = false;
  }
  console.warn(
    `refdes: the saved draft mirror for ${handle} could not be read (${reason}). ` +
      (preserved
        ? `The unreadable bytes are preserved under the sessionStorage key ${corruptKey(handle)}.`
        : 'The unreadable bytes could not be preserved in storage either; they live in this page only.')
  );
  mirrorNotice(handle, preserved);
  return emptyDraft();
}

function mirrorNotice(handle, preserved) {
  const bar = document.createElement('div');
  bar.className = 'banner bad';
  bar.setAttribute('role', 'alert');
  const text = document.createElement('p');
  text.textContent =
    `The saved mirror of unsaved work for ${handle} was unreadable, so this form starts clean. ` +
    (preserved
      ? `The unreadable bytes are preserved in sessionStorage under ${corruptKey(handle)}; recover them from that key before closing the tab.`
      : 'The unreadable bytes could not be preserved in storage; they exist in this page only.');
  bar.appendChild(text);
  const button = document.createElement('button');
  button.className = 'btn';
  button.textContent = 'Discard the unreadable mirror';
  button.addEventListener('click', () => {
    discardCorruptDraft(handle);
    bar.remove();
  });
  bar.appendChild(button);
  document.body.prepend(bar);
}

function load(handle) {
  let raw;
  try {
    raw = sessionStorage.getItem(key(handle));
  } catch (_) {
    return emptyDraft(); // a private-mode or quota failure costs persistence, not editing
  }
  if (!raw) return emptyDraft();
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    return reportCorruptMirror(handle, raw, err.message);
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    // parses but is not a draft: same class of damage -- bytes, not a draft
    return reportCorruptMirror(handle, raw, 'the stored mirror is not a draft object');
  }
  const links = parsed.links || {};
  return {
    revision: parsed.revision || null,
    fields: parsed.fields || {},
    body: parsed.body === undefined ? null : parsed.body,
    pins: parsed.pins || [],
    links: { add: links.add || {}, remove: links.remove || {} },
  };
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
  return (
    Object.keys(draft.fields).length > 0 ||
    draft.body !== null ||
    Object.keys(draft.links.add).length > 0 ||
    Object.keys(draft.links.remove).length > 0
  );
}

export function hasAnyDraft() {
  for (const draft of memory.values()) if (isDirty(draft)) return true;
  // an unreadable mirror is unsaved work we preserved: a tab close must ask
  return corruptMirrors.size > 0;
}

export function corruptDraft(handle) {
  return corruptMirrors.get(handle) || null;
}

export function discardCorruptDraft(handle) {
  corruptMirrors.delete(handle);
  try {
    sessionStorage.removeItem(corruptKey(handle));
  } catch (_) {
    /* nothing to remove where we cannot write */
  }
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

export function addDraftPin(handle, pin) {
  const draft = getDraft(handle);
  if (!draft.pins.some((p) => p.path === pin.path && p.key === pin.key)) {
    draft.pins.push(pin);
  }
  persist(handle, draft);
  return draft;
}

function linkToggle(draft, side, verb, target) {
  const here = draft.links[side];
  const other = draft.links[side === 'add' ? 'remove' : 'add'];
  if (!here[verb]) here[verb] = [];
  if (!here[verb].includes(target)) here[verb].push(target);
  if (other[verb]) {
    other[verb] = other[verb].filter((t) => t !== target);
    if (!other[verb].length) delete other[verb];
  }
  if (!here[verb].length) delete here[verb];
}

export function draftLinkAdd(handle, verb, target) {
  const draft = getDraft(handle);
  linkToggle(draft, 'add', verb, target);
  persist(handle, draft);
  return draft;
}

export function draftLinkRemove(handle, verb, target) {
  const draft = getDraft(handle);
  linkToggle(draft, 'remove', verb, target);
  persist(handle, draft);
  return draft;
}

// A save op applied: it stops being pending, and the file moved to a new
// revision. Drop it and record the revision in one step that persists once,
// at the end: if the mirror were written while the applied op was still in
// the draft (the revision update persisting first, the drop never), a reload
// would restore the applied edit as still-pending and a retry would re-post
// it. The mirror must only ever hold what memory still holds.
export function dropAppliedOp(handle, op, revision) {
  const draft = getDraft(handle);
  if (op.op === 'set_field') delete draft.fields[op.field];
  else if (op.op === 'set_body') {
    draft.body = null;
    draft.pins = [];
  } else {
    const side = op.op === 'add_link' ? 'add' : 'remove';
    const list = draft.links[side][op.verb] || [];
    const at = list.indexOf(op.target);
    if (at >= 0) list.splice(at, 1);
    if (!list.length) delete draft.links[side][op.verb];
  }
  draft.revision = revision;
  persist(handle, draft);
  return draft;
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
