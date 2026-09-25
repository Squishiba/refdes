# Windows line-ending bug on source write-back

Task from refdes-172: on Windows, `refdes id` (and any other command that
loads a project and writes an item or page source file back) rewrote files'
line endings. An LF file should stay LF, a CRLF file should stay CRLF, and
only the changed lines may change.

## The bug, as reproduced

Scratch project (`.scratch/mkproj.py`): `refdes-project.yaml` +
`refdes-schema.yaml` (type `requirement`, prefix REQ), five item files —
`lf.yaml` (all LF), `crlf.yaml` (all CRLF), `lf.md` (all LF), `mixed.md`
(LF front matter, CRLF body), `cases.md` (mostly LF, one CRLF line in the
body) — none carrying an `id:` or a `key:`. Run `refdes id`, count CRs from
the bytes (`.scratch/eolreport.py`; no `os.linesep` anywhere).

On `origin/main` at 81adbae:

```
items\cases.md    lf=6  crlf=1  -> MIXED     items\lf.md      lf=6  crlf=0 -> LF
items\mixed.md    lf=5  crlf=1  -> MIXED     items\lf.yaml    lf=6  crlf=0 -> LF
items\crlf.yaml   lf=0  crlf=6  -> CRLF
```

after `refdes id`:

```
items\cases.md    lf=0  crlf=9  -> CRLF     <-- was MIXED, flattened
items\mixed.md    lf=0  crlf=8  -> CRLF     <-- was MIXED, flattened
items\lf.md       lf=8  crlf=0  -> LF
items\lf.yaml     lf=8  crlf=0  -> LF
items\crlf.yaml   lf=0  crlf=8  -> CRLF
```

**The all-LF and all-CRLF halves of the reported symptom were already fixed**
by #37 (`changelog.d/id-hint-write-back.fixed.md`), which added
`newline=""` to the reads and writes. What survived is the case #37 could not
see: a file that already **mixes**. Every write-back computed one ending for
the whole file with `newline = "\r\n" if "\r\n" in text else "\n"` and then
re-joined all lines with it, so a single CRLF line re-typed every untouched
line around it. The reported symptom is real, but its surviving cause is the
mixed file, not the uniform one.

## Audit: every place src/refdes writes a source file back

`grep -n "open(" / write_text / write_bytes` across `src/refdes`, classified
per site. "Text mode" = the read folds CRLF to LF, or the write hands the file
to the platform's newline translation.

### Item and page source files — the bug class

| # | Site | Before | Verdict |
|---|---|---|---|
| 1 | `ids.py` `allocate()` | `newline=""` read/write, whole-file `"\r\n" if in text` join | **UNSAFE (mixed)** — flattened a mixed file. Now `textio` |
| 2 | `keys.py` `plan_missing()` | same | **UNSAFE (mixed)**. Now `textio` |
| 3 | `links.py` `plan_expansion()` | same | **UNSAFE (mixed)**. Now `textio` |
| 4 | `links.py` `plan_follows_freeze()` | same | **UNSAFE (mixed)**. Now `textio` |
| 5 | `links.py` `plan_check_expansion()` | same | **UNSAFE (mixed)**. Now `textio` |
| 6 | `links.py` `plan_calc_ref_rewrites()` | same | **UNSAFE (mixed)**. Now `textio` |
| 7 | `former_ids.py` `confirm()` | **text-mode read** + `newline=""` write | **UNSAFE always** — the read had already folded every CRLF, so the style check could only ever see `"\n"`; a CRLF file came out LF on *every* platform. Now `textio` |
| 8 | `revise.py` `_rewrite_file()` | `newline=""` read, whole-file join + a hand-rolled trailing-break fixup | **UNSAFE (mixed)**. Now `textio` |
| 9 | `calc_rewrite.py` `_rewrite_file()` | same shape | **UNSAFE (mixed)**. Now `textio` |
| 10 | `serve/edit.py` `create_item()` | binary read; `eol = "\r\n" if "\r\n" in original else "\n"` for the appended block | **UNSAFE (mixed)** — appending to a file whose tail is LF but which mentions CRLF anywhere gave the new item CRLF. Now `SourceText.ending_at` |
| 11 | `stub_tests.py` `generate()` | `open(target, "a", encoding="utf-8")` — text-mode append | **UNSAFE** — on Windows the platform translated the appended `\n`s, writing CRLF into the middle of an LF file. Now a binary append with the file's own ending |

