"""Tests for the invariants that must never quietly break.

The rest of the tool can be rewritten freely. These four cannot: IDs must never
shift, the calc DSL must never execute code, the content hash must follow the
on_change policy exactly, and checks must be evaluated at the worst-case tolerance
bound rather than the nominal.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from refdes import build as build_mod  # noqa: E402
from refdes import calc, ids, parse, render, seal  # noqa: E402
from refdes.schema import SchemaError, load_project  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")


# ------------------------------------------------------------------------- calc


def test_units_propagate_and_name_derived_results():
    env = {}
    outcomes = calc.evaluate_block("P = 3.3 V * 1.2 A", env)
    assert outcomes[0].error is None
    assert calc.format_value(env["P"]) == "3.96 W"


def test_author_units_are_not_second_guessed():
    """W/in^2 must stay in inches; we only name sub-products like V*A -> W."""
    env = {}
    calc.evaluate_block("A = 1.4 inch * 0.9 inch\nP = 3.3 V * 1.2 A\nD = P / A", env)
    assert "in²" in calc.format_value(env["D"])
    assert calc.format_value(env["A"]) == "1.26 in²"


def test_bracketed_units_are_explicit():
    env = {}
    calc.evaluate_block("h = 3 A\nt = 0.5 [h]", env)
    assert calc.format_value(env["t"]) == "0.5 h"


def test_bracketed_units_accept_products():
    env = {}
    calc.evaluate_block("tq = 2 [N*m]", env)
    assert env["tq"].nom.dimensionality == calc.Q(1, "N*m").dimensionality


def test_unit_variable_collision_warns_but_still_evaluates():
    """`A` for area is normal engineering notation; it must not fail the build."""
    outcomes = calc.evaluate_block("P = 3.3 V * 1.2 A\nA = 1.4 inch * 0.9 inch", {})
    assert outcomes[0].error is None
    assert outcomes[0].warning is not None
    assert "[A]" in outcomes[0].warning


def test_bracket_silences_the_collision_warning():
    outcomes = calc.evaluate_block("P = 3.3 V * 1.2 [A]\nA = 1.4 inch * 0.9 inch", {})
    assert outcomes[0].warning is None


def test_compound_unit_segments_are_never_ambiguous():
    outcomes = calc.evaluate_block("h = 3 A\nrate = 5 W/h", {})
    assert outcomes[1].warning is None


@pytest.mark.parametrize(
    "source,expected",
    [("x = 1.4 inch", "1.4 in"), ("x = 0.5 h", "0.5 h"), ("x = 12 V", "12 V")],
)
def test_simple_author_units_are_never_rewritten(source, expected):
    env = {}
    calc.evaluate_block(source, env)
    assert calc.format_value(env["x"]) == expected


def test_derived_results_still_collapse_to_named_units():
    env = {}
    calc.evaluate_block("f = 1 / (2.2 us)\nR = 50 mV / 1.2 A", env)
    assert calc.format_value(env["f"]) == "454.5 kHz"
    assert calc.format_value(env["R"]) == "41.67 mΩ"


def test_unit_assertion_passes_and_pins_the_display_unit():
    env = {}
    outcomes = calc.evaluate_block("P : W = 3.3 V * 1.2 A", env)
    assert outcomes[0].error is None
    assert calc.format_value(env["P"]) == "3.96 W"  # not 3.96 kW or 3960 mW


def test_unit_assertion_catches_dimensional_drift():
    outcomes = calc.evaluate_block("P : W = 3.3 V / 1.2 A", {})
    assert outcomes[0].error is not None
    assert "declared as W" in outcomes[0].error


def test_mil_is_a_length_not_pints_angular_mil():
    """pint reads a bare `mil` as the NATO angular mil, which is dimensionless.

    Every PCB engineer means 0.001 inch. Without the alias, `62 mil` silently
    becomes a dimensionless 62 and propagates as a wrong answer.
    """
    env = {}
    calc.evaluate_block("t : mm = 62 mil", env)
    assert calc.format_value(env["t"]) == "1.575 mm"

    outcomes = calc.evaluate_block("bad = 62 mil + 3 V", {})
    assert outcomes[0].error is not None  # now a real dimensional error


def test_mils_plural_also_works():
    env = {}
    calc.evaluate_block("a = 20 mil\nb = 20 mils", env)
    assert env["a"].nom == env["b"].nom


def test_dimensionless_units_keep_their_symbol():
    """50 ppm must not render as a bare 50, but 0.93 must stay bare."""
    env = {}
    calc.evaluate_block("r = 50 ppm\neff = 0.93", env)
    assert calc.format_value(env["r"]) == "50 ppm"
    assert calc.format_value(env["eff"]) == "0.93"


def test_dimensional_mismatch_is_an_error_not_a_wrong_answer():
    outcomes = calc.evaluate_block("x = 3.3 V + 1.2 A", {})
    assert outcomes[0].error is not None
    assert "V" in outcomes[0].error and "A" in outcomes[0].error


def test_tolerance_propagates_as_an_interval():
    env = {}
    calc.evaluate_block("V = 12 V ± 5%\nI = 2 A\nP = V * I", env)
    assert calc.format_value(env["P"]) == "24 W"
    assert calc.format_bounds(env["P"]) == "22.8 W … 25.2 W"


def test_absolute_tolerance():
    env = {}
    calc.evaluate_block("V = 12 V ± 0.5 V", env)
    assert calc.format_bounds(env["V"]) == "11.5 V … 12.5 V"


@pytest.mark.parametrize(
    "source",
    [
        '__import__("os").system("echo pwned")',
        'open("secrets.txt")',
        "x.__class__.__bases__",
        "[1, 2, 3]",
        "lambda: 1",
        "(1).__class__",
    ],
)
def test_calc_dsl_cannot_execute_code(source):
    with pytest.raises(calc.CalcError):
        calc.evaluate(source, {})


# ------------------------------------------------------------------------ limits


def test_check_uses_the_worst_case_bound_not_the_nominal():
    """A nominal that passes but a tolerance corner that fails must fail."""
    env = {}
    calc.evaluate_block("V = 10 V ± 20%", env)
    limit = calc.parse_limit("<= 11 V")
    ok, _detail = limit.check(env["V"])
    assert ok is False  # nominal 10 V passes, but the 12 V corner does not


def test_range_limit():
    env = {}
    calc.evaluate_block("V = 12 V", env)
    assert calc.parse_limit("9 V .. 36 V").check(env["V"])[0] is True
    assert calc.parse_limit("9 V .. 11 V").check(env["V"])[0] is False


def test_unreadable_limit_is_rejected():
    with pytest.raises(calc.CalcError):
        calc.parse_limit("somewhere under 2 watts")


# -------------------------------------------------------------------- on_change


def _project():
    project = load_project(config_path=os.path.join(REPO, "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def _hash_after(project, item_id, field, value):
    item = project.items[item_id]
    original = item.fields.get(field)
    item.fields[field] = value
    build_mod.compute_hashes(project)
    changed = item.content_hash
    item.fields[field] = original
    build_mod.compute_hashes(project)
    return changed


def test_log_field_does_not_disturb_the_content_hash():
    """Changing owner must not mark downstream links suspect."""
    project = _project()
    before = project.items["REQ-PWR-001"].content_hash
    assert _hash_after(project, "REQ-PWR-001", "owner", "Someone Else") == before


def test_invalidate_field_changes_the_content_hash():
    project = _project()
    before = project.items["CON-THM-001"].content_hash
    assert _hash_after(project, "CON-THM-001", "limit", "<= 1.5 W/in^2") != before


def test_item_level_override_beats_the_schema():
    """REQ-PWR-004 sets owner -> ignore, so even a `log` field goes fully silent."""
    project = _project()
    spec = project.types["requirement"]
    item = project.items["REQ-PWR-004"]
    assert item.on_change_for("owner", spec, project.default_on_change) == "ignore"
    assert project.items["REQ-PWR-001"].on_change_for(
        "owner", spec, project.default_on_change
    ) == "log"


# ----------------------------------------------------------------- coverage


COVERAGE_SCHEMA = """\
site: {title: "Coverage Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    label: Decision
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [proposed, accepted, on_hold], default: proposed, on_change: invalidate }
    links:
      satisfies: [requirement]
    satisfying_statuses: [accepted]
    body: { on_change: invalidate }
