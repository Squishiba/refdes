# AUDIT-C — dead and test-only code out of src (audit §1.1–§1.4)

Branch `chore/audit-dead-code`, base `d8bcbecb` (main @ PR #434, fast-forwarded
clean; tree clean before I started). Slice scope per dispatch: §1.1, §1.2,
§1.3, §1.4 only. Status: **finished** (see Evidence).

## Re-measurement first

Every §1 name was re-checked on current main with a repo-wide word-boundary
grep (`grep -rnw <name> src tests tools docs-site editors docs`), same scope
as the audit's. Output kept in `.scratch/audit_c/grep-before.txt` (pre-change)
and `.scratch/audit_c/grep-after.txt` (post-change). Every row of §1.1/§1.2/
§1.3/§1.4 still held at this base — `tools/docs_context/llm.py:213
_get_json_body` had *not* already been removed, contrary to the dispatch's
worry. No new reference appeared anywhere, so nothing had to be kept back.

§1.1 makes no timing claim, so there is nothing to re-time; the audit's §1
evidence is reference-scan evidence, and that is what I reproduced.

## What went out

- §1.1 `seal.SEAL_FILE`, `serve.state.CONFIG_NAMES`, `navis_ops.KINDS`. The
  `Outcome` docstring at `navis_ops.py:44` said "one of `KINDS`", so the ten
  kind names moved into that docstring (all ten verified as the literal first
  arguments of `Outcome(...)` in the module).
- §1.2 `tools/docs_context/llm.py:_get_json_body` (the collapsed pair).
- §1.3 six test-only wrappers moved to the suite, each keeping its behaviour:
  `revert_plan` and `patch_item` (patcher), `fold_at_tip` (chains),
  `scan_body` (navis), `resolve_schema` (standards), `legacy_hash_for`
  (build). Shared by two test modules → `tests/helpers.py` (the module
  documented for "used by more than one test module", imported
  `from helpers import ...`); single-module → the test module itself
  (`patch_item` → `test_patcher.py`, `fold_at_tip` → `test_threads_projection.py`).
  `patch_item`/`scan_body`/`resolve_schema`/`legacy_hash_for` bodies are the
  same four-line wrappers; call sites changed from `module.name(` to `name(`
  (47 sites in the two navis files), assertion text untouched.
  `fold_at_tip`'s equivalence test still compares the same two implementations:
  a thin `(value, source)` wrapper over the live `chains.fold_field_at_tip`
  against `chains.resolve_current_with_source`.
  **Excluded: `editor_journal.refuse_if_pending`** — the audit flags it for a
  design question for Jared, so the function and all its tests are untouched
  (`grep -w refuse_if_pending` in the after file shows it still in src at
  `editor_journal.py:698` and used by `tests/test_editor_journal.py`).
- §1.4 `history.legacy_object_payload`; the one caller
  `tests/test_history_edited.py::_capture_pre_323` now composes the same dict
  inline (`legacy_semantic_payload` + the three identity/provenance keys
  `object_payload` adds). Byte-for-byte the payload the old function built.

Prose that named a deleted symbol was retargeted, not deleted:
`chains.py`/`threads.py` docstrings now say what the pair is instead of
naming `fold_at_tip`; `schema.py`/`configcheck.py` docstrings now name the
production path `standards.resolve_namespaces` (which `resolve_schema` merely
wrapped). `docs/design/*.md` prose mentions are historical design records and
were left alone.

## Numbers

| measure | before (main) | after |
| --- | --- | --- |
| pytest collected | 5940 | 5940 (5938 passed, 2 skipped) |
| repo project `_site` tree hash | `b84395db…` | `b84395db…` |
| docs-site `--check` output hash | `d3178c28…` | `d3178c28…` |
| generated 40-item project `_site` hash | `5dd5fa57…` | `5dd5fa57…` |
| CLI outputs (index/check/schema/ls/work/navis ls/audit) | `0b476d2e…` | `0b476d2e…` |
| src+tools diff | — | 21 insertions, 159 deletions (net −138) |
| touched-file ruff `I,F401,F811,F841` | 2 pre-existing `I001` (history.py, schema.py — confirmed on HEAD) | same 2, no new findings |

Hashes come from `.scratch/audit_c/hash_build.py` (builds a copy of this repo's
project, both docs-site generators in `--check` mode, a generated project, and
seven CLI commands; a repeat run with the label changed reproduced every hash,
so they are path-independent). Box load during the full suite: 8.96 / 10.63 /
10.74 (1 min / 5 min / 15 min), 5 users.

Red-first: `git show HEAD:tests/<file>` into `.scratch/audit_c/red/` run
against the modified src fails on each moved name — `ImportError:
revert_plan`, `AttributeError: refdes.navis has no attribute 'scan_body'`,
`… chains … 'fold_at_tip'`, `… standards … 'resolve_schema'`,
`… build … 'legacy_hash_for'`, `… history … 'legacy_object_payload'`. The
same modules pass with the helpers in the suite.

Full suite, run once: `5938 passed, 2 skipped in 190.46s`
(`-n 4 --dist worksteal`). Touched test files: 788 passed.

## Notes

- No changelog fragment: nothing here is user-visible (no CLI, build, or
  serve output changed — the four hashes above are the proof).
- No user-facing docs page names the removed symbols (`grep -rnw` over
  `docs/*.md`), so no doc claim needed updating; the only prose edits are the
  src docstrings above. `docs/design/living-notes-plan.md` and
  `docs/design/extends.md` name `fold_at_tip`/`resolve_schema` in design
  prose, which is a record of what was decided at the time and stays.
