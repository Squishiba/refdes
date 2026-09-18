"""calc-rewrite (chunk 2 of the unit-syntax change): the transactional
`name : unit = expr` -> `name = expr | unit` rewrite command.

Every test here fails on main before calc_rewrite.py exists (import error),
which is the honest baseline for a new command.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import calc, calc_rewrite, cli, lifecycle, parse
from refdes.model import CHECK_VIOLATION
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
    project = _load(calc_project)  # default build seals append-only entries
    assert not [d for d in project.errors]
    build_mod.build(project, seal_write=True, reseal=False, accept_board_move=False)

    result = calc_rewrite.apply(str(calc_project))
    assert result.ok, result.errors
    assert len(result.sealed_entries) == 1
    assert "items/log.yaml" in result.sealed_entries[0]
    assert "LOG-001" in result.sealed_entries[0]

    log_text = (calc_project / "items" / "log.yaml").read_text(encoding="utf-8")
    assert "P : W = 12 V * 0.5 A" in log_text  # untouched
    dec_text = (calc_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "P = V * I | W" in dec_text  # everything else rewritten

    # And the untouched sealed entry still builds clean on the old spelling.
    project2 = _load(calc_project)
    assert not [d for d in project2.errors if d.code != CHECK_VIOLATION]


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
