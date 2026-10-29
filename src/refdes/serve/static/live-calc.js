// Live inline-calc recalculation in the body editor
// (in-prog-logs/inline-calc-live-editor-design-20261020.md §3.1-§3.8): the
// current text of the textarea goes to `POST /api/item/<ref>/calc` on a 400 ms
// debounce, the computed rows come back, and stale result slots can be
// filled. The client interprets no grammar: the route owns the parse, the
// statuses and every message, and the response carries line-relative
// columns only (§3.3) — converting them to document offsets of the text it
// sent is owned by this module alone (§3.5). Text mutates only through
// the input pipeline of the focused textarea, so the draft, the one Save and
// the revision
// check are untouched (§3.8). Two guards decide every response (§3.6): the
// sent-text snapshot and the revision of the form; a response failing either is
// discarded silently and the next trigger re-requests.

import { api } from './api.js';

const DEBOUNCE_MS = 400;
const AUTOFILL_KEY = 'refdes.live-calc.autofill';

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function readAutofillPref() {
  try {
    return localStorage.getItem(AUTOFILL_KEY) !== 'off';
  } catch (_) {
    return true; // a storage failure costs the preference, not the default
  }
}

function writeAutofillPref(on) {
  try {
    localStorage.setItem(AUTOFILL_KEY, on ? 'on' : 'off');
  } catch (_) {
    /* per-user preference; nothing to persist where we cannot write */
  }
}

// Document offsets of a line-relative column (§3.3): the sum of the lengths
// of the preceding lines, each +1 for its newline. Every select, insertion
// and caret test below runs on converted offsets, never on raw columns —
// a span below line 0 selects the wrong range if this step is skipped.
function lineStarts(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '\n') starts.push(i + 1);
  }
  return starts;
}

function toOffsets(text, span) {
  const starts = lineStarts(text);
  const base = starts[span.line];
  if (base === undefined) return null;
  const out = { start: base + span.start, end: base + span.end };
  if (span.result_start !== undefined && span.result_end !== undefined) {
    out.resultStart = base + span.result_start;
    out.resultEnd = base + span.result_end;
  }
  return out;
}

