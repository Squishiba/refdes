# Config/schema-validation messages: no more Python reprs

Follow-up to #83, which fixed the same defect in the item-level diagnostics
family (`build.py`). #83's write-up left a "Left alone, deliberately" note
pointing at `grep -rn "must be one of" src/refdes/*.py` and estimating "~8 more
list-repr messages in `schema.py`, `parse.py`, `standards.py`".

That estimate was low, and the grep was narrower than it looked. Re-running it
found 12 sites, not 8, and a recursive grep found 2 more in a fourth file the
top-level glob never covered. 14 sites fixed.

## What the defect is

Same shape as `build.py:235` on #83: an f-string interpolating a list/tuple
directly, so the user reads `"must be one of ['draft', 'active', 'retired']"`
instead of `"must be one of draft, active, retired"`. Fix pattern is #83's:
`", ".join(...)`, **declared order, never sorted** — these lists are
meaningfully ordered (`DIAGNOSTIC_LEVELS` is error/warning/info by severity;
`ON_CHANGE_MODES` is invalidate/log/ignore by how much they discard).

## The 14 sites

`schema.py` (9):

| Message | Interp. was |
|---|---|
| `item_layout must be one of ...` | `list(ITEM_LAYOUTS)` |
| `baseline_identity must be one of ...` | `list(BASELINE_IDENTITIES)` |
| `cross_workspace_severity must be one of ...` | `list(DIAGNOSTIC_LEVELS)` |
| `release_gate.X is not a known rule (one of ...)` | `list(RELEASE_GATE_DEFAULTS)` |
| `... which is not among status's declared choices: ...` | bare `choices` |
| `types.X.check_severity must be one of ...` (scalar) | `list(DIAGNOSTIC_LEVELS)` |
| `types.X.check_severity[status] must be one of ...` (mapping) | `list(DIAGNOSTIC_LEVELS)` |
| `types.X.fields.Y.on_change must be one of ...` | `list(ON_CHANGE_MODES)` |
| `types.X.body.on_change must be one of ...` | `list(ON_CHANGE_MODES)` |

`parse.py` (1): item-level `history: 'maybe' must be one of ...`.

`standards.py` (2): `standard.base must be one of ...` in both `_load_standard`
and `latest_version` (the `refdes init` path — it duplicates the message, so
fixing only the loader would have left half the bug).

`configcheck.py` (2) — see below.

## The two that mattered most: configcheck.py

Not in #83's note, not in the file list I was given, and invisible to the grep
#83 recommended — which is the reusable lesson here. `configcheck.py` sits at
`src/refdes/configcheck.py`, so `src/refdes/*.py` *does* match it. But the
literal string `"must be one of"` never appears in its source, because the
message is assembled across a call boundary:

```python
raise self.wrong(path, f"one of {list(ON_CHANGE_MODES)}", value)
#  ...and wrong() does: f"{path} must be {what}, got {_got(value)}"
```

The two halves join at runtime. Grepping for `"must be one of"` is structurally
incapable of finding it. Widening the grep to `f"one of {list("` is what did
find it — the defect is a *bare list interpolation*, and "must be one of" was
only ever a proxy for that. **Grep for `{list(`, `{choices}`, `sorted(` in a
message position next time, not for the finished English.**

The two sites it hid are also the ones a user is most likely to hit:

- `BlockChecker.mode()` — `body: {on_change: maybe}`
- `BlockChecker.field_spec()` — a field `type:` outside the declared types

Two things worth recording about the second:

1. It also called `sorted(FIELD_TYPES)`, so it was wrong twice: repr *and*
   alphabetized, against the preserve-declared-order rule. `FIELD_TYPES` is a
   `frozenset`, which has no declared order to preserve, so preserving order
   required introducing `FIELD_TYPE_ORDER = (*_FIELD_TYPE_MAP, "enum")` —
   the map's own insertion order, with the separately-handled `enum` last.
   `FIELD_TYPES` stays the frozenset for membership tests; a test pins that
   the two agree as sets and that the order is *not* the sorted one.

