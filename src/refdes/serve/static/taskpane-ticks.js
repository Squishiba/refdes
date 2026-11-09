/* The preview pane's ticks and their draft (docs/design/thread-workbench-w5b-plan.md
   W5b.3 + W5b.4 §6 Q1/Q5/Q6/Q8, all RATIFIED 2026-11-06). The response
   decoration grows the pane's tick rows in a preview page and loads this
   module beside them; a published page grows neither. It is the DOM glue:
   the pane's markup in, the two pure modules' decisions out. The store
   (tick-drafts.js) owns the draft's shape and mirror; the model
   (tick-pane.js) owns every rule -- which rows can draft, what a click
   names, how the pane paints a draft, what the header says, when the page
   asks before leaving. This file decides nothing of its own: it reads the
   rows, answers a change, restores a stored draft on load, shows the
   header count, offers Discard, and asks `beforeunload`. It records
   nothing to the project: the save is W5b.4c-2, so there is no request
   here. A storage that throws (blocked, private mode, full) costs
   persistence, never the pane. The pane's W5b.3 sentence under the title
   stays: the control is preview chrome, and it says so. Everything renders
   through textContent; no markup is ever pasted. */

import { createTickDrafts } from './tick-drafts.js';
import {
  panelFromRows,
  wantedState,
  applyDraft,
  indicator,
  isStale,
  tabLabel,
  needsUnloadPrompt,
  discardPlan,
} from './tick-pane.js';

function storageMirror() {
  // Q1 (ratified (b)): the per-tab mirror is the page's sessionStorage, the
  // editor's own draft lifetime. The access is guarded here -- before the
  // store is built -- because a throwing storage must cost persistence and
  // never the pane: the caller falls back to a page-memory mirror.
  try {
    return window.sessionStorage;
  } catch (_) {
    return null;
  }
}

function memoryMirror() {
  // the drop-in for a storage that throws: editing proceeds in page memory,
  // reload pays for the blocked storage.
  const rows = new Map();
  return {
    getItem(key) {
      return rows.has(key) ? rows.get(key) : null;
    },
    setItem(key, value) {
      rows.set(key, value);
    },
    removeItem(key) {
      rows.delete(key);
    },
  };
}

const drafts = createTickDrafts(storageMirror() || memoryMirror());

function attr(node, name) {
  return node.getAttribute(name) || '';
}

const tabs = [];

function refreshTabs() {
  // Q5a (ratified): a tab carries its OWN tip's pending count, never a
  // merged one; a clean tab carries no count at all.
  for (const tab of tabs) {
    const pending = tab.tipKey ? drafts.pendingCount(tab.tipKey) : 0;
    tab.node.textContent = tabLabel(tab.base, pending);
  }
}

function refreshPanel(entry) {
  const pendingTicks = entry.canDraft ? drafts.pendingTicks(entry.tipKey) : [];
  // applyDraft reads the DESCRIPTOR rows (state + checked + targets), never
  // the panelFromRows output: the model's rows carry no state and no
  // checked, and painting its answer from them un-checks every row the
  // file says is done (real-browser pass, 2026-11-09).
  const applied = applyDraft(entry.rows, pendingTicks);
  applied.rows.forEach((row, at) => {
    const box = entry.boxes[at];
    box.checked = row.checked;
    const label = box.closest('label');
    if (label) label.classList.toggle('refdes-taskpane-tick-pending', row.pending === true);
  });
  const pending = entry.canDraft ? drafts.pendingCount(entry.tipKey) : 0;
  const status = indicator({
    pending,
    stale: isStale(entry.canDraft ? drafts.revision(entry.tipKey) : '', entry.revision),
    orphans: applied.orphans.length,
    canDraft: entry.canDraft,
  });
  entry.status.textContent = status.text;
  entry.status.hidden = status.hidden;
  entry.discard.hidden = pending === 0;
  refreshTabs();
}

