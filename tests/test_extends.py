"""`extends:` -- single-level type inheritance (docs/design/extends.md).

Phase 1 (engine): resolution order, what is and is not inherited, the Liskov
guards, and the single-level rule. Later phases append consumers, the
coverage-grouping setting and the hardware@3 oracle below.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import standards
from refdes.schema import SchemaError, load_project

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
