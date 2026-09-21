"""`extends:` -- single-level type inheritance (docs/design/extends.md).

Phase 1 (engine): resolution order, what is and is not inherited, the Liskov
guards, and the single-level rule. Later phases append consumers, the
coverage-grouping setting and the hardware@3 oracle below.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import render, standards
from refdes.schema import SchemaError, load_project
from refdes.schema_json import build_schema

PARENT = (
    "link_types:\n"
    "  refines: { inverse: refined_by }\n"
    "types:\n"
    "  req:\n"
    "    prefix: REQ\n"
    "    label: Requirement\n"
    "    plural: Requirements\n"
    "    doc: The parent.\n"
    "    coverable: true\n"
    "    coverable_statuses: [active]\n"
    "    preview: [status, title]\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      status: { type: enum, choices: [draft, active], default: draft }\n"
    "    links:\n"
    "      refines: [req]\n"
    "    body: { on_change: invalidate, required: true }\n"
)

CHILD = (
    "  bnd:\n"
    "    extends: req\n"
    "    prefix: BND\n"
    "    label: Bound\n"
    "    plural: Bounds\n"
    "    fields:\n"
    "      limit: { type: limit, required: true }\n"
)


def _load(tmp_path, schema: str):
    write_project_config(tmp_path, "site: { title: T, out: _site }\n" + schema)
    return load_project(config_path=str(tmp_path / "refdes-project.yaml"))


def _err(tmp_path, schema: str) -> str:
    with pytest.raises(SchemaError) as exc:
        _load(tmp_path, schema)
    return str(exc.value)


# ------------------------------------------------------------- inheritance


def test_child_inherits_fields_links_body_and_coverage_flags(tmp_path):
    project = _load(tmp_path, PARENT + CHILD)
    bnd = project.types["bnd"]
    assert bnd.extends == "req"
    assert project.types["req"].extends == ""
    assert set(bnd.fields) == {"title", "status", "limit"}
    assert bnd.links == {"refines": ["req"]}
    assert bnd.body_required is True and bnd.body_on_change == "invalidate"
    assert bnd.preview == ["status", "title"]
    # Q2: coverable and coverable_statuses travel with the type.
    assert bnd.coverable is True
    assert bnd.coverable_statuses == ["active"]


def test_prefix_label_plural_are_the_childs_own(tmp_path):
    bnd = _load(tmp_path, PARENT + CHILD).types["bnd"]
    assert (bnd.prefix, bnd.label, bnd.plural) == ("BND", "Bound", "Bounds")


@pytest.mark.parametrize("missing", ["prefix", "label", "plural"])
def test_child_missing_identity_property_is_an_error(tmp_path, missing):
    child = "".join(
        line for line in CHILD.splitlines(keepends=True)
        if not line.startswith(f"    {missing}:")
    )
    message = _err(tmp_path, PARENT + child)
    assert f"types.bnd extends 'req' but does not declare {missing!r}" in message


def test_doc_is_not_inherited(tmp_path):
    project = _load(tmp_path, PARENT + CHILD)
    assert project.types["req"].doc == "The parent."
    assert project.types["bnd"].doc == ""


def test_field_override_replaces_the_whole_definition(tmp_path):
    """Q4: not deep-merged -- the child's `status` keeps nothing of the
    parent's choices or default."""
    project = _load(
        tmp_path,
        PARENT + CHILD + "      status: { type: enum, choices: [open, closed] }\n",
    )
    status = project.types["bnd"].fields["status"]
    assert status.choices == ["open", "closed"]
    assert status.default is None


def test_link_override_replaces_the_target_list(tmp_path):
    project = _load(
        tmp_path, PARENT + CHILD + "    links:\n      refines: [bnd]\n"
    )
    assert project.types["bnd"].links["refines"] == ["bnd"]
    assert project.types["req"].links["refines"] == ["req"]