for (const head of document.querySelectorAll('.refdes-taskpane .refdes-taskpane-head')) {
  // W5b.3's sentence, kept: the pane says plainly what the control is.
  const pane = head.closest('.refdes-taskpane');
  if (!pane || !pane.querySelector('input[data-refdes-task]')) continue;
  const note = document.createElement('p');
  note.className = 'refdes-taskpane-tick-note small muted';
  note.textContent =
    'Preview: ticking a row changes this page only -- nothing is saved.';
  head.insertAdjacentElement('afterend', note);
}

for (const tab of document.querySelectorAll('.refdes-taskpane-tab')) {
  // Q5a: a tab's label names its own tip's count, so the pairing tab ->
  // panel -> tip key is read once, and the label's base text is kept.
  const panelEl = document.getElementById(tab.getAttribute('aria-controls') || '');
  tabs.push({
    node: tab,
    base: tab.textContent,
    tipKey: panelEl ? attr(panelEl, 'data-refdes-tip-key') : '',
  });
}

for (const panelEl of document.querySelectorAll('.refdes-taskpane-panel')) {
  const boxes = Array.prototype.slice.call(
    panelEl.querySelectorAll('input[data-refdes-task]')
  );
  if (boxes.length === 0) continue;
  const rawRows = boxes.map((box) => ({
    taskId: attr(box, 'data-refdes-task'),
    state: attr(box, 'data-refdes-task-state'),
    tickStates: attr(box, 'data-refdes-tick-states'),
    checked: box.checked,
  }));
  const model = panelFromRows({
    tipKey: attr(panelEl, 'data-refdes-tip-key'),
    revision: attr(panelEl, 'data-refdes-revision'),
    rows: rawRows,
  });
  const status = document.createElement('p');
  status.className = 'refdes-taskpane-tick-status small muted';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.hidden = true;
  const discard = document.createElement('button');
  discard.type = 'button';
  discard.className = 'refdes-taskpane-discard';
  discard.textContent = 'Discard';
  discard.hidden = true;
  panelEl.insertBefore(status, panelEl.firstChild);
  panelEl.insertBefore(discard, status.nextSibling);
  const entry = {
    tipKey: attr(panelEl, 'data-refdes-tip-key'),
    revision: attr(panelEl, 'data-refdes-revision'),
    canDraft: model.canDraft,
    model,
    rows: rawRows,
    boxes,
    status,
    discard,
  };
  boxes.forEach((box, at) => {
    const row = model.rows[at];
    if (model.canDraft && !row.draftable) {
      // a row the model says cannot draft is inert, and says why (the
      // model's plain string, as text in the title, never as markup).
      box.disabled = true;
      box.title = row.reason;
    }
    box.addEventListener('change', () => {
      if (!entry.canDraft || !row.draftable) return; // the native toggle stands
      const raw = rawRows[at];
      const wanted = wantedState(raw, box.checked);
      drafts.setTick(entry.tipKey, row.taskId, wanted, raw.state);
      drafts.setRevision(entry.tipKey, entry.revision);
      refreshPanel(entry);
    });
  });
  discard.addEventListener('click', () => {
    // Q8a (ratified): Discard is the explicit release. The draft never
    // wrote a byte, so the rows return to what is RENDERED.
    drafts.discard(entry.tipKey);
    const plan = discardPlan(rawRows);
    plan.rows.forEach((row, at) => {
      entry.boxes[at].checked = row.checked;
    });
    refreshPanel(entry);
  });
  refreshPanel(entry); // restore: a draft stored by this tab takes over the rows
}

window.addEventListener('beforeunload', (event) => {
  // Q8 (ratified (a)): ONE prompt, its condition read at event time from
  // the store's live counts -- the standard preventDefault + returnValue
  // shape, the browser's own words.
  if (!needsUnloadPrompt(drafts.counts())) return;
  event.preventDefault();
  event.returnValue = '';
});
