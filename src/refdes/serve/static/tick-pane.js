// The tick pane's decision model: what the pane's unsaved-tick UI DECIDES,
// over plain objects the DOM glue (W5b.4c-1b) builds from the served markup
// (docs/design/thread-workbench-w5b-plan.md, §4 W5b.4 + §6 Q1/Q3/Q5/Q6/Q8,
// all RATIFIED 2026-11-06). The module is PURE by design and imports NOTHING:
// no DOM, no network, no storage, no page globals -- every rule here runs
// headless under test (tests/test_tick_pane.py), and the glue owns every
// touch of the page. Task ids are user data: ids like `__proto__` are matched
// as ordinary keys (Map / Set semantics, never a bare object index), and
// nothing built here ever consults Object.prototype.
//
// panelFromRows(panel)      -> {canDraft, reason, rows: [{taskId, draftable, reason, targets}]}
//   Can this panel draft at all, and which rows can? A tip with no key or no
//   revision is preview-only; a row needs an id and at least one legal target.
// wantedState(row, nowChecked) -> the state a click names (Q6b: a click that
//   lands the checkbox on its rendered state names that rendered state -- the
//   un-tick back to the original; any other click names the row's FIRST target).
// applyDraft(rows, pendingTicks) -> {rows, orphans}
//   The draft (the store's [taskId, wantedState] entries) over the rendered
//   rows: rows take their pending ticks, entries with no row come back as
//   orphans (Q3's pane-side notice), never silently dropped.
// indicator({pending, stale, orphans, canDraft}) -> {text, hidden}
//   Q8's ratified header count: "N unsaved ticks", with a stale clause
//   (Q3a: saving will ask to resolve), an orphan clause, and the
//   preview-only notice for a keyless tip. Plain strings the glue renders.
// isStale(draftRevision, panelRevision) -> a revision compare (Q3a): true
//   only when both are non-empty strings and differ.
// tabLabel(baseLabel, pendingCount) -> the tab-switch label with THIS tip's
//   own pending count (Q5a: drafts are per tip, tabs show per tip).
// needsUnloadPrompt(counts) -> Q8's generic prompt, per page: true iff any
//   tip has a pending tick (counts is the store's counts() object, which has
//   a null prototype -- read it as data, never through its prototype).
// discardPlan(rows) -> {rows} the rows' RENDERED checked states (Q8a:
//   discard is the explicit release; the draft never wrote a byte, so
//   returning to the file is returning to what is rendered).

function asText(value) {
  return typeof value === 'string' ? value : '';
}

function targetsOf(tickStates) {
  // the row's data-refdes-tick-states list: split, trimmed, empties dropped
  return asText(tickStates)
    .split(',')
    .map((target) => target.trim())
    .filter((target) => target !== '');
}

export function panelFromRows(panel) {
  const tipKey = asText(panel.tipKey);
  const revision = asText(panel.revision);
  const canDraft = tipKey !== '' && revision !== '';
  const reason = canDraft
    ? ''
    : 'this tip has no key/revision yet: ticks on it are preview-only and nothing is saved';
  const rows = [];
  for (const row of panel.rows) {
    const taskId = asText(row.taskId);
    const targets = targetsOf(row.tickStates);
    let draftable = false;
    let why = '';
    if (canDraft) {
      if (taskId === '') why = 'this task has no id, so its tick cannot be saved';
      else if (targets.length === 0) why = 'this row has no legal tick targets';
      else draftable = true;
    }
    rows.push({ taskId, draftable, reason: why, targets });
  }
  return { canDraft, reason, rows };
}

export function wantedState(row, nowChecked) {
  // Q6b: an un-tick names the row's RENDERED state (the draft entry closes
  // at its original), a tick names the FIRST legal target of the row.
  if (Boolean(nowChecked) === Boolean(row.checked)) return asText(row.state);
  const targets = targetsOf(row.tickStates);
  return targets.length > 0 ? targets[0] : asText(row.state);
}

export function applyDraft(rows, pendingTicks) {
  // Map first: duplicate entries resolve last-wins (the store's ticks are a
  // Map, so one entry per id), and a hostile id is an ordinary Map key.
  const draft = new Map();
  for (const entry of pendingTicks) draft.set(entry[0], entry[1]);
  const ids = new Set();
  for (const row of rows) {
    const taskId = asText(row.taskId);
    if (taskId !== '') ids.add(taskId); // the empty id never matches
  }
  const out = [];
  for (const row of rows) {
    const taskId = asText(row.taskId);
    if (taskId !== '' && draft.has(taskId)) {
      out.push({ taskId, checked: draft.get(taskId) === 'done', pending: true });
    } else {
      out.push({ taskId, checked: Boolean(row.checked), pending: false });
    }
  }
  const orphans = [];
  for (const [taskId, state] of draft) {
    if (!ids.has(taskId)) orphans.push([taskId, state]);
  }
  return { rows: out, orphans };
}

export function indicator(status) {
  const pending = Number(status.pending) || 0;
  const orphans = Number(status.orphans) || 0;
  const parts = [];
  if (pending > 0) parts.push(pending === 1 ? '1 unsaved tick' : `${pending} unsaved ticks`);
  if (status.stale) parts.push('made against an older version - saving will ask to resolve');
  if (orphans > 0) parts.push(`(${orphans} no longer match a task)`);
  if (status.canDraft === false) parts.push('ticks on this tip are preview-only - nothing is saved');
  const text = parts.join(' ');
  return { text, hidden: text === '' };
}

export function isStale(draftRevision, panelRevision) {
  // Q3a: staleness is a revision compare, and there is nothing to compare
  // against on a tip that carries no revision -- a keyless tip is never stale.
  return (
    typeof draftRevision === 'string' &&
    typeof panelRevision === 'string' &&
    draftRevision !== '' &&
    panelRevision !== '' &&
    draftRevision !== panelRevision
  );
}

export function tabLabel(baseLabel, pendingCount) {
  // Q5a: a clean tab carries no count at all; a dirty one carries its own.
  return pendingCount > 0 ? `${baseLabel} (${pendingCount})` : baseLabel;
}

export function needsUnloadPrompt(counts) {
  // counts() has a null prototype (Object.create(null)): Object.keys is a
  // static, so it reads as data; a hasOwnProperty call on it is a TypeError.
  if (!counts) return false;
  for (const tipKey of Object.keys(counts)) {
    if (Number(counts[tipKey]) > 0) return true;
  }
  return false;
}

export function discardPlan(rows) {
  const out = [];
  for (const row of rows) out.push({ taskId: asText(row.taskId), checked: Boolean(row.checked) });
  return { rows: out };
}
