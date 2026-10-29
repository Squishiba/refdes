# Design: live inline-calc recalculation in the browser editor

Status: **Design deliverable, reviewable; no product code changed.**
Claude-lane work authorized by Jared during Sol cover, 2026-10-20. Branch
`inline-calc-live-editor-design-20261020` (docs-only PR).

Scope: the live "recalculates while I type" editor workflow for inline calc
spans. The deferred-direction note it implements is
`docs/design/inline-calc-later.md` §"Live editor updates" (lines 21–31);
the owner decisions it inherits are D1/D2/D3 of
`docs/design/inline-calc.md:16-23`. Explicitly out: solving/E-series,
calculators/pins/library, the form panel, `inline-calc fill`, anything
in the (now-wired, #381) editor journal's story — the live layer
writes no files (§3.8) — and any non-editor optimization.

Sequencing premise: this design is written against **main @ aec4dec —
main @ 1d6d325 (the R12-F1..F3 grammar work, PR #351) plus everything
merged since: slice 2 / HASH_FORMAT 6 (PR #347, `ba6d153`), the
inline-calc release gate (PR #345, `c3073c6`), the editor transaction
journal (PR #367, `3c9035b`, library; wired into saves by PR #381,
`92ae18d`), the serve path scrubbing (PR #372, `27c4fda`), and the
XLSX defined-names picker (PR #380, `7486c99`)**. Every fact in §1 and
every `file:line` citation below was re-verified against main @
78c8954 on 2026-10-26 and re-checked against aec4dec on 2026-10-29:
between the two bases only `cli.py`, `editor_journal.py`,
`serve/edit.py`, `sources.py` and `serve/sources.py` changed in `src`
(the #381 journal wiring, #380 picker, #376 agentcoder queue — the
last outside this design's surface), and the only citations into
those files moved: `src/refdes/serve/edit.py:500` → `:518` (the `load_readonly`
overlay call) and the #367 journal facts (§1, §3.8). §1 lists what
each landed PR changed. The live
layer reads the grammar's *outputs* (parse results, diagnostics text),
never re-implements the grammar, so future grammar work propagates to it
without editing this design.

## 1. Baseline: what current code already supports (all verified)

Every line cited was read at main @ 78c8954 on 2026-10-26; on
2026-10-29 every citation into a file that changed since (the
`serve/edit.py` overlay call, now `:518`) was re-read at main @
aec4dec, and the rest were confirmed unchanged in `src` between the
two bases; the §7 probes
were run on the pre-#351 tree d620ab5 (a historical record — §7 flags
the one probe result #347 has since retired) and the grammar fixes do
not change the shapes they verified.

**Grammar + evaluation (main, slice 1 `e2d497b`/PR #333, messages
`50c0faf`/PR #341, span-recognition fixes `1d6d325`/PR #351, slice 2
`ba6d153`/PR #347):**

- `src/refdes/inline_calc.py` — the whole trigger grammar is a pure,
  importable module: `contains_trigger` (:91), `code_spans(line)` (:210,
  content-only view of a line's single-backtick spans), `code_span_ranges`
  (:124, the positional `(start, end)` view — landed with #347; the
  "what a rewriter needs" docstring is :135), `parse_span` (:306,
  fills `InlineSpan` (class :71) with `name/rhs/unit/result` or an
  `error` string; the result-slot cut is computed at :347 and not
  returned), `span_cross_ref` (:270) / `span_source_call` (:287),
  `triggered_spans(body)` (:519, fence-aware walk returning `line_offset`
  per span), and `compare_stored(value, span, computed_text)` (:597) —
  returns `None` when the stored literal is inside its precision window,
  the stale message (:594, `"stored result says 5 V, now computes 4 V"`)
  otherwise, raises `calc.CalcError` for malformed/incompatible literals.
  The parse-stage "stored result missing; write '= <quantity>'" message
  is :351/:388.
- `src/refdes/build.py:_run_inline_span` (:1683) — evaluates one span by
  re-spelling it as the fence line `name = rhs | unit` (:1711-1713) and
  running it through `calc.evaluate_block` in the item-wide `env`/`origins`
  (:1716), formats the value with `calc.format_value(value,
  project.sigfigs)` (:1731), verifies with `compare_stored` (:1738).
  **Side effects to know about: it reports through `project.error`/
  `project.warn` (mutates `project.diagnostics`) and writes
  `item.calc_values` (:1736) — the live route must not reuse it on the
  serve snapshot.**
- `src/refdes/build.py:_run_item_calcs` (:1752) — the source-ordered pass:
  fences and spans as one event list sorted by body-line offset
  (:1838-1846); `env` seeds the two resolvers (:1768-1773):
  `_make_calc_resolver` (cross-item `ITEM.NAME` reads, :1588) and
  `_make_source_resolver` (lockfile-pinned `source()`, :1644).
  `run_calcs` (:1937) is the dependency-order scheduler — edges from
  fence lines *and* inline span references (docstring :1941-1948; the
  scheduler code follows) — builds
  `by_key = _key_index(project)` (:1957) and caches each item's `env`
  on `item._env` (written :1933, docstring :1752-1756).
- `src/refdes/calc.py` — the restricted evaluator (owner D3): AST-whitelist
  walk (`_eval_node` :604ff), no `eval`/`exec` anywhere (grep-verified);
  `parse_quantity` (:589), `evaluate_assignment` (:693), `format_value`
  (:981), `evaluate_block` (:1301). Evaluation of a span RHS is
  microsecond-scale (§7 probe 2: of the order of 150-350 µs per
  span, measured 158/200/358 µs for evaluate / +format / +compare).

**Serve stack (main):**

- `src/refdes/serve/server.py` — `ThreadingHTTPServer` (:269); every
  `/api/` request entering `_api` (:783) must carry the launch token
  header (:785-786), every POST additionally passes the `Origin` check
  (:789) and the 1 MiB JSON body cap `MAX_BODY_BYTES` (:45, enforced
  :805-818). A new API route inherits all of this for free.
- `src/refdes/serve/api.py` — `handle()` (:44-81) is the route registry;
  `_find_item` (:92-121) resolves handle/key/display-id/former-id;
  `edit_state` (:759-832) is the single source of editability (sealed /
  imported / body-editable flags + reasons). The precedent for the new
  route is `_source_propose` (:946-977): *"composed and checked here so
  the browser never assembles the text and never learns the grammar"*.
  The request-key posture to copy is `_apply_edit` (:1073; its
  key extraction :1087-1116): it
  extracts exactly its known keys from the JSON body and ignores the
  rest — the established unknown-key forward compatibility. Since #372
  (`27c4fda`) `handle()` also scrubs the write routes' responses to
  project-relative paths (the F13-3 choke-point,
  `_relative_paths`/`_relative_paths_in_text` :635/:716); the proposed
  calc route returns spans, text and messages only — no paths — so it
  satisfies that contract by construction.
- `src/refdes/serve/state.py` — one in-memory `Snapshot(project, revision,
  …)` per process (`Snapshot` :144), rebuilt whole under `ProjectState._lock`
  on disk change (`refresh` :265-290); `snapshot` (:245-248) is a stable
  read for one request.
- `src/refdes/loader.py:load_readonly(config, overlay={path: text})`
  (:192-223) — builds a whole project with in-memory file text. It is the
  machinery the editor's save path judges candidates with
  (`src/refdes/serve/edit.py:518` at aec4dec, `:500` at 78c8954), and it is the
   fallback mechanism for live eval — its cost measured directly for
   this doc (median of 3 `time.perf_counter` runs around one
   `load_readonly(overlay=...)` call, single-file generated projects,
   2026-10-29): **0.03 s @ 20 items, 0.33 s @ 400**. The
   `docs/performance.md:44-52` figures (0.23 s @ 20, 0.42 @ 100,
   2.02 s @ 400, 19.1 s @ 1500) are the **whole** `POST
   /api/item/<ref>/edit` handler the overlay reload is one component
   of (model reload + write + full preview render before answering,
   `docs/performance.md:18-24,97-103`). Either way: hundreds of ms
   per request at 400 items — ruled out per keystroke; see §3.
- The preview pane serves the **saved** snapshot only
  (`src/refdes/serve/preview.py:77-92`; iframe in
  `src/refdes/serve/static/item.js:205-218`); `docs/design/browser-editor.md:430-432`
  describes a debounced *unsaved* preview request — **it is not
  implemented**: the `/edit` route takes body text only to save it, and
  no route in `api.handle` evaluates unsaved text for preview. The live
  calc route proposed here is the calc-shaped first instance of that
  pattern.

**Browser editor (main):**

- One plain `<textarea>` for the body, one draft, one Save
  (`docs/design/browser-editor.md:426-428`): `editor.js` `bodyControl`
  (:190-211) binds every `input` through `writeBody` →
  `setDraftBody(handle, area.value)` (src/refdes/serve/static/drafts.js:243) and stashes the
  commit on the node as `area._refdesCommit` (:208) — the existing hook any
  insertion helper must call (see `insertIntoBody` :102-118, which uses it
  :116).
- Insertion helpers exist (`insertIntoBody`, `insertSourceLine`
  :123-159) and write `area.value` **directly** (:112, :147) — that
  pattern destroys native undo, which is exactly the constraint
  `docs/design/inline-calc-later.md:27-31` flags: try
  `document.execCommand('insertText')`, browser-test undo, keep a manual
  Fill fallback. `document.execCommand('copy')` already ships in
  `src/refdes/serve/static/editor.js:316` (guarded), so the API use is precedented.
- `src/refdes/serve/static/api.js:5-22` — the single fetch wrapper; **no `AbortController`/signal
  support** (new, ~3 additive lines).
- `src/refdes/serve/static/app.js:81,83-84,98,107-121,128` — a 2 s poll of `/api/revision`
  (:109): git badge, stale/load-error banner, and a **serial** change
  re-renders clean views via a `refdes:rebuilt` event (:112-114,125;
  poll loop `setInterval` :128).
  It keeps **no** revision current for the form: `openRevision` (:81)
  is never assigned — `setOpenRevision` (:84) and `currentRevision`
  (:83) have **zero callers in `src/` and `tests/`** (grep at
  aec4dec), and the one read (:98) sits behind a `!== null` guard, so
  that banner line is dormant. The revision the item form holds and
  saves is the editor closure's `revision` (`src/refdes/serve/static/editor.js:39`:
  `draft.revision || edit.file_revision || item.revision` — the
  item's **file** revision, the same string space as the
  `expected_revision` a save sends (:236,:251; server-side computed
  `src/refdes/serve/api.py:769-770`, served at :825, checked at :1087-1089), advanced
  by each save response (:238-239). That value — not `openRevision` —
  is what §3.6's revision guard keys on.
- No browser automation: JS is checked statically
  (`tests/test_serve_static.py`: no inline scripts, `script-src 'self'` CSP
  `src/refdes/serve/security.py:71-73`, every imported module must exist), HTTP contracts
  are tested against a live `EditorApp` (`tests/serve_support.py`,
  `tests/test_serve_edit_http.py`, `tests/test_serve_editor_e2e.py`).
  Undo/caret behavior therefore ships with a **manual browser checklist**
  (inline-calc-later.md Q8: "test undo in supported browsers; retain
  manual Fill fallback"), recorded in the implementation PR's log.

**Landed since the first draft (main @ 78c8954, plus #381 landed
since the baseline refresh to aec4dec — what each changes for this
design):**

- **PR #347 (`ba6d153`, slice 2 / HASH_FORMAT 6):** `code_span_ranges`
  (:124), `span_cross_ref` (:270) and `span_source_call` (:287) are in
  `inline_calc.py` — the live route's replacement ranges build on
  `code_span_ranges` with no branch dependency left. The cross-item span
  dependency edges are landed (`run_calcs`' scheduler,
  `src/refdes/build.py:1941-1948`, docstring), and F12-5's "has not been evaluated
  yet" error
  is gone (`src/refdes/build.py:1622-1627` records the retirement) — the live route
  resolves cross-item refs and `source()` from the snapshot exactly as a
  build will, today. Spans now enter `calc_hash_for` (:2390, arithmetic
  only — the stored result excluded), the dependency scans, and the
  content hash (`HASH_FORMAT = 6`, `src/refdes/build.py:2260`); see §6.5 for the
  hash consequences of the fields decision.
- **PR #345 (`c3073c6`, release gate):** the gate's
  `inline_calc_results` rule (`src/refdes/lifecycle.py:825`, registered
  :908; `release_gate:` is the `refdes-project.yaml` config section)
  fails a release on stale inline-calc results. The live panel's stale
  row reuses `compare_stored`'s exact message (§3.3), so "panel clean"
  keeps predicting "gate green" — no design change, one more consumer
  this layer's vocabulary must not drift from.
- **PR #367 (`3c9035b`, editor journal):** `src/refdes/editor_journal.py`
  landed library-only (begin/complete/recover for crash-safe save
  transactions) and is **now wired into saves** — see #381; §3.8 is
  reworked to the wired state.
- **PR #381 (`92ae18d`, journal wired):** verified at aec4dec —
  `serve/edit.py` imports `editor_journal` (:103) and arms/clears
  `.refdes/editor-transaction/` around every editor save
  (`begin` :2196, `complete` :2228; an unarmed write lands nowhere);
  every project-loading CLI command refuses while a journal is
  pending (`src/refdes/cli.py:133`; exempt set `init`/`recover` :111), and
  `refdes recover` restores the journaled files (help run 2026-10-29
  from this tree). The serve snapshot machinery (`state.py`,
  `api.py`) does not consult the journal — the live layer's
  read-only surface is untouched by the wiring (§3.8), and
  `docs/design/browser-editor.md`'s Status line records the wired
  state.
- **PR #372 (`27c4fda`, serve scrubbing):** write-route responses are
  scrubbed to project-relative paths at the `handle()` choke-point
  (above). The calc route carries no paths; contract satisfied by
  construction.

## 2. Decisions this design adopts (from the parked direction)

Inheriting §"Live editor updates" of inline-calc-later.md (the owner
decisions of 2026-10-25 and 2026-10-29, §6, are folded into the
sections they change):

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
  (`src/refdes/serve/static/editor.js:203-209`). A new `live-calc.js` module schedules a request
  debounced **400 ms** after the last keystroke (constant, tunable —
  owner-confirmed 2026-10-25, §6.2), **and `blur`/`focus` on the
  textarea flush the pending schedule immediately** (§6.2; focus is a
  trigger too — review 02c3d871 finding: the refocus-then-apply
  promise below is mechanical, not aspirational): a flush is a trigger
  for the same scheduled request, not a second request type — it goes
  through the identical closure and guards. Exactly one
  difference: a response landing while the textarea is **unfocused**
  is display-only — panel, chips, computed values, armed Fill rows;
  it never mutates text and never calls `focus()` (the §3.5 focus
  rule, review 6a6db80 finding 1; §3.6 covers the guards).
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
- Draft *fields* are inputs by owner decision (§6.4): the request shape
  carries a `fields` bag (§3.3) and the preview pass accepts it (§3.4).
  How a span names a field **is** decided (Jared, 2026-10-29, §6.5a:
  the cross-item dotted form, with an optional `$` sigil). What is not
  *landed* is the field reference itself: today nothing field-derived
  feeds the calc pass (verified: `_run_item_calcs` reads `item.body`
  only, `src/refdes/build.py:1785/1797/1840-1844`), so until the field-reference
  slice (§4, item G1) lands the bag is carried and unused. The client already holds
  exactly what the bag needs: the draft's field edits live in
  `draft.fields` (a plain object of scalar values, `src/refdes/serve/static/drafts.js:21`,
  `setDraftField` :236-241; collections/null are not editable,
  `src/refdes/serve/api.py:1100-1102`).
- Cross-item references and `source()` resolve against the **current
  serve snapshot** — the same `item._env` caches and lockfile records a
  build uses on today's main (the #347 scheduler and fetch-pinning are
  landed, §1). Limits to document in docs:
  - A *target's* unsaved draft is not visible (only saved targets move a
    live cross-item result; the authoritative check is at save/build).
    Fields are not this limit's case: the bag carries *this item's*
    draft fields, read locally (§3.3).
  - A `source()` key named by a span that has never been fetched is
    refused with the fetch-pins-the-span message (F12-6, retired by
    #347, in main) — same truth `refdes check` reports.
- The whole *item* pass runs over the draft body — fences too, in source
  order with the spans (`_run_item_calcs` shape) — so a span may use a
  name defined by a fence earlier in the same draft, and the
  duplicate-name rule fires live exactly as at build.

### 3.3 Route contract (new)

`POST /api/item/<handle>/calc` — JSON, token, Origin, 1 MiB cap: all
inherited from `src/refdes/serve/server.py:783-818`. Registered in `api.handle` beside the
`/edit` branch (`src/refdes/serve/api.py:49-53`).

Request: `{"text": "<current draft body>",
"fields": {"<draft field name>": <scalar>, …}}`.

- 400 `{"error": "text is required: the draft body as one string"}` for
  missing/non-string text; 400 for a `fields` value that is not a JSON
  object. `fields` is optional — absent means "no draft field edits",
  i.e. the saved item's fields. Values are scalars, mirroring the
  `set_field` scalar rule (`src/refdes/serve/api.py:1100-1102`); the bag is the draft's
  `fields` object verbatim (`src/refdes/serve/static/drafts.js:21`).
- **Unknown keys are ignored, as part of the contract**: the route
  extracts exactly its known keys, the `_apply_edit` posture
  (`src/refdes/serve/api.py:1087-1116`). This is what lets the field-reference slice
  (§4, item G1) grow the request later (e.g. a field-reference mode
  flag) without a browser/serve version lockstep. Until that slice
  lands, `fields` is
  validated and carried; the preview pass accepts and does not consult
  it (§3.4).
- 404 unknown handle (same `_find_item` posture as every item route).
- 403 `{"error": <edit_state reason>}` when `edit_state(...)` says the
  body is not editable (sealed entry, imported item) — mirrors the
  "stop the false affordance" rule at `src/refdes/serve/static/editor.js:45-53`.

Response 200:

```json
{
  "revision": "<the item's file revision the snapshot computed>",
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
  ],
  "truncated": true                 // the 200-span guard below fired;
                                    // the key is omitted entirely when
                                    // nothing was cut (no `false`)
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
  model (§3.6): **the item's file revision** the snapshot computed on —
  the same string space as the form's `expected_revision` (computed
  `src/refdes/serve/api.py:769-770`, served :825, checked :1087-1089) — not the
  project-wide `/api/revision` `revision` (`src/refdes/serve/state.py:305`), which the
  form does not hold.
- Guard: the server evaluates at most the first 200 triggered spans of
  the body, in source order, and **omits the rest**; the response then
  carries top-level `"truncated": true` (the schema key above, sibling
  of `spans` — omitted, not `false`, when nothing was cut). A truncated
  response is rendered with one panel footer line ("showing the first
  200 spans"); the §3.6 supersede guards apply to it unchanged. Per-span
  cost is 0.15-0.35 ms (§7), so a request is bounded tens of ms
  regardless.

### 3.4 Backend: the narrow preview pass (new, small)

`build.py` gains a public, **side-effect-free** sibling:

```python
def preview_inline_spans(project, item, body_text, fields=None) -> list[dict]:
```

- `fields` is the §3.3 bag, keyword-only and optional: the pass
  **accepts it from day one** so the field-reference slice (§4, item
  G1) needs no signature change, and **ignores it** until that slice
  lands (the reference syntax is decided — §6.5a; with §3.2's verified
  fact as the floor: today's
  arithmetic reads body text + snapshot envs + lockfile, nothing else).
- Mirrors `_run_item_calcs`'s pass shape: `env` seeded with
  `_make_calc_resolver(project, _key_index(project))` and
  `_make_source_resolver(project, item, records, {}, [])` (main's
  signature, `src/refdes/build.py:1644-1650`) using the snapshot's memoized
  `project._source_lock` (read-only: `citations.locked_source_value`,
  same as a build); events =
  `calc.extract_blocks_with_lines(body_text)` + `inline_calc.triggered_spans(body_text)`
  sorted by offset (same as `src/refdes/build.py:1838-1846`).
- Per span: parse → eval → `format_value(value, project.sigfigs)` →
  `compare_stored`; status/message per §3.3. Positions:
  `code_span_ranges` (main, `src/refdes/inline_calc.py:124`) for `start/end`;
  **new, small**: `parse_span`/a helper exposing the result-slot column
  range (the cut position is already computed inside `parse_span` (the
  `readings[0]` cut, `src/refdes/inline_calc.py:347`), just not returned).
- **What it must not touch**: `project.diagnostics`, `item.calc_values`,
  `item._source_uses`, lockfiles, disk. Locals for `origins`/`env`/
  `resolved`/`uses`; a test proves the snapshot is unchanged after
  requests (§5 slice A).
- The resolver reads target `item._env` — present for every local item
  after any build (the scheduler caches it, `src/refdes/build.py:1752-1756`
  docstring, written :1933); for a target that failed calc, the existing
  "target's own calc failed" message propagates (`src/refdes/build.py:1619-1620`).

Why not `load_readonly(overlay=...)` per request: mechanism exists
(`src/refdes/loader.py:192-223`, `src/refdes/serve/edit.py:518` at aec4dec) and is the right fidelity
reference. Measured directly for this doc (median of 3
`time.perf_counter` runs around one overlay load, single-file generated
projects, 2026-10-29): **0.03 s @ 20 items, 0.33 s @ 400** — and the
`docs/performance.md:44-52` figures (0.23 s @ 20, 2.02 s @ 400) are the
whole POST /edit handler the overlay reload is one component of
(model reload + write + full preview render, `docs/performance.md:18-24,
:97-103`), not the overlay alone. Either way it cannot run on a 400 ms
debounce beyond toy projects. The narrow pass costs one item's calcs
(~0.1–5 ms,
§7). The e2e test uses the overlay as the **oracle**: the panel's computed
text must equal what the overlay-build reports as the diagnostic's
computed value (§5 slice A) — narrow pass fidelity pinned by test.

### 3.5 Browser: where results show and how they insert

New module `src/refdes/serve/static/live-calc.js`, wired by `editor.js`
(one import, one construction in `createEditor`, panel mounted by
`item.js` beside the textarea where the image/source pickers mount,
`src/refdes/serve/static/item.js:176-190` — panel placement decided 2026-10-25, §6.3):

- **Panel** (`.live-calc` under the textarea): one row per span —
  `NAME` + status chip + computed value; stale rows read exactly
  "stored result says X, now computes Y" (server `message`); error rows
  show the server message, styled with the existing `diag-*` classes.
  Zero triggered spans → panel hidden. Panel is presentation only
  (`textContent` everywhere — no HTML injection).
- **Auto-fill (default ON — owner-confirmed 2026-10-25, §6.1), gated by
  a user toggle (next bullet)**: for each span with `status == "stale"`
  and a result range, when
  `computed != <current stored text in textarea>`, set
  `selectionStart/End` over the result range and
  `document.execCommand('insertText', false, computed)`, spans applied
  **last-to-first** so earlier ranges stay valid; restore the caret
  (shift by the length delta of applied ranges after the caret).
  Apply precondition: **the textarea is focused** (focus rule below —
  unfocused, nothing applies). Per-span skip: the caret sits inside
  the result range **inclusive of both boundaries** —
  `result_start <= caret <= result_end` — so a caret parked at the
  end of a partially typed result (`= 5| V`, caret after `5`) counts
  as inside and a pause never overwrites a result being typed (the
  boundary is undefined in the first draft and collides with the
  common case; review 6a6db80 finding 2); and whenever the response
  failed §3.6's guards. After the edits:
  call `area._refdesCommit()` once — the draft, dirty flag, sessionStorage
  mirror, revision gate, and conflict screen all behave exactly as for
  typed text (`src/refdes/serve/static/editor.js:96-101`'s comment is the contract).
- **Focus rule (review 6a6db80, finding 1)**: auto-fill's text
  mutation runs **only while the textarea is focused**.
  `document.execCommand('insertText')` acts on the focused editing
  host — unfocused it is a silent no-op (§3.8's undo argument then
  degrades to a `.value` write, which native undo does not cover),
  so a blur-time apply would have to call `focus()` first, as
  `insertIntoBody` does (`src/refdes/serve/static/editor.js:102-118`, focus at :115). That
  alternative (refocus-then-insert) is **rejected**: blur names the
  element the author *chose next* (Save, a Fill button, a picker),
  and stealing it mid-flow is worse than a fill that lands when the
  author returns. The codebase's `area.focus()` precedent is an
  insertion the user *invoked* by clicking Insert — focus restoration
  there is the user's own request; ambient auto-fill has no such
  consent. The owner's answer "evaluate on `blur` as well"
  (2026-10-25, §6.2) is honored exactly: blur **evaluates** — flushes
  the request, refreshes the panel, arms the Fill rows — it just
  never applies text while unfocused. Refocus is the trigger that
  makes the apply real: the textarea's `focus` event flushes the
  pending schedule (§3.1), so after the author returns the request
  fires focused and — text unchanged, §3.6 guards passed — applies
  under the normal focused-typing rules.
- **Why the gate is `stale` and not `computed != stored` (review
  96ae35f, finding 1)**: the checker *accepts* within-window literals —
  `compare_stored` returns `None` when the stored nominal is inside its
  rounding window (`src/refdes/inline_calc.py:597`, acceptance window inside the
  comparison :635-658; :555-594 is the stale-**message** widening —
  `_PLAIN_NUMBER_RE`/`_half_of_place`/`_stale_message`, not the
  window).
  Verified 2026-10-26 (in-tree; §7 inlines the reproduction):
  `` `Vout := 2.218 V * 2 = 4.4 V` `` is status **ok**
  with computed `4.436 V` — a `computed != stored` rule spanning ok
  spans would rewrite a literal the checker accepts, on every pause,
  under the default, which is exactly the silent rewrite D1 forbids
  (`docs/design/inline-calc.md:16-23`: check/build "neither silently
  rewrites it"). `ok` rows are display-only; Fill appears on stale rows
  only, which the checker's own verdict makes the safe scope.
- **The toggle (§6.1 — auto-fill and Fill coexist, and the user picks
  auto-fill):** a checkbox in the panel header ("update results while I
  type"), persisted in `localStorage` under `refdes.live-calc.autofill`.
  **Per-user browser preference, not a project setting**, because: (a)
  it is an authoring-interaction preference, like a UI theme — it changes
  no content and no verdict; (b) `refdes-project.yaml` settings are
  shared project facts that travel through review and the file hashes —
  making one author's comfort a repo-wide, PR-reviewed change inverts
  that; (c) the serve stack has no per-user identity (single local
  launch token), so the browser is the only per-user scope the editor
  has. `localStorage` (the static JS's first use of it), not the drafts'
  `sessionStorage` mirror (`src/refdes/serve/static/drafts.js:3`): a preference should outlive
  the tab, an unsaved body should not. The CSP
  (`src/refdes/serve/security.py:71-73`)
  does not touch storage access. **Default: ON** — this design's
  original recommendation (§6.1); flipping it is a one-line constant in
  `live-calc.js`. **Fill with auto-fill ON**: Fill buttons stay on
  stale rows and are idempotent — the shared apply path already skips a
  span whose stored text equals `computed` (the check above), so Fill on
  an auto-filled span is a verified no-op. **Turning the toggle off
  never loses a diagnostic**: the panel, rows, status chips and server
  messages are presentation-only (the Panel bullet above) and render
  independently of the toggle — off gates exactly one step, the text
  mutation. The `execCommand`-false session fallback
  (next bullet) is a separate mechanism; it disables auto-fill *for the
  session* and says so, independent of the stored preference.
- **Fill fallback — one path per case (review 6a6db80, finding 3)**:
  each stale row carries a `Fill` button applying that one
  replacement through auto-fill's shared apply path. **Case A** —
  `document.execCommand('insertText')` succeeds (every supported
  browser): the single native-undo-protected edit of §3.8. **Case
  B** — `insertText` returns false (undo-unsafe browser, detected
  once per session): the apply uses an `insertIntoBody`-style
  `.value` splice (`src/refdes/serve/static/editor.js:102-118`), which is **not**
  native-undo-protected — the panel shows one honest standing line
  while Case B is active ("native undo may not cover these fills"),
  auto-fill disables itself for the session and says so (its
  mutation shares the path), and rows, chips and Fill rows keep
  working. Case B is entered only after `insertText` has *proven* to
  fail in that session — never preemptively. (Fill on a focused
  textarea may restore focus to the body through the splice, as
  `insertIntoBody` does: the author invoked the insertion by
  clicking it, so that focus move is the user's own request — the
  §3.5 focus-rule consent argument covers it.)
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
   panel update). Plus the **revision guard**: the request closure
   captures the form's revision — the editor closure's `revision`
   (`src/refdes/serve/static/editor.js:39`), read through a one-line `getRevision()` accessor
   the F3 wiring exposes — and on response, discard when
   `payload.revision !== getRevision()`. Both strings live in the
   form's own string space (§3.3): a rebuild under the form, a save
   elsewhere, or this form's own save (which advanced the closure's
   `revision`, `src/refdes/serve/static/editor.js:238-239`, behind an in-flight request —
   §3.1's save-in-flight skip keeps this form's own saves from
   *firing* requests, not from racing an already-in-flight response)
   move one and not the other, so the guard fires; the next keystroke
   re-evaluates against the new model. The guard is deliberately
   **not** keyed on `app.js`'s `openRevision`: that variable is
   never assigned (§1), and `string !== null` would discard **every**
   response.

Guard 2 is the correctness one (JS is single-threaded; a late response
*applied to newer text* is the damage to make impossible); AbortController
is bandwidth/latency hygiene.

**Blur and the guards (§6.2):** the blur flush (§3.1) fires the same
scheduled closure, so it is born under both guards like any keystroke
request — no blur-specific bypass exists. Blur does not change
`area.value`, so the text-snapshot compare is against the same string;
the revision guard is unchanged (blur does not move the form's revision);
and a flush that lands while an older
request is in flight supersedes it through guard 1 exactly as fast
typing does. **What a blur-fired response does (review 6a6db80,
finding 1):** the §3.5 focus rule decides — while the textarea is
unfocused the response is **display-only**: rows, status chips,
computed values refresh, Fill rows arm, **no text mutates and no
`focus()` is called** (focus stays on the element the author moved to
— Save, a Fill button, a picker). The refocus-then-insert alternative
is rejected in §3.5's focus-rule bullet, with the `insertIntoBody`
precedent and why it does not transfer. Refocus is a trigger of its
own (§3.1): the `focus` event flushes the pending schedule, so with
the text unchanged the request fires focused and applies under the
normal focused rules, caret-skip included — the checklist's
"refocus → fills apply" is this flush, not a stored-response apply
path (none exists: unfocused responses are display-only and are not
replayed from memory). The caret rule (§3.5 skip, inclusive of
both boundaries) reads `selectionStart/selectionEnd` from the textarea
element **at apply time**, and a textarea keeps its selection after
losing focus in both Chromium and Firefox — so the skip decision for
an author who blurs with the caret parked in a result range is made
from that same caret when they return and the fill applies. The undo
story: every *applied* fill is one native-undo step (Case A, §3.8);
blur applies nothing, so the first draft's "Ctrl+Z undoes a
blur-applied fill" claim is retired with the blur-time apply.

### 3.7 Error and unsafe-expression UX

- Half-typed `Vbad := 2 V * ` → span row: ⚠ "stored result missing;
  write '= <quantity>'", no text change (probe §7, probe 2: that's exactly
  the parse-stage message; probe 2 also shows the unclosed-span case
  `` `Vnew := 1 F * 2 `` yields no span at all — silence, which is right:
  the trigger is declared intent only once the span closes).
- Eval errors (unknown name, `| V` unit mismatch, cycle, `source()`
  refusal) → span row carries the R12 message, text untouched.
- "Unsafe" has no new surface: D3's AST-whitelist evaluator is the only
  code that runs; the route reads its known keys from one JSON object,
  evaluates nothing else, writes nothing, and stands behind the
  token/Origin/1 MiB gates.
  Cost is bounded by the 200-span cap. A pathologically expensive
  expression is the *same* exposure `refdes check`/`build` already have
  (design D1 posture) — noted, not new.

### 3.8 Normal text and undo protection

- Text mutates only via `execCommand('insertText')` (undo-merged into the
  native stack), only while the textarea is focused (§3.5 focus rule),
  and only over result ranges; the 400 ms debounce means
  pauses, not mid-word, are when it fires; a result range the caret is
  inside — inclusive of both boundaries, §3.5 — is never touched.
  (Case B's `.value` splice, §3.5, is the one mutation this bullet
  does not cover, and it says so on the panel.)
- Every mutation goes through the textarea's own input pipeline (an
  `insertText` edit fires `input` → existing `writeBody` → draft), so
  there is **one** draft, one Save, one revision check — the live layer
  adds no state to `drafts.js` (draft schema untouched).
- Save in flight → no apply (§3.1); after Save each applied op is
  dropped in the save loop (`dropAppliedOp`, `src/refdes/serve/static/drafts.js:310-326`, called
  per op at `src/refdes/serve/static/editor.js:242`) and the draft is cleared (`clearDraft`,
  `src/refdes/serve/static/drafts.js:328`, called at `src/refdes/serve/static/editor.js:252`), and the form re-renders
  on the new
  revision; the next evaluation runs against the new snapshot.
- **The editor journal is wired (#381) — and the live layer needs
  nothing from it.** Verified at aec4dec: `serve/edit.py` journals
  every editor save (import :103, `begin` :2196, `complete` :2228 —
  a write whose journal cannot be armed lands nowhere), every
  project-loading CLI command refuses while a journal is pending
  (`src/refdes/cli.py:133`, exempt `init`/`recover` :111), and `refdes recover`
  restores it (help run 2026-10-29 from this tree). The journal
  journals the server-side *file writes* of a save; the live layer
  writes no file, makes exactly one read-only request (§3.3), and
  its undo stack is the browser-native one — bullets 1–3 are
  untouched. `serve/api.py` imports nothing from `editor_journal`
  and writes no file (grep-verified at aec4dec), so the proposed
  calc route joins that posture by construction: the Save that
  carries an auto-filled draft is journaled exactly as today's
  saves are. One consequence worth naming: a save that dies
  mid-write leaves a pending journal, and while it is pending the
  CLI loading commands and new serve save attempts are refused
  (`JournalPending` → refusal, `src/refdes/serve/edit.py:2197`) until `refdes
  recover` — the live panel keeps rendering from the in-memory
  snapshot (the serve snapshot machinery does not consult the
  journal: no `editor_journal` import in `serve/` outside
  `edit.py`, grep-verified). That fits the design's own posture —
  the panel is display, `check`/`build` are the verdict, and the
  verdict gate is exactly what a pending journal stops.
- Discard draft / item switch → abort in-flight request, drop panel state
  (module teardown lives beside `createEditor`'s rebuild; re-renders carry
  the textarea over via `data-edit-key`, `src/refdes/serve/static/editor.js:199`, so the module
  binds once per textarea and re-arms on `bodyControl`).

## 4. New work, itemized (everything else above is existing support)

| # | Work | File(s) | Size |
|---|---|---|---|
| B1 | `preview_inline_spans(project, item, body_text, fields=None)` — read-only per-item pass; `fields` accepted, unused until G1 (the §6.5a syntax is decided; the reference itself is not yet implemented) | `src/refdes/build.py` | ~80 lines |
| B2 | result-slot range from the parse (`parse_span` returns content-relative cut column; `triggered_spans` unchanged) | `src/refdes/inline_calc.py` | ~15 lines (`code_span_ranges` is in main, :124 — dependency retired) |
| B3 | `POST /api/item/<ref>/calc` route + guards + `fields` bag validation (shape only; G1 owns semantics) | `src/refdes/serve/api.py` | ~60 lines |
| F1 | `{signal}` support in `api()` | `src/refdes/serve/static/api.js` | ~3 lines |
| F2 | `live-calc.js`: debounce, blur/focus flush (evaluate + panel only, never applies unfocused — §3.5 focus rule; the focus flush is what lands a display-only response's fills after refocus), abort, supersede, panel (incl. truncated footer), auto-fill on stale rows only (caret-skip inclusive of result-range boundaries) + user toggle (localStorage, default ON) + idempotent Fill, Case A/B apply paths (§3.5) | new static module | ~200 lines |
| F3 | wiring: construct/teardown in `createEditor`, panel mount, save-in-flight flag, and a `getRevision()` accessor returning the editor closure's `revision` (`src/refdes/serve/static/editor.js:39`/:238-239) — §3.6's revision guard reads it (never `app.js`'s unassigned `openRevision`, §1) | `src/refdes/serve/static/editor.js`, `item.js` | ~28 lines |
| D1 | docs pass (below) | `docs/design/inline-calc-later.md` status, `docs/design/browser-editor.md` §"Editing and previewing bodies" pointer, `docs/math.md` editor sentence, `changelog.d/*.added.md` | — |
| G1 | **Follow-up slice (post-A/B/C): field references in calc spans** per §6.5a/§6.5b — the `ITEM.$field` dotted reference in the grammar and resolver, the own-item non-cycle rule, the saved-target read, and the decided policy: bare-collision resolves to the calc value **with a WARNING naming both and `ITEM.$name`**, a non-quantity field value (or unit assertion against one) is an **eval-stage error naming the field**, undeclared/empty fields **error naming the field and listing the item's declared fields**, and **no hash change** (decided: no HASH_FORMAT bump — the release gate owns the stale-result verdict) | `src/refdes/calc.py` (`CROSS_REF_RE` :1114 + the cross-ref resolver it feeds, :1499; the quantity check rides `parse_quantity` :589), `src/refdes/build.py` (cycle rule :1980 — the self-`$` exemption; reference resolution reading saved fields; collision-warning emission through the pass's existing diagnostics path). The hash definitions do not move (§6.5b decision 4) | ~80–120 lines (guess) |

Deliberate non-goals for v1: live preview of `{{name}}` substitution,
rendered-fragment preview of unsaved bodies (the rest of
docs/design/browser-editor.md:430-432 — its own design), live fence diagnostics
(the 422-on-save owns fences), iframe refresh on drafts, multi-item
live eval, collaborative locking, anything in the wired editor
journal's story (#381 — the live layer rides saves unchanged,
§3.8).

## 5. PR slices (each lands green on the full suite; A → B → C order)

**Slice A — backend, no browser change** (`POST /api/item/<ref>/calc`, B1+B2+B3)

- Tests `tests/test_calc_preview.py` (unit): ok/stale/error/missing-result
  status+message parity with the `compare_stored`/`parse_span` strings;
  computed text equals `format_value(value, project.sigfigs)`; ranges
  correct for spans on multi-span lines, tab-flanked `=` delimiters, and
  a span after a fence whose offset shifts lines (fence name used by the
  span evaluates); duplicate-name live error; cross-item ref (main's
  dependency-order `run_calcs`, `src/refdes/build.py:1937`) + `source()` refusal
  message parity; 200-span truncation; **fields inertness**: a call with
  a `fields` bag returns exactly the call without it (the §3.4
  accepted-and-unused contract, pinned until the field-reference slice
  (§4, item G1) lands);
  **no-mutation**: env/diag snapshot of `project` compared before/after
  ten preview calls.
- Tests `tests/test_serve_calc_preview.py` (HTTP, `serve_support.Client`
  live-`EditorApp` posture): 200 shape; 400 missing text; 404; 403 on a
  sealed log and on an imported item (fixture like
  `test_serve_edit_http.py`); a `fields` bag returns 200 with the same
  spans; non-object `fields` is the 400; an **unknown request key is
  ignored** (the §3.3 forward-compat contract — today's `fields` was
  once an unknown key too); `snapshot_tree` byte-identity (the
  `test_no_write.py` posture); response `revision` equals the item's
  `file_revision` as GET `/api/item/<ref>` serves it (`src/refdes/serve/api.py:825`) —
  the form's revision space (§3.6 guard 2), **not** the
  project-wide `/api/revision` `revision` (`src/refdes/serve/state.py:305`).
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
  computed value and the post-save `check` is clean; the same posture
  for an ok-within-window span (`Vout := 2.218 V * 2 = 4.4 V` →
  status ok, computed `4.436 V`, §3.5 gate): the route reports the
  computed value, never marks it stale. (Focus rule, caret boundary
  and Case B are browser behaviours — pinned by the checklist below.)
- Manual browser checklist (recorded in the PR's in-prog-logs entry, per
  inline-calc-later.md Q8): (1) type `Vbad := 2 V * 2 = 5 V` → panel
  warns live, text settles to `= 4 V` after pause; (2) Ctrl+Z **once**
  restores the author's typed text (undo-merged); (3) caret inside a
  result range **inclusive of both boundaries** — pause mid-result,
  and pause with the caret just after a partially typed `= 5` —
  blocks auto-fill for that span, its bytes never change (§3.5);
  (4) fast typing never reorders/clobbers
   typed text (supersede guard; monitor network panel); (5) stale-span
   item opened → panel warns before first keystroke; (6) toggle OFF
   (panel checkbox, §3.5): panel + diagnostics keep rendering, text
   never mutates, Fill works; toggle state survives reload and item
   switch (localStorage); (7) toggle ON: clicking Fill on an
   auto-filled span is a no-op (idempotent, §3.5); (8) blur
   mid-debounce → request fires immediately: panel refreshes and Fill
   rows arm, **no text mutates, focus stays on the blur target**
   (§3.5 focus rule); refocus with the text unchanged → the `focus`
   flush (§3.1) re-fires the request focused and the fills apply; blur with the caret parked in a result range → that
   span stays skipped at apply time and its Fill row stays offered
   (§3.6); (9) Ctrl+Z undoes an applied fill as one native step;
   Case B (force `insertText` false in devtools): the `.value` splice
   fills, the no-undo panel line shows, auto-fill self-disables for
   the session (§3.5); (10) Firefox + Chromium both pass (1)-(9) —
   (6) included, its `localStorage` toggle is per-browser storage,
   so it is checked in each — and (11) as stated next; (11) an
   ok-within-window literal
   (`Vout := 2.218 V * 2 = 4.4 V`, computed `4.436 V`, §3.5's probe):
   the row renders, **the body bytes never change** under auto-fill ON
   (the stale-gate regression pin); (12) revision guard (§3.6): type,
   then let a **second tab** (or the CLI) save the same item and the
   2 s poll rebuild land — the calc response computed against the old
   model arrives and is **discarded**: the panel refreshes, the body
   text never mutates, and after the form re-renders on the new model
   the next keystroke re-evaluates and fills apply normally; the
   normal single-tab case (save through the form, poll quiet) must
   show fills applying **after** the save — proving the guard
   discards nothing when nothing moved.
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

**Slice G1 — field references in calc spans** (follow-up, post-A/B/C;
grammar §6.5a, policy §6.5b; **nothing in it exists until it lands**)

- Tests `tests/test_calc_field_refs.py` (unit, on the `check` path):
  `collision_warns_and_resolves_to_calc` — target carries both a calc
  value and a field `name`: a bare `TARGET.name` span evaluates the
  **calc value** and one WARNING names both and the `TARGET.$name`
  spelling (§6.5b 1); `nonquantity_field_eval_error` — referencing
  `status: approved` is an eval-stage error naming the field, not a
  parse-stage message (§6.5b 2); `unit_assertion_on_nonquantity` —
  `| V` against an enum field, same eval-stage shape (§6.5b 2);
  `undeclared_field_lists_declared` / `empty_field_lists_declared` —
  each error names the field and lists the item type's declared
  fields (§6.5b 3); `own_id_dollar_not_cycle` — `LOG-PWR-002.$rds_on`
  inside LOG-PWR-002 evaluates (§6.5a 4);
  `bare_own_id_calc_ref_still_cycle` — bare self-reference keeps
  today's `calc reference cycle` error (verified at the base: the
  message is built at `src/refdes/build.py:1980`);
  `field_edit_moves_result_hash_unchanged` — editing a referenced
  field moves the computed value, leaves `calc_hash` and the content
  hash unchanged (no bump — §6.5b 4), and the release gate's
  `inline_calc_results` rule reports the stale stored result.
- Acceptance: projects with **no** field references are byte-for-byte
  unchanged in `check`/`build`/hashes; HASH_FORMAT stays 6; the §3.3
  unknown-key posture carries the forward compat (slice A's test).

## 6. Decisions (Jared, 2026-10-25; items 5-6 on 2026-10-29)

The first draft's four open questions are answered; each answer is
folded into the section it changes, and the section list is the
follow-up map. The answers opened exactly **one new question** (§6.5)
— the grammar half of decision 4. The owner answered all of it on
2026-10-29: the reference syntax is item 5 (§6.5a), and the four
policy questions (collision, unit handling, missing/empty,
hash/on_change) are item 6 (§6.5b — the drafted proposals adopted
unchanged). Nothing in §6.5 is open; §4 item G1 is implementation.
**Provenance (review 96ae35f,
finding 2):** the four answers were given by the owner in session on
2026-10-25 as replies to the first review round's open questions;
this section, mirrored in the PR's round-2 comment, is the **first
tree record** of them — no pre-existing doc carries them. If a
record outside this branch is preferred, transcribe §6.1-§6.4 into
`docs/design/inline-calc.md` as owner decisions (the same offer covers
items 5-6 / §6.5a-§6.5b).

1. **Auto-fill on typing AND the manual Fill button, toggleable.**
   Folded into §3.5: the toggle is a checkbox in the panel header,
   persisted per-user in `localStorage` (`refdes.live-calc.autofill`)
   — a browser preference, not a project setting, for the reasons §3.5
   spells out (interaction preference, not project fact; no per-user
   identity in the serve stack). Default **ON** = this design's
   original recommendation (the parked direction,
    docs/design/inline-calc-later.md:23-26); flipping the default is a one-line
   constant in `live-calc.js`. Auto-fill fires on `stale` rows only,
   not on every `computed != stored` difference (the checker accepts
   within-window literals; §3.5's gate bullet, a review-round-3 fix).
   Fill keeps working with auto-fill on and is idempotent (shared
   apply path, stored-text equality check).
   Turning auto-fill off never loses a diagnostic — the panel is
   presentation-only and independent of the toggle. Slice B grows the
   toggle (item F2) and its tests (§5 slice B, checklist (6)-(7)).
2. **Debounce 400 ms, and evaluate on `blur` as well.** Folded into
   §3.1 (blur/focus flush the pending schedule through the same
   closure; the focus flush is what makes the refocus-then-apply
   promise mechanical — review 02c3d871),
   §3.6 (blur is born under both stale-response guards: text-snapshot
   supersede compares the unchanged `area.value`, the revision guard
   is unchanged (the form's own revision is untouched by blur), and
   the flush supersedes any in-flight request via
   guard 1). Scope of "evaluate", fixed in review round 4
   (6a6db80 finding 1): the answer commits to **evaluation**, not to
   applying — a blur-fired response refreshes the panel and arms the
   Fill rows; text applies only while the textarea is focused
   (§3.5 focus rule; refocus-then-insert considered and rejected
   there, with the `insertIntoBody` precedent).
3. **Panel directly under the body textarea**, beside the image/source
   pickers (`src/refdes/serve/static/item.js:176-190`), not in the Edit-bar — as proposed;
   recorded in §3.5.
4. **Item fields ARE calc inputs.** Folded into §3.2 (inputs
   decision + what today's pass provably reads), §3.3 (request shape:
   the draft's `fields` bag verbatim — `src/refdes/serve/static/drafts.js:21`/`:236-241`;
   scalar rule; the unknown-key-ignoring posture pinned as the
   forward-compat contract), §3.4 (the preview-pass signature takes
   `fields=None` from day one; item B1/B3). **Scope of this change:
   the route contract, the preview-pass signature and forward
   compatibility — NOT the inline-calc grammar.** What a field
   reference looks like inside a span is a grammar/language decision
   owned by `docs/design/inline-calc.md` (§"1. Source form and
   trigger", :63) — **that decision landed**: the owner answered on
   2026-10-29 as item 5 below (recorded in §6.5a), with the policy
   answers as item 6 (§6.5b). Until the
   field-reference slice (§4, item G1) implements them, the bag is
   carried and the pass ignores it; what the design needs now is
   implementation, not answers.
5. **Field-reference grammar — Form A (2026-10-29).** Item fields are
   referenced with the same dotted shape as a cross-item calc value
   (`ITEM.name`), with an **optional `$` sigil** (`ITEM.$field`) that
   explicitly names the item field; a bare `ITEM.name` keeps its
   present calc-value meaning, so no existing project changes meaning.
   An own-item `$` reference (`LOG-PWR-002.$rds_on` inside
   LOG-PWR-002) is allowed and is not a calc-reference cycle; a bare
   own-id reference to a calc value stays a cycle error. Cross-item
   field references read the **saved** target (the §3.2 limit); only
   the edited item's own fields come from the editor's `fields` bag.
    Recorded with its examples, sigil rationale in §6.5a; the
    collision case it opens is decided in §6.5b (item 6).
    **Provenance:** answered by the owner
    in-session 2026-10-29 as the reply to §6.5's reference-syntax
    sub-question; §6.5a is the first tree record of it (same status as
    §6.1-§6.4 above).
6. **Field-reference policy (2026-10-29).** The four open §6.5
   policy questions are answered — the drafted proposals adopted
   **unchanged**: (i) a bare `ITEM.name` collision resolves to the
   **calc value** with a checker **WARNING naming both and the
   `ITEM.$name` spelling** (error-on-collision rejected); (ii) a
   referenced field value is parsed as a quantity, and a non-quantity
   value (or a unit assertion against one) is an **eval-stage error
   naming the field**; (iii) an undeclared field and a
   declared-but-empty/null field both **error naming the field and
   listing the item's declared fields**; (iv) **no HASH_FORMAT
   bump** — a field-driven computed-value move with `calc_hash`
   fixed is accepted and covered by the release gate
   (`inline_calc_results`), and `timeline`/`ignore` fields are
   **not** forced to `invalidate`. Recorded with the questions they
   settle in §6.5b. **Provenance:** answered by the owner in-session
   2026-10-29; §6.5b is the first tree record of them (same status
   as items 1-5).

### 6.5 Field references in calc spans: decided (2026-10-29)

Every question in this section was answered by the owner on
2026-10-29: the reference syntax (§6.5a) and the four policy
questions — collision, unit handling, missing/empty fields,
hash/on_change (§6.5b, the drafted proposals adopted **unchanged**).
Nothing in §6.5 is open; none of it is implemented today — the §4
item G1 slice is where it lands, with the tests §5 names for it.

Verified starting points (main @ 78c8954, read 2026-10-26; the files
cited here — `build.py`, `model.py`, `lifecycle.py` — are unchanged
through aec4dec, so the lines hold):

- The calc pass reads **only `item.body`** — fences and spans
  (`src/refdes/build.py:1785/1797/1840-1844`); no field value enters any
  evaluation today.
- The **content hash** payload includes every field whose `on_change`
  mode is `invalidate` (`src/refdes/build.py:2296-2303`; modes
  `src/refdes/model.py:23-26`, default `invalidate` `src/refdes/model.py:181`, item/schema/
  project precedence `src/refdes/model.py:688-694`) plus the
  whitespace-normalized **body** (:2362-2363). HASH_FORMAT 6
  (`src/refdes/build.py:2260`, landed with #347) put span arithmetic and span
  cross-item references into the hashes; resolved cross-item *values*
  entered at HASH_FORMAT 4 as `calc_refs` (`src/refdes/build.py:2318`).
- **`calc_hash_for`** (:2390-2431) hashes only body arithmetic
  (fences + spans, stored results excluded); its docstring names "a
  result changing because an upstream value moved, with this item's
  own block untouched" as a question the probe deliberately does not
  answer.
- The **release gate** (the `inline_calc_results` rule,
  `src/refdes/lifecycle.py:825`/registered :908, #345 `c3073c6`) fails a release on
  any stale stored result.

#### 6.5a Decision: reference syntax — Form A (Jared, 2026-10-29)

1. **Fields ride the cross-item dotted form.** A span names a field
   with the same shape it uses for another item's calc value:
   `ITEM.name`. The dotted RHS must be the *whole* right-hand side
   of the assignment — CROSS_REF_RE: "the whole right-hand side is
   one dotted reference into another item", with an optional pipe
   unit (`src/refdes/calc.py:1106-1114`) — so field use inside larger
   arithmetic is two steps: read the field into a name, then do
   arithmetic on that name:

   ```
   Rds := CMP-PWR-001.$rds_on | mohm = 18 mohm
   P_loss := I_load * I_load * Rds | mW = 25.92 mW
   ```

   (Both are ordinary `name := rhs [| unit] = result` spans,
   `src/refdes/inline_calc.py:306`; fence lines share the RHS matcher,
   `src/refdes/calc.py:1499`.)
2. **An optional sigil disambiguates: `ITEM.$field` explicitly names
   the item FIELD.** A bare `ITEM.name` keeps its present meaning
   (a calc value — bare names are calc variables, `CALC_NAME_RE`,
   `src/refdes/inline_calc.py:67`, used by `parse_span` :318), so no existing
   project changes meaning. The sigil is never required except to
   reach a field that shares its name with a calc value (the
   collision case — decided, §6.5b).
3. **`$` is chosen because it is free in the grammar** (checked
   against base): `#` is the comment character (first unquoted `#`
   partitions in `split_comment`, `src/refdes/calc.py:1150-1163`), `|` the unit separator (`PIPE_UNIT_RE`
   :1105), `@` the composite key (CROSS_REF_RE's target half,
   :1115-1116), `.` the reference dot — exactly one, a dotted
   reference with two or more is rejected as block-qualified
   (`BLOCK_QUALIFIED_REF_RE`, :1122), so a dot sigil is out — `=`
   the span result delimiter, `:` part of `:=` (`NAME_ASSIGN_RE`,
   `src/refdes/inline_calc.py:30`), `+ - * / ^` the operators. `~` as an
   explicit calc sigil was considered and rejected by the owner
   ("feels odd"): there is **no calc sigil**.
4. **Own-item fields are not a cycle.** An item's own display id
   with the `$` form — `LOG-PWR-002.$rds_on` inside LOG-PWR-002 —
   must be allowed and must **not** be a calc-reference cycle.
   Today a bare own-id reference is one (verified 2026-10-29:
   `DEC-PWR-001.x` inside DEC-PWR-001 reports
   `calc reference cycle: DEC-PWR-001 -> DEC-PWR-001` from
   `refdes --no-write -c refdes-project.yaml check` on a scratch
   copy; the message is built at `src/refdes/build.py:1980`). A bare own-id
   reference to a calc value stays a cycle error.
5. **Read rule.** Cross-item field references read the **saved**
   target, exactly like cross-item calc refs (§3.2's limit); only
   the edited item's own fields come from the editor's `fields` bag
   (§3.3). Fields are static, so the dependency scan gains no new
   order edges beyond the self case (the live-layer bullet below).

#### 6.5b Decisions: policy (Jared, 2026-10-29)

The owner adopted all four drafted proposals **unchanged** on
2026-10-29. Each decision is recorded under the question it settles —
the question text stays as the record of the decision's scope.

1. **Collision (the case §6.5a decision 2 opens).** A bare
   `ITEM.name` where the target item has **both** a calc value and a
   field of that name resolves to the **calc value** (today's
   behaviour), and the checker emits a **WARNING naming both and the
   `$` spelling** (`ITEM.$name`) — because a calc added later could
   otherwise silently shadow a field a span used to read.
   Error-on-collision stays **rejected**: with no calc sigil
   (§6.5a decision 3) it would leave the calc value unspellable.
2. **Unit handling of field values.** Field values are YAML scalars
   of arbitrary shape (`status: approved`, `limit: 5 V`, free text).
   A referenced value is parsed as a quantity (the
   `calc.parse_quantity` shape, `src/refdes/calc.py:589`); a **non-quantity**
   value — and any `| V`-style unit assertion against one — is an
   **eval-stage error naming the field** (the unit-assertion shape,
   not the parse-stage shape of "stored result missing",
   `src/refdes/inline_calc.py:351`: the field reference itself parsed fine; it
   is the value that fails).
3. **Missing/empty field behavior.** A field the item's type does
   **not declare**, and a field declared but **empty/null**, are
   both an **error naming the field and listing the item's declared
   fields** (the unknown-name shape extended with the declaration
   list, so the author sees what *is* referencable). The bag's shape
   note stands: the editor carries scalars only — collections/null
   are not editable (`src/refdes/serve/api.py:1100-1102`) — so list-valued fields
   (`checks:`) stay out of the v1 bag.
4. **Hash / stale consequences.** Rely on the **release gate**
   (`inline_calc_results`, `src/refdes/lifecycle.py:825`, registered :908): a
   field edit may move a referencing span's computed value while
   `calc_hash` stays fixed (the arithmetic-only probe,
   `src/refdes/build.py:2390`) — **accepted**; the gate fires on exactly the
   stale stored result a field-driven move produces, so correctness
   has a verdict gate without a hash change. **No HASH_FORMAT bump
   when G1 lands** (HASH_FORMAT stays 6, `src/refdes/build.py:2260`); the
   format-7 path — field values entering the content hash the way
   resolved cross-item values entered at format 4 (`calc_refs`,
   `src/refdes/build.py:2318`), with #347's gated-bump precedent — stays
   available later if hash consumers are judged to need
   field-driven moves. Fields in `on_change: timeline`/`ignore`
   mode — invisible to the content hash (`src/refdes/build.py:2298-2299`) —
   are **not** forced to `invalidate`.
- **Live-layer consequences (listed for completeness, none
  blocking).** The bag is this item's own draft, read locally —
  §3.2's "a target's unsaved draft is not visible" limit does not
  apply to fields, so the panel can show field-driven results for
  unsaved field edits while `check`-at-save stays the verdict.
  Fields are local, so the dependency scan needs **no** new
  cross-item edges; with the hash decision taken (§6.5b decision
  4: no bump), neither the hash definitions nor the scheduler move
  at all.

## 7. Probes (verification record)

Scratch project: `.scratch/inline-calc-live-20261020/probe/` (2 items;
`DEC-001` body carries a good span, a stale span, a half-typed span, and
a cross-item span; `SRC-001` defines `V_in = 5.1 V` in a fence). CLI run
from the worktree (`PYTHONPATH=src python -m refdes.cli`, d620ab5):

**Reproducibility (reviews 96ae35f finding 4, 6a6db80 finding 4):**
the scratch dirs named here are gitignored and not part of the PR, so
the behavioural claims are **inlined below** — run from the checkout
with `PYTHONPATH=src python`; a reviewer re-ran them 2026-10-26 and
all four outcomes reproduced. The **timings** (per-span cost of the
order of 150-350 µs depending on what is included — measured
158/200/358 µs for `evaluate_block` / +`format_value` / +`compare_stored`
on a 2026-10-26 review run; original drafting mean ~130 µs — and the
0.011 s overlay floor) are indicative; §3.4's scaling argument leans
on the committed `docs/performance.md:44-52` table, not on them.

```python
# §3.5/§3.7 claims, from the tree (PYTHONPATH=src python):
from refdes import inline_calc, calc

cases = ["Vout := 2.218 V * 2 = 4.4 V",  # ok, computed 4.436 V (§3.5 gate)
         "Vbad := 2 V * 2 = 5 V",        # stale: "stored result says 5 V, ..."
         "Vhalf := 3 V *"]               # parse: "stored result missing; ..."
for text in cases:
    span = inline_calc.parse_span(0, text)
    if span.error:
        print(text, "-> parse error:", span.error)
        continue
    expr = f"{span.name} = {span.rhs}" + (f" | {span.unit}" if span.unit else "")
    for outcome in calc.evaluate_block(expr, {}):
        if outcome.error or outcome.value is None:   # build.py guards alike
            continue
        computed = calc.format_value(outcome.value, 4)
        verdict = inline_calc.compare_stored(outcome.value, span, computed)
        print(text, "-> computed", computed,
              "| status:", "ok" if verdict is None else f"stale ({verdict})")
# and: inline_calc.triggered_spans("`Vnew := 1 F * 2") == []  (unclosed: silence)
# fill round-trip: after writing `computed` over the stored literal
# ("Vbad := 2 V * 2 = 4 V"), the same loop prints status: ok.
```

1. `refdes check` reports, at `items/items.yaml`:
   `WARNING … inline calc Vbad: stored result says 5 V, now computes 4 V`;
   `ERROR … inline calc Vhalf := 3 V *: stored result missing; write '= <quantity>'`;
   `ERROR … inline calc Vref: cross-item reference 'SRC-001.V_in': SRC-001
   has not been evaluated yet …` (a record of that tree, d620ab5:
   main's F12-5 gap — retired by #347, §1; on today's main this probe's
   cross-item span resolves through the scheduler); diagnostics carry
   `file:line` + `item_id`
   (`api._diagnostics_for` posture, `src/refdes/serve/api.py:123-139`).
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
     (this is what makes §3.5's auto-fill stable, not oscillating;
     the probe covers the **stale** case — ok-within-window literals
     are by design never rewritten, hence the §3.5 gate);
    - `load_readonly` warm floor 0.011 s on this toy project (the
      `docs/performance.md:44-52` table is the scale reference).

Line counts: this file is a **deliverable report**, which AGENTS.md
exempts from the 150-line cap on task-progress logs ("a deliverable
report … is the work product itself, has no length cap"); the
companion progress log is the capped task log.