def test_null_link_suppresses_an_inherited_link(tmp_path):
    """`links: { verb: null }` removes the inherited verb -- distinct from
    omitting it (inherited) and from `[]` (declared, unrestricted)."""
    both = PARENT.replace(
        "      refines: [req]\n", "      refines: [req]\n      governed_by: [req]\n"
    ).replace(
        "  refines: { inverse: refined_by }\n",
        "  refines: { inverse: refined_by }\n  governed_by: { inverse: governs }\n",
    )
    inherited = _load(tmp_path, both + CHILD).types["bnd"].links
    assert inherited["governed_by"] == ["req"]
    unrestricted = _load(tmp_path, both + CHILD + "    links:\n      governed_by: []\n")
    assert unrestricted.types["bnd"].links["governed_by"] == []
    suppressed = _load(tmp_path, both + CHILD + "    links:\n      governed_by: null\n")
    assert "governed_by" not in suppressed.types["bnd"].links
    assert suppressed.types["bnd"].links["refines"] == ["req"]
    assert "governed_by" in suppressed.types["req"].links


def test_null_link_the_parent_never_declared_is_an_error(tmp_path):
    message = _err(tmp_path, PARENT + CHILD + "    links:\n      derives_from: null\n")
    assert "types.bnd.links.derives_from is null" in message
    assert "'req' declares no link 'derives_from'" in message


def test_own_body_and_scalars_replace_the_parents(tmp_path):
    project = _load(
        tmp_path,
        PARENT + CHILD
        + "    body: { on_change: log }\n    coverable: false\n",
    )
    bnd = project.types["bnd"]
    assert bnd.body_on_change == "log" and bnd.body_required is False
    assert bnd.coverable is False


def test_inherited_fields_come_first_then_the_childs_own_in_order(tmp_path):
    project = _load(
        tmp_path,
        PARENT
        + CHILD
        + "      title: { type: text, required: true }\n"
        + "      extra: { type: text }\n",
    )
    assert list(project.types["bnd"].fields) == ["status", "limit", "title", "extra"]


def test_overlay_edit_to_the_parent_reaches_the_child(tmp_path):
    """Resolution runs on the merged schema, so a field added to the parent
    anywhere in the layering is inherited (extends.md §2.3)."""
    project = _load(
        tmp_path,
        PARENT.replace(
            "    links:\n",
            "      rationale: { type: text }\n    links:\n",
        )
        + CHILD,
    )
    assert "rationale" in project.types["bnd"].fields


# ---------------------------------------------------------------- Liskov


def test_child_cannot_make_a_required_parent_field_optional(tmp_path):
    message = _err(tmp_path, PARENT + CHILD + "      title: { type: text }\n")
    assert (
        "types.bnd.fields.title is not required, but 'req' requires it" in message
    )


def test_child_may_keep_a_required_field_required(tmp_path):
    project = _load(
        tmp_path,
        PARENT + CHILD + "      title: { type: text, required: true, doc: Mine. }\n",
    )
    assert project.types["bnd"].fields["title"].doc == "Mine."


def test_child_cannot_lift_append_only(tmp_path):
    message = _err(
        tmp_path,
        (PARENT + CHILD).replace("    coverable: true\n", "    append_only: true\n", 1)
        + "    append_only: false\n",
    )
    assert "types.bnd.append_only is false, but 'req' is append_only" in message


def test_append_only_is_inherited(tmp_path):
    project = _load(
        tmp_path,
        (PARENT + CHILD).replace("    coverable: true\n", "    append_only: true\n", 1),
    )
    assert project.types["bnd"].append_only is True


# ------------------------------------------------------------ single level


def test_multi_level_extends_is_an_error_with_the_spec_message(tmp_path):
    message = _err(
        tmp_path,
        PARENT
        + CHILD
        + "  thermal_bound:\n"
        "    extends: bnd\n"
        "    prefix: THB\n"
        "    label: Thermal bound\n"
        "    plural: Thermal bounds\n",
    )
    assert message == (
        "types.thermal_bound.extends names 'bnd', which itself extends 'req'. "
        "Single-level inheritance only; thermal_bound must extend 'req' "
        "directly or not use extends:."
    )


def test_extending_an_unknown_type_is_an_error(tmp_path):
    message = _err(tmp_path, PARENT + CHILD.replace("extends: req", "extends: rq"))
    assert "types.bnd.extends names unknown type 'rq'. Did you mean 'req'?" in message


