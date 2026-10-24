# Design: live inline-calc recalculation in the browser editor

Status: **Design deliverable, reviewable; no product code changed.**
Claude-lane work authorized by Jared during Sol cover, 2026-10-20. Branch
`inline-calc-live-editor-design-20261020` (docs-only PR).

Scope: the live "recalculates while I type" editor workflow for inline calc
spans. The deferred-direction note it implements is
`docs/design/inline-calc-later.md` §"Live editor updates" (lines 21–31);
the owner decisions it inherits are D1/D2/D3 of
`docs/design/inline-calc.md:9-16`. Explicitly out: solving/E-series,
calculators/pins/library, the form panel, `inline-calc fill`, transaction
journaling, any non-editor optimization.

Sequencing premise: this design is written against **main @ 1d6d325 (which
merged the R12-F1..F3 grammar work as PR #351: inert HTML comments,
ambiguous-span flagging, the tight result separator) plus the still-open
slice-2 (PR #347, `feat-inline-calc-slice2-hash`, HASH_FORMAT 6) and
release-gate (PR #345) branches merged — #347/#345 are open at writing
time and nothing below assumes they have landed**. Where a fact
below depends on #347, it says so. The live layer reads the grammar's
*outputs* (parse results, diagnostics text), never re-implements the
grammar, so future grammar work propagates to it without editing this
design.

## 1. Baseline: what current code already supports (all verified)

Every line cited was read at main @ 1d6d325 (citations re-checked against
it; the §7 probes were run on the pre-#351 tree d620ab5 and the grammar
fixes do not change the shapes they verified); branch-only items are
marked.

**Grammar + evaluation (main, slice 1 `e2d497b`/PR #333, messages
`50c0faf`/PR #341, span-recognition fixes `1d6d325`/PR #351):**

- `src/refdes/inline_calc.py` — the whole trigger grammar is a pure,
  importable module: `contains_trigger` (:89), `code_spans(line)` (:122,
  content-only view of a line's single-backtick spans), `parse_span` (:224,
  fills `InlineSpan` with `name/rhs/unit/result` or a `error` string),
  `triggered_spans(body)` (:417, fence-aware walk returning `line_offset`
  per span), and `compare_stored(value, span, computed_text)` (:478) —
  returns `None` when the stored literal is inside its precision window,
  the stale message (`"stored result says 5 V, now computes 4 V"`)
  otherwise, raises `calc.CalcError` for malformed/incompatible literals.
- `src/refdes/build.py:_run_inline_span` (:1651) — evaluates one span by
  re-spelling it as the fence line `name = rhs | unit` (:1679-1682) and
  running it through `calc.evaluate_block` in the item-wide `env`/`origins`
  (:1684), formats the value with `calc.format_value(value,
  project.sigfigs)` (:1699), verifies with `compare_stored` (:1706).
  **Side effects to know about: it reports through `project.error`/
  `project.warn` (mutates `project.diagnostics`) and writes
  `item.calc_values` (:1704) — the live route must not reuse it on the
  serve snapshot.**
- `src/refdes/build.py:_run_item_calcs` (:1719) — the source-ordered pass:
  fences and spans as one event list sorted by body-line offset
  (:1810-1818); `env` seeds two   resolvers (:1739-1744):
  `_make_calc_resolver` (cross-item `ITEM.NAME` reads, :1538) and
  `_make_source_resolver` (lockfile-pinned `source()`, :1603).
  `run_calcs` (:1913) builds `by_key = _key_index(project)` (:1929) and
  caches each item's `env` on `item._env`.
- `src/refdes/calc.py` — the restricted evaluator (owner D3): AST-whitelist
  walk (`_eval_node` :604ff), no `eval`/`exec` anywhere (grep-verified);
  `parse_quantity` (:589), `evaluate_assignment` (:693), `format_value`
  (:981), `evaluate_block` (:1301). Evaluation of a span RHS is
  microsecond-scale (§7 probe 2: ~130 µs/span warm).

**Serve stack (main):**

- `src/refdes/serve/server.py` — `ThreadingHTTPServer` (:269); every
  `/api/` request must carry the launch token header (:785-786), every POST
  additionally passes the `Origin` check (:789) and the 1 MiB JSON body cap
  `MAX_BODY_BYTES` (:45, enforced :805-819). A new API route inherits all
  of this for free.
- `src/refdes/serve/api.py` — `handle()` (:41-76) is the route registry;
  `_find_item` (:89-122) resolves handle/key/display-id/former-id;
  `edit_state` (:172-244) is the single source of editability (sealed /
  imported / body-editable flags + reasons). The precedent for the new
  route is `_source_propose` (:359-387): *"composed and checked here so the
  browser never assembles the text and never learns the grammar"*.
- `src/refdes/serve/state.py` — one in-memory `Snapshot(project, revision,
  …)` per process, rebuilt whole under `ProjectState._lock` on disk change
  (:265-290); `snapshot` (:245-248) is a stable read for one request.
- `src/refdes/loader.py:load_readonly(config, overlay={path: text})`
  (:192-223) — builds a whole project with in-memory file text. It is the
  machinery the editor's save path judges candidates with
  (`serve/edit.py:470`), and it is the fallback mechanism for live eval —
  full-build floor: 0.23 s @ 20 items, 0.42 s @ 100, 2.0 s @ 400, 19.1 s @
  1500 (`docs/performance.md:44-51`). That rules it out per keystroke at
  400+ items; see §3.
- The preview pane serves the **saved** snapshot only
  (`src/refdes/serve/preview.py:77-92`; iframe in
  `src/refdes/serve/static/item.js:205-218`); `docs/design/browser-editor.md:429-431`
  describes a debounced *unsaved* preview request — **it is not
  implemented**: the `/edit` route takes body text only to save it, and
  no route in `api.handle` evaluates unsaved text for preview. The live
  calc route proposed here is the calc-shaped first instance of that
  pattern.

**Browser editor (main):**

- One plain `<textarea>` for the body, one draft, one Save
  (`docs/design/browser-editor.md:425-427`): `editor.js` `bodyControl`
  (:190-212) binds every `input` through `writeBody` →
  `setDraftBody(handle, area.value)` (drafts.js:243) and stashes the
  commit on the node as `area._refdesCommit` (:208) — the existing hook any
  insertion helper must call (see `insertIntoBody` :102-118, which uses it
  :116).
- Insertion helpers exist (`insertIntoBody`, `insertSourceLine`
  :123-159) and write `area.value` **directly** (:112, :147) — that
  pattern destroys native undo, which is exactly the constraint
  `docs/design/inline-calc-later.md:27-31` flags: try
  `document.execCommand('insertText')`, browser-test undo, keep a manual
  Fill fallback. `document.execCommand('copy')` already ships in
  `editor.js:316` (guarded), so the API use is precedented.
- `api.js:5-22` — the single fetch wrapper; **no `AbortController`/signal
  support** (new, ~3 additive lines).
- `app.js:81,96-105,107-128` — a 2 s poll of `/api/revision` keeps
  `openRevision` current; a revision change re-renders clean views. That
  is the live layer's staleness signal for "the server model moved under
  the form".
- No browser automation: JS is checked statically
  (`tests/test_serve_static.py`: no inline scripts, `script-src 'self'` CSP
  `security.py:71-73`, every imported module must exist), HTTP contracts
  are tested against a live `EditorApp` (`tests/serve_support.py`,
  `tests/test_serve_edit_http.py`, `tests/test_serve_editor_e2e.py`).
  Undo/caret behavior therefore ships with a **manual browser checklist**
  (inline-calc-later.md Q8: "test undo in supported browsers; retain
  manual Fill fallback"), recorded in the implementation PR's log.

**Branch dependencies (open PRs, not in main):**

- PR #347 adds to `src/refdes/inline_calc.py`: **`code_span_ranges(line)`
  — the positional (start, end) view of a line's spans** ("what a rewriter
  needs", branch step 1), plus `span_cross_ref` / `span_source_call`. The
  live route's replacement ranges are built on it. It also adds the
  cross-item span dependency edges that retire main's
  `build.py:1581-1587` "has not been evaluated yet" error (run-12 F12-5),
  and makes `refdes fetch` pin span `source()` keys (retires F12-6), so
  after #347 the live route resolves cross-item refs and `source()` from
  the snapshot exactly as a build will.
- PR #345 (release gate) is orthogonal; it changes nothing the live layer
  reads.

## 2. Decisions this design adopts (from the parked direction)

Inheriting §"Live editor updates" of inline-calc-later.md:

1. Evaluation happens **only in Python** (owner D3) — the browser sends
   body text and receives computed ranges/text; it never learns the
   grammar, never parses `:=` (locator work is §3.1's single
   `indexOf`-level exception, validity-checked server-side).
2. The result-writing into the draft is **a text edit, not a save** — it
   rides the existing draft → one-Save → revision-check/conflict pipeline
   (`docs/design/browser-editor.md` "Drafts…"), like the source-picker
   insert.
3. Apply replacements **from the end of the body toward the start**, skip
   any span whose result range contains the caret; half-typed/failing
   spans leave the text untouched and show the diagnostic.
4. Native undo via `document.execCommand('insertText')`, with a manual
   **Fill** button as the retained fallback if the browser check fails.
5. The preview pane stays the as-published view of **saved** text (D2);
   live recalc is a panel beside the textarea, not iframe refresh.

## 3. The smallest viable workflow

### 3.1 When evaluation happens

- Trigger: the body textarea's existing `input` path
  (`editor.js:203-209`). A new `live-calc.js` module schedules a request
  debounced **400 ms** after the last keystroke (constant, tunable).
- Client pre-gate: skip (and clear any panel) when the current text
  contains no `:=` substring — no request, no panel, no churn. This gate
  is an optimization only; the server is authoritative.
- Skip while a Save round-trip is in flight (module flag set by the
  editor's save flow); the post-save re-render re-arms evaluation against
  the new snapshot.
- No polling, no interval: evaluation is keystroke-driven + one flush on
  editor open (an opened item with pre-existing stale spans shows the
  panel immediately — the author sees today's `check` warning live).

### 3.2 What source text it evaluates

- The textarea's **current value** — the unsaved draft body, verbatim.
  Not the file, not the draft after Save.
- Draft *fields* are not inputs: calc scope is body text + cross-item
  target envs + the lockfile; field values (status, enums…) feed nothing
  in inline calc (verified: `_run_item_calcs` reads `item.body` only,
  `build.py:1757/1783/1810-1818`).
- Cross-item references and `source()` resolve against the **current
  serve snapshot** — the same `item._env` caches and lockfile records a
  build would use post-#347. Limits to document in docs:
  - A *target's* unsaved draft is not visible (only saved targets move a
    live cross-item result; the authoritative check is at save/build).
  - A `source()` key named by a span that has never been fetched is
    refused with the post-#347 fetch-pins-the-span message — same truth
    `refdes check` reports.
- The whole *item* pass runs over the draft body — fences too, in source
  order with the spans (`_run_item_calcs` shape) — so a span may use a
  name defined by a fence earlier in the same draft, and the
  duplicate-name rule fires live exactly as at build.

### 3.3 Route contract (new)

`POST /api/item/<handle>/calc` — JSON, token, Origin, 1 MiB cap: all
inherited from `server.py:785-819`. Registered in `api.handle` beside the
`/edit` branch (`api.py:46-50`).

Request: `{"text": "<current draft body>"}`.

- 400 `{"error": "text is required: the draft body as one string"}` for
  missing/non-string text.
- 404 unknown handle (same `_find_item` posture as every item route).
- 403 `{"error": <edit_state reason>}` when `edit_state(...)` says the
  body is not editable (sealed entry, imported item) — mirrors the
  "stop the false affordance" rule at `editor.js:45-53`.

Response 200:

```json
{
  "revision": "<snapshot.revision>",
  "spans": [
    {
      "line": 4,                    // 0-indexed line in `text`
      "start": 3, "end": 41,        // span content range on that line
                                    // (code_span_ranges: between the
                                    // backticks, exclusive)
      "result_start": 33, "result_end": 38,  // stored-result range within
                                             // the line (parse_span's cut
                                             // + content offset)
      "name": "Vout",
      "status": "ok" | "stale" | "error",
      "computed": "4.436 V",        // format_value(value, sigfigs); "" for
                                    // parse/eval errors
      "message": ""                 // the R12 diagnostic text verbatim;
                                    // "" when status == "ok"
    }
  ]
}
```

- One entry per **triggered** span, source order. Untriggered code spans
  and fence diagnostics are not reported (the save-time 422 owns fences;
  v1 keeps this route's contract to spans).
- `status: "error"` covers parse-stage errors ("stored result missing;
  write '= <quantity>'" — the half-typed case), eval failures (unknown
  name, unit assertion mismatch, `source()` refusals), and malformed
  stored literals; the message is exactly the text `refdes check` will
  report, so the panel teaches the CLI's vocabulary.
- `result_start/-end` is absent when the span has no parseable result
  slot; auto-fill and Fill are then unavailable for that span.
- `"revision"` lets the browser discard responses computed against an old
  model (§3.6).
- Guard: server evaluates at most the first 200 triggered spans of the
  body and appends `{"truncated": true}`; per-span cost is ~0.13 ms (§7),
  so a request is bounded tens of ms regardless.

### 3.4 Backend: the narrow preview pass (new, small)

`build.py` gains a public, **side-effect-free** sibling:

```python
def preview_inline_spans(project, item, body_text) -> list[dict]:
```

- Mirrors `_run_item_calcs`'s pass shape: `env` seeded with
  `_make_calc_resolver(project, _key_index(project))` and
  `_make_source_resolver(project, item, records, {}, [], [True])` using the
  snapshot's memoized `project._source_lock` (read-only:
  `citations.locked_source_value`, same as a build); events =
  `calc.extract_blocks_with_lines(body_text)` + `inline_calc.triggered_spans(body_text)`
  sorted by offset (same as `build.py:1810-1818`).
- Per span: parse → eval → `format_value(value, project.sigfigs)` →
  `compare_stored`; status/message per §3.3. Positions:
  `code_span_ranges` (#347) for `start/end`; **new, small**:
  `parse_span`/a helper exposing the result-slot column range (the cut
  position is already computed inside `parse_span` (the `readings[0]`
  cut, `inline_calc.py:265`), just not returned).
- **What it must not touch**: `project.diagnostics`, `item.calc_values`,
  `item._source_uses`, lockfiles, disk. Locals for `origins`/`env`/
  `resolved`/`uses`; a test proves the snapshot is unchanged after
  requests (§5 slice A).
- The resolver reads target `item._env` — present for every local item
  after any build (`run_calcs` caches it, `build.py:1721-1723` docstring);
  for a target that failed calc, the existing "target's own calc failed"
  message propagates (`build.py:1565-1571`).

Why not `load_readonly(overlay=...)` per request: mechanism exists
(`loader.py:192-223`, `serve/edit.py:470`) and is the right fidelity
reference — it is 0.23 s @ 20 items and 2.0 s @ 400
(`docs/performance.md:44-51`), so it cannot run on a 400 ms debounce
beyond toy projects. The narrow pass costs one item's calcs (~0.1–5 ms,
§7). The e2e test uses the overlay as the **oracle**: the panel's computed
text must equal what the overlay-build reports as the diagnostic's
computed value (§5 slice A) — narrow pass fidelity pinned by test.

### 3.5 Browser: where results show and how they insert

New module `src/refdes/serve/static/live-calc.js`, wired by `editor.js`
(one import, one construction in `createEditor`, panel mounted by
`item.js` beside the textarea where the image picker mounts,
`item.js:176-191`):

- **Panel** (`.live-calc` under the textarea): one row per span —
  `NAME` + status chip + computed value; stale rows read exactly
  "stored result says X, now computes Y" (server `message`); error rows
  show the server message, styled with the existing `diag-*` classes.
  Zero triggered spans → panel hidden. Panel is presentation only
  (`textContent` everywhere — no HTML injection).
- **Auto-fill (recommended default, per the parked direction)**: for each
  span with `status` ok/stale and a result range, when
  `computed != <current stored text in textarea>`, set
  `selectionStart/End` over the result range and
  `document.execCommand('insertText', false, computed)`, spans applied
  **last-to-first** so earlier ranges stay valid; restore the caret
  (shift by the length delta of applied ranges after the caret). Skip a
  span when the caret sits inside its result range (author mid-edit),
  when the textarea is not focused *and* the caret is inside the span
  range, and whenever the response failed §3.6's guards. After the edits:
  call `area._refdesCommit()` once — the draft, dirty flag, sessionStorage
  mirror, revision gate, and conflict screen all behave exactly as for
  typed text (`editor.js:96-101`'s comment is the contract).
- **Fill fallback**: each stale row carries a `Fill` button applying that
  one replacement through the same code path. If
  `document.execCommand('insertText')` returns false (undo-unsafe
  browser), auto-fill disables itself for the session, the panel says so
  in one line, and only the Fill buttons remain — they take the same
  `insertText` path, so a browser where it fails gets a manual splice
  through the `insertIntoBody`-style `.value` write with the honest
  panel note "native undo may not cover this insertion".
- The stored-result text is the **only** text the live layer writes:
  name, `:=`, RHS, unit, backticks are the author's.

### 3.6 Stale-response cancellation (two independent guards)

1. **Abort**: module keeps the in-flight `AbortController`; each new
   debounced request aborts the previous one; `api()` gains an optional
   `{signal}` (3 additive lines in `api.js`, mirrors the existing shape),
   `AbortError` is swallowed silently.
2. **Text-snapshot supersede (authoritative)**: the request closure
   captures the exact string sent; on response, if
   `area.value !== sent`, discard (typing beat the network — no apply, no
   panel update). Plus: discard when `payload.revision !== openRevision`
   (the poll moved the model: the server computed against a snapshot the
   form no longer holds; the next keystroke re-evaluates against the new
   one).

Guard 2 is the correctness one (JS is single-threaded; a late response
*applied to newer text* is the damage to make impossible); AbortController
is bandwidth/latency hygiene.

### 3.7 Error and unsafe-expression UX

- Half-typed `Vbad := 2 V * ` → span row: ⚠ "stored result missing;
  write '= <quantity>'", no text change (probe §7, probe 2: that's exactly
  the parse-stage message; probe 2 also shows the unclosed-span case
  `` `Vnew := 1 F * 2 `` yields no span at all — silence, which is right:
  the trigger is declared intent only once the span closes).
- Eval errors (unknown name, `| V` unit mismatch, cycle, `source()`
  refusal) → span row carries the R12 message, text untouched.
- "Unsafe" has no new surface: D3's AST-whitelist evaluator is the only
  code that runs; the route accepts one JSON string, evaluates nothing
  else, writes nothing, and stands behind the token/Origin/1 MiB gates.
  Cost is bounded by the 200-span cap. A pathologically expensive
  expression is the *same* exposure `refdes check`/`build` already have
  (design D1 posture) — noted, not new.

### 3.8 Normal text and undo protection

- Text mutates only via `execCommand('insertText')` (undo-merged into the
  native stack) and only over result ranges; the 400 ms debounce means
  pauses, not mid-word, are when it fires; a result range the caret is
  inside is never touched.
- Every mutation goes through the textarea's own input pipeline (an
  `insertText` edit fires `input` → existing `writeBody` → draft), so
  there is **one** draft, one Save, one revision check — the live layer
  adds no state to `drafts.js` (draft schema untouched).
- Save in flight → no apply (§3.1); after Save the draft is cleared
  (`drafts.js dropAppliedOp` :309-326) and the form re-renders on the new
  revision; the next evaluation runs against the new snapshot.
- Discard draft / item switch → abort in-flight request, drop panel state
  (module teardown lives beside `createEditor`'s rebuild; re-renders carry
  the textarea over via `data-edit-key`, `editor.js:199`, so the module
  binds once per textarea and re-arms on `bodyControl`).

## 4. New work, itemized (everything else above is existing support)

| # | Work | File(s) | Size |
|---|---|---|---|
| B1 | `preview_inline_spans(project, item, body_text)` — read-only per-item pass | `src/refdes/build.py` | ~80 lines |
| B2 | result-slot range from the parse (`parse_span` returns content-relative cut column; `triggered_spans` unchanged) | `src/refdes/inline_calc.py` | ~15 lines (needs #347's `code_span_ranges` merge) |
| B3 | `POST /api/item/<ref>/calc` route + guards | `src/refdes/serve/api.py` | ~50 lines |
| F1 | `{signal}` support in `api()` | `src/refdes/serve/static/api.js` | ~3 lines |
| F2 | `live-calc.js`: debounce, abort, supersede, panel, auto-fill + Fill, execCommand fallback | new static module | ~180 lines |
| F3 | wiring: construct/teardown in `createEditor`, panel mount, save-in-flight flag | `src/refdes/serve/static/editor.js`, `item.js` | ~25 lines |
| D1 | docs pass (below) | `docs/design/inline-calc-later.md` status, `docs/design/browser-editor.md` §"Editing and previewing bodies" pointer, `docs/math.md` editor sentence, `changelog.d/*.added.md` | — |

Deliberate non-goals for v1: live preview of `{{name}}` substitution,
rendered-fragment preview of unsaved bodies (the rest of
browser-editor.md:429-431 — its own design), live fence diagnostics
(the 422-on-save owns fences), iframe refresh on drafts, multi-item
live eval, collaborative locking, transaction journaling.

## 5. PR slices (each lands green on the full suite; A → B → C order)

**Slice A — backend, no browser change** (`POST /api/item/<ref>/calc`, B1+B2+B3)

- Tests `tests/test_calc_preview.py` (unit): ok/stale/error/missing-result
  status+message parity with the `compare_stored`/`parse_span` strings;
  computed text equals `format_value(value, project.sigfigs)`; ranges
  correct for spans on multi-span lines, tab-flanked `=` delimiters, and
  a span after a fence whose offset shifts lines (fence name used by the
  span evaluates); duplicate-name live error; cross-item ref (post-#347
  ordering) + `source()` refusal message parity; 200-span truncation;
  **no-mutation**: env/diag snapshot of `project` compared before/after
  ten preview calls.
- Tests `tests/test_serve_calc_preview.py` (HTTP, `serve_support.Client`
  live-`EditorApp` posture): 200 shape; 400 missing text; 404; 403 on a
  sealed log and on an imported item (fixture like
  `test_serve_edit_http.py`); `snapshot_tree` byte-identity (the
  `test_no_write.py` posture); response `revision` equals
  `/api/revision.revision`.
- **Oracle test** (the fidelity pin): for each status, build
  `loader.load_readonly(overlay={item_path: text})` and assert the full
  build reports the same computed/stale message for the span the route
  returned — the narrow pass may not drift from the real build.
- Acceptance: `refdes check` behavior byte-for-byte unchanged (route is
  additive); full suite green; serve startup unchanged.

**Slice B — browser** (F1+F2+F3)

- Python-side: extend `tests/test_serve_static.py` conventions (module
  exists/importable by the shell); e2e story addition in
  `tests/test_serve_editor_e2e.py` posture: draft a stale span via
  `/api/item/<ref>/calc`, apply the computed text, save through the
  normal edit route with the form's revision, assert file bytes carry the
  computed value and the post-save `check` is clean.
- Manual browser checklist (recorded in the PR's in-prog-logs entry, per
  inline-calc-later.md Q8): (1) type `Vbad := 2 V * 2 = 5 V` → panel
  warns live, text settles to `= 4 V` after pause; (2) Ctrl+Z **once**
  restores the author's typed text (undo-merged); (3) caret mid-result
  blocks auto-fill for that span; (4) fast typing never reorders/clobbers
  typed text (supersede guard; monitor network panel); (5) stale-span
  item opened → panel warns before first keystroke; (6) Fill button
  works with auto-fill disabled via a one-line module flag; (7) Firefox +
  Chromium both pass (1)-(5).
- Acceptance: checklist green; save/conflict flow tests
  (`test_serve_edit_http*`) untouched; no draft-schema change.

**Slice C — docs** (D1)

- `docs/design/inline-calc-later.md`: "Live editor updates" status line
  (implemented by this design's slices, decisions recorded);
  `docs/design/browser-editor.md`: one pointer sentence in §"Editing and
  previewing bodies" (the unsaved-preview paragraph gets its calc half
  landed, with the route name); `docs/math.md` author sentence ("the
  editor recalculates spans while you type; `check`/`build` remain the
  verdict"); changelog fragment `*.added.md`.
- Acceptance: docs-verified per AGENTS.md (every claim re-run against the
  commands it names).

## 6. Open questions for the owner

1. **Auto-fill on typing vs Fill-button-only.** The parked direction
   (inline-calc-later.md:23-26) describes auto-applying replacement
   ranges; this design auto-fills with the caret/undo guards above.
   If Jared wants text to move only on explicit Fill, slice B drops
   §3.5's auto path — everything else stands.
2. **Debounce constant** (400 ms proposed) and whether to evaluate on
   `blur` as well.
3. **Panel placement** — proposed: directly under the body textarea
   (beside the image/source pickers, `item.js:176-191`), not in the
   Edit-bar.
4. **Draft-field visibility**: fields are not calc inputs (§3.2) —
   confirm no future inline calc reads item fields, else the request
   shape grows a `fields` bag (route keeps forward compatibility by
   ignoring unknown keys).

## 7. Probes (verification record)

Scratch project: `.scratch/inline-calc-live-20261020/probe/` (2 items;
`DEC-001` body carries a good span, a stale span, a half-typed span, and
a cross-item span; `SRC-001` defines `V_in = 5.1 V` in a fence). CLI run
from the worktree (`PYTHONPATH=src python -m refdes.cli`, d620ab5):

1. `refdes check` reports, at `items/items.yaml`:
   `WARNING … inline calc Vbad: stored result says 5 V, now computes 4 V`;
   `ERROR … inline calc Vhalf := 3 V *: stored result missing; write '= <quantity>'`;
   `ERROR … inline calc Vref: cross-item reference 'SRC-001.V_in': SRC-001
   has not been evaluated yet …` (main's F12-5 gap — retired by #347,
   §1); diagnostics carry `file:line` + `item_id`
   (`api._diagnostics_for` posture, `api.py:125-139`).
2. `probe_live.py` (same dir):
   - `code_spans` content-only confirmed (no offsets — positional view is
     #347's `code_span_ranges`);
   - half-typed `Vbad := 2 V * 2 = ` → `InlineSpan.error = "stored result
     missing; write '= <quantity>'"`; an unclosed backtick span produces
     no span (silent, by design);
   - evaluator-only per-span cost **~130 µs** (2000-iter warm mean,
     `evaluate_block` + `format_value`);
   - **fill round-trip**: replacing the stored literal with
     `format_value(value, sigfigs)` makes `compare_stored` return `None` —
     auto-fill's output passes the next evaluation and the CLI check
     (this is what makes §3.5's auto-fill stable, not oscillating);
   - `load_readonly` warm floor 0.011 s on this toy project (the
     `docs/performance.md:44-51` table is the scale reference).

Line counts: this file is the deliverable report; the companion progress
log is capped separately.
