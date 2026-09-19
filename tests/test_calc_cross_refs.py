"""Cross-item calc references (finding 35, chunk 1).

`V_in = DEC-PWR-001.V_in` inside a calc block reads a named value from another
item: a real dependency, evaluated in dependency order, stored expanded as a
`DISPLAY-ID@key` composite like every other structured reference, and a loud
error (never a silent default) when the target item or name is gone. Chunk 2
(the content-hash change) is deliberately not here.
"""

from __future__ import annotations

import re

from conftest import write_project_config

from refdes import build as build_mod
from refdes import keys, links, parse, render
from refdes.schema import load_project

BASIC_CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n  decision: { prefix: DEC, fields: {} }\n"
)


def _write_items(tmp_path, files: dict[str, str]):
    write_project_config(tmp_path, BASIC_CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, body in files.items():
        (items / name).write_text(body, encoding="utf-8")


def _item_md(item_id: str, body: str) -> str:
    return f"---\nid: {item_id}\ntype: decision\n---\n\n{body}"


def _load(tmp_path, write: bool = True):
    """The cli._load() pipeline a writable command runs -- mint, expand calc
    references -- then build. `write=False` is `--no-write`."""
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    minted = keys.mint_missing(project, write=write)
    if minted:
        project.items = {}
        project.items_by_id = {}
        project.pending = []
        parse.load_items(project)
    links.expand_missing_calc_refs(project, write=write)
    build_mod.build(project)
    return project


# ------------------------------------------------------------ resolution


def test_reference_resolves_with_unit_and_tolerance(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 12 V ± 5%\n```\n"),
            "b.md": _item_md(
                "DEC-002",
                "```calc\nV_in = DEC-001.V_in\nP = V_in * 2 A | W\n```\n",
            ),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    b = project.item_by_id("DEC-002")
    assert b.calc_values["V_in"] == "12 V"
    # The ±5% arrives intact: 22.8 W … 25.2 W, not a suspiciously tight 24 W.
    assert b.calc_values["P"] == "24 W"
    line = next(c for c in b.calcs if c.name == "P")
    assert line.bounds == "22.8 W … 25.2 W"


def test_reference_with_pipe_unit_converts(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 12 V\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nV_mv = DEC-001.V_in | mV\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    assert project.item_by_id("DEC-002").calc_values["V_mv"] == "12000 mV"


def test_reference_wrong_dimension_reports_like_any_other(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 12 V\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nP = DEC-001.V_in | W\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "declared as W" in d.message]
    assert errors, project.errors
    assert "evaluates to V" in errors[0].message


def test_duplicate_name_rule_survives_references(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 12 V\n```\n"),
            "b.md": _item_md(
                "DEC-002",
                "```calc\nV_in = 5 V\nV_in = DEC-001.V_in\n```\n",
            ),
        },
    )
    project = _load(tmp_path, write=False)
    assert any("assigned twice" in d.message for d in project.errors)


# ------------------------------------------------------------ loud errors