export function createLiveCalc(handle, { getRevision, isSaving, getFields }) {
  const panel = el('section', 'live-calc');
  panel.hidden = true;

  const header = el('div', 'live-calc-head');
  header.appendChild(el('span', 'live-calc-title', 'Live inline calc'));
  const toggle = el('input', 'live-calc-autofill');
  toggle.type = 'checkbox';
  toggle.checked = readAutofillPref();
  toggle.addEventListener('change', () => writeAutofillPref(toggle.checked));
  const toggleLabel = el('label', 'live-calc-toggle');
  toggleLabel.appendChild(toggle);
  toggleLabel.appendChild(el('span', null, 'update results while I type'));
  header.appendChild(toggleLabel);
  panel.appendChild(header);

  const rowsBox = el('div', 'live-calc-rows');
  panel.appendChild(rowsBox);

  const footer = el('p', 'live-calc-note muted');
  footer.hidden = true;
  panel.appendChild(footer);

  // The Case B line (§3.5): insertText has proven to fail in this session,
  // so every fill is a .value splice and native undo may not cover it.
  const undoWarn = el('p', 'live-calc-note warn', 'native undo may not cover these fills');
  undoWarn.hidden = true;
  panel.appendChild(undoWarn);

  let area = null;
  let destroyed = false;
  let timer = null;
  let inflight = null;
  let sessionFallback = false; // Case B entered: insertText failed once
  let rows = [];
  let snapshotText = null; // the textarea value the visible rows were computed from

  function autofillActive() {
    return toggle.checked && !sessionFallback;
  }

  function renderRows(truncated) {
    rowsBox.textContent = '';
    panel.hidden = rows.length === 0;
    for (const span of rows) {
      const line = el('div', `live-calc-row live-calc-${span.status}`);
      line.appendChild(el('span', `calc-chip calc-chip-${span.status}`, span.status));
      line.appendChild(el('span', 'live-calc-name', span.name));
      if (span.computed) line.appendChild(el('span', 'live-calc-computed', span.computed));
      if (span.message) {
        const kind = span.status === 'ok' ? 'info' : span.status === 'stale' ? 'warning' : 'error';
        line.appendChild(el('span', `diag diag-${kind}`, span.message));
      }
      // Fill rides stale rows with a result slot only (§3.5): the verdict of
      // the checker makes that the safe scope; ok rows are display-only.
      if (span.status === 'stale' && span.result_start !== undefined) {
        const fill = el('button', 'btn live-calc-fill', 'Fill');
        fill.addEventListener('click', () => applySpan(span, true));
        line.appendChild(fill);
      }
      rowsBox.appendChild(line);
    }
    footer.hidden = !truncated;
    if (truncated) footer.textContent = 'showing the first 200 spans';
  }

  function clearPanel() {
    rows = [];
    snapshotText = null;
    renderRows(false);
  }

  // The one request closure every trigger runs through — debounce, blur
  // flush, focus flush, open flush (§3.1): identical, guards included.
  function run() {
    if (destroyed || !area || isSaving()) return;
    const text = area.value;
    if (!text.includes(':=')) {
      clearPanel(); // client pre-gate: no request, no panel, no churn
      return;
    }
    if (inflight) inflight.abort(); // §3.6 guard 1: supersede the in-flight request
    const controller = new AbortController();
    inflight = controller;
    const sent = text;
    api(`/api/item/${encodeURIComponent(handle)}/calc`, {
      method: 'POST',
      body: { text, fields: getFields() },
      signal: controller.signal,
    }).then((payload) => {
      if (destroyed || controller !== inflight) return;
      inflight = null;
      // §3.6 guard 2 (the correctness one): typing beat the network.
      if (area.value !== sent) return;
      // §3.6 guard 3: computed against an old model — the revision of the form,
      // never the unassigned revision variable of app.js (§1).
      if (payload.revision !== getRevision()) return;
      rows = Array.isArray(payload.spans) ? payload.spans : [];
      snapshotText = sent;
      renderRows(payload.truncated === true);
      autoFill();
    }).catch(() => {
      // AbortError from a supersede, and transport noise alike: silent.
      // The next debounce/flush re-requests.
    });
  }

  function schedule() {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      run();
    }, DEBOUNCE_MS);
  }

  function flushNow() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    run();
  }

  function autoFill() {
    // §3.5 focus rule: mutation runs only while the textarea is focused;
    // an unfocused response is display-only (rows, chips, armed Fill).
    if (!autofillActive() || isSaving() || document.activeElement !== area) return;
    const text = area.value;
    const caret = area.selectionStart;
    const targets = [];
    for (const span of rows) {
      if (span.status !== 'stale' || span.result_start === undefined) continue;
      const off = toOffsets(text, span);
      if (!off) continue;
      if (text.slice(off.resultStart, off.resultEnd) === span.computed) continue;
      // Skip a span whose result range contains the caret, inclusive of
      // both boundaries: a caret parked just after a half-typed `= 5`
      // counts as inside, so a pause never overwrites a result being typed.
      if (typeof caret === 'number' && off.resultStart <= caret && caret <= off.resultEnd) continue;
      targets.push({ span, off });
    }
    applyRanges(targets, false);
  }

  // The Fill entry (§3.5): one row through the shared apply path, consented —
  // the author invoked the insertion, so focusing the body is their request.
  function applySpan(span, consented) {
    if (isSaving() || snapshotText === null || area.value !== snapshotText) return;
    const off = toOffsets(area.value, span);
    if (!off || off.resultStart === undefined) return;
    if (area.value.slice(off.resultStart, off.resultEnd) === span.computed) return;
    applyRanges([{ span, off }], consented);
  }

  function applyRanges(targets, consented) {
    if (!targets.length) return;
    const caret0 = typeof area.selectionStart === 'number' ? area.selectionStart : area.value.length;
    let shift = 0;
    let applied = 0;
    // Last-to-first, so every earlier offset stays valid in the same pass.
    for (const target of targets.slice().reverse()) {
      if (!applyOne(target, consented)) continue;
      applied += 1;
      // Caret restore (§3.5): ranges ending before the caret move it by
      // their length delta; ranges after it contribute zero. Compare the
      // original caret — the deltas are cumulative and monotone ranges
      // below it all qualify against caret0, not against a shifted value.
      if (target.off.resultEnd < caret0) shift += target.span.computed.length - (target.off.resultEnd - target.off.resultStart);
    }
    if (!applied) return;
    area.setSelectionRange(caret0 + shift, caret0 + shift);
    if (consented) area.focus();
    // One commit for the whole batch: the draft, dirty flag and mirror
    // behave exactly as for typed text (the contract of editor.js).
    if (area._refdesCommit) area._refdesCommit();
  }

  function applyOne(target, consented) {
    const { span, off } = target;
    if (consented) area.focus();
    area.setSelectionRange(off.resultStart, off.resultEnd);
    let ok = false;
    try {
      // Case A: the native-undo-protected edit (the copy button in
      // editor.js is the in-tree precedent for using execCommand).
      ok = document.execCommand('insertText', false, span.computed) === true;
    } catch (_) {
      ok = false;
    }
    if (ok) return true;
    // Case B: insertText has proven it fails here. The splice is not
    // undo-protected, so it says so and auto-fill stands down for the
    // session (its mutation shares this path). Entered only after a
    // proven failure, never preemptively.
    if (!sessionFallback) {
      sessionFallback = true;
      undoWarn.hidden = false;
    }
    area.value = area.value.slice(0, off.resultStart) + span.computed + area.value.slice(off.resultEnd);
    return true;
  }

  const scheduleFromInput = () => schedule();
  // Blur flushes the pending schedule (§3.1): the verdict refreshes the panel,
  // arm the Fill rows — never apply text while unfocused (§3.5 focus rule).
  const flushOnBlur = () => {
    if (timer !== null) flushNow();
  };
  // Focus is a trigger of its own (§3.1): the request fires focused and —
  // text unchanged, guards passed — applies under the normal typing rules.
  const focusFlush = () => flushNow();

  const ctrl = {
    node: panel,
    // Bind once per textarea and re-arm on bodyControl (§3.8): a re-render
    // carries the node over, so a new editor instance takes it from the old
    // controller, whose listeners leave with it.
    attach(areaNode) {
      const prev = areaNode._refdesLiveCalc;
      if (prev === ctrl) return;
      if (prev) prev.detachFrom(areaNode);
      area = areaNode;
      areaNode._refdesLiveCalc = ctrl;
      areaNode.addEventListener('input', scheduleFromInput);
      areaNode.addEventListener('blur', flushOnBlur);
      areaNode.addEventListener('focus', focusFlush);
      flushNow(); // one flush on editor open: pre-existing stale spans show at once
    },
    detachFrom(areaNode) {
      areaNode.removeEventListener('input', scheduleFromInput);
      areaNode.removeEventListener('blur', flushOnBlur);
      areaNode.removeEventListener('focus', focusFlush);
      if (area === areaNode) {
        area = null;
        areaNode._refdesLiveCalc = null;
      }
    },
    destroy() {
      destroyed = true;
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      if (inflight) {
        inflight.abort();
        inflight = null;
      }
      if (area) ctrl.detachFrom(area);
    },
  };
  // The teardown sweep of the item view looks up the controller from the mounted
  // panel node (§3.8: abort the in-flight request across a rebuild).
  panel._refdesLiveCalc = ctrl;
  return ctrl;
}
