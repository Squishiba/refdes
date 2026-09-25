# named-calc-blocks docs (Phase 5): math.md, markdown.md, troubleshooting.md

Task: docs-only. Edit the three files listed in docs/design/named-calc-blocks.md
§9, verify every claim by running the real build in a scratch project, add a
unique changelog.d fragment, push and open a PR to main.

## Progress

1. Read docs/design/named-calc-blocks.md §3-9 and §11 (sections 3, 4, 5, 6, 7,
   8, 9, 11 + 12/13 for context). Behavior confirmed as decided; §11.5's
   key is `id=` (not `name=`).

2. Read the exact message strings from `src/refdes/calc.py` (parse_fence_attrs),
   `build.py` (#calc: fragment warnings), and the pinned tests
   (test_calc_block_names.py, test_calc_block_refs.py).

3. Built a scratch project at `.scratch/named-calc-docs/` using the worktree's
   own src on PYTHONPATH and the repo venv python, running the task's exact
   build command. Triggered and captured every message verbatim:
   - `calc fence: unknown attribute 'name' -- a calc fence accepts id="..."; write id="losses".`
   - `calc fence: 'losses' is not an attribute -- attributes are key="value"; write id="losses".`
     (identical text for both a bare word and an unquoted `id=losses`)
   - `calc fence: block name 'Losses' must match [a-z][a-z0-9_-]* -- write 'losses'.`
   - `calc block 'losses' is named twice in this item -- first at line 8, again at line 12. ...`
   - `[[DEC-001#calc:loess]]: DEC-001 has no calc block named 'loess' (it names: losses).`
   Exit codes: fragment-miss-only build exits 0; fence-error-only build exits 1.
   Also verified by running: named block renders
   `<table class="calc" id="calc-<name>"><caption class="calc-caption">…</caption>`;
   unnamed block renders byte-same `<table class="calc">`; values cross named
   blocks (still one item-wide scope; same value name in two named blocks still
   the "assigned twice" error); `[[ID#calc:name]]` links to `#calc-<name>`;
   a miss renders as `ref ref-missing` (red) with text visible; `{{calcblock}}`
   renders the owner's rows on a page (caption links back to owner); qualified
   `DEC-PWR-001.losses.P_diss` is an error naming the plain form.

4. Wrote the three doc edits:
   - docs/math.md: new "Naming a calc block" section (fence attribute, opt-in,
     lowercase grammar 1-40 chars, what a name is/is not: label on the
     rendering, not a scope/key/value qualifier; per-item uniqueness) + one
     paragraph in "Referencing another item's values" on block names never
     appearing in a value reference. Also reworded the "unless you name the
     item, below" pointer that the inserted section would have misdirected.
   - docs/markdown.md: Calc blocks subsection now states the fence info string
     is meaningful/validated; unrecognized text is a build error, not ignored.
   - docs/troubleshooting.md: five entries in "## Math" — unknown attribute,
     not-an-attribute (bare word + unquoted value), bad name charset, duplicate
     block name in an item, and the `#calc:` fragment warning — each with exact
     message and fix.

5. Added changelog.d/named-calc-blocks-docs.added.md (unique slug; format per
   changelog.d/README.md).

Minor difficulties: none blocking. Notes:
- links.md/blocks.md still lack the `#calc:`/`{{calcblock}}` sections on main;
  out of scope for this task (edit ONLY the three listed files), so math.md
  mentions the fragment/page-block forms in one sentence without claiming those
  pages document them.
- Refdes is not importable via the plain `python` on PATH; used the repo venv
  python with PYTHONPATH=<worktree>/src (worktree and main checkout are both at
  commit 4d1597d, so identical code).

Status: docs edits + fragment done; pytest/ruff, commit/push/PR next.