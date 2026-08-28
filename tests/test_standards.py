"""standard library.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
import yaml
from helpers import _build_at

from refdes import build as build_mod
from refdes import standards
from refdes.schema import SchemaError, load_project

# ------------------------------------------------------------ standard library


def test_standard_none_is_identical_to_omitting_standard(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    schema = (
        "site: { title: T, out: _site }\n"
        "standard: none\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
    )
    (a / "refdes.yaml").write_text(schema, encoding="utf-8")
    (b / "refdes.yaml").write_text(schema.replace("standard: none\n", ""), encoding="utf-8")
    pa = load_project(config_path=str(a / "refdes.yaml"))
    pb = load_project(config_path=str(b / "refdes.yaml"))
    assert set(pa.types) == set(pb.types) == {"requirement"}
    assert pa.link_types == pb.link_types


def test_standard_hardware_v1_resolves_the_six_types(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert set(project.types) == {
        "requirement", "constraint", "decision", "test", "component", "log",
    }
    assert project.types["requirement"].coverable is True
    assert project.types["requirement"].coverable_statuses == ["active"]
    assert project.types["test"].verifying_statuses == ["passing"]
    assert project.types["decision"].fields["rationale"].required_when == {"status": "rejected"}
    assert "refines" in project.link_types


def test_standard_hardware_v2_carries_the_whole_v1_delta(tmp_path):
    """v2 is the one version bump between 0.4.0 and 0.5.0, and it carries all
    three of that period's vocabulary changes at once: `title` -> `text`,
    `constraint` -> `bound` (prefix CON -> BND, gaining `refines:`), and
    `equivalent`/`alternate` restricted to components. They were developed as
    three internal steps and never published separately, so they ship as one
    version rather than three."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert "constraint" not in project.types

    bound = project.types["bound"]
    assert bound.prefix == "BND"
    assert "text" in bound.fields and bound.fields["text"].required is True
    assert "title" not in bound.fields
    assert bound.preview == ["status", "text", "limit"]
    assert bound.links["refines"] == ["bound"]
    assert bound.links["derives_from"] == ["requirement", "bound"]

    component = project.types["component"]
    assert component.links["equivalent"] == ["component"]
    assert component.links["alternate"] == ["component"]

    # Every verb that pointed at `constraint` now points at `bound`.
    assert project.types["decision"].links["constrained_by"] == ["bound"]
    assert project.types["test"].links["verifies"] == ["requirement", "bound"]
    assert project.types["log"].links["addresses"] == ["requirement", "bound"]

    # requirement is untouched throughout -- the `capability` rename that was
    # considered alongside the `bound` one was explicitly rejected.
    assert project.types["requirement"].prefix == "REQ"
    assert project.types["requirement"].links == {"refines": ["requirement"]}


