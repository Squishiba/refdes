# init: `.vscode/settings.json` — gitignore it, fix the docs, stop skipping silently

Source: `in-prog-logs/user-sim-release-gate-run2.md` §0 BUG 3 (plus the two
`.vscode` bullets in §2). Three consequences of one deliberate, correct
choice: `refdes init` writes `.vscode/settings.json` with an **absolute**
`yaml.schemas` path.

Scope per the task: `src/refdes/scaffold.py`'s init path (+ the two lines in
`cli.cmd_init` that print), `docs/standard-library.md`, `tests/test_scaffold.py`.
The absolute-path behaviour itself stays — it is tested
(`tests/test_scaffold.py::test_init_writes_vscode_yaml_schema_association`,
`::test_init_two_projects_get_disambiguated_schema_paths`) and the reasoning
(`scaffold.py:23-37`, finding 9) is sound.

## Repro, before touching anything

`.scratch/bug3/repro.py` runs **this worktree's** `src/` (the `refdes` on
`PATH` is a stale editable install pointing at
`/home/jorb/.paseo/worktrees/16msma8v/help-text-gaps-f3-f5/src`, exactly the
artefact run 2's preamble hit — worth remembering for any repro here).

### 1. `.vscode/settings.json` is not ignored by anything `init` writes

```
$ refdes init           # fresh empty dir
wrote refdes-project.yaml
standard: hardware@3
candidate parts live in items/<board>/candidates.yaml -- https://…
exit: 0

tree: ['.vscode', 'refdes-project.yaml']
gitignore present: False
$ git check-ignore .vscode/settings.json -> exit 1     # exit 1 == NOT ignored
$ git status --porcelain
?? .vscode/
?? refdes-project.yaml
```

So the file `init` leaves behind looks committable, and committing it bakes
one machine's path into every clone:

```json
{
  "yaml.schemas": {
    "/home/jorb/.paseo/worktrees/16msma8v/init-vscode-settings-bug3/.scratch/bug3/proj1/.refdes/schema.json": [
      "items/**/*.yaml"
    ]
  }
}
```

Confirmed there is **no existing `.gitignore` mechanism to match**: `git grep
-n gitignore -- src` returns only prose in comments (`citations.py:23`,
`schema_json.py:325`, `cli.py:1541`) — nothing in `init` or anywhere else
writes or edits a `.gitignore`. So there is no mechanism to copy, only a
style to match: this repo's own `.gitignore` ignores the *per-machine file*,
not the directory (`.claude/settings.local.json`), and puts a comment naming
the reason above it.

### 2. The docs show a relative path the code never emits

```
docs/standard-library.md:312: // .vscode/settings.json -- refdes init writes this for you
docs/standard-library.md:314:   "yaml.schemas": { "./.refdes/schema.json": ["items/**/*.yaml"] }
```

vs. the absolute path above. Docs and code disagree, as reported.

### 3. An existing `.vscode/settings.json` is skipped with no message at all

```
$ refdes init           # dir already has .vscode/settings.json = {"editor.formatOnSave": true}
wrote refdes-project.yaml
standard: hardware@3
candidate parts live in items/<board>/candidates.yaml -- https://…
exit: 0
settings.json unchanged: True
```

Three cheerful lines, exit 0, nothing about the file it did not write, and no
schema completion. `scaffold.py:117-120` is the silent `if not
os.path.isfile(settings_path)`.

## Decisions

**Ignore `.vscode/settings.json`, not `.vscode/`.** `init` writes exactly one
file there, and the rest of `.vscode/` is shareable by design — this repo
commits `.vscode/settings.json` *and* `.vscode/tasks.json` of its own
(`git ls-files .vscode`), and a project will plausibly want a
`launch.json`/`extensions.json` recommending `redhat.vscode-yaml`. Ignoring
the directory would forbid that and would also contradict the repo's own
precedent of ignoring the per-machine file by name.

**The `.gitignore` entry goes in only when `init` actually wrote the
settings file.** Two reasons. (a) Coherence: the entry exists because *we*
wrote a machine-specific file; a settings file we left alone is not ours to
ignore. (b) Effect: `.gitignore` does nothing to an already-tracked path, so
adding the entry in the skip case would be a lie in exactly the situation
where the user has deliberately committed their own settings.

**Note, not merge.** Merging `yaml.schemas` into an existing file is the
better outcome only if it is safe, and it is not obviously safe here:
`.vscode/settings.json` is JSONC — VS Code accepts comments and this repo's
own `.vscode/settings.json` has three of them — so `json.loads` fails on the
common case, and any comment-preserving merge is a real parser, not a small
safe addition. Worse, a merge writes a machine-specific absolute path into a
file the user may already track, which is the exact leak this bug is about,
into a file `.gitignore` cannot un-track. So: one line, printed, with the
real absolute path spelled out (not a `<path>` placeholder) so it is
paste-ready.

**Where the note is printed from.** `scaffold.py` has no `print` and neither
does any other library module (`git grep -c "print(" -- src/refdes` → 226 in
`cli.py`, 1 stray in `links.py`), so the CLI prints. `scaffold` owns the
decision and the text (`vscode_settings_exists`, `vscode_settings_note`);
`cmd_init` asks *before* calling `init`, because afterwards the file exists
either way and nothing distinguishes the one `init` wrote from the one it
skipped. That is the only reason `cli.py` is touched — still the init path,
nothing else about `init` changes.