2. **`configcheck` validates before `schema.py` builds the type spec.** So
   `configcheck.py:202` is what a user actually reads for a bad `body:
   on_change:`, and the identically-named `schema.py` check is *shadowed* —
   unreachable on the overlay path. Found this because
   `test_body_on_change_outside_the_modes_is_named_in_prose` failed after I'd
   "fixed" the schema.py one, with a traceback pointing at configcheck. Had I
   trusted the scoped grep and not run the test, the fix would have been dead
   code and the user-visible message would still have been a list repr.

   Both are now fixed. The `schema.py` one is no longer dead — it still guards
   the bundled standard's own type specs, which don't come through
   `configcheck`. The test docstring says which layer is which, so the next
   reader doesn't have to rediscover it from a traceback.

I extended scope here past the three files I was given, and flagged it to the
user before doing it rather than after: `configcheck.py` is config validation,
it's the module producing the user-visible text, and leaving it would have
meant shipping a "fix" whose headline case doesn't work. Flagging was the right
call — it's exactly the case the scoping rule exists to catch.

## Tests

Two existing tests were pinning the **broken** text and had to be corrected,
not just extended:

- `tests/test_project_settings.py:227` — matched
  `r"item_layout must be one of \['flat', 'workspace'\]"`. The regex was
  *encoding the bug*; it would have failed the moment the message was fixed.
- `tests/test_check_severity_status.py:213` — asserted
  `"['error', 'warning', 'info'], got 'note'" in message`.

Two more only matched a *prefix* and so never noticed the repr, but were worth
tightening to the full corrected sentence while I was there:
`test_project_settings.py` (`baseline_identity`) and `test_standards.py`
(standard `required_when` choices, `standard.base`).

New coverage, in the existing files where related tests already lived
(`test_project_settings.py`, `test_standards.py`, `test_check_severity_status.py`),
plus one new module `tests/test_message_prose.py` for the five sites that had
no natural home (`fields.*.on_change`, `body.on_change`, item `history`, field
`type`, and the `FIELD_TYPE_ORDER` invariant). Each asserts the prose text, the
`got '<value>'` tail, and the absence of a `['` repr.

## Docs

`docs/design/candidate-parts.md:335` quoted the `check_severity[status]` message
verbatim — and in a *third* form, `must be one of [error, warning, info]`,
bracketed-but-unquoted, matching neither the code nor the fix. Updated to the
corrected text so the doc doesn't become the stale copy.

Swept `docs/` for every other distinctive fragment (`is not a known rule`,
`declared choices:`, `standard.base must be`, the bracketed `must be one of
[` form) — no other page quotes these messages. `docs/troubleshooting.md`
already shows the *fixed* enum form from #83, so it needed nothing.

## Noted, not fixed

- `src/refdes/serve/security.py:57` and `serve/filters.py:187-191` are
  docstrings/comments and already-correct `", ".join` calls respectively —
  grep-visible, nothing to do. `filters.py` is the precedent that this codebase
  already writes these messages the right way.
- `model.py:858` matches `must be one of` but is a docstring
  (`accepts_type`), not a message.
- `in-prog-logs/docs-audit-lifecycle-batch.md:594` quotes the old repr. Left
  alone deliberately: it's a historical log of a past audit, not current docs,
  and rewriting history entries is how logs stop being trustworthy.

## Verification

- Full suite: **2678 passed, 2 skipped** (192s). `test_schema_json.py` ignored —
  no `jsonschema` in this environment, same gap #83 recorded.
- ruff on the 8 touched files: 6 findings, **all pre-existing on HEAD** (verified
  by running ruff against a `git archive` extraction of the same files from
  HEAD — identical rules and files, only line numbers shifted). Zero new.
- No line over the configured 100 introduced; the 6 that exist are pre-existing
  (count identical HEAD vs. now in each file).
- Every corrected message verified by actually loading a bad config and reading
  the real rendered text, not by reading the diff. That's what caught the
  configcheck shadowing.
