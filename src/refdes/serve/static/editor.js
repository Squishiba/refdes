// The edit form: docs/design/browser-editor.md, "Editing fields", "Editing and
// previewing bodies", and the concurrency decision "draft, refuse, diff -- never
// merge". Controls come from what the server says is editable (`item.edit`), so
// nothing here re-implements the schema: an enum's choices, a field's required
// flag, and every read-only reason arrive from Python. A draft lives in the
// browser (drafts.js) and is sent as one save per dirty part, each carrying the
// file revision the form opened on. A conflict offers keep-mine, keep-theirs,
// or copy-by-hand -- and never a merge.

import { api } from './api.js';
import {
  getDraft, setDraftField, setDraftBody, setDraftRevision, clearDraft, isDirty,
} from './drafts.js';
import { createLinksSection } from './links.js';
import { fieldControlNode } from './controls.js';

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function coerce(spec, raw) {
  if (!spec) return raw;
  if (spec.value_type === 'number') {
    const n = Number(raw);
    return Number.isNaN(n) ? raw : n;
  }
  if (spec.value_type === 'boolean') return raw === 'true';
  return raw;
}

export function createEditor(item, handle, onSaved, onDiscarded) {
  const edit = item.edit || { editable: false, fields: {}, body: {} };
  const draft = getDraft(handle);
  let revision = draft.revision || edit.file_revision || item.revision;
  const specs = {};

  const block = el('section', 'detail-block edit-block');
  block.appendChild(el('h2', null, 'Edit'));

  if (!edit.editable) {
    // Nothing to save: say why instead of offering a button that cannot work.
    // The server refuses independently; this only stops the false affordance.
    block.appendChild(el('p', 'muted', edit.reason || 'This item is read only.'));
    return { node: block, fieldControl: () => null, bodyControl: () => null };
  }

  const bar = el('div', 'edit-bar');
  const status = el('span', 'edit-status muted', 'saved');
  const save = el('button', 'btn save', 'Save');
  const discard = el('button', 'btn discard', 'Discard draft');
  bar.appendChild(save);
  bar.appendChild(discard);
  bar.appendChild(status);
  block.appendChild(bar);

  const messages = el('div', 'edit-messages');
  block.appendChild(messages);

  // Link pickers live inside the edit block: their adds and removes are
  // draft ops, so the one Save button, the one revision, and the one
  // conflict screen cover them exactly like a field edit (Slice 2).
  const linksSection = createLinksSection(item, handle, refreshStatus);
  if (linksSection) block.appendChild(linksSection);
  const conflictBox = el('div', 'conflict');
  conflictBox.hidden = true;
  block.appendChild(conflictBox);

  function refreshStatus() {
    const dirty = isDirty(draft);
    status.textContent = dirty ? 'unsaved' : 'saved';
    status.className = dirty ? 'edit-status warn' : 'edit-status muted';
    save.disabled = !dirty;
    discard.disabled = !dirty;
  }

  function note(text, kind) {
    messages.textContent = text || '';
    messages.className = `edit-messages ${kind || 'muted'}`.trim();
  }

  // ------------------------------------------------------------- controls

  function fieldControl(name, value) {
    const spec = (edit.fields || {})[name];
    if (!spec || !spec.editable) return null;
    specs[name] = spec;
    const shown = name in draft.fields ? draft.fields[name] : (value ?? '');
    // controls.js owns the enum/text control; the draft owns the value.
    return fieldControlNode(spec, shown, (node) => {
      setDraftField(handle, name, node.value);
      note('');
      refreshStatus();
    });
  }

  function bodyControl(value) {
    if (!edit.body || !edit.body.editable) return null;
    const area = el('textarea', 'body-edit');
    area.rows = 12;
    area.value = draft.body !== null ? draft.body : (value || '');
    area.addEventListener('input', () => {
      setDraftBody(handle, area.value);
      note('');
      refreshStatus();
    });
    return area;
  }

  // ---------------------------------------------------------------- save

  function pendingOps() {
    const ops = [];
    for (const [name, value] of Object.entries(draft.fields)) {
      ops.push({ op: 'set_field', field: name, value: coerce(specs[name], value) });
    }
    if (draft.body !== null) ops.push({ op: 'set_body', text: draft.body });
    for (const [verb, targets] of Object.entries(draft.links.add)) {
      for (const target of targets) ops.push({ op: 'add_link', verb, target });
    }
    for (const [verb, targets] of Object.entries(draft.links.remove)) {
      for (const target of targets) ops.push({ op: 'remove_link', verb, target });
    }
    return ops;
  }

  async function postAll(ops, atRevision) {
    let rev = atRevision;
    for (const one of ops) {
      const payload = await api(`/api/item/${encodeURIComponent(handle)}/edit`, {
        method: 'POST',
        body: Object.assign({}, one, { expected_revision: rev }),
      });
      rev = payload.revision;
      setDraftRevision(handle, rev);
      if (one.op === 'set_field') delete draft.fields[one.field];
      else if (one.op === 'set_body') draft.body = null;
      else {
        const side = one.op === 'add_link' ? 'add' : 'remove';
        const list = draft.links[side][one.verb] || [];
        const at = list.indexOf(one.target);
        if (at >= 0) list.splice(at, 1);
        if (!list.length) delete draft.links[side][one.verb];
      }
    }
    return rev;
  }

  async function saveAll(ops, atRevision) {
    save.disabled = true;
    note('Saving…', 'muted');
    try {
      await postAll(ops || pendingOps(), atRevision || revision);
      clearDraft(handle);
      note('Saved.', 'good');
      refreshStatus();
      onSaved();
    } catch (err) {
      save.disabled = false;
      refreshStatus();
      if (err.status === 409) showConflict(err.payload || {}, ops, atRevision || revision);
      else if (err.status === 422) showBlocked(err.payload || {});
      else note(`The save failed: ${err.message}`, 'bad');
    }
  }

  save.addEventListener('click', () => saveAll());

  discard.addEventListener('click', () => {
    clearDraft(handle);
    note('Draft discarded.', 'muted');
    refreshStatus();
    onDiscarded();
  });

  // ------------------------------------------------------------- failure

  function showBlocked(payload) {
    note('');
    messages.appendChild(el('p', 'banner bad', payload.reason || payload.message || 'The save was refused.'));
    for (const d of payload.diagnostics || []) {
      const where = d.file ? ` (${d.file}${d.line ? ':' + d.line : ''})` : '';
      messages.appendChild(el('p', `diag diag-${d.level}`, `${d.level.toUpperCase()} ${d.message}${where}`));
    }
  }

  function showConflict(payload, ops, atRevision) {
    conflictBox.textContent = '';
    conflictBox.hidden = false;
    conflictBox.appendChild(el('h3', null, 'The file changed on disk'));
    conflictBox.appendChild(el('p', 'muted', payload.message || ''));
    conflictBox.appendChild(el('p', 'muted', 'Your draft against what is there now:'));
    conflictBox.appendChild(el('pre', 'conflict-diff', payload.diff || '(no diff available)'));

    const mine = el('textarea', 'conflict-draft');
    mine.readOnly = true;
    mine.rows = 6;
    mine.value = describeDraft(ops);
    conflictBox.appendChild(mine);

    const actions = el('div', 'conflict-actions');
    const keepMine = el('button', 'btn', 'Keep mine');
    const keepTheirs = el('button', 'btn', 'Keep theirs');
    const copyOut = el('button', 'btn', 'Copy my draft');
    keepMine.addEventListener('click', () => {
      conflictBox.hidden = true;
      saveAll(ops, payload.current_revision);
    });
    keepTheirs.addEventListener('click', () => {
      clearDraft(handle);
      conflictBox.hidden = true;
      onDiscarded();
    });
    copyOut.addEventListener('click', () => {
      mine.select();
      try { document.execCommand('copy'); } catch (_) { /* select is enough to copy by hand */ }
    });
    actions.appendChild(keepMine);
    actions.appendChild(keepTheirs);
    actions.appendChild(copyOut);
    conflictBox.appendChild(actions);
  }

  function describeDraft(ops) {
    return (ops || pendingOps())
      .map((one) => {
        if (one.op === 'set_field') return `${one.field}: ${one.value}`;
        if (one.op === 'set_body') return `body:\n${one.text}`;
        return `${one.op} ${one.verb} -> ${one.target}`;
      })
      .join('\n\n');
  }

  refreshStatus();
  return { node: block, fieldControl, bodyControl };
}