def test_a_type_cannot_extend_itself(tmp_path):
    message = _err(tmp_path, PARENT + CHILD.replace("extends: req", "extends: bnd"))
    assert "types.bnd.extends names itself" in message


def test_extends_must_be_a_string(tmp_path):
    message = _err(tmp_path, PARENT + CHILD.replace("extends: req", "extends: [req]"))
    assert "types.bnd.extends must be a string" in message


# ------------------------------------------------------- subtype relation


def test_subtype_map_and_is_subtype(tmp_path):
    project = _load(tmp_path, PARENT + CHILD)
    assert project.subtype_map == {"req": {"bnd"}}
    assert project.is_subtype("bnd", "req")
    assert project.is_subtype("req", "req")
    assert not project.is_subtype("req", "bnd")


def test_accepts_type_is_the_allow_test(tmp_path):
    project = _load(tmp_path, PARENT + CHILD)
    assert project.accepts_type("bnd", ["req"])
    assert not project.accepts_type("req", ["bnd"])
    assert project.accepts_type("anything", [])  # empty list is unrestricted


# ------------------------------------------------------------ preset rule


def _bundle(tmp_path, monkeypatch, presets: dict[str, str]):
    root = tmp_path / "std" / "hardware" / "v1"
    (root / "presets").mkdir(parents=True)
    (root / "base.yaml").write_text(
        "types:\n"
        "  req:\n"
        "    prefix: REQ\n"
        "    fields:\n"
        "      title: { type: text }\n",
        encoding="utf-8",
    )
    for name, text in presets.items():
        (root / "presets" / f"{name}.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path / "std"))


def _preset_type(name: str, parent: str) -> str:
    return (
        f"types:\n  {name}:\n    extends: {parent}\n    prefix: {name[:3].upper()}\n"
        f"    label: {name}\n    plural: {name}s\n"
    )


def _load_with_presets(tmp_path, presets: list[str]):
    names = ", ".join(presets)
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        f"standard: {{ base: hardware, version: 1, presets: [{names}] }}\n",
    )
    return load_project(config_path=str(tmp_path / "refdes-project.yaml"))


def test_a_preset_may_extend_a_base_type(tmp_path, monkeypatch):
    _bundle(tmp_path, monkeypatch, {"p1": _preset_type("spec", "req")})
    assert _load_with_presets(tmp_path, ["p1"]).types["spec"].extends == "req"


def test_a_preset_may_not_extend_another_presets_type(tmp_path, monkeypatch):
    _bundle(
        tmp_path,
        monkeypatch,
        {"p1": _preset_type("spec", "req"), "p2": _preset_type("deep", "spec")},
    )
    with pytest.raises(SchemaError) as exc:
        _load_with_presets(tmp_path, ["p1", "p2"])
    assert "belongs to preset 'p1'" in str(exc.value)
    assert "presets are independent bundles" in str(exc.value)


# =========================================================================
# Phase 2: consumers -- link validation, coverage, index, completion, and
# the coverage.group_inherited setting.
# =========================================================================

CONSUMER_SCHEMA = (
    "link_types:\n"
    "  refines: { inverse: refined_by }\n"
    "  satisfies: { inverse: satisfied_by }\n"
    "  verifies: { inverse: verified_by }\n"
    "types:\n"
    "  req:\n"
    "    prefix: REQ\n"
    "    label: Requirement\n"
    "    plural: Requirements\n"
    "    coverable: true\n"
    "    coverable_statuses: [active]\n"
    "    fields:\n"
    "      title: { type: text }\n"
    "      status: { type: enum, choices: [draft, active], default: active }\n"
    "    links:\n"
    "      refines: [req]\n"
    "  bnd:\n"
    "    extends: req\n"
    "    prefix: BND\n"
    "    label: Bound\n"
    "    plural: Bounds\n"
    "    links:\n"
    "      refines: [bnd]\n"
    "  dec:\n"
    "    prefix: DEC\n"
    "    label: Decision\n"
    "    plural: Decisions\n"
    "    satisfying_statuses: [accepted]\n"
    "    fields:\n"
    "      title: { type: text }\n"
    "      status: { type: enum, choices: [proposed, accepted], default: proposed }\n"
    "    links:\n"
    "      satisfies: [req]\n"
    "  dec2:\n"
    "    extends: dec\n"
    "    prefix: DCB\n"
    "    label: Decision B\n"
    "    plural: Decisions B\n"
    "  tst:\n"
    "    prefix: TST\n"
    "    label: Test\n"
    "    plural: Tests\n"
    "    fields:\n"
    "      title: { type: text }\n"
    "    links:\n"
    "      verifies: [req]\n"
)

