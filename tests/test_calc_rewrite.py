"""calc-rewrite (chunk 2 of the unit-syntax change): the transactional
`name : unit = expr` -> `name = expr | unit` rewrite command.

Every test here fails on main before calc_rewrite.py exists (import error),
which is the honest baseline for a new command.
"""

from __future__ import annotations

from unittest import mock

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import calc, calc_rewrite, cli, lifecycle, parse
from refdes import seal as seal_mod
from refdes.model import CHECK_VIOLATION, RETIRED_UNIT_SPELLING
from refdes.schema import load_project

SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "    body: {}\n"
    "  log:\n"
    "    prefix: LOG\n"
    "    append_only: true\n"
    "    fields:\n"
    "      summary: { type: text, required: true }\n"
    "    body: {}\n"
)

MD_ITEM = """---
type: decision
id: DEC-001
title: Loss budget
---

Prose spelling `P : W = V * I` is not a calc line and stays put.

Reference: {{P}}

```calc
V = 12 V
I = 0.5 A
P : W = V * I  # conduction loss
```
"""

YAML_ITEM = (
    "defaults:\n"
    "  type: decision\n"
    "  prefix: DEC\n"
    "items:\n"
    "  - id: DEC-002\n"
    "    title: Timing\n"
    "    body: |\n"
    "      Timing note.\n"
    "\n"
    "      ```calc\n"
    "      t : ms = 2.5 s\n"
    "      ```\n"
)

LOG_ITEM = (
    "defaults:\n"
    "  type: log\n"
    "  prefix: LOG\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: First entry.\n"
    "    body: |\n"
    "      ```calc\n"
    "      P : W = 12 V * 0.5 A\n"
    "      ```\n"
)


