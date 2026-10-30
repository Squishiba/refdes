// Live inline-calc recalculation in the body editor
// (in-prog-logs/inline-calc-live-editor-design-20261020.md §3.1-§3.8): the
// textarea's current text goes to `POST /api/item/<ref>/calc` on a 400 ms
// debounce, the computed rows come back, and stale result slots can be
// filled. A field edit on the form schedules the same request (fields are
// calc inputs, §3.2/§6.4): the request carries the draft's field bag
// (§3.3), so the panel rows follow what the author typed. The client
// interprets no grammar: the route owns the parse, the
// statuses and every message, and the response carries line-relative
// columns only (§3.3) — converting them to document offsets of the text it
// sent is this module's alone (§3.5). Text mutates only through the focused
// textarea's own input pipeline, so the draft, the one Save and the revision
// check are untouched (§3.8). Two guards decide every response (§3.6): the
// sent-text snapshot and the form's revision; a response failing either is
// discarded silently and the next trigger re-requests.

import { api } from './api.js';

const DEBOUNCE_MS = 400;
const AUTOFILL_KEY = 'refdes.live-calc.autofill';
// §3.5: once insertText has proven it fails here, auto-fill stands down for
// the whole SESSION -- and a browser session outlives every controller (a
// save, a poll rebuild and an item switch each build a new one), so the flag
// lives in sessionStorage, not in a closure. sessionStorage is per-tab and
// dies with the tab: exactly the session §3.5 names. The formatting bar shares
// this session truth (formatbar.js); one detection serves both consumers.
const FALLBACK_KEY = 'refdes.live-calc.fallback';
// Mirrors build.PREVIEW_SPAN_LIMIT (src/refdes/build.py); the static test
// pins the two numbers against each other.
const PREVIEW_SPAN_LIMIT = 200;

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

function readFallbackFlag() {
  try {
    return sessionStorage.getItem(FALLBACK_KEY) === 'on';
  } catch (_) {
    return false; // a storage failure costs the stand-down, not a crash
  }
}

function writeFallbackFlag() {
  try {
    sessionStorage.setItem(FALLBACK_KEY, 'on');
  } catch (_) {
    /* the splice warning still shows; only persistence is lost */
  }
}

// The starts are computed once per response batch (the text is the same for
// every span in it); spanOffsets converts one span against them.
// The server's columns are PYTHON string indices = Unicode code points
// within the line; JS string offsets and textarea selection indices are
// UTF-16 code units. A BMP character (combining marks included) is one unit
// in both; only astral code points (above U+FFFF — every emoji) cost two,
// so a raw column addition lands one unit early per astral character
// earlier on the same line. cpToUnits advances cp code points and counts
// their UTF-16 length; a column past the line's last code point clamps to
// the line's end (the same tolerance a textarea gives setSelectionRange).
function cpToUnits(line, cp) {
  let units = 0;
  for (let seen = 0; seen < cp && units < line.length; seen++) {
    units += line.codePointAt(units) > 0xffff ? 2 : 1;
  }
  return units;
}

function spanOffsets(starts, text, span) {
  const base = starts[span.line];
  if (base === undefined) return null;
  if (span.result_start === undefined || span.result_end === undefined) return null;
  const next = starts[span.line + 1];
  const line = text.slice(base, next === undefined ? text.length : next - 1);
  return {
    resultStart: base + cpToUnits(line, span.result_start),
    resultEnd: base + cpToUnits(line, span.result_end),
  };
}

// Guard 3's progress memory (round 7): the server revision last re-synced
// for each handle. A re-sync that did not fix the baseline (a state the
// shell's re-render cannot reach) must not fire again for the SAME dropped
// revision -- that is the storm: drop -> re-render -> attach flush -> drop.
// Keyed by handle, so a genuinely NEW model revision fires again.
const lastStaleSync = new Map();