CONSUMER_ITEMS = (
    "items:\n"
    "  - { id: REQ-001, type: req, title: A requirement }\n"
    "  - { id: BND-001, type: bnd, title: A bound }\n"
    "  - { id: DEC-001, type: dec, status: accepted, title: Settled, satisfies: [BND-001] }\n"
    "  - { id: DCB-001, type: dec2, status: proposed, title: Unsettled, satisfies: [REQ-001] }\n"
    "  - { id: TST-001, type: tst, title: Proves it, verifies: [BND-001] }\n"
)


def _consumer_project(tmp_path, items: str = CONSUMER_ITEMS, settings: str = ""):
    write_project_config(
        tmp_path, "site: { title: T, out: _site }\n" + settings + CONSUMER_SCHEMA
    )
    (tmp_path / "items").mkdir(exist_ok=True)
    (tmp_path / "items" / "all.yaml").write_text(items, encoding="utf-8")
    return _build_at(tmp_path)


def test_subtype_satisfies_a_parent_link_target_list(tmp_path):
    """`dec.satisfies: [req]` accepts a `bnd`, `tst.verifies: [req]` too --
    no per-link marker, `extends:` is the whole commitment."""
    project = _consumer_project(tmp_path)
    assert not project.errors, [d.message for d in project.errors]
    assert project.item_by_id("DEC-001").resolved_links["satisfies"] == ["BND-001"]
    assert project.item_by_id("TST-001").resolved_links["verifies"] == ["BND-001"]


def test_a_parent_does_not_satisfy_a_list_naming_only_its_subtype(tmp_path):
    """Substitution runs one way: `bnd.refines: [bnd]` still refuses a plain req."""
    project = _consumer_project(
        tmp_path,
        CONSUMER_ITEMS + "  - { id: BND-002, type: bnd, title: X, refines: [REQ-001] }\n",
    )
    assert any(
        "refines may point at ['bnd'], but REQ-001 is a req" in d.message
        for d in project.errors
    ), [d.message for d in project.errors]


def test_coverage_of_a_subtype_item_follows_the_parents_rules(tmp_path):
    """BND-001 is coverable by inheritance (never declared on `bnd`): settled
    by DEC-001, proved by TST-001 -> verified."""
    project = _consumer_project(tmp_path)
    assert project.coverage["BND-001"].stage == "verified"
    assert project.coverage["BND-001"].satisfied_by == ["DEC-001"]


def test_coverage_honors_the_inherited_satisfying_statuses(tmp_path):
    """DCB-001 is a `dec2` (extends dec), which inherited `satisfying_statuses:
    [accepted]`: proposed -> the link is only a claim; accepted -> settled."""
    project = _consumer_project(tmp_path)
    assert project.coverage["REQ-001"].stage == "claimed"
    assert project.coverage["REQ-001"].claimed_by == ["DCB-001"]

    settled = CONSUMER_ITEMS.replace("status: proposed", "status: accepted")
    project = _consumer_project(tmp_path, settled)
    assert project.coverage["REQ-001"].stage == "satisfied"


def test_a_draft_subtype_item_is_left_out_by_the_inherited_statuses(tmp_path):
    items = CONSUMER_ITEMS + "  - { id: BND-002, type: bnd, status: draft, title: D }\n"
    project = _consumer_project(tmp_path, items)
    assert "BND-002" not in project.coverage