"""

COVERAGE_ITEMS = {
    "req-a.md": """\
---
id: REQ-A-001
type: requirement
text: Needs a settled decision.
---
""",
    "dec-a.md": """\
---
id: DEC-A-001
type: decision
title: Settled choice.
status: accepted
satisfies: [REQ-A-001]
---
""",
    "req-b.md": """\
---
id: REQ-B-001
type: requirement
text: Only claimed so far.
---
""",
    "dec-b.md": """\
---
id: DEC-B-001
type: decision
title: Not settled yet.
status: on_hold
satisfies: [REQ-B-001]
---
""",
}


@pytest.fixture
def coverage_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in COVERAGE_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_settled_decision_satisfies_but_unsettled_only_claims(coverage_project):
    """A requirement's only satisfier being `on_hold` must not read as satisfied (#1 P1-1)."""
    project = load_project(config_path=str(coverage_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    settled = project.coverage["REQ-A-001"]
    assert settled.stage == "satisfied"
    assert settled.satisfied_by == ["DEC-A-001"]
    assert settled.claimed_by == []

    unsettled = project.coverage["REQ-B-001"]
    assert unsettled.stage == "claimed"
    assert unsettled.claimed_by == ["DEC-B-001"]
    assert unsettled.satisfied_by == []


def test_satisfying_statuses_absent_keeps_old_behavior(coverage_project):
    """A type with no satisfying_statuses: configured still counts every link (back-compat)."""
    schema = COVERAGE_SCHEMA.replace("    satisfying_statuses: [accepted]\n", "")
    (coverage_project / "refdes.yaml").write_text(schema, encoding="utf-8")

    project = load_project(config_path=str(coverage_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    unsettled = project.coverage["REQ-B-001"]
    assert unsettled.stage == "satisfied"
    assert unsettled.satisfied_by == ["DEC-B-001"]
    assert unsettled.claimed_by == []


NO_STATUS_FIELD_SCHEMA = """\
site: {title: "Bad Schema", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    label: Decision
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links:
      satisfies: [requirement]
    satisfying_statuses: [accepted]
    body: { on_change: invalidate }
"""


def test_satisfying_statuses_requires_a_status_field(tmp_path):
    path = tmp_path / "refdes.yaml"
    path.write_text(NO_STATUS_FIELD_SCHEMA, encoding="utf-8")
    with pytest.raises(SchemaError, match="satisfying_statuses"):
        load_project(config_path=str(path))


# --------------------------------------------------------- misspelled link keys


TYPO_LINK_ITEMS = {
    "req-a.md": """\
---
id: REQ-A-001
type: requirement
text: Needs a decision.
---
""",
    "dec-a.md": """\
---
id: DEC-A-001
type: decision
title: Typo'd the link name.
status: accepted
sattisfies: [REQ-A-001]
---
""",
}


@pytest.fixture
def typo_link_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in TYPO_LINK_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_misspelled_link_key_errors_instead_of_silently_dropping(typo_link_project):
    """`sattisfies:` must fail the build, not warn while quietly losing the edge (#1 P1-3)."""
    project = load_project(config_path=str(typo_link_project / "refdes.yaml"))
    parse.load_items(project)

    assert any(
        "sattisfies" in d.message and "satisfies" in d.message for d in project.errors
    )
    assert not any("sattisfies" in d.message for d in project.warnings)
    # The edge really is dropped -- that's exactly why this must be an error.
    assert project.items["DEC-A-001"].links == {}


def test_unrecognized_field_far_from_any_link_still_only_warns(tmp_path):
    """A genuine unknown field with no close link name must keep warning, not error."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(
        """\
---
id: DEC-A-001
type: decision
title: Has a genuinely unrelated field.
status: accepted
completely_unrelated_nonsense: yes
---
""",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    assert any("completely_unrelated_nonsense" in d.message for d in project.warnings)
    assert not any("completely_unrelated_nonsense" in d.message for d in project.errors)


# ------------------------------------------------------------------ image src


IMAGE_ITEM = """\
---
id: DEC-A-001
type: decision
title: Has a couple images.
status: accepted
---

![missing](figures/missing.png)

![present](figures/present.png)

![remote](https://example.com/photo.png)
"""


@pytest.fixture
def image_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(IMAGE_ITEM, encoding="utf-8")
    figures = items / "figures"
    figures.mkdir()
    (figures / "present.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def test_missing_image_src_warns_present_and_remote_do_not(image_project):
    """A dangling image src must warn like every other dangling reference (#1 P1-4)."""
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    messages = [d.message for d in project.warnings]
    assert any("figures/missing.png" in m for m in messages)
    assert not any("figures/present.png" in m for m in messages)
    assert not any("example.com" in m for m in messages)


# -------------------------------------------------------------- stale output


PRUNE_ITEMS = {
    "req-a.md": """\
---
id: REQ-A-001
type: requirement
text: Stays.
---
""",
    "req-b.md": """\
---
id: REQ-B-001
type: requirement
text: Gets deleted.
---
""",
}


@pytest.fixture
def prune_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in PRUNE_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def _build_and_render(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return render.render_site(project)


def test_deleting_an_item_prunes_its_stale_page(prune_project):
    """A deleted item must not leave a live, still-linkable page in _site/ (#1 P1-4)."""
    out_dir = _build_and_render(prune_project)
    stale_page = os.path.join(out_dir, "req-b-001.html")
    assert os.path.isfile(stale_page)

    (prune_project / "items" / "req-b.md").unlink()

    out_dir = _build_and_render(prune_project)
    assert not os.path.isfile(stale_page)
    assert os.path.isfile(os.path.join(out_dir, "req-a-001.html"))


def test_prune_never_touches_files_it_did_not_write(prune_project):
    """Pruning must be scoped to the manifest, never a blanket sweep of out_dir."""
    out_dir = _build_and_render(prune_project)
    hand_written = os.path.join(out_dir, "notes.txt")
    with open(hand_written, "w", encoding="utf-8") as fh:
        fh.write("keep me")

    _build_and_render(prune_project)
    assert os.path.isfile(hand_written)


# ---------------------------------------------------------------------- ids


LIST_FILE = """\
defaults:
  type: requirement
  prefix: REQ-TMP
items:
  - id: REQ-TMP-001
    text: First.
  - text: Inserted at the top later.
  - id: REQ-TMP-002
    text: Second.
"""


@pytest.fixture
def temp_project(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "tmp.yaml").write_text(LIST_FILE, encoding="utf-8")
    return tmp_path


def test_allocation_never_renumbers_existing_items(temp_project):
    project = load_project(config_path=str(temp_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    text = (temp_project / "items" / "requirements" / "tmp.yaml").read_text(
        encoding="utf-8"
    )
    # The pre-existing IDs keep their numbers; the new item gets the next free one.
    assert "REQ-TMP-001" in text
    assert "REQ-TMP-002" in text
    assert "REQ-TMP-003" in text
    assert text.index("REQ-TMP-003") < text.index("REQ-TMP-002")  # inserted in place


def test_allocated_numbers_are_burned_and_never_reused(temp_project):
    project = load_project(config_path=str(temp_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    # Delete every item, then add a fresh one: it must not reclaim a burned number.
    (temp_project / "items" / "requirements" / "tmp.yaml").write_text(
        textwrap.dedent(
            """\
            defaults:
              type: requirement
              prefix: REQ-TMP
            items:
              - text: Brand new.
            """
        ),
        encoding="utf-8",
    )
    project2 = load_project(config_path=str(temp_project / "refdes.yaml"))
    parse.load_items(project2, require_ids=False)
    assignments = ids.allocate(project2)
    assert assignments[0][1] == "REQ-TMP-004"


FLOW_STYLE_LIST_FILE = """\
defaults:
  type: requirement
  prefix: REQ-TMP
items:
  - id: REQ-TMP-001
    text: First.
  - {text: flow style entry}
"""


@pytest.fixture
def flow_style_project(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "tmp.yaml").write_text(FLOW_STYLE_LIST_FILE, encoding="utf-8")
    return tmp_path


def test_allocation_into_flow_style_entry_stays_valid_yaml(flow_style_project):
    """`- {text: ...}` must gain an id without breaking the flow mapping (#1 P1-13)."""
    project = load_project(config_path=str(flow_style_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    path = flow_style_project / "items" / "requirements" / "tmp.yaml"
    text = path.read_text(encoding="utf-8")

    # The rewritten file must still be parseable YAML with the id + text intact.
    reparsed = yaml.safe_load(text)
    entries = reparsed["items"]
    assert entries[1] == {"id": "REQ-TMP-002", "text": "flow style entry"}


def test_unclosed_flow_entry_is_refused_not_corrupted(flow_style_project):
    """A flow mapping that doesn't close on its own line must be refused, not guessed at."""
    path = flow_style_project / "items" / "requirements" / "tmp.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            defaults:
              type: requirement
              prefix: REQ-TMP
            items:
              - id: REQ-TMP-001
                text: First.
              - {text: "spans
                multiple lines"}
            """
        ),
        encoding="utf-8",
    )
    project = load_project(config_path=str(flow_style_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    before = path.read_text(encoding="utf-8")
    ids.allocate(project)
    after = path.read_text(encoding="utf-8")

    assert after == before  # refused write must leave the source file untouched
    assert any("could not write id" in d.message for d in project.errors)


# ------------------------------------------------------------------------ imports

UPSTREAM = {
    "title": "Platform Interfaces",
    "version": "2026.3",
    "items": [
        {
            "id": "IFC-CAN-001",
            "type": "constraint",
            "title": "Per-pin current rating",
            "fields": {"title": "Per-pin current rating", "limit": "<= 3 A"},
            "links": {},
            "content_hash": "upstreamhash01",
        }
    ],
}

BOARD_DECISION = """\
---
id: DEC-X-001
type: decision
title: Connector pin allocation
status: accepted
constrains: [IFC-CAN-001]
checks:
  - value: I_pin
    against: IFC-CAN-001
---

```calc
I_total   = 4.8 A
n_pins    = 2
I_pin : A = I_total / n_pins
```
"""


@pytest.fixture
def importing_project(tmp_path):
    import json

    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "items.json").write_text(
        json.dumps(UPSTREAM), encoding="utf-8"
    )
    config = open(os.path.join(REPO, "refdes.yaml"), encoding="utf-8").read()
    config += (
        '\nimports:\n  - name: platform\n'
        '    items: upstream/items.json\n    version: "2026.3"\n'
    )
    (tmp_path / "refdes.yaml").write_text(config, encoding="utf-8")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "pins.md").write_text(BOARD_DECISION, encoding="utf-8")
    return tmp_path


def _build_at(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def test_imported_items_resolve_links_and_checks(importing_project):
    project = _build_at(importing_project)
    assert not project.errors
    upstream = project.items["IFC-CAN-001"]
    assert upstream.external is True
    assert upstream.origin == "platform"
    # 4.8 A over 2 pins is 2.4 A, inside the 3 A rating.
    assert project.items["DEC-X-001"].checks[0].ok is True


def test_upstream_change_fails_the_downstream_board(importing_project):
    import json

    tightened = json.loads(json.dumps(UPSTREAM))
    tightened["items"][0]["fields"]["limit"] = "<= 2 A"
    (importing_project / "upstream" / "items.json").write_text(
        json.dumps(tightened), encoding="utf-8"
    )
    project = _build_at(importing_project)
    assert project.items["DEC-X-001"].checks[0].ok is False


def test_version_pin_mismatch_refuses_the_import(importing_project):
    import json

    moved = json.loads(json.dumps(UPSTREAM))
    moved["version"] = "2026.4"
    (importing_project / "upstream" / "items.json").write_text(
        json.dumps(moved), encoding="utf-8"
    )
    project = _build_at(importing_project)
    assert any("pinned to" in d.message for d in project.errors)
    assert "IFC-CAN-001" not in project.items


def test_id_collision_across_projects_is_an_error(importing_project):
    colliding = (importing_project / "items" / "decisions" / "dup.yaml")
    colliding.write_text(
        "defaults: { type: constraint }\n"
        "items:\n"
        "  - id: IFC-CAN-001\n"
        "    title: Locally redefined\n"
        '    limit: "<= 9 A"\n',
        encoding="utf-8",
    )
    project = _build_at(importing_project)
    assert any("already exists" in d.message for d in project.errors)


def test_imported_items_are_excluded_from_local_coverage(importing_project):
    """Upstream's coverage gaps are upstream's problem, not this board's."""
    project = _build_at(importing_project)
    assert "IFC-CAN-001" not in project.coverage
    assert project.items["IFC-CAN-001"].content_hash == "upstreamhash01"


# ------------------------------------------------------------------------- pages


@pytest.fixture
def paged_project(tmp_path):
    config = open(os.path.join(REPO, "refdes.yaml"), encoding="utf-8").read()
    (tmp_path / "refdes.yaml").write_text(config, encoding="utf-8")

    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
        encoding="utf-8",
    )

    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text(
        "# Board overview\n\nStart with [the power notes](power.md).\n",
        encoding="utf-8",
    )
    (pages / "power.md").write_text(
        "---\norder: 5\n---\n\n# Power\n\nDriven by REQ-001.\n\n"
        "## Rails\n\ntext\n\n## Budget\n\ntext\n",
        encoding="utf-8",
    )
    return tmp_path


def test_pages_render_without_being_items(paged_project):
    project = _build_at(paged_project)
    assert not project.errors
    assert {p.slug for p in project.pages} == {"index", "power"}
    # A page is not an item: no ID, no coverage obligations.
    assert "index" not in project.items
    assert len(project.items) == 1


def test_page_titles_come_from_the_h1(paged_project):
    project = _build_at(paged_project)
    titles = {p.slug: p.title for p in project.pages}
    assert titles["index"] == "Board overview"
    assert titles["power"] == "Power"


def test_pages_sort_by_explicit_nav_then_order(paged_project):
    """front-matter `order: 5` beats the default 100."""
    project = _build_at(paged_project)
    assert [p.slug for p in project.pages] == ["power", "index"]


def test_page_to_page_links_are_rewritten_to_html(paged_project):
    project = _build_at(paged_project)
    index = next(p for p in project.pages if p.slug == "index")
    assert 'href="power.html"' in index.body_html
    assert ".md" not in index.body_html


def test_pages_can_reference_items_and_get_previews(paged_project):
    project = _build_at(paged_project)
    power = next(p for p in project.pages if p.slug == "power")
    assert 'data-ref="REQ-001"' in power.body_html


def test_page_headings_get_anchors(paged_project):
    project = _build_at(paged_project)
    power = next(p for p in project.pages if p.slug == "power")
    assert [text for _lvl, text, _a in power.headings] == ["Rails", "Budget"]
    assert '<h2 id="rails">' in power.body_html


def test_page_colliding_with_a_generated_report_is_an_error(paged_project):
    """A page called coverage.md must not silently clobber the coverage report."""
    (paged_project / "pages" / "coverage.md").write_text("# Nope\n", encoding="utf-8")
    project = _build_at(paged_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)
    # The report survives; the page is skipped rather than overwriting it.
    out = os.path.join(paged_project, "_site", "coverage.html")
    assert "Nope" not in open(out, encoding="utf-8").read()


def test_pages_only_project_may_use_report_names_freely(tmp_path):
    """With no items there are no generated reports, so coverage.md is fine."""
    (tmp_path / "refdes.yaml").write_text(
        "site:\n  title: Docs\n  out: _site\n  pages: pages\n"
        "types:\n  note:\n    prefix: NOTE\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "coverage.md").write_text("# Coverage guide\n", encoding="utf-8")
    project = _build_at(tmp_path)
    out = render.render_site(project)
    assert not project.errors
    assert "Coverage guide" in open(
        os.path.join(out, "coverage.html"), encoding="utf-8"
    ).read()


def test_docs_site_builds_with_no_items_at_all(tmp_path):
    """A pages-only project is a plain website; nothing item-shaped is required."""
    (tmp_path / "refdes.yaml").write_text(
        'site:\n  title: Docs\n  out: _site\n  pages: pages\n'
        "types:\n  note:\n    prefix: NOTE\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text("# Hello\n\nSome prose.\n", encoding="utf-8")

    project = _build_at(tmp_path)
    out = render.render_site(project)
    assert not project.errors
    assert os.path.isfile(os.path.join(out, "index.html"))
    assert os.path.isdir(os.path.join(out, "assets"))
    # No items means no item machinery in the output.
    assert not os.path.exists(os.path.join(out, "coverage.html"))


# ----------------------------------------------------------------- summary view


@pytest.mark.parametrize(
    "limit_text, value, expected",
    [
        ("<= 0.15 W/in^2", "0.10 W/in^2", 1 / 3),    # a third of the limit spare
        ("<= 0.15 W/in^2", "0.2366 W/in^2", -0.577), # over, so negative
        ("<= 0.15 W/in^2", "0.15 W/in^2", 0.0),      # exactly on the limit
        (">= 3.0 V", "3.3 V", 0.1),
        (">= 3.0 V", "2.7 V", -0.1),
        ("9 V .. 36 V", "12 V", 1 / 9),              # nearer edge decides
        ("9 V .. 36 V", "40 V", -4 / 27),
    ],
)
def test_margin_reports_fractional_slack(limit_text, value, expected):
    env = {}
    calc.evaluate_block(f"x = {value}", env)
    margin = calc.parse_limit(limit_text).margin(env["x"])
    assert margin == pytest.approx(expected, abs=1e-3)


def test_margin_sign_always_agrees_with_pass_fail():
    """A positive margin that failed, or negative that passed, would be a lie."""
    for limit_text, value in [
        ("<= 5 V", "4 V"), ("<= 5 V", "6 V"),
        (">= 5 V", "6 V"), (">= 5 V", "4 V"),
        ("1 V .. 5 V", "3 V"), ("1 V .. 5 V", "7 V"),
    ]:
        env = {}
        calc.evaluate_block(f"x = {value}", env)
        limit = calc.parse_limit(limit_text)
        ok, _ = limit.check(env["x"])
        assert (limit.margin(env["x"]) >= 0) is ok, (limit_text, value)


def test_margin_is_unit_aware_not_magnitude_aware():
    """150 mW and 0.1 W differ by 33%, not by a factor of 1500."""
    env = {}
    calc.evaluate_block("x = 0.1 W", env)
    assert calc.parse_limit("<= 150 mW").margin(env["x"]) == pytest.approx(1 / 3, abs=1e-3)


def test_margin_is_undefined_where_it_would_be_meaningless():
    env = {}
    calc.evaluate_block("x = 5 V", env)
    assert calc.parse_limit("== 5 V").margin(env["x"]) is None  # met or not, no "close"
    env2 = {}
    calc.evaluate_block("y = 0 V", env2)
    assert calc.parse_limit("<= 0 V").margin(env2["y"]) is None  # no dividing by zero


def test_summary_orders_checks_by_tightest_margin():
    payload = render.summary_payload(_project())
    margins = [c.margin for _i, c in payload["margin_rows"] if c.margin is not None]
    assert margins == sorted(margins)
    assert margins[0] < 0  # the thermal violation sorts to the top


def test_a_constraint_that_is_checked_against_is_not_orphaned():
    """`checks:` is a real dependency even though it creates no link edge.

    Listing a checked-against constraint as untraced would contradict the margins
    table on the very same page.
    """
    project = _project()
    payload = render.summary_payload(project)
    orphan_ids = {i.id for i in payload["orphans"]}
    checked = {c.against for i in project.local_items for c in i.checks if c.against}
    assert checked
    assert not (orphan_ids & checked)


def test_summary_reports_every_computed_value():
    project = _project()
    payload = render.summary_payload(project)
    assert len(payload["calc_rows"]) == sum(len(i.calcs) for i in project.local_items)


def test_log_entries_have_a_readable_title_not_their_own_id():
    """A log entry names its description `summary`, so `title` must find it.

    Without this every table that shows a title -- coverage, the full record, hover
    previews -- renders a column of bare IDs for log entries.
    """
    project = _project()
    entries = [i for i in project.local_items if i.type == "log"]
    assert entries
    for entry in entries:
        assert entry.title != entry.id
        assert entry.title == entry.fields["summary"]


def test_page_named_summary_collides_with_the_report(paged_project):
    (paged_project / "pages" / "summary.md").write_text("# Nope\n", encoding="utf-8")
    project = _build_at(paged_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)
    out = os.path.join(paged_project, "_site", "summary.html")
    assert "Nope" not in open(out, encoding="utf-8").read()


# -------------------------------------------------------------------- integration


def test_example_project_builds_and_catches_the_thermal_violation():
    project = _project()
    decision = project.items["DEC-PWR-001"]
    by_name = {c.value_name: c for c in decision.checks}
    assert by_name["eff"].ok is True
    assert by_name["P_dens"].ok is False
    assert "violates CON-THM-001" in " ".join(d.message for d in project.errors)


def test_backlinks_resolve_from_either_end_of_an_edge():
    """A test declaring `verifies` must appear as `verified_by` on the requirement."""
    project = _project()
    assert project.items["REQ-PWR-002"].backlinks["verified_by"] == ["TST-PWR-002"]
    assert project.items["REQ-PWR-002"].backlinks["satisfied_by"] == ["DEC-PWR-001"]


def test_coverage_separates_addressed_satisfied_and_verified():
    project = _project()
    cov = project.coverage

    # Worked on and decided, but no test proves it yet.
    assert cov["REQ-PWR-003"].stage == "satisfied"
    assert cov["REQ-PWR-003"].satisfied_by == ["DEC-PWR-001"]
    assert cov["REQ-PWR-003"].verified_by == []

    # Fully covered.
    assert cov["REQ-PWR-002"].stage == "verified"

    # Written down and never touched again.
    assert cov["REQ-PWR-004"].stage == "open"

    # A log entry alone counts as addressed, not satisfied.
    assert cov["CON-THM-001"].stage == "addressed"
    assert "LOG-A-005" in cov["CON-THM-001"].addressed_by


def test_outstanding_work_is_warned_about():
    project = _project()
    warned = {d.item_id for d in project.warnings}
    assert "REQ-PWR-003" in warned  # satisfied but unverified
    assert "REQ-PWR-004" in warned  # nothing at all
    assert "REQ-PWR-001" not in warned  # verified by TST-PWR-001


def test_log_entries_are_sealed_and_edits_are_caught():
    project = _project()
    entry = project.items["LOG-A-003"]
    seals = seal.load_seals(project)
    assert seals.get(entry.id) == entry.content_hash

    entry.fields["summary"] = "edited after the fact"
    build_mod.compute_hashes(project)
    seal.verify(project, write=False, reseal=False)
    assert "LOG-A-003" in project.seal_violations


def test_log_amendments_are_links_not_edits():
    """A correction appends a new entry rather than rewriting the old one."""
    project = _project()
    assert project.items["LOG-A-006"].links["amends"] == ["LOG-A-003"]
    assert project.items["LOG-A-003"].backlinks["amended_by"] == ["LOG-A-006"]
