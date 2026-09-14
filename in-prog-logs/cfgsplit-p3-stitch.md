# cfgsplit-p3-stitch — phase 3 stitch of the config split

Task: two small, independent fixes earlier workers found and left out of
scope, plus a changelog-fragment check.

## Step 0

`git merge --ff-only feat/config-split` → `e2a04eb..09bc393`, clean
fast-forward (working tree was clean). `git merge-base --is-ancestor
09bc393 HEAD` confirms the branch contains `09bc393`. Baseline before
touching anything: `python -m pytest tests/ -q` → **691 passed, 0 failed**.

## Fix 1 — revise_cli tests overwrote the project marker

`tests/test_revise_cli.py` `test_git_identity_success` (was line 136) and
`test_git_identity_failure_falls_back_and_warns` (was line 152) both did:

    (lifecycle_project / "refdes-project.yaml").write_text(
        "baseline_identity: git_identity\n", encoding="utf-8"
    )

`lifecycle_project` (tests/conftest.py) calls `write_project_config`, which
splits `LIFECYCLE_SCHEMA` by top-level key: `site:`/`id:` land in
`refdes-project.yaml` (the project marker holding all settings), `types:`/
`link_types:` land in `refdes-schema.yaml`. The write_text calls replaced the
marker wholesale with the single `baseline_identity` line, silently dropping
`site:`/`id:` and leaving the fixture exercising a bare project. Tests still
passed because their assertions don't touch those settings.

Fix: append instead of overwrite, mirroring the pattern already used in
`tests/test_lifecycle.py::test_unverified_requirements_when_explicitly_enabled_excludes_draft`
(the "Append: refdes-project.yaml is the marker..." comment).

Both sites now:

    with (lifecycle_project / "refdes-project.yaml").open("a", encoding="utf-8") as fh:
        fh.write("baseline_identity: git_identity\n")

Verified the two tests genuinely run against the full lifecycle project now:
`test_git_identity_success` asserts no `baseline_identity` warning (git
succeeds via the monkeypatched `subprocess.run`, so `lifecycle.py:336-341`'s
fallback warning — the only `baseline_identity` warning that exists — never
fires), and `test_git_identity_failure_falls_back_and_warns` asserts the
fallback warning does fire. Both pass with the fixture's `site:`/`id:` still
present.

## Fix 2 — staleness warning named only refdes-project.yaml

Found the two sites by grep:

- `src/refdes/schema_json.py::write_schema` computes `config_mtime` as the
  **max** across both `refdes-project.yaml` and `refdes-schema.yaml`.
- `src/refdes/cli.py::cmd_check` warns ".refdes/schema.json was older than
  refdes-project.yaml -- refreshed...", naming only one file.

So an edit to `refdes-schema.yaml` (with schema.json older) produced a
warning pointing at a file the user never touched. The current behaviour is
definitely misleading, not correct — the warning must name the trigger.

Smallest change that can't drift: extract the newest-config-file computation
into `schema_json.newest_config_file(project)` (the same max-over-both-files
logic, unchanged semantics; returns `None` when neither config exists), have
`write_schema` use it for the same staleness check (return type stays `bool`
— `tests/test_schema_json.py::test_write_schema_creates_the_file_and_detects_staleness`
asserts `is False`/`is True`, and I was not allowed to touch that module),
and have `cmd_check` name the returned file in the warning. The `_load`
docstring in cli.py also still claimed the staleness was against
`refdes-project.yaml` — updated to say "the newer of the two config files".

Behaviour verified end-to-end with real `refdes check` runs against a temp
two-file project:

- touch `refdes-schema.yaml` into the future, schema.json 10s in the past →
  "`.refdes/schema.json was older than refdes-schema.yaml -- refreshed.`"
- touch `refdes-project.yaml` into the future instead → "... older than
  refdes-project.yaml ..." (the common single-trigger case is unchanged).

## Changelog fragment — none added

`changelog.d/config-split-two-files.breaking.md` (written in phase 1)
already covers the whole split's user-visible effect: `refdes.yaml` retired,
`refdes-project.yaml` becomes the marker holding every project setting,
`refdes-schema.yaml` new and optional, what you must do to migrate, and the
error guard for misplaced keys. Nothing about these two fixes is a separate
user-visible change (one is test-only; the other removes a misleading filename
from an existing warning). No new fragment.

## Verification

- `python -m pytest tests/test_revise_cli.py tests/test_schema_json.py tests/test_lifecycle.py -q` → 65 passed.
- `python -m pytest tests/ -q` → **691 passed, 0 failed** (same count as the green baseline, no tests added/removed).
- `ruff check src/refdes/schema_json.py src/refdes/cli.py tests/test_revise_cli.py` → 1 finding, the pre-existing import-sort order on `schema_json.py:21` (`FieldSpec, ItemType, ON_CHANGE_MODES`) — untouched by this diff, one of the repo's known ~99 pre-existing findings (a green `ruff check .` is not a completion gate per AGENTS.md). Left alone per "don't refactor beyond these two fixes".
- `git status --short` → only the three files above plus this log.

Not touched: `docs/design/backlog.md`, `CHANGELOG.md`, any test module other
than `tests/test_revise_cli.py`.