def _index_html(tmp_path, directive: str, settings: str = ""):
    _consumer_project(tmp_path, settings=settings)
    (tmp_path / "pages").mkdir(exist_ok=True)
    (tmp_path / "pages" / "index.md").write_text(
        f"# Overview\n\n{directive}\n", encoding="utf-8"
    )
    project = _build_at(tmp_path)
    return next(p for p in project.pages if p.slug == "index").body_html


def test_index_lists_subtypes_under_the_parent_when_grouping_is_on(tmp_path):
    html = _index_html(tmp_path, '{{index by="status" type="req"}}')
    assert "REQ-001" in html and "BND-001" in html
    assert "(bnd)" in html  # the badge marks the row that is not a plain req


def test_index_stays_concrete_when_grouping_is_off(tmp_path):
    html = _index_html(
        tmp_path,
        '{{index by="status" type="req"}}',
        settings="coverage: { group_inherited: false }\n",
    )
    assert "REQ-001" in html
    assert "BND-001" not in html


def test_index_subtypes_parameter_overrides_the_setting(tmp_path):
    on = _index_html(
        tmp_path,
        '{{index by="status" type="req" subtypes="true"}}',
        settings="coverage: { group_inherited: false }\n",
    )
    assert "BND-001" in on
    off = _index_html(tmp_path, '{{index by="status" type="req" subtypes="false"}}')
    assert "BND-001" not in off


def test_index_subtypes_parameter_must_be_a_boolean(tmp_path):
    html = _index_html(tmp_path, '{{index by="status" type="req" subtypes="maybe"}}')
    assert "subtypes must be true or false" in html


def test_index_of_the_subtype_itself_never_lists_the_parent(tmp_path):
    html = _index_html(tmp_path, '{{index by="status" type="bnd"}}')
    assert "BND-001" in html and "REQ-001" not in html


def _site_page(tmp_path, name: str) -> str:
    project = _build_at(tmp_path)
    render.render_site(project)
    with open(os.path.join(str(tmp_path), "_site", name), encoding="utf-8") as fh:
        return fh.read()


def test_group_inherited_defaults_to_true_for_every_project(tmp_path):
    assert _consumer_project(tmp_path).group_inherited is True
    assert _load(tmp_path, PARENT + CHILD).group_inherited is True


def test_group_inherited_can_be_turned_off(tmp_path):
    project = _consumer_project(tmp_path, settings="coverage: { group_inherited: false }\n")
    assert project.group_inherited is False


@pytest.mark.parametrize(
    "block, message",
    [
        ("coverage: { group_inherited: maybe }\n", "coverage.group_inherited must be true or false"),
        ("coverage: { group: true }\n", "coverage.group is not valid"),
    ],
)
def test_coverage_setting_is_validated(tmp_path, block, message):
    write_project_config(tmp_path, "site: { title: T, out: _site }\n" + block + PARENT)
    with pytest.raises(SchemaError) as exc:
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    assert message in str(exc.value)


def test_coverage_page_badges_a_grouped_subtype_row(tmp_path):
    _consumer_project(tmp_path)
    html = _site_page(tmp_path, "coverage.html")
    assert 'A bound <span class="muted small">(bnd)</span>' in html
    assert "A requirement <span" not in html


def test_coverage_page_has_no_badge_when_grouping_is_off(tmp_path):
    _consumer_project(tmp_path, settings="coverage: { group_inherited: false }\n")
    assert "(bnd)" not in _site_page(tmp_path, "coverage.html")


def test_summary_folds_subtype_counts_into_the_parent_row_only_when_grouped(tmp_path):
    _consumer_project(tmp_path)
    grouped = render.summary_payload(_build_at(tmp_path))["type_rows"]
    by_name = {r["name"]: r for r in grouped}
    assert "bnd" not in by_name and by_name["req"]["count"] == 2

    _consumer_project(tmp_path, settings="coverage: { group_inherited: false }\n")
    separate = {r["name"]: r for r in render.summary_payload(_build_at(tmp_path))["type_rows"]}
    assert separate["req"]["count"] == 1 and separate["bnd"]["count"] == 1


