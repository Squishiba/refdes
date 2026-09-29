# in-prog: docs/design/form-ingestion-design.md

Task: write a new speculative design doc for schema-generated HTML intake
forms (generate form from live schema -> export a portable snippet -> a human
imports it), plus per-instance key for idempotency and difflib-based
similarity highlighting for curation.

Constraints: design-only, one new file, no index.md nav entry, no changelog
fragment, commit + PR against main.

## Verification log (what I actually ran, and what I found)

### Templates read in full

- `docs/design/editor-source-picker.md` (574 lines) — structural template.
  Status header with bold **proposed** + a per-slice LANDED record; §1 Problem
  with concrete quoted examples; every claim cited `file.py:line` or a
  command; §8 Non-goals as a checklist; §9 Open questions with A/B options
  and a "why this is still a question" line; §10 Tests named as acceptance
  criteria; §11 Phasing with LANDED dates.
- `docs/design/thread-workbench.md` (223 lines) — tonal template for the
  "explicitly not scheduled" framing and the §7 "Questions — decided"
  contrast (my doc gets the *un*decided variant).

### Correction 1: `/api/create/schema` is NOT `_create_preview`

The brief describes `/api/create/schema` as the `_create_preview` handler /
`serve.edit.preview_creation`. Verified in `src/refdes/serve/api.py:50-53` —
they are **two different routes**:

- `GET /api/create/schema`   -> `_create_schema`   (`api.py:574-607`)
- `GET /api/create/preview`  -> `_create_preview`  (`api.py:610-625`)
                               -> `serve.edit.preview_creation` (`edit.py:1369-1415`)

Schema is the one that matters for form generation. Both are described in the
doc, correctly attributed.

### `/api/create/schema` actual shape — verified LIVE

Ran three real `refdes serve` instances (see "How I ran it" below):
(a) `tests/serve_support.py:make_project` fixture, (b) this repo's own
`refdes-project.yaml` (hardware@3), (c) a hand-built scratch project whose
`refdes-schema.yaml` declares `refines` + `governed_by` link verbs.

Returns exactly:

    {"types": [{"name", "prefix", "label", "append_only", "amends",
                "fields": {fname: {"type", "required", "choices"|None,
                                   "default", "creatable"}}}],
     "boards": [...], "workspaces": [...], "date_format": "YYYY-MM-DD"}

Field types observed live on hardware@3: `text`, `person`, `date`, `limit`,
`enum` (with `choices` + `default`), `list`, `options`, `checks`,
`citations`, `refdes`. `creatable: false` on `list`/`options`/`checks`/
`citations`/`refdes` — matches `NON_SCALAR_FIELD_TYPES`
(`model.py:148`) which is what `_create_schema` tests at `api.py:590`.

### Correction 2 (the important one): the schema endpoint does NOT advertise link verbs

Verified live on the scratch project that declares `refines` and
`governed_by`: `"any key named links/verbs anywhere? False"`. `_create_schema`
emits only `"amends": "amends" in spec.links` as a **boolean**
(`api.py:598`). So a generated form **cannot** build its link inputs from
`/api/create/schema` as it stands.

`refdes schema --json` *does* carry them, as an array-of-strings property with
`description: "target: requirement, decision"`
(`schema_json.link_json_schema`, `schema_json.py:128-148`). Verified live:

    "refines": {"type": "array", "items": {"type": "string"},
                "description": "target: requirement"}

Second gap: `/api/create/schema` carries **no `doc:` strings** (checked the
real payload: `'doc' in json.dumps(payload)` -> False), while the JSON Schema
route does — `schema_json.py:117-125` copies `fspec.doc` into
`description`. Live on hardware@3 `bound.limit`:
`"description": "The numeric limit itself, parsed as a quantity with a
comparison - '>= 9 V', '<= 600 mA'. Required, and it is what makes this
bound checkable by other items' checks."` That doc text is the single most
valuable thing to show a non-expert, and it is in the route the brief did
not name. Named as a real fork in the doc.

