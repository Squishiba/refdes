# Task log: docs(backlog) status audit against main — 2026-10-26

Task: audit all 38 findings in `docs/design/backlog.md` (status lines are
stale by design) plus `docs/design/*.md` Status lines against `main`
(`78c8954`); report-only, no product code. Deliverable:
`in-prog-logs/backlog-status-audit-20261026.md`.

## What was done

- Baseline check: `main` == `origin/main` == `HEAD` == `78c8954`; tree
  clean at start.
- Re-verified the 2026-10-23 audit's scope (`878e9b7`, audited at
  `899ab91`, 12 commits behind) against the current tree rather than
  copying it. One real change found: `3c9035b` landed
  `src/refdes/editor_journal.py` (begin/complete/recover) **unwired** —
  the commit says so, `serve/edit.py:14,780` confirms, and
  `refdes --help` has no `recover`. Finding 15 stays PARTIAL with the
  remaining work narrowed to wiring.
- All 48 cited backlog commits: `git merge-base --is-ancestor` → all
  ancestors of main.
- Every finding 1–38 verified against code at file:line level (the
  report's table names them); the backlog's own `file:line` cites were
  re-resolved and several have drifted (`render.py:97/133/264` →
  `159/263/509`; `nav.py:43` → `:53`; `history.py:842/879` → `:1242/:1279`;
  `HASH_FORMAT` 5 → 6). Drift is recorded, not treated as a defect.
- Loud checks actually run:
  - `refdes ls --help` (flags incl. `--tag`, `--file`), `refdes --help`
    (no `recover`), Pages live state via `gh api` (`status:"built"`,
    `has_pages:true`);
  - calc lexer probe via the venv python against the worktree `src`:
    `100 V * 5 %` → `500.0 percent*volt`, `10 kΩ + 5 kΩ`, `2 MΩ`,
    `90 °C`, `1 µF * 1000` all evaluate (finding 18 closed);
  - `pytest` over 17 finding-gating test files: **295 passed**
    (field refs, citation ids, escaping, board contracts/includes,
    tree, theme, extends, calc cross-refs ×3, calc blocks ×3, docs
    examples, standard docs complete, image search).
- Design-doc Status lines: all 22 `docs/design/*.md` files checked.
  4 mismatches (report §3); the rest verified by re-running the cited
  commits (`dc0c138/0459f64/8085da2/ecb85bb`, the picker/upload slice
  shas, `da2e44b/0f38619/3c24a63`, `4b34238`, `59d2915/197bc7c/1d796a7/
  8226b79/bda7ab5`) and the cited code paths.

## Judgement calls

- Findings 16/17 classified SUPERSEDED (hardware@2 artifacts; v3 has no
  `decision` type/`recorded_by` verb — verified by grepping v3
  `base.yaml`, whose types are requirement/bound/test/component/group/
  log). Finding 22's decision half rides on `log` post-4a — recorded.
- "Blocked on the owner" items (form-ingestion, item-search-hover,
  W5b) are reported as not-code-queueable, matching the prior audit;
  they're not counted OPEN since no finding-level backlog item is open.
- The report supersedes the 2026-10-23 audit (it says so in its header)
  rather than deleting it.

## Difficulties

- Finding 15 needed care: the 10-23 audit's "not wired" evidence is a
  week old and the journal module landed since; the verdict survives but
  only after re-reading `3c9035b` and the two `edit.py` comments.
- `extends.md:502` looks like a live "outstanding" status at a glance;
  it is quoted text inside a before/after fence. Checked by reading the
  whole block (lines 494–516) before deciding it's not a mismatch.

## State

Finished. Report + this log committed on `docs/backlog-audit-20261026`,
pushed, docs-only PR opened (not merged).