def test_missing_item_errors_loudly_at_the_reference(tmp_path):
    _write_items(
        tmp_path,
        {
            "b.md": _item_md("DEC-002", "```calc\nV = DEC-NOPE.V_in\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "DEC-NOPE" in d.message]
    assert errors, project.errors
    d = errors[0]
    assert "no item 'DEC-NOPE'" in d.message
    assert "DEC-002.V_in" not in d.message  # the reference text is quoted whole
    assert "DEC-NOPE.V_in" in d.message
    assert d.item_id == "DEC-002"
    assert d.line is not None


def test_missing_name_errors_naming_what_the_target_defines(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 12 V\nI_out = 1 A\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nX = DEC-001.Iout\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "Iout" in d.message]
    assert errors, project.errors
    d = errors[0]
    assert "does not define 'Iout'" in d.message
    assert "it defines: I_out, V_in" in d.message
    assert d.item_id == "DEC-002"


# ------------------------------------------------------------ cycles


def test_two_item_cycle_names_the_cycle(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV = DEC-002.W\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nW = DEC-001.V\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    cycles = [d for d in project.errors if "calc reference cycle:" in d.message]
    assert len(cycles) == 1, project.errors
    path = cycles[0].message.split("calc reference cycle:")[1].strip()
    parts = [p.strip() for p in path.split("->")]
    assert parts == ["DEC-001", "DEC-002", "DEC-001"] or parts == [
        "DEC-002",
        "DEC-001",
        "DEC-002",
    ]


def test_three_item_cycle_names_the_full_cycle(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV = DEC-002.W\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nW = DEC-003.U\n```\n"),
            "c.md": _item_md("DEC-003", "```calc\nU = DEC-001.V\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    cycles = [d for d in project.errors if "calc reference cycle:" in d.message]
    assert len(cycles) == 1, project.errors
    path = cycles[0].message.split("calc reference cycle:")[1].strip()
    parts = [p.strip() for p in path.split("->")]
    assert len(parts) == 4
    assert parts[0] == parts[-1]
    assert set(parts[:-1]) == {"DEC-001", "DEC-002", "DEC-003"}


# ------------------------------------------------- upstream failure notes


def test_upstream_calc_failure_is_reported_as_such(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md(
                "DEC-001", "```calc\nV_in = 3.3 V\nX = 1 V + 1 A\n```\n"
            ),
            "b.md": _item_md("DEC-002", "```calc\nV = DEC-001.V_in\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    root = [d for d in project.errors if "cannot add" in d.message]
    assert len(root) == 1, project.errors
    notes = [d for d in project.errors if "own calc failed" in d.message]
    assert len(notes) == 1, project.errors
    assert "cannot resolve 'DEC-001.V_in'" in notes[0].message
    assert notes[0].item_id == "DEC-002"


# ------------------------------------------------- rename survival


def test_rename_of_target_refreshes_composite_and_still_resolves(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 3.3 V\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nV = DEC-001.V_in\n```\n"),
        },
    )
    project = _load(tmp_path, write=True)
    assert not project.errors
    b_file = tmp_path / "items" / "b.md"
    text = b_file.read_text(encoding="utf-8")
    assert "V = DEC-001@" in text  # frozen to the composite
    key = re.search(r"DEC-001@([0-9a-z]+)\.V_in", text).group(1)

    # Rename the target's display id; the reference's key half is unchanged.
    a_file = tmp_path / "items" / "a.md"
    a_file.write_text(
        a_file.read_text(encoding="utf-8").replace("id: DEC-001", "id: DEC-777"),
        encoding="utf-8",
    )
    project = _load(tmp_path, write=True)
    assert not project.errors
    text = b_file.read_text(encoding="utf-8")
    assert f"V = DEC-777@{key}.V_in" in text  # display half refreshed
    assert project.item_by_id("DEC-002").calc_values["V"] == "3.3 V"


def test_no_write_resolves_bare_and_changes_nothing(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 3.3 V\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nV = DEC-001.V_in\n```\n"),
        },
    )
    # Mint keys writably, then leave the reference bare (as if authored on a
    # machine that only ever ran --no-write since adoption).
    _load(tmp_path, write=True)
    b_file = tmp_path / "items" / "b.md"
    bare = re.sub(r"DEC-001@\S+?\.V_in", "DEC-001.V_in",
                  b_file.read_text(encoding="utf-8"))
    b_file.write_text(bare, encoding="utf-8")

    project = _load(tmp_path, write=False)
    assert not project.errors
    assert project.item_by_id("DEC-002").calc_values["V"] == "3.3 V"
    assert b_file.read_text(encoding="utf-8") == bare  # nothing written back
    assert any("calc reference has not been expanded" in d.message
               for d in project.infos)


# ------------------------------------------------- rendering and export


def test_rendered_table_shows_the_reference_readably(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 3.3 V\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nV = DEC-001.V_in\n```\n"),
        },
    )
    project = _load(tmp_path, write=True)  # expands to the composite in source
    assert not project.errors
    html = project.item_by_id("DEC-002").body_html
    # Readable display form (linkified to the target page, like every other
    # id the renderer prints)...
    assert ">DEC-001</a>.V_in" in html
    # ...key half never leaks into the page.
    assert "@" not in html


def test_items_json_export_shows_the_reference(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "```calc\nV_in = 3.3 V\n```\n"),
            "b.md": _item_md("DEC-002", "```calc\nV = DEC-001.V_in\n```\n"),
        },
    )
    project = _load(tmp_path, write=True)
    assert not project.errors
    payload = render.items_json(project)
    entry = next(i for i in payload["items"] if i["id"] == "DEC-002")
    line = entry["calcs"][0]
    assert line["name"] == "V"
    assert line["expression"] == "DEC-001.V_in"  # readable, key half hidden
    assert line["reference"].startswith("DEC-001@")  # raw composite preserved
    assert line["result"] == "3.3 V"