### Correction 3: `POST /api/items/create` does NOT accept a `body:` field

`CreateRequest` (`edit.py:771-794`) has `who/type/fields/id/destination/
amends/links` — no body. `_create_item` (`api.py:628-677`) reads only those
keys. Verified live: posted `"body": "## Why\nBecause."` alongside a valid
`fields`+`links` body; response was `kind: created` and the written item
carried **no markdown body** — the field is silently ignored, not refused.

Consequence: a `body:` in an intake form cannot be written at creation. The
only body write is a **second** request, `POST /api/item/<ref>/edit` with
`op: "set_body"` (`api.py:487-491`), which needs the id minted by the first
request plus an `expected_revision` — a two-step, non-atomic sequence. This
is a real constraint on the design's "export a create request" idea and on
its `body:` open question, and it is now sourced.

### Link creation (F1) — verified LIVE

`git log --oneline -1` = `9d9b549 feat(serve): create writes any declared
link verb, not just amends (F1) (#100)`. Read `edit.py:1176-1254` and
exercised it against a live server. Confirmed behaviours:

- `links` is `{verb: [refs...]}`, one **non-empty list** per verb
  (`edit.py:1225-1229`; malformed shapes are 400 at `api.py:657-663`).
- Three target spellings accepted, all re-derived server-side into
  `links.composite_for` output (`links.py:311-319` -> `DISPLAY@key`):
  live-created REQ-004 from a **bare surrogate key** `m6p4r95v2zp` and
  REQ-005 from the **composite** `REQ-001@m6p4r95v2zp`; both wrote
  `refines: [REQ-001@m6p4r95v2zp]`.
- What lands is one flow-sequence line per verb, multi-target joined:
  `governed_by: [REQ-002@s9vdx3ac1d6, DEC-001@yn5vsd2s7m5]`
  (`edit.py:1253`).
- Refusals, live, exact text:
  - undeclared verb -> 422 `requirement does not declare the link 'refines';
    it declares no links at all` (`edit.py:1230-1232`)
  - wrong allowed type -> 422 `'refines' accepts targets of type
    requirement; LOG-001 is a log` (`edit.py:1191-1193`)
  - unknown target -> 422 `no item 'REQ-999' in this project to link to with
    'refines'` (`edit.py:1190`)
- A keyless target is refused: `edit.py:1195-1200` — no composite can be
  written, and a bare id "would drop the identity the link is for".

### difflib precedent — read, not assumed

- `configcheck.py:159-164` `_hint` — `get_close_matches(str(key), sorted(known),
  n=1, cutoff=0.6)`. Its comment is the best statement of the cutoff policy
  in the repo: *"0.6, not difflib's 0.5: at 0.5 `unit` is 'close' to `note`,
  and a wrong suggestion is worse than none -- every real typo this has to
  catch (`titel`, `labl`, `requird`, `trac`, ...) scores 0.8 or above."*
  Directly supports the doc's "tune against usage, do not pick a number".
- `parse.py:207-209` `_suggest` (cutoff 0.6, n=1).
- `parse.py:583-584` — link/field did-you-mean on a misspelled key
  (cutoff 0.6 each).
- `citations.py:340-352` — the **closest** thing to title-similarity
  precedent: `get_close_matches(want, [_norm(t) for t, _p in titles], n=5)`
  with no cutoff, on a *normalized* title, for a "no outline entry titled X"
  error. `_norm` is the normalization the design would reuse.
- Full inventory (23 call sites) grepped; the above are the load-bearing ones.

### Conflict-diff UI precedent — read, found

- Server: `edit.py:163-187` `Conflict` dataclass (`who, ref, path,
  expected_revision, current_revision, current_text, diff, ok, kind`), and
  the unified diff is built at `edit.py:598-607` via
  `difflib.unified_diff(..., fromfile="<rel> (on disk)",
  tofile="<rel> (your edit)")`.
