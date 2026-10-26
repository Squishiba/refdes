# AgentCoder queue specification progress

- Read AGENTS.md first; checkout was clean. Code remains read-only.
- Read the Paseo operation skill, driver, adjacent README, workspace reuse log,
  named workspace/land-push suites and relevant tool regression tests.
- Verified local history includes the workspace reuse change from PR #373.
- Checked docs/index.md and existing docs for overlapping queue documentation.
- Ran Paseo top-level, ls, permit and relevant lifecycle subcommand help.
- Ran global agent and pending-permission listings: both reported
  DAEMON_NOT_RUNNING. Live payloads are explicitly unverified in the spec;
  no daemon was started, agent launched, permission answered or service changed.
- Ran driver without arguments to verify its existing usage surface.
- Incorporated owner's runtime capacity clarification: configurable default,
  runtime raise/lower without stopping agents, invalid updates keep prior value,
  optional provider caps, value/source status and explicit runtime tests.
- Specified hard global admission prerequisite rather than claiming polling
  can prevent unrelated launch races. Documented deterministic recovery limits,
  exact follow-up templates, no orchestrator fallback and retained attempts.
- Documented the no-deletion gap in the existing executor and shared editable
  environment trap; proposed queue-only safety requirements without code edits.
- Wrote the requested spec, test/pilot gates, implementation slices and estimates.
- Live pilot is a required future implementation gate, not claimed completed.
- Validation: source/citation and requirements review; only the two requested
  Markdown files staged and committed. No push, merge or PR creation.
- Status: specification task complete; queue implementation not started.

- V1 follow-up: reread instructions/current driver and CLI help; daemon listing
  still unavailable. Kept full spec untouched and wrote a separate scope cut.
- Applied owner decisions: cooperative soft global/prefix caps, no daemon gate
  or OS isolation, fail-closed permission classifier, recovery and reliable
  parent-process completion before scheduler and UI polish.
- Applied latest simplification: Paseo count only, no launch-lock/recount or
  corrective parking; metrics are unverified later refinement, not v1 work.
- Added ordered slices/estimates, live fixture/draft-PR-close pilot outline,
  overlap/cap mutations, explicit operating limits and upgrade path.
- Validation: reviewed scope/citations, documentation diff and clean staging;
  v1 specification complete, implementation and live pilot remain future work.