export function createLiveCalc(handle, { getRevision, isSaving, getFields,
  revisionFromDraft = () => false }) {
  const panel = el('section', 'live-calc');
  panel.hidden = true;

  const header = el('div', 'live-calc-head');
  header.appendChild(el('span', 'live-calc-title', 'Live inline calc'));
  const toggle = el('input', 'live-calc-autofill');
  toggle.type = 'checkbox';
  // Session fallback (§3.5): read at construction, so every controller the
  // shell rebuilds (save, poll, item switch) starts out stood down. The
  // checkbox shows the EFFECTIVE state, not the stored preference: it never
  // reads ON while the session stand-down is suppressing mutation.
  let sessionFallback = readFallbackFlag();
  toggle.checked = readAutofillPref() && !sessionFallback;
  toggle.addEventListener('change', () => {
    const on = toggle.checked && !sessionFallback;
    writeAutofillPref(on);
    toggle.checked = on;
  });
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

  // The session stand-down line (§3.5): shown whenever auto-fill is off
  // for the session, at construction too -- a rebuilt controller says so
  // before its first response, because the state is the session's, not
  // this panel's.
  const sessionOff = el(
    'p',
    'live-calc-note warn',
    'auto-fill is off for this session (undo is unavailable here); Fill still works',
  );
  sessionOff.hidden = !sessionFallback;
  panel.appendChild(sessionOff);

  let area = null;
  let destroyed = false;
  let timer = null;
  let inflight = null;
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
      // Fill rides stale rows with a result slot only (§3.5): the checker's
      // own verdict makes that the safe scope; ok rows are display-only.
      // A span with only one boundary is not fillable — the apply path
      // needs the full pair, so the button appears on the pair alone.
      if (span.status === 'stale' && span.result_start !== undefined && span.result_end !== undefined) {
        const fill = el('button', 'btn live-calc-fill', 'Fill');
        fill.addEventListener('click', () => applySpan(span, true));
        line.appendChild(fill);
      }
      rowsBox.appendChild(line);
    }
    footer.hidden = !truncated;
    if (truncated) footer.textContent = `showing the first ${PREVIEW_SPAN_LIMIT} spans`;
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
      // never app.js's unassigned openRevision (§1). Dropping stays silent, but
      // the drop proves the form's baseline trails the served model (a rebuild
      // can land between the view's GET and the poll's baseline capture), so
      // tell the shell to re-sync: it re-renders the view behind the draft
      // (drafts.js survives it) and the next request carries a fresh revision.
      // While a save is running the signal is suppressed: the editor advances
      // the form's own revision after saveAll's first op, so a pre-save
      // response is LEGITIMATELY stale, and re-rendering the pane now would
      // leave saveAll writing against detached DOM (a conflict box would
      // render invisibly). The save re-renders at its end and the next
      // request carries the fresh revision — skipping loses nothing.
      // The same reasoning covers a DRAFT-backed baseline (dropAppliedOp
      // persists draft.revision after a partial save + 409): the form
      // INTENTIONALLY trails the model while the author resolves the
      // conflict, so every response is legitimately stale and a re-render
      // only destroys the conflict box and re-fires the drop forever.
      // Belt: fire at most once per distinct dropped revision per handle —
      // if the re-sync did not fix it, it will not.
      if (payload.revision !== getRevision()) {
        if (!isSaving() && !revisionFromDraft() && window.dispatchEvent
            && lastStaleSync.get(handle) !== payload.revision) {
          lastStaleSync.set(handle, payload.revision);
          window.dispatchEvent(new CustomEvent('refdes:stale-calc', { detail: payload.revision }));
        }
        return;
      }
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
    const starts = lineStarts(text); // once per batch: every span converts against it
    const targets = [];
    for (const span of rows) {
      // Auto-fill's stale gate: a non-stale row is never touched, and a
      // span missing either boundary of its result pair is skipped -- the
      // apply path needs the full pair to splice.
      if (span.status !== 'stale' || span.result_start === undefined || span.result_end === undefined) continue;
      const off = spanOffsets(starts, text, span);
      if (!off) continue;
      if (text.slice(off.resultStart, off.resultEnd) === span.computed) continue;
      if (selectionSkips(off)) continue;
      targets.push({ span, off });
    }
    applyRanges(targets, false);
  }

  // The author's live selection owns any text it touches (§3.5 caret rule):
  // a caret parked anywhere in a result range, inclusive of both boundaries,
  // counts as inside -- a pause never overwrites a result being typed. A
  // NON-collapsed selection is inside anything it overlaps: bytes selected
  // at the moment a fill lands are bytes the author is working on.
  function selectionSkips(off) {
    const s = area.selectionStart;
    const e = area.selectionEnd;
    if (typeof s !== 'number') return false;
    if (s === e) return off.resultStart <= s && s <= off.resultEnd;
    return s < off.resultEnd && e > off.resultStart;
  }

  // The Fill entry (§3.5): one row through the shared apply path, consented —
  // the author invoked the insertion, so focusing the body is their request.
  function applySpan(span, consented) {
    if (isSaving() || snapshotText === null || area.value !== snapshotText) return;
    const off = spanOffsets(lineStarts(area.value), area.value, span);
    if (!off) return;
    if (area.value.slice(off.resultStart, off.resultEnd) === span.computed) return;
    applyRanges([{ span, off }], consented);
  }

  function applyRanges(targets, consented) {
    if (!targets.length) return;
    const caret0 = typeof area.selectionStart === 'number' ? area.selectionStart : area.value.length;
    let shift = 0;
    let applied = 0;
    let spliced = false;
    // Last-to-first, so every earlier offset stays valid in the same pass.
    for (const target of targets.slice().reverse()) {
      const outcome = applyOne(target, consented);
      if (!outcome) continue;
      if (outcome === 'splice') spliced = true;
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
    // behave exactly as for typed text (editor.js's contract).
    if (area._refdesCommit) area._refdesCommit();
    // A Case B splice fires no input event, so nothing would re-request on
    // its own: schedule the recalculation the commit cannot, keeping the
    // panel (and a focused textarea's auto-fill) current with the text.
    if (spliced) schedule();
  }

  function applyOne(target, consented) {
    const { span, off } = target;
    if (consented) area.focus();
    area.setSelectionRange(off.resultStart, off.resultEnd);
    let ok = false;
    try {
      // Case A: the native-undo-protected edit (editor.js's copy button is
      // the in-tree precedent for using execCommand).
      ok = document.execCommand('insertText', false, span.computed) === true;
    } catch (_) {
      ok = false;
    }
    if (ok) return true;
    // Case B: insertText has proven it fails here. The splice is not
    // undo-protected, so it says so and auto-fill stands down for the
    // SESSION (its mutation shares this path): the flag goes to
    // sessionStorage, so the next controller the shell builds is born
    // stood down. Entered only after a proven failure, never preemptively.
    if (!sessionFallback) {
      sessionFallback = true;
      writeFallbackFlag();
      undoWarn.hidden = false;
      sessionOff.hidden = false;
    }
    area.value = area.value.slice(0, off.resultStart) + span.computed + area.value.slice(off.resultEnd);
    return 'splice';
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
    // A field edit is a calc input (design §3.2/§6.4, slice C): the same
    // debounced request re-fires through the identical closure, and the
    // fresh bag rides it (§3.3). With the textarea unfocused the response
    // is display-only by §3.5's focus rule -- rows and Fill refresh, no
    // text mutates.
    fieldsChanged() {
      if (area) schedule();
    },
  };
  // The teardown sweep of the item view looks up the controller from the mounted
  // panel node (§3.8: abort the in-flight request across a rebuild).
  panel._refdesLiveCalc = ctrl;
  return ctrl;
}
