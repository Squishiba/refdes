"""Field references in calc blocks and inline spans (live inline-calc G1).

`Rds = DEC-001.$rds_on` names one *field* of the target item -- the `$` is
what separates the field from the target's calc value of the same name. The
field read is the saved item, not its evaluated calc env, so a field
reference creates no dependency edge (a self-reference `ITEM.$field` in ITEM
is not a cycle, while the bare self-reference keeps its cycle), the field
value enters no hash, and a moved field value reaches the author through the
computed result and the stale-span release gate. The whole right-hand side
must be the reference (with its optional pipe unit); a field spliced into
arithmetic is a clear error naming the two-step form.
"""

from __future__ import annotations

import re

from conftest import write_project_config

from refdes import build as build_mod
from refdes import calc_rewrite, keys, links, parse
from refdes.schema import load_project

BASIC_CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      rds_on: { type: text }\n"
    "      limit: { type: text }\n"
    "      V_in: { type: text }\n"
    "      blank: { type: text }\n"
    "      tags: { type: list }\n"
    "      rds-on: { type: text }\n"
    "      2stage: { type: text }\n"
)


def _write_items(tmp_path, files: dict[str, str]):
    write_project_config(tmp_path, BASIC_CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, body in files.items():
        (items / name).write_text(body, encoding="utf-8")


def _item_md(
    item_id: str, body: str, fields: dict[str, str] | None = None
) -> str:
    lines = [f"id: {item_id}", "type: decision"]
    for key, value in (fields or {}).items():
        lines.append(f"{key}: {value}" if value != "" else f"{key}:")
    return "---\n" + "\n".join(lines) + f"\n---\n\n{body}"


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


RESISTOR = _item_md("DEC-001", "A resistor.\n", {"rds_on": "18 mohm", "limit": "5 V"})


# ------------------------------------------------------------ evaluation


def test_fence_field_reference_resolves(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md("DEC-002", "```calc\nRds = DEC-001.$rds_on | mohm\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    assert project.item_by_id("DEC-002").calc_values["Rds"] == "18 m\u03a9"


def test_span_field_reference_resolves(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md(
                "DEC-002",
                "The FET is `Rds2 := DEC-001.$rds_on | mohm = 18 mohm` hot.\n",
            ),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    assert not project.warnings
    assert project.item_by_id("DEC-002").calc_values["Rds2"] == "18 m\u03a9"


def test_arithmetic_on_a_field_reference_works(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md(
                "DEC-002",
                "```calc\nRds = DEC-001.$rds_on | mohm\nP = Rds * (2 A) * (2 A) | mW\n```\n",
            ),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    # 18 mohm * 4 A^2 = 72 mW -- the field arrived as a quantity.
    assert project.item_by_id("DEC-002").calc_values["P"] == "72 mW"


def test_dollar_in_larger_arithmetic_is_a_clear_error(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md("DEC-002", "```calc\nX = DEC-001.$rds_on * 2\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "whole right-hand side" in d.message]
    assert errors, project.errors
    assert "ITEM.$field" in errors[0].message


def test_hyphenated_field_name_gets_its_own_error(tmp_path):
    # The schema key `rds-on` is legal; the reference grammar's name half is
    # identifier-only. The error names the field and the rule -- it does NOT
    # blame the shape ("must be the whole right-hand side") -- and lists the
    # declared names that DO qualify.
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "A resistor.\n", {"rds-on": "18 mohm"}),
            "b.md": _item_md("DEC-002", "```calc\nQ = DEC-001.$rds-on\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "cannot be referenced with $" in d.message]
    assert errors, project.errors
    assert "'rds-on'" in errors[0].message
    assert "identifier-style" in errors[0].message
    assert "the item type declares: V_in, blank, limit, rds_on, tags" in (
        errors[0].message
    )
    assert "whole right-hand side" not in errors[0].message


def test_leading_digit_field_name_gets_its_own_error(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "A resistor.\n", {"2stage": "5 V"}),
            "b.md": _item_md("DEC-002", "```calc\nQ = DEC-001.$2stage\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "cannot be referenced with $" in d.message]
    assert errors, project.errors
    assert "'2stage'" in errors[0].message
    assert "whole right-hand side" not in errors[0].message


def test_block_qualified_field_reference_is_rejected(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md(
                "DEC-002", "```calc\nQ = DEC-001.losses.$rds_on\n```\n"
            ),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "names a block" in d.message]
    assert errors, project.errors
    # The suggestion names the field form, not the calc-value spelling.
    assert "ITEM.$field" in errors[0].message
    assert "DEC-001.$rds_on" in errors[0].message


# ------------------------------------------------------------ field errors


def test_quantity_fields_resolve(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md(
                "DEC-002", "```calc\nS = DEC-001.$limit\nN = DEC-001.$rds_on\n```\n"
            ),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    b = project.item_by_id("DEC-002")
    assert b.calc_values["S"] == "5 V"
    assert b.calc_values["N"] == "18 m\u03a9"


def test_tolerance_in_field_value_is_not_a_quantity(tmp_path):
    # The field read is `parse_quantity` (the bare-quantity parse), not the
    # assignment parse -- the `±` split only lives on calc lines, so a
    # tolerance in the field value is the same loud not-a-quantity error.
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "A resistor.\n", {"V_in": "12 V ± 5%"}),
            "b.md": _item_md("DEC-002", "```calc\nv = DEC-001.$V_in\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "not a quantity" in d.message]
    assert errors, project.errors
    assert "'V_in'" in errors[0].message
    assert "DEC-001" in errors[0].message


def test_text_field_is_an_eval_error_naming_the_field(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "A resistor.\n", {"limit": "approved"}),
            "b.md": _item_md("DEC-002", "```calc\nS = DEC-001.$limit | V\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "not a quantity" in d.message]
    assert errors, project.errors
    assert "'limit'" in errors[0].message
    assert "DEC-001" in errors[0].message


def test_undeclared_field_lists_declared_fields(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md("DEC-002", "```calc\nN = DEC-001.$nope\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "has no field 'nope'" in d.message]
    assert errors, project.errors
    assert "it declares: 2stage, V_in, blank, limit, rds-on, rds_on, tags" in errors[0].message


def test_empty_field_lists_declared_fields(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "A resistor.\n", {"rds_on": "18 mohm", "blank": ""}),
            "b.md": _item_md("DEC-002", "```calc\nE = DEC-001.$blank\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "field 'blank' is empty" in d.message]
    assert errors, project.errors
    assert "it declares: 2stage, V_in, blank, limit, rds-on, rds_on, tags" in errors[0].message


def test_list_valued_field_is_out_of_scope(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "A resistor.\n", {"rds_on": "18 mohm"}),
            "b.md": _item_md(
                "DEC-002", "```calc\nL = DEC-001.$tags\n```\n", {"tags": "[-]"}
            ),
        },
    )
    project = _load(tmp_path, write=False)
    # `tags` is a list-typed field of the decision type, declared for every
    # item of it; a reference into it is out of scope by shape, set or not.
    errors = [d for d in project.errors if "list-valued field" in d.message]
    assert errors, project.errors


def test_declared_list_field_is_out_of_scope(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md("DEC-001", "A resistor.\n", {"rds_on": "18 mohm", "tags": "[-]"}),
            "b.md": _item_md("DEC-002", "```calc\nL = DEC-001.$tags\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    errors = [d for d in project.errors if "list-valued field" in d.message]
    assert errors, project.errors


# ------------------------------------------------------------ collisions


def test_collision_warns_and_resolves_to_calc(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md(
                "DEC-001", "```calc\nV_in = 12 V\n```\n",
                {"rds_on": "18 mohm", "V_in": "5 V"},
            ),
            "b.md": _item_md("DEC-002", "```calc\nW = DEC-001.V_in\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    assert project.item_by_id("DEC-002").calc_values["W"] == "12 V"
    warnings = [d for d in project.warnings if "both a calc value" in d.message]
    assert warnings, project.warnings
    assert "$V_in" in warnings[0].message


def test_collision_with_empty_field_warns(tmp_path):
    # The decided policy warns whenever BOTH exist -- an empty string, a
    # null, a list included -- because the bare reference silently resolves
    # to the calc value in every case.
    for label, saved in (("empty", '""'), ("null", "")):
        _write_items(
            tmp_path,
            {
                "a.md": _item_md(
                    "DEC-001", "```calc\nblank = 12 V\n```\n", {"blank": saved}
                ),
                "b.md": _item_md("DEC-002", "```calc\nW = DEC-001.blank\n```\n"),
            },
        )
        project = _load(tmp_path, write=False)
        assert not project.errors, (label, project.errors)
        assert project.item_by_id("DEC-002").calc_values["W"] == "12 V"
        warnings = [d for d in project.warnings if "both a calc value" in d.message]
        assert warnings, (label, project.warnings)
        assert "$blank" in warnings[0].message, (label, warnings[0].message)


def test_collision_with_list_field_warns(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md(
                "DEC-001", "```calc\ntags = 12 V\n```\n", {"tags": "[alpha, beta]"}
            ),
            "b.md": _item_md("DEC-002", "```calc\nW = DEC-001.tags\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors, project.errors
    assert project.item_by_id("DEC-002").calc_values["W"] == "12 V"
    warnings = [d for d in project.warnings if "both a calc value" in d.message]
    assert warnings, project.warnings
    assert "list-valued" in warnings[0].message
    assert "$tags" not in warnings[0].message


def test_explicit_dollar_reads_the_field_and_is_silent(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md(
                "DEC-001", "```calc\nV_in = 12 V\n```\n",
                {"rds_on": "18 mohm", "V_in": "5 V"},
            ),
            "b.md": _item_md("DEC-002", "```calc\nF = DEC-001.$V_in\n```\n"),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    assert not project.warnings
    assert project.item_by_id("DEC-002").calc_values["F"] == "5 V"


# ------------------------------------------------------------ cycles


def test_own_id_field_reference_is_not_a_cycle(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md(
                "DEC-001", "```calc\nRds_self = DEC-001.$rds_on\n```\n",
                {"rds_on": "18 mohm"},
            ),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    assert project.item_by_id("DEC-001").calc_values["Rds_self"] == "18 m\u03a9"


def test_bare_own_id_calc_reference_is_still_a_cycle(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md(
                "DEC-001", "```calc\nVb = 1 V\nYb = DEC-001.Vb\n```\n"
            ),
        },
    )
    project = _load(tmp_path, write=False)
    assert any(
        "calc reference cycle: DEC-001 -> DEC-001" in d.message
        for d in project.errors
    ), project.errors


def test_field_reference_creates_no_dependency_edge(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": _item_md(
                "DEC-001", "```calc\nX = DEC-002.Vb\n```\n", {"rds_on": "18 mohm"}
            ),
            "b.md": _item_md(
                "DEC-002",
                "```calc\nVb = 1 V\nRds = DEC-001.$rds_on | mohm\n```\n",
            ),
        },
    )
    # A's bare reference is an edge A -> B; B's field reference into A is
    # not. With an edge here this pair would be a cycle; without one, both
    # values compute.
    project = _load(tmp_path, write=False)
    assert not project.errors
    assert project.item_by_id("DEC-001").calc_values["X"] == "1 V"
    assert project.item_by_id("DEC-002").calc_values["Rds"] == "18 m\u03a9"


# ------------------------------------------------------------ hashes


def test_hash_format_unchanged(tmp_path):
    assert build_mod.HASH_FORMAT == 6


def test_field_reference_values_never_reach_the_snapshot(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md(
                "DEC-002",
                "```calc\nRds = DEC-001.$rds_on | mohm\n```\n\n"
                "Also `Rds2 := DEC-001.$rds_on | mohm = 18 mohm`.\n",
            ),
        },
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    b = project.item_by_id("DEC-002")
    assert build_mod.calc_reference_snapshot(project, b) == {}


def test_field_edit_moves_the_value_not_the_hashes(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md(
                "DEC-002",
                "```calc\nRds = DEC-001.$rds_on | mohm\n```\n\n"
                "Also `Rds2 := DEC-001.$rds_on | mohm = 18 mohm`.\n",
            ),
        },
    )
    project = _load(tmp_path, write=False)
    b = project.item_by_id("DEC-002")
    hash_before, calc_hash_before = b.content_hash, build_mod.calc_hash_for(b)

    a_file = tmp_path / "items" / "a.md"
    a_file.write_text(
        a_file.read_text(encoding="utf-8").replace(
            "rds_on: 18 mohm", "rds_on: 20 mohm"
        ),
        encoding="utf-8",
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    b = project.item_by_id("DEC-002")
    assert b.calc_values["Rds"] == "20 m\u03a9"
    # The field value is not part of this item's content hash, and the
    # reference's arithmetic text did not move, so neither hash moved.
    assert b.content_hash == hash_before
    assert build_mod.calc_hash_for(b) == calc_hash_before
    # The stale span is the loud channel the author sees.
    assert any("stored result" in d.message for d in project.warnings), (
        project.warnings
    )


# ------------------------------------------------------------ expansion


def test_composite_field_reference_expands_and_survives_rename(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md("DEC-002", "```calc\nRds = DEC-001.$rds_on | mohm\n```\n"),
        },
    )
    project = _load(tmp_path, write=True)
    assert not project.errors
    b_file = tmp_path / "items" / "b.md"
    text = b_file.read_text(encoding="utf-8")
    assert "Rds = DEC-001@" in text  # anchored to the composite
    key = re.search(r"DEC-001@([0-9a-z]+)\.\$rds_on", text).group(1)

    a_file = tmp_path / "items" / "a.md"
    a_file.write_text(
        a_file.read_text(encoding="utf-8").replace("id: DEC-001", "id: DEC-777"),
        encoding="utf-8",
    )
    project = _load(tmp_path, write=True)
    assert not project.errors
    text = b_file.read_text(encoding="utf-8")
    assert f"Rds = DEC-777@{key}.$rds_on" in text  # display half refreshed
    assert project.item_by_id("DEC-002").calc_values["Rds"] == "18 m\u03a9"


def test_bare_and_composite_field_reference_hashes_match(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md("DEC-002", "```calc\nRds = DEC-001.$rds_on | mohm\n```\n"),
        },
    )
    _load(tmp_path, write=True)  # the writer expands the reference
    b_file = tmp_path / "items" / "b.md"
    composite = b_file.read_text(encoding="utf-8")
    assert "Rds = DEC-001@" in composite
    composite_hash = _load(tmp_path, write=False).item_by_id("DEC-002").content_hash

    b_file.write_text(
        re.sub(r"DEC-001@\S+?\.\$rds_on", "DEC-001.$rds_on", composite),
        encoding="utf-8",
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    # The target half of a field reference hashes to the same token as every
    # other reference: bare and composite spellings are hash-identical.
    assert project.item_by_id("DEC-002").content_hash == composite_hash


def test_bare_key_item_half_resolves(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md("DEC-002", "```calc\nRds = DEC-001.$rds_on | mohm\n```\n"),
        },
    )
    _load(tmp_path, write=True)
    a_text = (tmp_path / "items" / "a.md").read_text(encoding="utf-8")
    key = re.search(r"^key: (\S+)$", a_text, re.MULTILINE).group(1)
    b_file = tmp_path / "items" / "b.md"
    b_file.write_text(
        b_file.read_text(encoding="utf-8").replace(
            f"DEC-001@{key}.$rds_on", f"{key}.$rds_on"
        ),
        encoding="utf-8",
    )
    project = _load(tmp_path, write=False)
    assert not project.errors
    assert project.item_by_id("DEC-002").calc_values["Rds"] == "18 m\u03a9"


def test_no_write_resolves_field_reference_and_changes_nothing(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md("DEC-002", "```calc\nRds = DEC-001.$rds_on | mohm\n```\n"),
        },
    )
    _load(tmp_path, write=True)
    b_file = tmp_path / "items" / "b.md"
    bare = re.sub(
        r"DEC-001@\S+?\.\$rds_on", "DEC-001.$rds_on",
        b_file.read_text(encoding="utf-8"),
    )
    b_file.write_text(bare, encoding="utf-8")

    project = _load(tmp_path, write=False)
    assert not project.errors
    assert project.item_by_id("DEC-002").calc_values["Rds"] == "18 m\u03a9"
    assert b_file.read_text(encoding="utf-8") == bare  # nothing written back


# ------------------------------------------------------------ calc-rewrite


def test_calc_rewrite_preserves_field_reference_lines(tmp_path):
    _write_items(
        tmp_path,
        {
            "a.md": RESISTOR,
            "b.md": _item_md(
                "DEC-002",
                "```calc\nRds = DEC-001.$rds_on | mohm\nP : mW = 1 V * 2 A\n```\n"
            ),
        },
    )
    # `P : mW = ...` is the retired spelling; `refdes calc-rewrite` migrates
    # it and must leave the field-reference line alone.
    result = calc_rewrite.apply(str(tmp_path))
    assert result.ok, result.errors
    text = (tmp_path / "items" / "b.md").read_text(encoding="utf-8")
    assert "Rds = DEC-001.$rds_on | mohm" in text
    assert "P = 1 V * 2 A | mW" in text
