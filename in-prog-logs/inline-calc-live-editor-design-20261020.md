# Design: live inline-calc recalculation in the browser editor

Status: **Design deliverable, reviewable; no product code changed.**
Claude-lane work authorized by Jared during Sol cover, 2026-10-20. Branch
`inline-calc-live-editor-design-20261020` (docs-only PR).

Scope: the live "recalculates while I type" editor workflow for inline calc
spans. The deferred-direction note it implements is
`docs/design/inline-calc-later.md` §"Live editor updates" (lines 21–31);
the owner decisions it inherits are D1/D2/D3 of
`docs/design/inline-calc.md:16-23`. Explicitly out: solving/E-series,
calculators/pins/library, the form panel, `inline-calc fill`, wiring the
landed editor-journal module into saves (#367 — the live layer writes no
files), any non-editor optimization.

Sequencing premise: this design is written against **main @ 78c8954 —
main @ 1d6d325 (the R12-F1..F3 grammar work, PR #351) plus everything
merged since: slice 2 / HASH_FORMAT 6 (PR #347, `ba6d153`), the
inline-calc release gate (PR #345, `c3073c6`), the standalone editor
transaction journal (PR #367, `3c9035b` — library-only, not wired into
saves), and the serve path scrubbing (PR #372, `27c4fda`)**. Every fact
in §1 and every `file:line` citation below was re-verified against that
main on 2026-10-26 (§1 lists what each landed PR changed). The live
layer reads the grammar's *outputs* (parse results, diagnostics text),
never re-implements the grammar, so future grammar work propagates to it
without editing this design.

## 1. Baseline: what current code already supports (all verified)

Every line cited was read at main @ 78c8954 on 2026-10-26; the §7 probes
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
  fence lines *and* inline span references (:1941-1946) — builds
  `by_key = _key_index(project)` (:1957) and caches each item's `env`
  on `item._env` (written :1933, docstring :1752-1756).
- `src/refdes/calc.py` — the restricted evaluator (owner D3): AST-whitelist
  walk (`_eval_node` :604ff), no `eval`/`exec` anywhere (grep-verified);
  `parse_quantity` (:589), `evaluate_assignment` (:693), `format_value`
  (:981), `evaluate_block` (:1301). Evaluation of a span RHS is
  microsecond-scale (§7 probe 2: ~130 µs/span warm).

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
  The request-key posture to copy is `_apply_edit` (:1087-1116): it
  extracts exactly its known keys from the JSON body and ignores the
  rest — the established unknown-key forward compatibility. Since #372
  (`27c4fda`) `handle()` also scrubs the write routes' responses to
  project-relative paths (the F13-3 choke-point,
  `_relative_paths`/`_relative_paths_in_text` :635/:716); the proposed
  calc route returns spans, text and messages only — no paths — so it
  satisfies that contract by construction.
- `src/refdes/serve/state.py` — one in-memory `Snapshot(project, revision,
  …)` per process (`Snapshot` :144), rebuilt whole under `ProjectState._lock`
  on disk change (`refresh` :267-291); `snapshot` (:245-248) is a stable
  read for one request.
- `src/refdes/loader.py:load_readonly(config, overlay={path: text})`
  (:192-223) — builds a whole project with in-memory file text. It is the
  machinery the editor's save path judges candidates with
  (`serve/edit.py:500`), and it is the fallback mechanism for live eval —
  full-build floor: 0.23 s @ 20 items, 0.42 s @ 100, 2.02 s @ 400, 19.1 s
  @ 1500 (`docs/performance.md:44-52`). That rules it out per keystroke at
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
  (:190-211) binds every `input` through `writeBody` →
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
- `app.js:81,93-104,107-121,128` — a 2 s poll of `/api/revision` keeps
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

**Landed since the first draft (all in main @ 78c8954 now — what each
changes for this design):**

- **PR #347 (`ba6d153`, slice 2 / HASH_FORMAT 6):** `code_span_ranges`
  (:124), `span_cross_ref` (:270) and `span_source_call` (:287) are in
  `inline_calc.py` — the live route's replacement ranges build on
  `code_span_ranges` with no branch dependency left. The cross-item span
  dependency edges are landed (`run_calcs`' scheduler,
  `build.py:1941-1946`), and F12-5's "has not been evaluated yet" error
  is gone (`build.py:1622-1627` records the retirement) — the live route
  resolves cross-item refs and `source()` from the snapshot exactly as a
  build will, today. Spans now enter `calc_hash_for` (:2390, arithmetic
  only — the stored result excluded), the dependency scans, and the
  content hash (`HASH_FORMAT = 6`, `build.py:2260`); see §6.5 for the
  hash consequences of the fields decision.
- **PR #345 (`c3073c6`, release gate):** the gate's
  `inline_calc_results` rule (`src/refdes/lifecycle.py:825`, registered
  :908; `release_gate:` is the `refdes-project.yaml` config section)
  fails a release on stale inline-calc results. The live panel's stale
  row reuses `compare_stored`'s exact message (§3.3), so "panel clean"
  keeps predicting "gate green" — no design change, one more consumer
  this layer's vocabulary must not drift from.
- **PR #367 (`3c9035b`, editor journal):** `src/refdes/editor_journal.py`
  is landed **library-only** — begin/complete/recover for crash-safe
  save transactions, explicitly *not wired into `serve/edit.py` or the
  CLI* (verified: no `editor_journal` import anywhere under `src/refdes/`
  except the module itself). §3.8 spells out why the live layer's
  save/undo assumptions are unchanged.
- **PR #372 (`27c4fda`, serve scrubbing):** write-route responses are
  scrubbed to project-relative paths at the `handle()` choke-point
  (above). The calc route carries no paths; contract satisfied by
  construction.

## 2. Decisions this design adopts (from the parked direction)

Inheriting §"Live editor updates" of inline-calc-later.md (the owner
decisions of 2026-10-25, §6, are folded into the sections they change):

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
  debounced **400 ms** after the last keystroke (constant, tunable —
  owner-confirmed 2026-10-25, §6.2), **and a `blur` on the textarea
  flushes the pending schedule immediately** (§6.2): blur is a trigger
  for the same scheduled request, not a second request type — the
  flush goes through the identical closure, guards and apply path
  (§3.6 covers the interactions).
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
  What is *not* decided is how a span names a field — that is the
  grammar question in §6.5. Today nothing field-derived feeds the calc
  pass (verified: `_run_item_calcs` reads `item.body` only,
  `build.py:1785/1797/1840-1844`), so until `docs/design/inline-calc.md`
  answers §6.5 the bag is carried and unused. The client already holds
  exactly what the bag needs: the draft's field edits live in
  `draft.fields` (a plain object of scalar values, `drafts.js:21`,
  `setDraftField` :236-241; collections/null are not editable,
  `api.py:1100-1102`).
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
inherited from `server.py:783-818`. Registered in `api.handle` beside the
`/edit` branch (`api.py:49-53`).

Request: `{"text": "<current draft body>",
"fields": {"<draft field name>": <scalar>, …}}`.

- 400 `{"error": "text is required: the draft body as one string"}` for
  missing/non-string text; 400 for a `fields` value that is not a JSON
  object. `fields` is optional — absent means "no draft field edits",
  i.e. the saved item's fields. Values are scalars, mirroring the
  `set_field` scalar rule (`api.py:1100-1102`); the bag is the draft's
  `fields` object verbatim (`drafts.js:21`).
- **Unknown keys are ignored, as part of the contract**: the route
  extracts exactly its known keys, the `_apply_edit` posture
  (`api.py:1087-1116`). This is what lets the §6.5 grammar decision grow
  the request later (e.g. a field-reference mode flag) without a
  browser/serve version lockstep. Until §6.5 lands, `fields` is
  validated and carried; the preview pass accepts and does not consult
  it (§3.4).
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
  model (§3.6).
- Guard: the server evaluates at most the first 200 triggered spans of
  the body, in source order, and **omits the rest**; the response then
  carries top-level `"truncated": true` (the schema key above, sibling
  of `spans` — omitted, not `false`, when nothing was cut). A truncated
  response is rendered with one panel footer line ("showing the first
  200 spans"); the §3.6 supersede guards apply to it unchanged. Per-span
  cost is ~0.13 ms (§7), so a request is bounded tens of ms regardless.

### 3.4 Backend: the narrow preview pass (new, small)

`build.py` gains a public, **side-effect-free** sibling:

```python
def preview_inline_spans(project, item, body_text, fields=None) -> list[dict]:
```

- `fields` is the §3.3 bag, keyword-only and optional: the pass
  **accepts it from day one** so the §6.5 grammar decision needs no
  signature change, and **ignores it** until that decision says how a
  span names a field (with §3.2's verified fact as the floor: today's
  arithmetic reads body text + snapshot envs + lockfile, nothing else).
- Mirrors `_run_item_calcs`'s pass shape: `env` seeded with
  `_make_calc_resolver(project, _key_index(project))` and
  `_make_source_resolver(project, item, records, {}, [])` (main's
  signature, `build.py:1644-1650`) using the snapshot's memoized
  `project._source_lock` (read-only: `citations.locked_source_value`,
  same as a build); events =
  `calc.extract_blocks_with_lines(body_text)` + `inline_calc.triggered_spans(body_text)`
  sorted by offset (same as `build.py:1838-1846`).
- Per span: parse → eval → `format_value(value, project.sigfigs)` →
  `compare_stored`; status/message per §3.3. Positions:
  `code_span_ranges` (main, `inline_calc.py:124`) for `start/end`;
  **new, small**: `parse_span`/a helper exposing the result-slot column
  range (the cut position is already computed inside `parse_span` (the
  `readings[0]` cut, `inline_calc.py:347`), just not returned).
- **What it must not touch**: `project.diagnostics`, `item.calc_values`,
  `item._source_uses`, lockfiles, disk. Locals for `origins`/`env`/
  `resolved`/`uses`; a test proves the snapshot is unchanged after
  requests (§5 slice A).
- The resolver reads target `item._env` — present for every local item
  after any build (the scheduler caches it, `build.py:1752-1756`
  docstring, written :1933); for a target that failed calc, the existing
  "target's own calc failed" message propagates (`build.py:1619-1620`).

Why not `load_readonly(overlay=...)` per request: mechanism exists
(`loader.py:192-223`, `serve/edit.py:500`) and is the right fidelity
reference — it is 0.23 s @ 20 items and 2.02 s @ 400
(`docs/performance.md:44-52`), so it cannot run on a 400 ms debounce
beyond toy projects. The narrow pass costs one item's calcs (~0.1–5 ms,
§7). The e2e test uses the overlay as the **oracle**: the panel's computed
text must equal what the overlay-build reports as the diagnostic's
computed value (§5 slice A) — narrow pass fidelity pinned by test.

### 3.5 Browser: where results show and how they insert

New module `src/refdes/serve/static/live-calc.js`, wired by `editor.js`
(one import, one construction in `createEditor`, panel mounted by
`item.js` beside the textarea where the image/source pickers mount,
`item.js:176-190` — panel placement decided 2026-10-25, §6.3):

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
  (shift by the length delta of applied ranges after the caret). Skip a
  span when the caret sits inside its result range (author mid-edit),
  when the textarea is not focused *and* the caret is inside the span
  range, and whenever the response failed §3.6's guards. After the edits:
  call `area._refdesCommit()` once — the draft, dirty flag, sessionStorage
  mirror, revision gate, and conflict screen all behave exactly as for
  typed text (`editor.js:96-101`'s comment is the contract).
- **Why the gate is `stale` and not `computed != stored` (review
  96ae35f, finding 1)**: the checker *accepts* within-window literals —
  `compare_stored` returns `None` when the stored nominal is inside its
  rounding window (`inline_calc.py:597`, window logic :555-594).
  Verified 2026-10-26 (`.scratch/inline-calc-window/probe_window.py`,
  from this tree): `` `Vout := 2.218 V * 2 = 4.4 V` `` is status **ok**
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
  `sessionStorage` mirror (`drafts.js:3`): a preference should outlive
  the tab, an unsaved body should not. The CSP (`security.py:71-73`)
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

**Blur and the guards (§6.2):** the blur flush (§3.1) fires the same
scheduled closure, so it is born under both guards like any keystroke
request — no blur-specific bypass exists. Blur does not change
`area.value`, so the text-snapshot compare is against the same string;
the revision guard is unchanged; and a flush that lands while an older
request is in flight supersedes it through guard 1 exactly as fast
typing does. The caret rules (§3.5 skip, §3.8 protection) read
`selectionStart/selectionEnd` from the textarea **element at apply
time**, and a textarea keeps its selection after losing focus in both
Chromium and Firefox — so an author who blurs with the caret parked
inside a result range keeps the caret-skip: auto-fill still will not
touch that span, and its `Fill` row remains offered for the explicit
click (§6.1's coexistence). The undo story is unchanged: a blur-applied
fill is the same single `insertText` edit (§3.8).

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
  native stack) and only over result ranges; the 400 ms debounce means
  pauses, not mid-word, are when it fires; a result range the caret is
  inside is never touched.
- Every mutation goes through the textarea's own input pipeline (an
  `insertText` edit fires `input` → existing `writeBody` → draft), so
  there is **one** draft, one Save, one revision check — the live layer
  adds no state to `drafts.js` (draft schema untouched).
- Save in flight → no apply (§3.1); after Save the draft is cleared
  (`drafts.js dropAppliedOp` :310-326) and the form re-renders on the new
  revision; the next evaluation runs against the new snapshot.
- **The editor journal (#367) changes nothing in this section.**
  `src/refdes/editor_journal.py` landed as a *library only* —
  begin/complete/recover for crash-safe multi-file save transactions —
  and is not wired into `serve/edit.py` or the CLI (verified by grep:
  no importer under `src/refdes/` outside the module; its commit
  `3c9035b` says so in the message). The journal journals the
  server-side *file writes* of a save; the live layer writes no file,
  makes exactly one read-only request (§3.3), and its undo stack is the
  browser-native one — bullets 1–3 are untouched by it. When a later
  slice wires the journal in (a §4 non-goal here), auto-fill needs no
  change: it composes draft text, and the journal journals whatever the
  eventual Save writes.
- Discard draft / item switch → abort in-flight request, drop panel state
  (module teardown lives beside `createEditor`'s rebuild; re-renders carry
  the textarea over via `data-edit-key`, `editor.js:199`, so the module
  binds once per textarea and re-arms on `bodyControl`).

## 4. New work, itemized (everything else above is existing support)

| # | Work | File(s) | Size |
|---|---|---|---|
| B1 | `preview_inline_spans(project, item, body_text, fields=None)` — read-only per-item pass; `fields` accepted, unused until §6.5 | `src/refdes/build.py` | ~80 lines |
| B2 | result-slot range from the parse (`parse_span` returns content-relative cut column; `triggered_spans` unchanged) | `src/refdes/inline_calc.py` | ~15 lines (`code_span_ranges` is in main, :124 — dependency retired) |
| B3 | `POST /api/item/<ref>/calc` route + guards + `fields` bag validation (shape only; §6.5 owns semantics) | `src/refdes/serve/api.py` | ~60 lines |
| F1 | `{signal}` support in `api()` | `src/refdes/serve/static/api.js` | ~3 lines |
| F2 | `live-calc.js`: debounce + blur flush, abort, supersede, panel (incl. truncated footer), auto-fill on stale rows only + user toggle (localStorage, default ON) + idempotent Fill, execCommand fallback | new static module | ~200 lines |
| F3 | wiring: construct/teardown in `createEditor`, panel mount, save-in-flight flag | `src/refdes/serve/static/editor.js`, `item.js` | ~25 lines |
| D1 | docs pass (below) | `docs/design/inline-calc-later.md` status, `docs/design/browser-editor.md` §"Editing and previewing bodies" pointer, `docs/math.md` editor sentence, `changelog.d/*.added.md` | — |

Deliberate non-goals for v1: live preview of `{{name}}` substitution,
rendered-fragment preview of unsaved bodies (the rest of
browser-editor.md:429-431 — its own design), live fence diagnostics
(the 422-on-save owns fences), iframe refresh on drafts, multi-item
live eval, collaborative locking, wiring the landed #367 journal into
saves (orthogonal: the live layer writes no files, §3.8).

## 5. PR slices (each lands green on the full suite; A → B → C order)

**Slice A — backend, no browser change** (`POST /api/item/<ref>/calc`, B1+B2+B3)

- Tests `tests/test_calc_preview.py` (unit): ok/stale/error/missing-result
  status+message parity with the `compare_stored`/`parse_span` strings;
  computed text equals `format_value(value, project.sigfigs)`; ranges
  correct for spans on multi-span lines, tab-flanked `=` delimiters, and
  a span after a fence whose offset shifts lines (fence name used by the
  span evaluates); duplicate-name live error; cross-item ref (main's
  dependency-order `run_calcs`, `build.py:1937`) + `source()` refusal
  message parity; 200-span truncation; **fields inertness**: a call with
  a `fields` bag returns exactly the call without it (the §3.4
  accepted-and-unused contract, pinned until §6.5 answers);
  **no-mutation**: env/diag snapshot of `project` compared before/after
  ten preview calls.
- Tests `tests/test_serve_calc_preview.py` (HTTP, `serve_support.Client`
  live-`EditorApp` posture): 200 shape; 400 missing text; 404; 403 on a
  sealed log and on an imported item (fixture like
  `test_serve_edit_http.py`); a `fields` bag returns 200 with the same
  spans; non-object `fields` is the 400; an **unknown request key is
  ignored** (the §3.3 forward-compat contract — today's `fields` was
  once an unknown key too); `snapshot_tree` byte-identity (the
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
   item opened → panel warns before first keystroke; (6) toggle OFF
   (panel checkbox, §3.5): panel + diagnostics keep rendering, text
   never mutates, Fill works; toggle state survives reload and item
   switch (localStorage); (7) toggle ON: clicking Fill on an
   auto-filled span is a no-op (idempotent, §3.5); (8) blur
   mid-debounce → request fires immediately and fills apply; blur with
   the caret parked mid-result → that span keeps being skipped and its
   Fill row stays offered (§3.6); (9) Ctrl+Z undoes a blur-applied fill
   as one native step; (10) Firefox + Chromium both pass (1)-(5),
   (7)-(9) and (11); (11) an ok-within-window literal
   (`Vout := 2.218 V * 2 = 4.4 V`, computed `4.436 V`, §3.5's probe):
   the row renders, **the body bytes never change** under auto-fill ON
   (the stale-gate regression pin).
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

## 6. Decisions (Jared, 2026-10-25)

The first draft's four open questions are answered; each answer is
folded into the section it changes, and the section list is the
follow-up map. The answers open exactly **one new question** (§6.5) —
the grammar half of decision 4. **Provenance (review 96ae35f,
finding 2):** the four answers were given by the owner in session on
2026-10-25 as replies to the first review round's open questions;
this section, mirrored in the PR's round-2 comment, is the **first
tree record** of them — no pre-existing doc carries them. If a
record outside this branch is preferred, transcribe §6.1-§6.4 into
`docs/design/inline-calc.md` as owner decisions.

1. **Auto-fill on typing AND the manual Fill button, toggleable.**
   Folded into §3.5: the toggle is a checkbox in the panel header,
   persisted per-user in `localStorage` (`refdes.live-calc.autofill`)
   — a browser preference, not a project setting, for the reasons §3.5
   spells out (interaction preference, not project fact; no per-user
   identity in the serve stack). Default **ON** = this design's
   original recommendation (the parked direction,
    inline-calc-later.md:23-26); flipping the default is a one-line
   constant in `live-calc.js`. Auto-fill fires on `stale` rows only,
   not on every `computed != stored` difference (the checker accepts
   within-window literals; §3.5's gate bullet, a review-round-3 fix).
   Fill keeps working with auto-fill on and is idempotent (shared
   apply path, stored-text equality check).
   Turning auto-fill off never loses a diagnostic — the panel is
   presentation-only and independent of the toggle. Slice B grows the
   toggle (item F2) and its tests (§5 slice B, checklist (6)-(7)).
2. **Debounce 400 ms, and evaluate on `blur` as well.** Folded into
   §3.1 (blur flushes the pending schedule through the same closure),
   §3.6 (blur is born under both stale-response guards: text-snapshot
   supersede compares the unchanged `area.value`, the revision guard
   is unchanged, and the flush supersedes any in-flight request via
   guard 1), §3.6/§3.8 (caret rules read the textarea's
   `selectionStart/End` at apply time — selection persists after blur,
   so caret-skip and the undo merge behave the same for blur-fired
   fills).
3. **Panel directly under the body textarea**, beside the image/source
   pickers (`item.js:176-190`), not in the Edit-bar — as proposed;
   recorded in §3.5.
4. **Item fields ARE calc inputs.** Folded into §3.2 (inputs
   decision + what today's pass provably reads), §3.3 (request shape:
   the draft's `fields` bag verbatim — `drafts.js:21`/`:236-241`;
   scalar rule; the unknown-key-ignoring posture pinned as the
   forward-compat contract), §3.4 (the preview-pass signature takes
   `fields=None` from day one; item B1/B3). **Scope of this change:
   the route contract, the preview-pass signature and forward
   compatibility — NOT the inline-calc grammar.** What a field
   reference looks like inside a span is a grammar/language decision
   owned by `docs/design/inline-calc.md` (§"1. Source form and
   trigger", :63). Until it lands, the bag is carried and the pass
   ignores it; §6.5 is that decision, and it is the one thing this
   design now needs from the owner.

### 6.5 New open question for Jared: the field-reference grammar

Verified starting points (main @ 78c8954, read 2026-10-26):

- The calc pass reads **only `item.body`** — fences and spans
  (`build.py:1785/1797/1840-1844`); no field value enters any
  evaluation today.
- The **content hash** payload includes every field whose `on_change`
  mode is `invalidate` (`build.py:2296-2303`; modes
  `model.py:23-26`, default `invalidate` `model.py:181`, item/schema/
  project precedence `model.py:688-694`) plus the
  whitespace-normalized **body** (:2362-2363). HASH_FORMAT 6
  (`build.py:2260`, landed with #347) put span arithmetic and span
  cross-item references into the hashes; resolved cross-item *values*
  entered at HASH_FORMAT 4 as `calc_refs` (`build.py:2318`).
- **`calc_hash_for`** (:2390-2431) hashes only body arithmetic
  (fences + spans, stored results excluded); its docstring names "a
  result changing because an upstream value moved, with this item's
  own block untouched" as a question the probe deliberately does not
  answer.
- The **release gate** (the `inline_calc_results` rule,
  `lifecycle.py:825`/registered :908, #345 `c3073c6`) fails a release on
  any stale stored result.

Sub-questions:

- **Reference syntax.** How does a span name a field? Bare
  `status` collides with the calc-name namespace (`CALC_NAME_RE`,
  `inline_calc.py:67`, used by `parse_span` :318 — a bare name is a
  calc variable). A qualified `item.status` form must not collide
  with the `ITEM.NAME` cross-item grammar (items are the owners of
  that namespace). A sigil (`$status`, `%status`)? Whatever the
  answer, it must compose with the trigger grammar
  `name := rhs [| unit] = result` (`docs/design/inline-calc.md` §1,
  `inline_calc.py:306`) and stay inside the AST-whitelist evaluator
  (D3).
- **Unit handling of field values.** Field values are YAML scalars of
  arbitrary shape (`status: approved`, `limit: 5 V`, free text). Does
  a referenced value parse as a quantity (the `calc.parse_quantity`
  shape, `calc.py:589`)? Message for a non-quantity referenced field:
  parse-stage (like "stored result missing", `inline_calc.py:351`) or
  eval-stage (like a unit assertion)? Are `| V` assertions against
  enum fields a parse error, an eval error, or meaningless-and-rejected?
- **Missing/empty field behavior.** Reference to a field the item's
  type does not declare: eval error naming the field (the unknown-name
  shape)? Field declared but empty/null: error, or skip the span as
  unevaluable? Note the editor's bag carries scalars only —
  collections/null are not editable (`api.py:1100-1102`) — so
  list-valued fields (`checks:`) are out of the v1 bag by shape.
- **Hash / stale consequences.** A field edit is already a content
  change for invalidate-mode fields, so save-time revision/conflict
  machinery sees it and the release gate sees the stale stored result
  — the live panel carries the same messages, so the UX closes over
  the whole loop. The open calls:
  - a field edit moves a referencing span's **computed value** while
    `calc_hash` stays fixed (arithmetic-only probe, :2390) — the exact
    "upstream value moved" pattern the probe names as not-its-question:
    accept that, or is a referenced field an arithmetic *input* that
    belongs in the content hash the way resolved cross-item values
    entered at format 4 (`calc_refs`, :2318) — which would mean
    HASH_FORMAT 7 (the #347 precedent for the cost: a gated bump —
    reconstruction of earlier formats keeps working, no recorded hash,
    baseline entry or seal moves, per `ba6d153`'s own message);
  - fields in `on_change: timeline`/`ignore` mode are invisible to
    the content hash (`build.py:2298-2299`): a referenced field in
    those modes can silently move a computed result with **no hash
    change** — is the release gate's coverage the answer, or must
    referenced fields be forced to `invalidate`?
- **Live-layer consequences (listed for completeness, none blocking).**
  The bag is this item's own draft, read locally — §3.2's "a target's
  unsaved draft is not visible" limit does not apply to fields, so the
  panel can show field-driven results for unsaved field edits while
  `check`-at-save stays the verdict. Fields are local, so the
  dependency scan needs **no** new cross-item edges; if the hash
  answer is "fields are arithmetic input", only the hash definitions
  move, not the scheduler.

## 7. Probes (verification record)

Scratch project: `.scratch/inline-calc-live-20261020/probe/` (2 items;
`DEC-001` body carries a good span, a stale span, a half-typed span, and
a cross-item span; `SRC-001` defines `V_in = 5.1 V` in a fence). CLI run
from the worktree (`PYTHONPATH=src python -m refdes.cli`, d620ab5):

**Reproducibility (review 96ae35f, finding 4):** the scratch dirs named
here are gitignored and not part of the PR — §7 is a record, not a
reproducer. A review pass on 2026-10-26 re-ran the behavioural claims
against the current tree and reproduced: the half-typed "stored result
missing" error, the unclosed-span silence, the stale-case fill
round-trip, and the within-window case that pins §3.5's stale gate
(`.scratch/inline-calc-window/probe_window.py` in this checkout:
`Vout := 2.218 V * 2 = 4.4 V` → status ok, computed `4.436 V`). The
**timings** (~130 µs/span, 0.011 s overlay floor) were measured on the
2026-10-20 machine and are indicative; §3.4's scaling argument leans on
the committed `docs/performance.md:44-52` table, not on them.

1. `refdes check` reports, at `items/items.yaml`:
   `WARNING … inline calc Vbad: stored result says 5 V, now computes 4 V`;
   `ERROR … inline calc Vhalf := 3 V *: stored result missing; write '= <quantity>'`;
   `ERROR … inline calc Vref: cross-item reference 'SRC-001.V_in': SRC-001
   has not been evaluated yet …` (a record of that tree, d620ab5:
   main's F12-5 gap — retired by #347, §1; on today's main this probe's
   cross-item span resolves through the scheduler); diagnostics carry
   `file:line` + `item_id`
   (`api._diagnostics_for` posture, `api.py:123-139`).
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

Line counts: this file is the deliverable report; the companion progress
log is capped separately.
