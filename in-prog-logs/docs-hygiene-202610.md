# docs hygiene before release — 2026-10-22

Branch `docs-hygiene-202610`, fresh off `origin/main` (synced to cf99252
before starting). Source of the work: the release-readiness audit
`in-prog-logs/release-readiness-audit-2026-10.md` §4, §7 and the verdict
table (SHOULD-FIX rows).

## Job 1 — stale `Status:` lines in `docs/design/` for shipped features

For each doc: read the Status paragraph, verified against
`git log --oneline --grep`/`gh pr view <n> --json state,title`, and rewrote
ONLY the Status paragraph. No other lines touched.

- `editor-image-upload.md`: proposed -> **implemented**. Verified #50,#52,#53,
  #60,#63,#69 all MERGED (`gh pr view`); author docs exist in
  `docs/markdown.md`. Cited the same PRs the old line already carried.
- `editor-source-picker.md`: proposed -> **implemented**. Slices A #49,
  B #59, C #62; PDF page read #57; user guide #349 (all MERGED, `git log`
  `git show` on commit subjects + `gh`). Design-only residue kept: the one
  §10 end-to-end rebuild/drift test that never shipped.
- `editor-vscode-adapter.md`: proposed -> **partially implemented**. V−1 #58,
  V0 #66, contract tests #108 all MERGED; added the §8 hover/deep-link client
  note (shipped with V0 — the `vscode-live-snapshot-hover` fragment). V1/V2
  and every webview remain design only (unchanged).
- `inline-calc.md`: kept **Partially landed**, added the PR citations —
  slice 1 #333, F12 messages #341, grammar #351, release gate #345 all MERGED;
  hash-format-6 / slice 2 (#347) left as "in review" (state OPEN per
  `gh pr view 347`).
- `living-notes-plan.md`: proposed -> **Implemented (H1–H8; optional H9 not
  landed)**. Phase attribution, each hash verified with
  `git show -s --format=%s <hash>`: history store H1 `d84e123`, capture H2
  `47a5300`, diagnostic H3 `506842c`, history commands H4 `1981f9e`, sealing
  H5 #157, `tasks:` H6 #183, thread view/`thread`/`work` H7a/b/c #187/#191/#194,
  gate rules H8 #193. Optional H9 not landed. (My first pass mislabelled H4 as
  `1f4eed9` — that commit is `fix(changelog) ... (#74)`, not H4; fixed, and the
  stale "so H1 is unblocked" ending removed.)
- `item-search-hover.md`: **left unchanged** (verify). grep of
  `editors/vscode/` + `src/refdes/` finds no item-search / `?`-trigger code;
  its "no slices scoped, no code written" is true. The live-snapshot hover is
  from the VS Code adapter (#66), a different feature.

Note: prior status-correction passes exist (#313,#314,#320,#311,#310), so I
re-read every Status paragraph from synced main, not from the audit quotes.

## Job 2 — docs-site build warnings

Baseline: `refdes build` in `docs-site/` = **4 warnings** (1 assets, 3
citation).

(a) `site.assets entry 'images' is not a directory`: the `images:` dir was
added in 2565387 to hold `docs-site/images/vocabulary-graph.svg`; 09baee8
deleted that svg (diagrams became inline SVG) and left the setting + dir
deleting. No `docs-site/images`, `figures`, or any doc referencing a real
served asset. The **setting is dead** -> removed the `assets:` block and its
now-false comment. (Dir should NOT be created: nothing uses it.)

(b) `reference to citation ''` x3: the generated `docs/vocabulary.md` renders
the `citations` field's `doc:` text (from
`src/refdes/standards/hardware/v3/base.yaml:123`) which contains a literal
`[[cite:]]`; the docs renderer parses it as a live citation with empty id.
Chose to fix **the generator** not base.yaml: editing the standard's doc string
would break the frozen resolved-schema fixture
`tests/fixtures/hardware3_resolved.json` / `test_extends.py::test_hardware3_base_resolves_unchanged`.
Added `_protect_citation_refs` to `docs-site/gen_examples.py`
`render_vocabulary_block`, wrapping `[[cite:…]]` tokens in a code span
(`build.py` `PROTECTED_RE` skips `<code>`, so the syntax renders literally —
same as the built site, which HTML-escapes). Regenerated
`docs/vocabulary.md` (3 lines) + `schema-reference.md` (no change);
`gen_examples.py --check` passes.

After: `refdes build` = **0 warnings**.

## Changelog

- `changelog.d/docs-site-build-warnings.fixed.md` for the user-visible docs-site
  changes (built vocabulary page, clean docs build).
- `changelog.d/design-doc-status-lines.fixed.md` for the Status-line
  corrections — added in the review round: the neighbouring passes that made
  this exact kind of change each ship a `.fixed.md` fragment
  (`design-doc-status-lines`, `backlog-stale-status-lines.fixed.md`,
  `workbench-w3-status-line.fixed.md`, `agents-keys-status.fixed.md`), so
  this pass follows that convention.

## Verification

- `PYTHONPATH=$PWD/src ... -m pytest -q`: 4394 passed, 2 skipped (foreground,
  ~8 min; docs tests pin the generated files — green after regenerate).
- `ruff check docs-site/gen_examples.py --select E9,F`: 5 F541, all pre-existing
  on main (`git show HEAD:...` reproduces identical lines 121–126 in
  `render_block`, not my edit). Left per AGENTS.md (don't fix unrelated
  findings). My added code is clean.
- Docs-site build before/after: 4 -> 0 warnings.

## Review round (PR #363, chunk)

Fixed the two real errors the review found, then re-audited every citation in
the diff. Method: each 7-char hash via `git show -s --format=%s <hash>`, each
`#N` via `gh pr view <n> --json state,title`, before it was written.

- living-notes-plan.md + this log: H4 was `1f4eed9` (that is
  `fix(changelog) ... (#74)`); corrected to `1981f9e` (phase H4). Re-scoped to
  **Implemented (H1–H8; optional H9 not landed)** per `backlog.md:2979-2986`,
  attributed store H1 `d84e123` / capture H2 `47a5300` / diagnostic H3
  `506842c`, and dropped the stale "so H1 is unblocked" ending.
- Verified hashes (subject matched the citation): d84e123 (H1 store),
  47a5300 (H2 capture), 506842c (H3 diagnostic), 1981f9e (H4 commands),
  86baa20/03625df/271ece6/8d34251/79eaacf/00ca9d3 (image-upload
  #50/#52/#53/#60/#63/#69), da2e44b/0f38619/3c24a63 (vscode #58/#66/#108).
- Verified PRs (all MERGED unless noted): #49 #59 #62 #57 #349
  (source-picker/reads/panel/PDF-read/user-guide); #333 #341 #351 #345
  (inline-calc) with **#347 OPEN**; #157 #183 #187 #191 #194 #193
  (living-notes H5–H8); prior passes #310 #311 #313 #314 #320 (all MERGED).
- Re-audited the full diff: every `#N`/hash in the *Status paragraphs I wrote*
  is in the verified lists above. The remaining `#N`/hash hits in those files
  (e.g. editor-image-upload.md:55-759, source-picker:291/448/463/602/635,
  vscode:119/247/485, living-notes:475/528) are pre-existing body text I did
  not touch.
- New fragment `design-doc-status-lines.fixed.md` added per the convention
  above (neighbouring status-fix passes all carry one).

Finished.
