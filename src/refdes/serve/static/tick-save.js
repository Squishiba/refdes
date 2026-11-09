// The tick pane's save model: the REQUEST and RESPONSE logic of the pane's
// Save (docs/design/thread-workbench-w5b-plan.md, §4 W5b.4 + §6 Q3/Q6/Q8,
// all RATIFIED 2026-11-06). The module is PURE by design and imports NOTHING:
// no DOM, no network, no storage, no token -- the permission seam owns the
// token header and the caller (the 4c-2b glue) owns the round trip; every
// rule here runs headless under test (tests/test_tick_save.py) over plain
// data. Task ids are user data: ids like `__proto__` are ordinary keys
// (Map/Set semantics, never a bare object index), and every message this
// module produces is a plain string -- server text arrives control-stripped
// and capped, so the glue's textContent render is inert by construction.
//
// buildSaveRequest({ref, revision, pendingTicks})
//   -> {ok: true, path, body}  the captured W5b.2 request: path names the
//      ref as ONE percent-encoded segment, body is {ticks, expected_revision}
//      with the tick pairs COPIED (the built request is a snapshot).
//   -> {ok: false, reason}     a local refusal, reason a plain string:
//      nothing the route would 400 on ever leaves the pane.
// planSaveResponse({status, body}) -> {kind, message, ...} with kinds
//   saved / conflict / refused / invalid / forbidden / error; the caller
//   keeps the draft on every kind but "saved".
// conflictChoices({revision, pendingTicks, current})
//   -> {keepTheirs, keepMine, copyOut}  Q3(a)'s ratified three, and nothing
//      that merges: keep-mine re-stamps MY pairs on the current revision.
// describeConflict({pendingTicks, current})
//   -> [{taskId, mine, theirs, differs}]  the current tip's list against
//      the ticks, current order first, vanished pending rows appended.

const STATES = ['open', 'done', 'dropped'];
const MESSAGE_CAP = 300;

// The seam's token 403 and the read-only 403 share one pane line, because
// the author's fix is the same act: relaunch the server, writable and fresh.
const FORBIDDEN_GENERIC =
  "the server refused the save: it was started read-only (--no-write) or this page's launch token is stale - relaunch refdes serve to fix either";

function isNonEmptyString(value) {
  return typeof value === 'string' && value !== '';
}

