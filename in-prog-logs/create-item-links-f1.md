# Create-item links (F1, links half)

Task: `POST /api/items/create` could set scalar fields but rejected every link
verb (`refines`, `part_of`, `satisfies`, ...) with "TYPE does not declare a
field 'VERB'". `amends:` was the one verb with a working create path. This
generalises that path to any verb a type declares. Backend only; `body:` is
explicitly out of scope.

Source finding: `in-prog-logs/user-sim-release-gate-run1.md` §F1.

## What I found (verified, not assumed)

- `serve/edit.py::_amends_line` is the precedent: verb declared → target
  exists → `project.accepts_type(target.type, allowed)` → `links.composite_for`
  → refuse if the target carries no key. Returns `(line_text, reason)` and the
  line it writes is `amends: [{DISPLAY}@{key}]` — a YAML flow sequence even for
  one target.
- `ItemType` (model.py:225 — the task brief called it `TypeSpec`; there is no
  `TypeSpec` class in this repo) holds `fields: dict[str, FieldSpec]` and a
  *separate* `links: dict[str, list[str]]` (verb -> allowed target types).
  `_creation_fields` only ever consults `spec.fields`, which is why a verb
  arriving in `fields:` was reported as an unknown field.
- `_item_lines(spec, fields, link_lines, inherited)` appends `link_lines`
  verbatim after the scalar fields, and `_create_locked` prefixes each line
  with the destination's indent for `append-yaml`. So `link_lines` really is
  destination-agnostic — confirmed by reading the three block builders, not
  touched here.
- Multi-target spelling in this repo's own items (grep over `items/`):
  `items/board-a/log.yaml:31` `addresses: [REQ-PWR-001@1zn5skrv6k3,
  REQ-PWR-002@rgsmdxz3w5m]` and
  `items/decisions/dec-pwr-001-regulator-topology.md:11`
  `satisfies: [REQ-PWR-002@rgsmdxz3w5m, REQ-PWR-003@na934tg83df]` — one flow
  sequence line per verb, `", "` between targets. That is the shape emitted.
- Cardinality: nothing in the schema declares a maximum target count.
  `spec.links[verb]` is the list of allowed *target types*, not of targets, so
  every verb is multi-valued in practice (the two lines above are the proof).
  No verb needed special-casing for "more than one".
- The ordinary edit route (`_resolve_link_op`, called from `_apply_locked` for
  `AddLink`) resolves with `_find_item`: `project.items` handle, then display
  id, then surrogate key. `Project.item_by_ref` does **not** parse a
  `DISPLAY@key` composite, so a composite target is unresolvable there. For
  creation I additionally resolve a composite by its key half (the key is what
  resolves, per `docs/design/keys.md` §3 and the wording of the tool's own
  dangling-key diagnostic), and the text written is still re-derived from the
  resolved item, never copied from the request.
- `load_readonly` — the load every create plans against — does not mint keys
  (`keys.mint_missing` is only called by writable commands), so a fixture item
  with no `key:` line is a real keyless target. That is how the "target with no
  key" test gets one.

## What I built

