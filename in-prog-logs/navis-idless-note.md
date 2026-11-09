# navis verbs note id-less items they did not scan (F16-1)

Task: finding F16-1 of the run-16 user-sim. `refdes navis ls`/`all`
printed "no Navis: no `<!--navi: text-->` marker in any item body"
when the project's only markers sat in bodies of items with no `id:`
(yaml list entries before `refdes id`). Those items land in
`project.pending` (parse.py `load_items`) and never enter the scan
(`navis.projection` walks `project.local_items`), so the listing was
silently incomplete.

Reproduced first with `.scratch/navis-idless-note/repro.sh` (hardware@3
project, one defaults+items yaml file, marker in the id-less entry):
`--no-write navis ls` printed the "no Navis" line, exit 0; after
`refdes id` the marker appeared. Confirmed the message lies exactly as
reported.

Fix (cli.py only): new `_navis_idless_note(project)` counts
`len(project.pending)` (items skipped, not markers — skipped bodies
are deliberately not parsed) and formats
`note: N item(s) have no id yet and were not scanned -- run 'refdes
id' to allocate them`, singular handled. Wired into `cmd_navis`'s
shared ls/all path: printed on **stderr** after the "no Navis" line
(empty case) and after the listing (non-empty case). Stderr because
the neighbouring notices on this run (load writes, load errors, marker
diagnostics) all ride stderr and stdout owes only the piped answer
(`test_a_cold_navis_run_prints_the_answer_on_stdout_alone` is that
rule's test). Exit codes untouched; `show`/`archive`/`restore`/`refdes
index` untouched.

Red-first: new tests/test_navis_idless_note.py, in-process
`cli_mod.main` like tests/test_navis_cli.py. (a) empty listing notes
N=1, (b) listing + skipped item notes, (c) all-id'd project prints no
note, (d) after `refdes id` the note is gone. (a) and (b) failed on
the unmodified tree (err was empty); all four pass after the fix.
Plural wording verified by hand on a two-id-less-item project.

Tests: new file 4 passed; all navis test files 774 passed;
test_crossplatform_lint.py 26 passed; full suite once: 6417 passed, 2
skipped (~2 min). ruff: new test file clean; cli.py's I001 is
pre-existing (reproduced on the HEAD copy), left alone per AGENTS.md.

Docs: docs/navis.md's exit-code table mentions the `no Navis:` line
and its examples show verb output, so added a short
"Items with no `id:` are not scanned" paragraph + console example
(singular note) after the ls-vs-all block, wording from the repro run.
Task notes docs PR #475 adds a sentence about the same skip to
docs/navis.md — re-merged origin/main before the PR; kept both (no
conflict observed at merge time).

Changelog: changelog.d/navis-idless-note.changed.md.

Status: finished.
