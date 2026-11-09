/* The tick pane's SAVE seam (docs/design/thread-workbench-w5b-plan.md §4
   W5b.4 + §6 Q3/Q5/Q6/Q8, RATIFIED 2026-11-06): the pane's ONLY network
   module, and it decides nothing of its own -- the request and the reading of
   every answer are tick-save.js's, the rows of the CURRENT page are read
   through tick-pane.js's panelFromRows (the reader the load used), the draft
   is tick-drafts.js's. The seam owns the round trip, the launch token, the
   Save button and the conflict panel, so taskpane-ticks.js stays as pure of
   the network as W5b.3 left it: it imports this module and hands it its
   panels with one call.

   initSave({ drafts, panels, refreshPanel }): a Save button joins each panel
   that can draft -- hidden with no pending tick, disabled in flight. It posts
   buildSaveRequest's path (the panel's tip KEY: the identity that survives a
   rename, Q5a) with the draft's revision, the session cookie (same-origin
   credentials) and the token read from the page's meta AT SAVE TIME into
   X-Refdes-Token and nowhere else: never a URL, never storage, never text.
   The answers are Q3 (a), ratified: saved discards and reloads onto the new
   tip; refused/invalid/forbidden/error put the server's own (capped) text in
   a role=alert line and KEEP the draft for a retry; conflict re-reads the
   current page -- the 409 carries no task rows -- and offers exactly Keep mine
   / Keep theirs / Copy it out, and nothing that merges. No beforeunload here:
   the glue owns the page's one prompt (Q8). */

import { buildSaveRequest, planSaveResponse, conflictChoices, describeConflict } from './tick-save.js';
import { panelFromRows } from './tick-pane.js';

function tokenValue() {
  // a token baked at module load survives nothing: read the page's meta now
  const meta = document.querySelector('meta[name="refdes-token"]');
  return meta && typeof meta.content === 'string' ? meta.content : '';
}

function hostOf(panel) {
  return panel.panelEl && typeof panel.panelEl.appendChild === 'function' ? panel.panelEl : null;
}

function currentOf(node) {
  // the CURRENT tip as the model wants it, read through the reader the load
  // used: the descriptor rows of the panel element, in the page's own order,
  // and a row with no id is no row at all.
  const tipKey = node.getAttribute('data-refdes-tip-key') || '';
  const revision = node.getAttribute('data-refdes-revision') || '';
  const raw = [];
  for (const box of node.querySelectorAll('input[data-refdes-task]')) {
    raw.push({
      taskId: box.getAttribute('data-refdes-task') || '',
      state: box.getAttribute('data-refdes-task-state') || '',
      tickStates: box.getAttribute('data-refdes-tick-states') || '',
      checked: Boolean(box.checked),
    });
  }
  const model = panelFromRows({ tipKey, revision, rows: raw });
  const rows = [];
  model.rows.forEach((row, at) => {
    if (row.taskId !== '') rows.push({ taskId: row.taskId, state: raw[at].state });
  });
  return { tipKey, revision, rows };
}

function line(host, text, className) {
  const node = document.createElement('p');
  if (className) node.className = className;
  node.textContent = text;
  host.appendChild(node);
  return node;
}

function makeButton(label, host, onClick) {
  const node = document.createElement('button');
  node.type = 'button';
  node.textContent = label;
  node.addEventListener('click', onClick);
  host.appendChild(node);
  return node;
}

function copyItOut(host, text) {
  // the author's own escape hatch: MY lines, MY order, in a read-only
  // transcript that stands whether or not the clipboard answers.
  const area = document.createElement('textarea');
  area.readOnly = true;
  area.value = text;
  host.appendChild(area);
  try {
    // a refused clipboard costs the copy, never the pane -- and a refusal
    // in a real browser is an ASYNC rejection the catch below cannot see:
    // swallow it too, or the pane leaks an unhandledRejection.
    const copied = navigator.clipboard.writeText(text);
    if (copied && typeof copied.catch === 'function') copied.catch(() => {});
  } catch (_) {
    // no permission, no clipboard API on a plain-HTTP origin: the textarea
    // on the page IS the copy, and the pane keeps working.
  }
}

async function bodyOf(response) {
  try {
    return await response.json();
  } catch (_) {
    return await response.text(); // a text/plain 403 has no JSON to read
  }
}

async function postSave(request, token) {
  try {
    const response = await fetch(request.path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Refdes-Token': token },
      body: JSON.stringify(request.body),
    });
    return planSaveResponse({ status: response.status, body: await bodyOf(response) });
  } catch (err) {
    // no status is invented for a round trip that refused to start
    const reason = err && typeof err.message === 'string' ? err.message : '';
    return planSaveResponse({ status: 0, body: { error: reason } });
  }
}

async function currentPage(panel) {
  // the 409 names no task rows, so the CURRENT list comes from the page the
  // pane stands on: a same-origin GET with the browser's own cookies and NO
  // token header, read out of the page text.
  const response = await fetch(location.href, { credentials: 'same-origin' });
  const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
  for (const node of parsed.querySelectorAll('.refdes-taskpane-panel')) {
    if (node.getAttribute('data-refdes-tip-key') === panel.tipKey) return currentOf(node);
  }
  return null;
}