`src/refdes/serve/edit.py`
- `CreateRequest.links: dict[str, list[str]] = field(default_factory=dict)`.
- `_link_target(project, verb, ref, allowed)` — one target → composite or
  reason. Same three checks and the same message shapes as `_resolve_link_op`
  ("`'verb' accepts targets of type X; ID is a Y`", "`carries no artifact
  key, so no DISPLAY-ID@key composite can be written for it`").
- `_link_lines(project, spec, links_map)` — shape validation, verb-declared
  check ("`requirement does not declare the link 'verifies'; it declares
  governed_by, refines`"), one target named at most once, one
  `verb: [A@k1, B@k2]` line per verb.
- `_create_locked`: after the existing `amends` block, resolve `request.links`
  and extend `link_lines`. Still one write, still before any byte is planned.
  A verb requested both as `amends:` and inside `links:` is a refusal ("'amends'
  was requested twice ..."), so nothing is written twice.
- `_amends_line` is untouched, deliberately: its messages are its own ("to
  amend", "amending it with a bare id") and the brief asked for no behaviour
  change there. The small duplication is the cost of that.

`src/refdes/serve/api.py`
- `_create_item` validates `links` as `dict[str, list[str]]` (non-empty verb
  name, non-empty list of non-empty strings) with the same 400 style as
  `fields`/`id`/`destination`, and passes it through. Shape is the HTTP 400;
  meaning (undeclared verb, unresolvable target, keyless target) stays the
  service's 422.

Not touched: `_creation_fields`, `_resolve_destination` and the three
destination block builders, `amends:` behaviour, anything for a request with no
`links`, and all frontend files (`create.js` etc.). `body:` untouched — see
"scope" below.

## Scope note: `body:` stayed out

`body` is a *field* in the resolved schema (`requirement.body` etc. in
`standards/hardware/v3/base.yaml`), and `_creation_fields` rejects it today
with the same "does not declare a field 'body'" message — because the create
form's `fields:` map only accepts scalars and `body` is not in `spec.fields`
for the hardware@3 types (it is folded in via `body:`/`body_required`, not
declared as a field). Nothing about the link path depends on that: links arrive
through their own `links` request key and their own resolver, so the two
findings in F1 are separable and I only did the links half. No entanglement
found.

## Verification

- Plain `pytest tests/` works from this worktree and imports *this* worktree's
  `src`: `tests/conftest.py` does its own `sys.path.insert(0, "../src")`, so no
  `PYTHONPATH` prefix is needed and the broken editable install on PATH (it
  points at `/tmp/w-pr59-merge/src`, which no longer exists) never comes into
  play. Checked rather than assumed: `python -c "import refdes"` fails with no
  module, while `pytest tests/test_serve_create.py` collects and passes — that
  only happens via conftest's insert. `.scratch/pytest_src.py` and
  `.scratch/refdes_src.py` are still useful for driving the `refdes` CLI
  itself, where there is no conftest to help.
- New tests in `tests/test_serve_create.py`: single target, multi target (one
  flow-sequence line, order preserved, resolves to both display ids), all three
  destination shapes, no-links request writes no link lines, undeclared verb,
  wrong target type, unknown target ref, keyless target, client-supplied
  composite re-derived, composite with an unknown key half, malformed `links`
  values (service) and malformed `links` bodies (HTTP 400), the same target
  named twice in three spellings, `amends` requested twice, and HTTP
  create-with-links round trip. The pre-existing
  `test_amending_a_sealed_log_never_touches_the_sealed_entry` and
  `test_amends_requires_the_verb_and_a_keyed_target` still pass unchanged.
- Fixture note: the shared SCHEMA gained `refines`/`governed_by` link types and
  `requirement.links`; the fixture items are keyless until a test calls the new
  `mint_keys()` helper, which is also how the keyless-target test keeps REQ-090
  as the only keyless item.

## One change made after the first pass

Duplicate targets. The first pass resolved `links: {verifies: [A, A]}` and wrote
`verifies: [A@k, A@k]`. The edit route has never allowed that — `patcher.py`
refuses an add whose target is already there ("item X already links Y") — so
creation was the one door through which a self-duplicated link line could be
written, and `refdes check` does not flag the result. `_link_lines` now compares
the *resolved composite*, not the spelling sent, so `REQ-001`, its bare key and
`REQ-001@key` are one target asked for twice, and are refused:
"links 'verifies' names REQ-001 twice; one creation links each target once".
Three parametrised cases in `test_the_same_target_named_twice_is_refused` cover
exactly those three spellings. Nothing else from the first pass changed.

## Results

- `pytest tests/` — **2740 passed, 2 skipped** (194s). With the first pass's
  code but before the duplicate-target tests: 2737 passed, 2 skipped.
- `ruff check src/refdes/serve/edit.py src/refdes/serve/api.py --select I,F` —
  clean. Run over `tests/test_serve_create.py` too: clean.
- `tests/test_serve_create.py` alone — 54 passed.
- The pre-existing `amends:` tests
  (`test_amends_requires_the_verb_and_a_keyed_target`,
  `test_amending_a_sealed_log_never_touches_the_sealed_entry`) pass unchanged,
  and case 9 of the manual run below is `amends:` over HTTP with no `links`,
  producing the same single `amends: [LOG-001@…]` line it always did.
- The scratch project the run below leaves behind passes `refdes check`: 7
  items, 0 errors, 1 warning — and the warning is `REQ-003` having no `body:`,
  an artefact of the hand-written fixture, not of anything this change wrote.

One number in the notes above could not be reproduced: "baseline 1582 passed, 1
skipped". `pytest tests/` on this tree reports 2737 with the first pass's tests
already present, and the scratch runner collects the same `tests` directory, so
the runner does not explain the gap — most likely it was a partial collection,
or a tree from before other sessions landed. Recording the number actually
measured here instead of repeating that one.

## Manual run

`curl` is refused by this session's shell whitelist, so
`.scratch/links-f1/repro.py` starts a real `EditorApp` on an ephemeral
127.0.0.1 port and sends each request over a real socket — same method, path,
headers and JSON body as the curl command it prints above each case, launch
token in `X-Refdes-Token`. Nothing is monkeypatched: the route handler,
`serve.edit.create_item` and the write lock are the ones shipping. Against a
fresh `hardware@3` project (`REQ-001`, `REQ-002`, `REQ-099`, `DEC-001`,
`LOG-001`; keys minted for all but `REQ-099`, whose `key:` line the script
deletes, since `load_readonly` — the load every create plans against — never
mints).

```
# live server: http://127.0.0.1:53735  (token header X-Refdes-Token)

=== 1. one target, one verb ===
$ curl -X POST http://127.0.0.1:53735/api/items/create \
    -H 'Content-Type: application/json' \
    -H 'Origin: http://127.0.0.1:53735' \
    -H 'X-Refdes-Token: <launch token>' \
    -d '{"type": "test", "fields": {"title": "Load regulation"},
         "destination": "items/tests.md",
         "links": {"verifies": ["REQ-001"]}}'
