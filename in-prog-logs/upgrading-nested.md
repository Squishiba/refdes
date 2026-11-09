# upgrading-nested — docs/upgrading.md step 1, ancestor-marker caveat

Task: finding 2 of the run-17 user-simulation release gate. `docs/upgrading.md`
step 1 says a 0.5.0-shaped project "no longer loads" and exits 2 after the
upgrade, which is true only when no ancestor directory carries
`refdes-project.yaml`. A probe nested inside a refdes tree silently loads the
ancestor's project and exits 0.

## Reproduction (current source, PYTHONPATH=<worktree>/src)

Probe A — a directory holding only a legacy `refdes.yaml`
(`standard: {base: hardware, version: 2}` + one requirement file), with no
marker anywhere above it. Every ancestor of the probe under the worktree
carries the checkout's own marker, so the marker-free ancestry was made with a
private mount namespace (`unshare -r -m`) bind-mounting `/dev/null` over the
worktree's `refdes-project.yaml`; `find_config` tests `os.path.isfile`, so a
char device is not a marker and the walk runs to `/`. Nothing was written
outside the worktree and the mount is gone with the namespace.

    $ refdes check
    configuration error: refdes.yaml is retired. Split it into the two files
    it became: ... (verbatim, the text step 1 quotes)
    exit=2

Probe B — the same legacy directory nested inside a directory that has
`refdes-project.yaml` (an "Outer Project" with one requirement):

    $ refdes --no-write check      # from the nested probe
    WARNING <project> — 1 item(s) with no coverage — see coverage.html
    1 items, 0 errors, 1 warnings
    exit=0
    $ refdes --no-write ls
    REQ-PWR-001  requirement  Outer requirement
    exit=0

The ancestor's item is listed, the probe's own `REQ-PWR-002` is not: the
legacy file is never read, and step 1's "stops the project at the door" does
not happen. Probes live in `.scratch/upgrading-nested/`.

`refdes --help` (run, not remembered) shows a global
`-c, --config CONFIG   path to refdes-project.yaml`, so the retired file can
be named directly. From inside probe B:

    $ refdes -c refdes.yaml check
    configuration error: refdes.yaml is retired. Split it into the two files
    it became: ... (same verbatim text)
    exit=2

`src/refdes/schema.py:find_config` is the code that walks up and prefers the
nearest marker, recording a legacy file only to report it when no marker is
found; `tests/test_config_split.py` covers the standalone case (its own
comment notes the fixture must not inherit the checkout's marker).

## The change

- `docs/upgrading.md` step 1: one sentence naming the precondition (the walk
  up finds the nearest marker, so a nested probe loads the ancestor project
  and exits 0 with `refdes.yaml` unread) plus the isolation line — copy the
  probe outside any project, or `refdes -c refdes.yaml check`, which prints
  the quoted message and exits 2 from a nested directory. Every quoted string
  above is output I ran.
- Same page, breaking-change table: the `refdes.yaml` row said "exit 2, on
  every command"; it now adds "when no ancestor directory carries the marker
  (step 1)". That row was the only other unconditional claim of this exit-2
  story I found in `docs/`.

## Other pages checked

`docs/troubleshooting.md` quotes the same message ("Your project still
carries the old single-file config, which the loader now refuses") directly
above its entry for `no refdes-project.yaml found in ... or any parent
directory`, which already states that "commands search upward from the current
directory" and names `-c`. Left as is — the walk-up is documented one entry
away and no exit code is asserted there. No other page claims the retired
file's exit 2.

## Verification

- `tests/test_docs_anchors.py` + `tests/test_crossplatform_lint.py`: 28
  passed.
- `docs-site/gen_examples.py --check`: both derived pages up to date;
  `tests/test_docs_examples.py`: 6 passed.
- Full suite: run once with
  `PYTHONPATH=<abs worktree>/src ... pytest -q -n 4 --dist worksteal`, result
  recorded in the PR.
- No source change, so no red-first test: the behaviour is already covered by
  `tests/test_config_split.py`; this PR only narrows a docs claim to what the
  code does. `ruff` not run (no Python file touched).

## Notes

- The isolation flag is real (`-c/--config`, from `refdes --help`), not
  invented; naming `refdes.yaml` with it is what fires the retired-config
  error from a nested directory.
- `refdes -c refdes.yaml check` without `--no-write` creates
  `.refdes-write.lock` in the current directory before the load fails; in a
  real user's nested probe that is a stray lock file in the probe, worth
  knowing when the probe is a copy of a live directory.