@pytest.fixture
def calc_project(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(MD_ITEM, encoding="utf-8")
    (items / "timing.yaml").write_text(YAML_ITEM, encoding="utf-8")
    return tmp_path


def _load(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    return project


def test_the_refdes_repo_itself_has_no_retired_spellings():
    """The repo's own items were migrated with `refdes calc-rewrite` — the
    dogfood step of the retirement. The build still fails by design (DEC-PWR-001
    teaches a check violation), but no retired-unit-spelling diagnostic
    survives anywhere in the tree."""
    import os

    from helpers import REPO

    project = load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not [
        d for d in project.errors + project.warnings
        if d.code == RETIRED_UNIT_SPELLING
    ]


def test_rewrite_markdown_item(calc_project):
    result = calc_rewrite.apply(str(calc_project))
    assert result.ok, result.errors
    assert result.changed_files == ["items/dec.md", "items/timing.yaml"]
    text = (calc_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "P = V * I | W  # conduction loss" in text
    assert "P : W = V * I  # conduction loss" not in text
    # V and I were plain assignments -- untouched.
    assert "V = 12 V" in text and "I = 0.5 A" in text


def test_rewrite_yaml_body(calc_project):
    result = calc_rewrite.apply(str(calc_project))
    assert result.ok, result.errors
    assert result.changed_files == ["items/dec.md", "items/timing.yaml"]
    text = (calc_project / "items" / "timing.yaml").read_text(encoding="utf-8")
    # Indentation inside the block scalar is preserved exactly.
    assert "      t = 2.5 s | ms\n" in text


def test_idempotent_second_run_changes_nothing(calc_project):
    first = calc_rewrite.apply(str(calc_project))
    assert first.ok, first.errors
    before = (calc_project / "items" / "dec.md").read_bytes()
    second = calc_rewrite.apply(str(calc_project))
    assert second.ok, second.errors
    assert second.changed_files == []
    assert second.line_changes == []
    assert (calc_project / "items" / "dec.md").read_bytes() == before


def test_dry_run_writes_nothing(calc_project):
    before_md = (calc_project / "items" / "dec.md").read_bytes()
    before_yaml = (calc_project / "items" / "timing.yaml").read_bytes()
    result = calc_rewrite.apply(str(calc_project), dry_run=True)
    assert result.ok, result.errors
    assert result.changed_files == ["items/dec.md", "items/timing.yaml"]
    assert any("P : W = V * I" in c and "->" in c for c in result.line_changes)
    assert len(result.line_changes) == 2
    assert (calc_project / "items" / "dec.md").read_bytes() == before_md
    assert (calc_project / "items" / "timing.yaml").read_bytes() == before_yaml


def test_sealed_entry_refused_and_reported_while_others_rewrite(calc_project):
    (calc_project / "items" / "log.yaml").write_text(LOG_ITEM, encoding="utf-8")
    project = _load(calc_project)
    # Not sealed yet, so the old spelling inside the entry is a real error --
    # and an entry with errors is never sealed. The sealed-with-old-spelling
    # case is therefore purely historical: sealed before the retirement. That
    # history is simulated here by writing the seal record directly, with the
    # entry's current content hash.
    assert [d for d in project.errors if d.code == "retired_unit_spelling"]
    log = project.item_by_id("LOG-001")
    seal_mod.save_seals(project, {log.id: log.content_hash})

    result = calc_rewrite.apply(str(calc_project))
    assert result.ok, result.errors
    assert len(result.sealed_entries) == 1
    assert "items/log.yaml" in result.sealed_entries[0]
    assert "LOG-001" in result.sealed_entries[0]

    log_text = (calc_project / "items" / "log.yaml").read_text(encoding="utf-8")
    assert "P : W = 12 V * 0.5 A" in log_text  # untouched
    dec_text = (calc_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "P = V * I | W" in dec_text  # everything else rewritten

    # And the untouched sealed entry builds: its retired spelling is a
    # warning, not an error -- it cannot be fixed without resealing.
    project2 = _load(calc_project)
    assert not [d for d in project2.errors if d.code != CHECK_VIOLATION]
    assert [d for d in project2.warnings if "retired" in d.message]


def test_value_changing_rewrite_refused_and_rolled_back(calc_project, monkeypatch):
    bad = {"W": "mW", "ms": "s"}  # dimensionally valid, different displayed value

    def bad_rewrite(line):
        code = line.partition("#")[0]
        match = calc.ANNOTATED_RE.match(code.strip())
        if not match:
            return None
        name, unit, expression = match.groups()
        if unit not in bad:
            return None
        indent = line[: len(line) - len(line.lstrip())]
        comment = line[line.index("#"):] if "#" in line else ""
        return f"{indent}{name} = {expression} | {bad[unit]}{comment}"

    monkeypatch.setattr(calc_rewrite, "rewrite_line", bad_rewrite)
    before = (calc_project / "items" / "dec.md").read_bytes()
    result = calc_rewrite.apply(str(calc_project))
    assert not result.ok
    assert any("rolled back" in e for e in result.errors)
    assert any("P" in e and "mW" in e for e in result.errors)
    assert (calc_project / "items" / "dec.md").read_bytes() == before
    # The other file rolled back too -- all or nothing.
    assert "t : ms = 2.5 s" in (calc_project / "items" / "timing.yaml").read_text(
        encoding="utf-8"
    )


# ------------------- the tolerance the build error points calc-rewrite at
#
# `check` says: a tolerance belongs on the right-hand side, write
# `P = V * I ± 10% | W`, run `refdes calc-rewrite`. But calc-rewrite refused
# the file, reporting the before-picture as "was '' in unit 'W +/- 10%'": the
# line never computed under the old spelling, and the guard that is supposed
# to skip exactly that case never fired.


TOLERANCE_ITEM = (
    "defaults:\n"
    "  type: decision\n"
    "  prefix: DEC\n"
    "items:\n"
    "  - id: DEC-900\n"
    "    title: Tolerance case\n"
    "    body: |\n"
    "      ```calc\n"
    "      V_supply = 12 V\n"
    "      I_load = 1.2 A\n"
    "      P : W +/- 10% = V_supply * I_load\n"
    "      ```\n"
)


def test_tolerance_line_rewrites_rather_than_refuses(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "tol.yaml").write_text(TOLERANCE_ITEM, encoding="utf-8")

    result = calc_rewrite.apply(str(tmp_path))
    assert result.ok, result.errors
    text = (items / "tol.yaml").read_text(encoding="utf-8")
    assert "P : W +/- 10%" not in text
    # The tolerance lands on the right-hand side, spelled the way calc's
    # TOLERANCE_SPLIT accepts and re-renders: U+00B1, not the ASCII "+/-" the
    # old spelling happened to be typed with.
    assert "P = V_supply * I_load ± 10% | W" in text


def test_the_rewritten_tolerance_line_is_exactly_what_check_asked_for(tmp_path):
    """The point of the fix: `check` names a specific replacement, and after
    `calc-rewrite` the project must be in that state -- the same error gone."""
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "tol.yaml").write_text(TOLERANCE_ITEM, encoding="utf-8")

    before = _load(tmp_path)
    tolerance_error = next(
        d for d in before.errors if "a tolerance belongs on the right-hand side" in d.message
    )
    assert "run 'refdes calc-rewrite'" in tolerance_error.message

    assert calc_rewrite.apply(str(tmp_path)).ok
    after = _load(tmp_path)
    assert not [
        d for d in after.errors if "a tolerance belongs on the right-hand side" in d.message
    ]
    assert not [d for d in after.errors if d.code == RETIRED_UNIT_SPELLING]


def test_the_tolerance_line_still_evaluates_after_the_rewrite(tmp_path):
    """Not a pass because the guard stopped looking: the rewritten line has to
    compute the number the old spelling was reaching for, tolerance and all."""
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "tol.yaml").write_text(TOLERANCE_ITEM, encoding="utf-8")

    assert calc_rewrite.apply(str(tmp_path)).ok
    after = _load(tmp_path)
    calc_line = next(c for c in after.item_by_id("DEC-900").calcs if c.name == "P")
    assert calc_line.error is None
    assert "14.4" in calc_line.result
    assert calc_line.bounds, "a +/- 10% line must carry an interval, not a point"


def test_a_line_that_computed_before_still_guards_its_value(tmp_path):
    """The other direction, and the reason the guard exists: a line that DID
    compute before must still be refused if the rewrite would change what it
    computes. Skipping the no-value case must not have skipped this one."""
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(MD_ITEM, encoding="utf-8")

    def changes_the_value(line):
        code = line.partition("#")[0]
        match = calc.ANNOTATED_RE.match(code.strip())
        if not match:
            return None
        name, unit, expression = match.groups()
        if unit != "W":
            return None
        indent = line[: len(line) - len(line.lstrip())]
        comment = line[line.index("#"):] if "#" in line else ""
        return f"{indent}{name} = {expression} | mW{comment}"

    before = (items / "dec.md").read_bytes()
    with mock.patch.object(calc_rewrite, "rewrite_line", changes_the_value):
        result = calc_rewrite.apply(str(tmp_path))
    assert not result.ok
    assert any("rolled back" in e for e in result.errors)
    assert (items / "dec.md").read_bytes() == before


def test_baselines_do_not_show_rewritten_items_as_changed(calc_project):
    project = _load(calc_project)
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"

    result = calc_rewrite.apply(str(calc_project))
    assert result.ok, result.errors
    assert result.baselines_updated == ["rev-a"]

    project2 = _load(calc_project)
    baseline = lifecycle.load_baseline(project2, "rev-a")
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == []
    assert diff.added == []
    assert diff.removed == []


def test_calc_hash_carried_forward(calc_project):
    project = _load(calc_project)
    old_hash = build_mod.calc_hash_for(project.item_by_id("DEC-001"))
    assert old_hash is not None
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"

    result = calc_rewrite.apply(str(calc_project))
    assert result.ok, result.errors

    project2 = _load(calc_project)
    new_hash = build_mod.calc_hash_for(project2.item_by_id("DEC-001"))
    assert new_hash is not None and new_hash != old_hash  # source text did move
    baseline = lifecycle.load_baseline(project2, "rev-a")
    entry = baseline.items["DEC-001"]
    assert entry["calc_hash"] == new_hash  # ... and the baseline moved with it
    # The stale-arithmetic signal stays silent for the rewritten item.
    diff = lifecycle.diff_against(project2, baseline)
    assert not any("DEC-001" in entry for entry in diff.stale_arithmetic)


def test_prose_and_references_never_touched(calc_project):
    result = calc_rewrite.apply(str(calc_project))
    assert result.ok, result.errors
    text = (calc_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "Prose spelling `P : W = V * I` is not a calc line and stays put." in text
    assert "Reference: {{P}}" in text


def test_comment_text_survives_byte_for_byte(calc_project):
    items = calc_project / "items"
    text = (items / "dec.md").read_text(encoding="utf-8")
    (items / "dec.md").write_text(
        text.replace("# conduction loss", "#  two spaces | and a pipe "),
        encoding="utf-8",
    )
    result = calc_rewrite.apply(str(calc_project))
    assert result.ok, result.errors
    after = (items / "dec.md").read_text(encoding="utf-8")
    assert "P = V * I | W  #  two spaces | and a pipe " in after


ALIGNED_MD = """---
type: decision
id: DEC-003
title: Aligned block
---

```calc
V_out   = 3.3 V
I_load  = 1.2 A
eff     = 0.9
P_out   : W      = V_out * I_load
P_diss  : W      = P_out * (1/eff - 1)  # converter loss at full load
P_dens  : W/in^2 = P_diss / 4 cm^2
```
"""


def _equals_columns(text):
    cols = []
    in_block = False
    for line in text.splitlines():
        if line.strip().startswith("```calc"):
            in_block = True
            continue
        if in_block and line.strip() == "```":
            in_block = False
            continue
        if in_block and "=" in line:
            cols.append(line.index("="))
    return cols


def test_rewrite_preserves_equals_column(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    path = items / "aligned.md"
    path.write_text(ALIGNED_MD, encoding="utf-8")
    before = _equals_columns(ALIGNED_MD)
    assert before == [8, 8, 8, 17, 17, 17]

    result = calc_rewrite.apply(str(tmp_path))
    assert result.ok, result.errors
    after_text = path.read_text(encoding="utf-8")
    # Every = in the block sits in exactly the column it was in.
    assert _equals_columns(after_text) == before
    assert f"{'P_out':<17}= V_out * I_load | W" in after_text
    assert "P_diss  " in after_text  # name column untouched too
    assert "# converter loss at full load" in after_text
    # Plain aligned lines are not rewritten at all.
    assert "V_out   = 3.3 V" in after_text
    # And the rewrite is still idempotent on aligned lines.
    second = calc_rewrite.apply(str(tmp_path))
    assert second.ok and second.changed_files == []


def test_cli_calc_rewrite_no_write_behaves_as_dry_run(calc_project, monkeypatch, capsys):
    monkeypatch.chdir(calc_project)
    before = (calc_project / "items" / "dec.md").read_bytes()
    code = cli.main(["--no-write", "calc-rewrite"])
    assert code == 0
    out = capsys.readouterr().out
    assert "would rewrite" in out
    assert (calc_project / "items" / "dec.md").read_bytes() == before

    code = cli.main(["calc-rewrite"])
    assert code == 0
    assert "rewrote" in capsys.readouterr().out
    assert (calc_project / "items" / "dec.md").read_bytes() != before
