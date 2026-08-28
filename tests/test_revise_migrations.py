"""hardware@2: the whole v1 -> v2 delta -- and: hardware@3 (finding 7, field unification).

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import yaml
from helpers import PARTS_SCHEMA

from refdes import build as build_mod
from refdes import parse, revise, standards
from refdes.schema import load_project

# ------------------------------------- hardware@2: the whole v1 -> v2 delta

def test_an_item_still_typed_constraint_at_v2_names_the_rename(tmp_path):
    """The type-level counterpart of the `constraint.title` -> `constraint.text`
    diagnostic (finding 4). Without it, moving the pin to v3 by hand reports a
    bare "unknown type 'constraint'." on every item in the project, and
    difflib's did-you-mean offers nothing: `constraint` and `bound` are not
    close enough to suggest."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: CON-001\n    type: constraint\n    text: Board power density\n"
        "    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    messages = [d.message for d in project.errors]
    assert any(
        "it is now 'bound'" in m and "hardware@2" in m and "standard upgrade" in m
        for m in messages
    ), messages


def test_the_rename_hint_stays_quiet_where_the_new_type_does_not_exist(tmp_path):
    """A hand-rolled schema that has never heard of either name must get the
    ordinary unknown-type error, not advice to rename into a type it has no
    declaration for."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  widget: { prefix: WID, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n  - id: CON-001\n    type: constraint\n    text: Nope.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    messages = [d.message for d in project.errors]
    assert any("unknown type 'constraint'" in m for m in messages), messages
    assert not any("it is now 'bound'" in m for m in messages), messages


def _equivalence_project(tmp_path, version, target_id="REQ-001"):
    """A component declaring `equivalent:` at a target that is not a
    component, against a given pinned standard version."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: %d, presets: [] }\n"
        "id: { width: 3, ledger: .refdes/ids.yaml }\n" % version,
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: REQ-001\n    type: requirement\n    text: A requirement.\n"
        "    status: active\n"
        "  - id: CMP-001\n    type: component\n    title: A capacitor.\n"
        "    equivalent: [%s]\n" % target_id,
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def test_hardware_v2_restricts_equivalent_and_alternate_to_components(tmp_path):
    """`[]` in a `links:` target list means *unrestricted* -- that is what it
    deliberately means one type up on `decision.blocked_by:` -- so writing it
    on `equivalent`/`alternate` left v1's dictionary accepting `equivalent:
    [REQ-001]` on a component with no diagnostic at all, while the spec
    (docs/design/standard-library.md 11) and every version of the docs said
    component -> component. v2 restores the intent."""
    project = _equivalence_project(tmp_path, version=2)
    assert any(
        "equivalent may point at ['component']" in d.message and "REQ-001" in d.message
        for d in project.errors
    ), [str(d) for d in project.errors]


def test_hardware_v2_still_allows_a_component_to_component_equivalence(tmp_path):
    """The restriction must not catch the case it exists to describe."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: CMP-001\n    type: component\n    title: First source.\n"
        "    equivalent: [CMP-002]\n"
        "  - id: CMP-002\n    type: component\n    title: Second source.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors, [str(d) for d in project.errors]


def test_v1_keeps_the_unrestricted_behaviour(tmp_path):
    """Byte-identical forever: a project pinned at v1 sees no change at all,
    including the permissiveness v2 removes. Upgrading is what opts a project
    into the check."""
    project = _equivalence_project(tmp_path, version=1)
    assert not any("equivalent may point at" in d.message for d in project.errors), [
        str(d) for d in project.errors
    ]


def test_v3_is_the_version_init_pins(tmp_path):
    assert standards.latest_version("hardware") == 3


def test_the_parts_fixture_matches_the_bundled_standard():
    """The suite never caught the unrestricted `equivalent` because the parts
    fixture hand-declared the *restricted* form -- the schema the standard was
    supposed to have, not the one it shipped. A fixture that can quietly
    diverge from the dictionary it stands in for is a trap for whoever reads
    it next, so this pins the two together."""
    _link_types, types = standards.resolve_schema(
        {"standard": {"base": "hardware", "version": standards.latest_version("hardware")}},
        require_rejection_rationale=True,
    )
    shipped = types["component"]["links"]
    fixture = yaml.safe_load(PARTS_SCHEMA)["types"]["component"]["links"]
    for verb in ("equivalent", "alternate"):
        assert fixture[verb] == shipped[verb], (
            f"parts fixture declares {verb}: {fixture[verb]}, "
            f"but the bundled standard ships {shipped[verb]}"
        )


def test_hardware_v1_still_resolves_constraint_unchanged(tmp_path):
    """v2 is a new pinned version, not an edit to an old one -- a project
    still pinned at v1 sees no difference at all."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert "bound" not in project.types
    assert project.types["constraint"].prefix == "CON"
    assert "title" in project.types["constraint"].fields
    assert project.types["component"].links["equivalent"] == []