def test_json_schema_completion_offers_subtypes_where_the_parent_is_named(tmp_path):
    project = _consumer_project(tmp_path)
    branch = build_schema(project)["$defs"]["dec__bare"]
    assert branch["properties"]["satisfies"]["description"] == "target: req, bnd"


# =========================================================================
# Phase 3 + 4: hardware@3 adopts `bound extends requirement`; oracle and the
# standard-level positive/negative cases.
# =========================================================================

import json  # noqa: E402
from pathlib import Path  # noqa: E402

from oracle_dump import resolved_dump  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

HARDWARE3 = "standard: { base: hardware, version: 3 }\n"


def _normalized(dump: str) -> dict:
    return json.loads(dump)


@pytest.mark.parametrize(
    "fixture, presets",
    [
        ("hardware3_resolved.json", []),
        ("hardware3_design_debate_resolved.json", ["design-debate"]),
    ],
)
def test_hardware3_base_resolves_unchanged(fixture, presets):
    """The acceptance test of extends.md §5.2: converting `bound` to
    `extends: requirement` leaves the resolved schema literally identical, so
    nothing that hashes, seals or baselines an item can tell. The fixtures are
    the pre-conversion dumps (types and link_types, every field, link and
    scalar). `bound` suppresses the one inherited link it never had
    (`governed_by: null`, §2.2). Field order is compared too; link-verb order
    is not (inherited verbs come first), and nothing reads it."""
    expected = _normalized((FIXTURES / fixture).read_text(encoding="utf-8"))
    actual = _normalized(resolved_dump(presets))

    assert list(actual["types"]) == list(expected["types"])
    for name, spec in expected["types"].items():
        assert actual["types"][name] == spec, f"types.{name} drifted"
        assert list(actual["types"][name]["fields"]) == list(spec["fields"])
    assert actual["link_types"] == expected["link_types"]
    assert "governed_by" not in actual["types"]["bound"]["links"]


def test_hardware3_bound_extends_requirement(tmp_path):
    project = _load(tmp_path, HARDWARE3)
    assert project.types["bound"].extends == "requirement"
    assert project.subtype_map == {"requirement": {"bound"}}
    assert project.types["requirement"].extends == ""
    # Identity is the bound's own, never the requirement's.
    bound = project.types["bound"]
    assert (bound.prefix, bound.label, bound.plural) == ("BND", "Bound", "Bounds")
    assert bound.coverable is True and bound.coverable_statuses == ["active"]


