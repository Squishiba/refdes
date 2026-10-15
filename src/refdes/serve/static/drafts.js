// Drafts: what the editor holds before it saves (docs/design/browser-editor.md,
// "Drafts: what the editor holds before it saves"). The live copy is this page's
// memory; a mirror in sessionStorage survives a tab reload and dies with the
// tab. Nothing about a draft touches disk, and nothing survives a browser
// restart -- closing the tab is a discard, which is why `beforeunload` asks.
// A mirror that exists but cannot be read is never read as a clean slate:
// its bytes are preserved under `refdes.draft.corrupt.v1.` and reported.

const PREFIX = 'refdes.draft.v1.';
// An unreadable mirror is copied here and nothing else ever writes this key,
// so the bytes survive page edits and reloads -- re-armed from this key on
// every load -- until an explicit discard, which clears both this key and
// the draft slot (only if it still holds the discarded bytes).
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

function decodeMirror(stored) {
  // The recovery copy is an envelope carrying the concrete parse reason, so
  // a reload names the same damage the first page saw, not a generic line.
  // A value predating the envelope decodes as bare bytes with a generic
  // reason; an envelope is only accepted as a whole {raw, reason} pair of
  // strings, so recovery bytes that are not one are never misread as one.
  try {
    const envelope = JSON.parse(stored);
    if (
      envelope !== null &&
      typeof envelope === 'object' &&
      !Array.isArray(envelope) &&
      typeof envelope.raw === 'string' &&
      typeof envelope.reason === 'string'
    ) {
      return envelope;
    }
  } catch (_) {
    /* fall through: the bare-bytes form */
  }
  return { raw: stored, reason: 'unreadable bytes preserved by an earlier page load' };
}

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const DRAFT_KEYS = new Set(['revision', 'fields', 'body', 'pins', 'links']);

function draftShapeProblem(parsed) {
  // Shape-first, permissive where age explains the difference: keys added
  // after a mirror was written (pins, links) may be absent -- load()
  // defaults them -- and unknown extra keys are left alone. Every
  // recognized key that IS present must hold the type the draft accessors
  // rely on, so a mirror the code would run on blindly is named instead.
  // (Pins entries are not checked: a damaged entry degrades a pin label,
  // not the draft.)
  if (parsed === null) return 'the stored mirror is not a draft object';
  if (![...DRAFT_KEYS].some((k) => k in parsed)) {
    return 'the stored mirror has none of the draft keys';
  }
  if (parsed.revision !== undefined && parsed.revision !== null && typeof parsed.revision !== 'string') {
    return 'the mirror revision is not a string';
  }
  if (parsed.fields !== undefined && !isPlainObject(parsed.fields)) {
    return 'the mirror fields is not an object';
  }
  if (parsed.body !== undefined && parsed.body !== null && typeof parsed.body !== 'string') {
    return 'the mirror body is not a string';
  }
  if (parsed.pins !== undefined && !Array.isArray(parsed.pins)) {
    return 'the mirror pins is not a list';
  }
  if (parsed.links !== undefined) {
    if (!isPlainObject(parsed.links)) return 'the mirror links is not an object';
    for (const side of ['add', 'remove']) {
      const ops = parsed.links[side];
      if (ops === undefined) continue;
      if (!isPlainObject(ops)) return `the mirror links.${side} is not an object`;
      if (!Object.values(ops).every(Array.isArray)) {
        return `the mirror links.${side} verbs are not lists of targets`;
      }
    }
  }
  return null;
}

function reportCorruptMirror(handle, raw, reason) {
  // Bytes that existed but could not be read are evidence of unsaved work,
  // never a clean slate: keep them in a recovery key, say so in the console
  // and on the page, and let the close prompt stay armed. Editing still
  // proceeds from a fresh draft -- the refusal is to be silent, not to be
  // useful. If even the copy cannot be stored the bytes live in this page
  // only; persistence is lost, but silence never is.
  const entry = corruptMirrors.get(handle) || { warned: false };
  entry.raw = raw;
  entry.reason = reason;
  corruptMirrors.set(handle, entry);
  let preserved = true;
  try {
    sessionStorage.setItem(corruptKey(handle), JSON.stringify({ raw, reason }));
  } catch (_) {
    preserved = false;
  }
  if (entry.warned) return; // one warning and one banner per page
  entry.warned = true;
  console.warn(
    `refdes: the saved draft mirror for ${handle} could not be read (${reason}). ` +
      (preserved
        ? `A copy of the unreadable bytes is preserved under the sessionStorage key ${corruptKey(handle)}.`
        : 'The unreadable bytes could not be preserved in storage either; they live in this page only.')
  );
  mirrorNotice(handle, preserved);
}

function mirrorNotice(handle, preserved) {
  const bar = document.createElement('div');
  bar.className = 'banner bad';
  bar.setAttribute('role', 'alert');
  const text = document.createElement('p');
  text.textContent =
    `The saved mirror of unsaved work for ${handle} was unreadable, so this form starts clean. ` +
    (preserved
      ? `A copy of the unreadable bytes is preserved in sessionStorage under ${corruptKey(handle)}; recover them from that key before closing the tab.`
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
    // a recovery copy from an earlier page load is re-armed on every load,
    // even once a newer valid draft has replaced the slot it was found in
    const recovered = sessionStorage.getItem(corruptKey(handle));
    if (recovered) {
      const mirror = decodeMirror(recovered);
      reportCorruptMirror(handle, mirror.raw, mirror.reason);
    }
  } catch (_) {
    return emptyDraft(); // a private-mode or quota failure costs persistence, not editing
  }
  if (!raw) return emptyDraft();
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    reportCorruptMirror(handle, raw, err.message);
    return emptyDraft();
  }
  const problem = draftShapeProblem(isPlainObject(parsed) ? parsed : null);
  if (problem) {
    // parses but is not a usable draft: same class of damage -- bytes, not a draft
    reportCorruptMirror(handle, raw, problem);
    return emptyDraft();
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
  const entry = corruptMirrors.get(handle);
  corruptMirrors.delete(handle);
  try {
    sessionStorage.removeItem(corruptKey(handle));
    // a discard also clears the unreadable bytes from the draft slot, so a
    // reload finds nothing to re-report -- only when the slot still holds
    // exactly those bytes; a newer valid draft in the slot survives
    if (entry && sessionStorage.getItem(key(handle)) === entry.raw) {
      sessionStorage.removeItem(key(handle));
    }
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

// Cancelling a pending op -- what the undo button means: the op leaves the
// draft and the link returns to what the server holds. It is not a toggle
// onto the other side. An undo of a pending add that becomes a pending
// remove names a link the item does not have (and of a pending remove, a
// link it already has); the server refuses exactly those ops with 422, and
// a refused save leaves the whole draft behind (EDITOR-API-004).
export function draftLinkCancel(handle, verb, target) {
  const draft = getDraft(handle);
  for (const side of ['add', 'remove']) {
    const list = draft.links[side][verb];
    if (!list) continue;
    const at = list.indexOf(target);
    if (at >= 0) list.splice(at, 1);
    if (!list.length) delete draft.links[side][verb];
  }
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