### Config files (hand-authored; `.gitattributes` pins `*.yaml` to `eol=lf`)

| # | Site | Before | Verdict |
|---|---|---|---|
| 12 | `revise.py` `_bump_standard_version()` | `splitlines(keepends=True)` over a **text-mode read**, written with a bare `open(..., "w")` | **UNSAFE always** — a CRLF config came out all-LF on Linux and an LF one all-CRLF on Windows, to bump one number. Now `textio` |
| 13 | `scaffold.py` `add_preset()` | text-mode read + bare `open(..., "w")` | **UNSAFE always** — same shape on `refdes-project.yaml`. Now `textio` |
| 14 | `scaffold.py` `remove_preset()` | same, plus the same on the `.scratch` simulation copy | **UNSAFE always**. Now `textio` |
| 15 | `revise.py` `apply()` config rollback | `open(config_path, "r")` (text mode) + `newline=""` write | **UNSAFE always** — a CRLF config was restored as LF. Now `textio` |

### Transaction plumbing (reads/writes that carry other writers' text)

| # | Site | Before | Verdict |
|---|---|---|---|
| 16 | `revise.py` `write_rewrites()` / `restore_rewrites()` | already `newline=""` | **SAFE** — but only as good as the `after` text it is handed, which is why 8/9 had to be fixed. Now `textio.write_text`, for one spelling |
| 17 | `revise.py` `write_rewrites_verified()` post-write read | already `newline=""` | **SAFE**. Now `textio.read_text` |
| 18 | `revise.py` `_capture_seal_files()` / `_restore_seal_files()` | **text-mode** read + **text-mode** write | **UNSAFE** — the pair is a fidelity claim ("put them back exactly") and on Linux restored a CRLF seal as LF. Now `textio` |
| 19 | `revise.py` `_snapshot_item_texts()`, `_simulate_key_ensure()`, post-write stale re-read, display-half refresh re-read | already `newline=""` | **SAFE**. Now `textio` |
| 20 | `calc_rewrite.py` dry-run copy write | already `newline=""` | **SAFE**. Now `textio` |
| 21 | `adopt.py` (4 reads + the `FileRewrite`s it builds) | already `newline=""` | **SAFE** — left alone; it was already doing this correctly and is the closest existing example of the pattern |

### Generated state — machine-owned, regenerated whole, committed

These have no "original style" to preserve (they are rewritten from a
serializer every time), so the only question is whether the bytes depend on
the platform. Six of the nine already answered "no"; three did not.

| # | Site | Before | Verdict |
|---|---|---|---|
| 22 | `lifecycle.py` `_save_baseline_file()` | `newline=""` | **SAFE** — the model to follow |
| 23 | `seal.py` `save_seals()` | `newline=""` | **SAFE** — the model to follow |
| 24 | `boards.py` `save_manifest()` | `newline=""` | **SAFE** — the model to follow |
| 25 | `ids.py` `save_ledger()` | bare `open(..., "w")` | **PLATFORM-DEPENDENT** — `.refdes/ids.yaml` is committed (`.gitignore` says so explicitly) and came out CRLF on Windows. Now `textio` |
| 26 | `citations.py` `save_lockfile()` | bare `open(..., "w")` | **PLATFORM-DEPENDENT** — same, and committed. Now `textio` |
| 27 | `history.py` `save_object()` | bare `open(..., "w")` | **PLATFORM-DEPENDENT** — content-addressed and immutable, so the same item produced different bytes on different machines, which is exactly what a content address must not do. Now `textio` |
| 28 | `history.py` `append_event()` | bare `open(..., "w")` | **PLATFORM-DEPENDENT**, same. Now `textio` |
| 29 | `schema_json.py` `write_schema()` | bare `open(..., "w")` | **PLATFORM-DEPENDENT** (gitignored, but still). Now `textio` |

### Deliberately NOT changed

