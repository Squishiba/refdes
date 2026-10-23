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
- `living-notes-plan.md`: proposed -> **Implemented**. Phases landed:
  H4 capture 1f4eed9, B3 #166, H5 #157, H6 #183, H7a #187, H7b #191,
  H7c #194, H8 #193 (git log `--grep "living notes H"`).
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

`changelog.d/docs-site-build-warnings.fixed.md` for the user-visible docs-site
changes. Design-doc Status edits are not part of the built site (site nav is
`docs/*.md`, not `docs/design/*`), so no fragment for those.

## Verification

- `PYTHONPATH=$PWD/src ... -m pytest -q`: 4394 passed, 2 skipped (foreground,
  ~8 min; docs tests pin the generated files — green after regenerate).
- `ruff check docs-site/gen_examples.py --select E9,F`: 5 F541, all pre-existing
  on main (`git show HEAD:...` reproduces identical lines 121–126 in
  `render_block`, not my edit). Left per AGENTS.md (don't fix unrelated
  findings). My added code is clean.
- Docs-site build before/after: 4 -> 0 warnings.

Finished.