def test_standard_hardware_v1_still_has_constraint_title(tmp_path):
    """v1 must stay byte-identical forever -- adding v2 must not touch it."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    constraint = project.types["constraint"]
    assert "title" in constraint.fields
    assert "text" not in constraint.fields
    assert constraint.preview == ["status", "limit", "rationale"]


def test_standard_version_must_be_a_pinned_integer(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: latest, presets: [] }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="pinned integer"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_standard_unknown_base_is_rejected(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: nope, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="standard.base must be one of"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_pinning_a_version_that_does_not_exist_is_a_clear_error(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 99, presets: [] }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="standard.version 99 does not exist"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_design_debate_preset_adds_its_types(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [design-debate] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert {"debate", "option", "claim", "position"} <= set(project.types)
    assert project.types["option"].check_severity == "info"


def _write_fake_standard(root, preset_files):
    """A minimal fake `<root>/fake/v1/base.yaml` (+ presets/*.yaml), isolated
    from the real bundled hardware standard, for collision tests that need
    full control over both sides of the collision."""
    version_dir = os.path.join(str(root), "fake", "v1")
    presets_dir = os.path.join(version_dir, "presets")
    os.makedirs(presets_dir, exist_ok=True)
    with open(os.path.join(version_dir, "base.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump(
            {"types": {"widget": {"prefix": "WID", "fields": {}}}}, fh
        )
    for name, doc in preset_files.items():
        with open(os.path.join(presets_dir, f"{name}.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh)


def test_preset_colliding_with_the_base_is_a_hard_error(tmp_path, monkeypatch):
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path))
    monkeypatch.setattr(standards, "_KNOWN_BASES", ("fake",))
    _write_fake_standard(
        tmp_path,
        preset_files={"clashing": {"types": {"widget": {"prefix": "W2", "fields": {}}}}},
    )
    with pytest.raises(
        SchemaError,
        match="declares type 'widget', which the fake standard also declares",
    ):
        standards.resolve_schema(
            {"standard": {"base": "fake", "version": 1, "presets": ["clashing"]}}, True
        )


def test_two_presets_colliding_with_each_other_is_a_hard_error(tmp_path, monkeypatch):
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path))
    monkeypatch.setattr(standards, "_KNOWN_BASES", ("fake",))
    _write_fake_standard(
        tmp_path,
        preset_files={
            "one": {"types": {"gadget": {"prefix": "GAD", "fields": {}}}},
            "two": {"types": {"gadget": {"prefix": "GA2", "fields": {}}}},
        },
    )
    with pytest.raises(
        SchemaError,
        match="preset 'two' declares type 'gadget', which preset 'one' also declares",
    ):
        standards.resolve_schema(
            {"standard": {"base": "fake", "version": 1, "presets": ["one", "two"]}}, True
        )


def test_overlay_adds_field_removes_field_and_redeclares_enum(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n"
        "types:\n"
        "  requirement:\n"
        "    fields:\n"
        "      erratum_ref: { type: text, on_change: log }\n"
        "      rationale: null\n"
        "      status: { type: enum, choices: [draft, active, retired, deprecated],\n"
        "                default: draft, on_change: invalidate }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    req = project.types["requirement"]
    assert "erratum_ref" in req.fields
    assert "rationale" not in req.fields
    assert req.fields["status"].choices == ["draft", "active", "retired", "deprecated"]
    assert "text" in req.fields  # untouched inherited field survives the merge


def test_overlay_adds_a_brand_new_type_alongside_the_standard(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n"
        "types:\n"
        "  widget:\n"
        "    prefix: WID\n"
        "    fields:\n"
        "      name: { type: text, required: true }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert "widget" in project.types
    assert "requirement" in project.types  # the standard's own types are untouched


def test_removing_a_type_something_still_targets_is_a_load_error(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n"
        "types:\n"
        "  component: null\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="selects.*'component'"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


FALLBACK_COVERAGE_SCHEMA = """\
site: { title: T, out: _site }
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
  verifies:  { inverse: verified_by,  label: Verifies }
types:
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true }
  constraint:
    prefix: CON
    fields:
      title: { type: text, required: true }
      limit: { type: limit, required: true }
  decision:
    prefix: DEC
    satisfying_statuses: [accepted]
    fields:
      title:  { type: text, required: true }
      status: { type: enum, choices: [proposed, accepted], default: proposed }
    links:
      satisfies: [requirement, constraint]
"""


FALLBACK_COVERAGE_ITEMS = (
    "items:\n"
    "  - id: REQ-001\n    type: requirement\n    text: A requirement.\n"
    "  - id: CON-001\n    type: constraint\n    title: A constraint.\n"
    '    limit: "<= 1 W"\n'
    "  - id: DEC-001\n    type: decision\n    title: Claims REQ-001.\n"
    "    status: proposed\n    satisfies: [REQ-001]\n"
    "  - id: DEC-002\n    type: decision\n    title: Claims CON-001.\n"
    "    status: proposed\n    satisfies: [CON-001]\n"
)


def test_coverable_fallback_warns_once_per_type_and_keeps_requirement_only_asymmetry(tmp_path):
    """No type here declares `coverable:`, so both requirement and constraint
    fall back to the old name-based convention -- but only requirement keeps
    getting the per-item warnings, exactly like before `coverable:` existed."""
    (tmp_path / "refdes.yaml").write_text(FALLBACK_COVERAGE_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(FALLBACK_COVERAGE_ITEMS, encoding="utf-8")
    project = _build_at(tmp_path)

    fallback_warnings = [
        d for d in project.warnings if "falling back to name-based detection" in d.message
    ]
    assert len(fallback_warnings) == 2  # once for requirement, once for constraint

    assert any(
        d.item_id == "REQ-001" and "claimed but not verified" in d.message
        for d in project.warnings
    )
    assert not any(
        d.item_id == "CON-001" and "claimed but not verified" in d.message
        for d in project.warnings
    )


def test_explicit_coverable_extends_warnings_beyond_the_fallback_names(tmp_path):
    """Once constraint opts in with `coverable: true` explicitly, it gets the
    same per-item warnings as requirement -- no more name restriction."""
    schema = FALLBACK_COVERAGE_SCHEMA.replace(
        "  constraint:\n    prefix: CON\n",
        "  constraint:\n    prefix: CON\n    coverable: true\n",
    )
    (tmp_path / "refdes.yaml").write_text(schema, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(FALLBACK_COVERAGE_ITEMS, encoding="utf-8")
    project = _build_at(tmp_path)

    assert any(
        d.item_id == "CON-001" and "claimed but not verified" in d.message
        for d in project.warnings
    )
    fallback_warnings = [
        d for d in project.warnings if "falling back to name-based detection" in d.message
    ]
    assert len(fallback_warnings) == 1  # only requirement goes through the fallback now


def test_coverable_statuses_excludes_unlisted_statuses_entirely(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    coverable: true\n"
        "    coverable_statuses: [active]\n"
        "    fields:\n"
        "      text:   { type: text, required: true }\n"
        "      status: { type: enum, choices: [draft, active, retired], default: draft }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: REQ-001\n    type: requirement\n    text: Draft.\n    status: draft\n"
        "  - id: REQ-002\n    type: requirement\n    text: Active.\n    status: active\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert "REQ-001" not in project.coverage
    assert "REQ-002" in project.coverage


def test_explicit_null_enum_field_gets_default_applied_and_reported(tmp_path):
    """A bare `status:` (present, value null) must not bypass the schema default and
    the enum check the way it silently did before -- it should behave exactly like
    an absent key: get the default, and say so, rather than being treated as an
    already-resolved value with nothing to check."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    coverable: true\n"
        "    coverable_statuses: [active]\n"
        "    fields:\n"
        "      text:   { type: text, required: true }\n"
        "      status: { type: enum, choices: [draft, active, retired], default: draft }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: REQ-001\n    type: requirement\n    text: A requirement.\n    status:\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)

    assert not project.errors
    assert project.items["REQ-001"].fields["status"] == "draft"
    assert any(
        d.item_id == "REQ-001" and "status" in d.message and "null" in d.message.lower()
        for d in project.warnings
    )


def test_verifying_statuses_filters_which_links_count_as_verified(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "link_types:\n"
        "  verifies: { inverse: verified_by, label: Verifies }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    coverable: true\n"
        "    fields:\n"
        "      text: { type: text, required: true }\n"
        "  test:\n"
        "    prefix: TST\n"
        "    verifying_statuses: [passing]\n"
        "    fields:\n"
        "      title:  { type: text, required: true }\n"
        "      status: { type: enum, choices: [planned, passing], default: planned }\n"
        "    links:\n"
        "      verifies: [requirement]\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: REQ-001\n    type: requirement\n    text: A requirement.\n"
        "  - id: TST-001\n    type: test\n    title: A test.\n    status: planned\n"
        "    verifies: [REQ-001]\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.coverage["REQ-001"].verified_by == []
    assert project.coverage["REQ-001"].stage == "open"

    project.items["TST-001"].fields["status"] = "passing"
    build_mod.compute_coverage(project)
    assert project.coverage["REQ-001"].verified_by == ["TST-001"]
    assert project.coverage["REQ-001"].stage == "verified"


def test_field_sets_include_expands_with_own_fields_winning(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "field_sets:\n"
        "  provenance:\n"
        "    source: { type: text, on_change: log }\n"
        "    tags:   { type: list, on_change: ignore }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    include: [provenance]\n"
        "    fields:\n"
        "      text:   { type: text, required: true }\n"
        "      source: { type: text, on_change: invalidate }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    req = project.types["requirement"]
    assert "tags" in req.fields
    assert req.fields["source"].on_change == "invalidate"  # own field beats the include


def test_include_unknown_field_set_errors_at_load(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    include: [nope]\n"
        "    fields:\n"
        "      text: { type: text, required: true }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="unknown field_set 'nope'"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


REQUIRED_WHEN_SCHEMA = """\
site: { title: T, out: _site }
types:
  decision:
    prefix: DEC
    fields:
      title:     { type: text, required: true }
      status:    { type: enum, choices: [proposed, accepted, rejected], default: proposed }
      rationale: { type: text, required_when: { status: rejected } }
"""


def test_required_when_enforces_only_when_the_condition_matches(tmp_path):
    (tmp_path / "refdes.yaml").write_text(REQUIRED_WHEN_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: DEC-001\n    type: decision\n    title: Fine without rationale.\n"
        "    status: proposed\n"
        "  - id: DEC-002\n    type: decision\n    title: Needs a reason.\n"
        "    status: rejected\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert not any(d.item_id == "DEC-001" for d in project.errors)
    assert any(
        d.item_id == "DEC-002"
        and "'rationale' is required when status is 'rejected'" in d.message
        for d in project.errors
    )


def test_required_when_links_condition(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "link_types:\n"
        "  alternate: { inverse: alternate, label: Alternate }\n"
        "types:\n"
        "  component:\n"
        "    prefix: CMP\n"
        "    fields:\n"
        "      title:     { type: text, required: true }\n"
        "      rationale: { type: text, required_when: { links: alternate } }\n"
        "    links:\n"
        "      alternate: []\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: CMP-001\n    type: component\n    title: Plain.\n"
        "  - id: CMP-002\n    type: component\n    title: Has an alternate.\n"
        "    alternate: [CMP-001]\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert not any(d.item_id == "CMP-001" for d in project.errors)
    assert any(d.item_id == "CMP-002" and "rationale" in d.message for d in project.errors)


def test_required_when_dangling_enum_value_errors_at_load(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n"
        "types:\n"
        "  decision:\n"
        "    fields:\n"
        "      status: { type: enum, choices: [proposed, accepted], default: proposed }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="not among status's declared choices"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_required_when_and_required_together_is_a_load_error(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  widget:\n"
        "    prefix: WID\n"
        "    fields:\n"
        "      x: { type: text, required: true, required_when: { y: z } }\n"
        "      y: { type: enum, choices: [z], default: z }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="both 'required: true' and 'required_when:'"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_required_when_unknown_link_errors_at_load(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  widget:\n"
        "    prefix: WID\n"
        "    fields:\n"
        "      rationale: { type: text, required_when: { links: nope } }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="not a declared link"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_require_rejection_rationale_false_drops_the_condition(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "refdes-project.yaml").write_text(
        "require_rejection_rationale: false\n", encoding="utf-8"
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert project.types["decision"].fields["rationale"].required_when is None
