# User-simulation release gate, run 15

Run date 2026-11-01. Base `d9719a9` (branch `user-sim-run15`, merged
clean from `origin/main`). In-scope surfaces: the new editor formatting bar
(PR #393), the refdes button group (slice 2), `refdes navis archive`/
`restore` (slice 3, #396), YAML list-file Navi key minting (#398, #399),
the run-14 fix round (#399), and the README parallel test command.

Surfaces were driven as a user would: real Chromium (puppeteer-core,
headless) against `refdes serve --port 8758` on a scratch multi-board
project, and the CLI directly against copies of the same project.

## Findings

| # | Sev | Surface | One-line summary |
|---|-----|---------|------------------|
| F15-1 | Medium | YAML mint / exit codes | a Navi marker in a flow-style `body:` makes every writable command mint a fresh key, report `ERROR … could not write key … back into the source`, and exit 1 — `navis ls` included; docs promise keyless + warning, exit 0 |
| F15-2 | Low | refdes skeletons / docs | the `[[fig:]]` and `{{}}` skeletons do not fail the gate (both saved cleanly as literal text); the changelog claims all four snippets "intentionally fail the gate until completed" |
| F15-3 | Info | navis CLI / docs | corrupt archive records warn as `navis archive record is unreadable …` with no `navis.archive_corrupt` code in the output (the docs say the warning is `navis.archive_corrupt`); the sibling orphan warning *does* print its code |
| F15-4 | Low | test suite / README | the two `--no-write` help-text pins in `tests/test_no_write.py` fail with `IndexError` when `COLUMNS` is narrow (≤75) or wide (85–95, ≥160) — the README's documented `pytest -q -n 4 --dist worksteal` command is not terminal-width independent |

## F15-1 — flow-style Navi marker: mint churn + exit 1

Project: `items/board-b/flow-shape.yaml` — one item whose whole list entry
is flow style, `body: "Flow body. <!--navi: …-->"`. docs/markdown.md: flow
style is a *refused* mint shape — "keep the marker keyless with a warning
naming the shape, bytes untouched". The refusal warning is emitted, and
then the mint also writes and reports a hard ERROR:

```
$ refdes navis ls            # a READ verb, on a project with one flow marker
ERROR   items/board-b/flow-shape.yaml:6 — could not write key pmg7b5tnnzq back into the source
... (13 Navis listed)
exit=1
```

Every writable run mints a *new* key and re-reports it (observed over ten
runs: `pmg7b5tnnzq`, `gr9kc1jk781`, `few8120q5gd`, `82whfbnd9r9`,
`c2xvkjsj77s`, `hg71jbrzzfj`, `5bvv9e44c0j`, `cw8e1kh9znt`,
`whngj3we1qn` — none ever written). Consequences measured:
`navis ls` exits 1 (docs: exit 0; `--no-write` exits 0, confirming the mint
is the cause); a successful `navis archive` exits 1; `check` exits 1 with
0 real gate errors; `build` is the same. A project carrying one
flow-style-marker item cannot exit-0 any writable command, and the churn
tells the author nothing they can act on. This is the run-13
keyless-handle shape (F13-2) in the mint itself: refused shape, write
still attempted, hard failure. The mint plan (slice 2, #398) refuses the
write for this shape in the warning — the error path shows the refusal is
not honored by the writer.

## F15-2 — two of the four skeletons don't fail the gate

changelog.d/editor-refdes-buttons.added.md: the skeleton buttons insert
"the §H-4 snippets that intentionally fail the gate until completed … a
skeleton save is blocked with the gate's own message, and the text
survives." Tested each skeleton, inserted into a clean requirement via the
real editor, then Save (Chromium on 8758):

- `` `name := 0 | V` `` → blocked, gate message
  `inline calc name := 0 | V: stored result missing; write '= <quantity>'`,
  draft survives ✓
- ```` ```calc name = expr | V ``` ```` → blocked, gate message
  `calc 'name': unknown name 'expr'`, draft survives ✓
- `[[fig:]]` → **saved** (`status: saved`, no message). The literal
  `[[fig:]]` lands in the file and renders as text in the published page.
- `{{}}` → **saved** (same).

The claim holds for the two calc skeletons and overstates the other two.
A user who clicks Image→Source→save after inserting `[[fig:]]` gets no
gate feedback at all — the snippet they were told "intentionally fails
the gate" is inert. Evidence: `user-sim-run15-evidence/suiteEFG.json`.

## F15-3 — corrupt-record warning carries no code

docs/cli-reference.md: "A record the tool cannot read … produces a
`navis.archive_corrupt` warning naming the file: skipped, not deleted,
the rest of the store loads." Behavior is right (four poisoned records —
not gzip, not YAML, foreign `archive_format`, key not its file's name —
each warn, name their file, are skipped, and the rest loads; the store
survives). The rendered line is
`WARNING .refdes/navis/garbage.yaml.gz — navis archive record is unreadable (…)`
— no `navis.archive_corrupt` anywhere in CLI output
(`grep -c archive_corrupt` = 0, `grep -c unreadable` = 4). The code
exists as a Diagnostic code (`src/refdes/navis_archive.py:52`); the
sibling archived-orphan warning prints its code inline
(`navis.archived_orphan: …`), so the machine-readable surface is
inconsistent between two warnings documented identically. Evidence:
`user-sim-run15-evidence/navis-cli-matrix.log`.

## F15-4 — the help-text pins are terminal-width brittle

`tests/test_no_write.py::test_no_write_help_lists_calc_rewrite_among_the_reporting_commands`
and `::test_no_write_help_lists_every_command_the_docs_table_lists_as_reporting`
parse `refdes --no-write --help` in-process and split on the literal
phrase `explicit write commands either`. argparse re-wraps that paragraph
to the terminal width, so at some widths the phrase lands across a line
break, the split returns one element, and the tests die with
`IndexError: list index out of range` — under the exact command the
README documents:

```
./.venv/bin/python -m pytest -q -n 4 --dist worksteal
```

Both full-suite runs in this gate's PTY reproduced it:
`2 failed, 5626 passed, 2 skipped`. The failures are pure terminal
width, not product behavior — the same suite is green at a standard
width (`COLUMNS=100 pytest -q -n 4 --dist worksteal` → 5628 passed,
2 skipped), and the pins' sweep fails at COLUMNS=50/55/65/75/85/95/160/200
while passing at 77–83/100–140. Nothing in the CLI changes across widths;
the pins assert on a rendering argparse itself reflows. The README tells
users to run this command verbatim; the suite at base `d9719a9` carries
the brittleness (not introduced by any in-scope PR).

## Verified sweeps

**Formatting bar (slice 1, #393), Chromium 8758** —
`user-sim-run15-evidence/bar-results.json`. All 11 core buttons exist as
real `<button>`s with aria-labels, wrap/prefix/insert, and toggle off
(Bold/Italic/Strike/Code wrap+untoggle; Heading cycles `#`→`#####`;
bulleted/numbered/quote prefix+toggle; Link wraps selection
`[rail](url)`; Table inserts a 2×2 skeleton; HR `---`).
`Ctrl+B`/`Ctrl+I`/`Ctrl+K`/`Alt+Shift+5` all bound (direct probe:
`*rail*` inserted, keydown `i`+ctrl reaches the handler; one suite-A
`false` was the driver's own focus artifact). One toolbar insertion = one
native `Ctrl+Z` step (`oneUndoOneStep: true`). Mousedown on the bar keeps
focus in the textarea (no focus stealing). Clicks and shortcuts are gated
while a save is in flight (intercepted slow POST: `boldApplied: false`,
`italicApplied: false`, save lands, status `saved`). The Case-B note
("Undo may need more than one step in this browser.") exists and is
hidden in Chromium (Case A path). Inside a ```` ```calc ```` fence the bar
wraps `**V_out**` — the fence stays syntactically intact and the save is
blocked by the gate's own calc error, undo restores (observed, not
promised; recorded as behavior).

**Refdes buttons (slice 2), Chromium** — picker opens on `[[ID]]`, rows
sorted by display id (asserted over 8 captured rows), type-ahead filters
by id and title, ArrowDown+Enter inserts `[[REQ-A-PWR-001]]` at caret,
a selection is wrapped as `[[BND-THM-001|rail]]`, Escape closes, focus
returns to the textarea (`focusBack: body-edit`), a failed items fetch
shows the honest banner (`items failed: Failed to fetch`). Skeleton
insertion: `name` selected in both calc skeletons; the calc-fence
skeleton lands *after* the enclosing fence when the caret is inside one
(fence-aware placement asserted); `[[fig:]]` and `{{}}` land with the
caret inside the brackets; a selection is wrapped and stays selected.
Image/Source buttons focus the panels below (active element
`image-filter` / `source-picker`). The read-only editor of an imported
item shows no bar at all.

**navis archive/restore (slice 3, #396)** — full matrix in
`user-sim-run15-evidence/navis-cli-matrix.log`: `ls`/`all`/`show` render
the documented rows (`1. cyek3t text DISPLAY-ID (file:line)`), `all`
appends archived rows labelled `[archived]`; archive writes only
`{key}.yaml.gz` under `.refdes/navis/` (store-only — item files, hashes,
seals byte-identical, asserted with `find -newer`), the pointer stops
linking (the Navi leaves `ls`), `show` prints the record beside live text
with the `marker text has changed since archived` note; a second archive
of the same Navi says so and writes nothing; restore brings it back
showing its **current** text; `restore` of a non-archived Navi → exit 2;
a hand-deleted marker → `navis.archived_orphan` **exit 1** refusing to
write a marker back; `--no-write` refuses both verbs (exit 2, "refusing
to run it under --no-write"); with `.refdes/editor-transaction/` present
both verbs refuse (exit 2, pointing at `refdes recover`); an empty
project prints `no Navis: …` exit 0; an unparseable items file reports on
stderr exit 1; keyless markers list with no key column, mint announcements
on stderr. Selector matrix: full key, key prefix (6–10 chars), ordinal
from `ls`, an all-digit declared key resolves as key not ordinal
(`navis show 22222222222` resolves; `bbr02` names nothing exit 2),
`archive 2` addresses the keyless row and refuses with the
"mint warnings above" pointer. The `index` payload carries the same
projection (active+archived, `navis` top-level key).

**YAML list-file mint (#398)** — minted: literal block `body: |` and
single-line quoted `body: "…"` (both mints landed, keys written,
announced on stderr). Refused with accurate shape-naming warnings and
untouched bytes: folded `>`, plain, multi-line quoted, flow style (see
F15-1 for its ERROR addendum), `defaults:`-supplied body, merge-key
`<<:` body, alias-shared body. A declared corrupt navi key
(`<!--navi:22222222222 …-->`) is reported as corrupt (check-character
message) and never repaired; mint mints around it.

**Run-14 fixes (#399) — all verified.** F14-1 (stale span shows the
rounded value): `Pin := 2.2 W * 2 = 4.3 W` warns
`stored result says 4.3 W, now computes 4.4 W` — no raw float; the
raw-value widening (`E6 := 0.6899 W * 5.000000000000001 = 3.5 W` →
`now computes 3.4495 W`) is sigfig-normalized. F14-2 (offset-unit rule
documented in docs/math.md): the `delta_degC` example computes; `42 K/W`
in a `degC` fence refuses with the pint `Ambiguous operation with offset
unit` message the docs now quote. F14-4 (marker strip): built pages carry
no `navi:` text (grep over `_site/*.html` = 0). F14-3: changelog now
explains the code lives on the diagnostic, not the warning line (see
F15-3 for the remaining docs gap). F14-5 (picker endpoint docs):
docs/markdown.md now names `sources/entries` with a real response shape.

**README parallel test command** — the README documents
`./.venv/bin/python -m pytest -q -n 4 --dist worksteal`. This run executed
it with the worktree venv interpreter: green at `COLUMNS=100`
(5628 passed, 2 skipped, 2m40s); the two `--no-write` help-text pins fail
at some other terminal widths — see F15-4.

## Environment

- Chromium: `/usr/bin/chromium` headless, puppeteer-core, per-test
  `createBrowserContext()` isolation, `--no-sandbox
  --disable-dev-shm-usage`, `page.on('dialog', accept)`.
- Serve on 8758, token from `url.txt`; API checks with
  `X-Refdes-Token` (the cookie path 403s for `/api/*` by design).
- Scratch projects: `pwr` (2 boards + unregistered shared folder +
  imported upstream), `nav` (copy for archive matrix), `nav2`
  (clean-building copy), `offset` (run-14 math fixtures), `digit`
  (all-digit navi key).
