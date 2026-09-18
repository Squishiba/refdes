Task: finding-37 decisions + links.md part_of row (docs only, two commits)

2026-09-18

EDIT 1 — backing finding 37's three decisions into docs/design/backlog.md:
- Status paragraph rewritten to record Jared's 2026-09-18 decisions:
  (a) multi-parent items expand once / reference elsewhere (duplication
  rejected, with the doc's own reason), (b) tree-<board>.html + workspace
  equivalent join scoped report set now, (c) catch-all bucket named
  Project-wide (not (unfiled), with the recorded rationale).
- Noted the §1 containment-spine question as still open in Status — the task
  listed only three decisions and that one wasn't among them.
- Replaced every other "(unfiled)" bucket reference with "Project-wide"
  (7 occurrences), kept the no-omission argument intact.
- Reconciled the two places that said tree-<board>.html was "undecided now":
  §4 "should be decided later" -> decided 2026-09-18 to join now, and the
  v1-scope Refuse list (removed it from Refuse, added scoped pages to
  Include). These were internal contradictions introduced by decision (b).

EDIT 2 — docs/links.md verb table:
- Added `part_of` / `contains` row (between blocked_by and equivalent, which
  matches base.yaml link_types declaration order) plus a "Only from
  hardware@3 onward" note mirroring the existing hardware@2 blockquote.
  Verified against hardware/v3/base.yaml: part_of declared on requirement,
  bound, decision, test, component; inverse contains. v1/v2 base.yaml have
  neither part_of nor group (confirmed by Select-String on both files), so
  the "hardware@3" claim is grounded.
- Table row audit vs base.yaml link_types: all 14 existing rows match
  verb/inverse 1:1; only part_of was missing. No mismatches to fix.
- Changelog fragment changelog.d/links-part-of-row.fixed.md added (edit 2
  only, per task).

Remaining: ruff (docs only — nothing to check?), full pytest, rebase main,
rerun, report shas.