function wirePanel(panel, drafts, refreshPanel) {
  const host = hostOf(panel);
  if (!host) return;
  const save = document.createElement('button');
  save.type = 'button';
  save.className = 'refdes-taskpane-save';
  save.textContent = 'Save';
  save.hidden = true;
  host.appendChild(save);
  let inFlight = false;

  function draw() {
    save.hidden = drafts.pendingCount(panel.tipKey) === 0;
    save.disabled = inFlight;
  }

  function clearOld() {
    for (const node of host.querySelectorAll('[role]')) {
      if (node.getAttribute('role') === 'alert') node.remove();
    }
    for (const node of host.querySelectorAll('.refdes-taskpane-conflict')) node.remove();
  }

  function say(message) {
    const node = document.createElement('p');
    node.className = 'refdes-taskpane-save-message small muted';
    node.setAttribute('role', 'alert');
    node.textContent = message;
    host.appendChild(node);
  }

  function release() {
    if (typeof refreshPanel === 'function') refreshPanel(panel);
    location.reload();
  }

  function keepMine(current) {
    // Q3(a) Keep mine: MY ticks on the CURRENT identity -- the current tip
    // key, the revision the page carries now -- on rows that still exist
    // only. A vanished row is dropped, never invented back: nothing merges.
    // The pairs are read at CLICK time, not frozen when the panel was
    // shown: the panel stands while the author keeps ticking, and choices
    // computed at show time would discard the draft and re-store the OLD
    // pairs, losing every later tick.
    const choices = conflictChoices({
      revision: drafts.revision(panel.tipKey) || panel.revision,
      pendingTicks: drafts.pendingTicks(panel.tipKey),
      current: current || {},
    });
    drafts.discard(panel.tipKey);
    for (const pair of choices.keepMine.ticks) {
      const row = current.rows.filter((one) => one.taskId === pair[0])[0];
      drafts.setTick(current.tipKey, pair[0], pair[1], row ? row.state : pair[1]);
    }
    drafts.setRevision(current.tipKey, current.revision);
    release();
  }

  function keepTheirs() {
    // Q3(a) Keep theirs: the explicit release of my draft onto their list.
    drafts.discard(panel.tipKey);
    release();
  }

  function showConflict(message, current, pendingTicks) {
    const choices = conflictChoices({
      revision: drafts.revision(panel.tipKey) || panel.revision,
      pendingTicks,
      current: current || {},
    });
    const box = document.createElement('div');
    box.className = 'refdes-taskpane-conflict';
    host.appendChild(box);
    line(box, message, 'refdes-taskpane-conflict-head small muted');
    if (!current) {
      // Keep mine would stamp onto a panel the page does not show: the two
      // outcomes that need no rows are the only two offered.
      line(box, 'this page has no panel for this thread any more: nothing here to keep your ticks against');
      makeButton('Keep theirs', box, keepTheirs);
      makeButton('Copy it out', box, () => copyItOut(box, choices.copyOut.text));
      return;
    }
    for (const row of describeConflict({ pendingTicks, current })) {
      const theirs = row.theirs === null ? 'gone' : row.theirs;
      const mine = row.mine === null ? '-' : row.mine;
      line(box, row.taskId + ': yours ' + mine + ', the file has ' + theirs);
    }
    makeButton('Keep mine', box, () => keepMine(current));
    makeButton('Keep theirs', box, keepTheirs);
    makeButton('Copy it out', box, () => copyItOut(box, choices.copyOut.text));
  }

  save.addEventListener('click', async () => {
    if (inFlight) return;
    clearOld();
    const request = buildSaveRequest({
      ref: panel.tipKey,
      revision: drafts.revision(panel.tipKey) || panel.revision,
      pendingTicks: drafts.pendingTicks(panel.tipKey),
    });
    if (!request.ok) {
      say(request.reason); // a local refusal: nothing left the pane
      draw();
      return;
    }
    inFlight = true;
    draw();
    const plan = await postSave(request, tokenValue());
    if (plan.kind === 'saved') {
      drafts.discard(panel.tipKey);
      release(); // the new entry is the tip; the re-render is the server's
      return;
    }
    inFlight = false;
    if (plan.kind !== 'conflict') {
      say(plan.message);
      draw();
      return;
    }
    let current = null;
    let unreadable = false;
    try {
      current = await currentPage(panel);
    } catch (_) {
      unreadable = true;
    }
    if (unreadable) {
      say(plan.message + ' (and the current page could not be read)');
      draw();
      return;
    }
    showConflict(plan.message, current, drafts.pendingTicks(panel.tipKey));
    draw();
  });

  host.addEventListener('change', draw);
  draw();
}

export function initSave({ drafts, panels, refreshPanel }) {
  for (const panel of Array.isArray(panels) ? panels : []) {
    // a tip with no key cannot be named by a save: its ticks stay exactly
    // as the pane's indicator already says -- preview-only.
    if (!panel || !panel.canDraft || !panel.tipKey) continue;
    wirePanel(panel, drafts, refreshPanel);
  }
}