< 200  {"kind": "created", "id": "TST-001", "key": "9f4g48kk6v6",
        "type": "test", "path": "items/tests.md"}

=== 2. two targets, one verb (multi-target) ===
< 200  created: DEC-002 (decision) in items/decs.yaml

=== 3. two verbs in one request ===
< 200  created: DEC-003 (decision) in items/decs.yaml

=== 4. undeclared verb ===
< 422  "decision does not declare the link 'verifies'; it declares blocked_by,
       constrained_by, part_of, recorded_by, satisfies, selects, supersedes"

=== 5. target of the wrong type ===
< 422  "'verifies' accepts targets of type requirement, bound; DEC-001 is a
       decision"

=== 6. target that is not in the project ===
< 422  "no item 'REQ-999' in this project to link to with 'verifies'"

=== 7. target carrying no artifact key ===
< 422  "REQ-099 carries no artifact key, so no DISPLAY-ID@key composite can be
       written for it; linking it with a bare id would drop the identity the
       link is for"

=== 8. malformed: empty target list ===
< 400  {"error": "links 'verifies' must be a non-empty list of target refs"}

=== 9. amends: unchanged, still works on its own ===
< 200  created: LOG-002 (log) in items/log.yaml

=== 10. the same target named twice, in two spellings ===
< 422  "links 'verifies' names REQ-001 twice; one creation links each target
       once"
```

What cases 1, 2, 3 and 9 wrote:

```
items/tests.md   ---
                 id: TST-001
                 key: avhhgafj73h
                 type: test
                 title: Load regulation
                 status: planned
                 verifies: [REQ-001@hjgssa6za66]
                 ---

items/decs.yaml    - id: DEC-002
                     key: c0fgshdcj09
                     title: Two rails, one choice
                     status: proposed
                     date: "2026-09-28"
                     satisfies: [REQ-001@qpev598fsm6, REQ-002@dtqembc1rn6]
                   - id: DEC-003
                     key: jxb969sfb14
                     title: Buck, constrained
                     status: proposed
                     date: "2026-09-28"
                     satisfies: [REQ-002@dtqembc1rn6]
                     blocked_by: [DEC-001@gk2j2vt9bne]

items/log.yaml     - id: LOG-002
                     key: mtzwqmq5h62
                     date: "2026-09-28"
                     summary: Correction to the first entry
                     amends: [LOG-001@w2mt8n7sc87]
```

One honesty note about getting this run: the first version of the script left
case 7 *passing* (200) when it should refuse, because its `key:`-stripping
helper looked for a line starting `key:` while the minted key is the line that
*opens* the block (`  - key: …`). That was the harness failing to create a
keyless target, not the product accepting one — after the helper was fixed,
case 7 refuses with the message above. Worth recording, because "the repro said
OK" was wrong for exactly the case that matters most.