def test_hardware3_bound_satisfies_every_list_that_names_requirement(tmp_path):
    """The standard's own consumers: a decision `satisfies:` and a test
    `verifies:` a bound, and coverage closes on it -- through `extends:`, with
    `bound` also still named explicitly in those lists."""
    write_project_config(tmp_path, "site: { title: T, out: _site }\n" + HARDWARE3)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "all.yaml").write_text(
        "items:\n"
        "  - { id: BND-001, type: bound, status: active, limit: '<= 5 V',\n"
        "      body: The rail stays under five volts. }\n"
        "  - { id: DEC-001, type: decision, status: accepted, title: Regulator,\n"
        "      satisfies: [BND-001] }\n"
        "  - { id: TST-001, type: test, status: passing, title: Rail check, verifies: [BND-001] }\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert not project.errors, [d.message for d in project.errors]
    assert project.coverage["BND-001"].stage == "verified"


def test_overlay_may_extend_a_base_type(tmp_path):
    project = _load(
        tmp_path,
        HARDWARE3
        + "types:\n"
        "  thermal_bound:\n"
        "    extends: requirement\n"
        "    prefix: THB\n"
        "    label: Thermal bound\n"
        "    plural: Thermal bounds\n"
        "    fields:\n"
        "      limit: { type: limit, required: true }\n",
    )
    thb = project.types["thermal_bound"]
    assert thb.extends == "requirement"
    assert {"title", "status", "limit", "source", "owner"} <= set(thb.fields)
    assert project.subtype_map == {"requirement": {"bound", "thermal_bound"}}


def test_overlay_extending_an_already_extended_type_is_an_error(tmp_path):
    """The parent's spec still has `extends:` after the standard's own
    resolution -- the single-level rule catches an overlay hop the same way."""
    message = _err(
        tmp_path,
        HARDWARE3
        + "types:\n"
        "  thermal_bound:\n"
        "    extends: bound\n"
        "    prefix: THB\n"
        "    label: Thermal bound\n"
        "    plural: Thermal bounds\n",
    )
    assert message == (
        "types.thermal_bound.extends names 'bound', which itself extends "
        "'requirement'. Single-level inheritance only; thermal_bound must "
        "extend 'requirement' directly or not use extends:."
    )


def test_overlay_edit_to_requirement_reaches_bound(tmp_path):
    """extends.md §2.3's key consequence, on the real standard: a field the
    project adds to `requirement` is inherited by `bound`."""
    project = _load(
        tmp_path,
        HARDWARE3
        + "types:\n"
        "  requirement:\n"
        "    fields:\n"
        "      verification_plan: { type: text }\n",
    )
    assert "verification_plan" in project.types["bound"].fields


def test_overlay_can_retype_bound_to_extend_nothing_by_removing_it(tmp_path):
    """`types.bound: null` still removes the type; dangling references to it
    surface as the usual link-target load error, not an extends one."""
    message = _err(tmp_path, HARDWARE3 + "types:\n  bound: null\n")
    assert "bound" in message and "extends" not in message


def test_overlay_suppresses_a_link_that_arrives_via_extends(tmp_path):
    """The overlay's null is interpreted after inheritance: `part_of` comes
    from `requirement`, and the null un-declares it on `bound` only."""
    project = _load(
        tmp_path, HARDWARE3 + "types:\n  bound:\n    links:\n      part_of: null\n"
    )
    assert "part_of" not in project.types["bound"].links
    assert "part_of" in project.types["requirement"].links


def test_overlay_null_for_a_verb_the_parent_never_declared_is_still_an_error(tmp_path):
    message = _err(
        tmp_path, HARDWARE3 + "types:\n  bound:\n    links:\n      nonesuch: null\n"
    )
    assert "types.bound.links.nonesuch is null" in message
    assert "'requirement' declares no link 'nonesuch'" in message


def test_overlay_type_with_its_own_extends_and_nulls(tmp_path):
    """A brand-new overlay type that extends and nulls an inherited link."""
    project = _load(
        tmp_path,
        HARDWARE3
        + "types:\n"
        "  soft_bound:\n"
        "    extends: requirement\n"
        "    prefix: SFB\n"
        "    label: Soft bound\n"
        "    plural: Soft bounds\n"
        "    links:\n"
        "      part_of: null\n"
        "      governed_by: null\n",
    )
    links = project.types["soft_bound"].links
    assert "part_of" not in links and "governed_by" not in links
    assert "part_of" in project.types["requirement"].links


def test_overlay_edits_parent_and_nulls_in_the_child_together(tmp_path):
    """The parent gains a field and a link target list in the overlay; the
    child inherits the field, but not the link the overlay nulls on it."""
    project = _load(
        tmp_path,
        HARDWARE3
        + "types:\n"
        "  requirement:\n"
        "    fields:\n"
        "      verification_plan: { type: text }\n"
        "    links:\n"
        "      part_of: [group]\n"
        "  bound:\n"
        "    links:\n"
        "      part_of: null\n",
    )
    assert "verification_plan" in project.types["bound"].fields
    assert "part_of" not in project.types["bound"].links
    assert "part_of" in project.types["requirement"].links


def test_overlay_null_on_an_ordinary_type_still_removes_its_own_link(tmp_path):
    project = _load(
        tmp_path, HARDWARE3 + "types:\n  requirement:\n    links:\n      part_of: null\n"
    )
    assert "part_of" not in project.types["requirement"].links
    # ...and the child, which inherits from the edited parent, follows it.
    assert "part_of" not in project.types["bound"].links


def test_overlay_renulling_an_already_suppressed_link_stays_suppressed(tmp_path):
    project = _load(
        tmp_path, HARDWARE3 + "types:\n  bound:\n    links:\n      governed_by: null\n"
    )
    assert "governed_by" not in project.types["bound"].links