- Client: `static/editor.js:294-330` `showConflict` — an `h3`, two muted
  `p`s, and `el('pre', 'conflict-diff', payload.diff)`; then a read-only
  textarea and Keep mine / Keep theirs / Copy my draft.
- Second precedent in the same shape for a *non-text* payload:
  `static/images.js:118-160` ("the binary variant of the conflict dialog").
  Its own comment says it follows "the convention already used by
  editor.js showConflict". This is the one to cite for rendering a
  side-by-side comparison that is not itself a text diff.

### Link-target picker precedent (for the open question)

`static/links.js:28-36` `candidatesFor` fetches `/api/items?type=…` once per
declared target type and merges; `links.js:120-149` is a **client-side
substring filter** over that preloaded list (`label.includes(want)`).
So the editor's picker is not a server search — it is a whole candidate list
in the page plus a local filter. An offline form embedding that would embed
the list, which is exactly the "needs to talk to a live project" tension.

### Existing "propose, then a human applies it" precedent

`cli.py:1214-1280` `cmd_former_ids_propose` — the exact shape: compute
candidates, print them all, **write none** unless `--confirm OLD_ID[,...]`
names which ones ("Nothing written. Re-run with --confirm ... to record the
ones you accept", `cli.py:1259-1263`), then `former_ids_mod.confirm`. Also
`cli.py:1464` and the parser help at `cli.py:1894` both name
`former-ids propose --confirm` as the model. This is the single best
citation for the doc's "export a snippet, a human applies it" posture.

### Existing schema-driven form generator (the thing to extend)

`static/create.js` (178 lines) is already a schema-driven New Item form:
fetches `/api/create/schema` (`:33`), renders one control per `creatable`
field (`:105-114`), maps `enum` -> `<select>` and everything else ->
`<input type=text>` (`:107-111`, via `controls.js:9-16`), previews the id
from `/api/create/preview` (`:117-138`), and POSTs
`{type, fields, id?, destination?, amends?}` (`:154-157`). Its own header
comment: *"the schema comes from /api/create/schema, so nothing here
re-implements a project fact -- and the client never mints a key or writes a
DISPLAY-ID@key composite."*

Verified: **`create.js` sends no `links` at all** — no link inputs exist in
the shipped New Item form. So a generated intake form would be the *first*
consumer of the F1 backend capability, and `create.js` is the closest
existing code to generate from, not a greenfield generator.

### Nav convention — verified

`grep -n "design" docs/index.md` returns one hit, a link to
`design-log.md` (line 27) — a *user-facing* genre page, not a design doc.
None of the 22 files in `docs/design/` appear in `docs/index.md`. Confirms
the brief: no nav entry.

## How I ran it

`which refdes` -> `/home/jorb/venv-refdes/bin/refdes`, which imports from a
**different worktree**
(`/home/jorb/.paseo/worktrees/16msma8v/user-sim-release-gate-run2b`). So
every command here is pinned to this checkout with
`PYTHONPATH=/home/jorb/.paseo/worktrees/16msma8v/form-ingestion-design/src`.
Do not trust a bare `refdes` in this session's output.

Auth detail worth recording: `/api/*` routes are gated on the
`X-Refdes-Token` **header** (`security.TOKEN_HEADER`, `security.py:23`),
not the cookie and not a `?token=` query param — the cookie is only for the
HTML surfaces (`server.py:404-405`, `server.py:510-511`). My first three curl
attempts returned 403 before I read that.

Scratch projects and scripts live in `.scratch/formcheck/` and were left
there, per AGENTS.md.

### `limit` grammar — the §1 example's teeth

`calc.parse_limit` (`calc.py:834-861`) accepts `<op> <quantity>` or
`low .. high`, borrows the unit across a `..` range, and raises
`could not read limit ...; expected a comparison such as '<= 2 W/in^2' or a
range such as '9 V .. 36 V'` otherwise. It also has a multi-bound hint
(`_multi_bound_hint`, `calc.py:824-831`). This is what makes the §1 example
real: a submitter who types `3.3V +/- 5%` gets that error and no way to guess
the fix.

`bound` in the bundled standard, for the §1 citation
(`standards/hardware/v3/base.yaml:202-216`): `limit` required with exactly
that `doc:`, `links: refines: [bound] / derives_from: [requirement, bound] /
governed_by: null` — the `null` is a deliberate refusal, commented in place.

### `refdes new` output — verified by running it

Against the scratch project, `refdes new requirement` prints front matter
with the required field marked, enum choices in a comment, each link verb
with its target types, and `<!-- optional body. -->`. Its own help says it is
"generated from the identical resolved schema `refdes schema --json` emits --
not a second, hand-maintained template that could drift from it." Cited in
§3.2 as the human-readable-snippet shape that already exists.

### Nav convention — re-verified

`grep -c "design/" docs/index.md` -> **0**. There is no `design/` path in
`docs/index.md` at all. 22 other files in `docs/design/`, none in nav. My
first draft said "22 files in `docs/design/`" in §9, which was off by one the
moment I created the file; corrected to "the other 22 files".

### Post-draft mechanical verification

Scripted a check over every `` `file:line` `` and `` `file:a-b` `` citation in
the finished doc: **61 citations, all resolve to a real file, all in range.**
Then hand-checked 17 of the load-bearing ones by printing the cited line:
`api.py:590` (the `creatable` test), `api.py:598` (`"amends" in spec.links`),
`edit.py:1190/1191-1193/1195-1200/1230-1232/1247-1251/1253` (all five
refusal texts and the line-emitting statement, verbatim as quoted),
`links.py:311` (`composite_for`), `model.py:148` (`NON_SCALAR_FIELD_TYPES`),
`configcheck.py:163` (the 0.6 line), `calc.py:834` (`parse_limit`),
`schema_json.py:43` (the limit `examples`), `base.yaml:216` (`governed_by:
null`), `links.js:31` (`/api/items?type=`), `editor.js:300`
(`pre.conflict-diff`), `images.js:118` (the binary-conflict comment),
`cli.py:1259-1263` ("Nothing written"), `browser-editor.md:999` (the
apply-operation invariant), `citations.py:277` (`_norm`).

Three of the brief's own premises turned out to be wrong, and correcting them
is the most useful thing this pass produced:

1. `/api/create/schema` is `_create_schema`, **not** `_create_preview` /
   `preview_creation`. Two different routes (`api.py:50-53`).
2. `/api/create/schema` does **not** advertise link verbs (only an `amends`
   boolean), so a generated form's link inputs cannot come from the endpoint
   the brief named. `refdes schema --json` can, via
   `link_json_schema`'s `description: "target: …"`.
3. `POST /api/items/create` does **not** accept a `body:` — it is silently
   ignored, not refused (live-verified). A body is only writable by a second
   `set_body` edit against an already-created item with a revision check.

Also corrected: the `refdes` on PATH in this session resolves to a *different*
worktree, and `/api/*` is gated on the `X-Refdes-Token` header
(`security.py:23`, `server.py:510-511`), not the cookie.

## Outcome

- `docs/design/form-ingestion.md` — the only code/doc change. ~330 lines,
  nine sections: Problem (the `bound.limit` grammar as the concrete case),
  What has to be true, Direction (generate-from-schema / export-a-snippet /
  instance key / similarity highlighting), the two corrections in §4, the
  accepted staleness limitation, six unresolved questions, an explicit
  "what is still design only" list, a precedent index, and non-goals.
- Status header reads **proposed; no slices scoped, no code written**, and
  says in its own words that nothing in it is decided.
- No `docs/index.md` edit, no `changelog.d/` fragment (confirmed against
  `changelog.d/README.md`'s neighbours: every existing fragment is
  `.added.md`/`.fixed.md`/`.changed.md`/`.breaking.md` describing shipped
  behavior; this changes none).
- No code touched, no tests to run. This is a documentation-only commit.
- `.scratch/formcheck/` left in place per AGENTS.md.