| # | Site | Verdict |
|---|---|---|
| 30 | `render.py` — site HTML, `items.json`, `manifest.json`, theme CSS | **OUT OF SCOPE BY INSTRUCTION.** Build output, and intentionally CRLF on Windows. Verified still CRLF after the change; a test pins that. |
| 31 | `patcher.py` `_load()`'s `eol` | **NOT A WRITE-BACK.** The patcher never writes: `plan_patch` returns a plan and `apply_patch` returns new text, and the caller decides whether those bytes reach disk. Its `eol` only decides what a *newly emitted* line inside an edited span looks like, and `_check_replacement_eol` proves the span agrees with it. `tests/test_patcher.py::test_mixed_line_endings_follow_the_files_detected_eol` pins its "the file mentions CRLF, so new lines are CRLF" rule on purpose. I tried routing it through `textio.dominant`, it broke that test, and I reverted: changing a separately documented decision is not this task's call. Flagged to refdes-172 instead. |
| 32 | `serve/edit.py` `_atomic_replace` / `_atomic_create` / `_restore` | **SAFE.** Binary (`"rb"`/`"wb"`, `os.fdopen(fd, "wb")`), byte-exact by construction, with a re-read-and-compare. Untouched. |
| 33 | `citations.py` kept-copy blobs, `build.py` image reads, `stub_tests.py` `rb` probe, `serve/preview.py` pid marker, `serve/state.py`, `server.py` | **SAFE / not source.** Binary or not a source file. |
| 34 | `parse.py` `read_source()`, `pages.py`, `schema.py`, `standards.py`, `imports.py`, `theme.py`, `sources.py`, `history.py` reads, `lifecycle.py`/`seal.py`/`boards.py` reads, `keys.py` adoption marker | **SAFE BY DESIGN.** These normalize CRLF to LF on purpose, because the caller wants to *parse*, not to preserve layout. `parse.read_source` even says so. A load-time write must therefore re-read the file itself with `newline=""` — which is what `textio` does — rather than reuse the parser's normalized text. |
| 35 | `adopt.py` | **SAFE**, already correct. Left as the existing example of the pattern. |

## The fix

One new module, `src/refdes/textio.py`:

- `read_text(path)` / `write_text(path, text)` — `newline=""` both ways, so
  terminators survive in and out. Having one spelling of the safe form is the
  point: the unsafe form (`open(..., "w", encoding="utf-8")` with no
  `newline=`) is a one-token omission away, and it was the omission that
  caused sites 12–14 and 25–29.
- `SourceText(text)` / `.of(path)` — holds the text plus, per line, the
  terminator that ended it. `.lines` hands back bare lines (what every
  line-oriented editor in this codebase already works with); `.render(lines)`
  puts each original line's **own** terminator back on that same line, so an LF
  file stays LF, a CRLF file stays CRLF, and a mixed file keeps its mix outside
  the line that changed. `.text` is the verbatim original, for the
  `after != text` no-op checks the planners already do.
- `SourceText.ending_at(i)` — the same neighbour rule, for a caller that
  appends instead of splicing (`serve/edit.create_item`).
- `SourceText.dominant` — majority ending, LF on a tie. Only consulted when
  there is no neighbour to ask.

Two rules `render()` had to get right, both of which my first draft got wrong
and the tests caught:

1. **Which ending does a *new* line wear?** It takes the ending of the line it
   was inserted above — the line whose slot it now occupies. That is also the
   block it joined, because every insertion here puts a new `id:`/`key:`/link
   line at the *top* of an item and the item's own keys are below it. An append
   at the end of a file, with nothing below to ask, falls back to the line
   above.
2. **A file with no trailing newline.** The old code was
   `newline.join(lines) + newline`, which *always* appended a break —
   `revise.py` and `calc_rewrite.py` each carried a hand-rolled fixup for it.
   `render()` decides per line: the empty ending is only ever correct on the
   final line, so any line that is no longer last gets a real break from its
   nearest neighbour that has one.

`difflib.SequenceMatcher(..., autojunk=False)` does the alignment. `autojunk`
is not a tuning knob here: it classifies any line appearing in more than 1% of
a long sequence as "popular" and stops matching it, and an item file is full of
`- type: requirement` and `    body: |`. There is a test that fails if it is
ever turned back on.

