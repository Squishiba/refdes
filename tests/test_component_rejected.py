"""Phase 4 (layout) tests for docs/design/candidate-parts.md §6.

Two of the six tests from §9's table, the ones this task owns:
`test_defaults_status_warning` (a `defaults:`-declared status no item in
the file actually carries is dead configuration, cached as a warning) and
`test_new_list_skeleton` (`refdes new <type> --list`, the list-file
skeleton printer). The other four -- `test_rejected_never_satisfies`,
`test_selects_rejected_component_warns`, `test_rejected_stays_on_parts_page`,
`test_hardware3_component_choices` -- are the Phase 1/3 work and land in a
separate change, so this file can be merged independently.
"""

from __future__ import annotations

import yaml

from refdes import cli as cli_mod
from refdes import parse
from refdes import scaffold as scaffold_mod
from refdes.schema import load_project


# ------------------------------------------------------------------- the warning


def test_defaults_status_warning(tmp_path):
    """A list file whose `defaults:` declares a `status` value no item in
    the file actually has (every entry's own value won) is dead
    configuration and warns. Everything is content-derived: nothing about
    the file's name or location is read, so renaming the file changes
    nothing the warning depends on (candidate parts §6.3, §6.1)."""
    scaffold_mod.init(str(tmp_path))
    power = tmp_path / "items" / "power"
    power.mkdir(parents=True)
    (power / "candidates.yaml").write_text(
        "defaults:\n"
        "  type: component\n"
        "  status: candidate\n"
        "\n"
        "items:\n"
        "  - id: CMP-PWR-001\n"
        "    title: The winner\n"
        "    status: selected\n"
        "  - id: CMP-PWR-002\n"
        "    title: The loser\n"
        "    status: rejected\n",
        encoding="utf-8",
    )
    project = load_project(start=str(tmp_path))
    parse.load_items(project)

    dead = [d for d in project.warnings if "dead configuration" in d.message]
    assert len(dead) == 1
    message = dead[0].message
    assert "'status: candidate'" in message
    assert "candidates.yaml" not in message  # not path-derived
    assert dead[0].file == "items/power/candidates.yaml"
    assert dead[0].line == 2  # the defaults: block's own first key line

    # Renaming the file changes nothing: same warning, same text.
    (power / "candidates.yaml").rename(power / "shortlist.yaml")
    renamed = load_project(start=str(tmp_path))
    parse.load_items(renamed)
    again = [d for d in renamed.warnings if "dead configuration" in d.message]
    assert len(again) == 1
    assert again[0].message == message

    # One item actually in the declared status: the default is doing its
    # job, so the same defaults: block warns nothing.
    (power / "matched.yaml").write_text(
        "defaults:\n"
        "  type: component\n"
        "  status: candidate\n"
        "\n"
        "items:\n"
        "  - id: CMP-PWR-003\n"
        "    title: Still a candidate\n",
        encoding="utf-8",
    )
    matched = load_project(start=str(tmp_path))
    parse.load_items(matched)
    matched_dead = [
        d for d in matched.warnings
        if d.file == "items/power/matched.yaml" and "dead configuration" in d.message
    ]
    assert not matched_dead


# ---------------------------------------------------------------- the --list flag


def test_new_list_skeleton(tmp_path, capsys):
    """`refdes new <type> --list` prints a list-file skeleton: a `defaults:`
    block carrying the items' shared type and the status field's default,
    then one empty entry. It prints the mapping form a list file must have
    (defaults: plus an items: key), writes nothing, and a type with no
    status field emits no status: line at all (candidate parts §6.4)."""
    scaffold_mod.init(str(tmp_path))
    config = str(tmp_path / "refdes-project.yaml")
    before = _tree(tmp_path)

    status = cli_mod.main(["-c", config, "new", "component", "--list"])
    assert status == 0
    out = capsys.readouterr().out
    assert "defaults:" in out
    assert "type: component" in out
    assert "status: candidate" in out
    assert "items:" in out
    assert "  - id:" in out
    assert "title:  # required" in out

    # The output is loadable as the mapping form parse_list_file requires --
    # redirecting it into place cannot produce a rejected list file.
    parsed = yaml.safe_load(out)
    assert isinstance(parsed, dict)
    assert parsed["defaults"]["type"] == "component"
    assert parsed["defaults"]["status"] == "candidate"
    assert len(parsed["items"]) == 1
    entry = parsed["items"][0]
    assert entry["id"] is None
    assert "title" in entry
    assert "status" not in entry

    # A type with no status field (hardware@3's log) emits no status: line
    # at all and no dead default for a skeleton that can't use one.
    status = cli_mod.main(["-c", config, "new", "log", "--list"])
    assert status == 0
    out_log = capsys.readouterr().out
    assert "type: log" in out_log
    assert "date:  # required" in out_log
    assert "status" not in out_log

    # new writes nothing with or without --no-write, so composing the print
    # with a redirect is safe and --no-write keeps it side-effect-free.
    status = cli_mod.main(["--no-write", "-c", config, "new", "component", "--list"])
    assert status == 0
    assert capsys.readouterr().out == out
    assert _tree(tmp_path) == before


def _tree(root):
    return sorted(
        str(p.relative_to(root)).replace("\\", "/")
        for p in root.rglob("*")
        if p.is_file()
    )