def test_standard_upgrade_v1_to_v2_applies_the_whole_collapsed_delta(tmp_path):
    """End-to-end against the real bundled standard, as one v1 -> v2 run.

    The three changes v2 carries were developed as three internal steps, so
    the migration that replaces them must be tested as the single step it now
    is rather than assumed to be the concatenation of three that each passed.
    This exercises all of it at once: `title` -> `text` on a type that is
    *itself* being renamed in the same step (the field pass is keyed by the
    old type name and runs against the pre-rewrite project, which is what
    keeps the type rename from hiding it), the compound-prefix convention
    this repository uses, structured references through both a link and a
    `checks:` entry, and an equivalence that must survive untouched while the
    restriction on it starts being enforced."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n  status: active\n"
        "items:\n"
        "  - id: CON-THM-001\n    title: Board power density\n    limit: \"<= 1 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "cmp.yaml").write_text(
        "defaults:\n  type: component\n  prefix: CMP\n"
        "items:\n"
        "  - id: CMP-001\n    title: First source.\n    equivalent: [CMP-002]\n"
        "  - id: CMP-002\n    title: Second source.\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "status: accepted\n"
        "constrained_by: [CON-THM-001]\n"
        "checks:\n"
        "  - value: P_dens\n"
        "    against: CON-THM-001\n"
        "---\n\n"
        "```calc\nP_dens : W/in^2 = 0.1 W/in^2\n```\n",
        encoding="utf-8",
    )

    steps = revise.apply_standard_upgrade(str(tmp_path), 2)
    assert len(steps) == 1
    assert steps[0].result.ok, steps[0].result.errors
    assert steps[0].result.id_changes == {"CON-THM-001": "BND-THM-001"}

    con_text = (items / "con.yaml").read_text(encoding="utf-8")
    assert "type: bound" in con_text
    assert "prefix: BND-THM" in con_text
    assert "id: BND-THM-001" in con_text
    # The field rename landed too, on the same item, in the same step.
    assert "text: Board power density" in con_text
    assert "title:" not in con_text

    dec_text = (items / "dec.md").read_text(encoding="utf-8")
    assert "constrained_by: [BND-THM-001]" in dec_text
    assert "against: BND-THM-001" in dec_text

    # Nothing renames an equivalence; the restriction only starts being checked.
    assert "equivalent: [CMP-002]" in (items / "cmp.yaml").read_text(encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert project.standard_version == 2
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors, [str(d) for d in project.errors]


def test_upgrade_refuses_when_an_equivalence_no_longer_satisfies_v2(tmp_path):
    """v2's third change renames nothing, so its migration.yaml says nothing
    about it -- but the step still re-validates, and a component pointing
    `equivalent` at a non-component is refused and rolled back rather than
    pinned to a version its own items don't satisfy."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: REQ-001\n    type: requirement\n    text: A requirement.\n"
        "    status: active\n"
        "  - id: CMP-001\n    type: component\n    title: A capacitor.\n"
        "    equivalent: [REQ-001]\n",
        encoding="utf-8",
    )
    steps = revise.apply_standard_upgrade(str(tmp_path), 2)
    assert len(steps) == 1
    assert not steps[0].result.ok
    assert any("equivalent may point at" in e for e in steps[0].result.errors), (
        steps[0].result.errors
    )
    # Rolled back: the pin did not move.
    assert "version: 1" in (tmp_path / "refdes.yaml").read_text(encoding="utf-8")


