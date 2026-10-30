# Navis slice 2: key minting on the writable load

Task (from the slice-1 design doc, in-prog-logs/navis-design-20261025.md
§5, §7.2, §13): mint the 11-char navi key into each keyless
`<!--navi: text-->` marker on the writable-load path, announced; short-key
(6-char prefix) CLI resolution; corruption lint for declared marker keys.

## What landed

- `navis.mint_keys(project, write)` (src/refdes/navis.py): collects keyless
  live occurrences via `analyze_navis(item.body)` (exact raw provenance —
  never a re-search), mints `keys.mint()` keys unique against all declared
  keys, splices `KEY + " "` at the marker's exact position in the item's
  own file (right-to-left per line), writes via `revise.FileRewrite` +
  `write_rewrites_verified` (reparse guard, refusal-to-write recorded on
  `load_writes.blocked`). Refusals (`NAVI_MINT_REFUSED` warning):
  `body_line is None` (a list file's `body:` scalar — no locatable bytes)
  and provenance mismatch (file line != body raw line; guards e.g.
  U+2028/`\x85` splits textio sees that the text-mode parse didn't).
  `write=False` prints "N navi marker(s) ... the next writable command
  will mint them." and writes nothing. Per-mint stderr announcement
  (`anchor_follows` precedent) + `(minted N navi key(s) while loading)`
  summary in `cli._load_write_notice`.
- `navis.scan()`: declared keys validated with `keys.malformed_key_message`
  (`... in navi marker` context), reported at the marker line, never
  repaired. Chosen for scan(), not scan_body(), so slice-1 tests that
  hand-write keys keep passing (the fixture keys k7f3q2x8d0m/8tqf4m2z0bh
  are invalid-check-char, now warn; navis entries are still listed).
- `loader.load_tree`: mint runs last among the load's writers (after
  key-mint reparse, link expansions, anchor_follows reparse, before image
  freeze), gated on `write`, counted on `load_writes.minted_navi_keys`,
  then reparse + imports reload (anchor_follows precedent). The splice is
  within-line so line counts (and every parsed position) survive.
- CLI: `navis ls` rows lead with the 6-char key prefix; `show` selector is
  full key → 6..10-char key prefix (unique match, ambiguity names
  candidates exit 2) → ls ordinal. Keyless show note reworded ("the next
  writable command mints a key").
- model: `LoadWrites.minted_navi_keys` (in `__bool__`).
- docs: cli-reference.md navis section (console block re-captured from
  real runs, table, slice-2 notes), markdown.md grammar bullet now says
  the tool mints keys; changelog.d/navis-slice-2.added.md fragment.

## Tests (tests/test_navis_mint.py, 31 tests, red first)

Basics: writable load, idempotence (second run 0 bytes), --no-write,
load_readonly, duplicate texts → distinct keys, two markers one line,
multi-item file, keyed markers untouched (mixed line), key stability.
Shape matrix: CRLF and lone-CR files keep terminators (whole-file
terminator fixtures — first draft normalized the front-matter and made
the file mixed), hard-break line, table cell, inert code span/fence stay
inert + byte-identical, YAML list/quoted/folded `body:` scalars refuse
(bytes intact, refusal warning, marker lists keyless). Corruption:
declared bad key reported "malformed", bytes intact, not minted over.
CLI: ls shows prefix, writable run announces on stderr, show by prefix,
ambiguous prefix names both keys exit 2, no-match prefix names nothing,
full key wins over the prefix grammar. Hash/seal (§7.2 policy pinned):
invalidate body's content_hash changes when the key lands, ignore body's
does not, sealed append-only → mint lands, build fails with
"modified since it was sealed"/"--reseal" hint. Filesystem: chmod 0444
file refuses the write, refusal recorded, bytes intact.

Fixture gotchas fixed along the way: YAML list files need the `items:`
mapping form (top-level list is rejected by the parser); minted keys are
colon-adjacent (`<!--navi:KEY text-->` — grammar has no space after the
colon, so the splice consumes the author's space); hand-built "valid"
keys must be 11 chars via check_char.

## Verification

- tests/test_navis_mint.py: 31 passed; slice-1 suites
  (test_navis.py/test_navis_cli.py/test_navis_matrix.py): 364 passed
  unmodified (corruption-lint warnings are on stderr, substring asserts
  unaffected; one slice-1 CLI test asserts `key: k7f3q2x8d0m` in show
  output — passes, warnings don't change stdout).
- Full suite: 5517 passed, 2 skipped.
- ruff: clean on navis.py/loader.py/test file; cli.py I001 and model.py
  UP037 findings verified pre-existing on origin/main, left alone.
- Differential proof (.scratch/navis-slice2/): pristine marker-free
  fixture (with a normal `<!-- -->` comment, a `<!--navitext:` near-miss,
  and markers inside a fence + a code span), keys pre-declared so the load
  is write-silent; built under origin/main tree (git archive) and the
  feature tree: build stdout, navis ls, and the whole tree (items +
  configs) identical.
- Docs console block captured from a real demo-project run (writable ls
  mint announcement + prefix column; show by 6-char prefix).
- CI round 1: windows-latest failed one fixture assertion that spelled
  `\n` into a text-mode-written file (write_text translates to CRLF
  there); the mint itself was correct. Replaced with splitlines content
  comparison; all checks green.

## Notes / open points for reviewers

- Slice-1 fixture keys (k7f3q2x8d0m, 8tqf4m2z0bh) are invalid-check-char
  by design (slice 1 pre-dates the lint); slice-1 tests tolerate the new
  stderr warnings. A future cleanup can mint valid keys into those
  fixtures; not this PR.
- Archive records, panel surfacing, and the mint-on-write notice in the
  browser editor remain slice 3+.
- Task done: yes.
