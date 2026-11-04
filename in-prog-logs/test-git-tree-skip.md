# test: skip the main-differential tests cleanly outside their own git checkout

## Problem (verified)

`_git_tree(ref, dest)` (duplicated in `tests/test_navis_archive.py` and
`tests/test_navis_site_panel.py`) ran `git -C REPO archive <ref>` and fed
stdout to `tarfile.open`. When the tests run from a `git archive` extract
that sits inside another repo's gitignored directory, `git -C REPO archive`
walks up to the parent repo, archives a subpath absent from that tree, and
exits 0 with a zero-filled (10240-byte) tar. `tarfile.open` then raises
`tarfile.ReadError: ... method tar: ReadError('end of file header')`, so the
two `test_navis_free_project_builds_byte_identical_to_main[True/False]`
differentials FAIL (4 failures) where they should skip.

Reproduced: `git archive HEAD | tar -x -C .scratch/x1`, then ran the two
files with `PYTHONPATH=.scratch/x1/src` from inside `.scratch/x1` -> 4
failures with that ReadError.

## Fix

One shared helper in `tests/test_navis_archive.py` (where `SRC`/`REPO`
already live and where `test_navis_site_panel.py` imports shared names).
`_git_tree` returns None (caller skips) -- never raises -- when: git is
absent (OSError caught); `git -C REPO rev-parse --show-toplevel` fails, or
its realpath != realpath(REPO) (the "not its own repo" case that produced
the empty tar); `git archive` exits non-zero or its output is empty; the
output is not a readable tar (`tarfile.TarError` caught). `import io` moved
to module top. `test_navis_site_panel.py` imports `_git_tree` from
`test_navis_archive` and drops its local copy plus now-unused
`import tarfile` / `REPO` import. No src/ changes.

## Tests

New `tests/test_git_tree_helper.py`, red-first (all monkeypatch the
`REPO` global): (1) not a git checkout -> None; (2) subdir of a parent repo
-> None (the empty-tar case: FAILED on old code with the exact ReadError,
passes now); (3) its own repo with one commit + `HEAD` -> returns a usable
tree with `src/keystone.py`. Uses `git -c user.email/-c user.name`, no
global git config needed.

## Verification

- Red: helper test #2 fails on old code with the reported ReadError; full
  reproduction 4 failed.
- Real checkout: the 2 differential files pass (51 passed), the 4
  differential cases PASS (not skipped).
- Extract path (committed tree, `PYTHONPATH=.scratch/x1/src`): the
  differential cases SKIP, not fail.
- `ruff check` (F401/F811/F841) clean on touched files; the site_panel
  I001 finding is pre-existing (present on the committed file).