# ------------------------------------------------------ hardware@3 (finding 7, field unification)


def test_standard_upgrade_v2_to_v3_renames_text_and_method_to_body(tmp_path):
    """End-to-end against the real bundled standard: requirement.text and
    bound.text both become body:, test.method becomes body: too, and the
    upgraded project validates clean against v3's own body_required rule."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "req.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ, status: active }\n"
        "items:\n  - id: REQ-001\n    text: The unit shall operate from 9 V to 36 V.\n",
        encoding="utf-8",
    )
    (items / "bnd.yaml").write_text(
        "defaults: { type: bound, prefix: BND, status: active }\n"
        "items:\n  - id: BND-001\n    text: Board power density\n    limit: \"<= 1 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "tst.yaml").write_text(
        "defaults: { type: test, prefix: TST }\n"
        "items:\n  - id: TST-001\n    title: Input sweep\n    "
        "method: Sweep 9 V to 36 V.\n    verifies: [REQ-001]\n",
        encoding="utf-8",
    )

    steps = revise.apply_standard_upgrade(str(tmp_path), 3)
    assert len(steps) == 1
    assert steps[0].result.ok, steps[0].result.errors

    req_text = (items / "req.yaml").read_text(encoding="utf-8")
    assert "body: The unit shall operate from 9 V to 36 V." in req_text
    assert "text:" not in req_text

    tst_text = (items / "tst.yaml").read_text(encoding="utf-8")
    assert "body: Sweep 9 V to 36 V." in tst_text
    assert "method:" not in tst_text

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert project.standard_version == 3
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors, [str(d) for d in project.errors]
    assert project.items["REQ-001"].body == "The unit shall operate from 9 V to 36 V."
    assert project.items["REQ-001"].title == "The unit shall operate from 9 V to 36 V."


def test_upgrade_refuses_when_an_item_already_has_its_own_body(tmp_path):
    """A requirement that already carries prose body content (in addition to
    text:) must not have that content silently orphaned or overwritten by
    the text: -> body: rename -- refused and rolled back instead."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "req.md").write_text(
        "---\nid: REQ-001\ntype: requirement\nstatus: active\n"
        "text: The unit shall operate from 9 V to 36 V.\n---\n\n"
        "Extra context that already lives in this item's own body.\n",
        encoding="utf-8",
    )
    steps = revise.apply_standard_upgrade(str(tmp_path), 3)
    assert len(steps) == 1
    assert not steps[0].result.ok
    assert any("already has its own body content" in e for e in steps[0].result.errors), (
        steps[0].result.errors
    )
    assert "version: 2" in (tmp_path / "refdes.yaml").read_text(encoding="utf-8")


def test_v3_requirement_body_is_required_but_only_a_warning(tmp_path):
    """A requirement with no statement isn't one -- but this is enforced as
    a warning, not a build-blocking error, so a stub can exist mid-draft."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 3, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "req.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ, status: active }\n"
        "items:\n  - id: REQ-001\n    title: Just a caption, no body.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert project.errors == []
    assert any(
        "body: is empty" in d.message for d in project.warnings
    ), [str(d) for d in project.warnings]


def test_v3_requirement_title_is_optional_and_falls_back_to_body(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 3, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "req.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ, status: active }\n"
        "items:\n  - id: REQ-001\n    body: The unit shall operate from 9 V to 36 V.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert not project.errors, [str(d) for d in project.errors]
    assert project.items["REQ-001"].title == "The unit shall operate from 9 V to 36 V."


def test_v3_governed_by_link_resolves_its_backlink(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 3, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "req.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ, status: active }\n"
        "items:\n"
        "  - id: REQ-001\n    body: General rule about isolation.\n"
        "  - id: REQ-002\n    body: A specific input must comply with REQ-001.\n"
        "    governed_by: [REQ-001]\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert not project.errors, [str(d) for d in project.errors]
    assert project.items["REQ-002"].links["governed_by"] == ["REQ-001"]
    assert project.items["REQ-001"].backlinks["governs"] == ["REQ-002"]