## After the fix

Same script, fresh scratch dirs (`.scratch/bug3/runs/<ts>/`).

### 1. Ignored now

```
$ refdes init
tree: ['.gitignore', '.vscode', 'refdes-project.yaml']
gitignore present: True
$ git check-ignore .vscode/settings.json -> exit 0
stdout: '.vscode/settings.json\n'
$ git status --porcelain
?? .gitignore
?? refdes-project.yaml
```

`.vscode/` is gone from `git status`; the two files that *should* be committed
remain. `.gitignore` content:

```
# Written by `refdes init`. The yaml.schemas path in this file is an
# absolute path into one checkout, so a committed copy hands every other
# clone a schema that resolves to nothing -- silently, in both tools.
# Editor settings you mean to share belong in a file you write yourself.
.vscode/settings.json
```

### 2. Docs match the code

`grep yaml.schemas docs/standard-library.md` no longer finds the relative
example; the block now reads
`"/home/you/widget/.refdes/schema.json": ["items/**/*.yaml"]` with the
multi-root reason and the `.gitignore` consequence in the prose after it.
`tests/test_scaffold.py::test_docs_show_the_absolute_schema_path_init_actually_emits`
parses the documented snippet and asserts the key is absolute, so the page
cannot drift again — the same gate shape `tests/test_docs_examples.py` uses
for the generated type examples.

Left alone: `docs/design/standard-library.md:1768` still shows the relative
form. That is the design record, not the shipped docs page, and the task
scoped the docs change to one file.

### 3. The skip says so

```
$ refdes init      # dir already has .vscode/settings.json
wrote refdes-project.yaml
standard: hardware@3
note: .vscode/settings.json already exists; left it alone. Add "yaml.schemas": {"/…/proj3/.refdes/schema.json": ["items/**/*.yaml"]} yourself for schema completion.
candidate parts live in items/<board>/candidates.yaml -- https://…
settings.json unchanged: True
```

## What changed

- `src/refdes/scaffold.py` — `_vscode_schema_path` (the absolute path, now
  shared by the settings text and the note), `_write_vscode_settings` (the
  skip, now returning whether it wrote), `_ensure_vscode_settings_gitignored`
  + `_gitignore_addresses_vscode_settings` + `_VSCODE_GITIGNORE_BLOCK` /
  `_GITIGNORE_COVERS_VSCODE_SETTINGS`, and the public `vscode_settings_exists`
  / `vscode_settings_note`. `init`'s body is three lines where the old silent
  `if not os.path.isfile(...)` block was.
- `src/refdes/cli.py` — `cmd_init` only: ask `vscode_settings_exists` before
  `init` runs, print `vscode_settings_note` after the standard line when it
  did. Nothing else in the CLI touched.
- `docs/standard-library.md` — the `yaml.schemas` example + a paragraph.
- `tests/test_scaffold.py` — 11 new test functions, 18 collected cases (33 →
  44 functions, 51 collected; one parametrised over 8 already-covered
  patterns): gitignore written, `git check-ignore` exits 0,
  only the one file ignored not the directory, existing gitignore preserved and
  entry added once, CRLF preserved, covered patterns and `!` negations left
  untouched, `.vscodeignore` not mistaken for coverage, no gitignore when
  `write_vscode_settings=False`, the note printed with the real path and the
  foreign file byte-identical, no note on a clean init, docs agree with code.
- `changelog.d/init-vscode-settings-gitignore.fixed.md`.

One unrelated-to-the-bug line: `ruff check src/refdes/scaffold.py --select I,F`
— the gate this task names — reported a pre-existing `I001` at HEAD (verified
with `git show HEAD:src/refdes/scaffold.py | ruff check --select I,F
--stdin-filename … -`). It is the one-line `from . import standards` /
`from . import textio` merge ruff's own fix suggests, in the file I am already
touching and under the rule the gate names, so I applied it rather than leave
the gate red. No other pre-existing finding was touched.

## Verification

- `pytest tests/` → **2781 passed, 2 skipped** in 196s.
- `ruff check src/refdes/scaffold.py --select I,F` → clean (and
  `src/refdes/cli.py tests/test_scaffold.py` clean under the same rules).
- Repro script above, before and after, in `.scratch/bug3/repro.py`.

## Progress log

- [x] Repro all three (above).
- [x] Fix 1: `.gitignore` entry in `scaffold.init`.
- [x] Fix 2: `docs/standard-library.md` example.
- [x] Fix 3: the note (note only — no merge, reasoning above).
- [x] Tests, `pytest tests/`, `ruff check src/refdes/scaffold.py --select I,F`.
- [x] Changelog fragment; commit; PR against `main`.

## PR

https://github.com/Squishiba/refdes/pull/109 against `main`, commit
`4399b82` (one commit; a second push amended in a Windows-proofing tweak to
the note assertion).

That tweak: the first version asserted
`(tmp_path / ".refdes" / "schema.json").as_posix() in out`. `init` builds its
path from `os.getcwd()`, which on Windows returns the long form of an 8.3
short temp directory (`RUNNER~1`), while `tmp_path` can carry the short form,
so the two sides could differ on a CI runner and nowhere else. Both sides now
go through `os.path.abspath(...).replace("\\", "/")`, plus a plain
`".refdes/schema.json" in out`, so the assertion still pins the note to this
project's directory without depending on how the runner spells it.

Task finished.