function isPlain(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function textOf(value) {
  return typeof value === 'string' ? value : '';
}

function cleanServerText(value) {
  // Server text becomes a pane message: C0 and DEL control characters are
  // stripped (a refusal may echo an author's task text, and a pane line is
  // plain text, not a scroll of NULs), then the result is capped at 300.
  let out = '';
  for (const ch of String(value)) {
    const code = ch.codePointAt(0);
    if (code < 0x20 || code === 0x7f) continue;
    out += ch;
  }
  return out.slice(0, MESSAGE_CAP);
}

function pendingPairs(pendingTicks) {
  // The [taskId, state] pairs, shape-filtered, in the caller's order.
  const pairs = [];
  if (Array.isArray(pendingTicks)) {
    for (const entry of pendingTicks) {
      if (Array.isArray(entry) && entry.length === 2 && typeof entry[0] === 'string') {
        pairs.push([entry[0], entry[1]]);
      }
    }
  }
  return pairs;
}

function currentRows(current) {
  // The current tip's rows as the caller has them (the 409 carries no
  // structured list, only disk text): plain data, shape-filtered.
  const rows = isPlain(current) && Array.isArray(current.rows) ? current.rows : [];
  const out = [];
  for (const row of rows) {
    if (isPlain(row) && typeof row.taskId === 'string') out.push(row);
  }
  return out;
}

export function buildSaveRequest(input) {
  const source = input || {};
  if (!isNonEmptyString(source.ref)) {
    return { ok: false, reason: 'the save needs the ref of the item this pane is for' };
  }
  if (!isNonEmptyString(source.revision)) {
    return { ok: false, reason: 'the save needs the revision the list was rendered at: reload the list before saving' };
  }
  if (!Array.isArray(source.pendingTicks) || source.pendingTicks.length === 0) {
    return { ok: false, reason: 'there is nothing to save: no ticks are pending' };
  }
  const ticks = [];
  for (const entry of source.pendingTicks) {
    if (!Array.isArray(entry) || entry.length !== 2) {
      return { ok: false, reason: 'every pending tick is an id-and-state pair' };
    }
    if (!isNonEmptyString(entry[0])) {
      return { ok: false, reason: 'every pending tick names a task by a non-empty id' };
    }
    if (typeof entry[1] !== 'string' || STATES.indexOf(entry[1]) === -1) {
      return { ok: false, reason: 'a pending tick names a state outside open, done, dropped' };
    }
    ticks.push([entry[0], entry[1]]);
  }
  return {
    ok: true,
    path: '/api/item/' + encodeURIComponent(source.ref) + '/continue',
    body: { ticks: ticks, expected_revision: source.revision },
  };
}

export function planSaveResponse(response) {
  const source = response || {};
  const status = Number(source.status);
  const body = source.body;
  const serverError = isPlain(body) ? textOf(body.error) : textOf(body);

  if (status === 200 && isPlain(body) && body.kind === 'applied') {
    // The draft is cleared by the caller on this kind alone; the landing
    // spot (new revision, new entry id and handle, path) rides along.
    return {
      kind: 'saved',
      message: cleanServerText(textOf(body.message) || 'the server accepted the save'),
      revision: body.revision,
      id: body.id,
      handle: body.handle,
      path: body.path,
    };
  }
  if (status === 409 && isPlain(body) && body.kind === 'conflict') {
    // The 409 carries the CURRENT state verbatim (raw disk text, no rows):
    // nothing is merged here, and the pane's rows come from data it rendered.
    return {
      kind: 'conflict',
      message: cleanServerText(textOf(body.message) || 'the file changed since this draft was made'),
      expectedRevision: body.expected_revision,
      currentRevision: body.current_revision,
      currentText: body.current_text === undefined ? null : body.current_text,
      diff: textOf(body.diff),
    };
  }
  if (status === 422 && isPlain(body) && (body.kind === 'refused' || body.kind === 'invalid')) {
    // The fold's refusal and the gate's blocking diagnostics: the server's
    // own text is the message; the caller keeps the draft.
    return {
      kind: body.kind,
      message: cleanServerText(textOf(body.message) || textOf(body.reason) || 'the server would not take the save'),
    };
  }
  if (status === 400) {
    // The route's malformed-body gate: a shape the pane must never produce,
    // so it reads as invalid with the route's own text.
    return {
      kind: 'invalid',
      message: cleanServerText(serverError || 'the request was malformed: it should never have been sent'),
    };
  }
  if (status === 403) {
    // The read-only 403 is JSON naming --no-write (its own text); the seam's
    // token 403 is text/plain, and an empty one has nothing to read: both
    // get the one safe line naming every cause the author can act on. Only
    // the JSON error is echoed -- a text/plain body never reaches the pane.
    const jsonError = isPlain(body) ? textOf(body.error) : '';
    return { kind: 'forbidden', message: cleanServerText(jsonError) || FORBIDDEN_GENERIC };
  }
  if (status === 0) {
    // The caller caught the round trip refuse to start and hands {status:0,
    // body:{error}}: a transient, not a refusal -- and there is no status to
    // name, because there was no answer.
    const base = 'the save did not reach the server';
    return { kind: 'error', message: cleanServerText(serverError ? base + ': ' + serverError : base + ' (no answer at all)') };
  }
  // Anything unnamed (405, 415, 500, a 200 with a junk body, no status):
  // one generic safe line naming the status, never the raw body, whose
  // text/plain or HTML shapes the pane must never paint.
  const named = Number.isInteger(status) && status > 0 ? ' status ' + status : '';
  return {
    kind: 'error',
    message: 'the server answered the save with an answer the pane does not recognize' + named,
  };
}

export function conflictChoices(input) {
  const source = input || {};
  const current = isPlain(source.current) ? source.current : {};
  // A current with no usable revision cannot be re-stamped against: the
  // empty string rides into keepMine, and buildSaveRequest refuses to post
  // it -- the closed chain needs no special case here.
  const revision = isNonEmptyString(current.revision) ? current.revision : '';
  const tipIds = new Set();
  for (const row of currentRows(current)) tipIds.add(row.taskId);
  const pairs = pendingPairs(source.pendingTicks);
  const ticks = [];
  const dropped = [];
  for (const pair of pairs) {
    // MY order, MY states, only rows that still exist: no merge, ever (Q3).
    if (tipIds.has(pair[0])) ticks.push([pair[0], pair[1]]);
    else dropped.push(pair[0]);
  }
  const at = isNonEmptyString(source.revision) ? source.revision : '(unknown)';
  const nowAt = isNonEmptyString(current.revision) ? current.revision : '(unknown)';
  const lines = ['Tick draft made at ' + at + ', the file is now at ' + nowAt + ':'];
  for (const pair of pairs) lines.push(pair[0] + ': ' + String(pair[1]));
  return {
    keepTheirs: { discard: true },
    keepMine: { revision: revision, ticks: ticks, dropped: dropped },
    copyOut: { text: lines.join('\n') },
  };
}

export function describeConflict(input) {
  const source = input || {};
  const current = isPlain(source.current) ? source.current : {};
  const wanted = new Map();
  for (const pair of pendingPairs(source.pendingTicks)) wanted.set(pair[0], pair[1]);
  const tipIds = new Set();
  const rows = [];
  for (const row of currentRows(current)) {
    tipIds.add(row.taskId);
    const mine = wanted.has(row.taskId) ? wanted.get(row.taskId) : null;
    const theirs = typeof row.state === 'string' ? row.state : null;
    rows.push({ taskId: row.taskId, mine: mine, theirs: theirs, differs: mine !== null && mine !== theirs });
  }
  for (const pair of pendingPairs(source.pendingTicks)) {
    // A tick whose row vanished is APPENDED (theirs null), never silently
    // dropped: the author sees exactly which of their ticks have no target.
    if (!tipIds.has(pair[0])) {
      rows.push({ taskId: pair[0], mine: pair[1], theirs: null, differs: true });
    }
  }
  return rows;
}