`_BREAKS` in `textio` lists every character `str.splitlines()` treats as a
break (`\v`, `\f`, `\x1c`, `\x1d`, `\x1e`, `\x85`, `\u2028`, `\u2029` included),
because the terminator extractor has to agree with `splitlines()` about where
the lines are or it attaches terminators to the wrong ones. A test round-trips
each one.

## Tests

`tests/test_eol_fidelity.py`, 51 tests, all written against bytes and none
touching `os.linesep`, so the same assertions mean the same thing on the Linux
and Windows CI legs. The CRLF fixtures are built as `b"..."` literals on
purpose: `write_text` on Windows would hand them straight to the newline
translation under test.

- `TestSourceText` — the helper directly: LF, CRLF, mixed, and byte-identical
  round trips; the neighbour rule for inserted and replaced lines; a file with
  no final break; a deletion; an empty file; `dominant` including the tie; the
  `autojunk` regression; `.lines` handing out a fresh list; every
  `str.splitlines` boundary.
- `TestAppendEnding` — the appending twin: LF, CRLF, mixed (last line wins),
  no-final-break, empty.
- `TestReadWrite` — exact byte comparison, so it fails on Windows and passes on
  Linux if `newline=""` is ever dropped.
- `TestIdAllocation`, `TestKeyMinting`, `TestLinkExpansion` — parametrized over
  LF and CRLF for every fixture file, plus a mixed case each, plus the
  no-trailing-newline case, plus `--no-write` touching nothing.
- `TestFormerIds`, `TestConfigWrites`, `TestEditorCreate` — the sites that were
  unsafe on *every* platform, not just Windows.
- `TestGeneratedState` — the committed state files.
- `TestBuildOutputIsUnchanged` — site HTML is still the platform's own, CRLF on
  Windows, and no `\r\r`.

Two of the rules were wrong in my first draft and the tests caught both, which
is the main reason they are written as separate named cases:

- I first had an inserted line ask the line **above** it. That put a new `key:`
  line in the wrong style whenever the line above and the line below disagreed
  — which is exactly the mixed case. It now asks the line it displaces.
- `render` initially glued an appended line onto an unterminated last line,
  because the empty ending that `splitlines(keepends=True)` uses to spell "no
  trailing newline" was still on a line that was no longer last. Fixed by
  `_break_unterminated`, and the test says so.

**The tests were verified to fail against the unfixed code.**
`.scratch/prefixcheck.py` reconstructs `origin/main`'s `src/` in
`.scratch/prefix-check/` (no stash — AGENTS.md forbids it, and there is another
session's stash in this checkout) and runs the new test file there:
**16 failed, 30 passed**, one or more per write-back path. After the fix: 51
passed. Full suite: **2205 passed**.

## Verification with real commands

`.scratch/paths.py` builds the fixture project three ways (all-LF, all-CRLF,
genuinely mixed — front matter LF, body CRLF) and runs `refdes id`, `check`,
`build`, `standard add-preset`, `standard remove-preset` **in sequence on one
copy per variant**, so a link expansion has a minted key to expand into. All
fifteen combinations report `styles_preserved=True`, composites do expand to
`REQ-001@<key>`, keys do get minted, the `id: '042'` hint is replaced in place,
and `no-final-break.md` still has no final break afterwards.

## Notes for review

- `SourceText.render` is O(n·d) in the worst case via difflib. Item files are
  tens to low hundreds of lines, and `revise` already runs difflib over whole
  files, so this is not a new cost class — but it is a change in kind for the
  load path, which runs on *every* command that loads a project. If that ever
  shows up in a profile, the fast path is already there: `lines == self._lines`
  returns `self._text` without touching difflib, which is the no-op case and
  the common one for a project whose files are already fully expanded.
- `patcher.py` was left alone on purpose (row 31). If refdes-172 wants the
  patcher to agree with `textio` about a mixed file, that is a separate
  decision with its own test to change, and I would rather it be made
  explicitly than inherited from this fix.
- `stub_tests.py` now appends in binary mode. That is a behaviour change in
  one narrow way: the appended block is no longer subject to the platform's
  newline translation, which is the point, but it means the file's endings are
  now decided by the file rather than by the OS.
