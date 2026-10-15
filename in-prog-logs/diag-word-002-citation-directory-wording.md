# DIAG-WORD-002: a directory citation gets one CLI refusal wording

Date: 2026-10-15. Branch: `fix/citation-directory-wording-20261015`, base
`3793ac9` (current main tip, confirmed by `git fetch` + merge-base).
Key file: `src/refdes/citations.py` (+ focused tests, one docs row, changelog).

## The claim (from current-main-resweep-refusal-wording.tsv)

A citation whose `path:` names a directory is one condition with two
wordings: `refdes check` says `cited local file 'sources/adir' does not
exist` and `refdes fetch` says `cited local file 'sources/adir' cannot be
read: Is a directory (cited by CMP-001)`.

## Runtime verification (before touching code)

Probe in `.scratch/dw2-probe` (site in `refdes-project.yaml`, `types:` in
`refdes-schema.yaml` — the retired-`refdes.yaml` split; items/cmp.yaml: CMP-001
cites `sources/adir`, which exists as a directory). Ran the real venv CLI with
`PYTHONPATH=src` pinned to this worktree and `refdes.__file__` asserted to the
worktree path:

- `check` -> `ERROR items/cmp.yaml:4 [CMP-001] — cited local file 'sources/adir' does not exist`, exit 1
  (`_resolve_local`'s `not os.path.isfile` gate — never asks what the path is)
- `fetch` -> `FAILED sources/adir cited local file 'sources/adir' cannot be read: Is a directory (cited by CMP-001)`, exit 1
  (the loop's `open()` raises `IsADirectoryError`; `_local_read_failure` only
  special-cases `FileNotFoundError`, so the OS's bare strerror falls to the
  generic `cannot be read: {reason}` branch)

PRESENT at 3793ac9. (The row's line numbers 1800/2289/2609 had shifted to
1977/2466/2842 at this tip — same code.)

## The fix

One sentence, built once: `directory_citation_detail(canon)` =
`cited local file {canon!r} is a directory, not a file`.

- `_resolve_local` (check/build/index family): the `not isfile` gate now
  checks `isdir` and uses the shared sentence; a genuinely absent path keeps
  `does not exist`. `status.state` stays `"missing"` (machine field; the
  model.py comment "the cited repo file does not exist on disk" stays true —
  the *file* does not).
- `_local_read_failure` (fetch): `IsADirectoryError` maps to the shared
  sentence (the `(cited by ...)` suffix convention is kept);
  `FileNotFoundError` and the generic `cannot be read: {strerror}` branches
  are untouched.
- fetch loop local read: gates `os.path.isdir` and raises `IsADirectoryError`
  before `open()`. Reason: POSIX `open()` on a directory raises
  `IsADirectoryError`, Windows raises `PermissionError` — indistinguishable
  from an unreadable file, which would word one condition as the other on
  Windows. The gate makes the sentence deterministic on every platform.

Deliberately untouched: the `is not on disk` family (source-key refresh,
page accept, offline outline — separate code paths, separate family), and
serve (`stage_source_pins` is DIAG-WORD-003; the picker's `sources.py:729`
`does not exist` is the serve side, out of this row).

## Verification

- Repro probe after fix: check and fetch both print the one sentence (fetch
  with `(cited by CMP-001)`); `build` shares `_resolve_local` and agrees;
  genuine missing keeps `does not exist` on both commands; chmod-000 real
  file keeps `cannot be read: Permission denied` (all with pinned PYTHONPATH,
  real CLI, exit 1 unchanged).
- New tests in `tests/test_citation_path_hygiene.py` (the file whose opening
  theme is "one sentence for one condition"):
  `test_a_cited_directory_gets_one_sentence_from_both_commands` — asserts the
  shared sentence on both commands, the absence of BOTH old wordings, the
  cited-by list, and no absolute root; RED at base 3793ac9 (verified in a
  detached base worktree under `.scratch/base-head`, no stash), green on fix.
  `test_a_removed_directory_falls_back_to_the_genuine_missing_sentence` —
  control pinning the genuine-missing case over the new branch.
- Existing controls untouched and green: the `does not exist` pair tests and
  the chmod-000 unreadable test in the same file.
- Focused suites: test_citation_path_hygiene + citations/ids/pages/sections/
  locking/fetch_size_warning = 230 passed, 1 skipped.
- Full suite: 3889 passed, 2 skipped, exit 0.
- Scoped ruff (citations.py + the test file, repo config): 7 findings on the
  branch == 7 on the base copies of the same files — all pre-existing, none
  introduced.
- The base verification used `git worktree add --detach .scratch/base-head`
  (no stash, per AGENTS.md) and the worktree was removed after.

## Docs

`docs/output.md`'s `"missing"` state row now names the directory case (the
state value did not change, its coverage did). `docs/markdown.md:547`
severity table stays true as-is (the directory case was and is an error).

## Outcome

Finished. Full-suite and ruff results recorded in the PR body; not merged
per protocol.
