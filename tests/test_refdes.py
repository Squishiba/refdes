"""Tests for the invariants that must never quietly break.

The rest of the tool can be rewritten freely. These four cannot: IDs must never
shift, the calc DSL must never execute code, the content hash must follow the
on_change policy exactly, and checks must be evaluated at the worst-case tolerance
bound rather than the nominal.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import textwrap

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from refdes import boards as boards_mod  # noqa: E402
from refdes import build as build_mod  # noqa: E402
from refdes import calc, cli as cli_mod, citations as citations_mod, ids, nav as nav_mod, parse, render, seal  # noqa: E402
from refdes import former_ids  # noqa: E402
from refdes import lifecycle  # noqa: E402
from refdes import revise  # noqa: E402
from refdes import scaffold as scaffold_mod  # noqa: E402
from refdes import schema_json as schema_json_mod  # noqa: E402
from refdes import standards  # noqa: E402
from refdes import stub_tests as stub_tests_mod  # noqa: E402
from refdes import workspaces as workspaces_mod  # noqa: E402
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


def test_misplaced_tolerance_names_the_fix_not_the_parse_failure():
    """Finding 9: a tolerance one character to the left of where it belongs
    (next to the unit assertion, not the expression) must not surface as
    "unknown unit 'W ± 10%'" -- that describes what the parser saw, not what
    the author meant, while they're one character from working syntax."""
    outcomes = calc.evaluate_block("P : W ± 10% = V * I", {})
    assert outcomes[0].error is not None
    assert "unknown unit" not in outcomes[0].error
    assert (
        "a tolerance belongs on the right-hand side — P : W = V * I ± 10%"
        == outcomes[0].error
    )


def test_misplaced_tolerance_plus_minus_spelling_is_also_caught():
    outcomes = calc.evaluate_block("P : W +/- 10% = V * I", {})
    assert outcomes[0].error is not None
    assert "a tolerance belongs on the right-hand side — P : W = V * I ± 10%" == outcomes[0].error


def test_misplaced_tolerance_error_reaches_the_build_diagnostic(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nV = 3.3 V\nI = 1.2 A\nP : W ± 10% = V * I\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    message = next(d.message for d in project.errors if "P" in d.message)
    assert "calc 'P': a tolerance belongs on the right-hand side — P : W = V * I ± 10%" == message


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


# --------------------------------------------------------------- sigfig format


def test_format_quantity_default_digits_is_four():
    env = {}
    calc.evaluate_block("P = 3.3 V * 1.2 A", env)
    assert calc.format_value(env["P"]) == "3.96 W"


def test_format_quantity_respects_requested_digits():
    env = {}
    calc.evaluate_block("P = 3.3 V * 1.2 A", env)
    assert calc.format_value(env["P"], 2) == "4 W"


def test_format_quantity_prefers_positional_over_a_couple_of_invented_zeros():
    """issue #3 finding 14: plain `:.{n}g` renders 606.0606 at 2 sigfigs as
    "6.1e+02", which overstates how surprising the number is. One invented
    trailing zero is close enough to stay positional: "610"."""
    env = {}
    calc.evaluate_block("x = 606.0606", env)
    assert calc.format_value(env["x"], 2) == "610"


def test_format_quantity_keeps_scientific_beyond_a_couple_of_invented_zeros():
    """1234567 at 4 sigfigs would need three invented zeros ("1235000") to stay
    positional -- too far from the real precision, so it keeps the exponent."""
    env = {}
    calc.evaluate_block("x = 1234567", env)
    assert calc.format_value(env["x"], 4) == "1.235e+06"


def test_format_quantity_sigfig_taming_applies_with_units_too():
    env = {}
    calc.evaluate_block("R = 606.0606 ohm", env)
    assert calc.format_value(env["R"], 2) == "610 Ω"


@pytest.mark.parametrize(
    "magnitude, digits, expected",
    [
        (606.0606, 2, "610"),      # 1 invented zero -- positional
        (1234567, 4, "1.235e+06"),  # 3 invented zeros -- stays scientific
        (999.6, 3, "1000"),        # rounds across a power of ten, still positional
        (0.0004321, 2, "0.00043"),  # underflow case untouched by this rule
        (0, 3, "0"),
    ],
)
def test_sigfig_str_boundary_cases(magnitude, digits, expected):
    assert calc._sigfig_str(magnitude, digits) == expected


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


def test_unreadable_limit_hints_when_it_looks_like_several_bounds():
    """Multiple numbers plus a list-like conjunction reads as several bounds
    stuffed into one field -- the exact shape of the sensor spec (accuracy,
    temperature, clamp voltage) that motivated this hint."""
    with pytest.raises(calc.CalcError) as exc:
        calc.parse_limit("±1 % of full scale across 0-60 degC, with 12 V TVS protection")
    assert "split it into one item per bound" in str(exc.value)


def test_unreadable_limit_does_not_hint_on_an_ordinary_typo():
    """A single-bound typo shouldn't get told to split into multiple constraints."""
    with pytest.raises(calc.CalcError) as exc:
        calc.parse_limit("somewhere under 2 watts")
    assert "split it into one item per bound" not in str(exc.value)


def test_unreadable_limit_does_not_hint_on_a_tolerance_alone():
    """Two numbers with no list-like conjunction (a tolerance, not a list of
    bounds) should not trigger the hint either."""
    with pytest.raises(calc.CalcError) as exc:
        calc.parse_limit("100 ohm ±5%")
    assert "split it into one item per bound" not in str(exc.value)


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


def test_log_and_ignore_are_indistinguishable_for_hashing():
    """`log` is reserved for a future history layer; today it behaves as `ignore`."""
    project = _project()
    before = project.items["REQ-PWR-001"].content_hash
    log_hash = _hash_after(project, "REQ-PWR-001", "owner", "Someone Else")  # on_change: log
    ignore_hash = _hash_after(project, "REQ-PWR-001", "last_reviewed", "2020-01-01")  # on_change: ignore
    assert log_hash == before == ignore_hash


def test_invalidate_field_changes_the_content_hash():
    project = _project()
    before = project.items["BND-THM-001"].content_hash
    assert _hash_after(project, "BND-THM-001", "limit", "<= 1.5 W/in^2") != before


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


# ---------------------------------------------------- coverage warning aggregation

COVERAGE_AGGREGATION_SCHEMA = """\
site: {title: "Coverage Aggregation Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
  verifies:  { inverse: verified_by, label: "Verifies" }
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
  test:
    prefix: TST
    label: Test
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links:
      verifies: [requirement]
    body: { on_change: invalidate }
"""

COVERAGE_AGGREGATION_ITEMS = {
    "req-open.md": "---\nid: REQ-OPEN-001\ntype: requirement\ntext: Untouched.\n---\n",
    "req-sat.md": "---\nid: REQ-SAT-001\ntype: requirement\ntext: Settled, unverified.\n---\n",
    "dec-sat.md": (
        "---\nid: DEC-SAT-001\ntype: decision\ntitle: t\nstatus: accepted\n"
        "satisfies: [REQ-SAT-001]\n---\n"
    ),
    "req-claim.md": "---\nid: REQ-CLAIM-001\ntype: requirement\ntext: Not settled.\n---\n",
    "dec-claim.md": (
        "---\nid: DEC-CLAIM-001\ntype: decision\ntitle: t\nstatus: on_hold\n"
        "satisfies: [REQ-CLAIM-001]\n---\n"
    ),
    "req-verified.md": "---\nid: REQ-VERIFIED-001\ntype: requirement\ntext: Fully covered.\n---\n",
    "dec-verified.md": (
        "---\nid: DEC-VERIFIED-001\ntype: decision\ntitle: t\nstatus: accepted\n"
        "satisfies: [REQ-VERIFIED-001]\n---\n"
    ),
    "tst.md": (
        "---\nid: TST-VERIFIED-001\ntype: test\ntitle: t\n"
        "verifies: [REQ-VERIFIED-001]\n---\n"
    ),
}


@pytest.fixture
def coverage_aggregation_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_AGGREGATION_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in COVERAGE_AGGREGATION_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def _build_coverage_project(path):
    project = load_project(config_path=str(path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def test_open_and_unverified_coverage_warnings_are_aggregated(coverage_aggregation_project):
    """Per-item noise for the two routine coverage classes collapses into one
    summary line each, with `coverage.html` carrying the detail (issue #3, finding 8)."""
    project = _build_coverage_project(coverage_aggregation_project)

    messages = {d.message for d in project.warnings if d.item_id is None}
    assert "1 item(s) with no coverage — see coverage.html" in messages
    assert "1 requirement(s) satisfied but not verified — see coverage.html" in messages

    # No per-item duplicate for either aggregated class.
    assert not any(d.item_id == "REQ-OPEN-001" for d in project.warnings)
    assert not any(d.item_id == "REQ-SAT-001" for d in project.warnings)
    # Fully verified requirement contributes to neither bucket.
    assert not any(d.item_id == "REQ-VERIFIED-001" for d in project.warnings)


def test_claimed_but_not_verified_stays_per_item(coverage_aggregation_project):
    """The one coverage warning that names something actionable -- an unsettled
    decision -- must not be swallowed into the aggregate."""
    project = _build_coverage_project(coverage_aggregation_project)

    claimed = [d for d in project.warnings if d.item_id == "REQ-CLAIM-001"]
    assert len(claimed) == 1
    assert "claimed but not verified" in claimed[0].message


def test_satisfied_without_any_test_items_is_silent(coverage_project):
    """`coverage_project` declares no `test` type at all, so "not verified" is
    noise by construction -- suppressed entirely, per item and aggregated."""
    project = _build_coverage_project(coverage_project)

    assert not any(d.item_id == "REQ-A-001" for d in project.warnings)
    assert not any("satisfied but not verified" in d.message for d in project.warnings)


def test_first_test_item_makes_unverified_warnings_reappear(coverage_project):
    """The suppression only holds while zero `test` items exist -- adding the
    first one is meant to bring the warning right back (confirmed intended
    behaviour, not a surprise to design around)."""
    # Verifier-type detection is link-based now (docs/design/standard-library.md
    # §2), so this fixture's `test` type needs an actual `verifies:` link to
    # count -- a bare type named "test" with no such link no longer implies one.
    schema = COVERAGE_SCHEMA.replace(
        '  satisfies: { inverse: satisfied_by, label: "Satisfies" }\n',
        '  satisfies: { inverse: satisfied_by, label: "Satisfies" }\n'
        '  verifies: { inverse: verified_by, label: "Verifies" }\n',
    ) + (
        "  test:\n"
        "    prefix: TST\n"
        "    label: Test\n"
        "    fields:\n"
        "      title: { type: text, required: true, on_change: invalidate }\n"
        "    links:\n"
        "      verifies: [requirement]\n"
        "    body: { on_change: invalidate }\n"
    )
    (coverage_project / "refdes.yaml").write_text(schema, encoding="utf-8")
    (coverage_project / "items" / "tst.md").write_text(
        "---\nid: TST-UNRELATED-001\ntype: test\ntitle: An unrelated test.\n---\n",
        encoding="utf-8",
    )

    project = _build_coverage_project(coverage_project)

    assert any(
        d.message == "1 requirement(s) satisfied but not verified — see coverage.html"
        for d in project.warnings
    )


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


def test_constraint_title_renamed_to_text_gives_a_specific_diagnostic(tmp_path):
    """Finding 4: hardware v2 renamed constraint.title to constraint.text. An
    item still declaring the old key must get one diagnostic naming the
    rename -- not the generic unknown-field warning plus an unrelated-looking
    missing-required error a plain rename would otherwise produce."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: CON-001\n    type: constraint\n    title: Old-style constraint.\n"
        '    limit: "<= 1 W"\n',
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    rename_errors = [
        d for d in project.errors
        if "constraint.title" in d.message and "constraint.text" in d.message
    ]
    assert len(rename_errors) == 1
    assert rename_errors[0].item_id == "CON-001"

    # Exactly this one diagnostic -- not the generic pair a plain rename would
    # otherwise produce.
    assert not any("unknown field 'title'" in d.message for d in project.warnings)
    assert not any("missing required field 'text'" in d.message for d in project.errors)

    # The old value is used for the new field, so nothing downstream cascades
    # into a confusing secondary failure.
    assert project.items["CON-001"].fields["text"] == "Old-style constraint."


def test_constraint_title_on_hardware_v1_is_unaffected(tmp_path):
    """v1 is untouched: title: is still constraint's real field there, so the
    rename diagnostic must not fire -- confirming it's scoped to schemas
    where the rename actually applies, not fired unconditionally by type
    name alone."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: CON-001\n    type: constraint\n    title: A constraint.\n"
        '    limit: "<= 1 W"\n',
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors
    assert not project.warnings
    assert project.items["CON-001"].fields["title"] == "A constraint."


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


# ------------------------------------------------ checks against temperatures

TEMPERATURE_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    '  constrained_by: { inverse: constrains, label: "Constrained by" }\n'
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      checks: { type: checks }\n"
    "    links:\n"
    "      constrained_by: [bound]\n"
    "    body: {}\n"
)


def _temperature_project(tmp_path, limit, value="40 degC"):
    (tmp_path / "refdes.yaml").write_text(TEMPERATURE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "b.yaml").write_text(
        "items:\n"
        "  - id: BND-001\n    type: bound\n    text: Junction temperature\n"
        '    limit: "%s"\n' % limit,
        encoding="utf-8",
    )
    (items / "d.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Thermal\n"
        "constrained_by: [BND-001]\n"
        "checks:\n"
        "  - value: T_j\n"
        "    against: BND-001\n"
        "---\n\n"
        "```calc\nT_j : degC = %s\n```\n" % value,
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


@pytest.mark.parametrize("limit", ["<= 85 degC", "< 85 degC", ">= 10 degC", "<= 200 degF"])
def test_a_check_against_a_temperature_limit_does_not_crash(tmp_path, limit):
    """`< 85 degC` is one of the six forms the limits table documents, and about
    the most obvious constraint a board has. Every one-sided comparison against
    an offset unit used to abort the whole command with an unhandled
    pint.OffsetUnitCalculusError traceback -- not a diagnostic, a crash -- from
    inside margin(), which divides a temperature *difference* by a temperature
    *reading*. No test had ever evaluated a check against a temperature, and the
    sample project has none."""
    project = _temperature_project(tmp_path, limit)
    result = project.items["DEC-001"].checks[0]
    assert result.ok, result.detail
    # The comparison itself is well-defined and still reported.
    assert "40" in result.detail


def test_a_temperature_margin_is_undefined_not_invented(tmp_path):
    """A fraction of an offset-unit reading has no meaning -- 45 degC of slack
    against an 85 degC limit is 53% or 13% depending purely on where zero
    sits -- so there is no number to report. `margin: None` is the same
    already-supported state an `==` limit produces."""
    project = _temperature_project(tmp_path, "<= 85 degC")
    assert project.items["DEC-001"].checks[0].margin is None


def test_an_absolute_temperature_scale_still_gets_a_real_margin(tmp_path):
    """Kelvin has no offset, so the division is well-defined and the margin is
    a real number -- the None above is specific to offset units, not a blanket
    give-up on temperature."""
    project = _temperature_project(tmp_path, "<= 350 K", value="300 K")
    margin = project.items["DEC-001"].checks[0].margin
    assert margin is not None
    assert margin == pytest.approx((350 - 300) / 350, rel=1e-6)


def test_a_temperature_range_limit_still_gets_a_real_margin(tmp_path):
    """A range measures slack against its own span -- a difference divided by a
    difference -- so offset units are not ambiguous there and never were."""
    project = _temperature_project(tmp_path, "0 degC .. 60 degC")
    assert project.items["DEC-001"].checks[0].margin is not None


# --------------------------------------------------------- YAML error diagnostics


def test_invalid_yaml_in_a_list_file_reports_the_real_line_not_always_1(tmp_path):
    """Finding 13's actual point: line=1 was hardcoded, not a fallback -- wrong
    for any malformed YAML past the first couple of lines, not just the '>'
    gotcha this finding is nominally about. A literal tab in indentation is a
    clean repro: YAML disallows it outright, and PyYAML's own mark lands
    exactly on the offending line."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: REQ-A-001\n"
        "    text: fine.\n"
        "  - id: REQ-A-002\n"
        "\ttext: tabbed\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert yaml_errors[0].line != 1
    assert yaml_errors[0].line == 5  # the tabbed line itself


def test_invalid_yaml_in_markdown_front_matter_reports_the_real_line(tmp_path):
    """Same fix, front-matter path -- the parsed text is a *slice* of the
    file starting after the opening fence, so the exception's own mark (which
    is relative to that slice) needs the slice's offset added back, or the
    reported line would be wrong in a new way instead of just defaulting to 1."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.md").write_text(
        "---\n"
        "id: DEC-A-001\n"
        "type: decision\n"
        "title: fine so far\n"
        "\tstatus: tabbed\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML front-matter" in d.message]
    assert len(yaml_errors) == 1
    assert yaml_errors[0].line != 1
    assert yaml_errors[0].line == 5  # the tabbed line itself


def test_bare_gte_limit_gets_a_quoting_hint(tmp_path):
    """A bare '>=' value is read by YAML as a folded-block-scalar indicator,
    not a comparison -- the resulting scanner error should carry a targeted
    hint saying so, not just PyYAML's raw internals message."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: CON-001\n"
        "    title: t\n"
        "    limit: >= 9 V\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert "needs quotes" in yaml_errors[0].message
    assert '">= 9 V"' in yaml_errors[0].message
    assert yaml_errors[0].line == 4  # the `limit: >= 9 V` line itself


def test_bare_gt_hint_fires_on_any_field_not_just_limit(tmp_path):
    """The finding is explicit that this must be scoped to the line's actual
    content, not to a field literally named `limit` -- the same YAML gotcha
    hits any field."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: REQ-A-001\n"
        "    text: > shall be greater than something\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert "needs quotes" in yaml_errors[0].message


def test_other_yaml_errors_get_no_quoting_hint(tmp_path):
    """The hint must not fire on an unrelated malformed-YAML failure -- an
    unterminated flow sequence has nothing to do with the '>' gotcha."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: REQ-A-001\n"
        "    text: [ unterminated\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert "needs quotes" not in yaml_errors[0].message


# ------------------------------------------------------------- images and assets


def _asset_hash(data: bytes) -> str:
    """Matches build.py's own truncation of the content sha256 for a hashed
    asset filename -- computed here, not hardcoded, so a deliberate change to
    the truncation length doesn't silently rot these tests."""
    return hashlib.sha256(data).hexdigest()[:16]


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


def test_missing_image_src_errors_present_and_remote_do_not(image_project):
    """A dangling image src must fail the build now that a resolving one works."""
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    messages = [d.message for d in project.errors]
    assert any("figures/missing.png" in m for m in messages)
    assert not any("figures/present.png" in m for m in messages)
    assert not any("example.com" in m for m in messages)
    assert not any("figures/missing.png" in d.message for d in project.warnings)


def test_present_local_image_is_registered_and_rewritten(image_project):
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    assert "items/figures/present.png" in project.assets
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    assert project.assets["items/figures/present.png"] == f"items/figures/present.{digest}.png"
    item = project.items["DEC-A-001"]
    assert f'src="assets/items/figures/present.{digest}.png"' in item.body_html
    # A remote src is never touched or registered.
    assert "assets/https" not in item.body_html
    assert 'src="https://example.com/photo.png"' in item.body_html


def test_local_image_is_copied_into_the_site(image_project):
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)

    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    copied = os.path.join(out, "assets", "items", "figures", f"present.{digest}.png")
    assert os.path.isfile(copied)
    assert open(copied, "rb").read() == b"\x89PNG\r\n\x1a\n"


def test_editing_an_image_changes_its_url_and_prunes_the_old_one(image_project):
    """Content-hashed filenames (docs/design/index-blocks.md §10): editing the
    bytes in place must not silently serve stale content from a cache under
    the same URL -- the filename itself has to change, and the old one must
    not linger in _site/."""
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)
    old_digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    old_path = os.path.join(out, "assets", "items", "figures", f"present.{old_digest}.png")
    assert os.path.isfile(old_path)

    new_bytes = b"\x89PNG\r\n\x1a\n\x00extra"
    (image_project / "items" / "figures" / "present.png").write_bytes(new_bytes)

    project2 = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)
    out2 = render.render_site(project2)
    new_digest = _asset_hash(new_bytes)
    assert new_digest != old_digest
    new_path = os.path.join(out2, "assets", "items", "figures", f"present.{new_digest}.png")
    assert os.path.isfile(new_path)
    assert not os.path.isfile(old_path)  # pruned, same as any other stale output


def test_deleting_an_image_reference_prunes_its_copied_asset(image_project):
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    copied = os.path.join(out, "assets", "items", "figures", f"present.{digest}.png")
    assert os.path.isfile(copied)

    text = (image_project / "items" / "dec-a.md").read_text(encoding="utf-8")
    text = text.replace("![present](figures/present.png)\n\n", "")
    (image_project / "items" / "dec-a.md").write_text(text, encoding="utf-8")

    out = _build_and_render(image_project)
    assert not os.path.isfile(copied)


def test_asset_colliding_with_a_template_reserved_name_is_an_error(tmp_path):
    """A site.assets: directory literally named `style.css` must not clobber
    the template's own reserved top-level asset name. An `<img src>` can no
    longer produce this collision now that it is always content-hashed (an
    escaping `../style.css` reference now lands on `style.<hash>.css`); a
    site.assets: mapping stays an identity mapping (docs/design/index-blocks.md
    §10), so it is the one remaining way to hit this."""
    schema = COVERAGE_SCHEMA.replace(
        'site: {title: "Coverage Test", out: _site}',
        'site: {title: "Coverage Test", out: _site, assets: ["style.css"]}',
    )
    (tmp_path / "refdes.yaml").write_text(schema, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    clobber_dir = tmp_path / "style.css"
    clobber_dir.mkdir()
    (clobber_dir / "logo.png").write_text("SHOULD NOT LAND HERE", encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)

    assert any("would be written to assets/style.css" in d.message for d in project.errors)
    real_style = open(os.path.join(out, "assets", "style.css"), encoding="utf-8").read()
    assert "SHOULD NOT LAND HERE" not in real_style  # the template's own stylesheet survived


# ------------------------------------------------------------- site.assets:

SITE_ASSETS_SCHEMA = COVERAGE_SCHEMA.replace(
    'site: {title: "Coverage Test", out: _site}',
    'site: {title: "Coverage Test", out: _site, assets: [figures]}',
)


@pytest.fixture
def site_assets_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(SITE_ASSETS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: Nothing references figures.\n---\n",
        encoding="utf-8",
    )
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "board.pdf").write_bytes(b"%PDF-1.4 fake")
    return tmp_path


def test_site_assets_directory_is_copied_with_no_reference_needed(site_assets_project):
    out = _build_and_render(site_assets_project)
    copied = os.path.join(out, "assets", "figures", "board.pdf")
    assert os.path.isfile(copied)
    assert open(copied, "rb").read() == b"%PDF-1.4 fake"


def test_site_assets_missing_directory_warns(tmp_path):
    schema = COVERAGE_SCHEMA.replace(
        'site: {title: "Coverage Test", out: _site}',
        'site: {title: "Coverage Test", out: _site, assets: [nope]}',
    )
    (tmp_path / "refdes.yaml").write_text(schema, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert any("'nope' is not a directory" in d.message for d in project.warnings)


# ------------------------------------------------------------- figure/caption

FIGURE_ITEM = """\
---
id: DEC-A-001
type: decision
title: Has a captioned figure.
status: accepted
---

![the curve](figures/present.png){width=60% caption="Figure 3 — the curve"}

![no caption given](figures/present.png){width=40%}

![plain, no suffix](figures/present.png)
"""


@pytest.fixture
def figure_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(FIGURE_ITEM, encoding="utf-8")
    figures = items / "figures"
    figures.mkdir()
    (figures / "present.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def test_figure_attrs_wrap_the_image_and_set_width_and_caption(figure_project):
    project = load_project(config_path=str(figure_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    html = project.items["DEC-A-001"].body_html
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")

    assert '<figure class="md-figure" style="width: 60%">' in html
    assert "<figcaption>Figure 3 — the curve</figcaption>" in html
    assert f'<img src="assets/items/figures/present.{digest}.png" alt="the curve" />' in html


def test_figure_caption_falls_back_to_alt_when_not_given(figure_project):
    project = load_project(config_path=str(figure_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    html = project.items["DEC-A-001"].body_html

    assert '<figure class="md-figure" style="width: 40%">' in html
    assert "<figcaption>no caption given</figcaption>" in html


def test_image_with_no_suffix_is_never_wrapped_in_a_figure(figure_project):
    project = load_project(config_path=str(figure_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    html = project.items["DEC-A-001"].body_html
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")

    assert f'<img src="assets/items/figures/present.{digest}.png" alt="plain, no suffix" />' in html
    # Exactly two images are wrapped (the two with a suffix); the third stands alone.
    assert html.count("<figure") == 2


# ------------------------------------------------------------- pages + images

def test_pages_get_the_same_image_resolution_and_copy(tmp_path):
    config = open(os.path.join(REPO, "refdes.yaml"), encoding="utf-8").read()
    (tmp_path / "refdes.yaml").write_text(config, encoding="utf-8")
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text(
        "# Overview\n\n![board photo](img/board.png)\n", encoding="utf-8"
    )
    img_dir = pages / "img"
    img_dir.mkdir()
    (img_dir / "board.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    out = _build_and_render(tmp_path)
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    assert os.path.isfile(os.path.join(out, "assets", "pages", "img", f"board.{digest}.png"))
    index_html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert f'src="assets/pages/img/board.{digest}.png"' in index_html


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


def test_id_write_back_fills_bare_id_key_in_place_not_a_second_key(tmp_path):
    """`refdes new` scaffolds a bare `id:` placeholder as the first key. Running
    `refdes id` on it must fill that key in place -- not insert a second `id:` key
    below it. A duplicate key is not a cosmetic wart: YAML resolves a mapping with
    a duplicate key to the *last* occurrence, which is the still-empty original, so
    the item silently looks unallocated again on the very next parse, and a second
    `refdes id` run burns a second id on top of the first without fixing anything."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "i.yaml"
    path.write_text(
        "defaults: { type: requirement, prefix: CAN }\n"
        "items:\n"
        "  - id:\n"
        "    text: A can requirement.\n",
        encoding="utf-8",
    )

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "CAN-001"

    text = path.read_text(encoding="utf-8")
    assert text.count("id:") == 1, f"expected exactly one 'id:' key, got:\n{text}"
    assert "id: CAN-001" in text

    # Re-parse from disk, the way a second, separate `refdes id` invocation would --
    # this is what actually exposes the corruption: a duplicate key resolves to the
    # *last* one, so a still-broken file looks pending again here.
    project2 = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project2, require_ids=False)
    assert project2.items.get("CAN-001") is not None
    assert not project2.pending, "the item must not still look unallocated on reparse"

    # A second run against an already-correct file must be a no-op, not another
    # allocation burning a second id for the same item.
    assignments2 = ids.allocate(project2)
    assert assignments2 == []


def test_id_write_back_fills_bare_id_key_in_place_markdown(tmp_path):
    """Same corruption as the YAML-list form above, but through the front-matter
    insertion path (`insert_into_markdown`), which is even more directly at fault:
    it splices in a new line unconditionally, with no read of what's already on the
    target line at all."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  decision: { prefix: DEC, fields: { title: { type: text, required: true } }, body: {} }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "d.md"
    path.write_text(
        "---\n"
        "id:\n"
        "type: decision\n"
        "title: A decision.\n"
        "---\n"
        "Body text.\n",
        encoding="utf-8",
    )

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "DEC-001"

    text = path.read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert front_matter.count("id:") == 1, f"expected exactly one 'id:' key, got:\n{text}"
    assert "id: DEC-001" in front_matter

    project2 = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project2, require_ids=False)
    assert project2.items.get("DEC-001") is not None
    assert not project2.pending, "the item must not still look unallocated on reparse"

    assignments2 = ids.allocate(project2)
    assert assignments2 == []


# --------------------------------------------- bare-numeric expand-and-freeze (finding 8 Part 1)

NUMERIC_HINT_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n"
)


def _numeric_hint_project(tmp_path, items_yaml):
    (tmp_path / "refdes.yaml").write_text(NUMERIC_HINT_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def test_quoted_numeric_id_expands_in_place_no_duplicate_key(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: \"042\"\n    text: Legacy number.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "CAN-042"

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert text.count("id:") == 1, f"expected exactly one 'id:' key, got:\n{text}"
    assert "id: CAN-042" in text


def test_expanded_numeric_id_is_byte_identical_to_a_hand_typed_one(tmp_path):
    """The finding's own hard-won conclusion: once expanded, the stored id is
    exactly as self-contained as a fully hand-typed one -- nothing left for
    check/build to ever resolve live."""
    hand_root = tmp_path / "hand"
    (hand_root / "items").mkdir(parents=True)
    (hand_root / "refdes.yaml").write_text(NUMERIC_HINT_SCHEMA, encoding="utf-8")
    hand_file = hand_root / "items" / "r.yaml"
    hand_file.write_text(
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CAN-042\n    text: Same content either way.\n",
        encoding="utf-8",
    )

    exp_root = tmp_path / "expanded"
    (exp_root / "items").mkdir(parents=True)
    (exp_root / "refdes.yaml").write_text(NUMERIC_HINT_SCHEMA, encoding="utf-8")
    exp_file = exp_root / "items" / "r.yaml"
    exp_file.write_text(
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: \"042\"\n    text: Same content either way.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(exp_root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    assert exp_file.read_text(encoding="utf-8") == hand_file.read_text(encoding="utf-8")


def test_quoted_numeric_id_expands_in_markdown_front_matter(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: { title: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "d.md"
    path.write_text('---\nid: "5"\ntype: decision\ntitle: Md form.\n---\n', encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "DEC-5"

    text = path.read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert front_matter.count("id:") == 1
    assert "id: DEC-5" in front_matter


def test_quoted_numeric_id_expands_inside_a_flow_style_entry(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        'items:\n  - {id: "042", text: flow style entry}\n',
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    reparsed = yaml.safe_load(text)
    assert reparsed["items"] == [{"id": "CAN-042", "text": "flow style entry"}]


def test_unquoted_numeric_id_is_refused_not_silently_mangled(tmp_path):
    """YAML reads an unquoted leading zero as octal (042 -> 34); trusting it
    would risk freezing the wrong id forever, so it's refused rather than
    expanded -- and, critically, must not be treated as an ordinary pending
    item either (see the next test)."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: 042\n    text: Unquoted, dangerous.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert any(
        "unquoted number" in d.message and "octal" in d.message for d in project.errors
    )


def test_unquoted_numeric_id_is_never_allocated_into(tmp_path):
    """The bug this guards against: an item that failed _resolve_id_value's
    safety check still has item.id == "" like a genuinely blank item -- if it
    entered project.pending, `refdes id` would allocate a fresh, unrelated id
    and write it in *alongside* the bad value (duplicate key, Part 0's bug
    again) instead of leaving the file untouched for a human to fix."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: 042\n    text: Unquoted, dangerous.\n",
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")

    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert project.pending == []

    assignments = ids.allocate(project)
    assert assignments == []
    after = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert after == before
    ledger_path = root / ".refdes" / "ids.yaml"
    assert not ledger_path.exists(), "no id may be burned for a rejected value"


def test_numeric_hint_freezes_the_authors_number_not_the_next_sequential_one(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n"
        "  - id: CAN-002\n    text: Already at 2.\n"
        "  - id: \"050\"\n    text: Matches legacy numbering.\n"
        "  - id:\n    text: Freshly authored, no opinion.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    by_text = {item.fields["text"]: new_id for item, new_id in assignments}
    assert by_text["Matches legacy numbering."] == "CAN-050"
    # The fresh item gets the next number *after* the frozen one, not 003.
    assert by_text["Freshly authored, no opinion."] == "CAN-051"


def test_numeric_hint_colliding_with_a_live_id_is_refused(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n"
        "  - id: CAN-005\n    text: Already exists.\n"
        "  - id: \"5\"\n    text: Collides with above.\n",
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments == []
    assert any("already used or was burned" in d.message for d in project.errors)
    assert (root / "items" / "r.yaml").read_text(encoding="utf-8") == before


def test_numeric_hint_colliding_with_a_burned_but_deleted_id_is_refused(tmp_path):
    """Burned ids are permanent even after the item that held one is deleted
    -- a numeric hint must respect that, not just check against currently
    live items."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: \"5\"\n    text: Wants a retired number.\n",
    )
    (root / ".refdes").mkdir()
    (root / ".refdes" / "ids.yaml").write_text(
        "burned:\n  CAN: 5\nallocated: []\n", encoding="utf-8"
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments == []
    assert any("already used or was burned" in d.message for d in project.errors)


def test_numeric_hint_two_items_requesting_the_same_number_only_one_wins(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n"
        "  - id: \"9\"\n    text: First claim.\n"
        "  - id: \"9\"\n    text: Second claim, same number.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert len(assignments) == 1
    assert assignments[0][0].fields["text"] == "First claim."
    assert any("already used or was burned" in d.message for d in project.errors)


def test_cli_id_reports_a_numeric_hint_collision_and_exits_nonzero(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n"
        "  - id: CAN-005\n    text: Already exists.\n"
        "  - id: \"5\"\n    text: Collides.\n",
    )
    status = cli_mod.main(["-c", str(root / "refdes.yaml"), "id"])
    assert status == 1


def test_cli_id_succeeds_and_reports_zero_when_nothing_is_pending(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CAN-001\n    text: Already has an id.\n",
    )
    assert cli_mod.main(["-c", str(root / "refdes.yaml"), "id"]) == 0


# --------------------------------------- prefix ("type segment") validation (finding 8 Parts 1/2)


def test_prefix_mismatch_from_a_defaults_override_is_the_documented_error(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    message = next(d.message for d in project.errors if "CNA-001" in d.message)
    assert message == "id 'CNA-001' does not match this item's prefix 'CAN' (from defaults:)"


def test_prefix_mismatch_against_the_types_own_default_names_the_type(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "items:\n  - id: XYZ-001\n    type: requirement\n    text: No override at all.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    message = next(d.message for d in project.errors if "XYZ-001" in d.message)
    assert message == (
        "id 'XYZ-001' does not match this item's prefix 'REQ' "
        "(the 'requirement' type's default)"
    )


def test_prefix_mismatch_is_reported_not_silently_rewritten(tmp_path):
    """A mismatch is Part 0's class of harm self-inflicted: auto-fixing an
    *existing* id would change the string every link is keyed on. The file
    must be untouched after a mismatch is reported."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert (root / "items" / "r.yaml").read_text(encoding="utf-8") == before
    assert project.items["CNA-001"].id == "CNA-001"  # not corrected in memory either


def test_prefix_with_a_free_form_category_segment_is_not_a_mismatch(tmp_path):
    """Part 2's category segment is typed straight into the id with no
    matching `prefix:` of its own (`IO-AI`, `EXP-PCIE`) -- this must not be
    confused with an actually-wrong prefix. Regression guard: split_id's own
    greedy match reads 'CON-IO' as one inseparable unit, which a naive
    equality check against the bare declared prefix would wrongly flag."""
    root = _numeric_hint_project(
        tmp_path,
        "items:\n  - id: REQ-IO-004\n    type: requirement\n    text: Category segment, no override.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert not any("REQ-IO-004" in d.message for d in project.errors)


def test_prefix_validation_skips_pending_items(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id:\n    text: Not allocated yet.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert project.errors == []


def test_prefix_validation_runs_as_part_of_a_real_build(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert any(
        "does not match this item's prefix" in d.message for d in project.errors
    )


# ------------------------------------------------------------------ former_ids

FORMER_IDS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
    "  decision: { prefix: DEC, fields: {}, body: {} }\n"
)


def _former_ids_project(tmp_path, items_yaml):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _former_ids_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def test_former_ids_are_burned_so_the_allocator_never_reissues_them(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Renumbered item.\n    former_ids: [REQ-050]\n"
        "  - text: Brand new, no id yet.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments[0][1] == "REQ-051"  # not REQ-002 -- REQ-050 stays burned


def test_former_ids_colliding_with_another_items_live_id_is_an_error(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: A.\n"
        "  - id: REQ-002\n    text: B.\n    former_ids: [REQ-001]\n",
    )
    project = _former_ids_build(root)
    assert any(
        "former_ids: 'REQ-001' is still a live item id" in d.message and d.item_id == "REQ-002"
        for d in project.errors
    )
    assert "REQ-001" not in project.former_ids


def test_former_ids_naming_itself_is_an_error(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A.\n    former_ids: [REQ-001]\n",
    )
    project = _former_ids_build(root)
    assert any(
        "former_ids: 'REQ-001' is this item's own current id" in d.message
        for d in project.errors
    )


def test_former_ids_claimed_by_two_items_is_an_error(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: A.\n    former_ids: [REQ-OLD-01]\n"
        "  - id: REQ-002\n    text: B.\n    former_ids: [REQ-OLD-01]\n",
    )
    project = _former_ids_build(root)
    message = next(d.message for d in project.errors if "REQ-OLD-01" in d.message)
    assert "REQ-001" in message and "REQ-002" in message
    assert "exactly one item" in message


def test_former_ids_resolve_bracketed_reference_with_a_formerly_marker(tmp_path):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\nSee [[REQ-050]] for context.\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    assert not project.errors
    html = project.items["DEC-001"].body_html
    assert 'class="ref ref-former"' in html
    assert 'href="req-001.html"' in html
    assert 'data-ref="REQ-001"' in html
    assert "(formerly REQ-050)" in html


def test_former_ids_resolve_bare_reference_when_it_fits_the_bare_pattern(tmp_path):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\nSee REQ-050 for context.\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    html = project.items["DEC-001"].body_html
    assert 'class="ref ref-former"' in html
    assert "(formerly REQ-050)" in html


def test_former_ids_shaped_like_a_legacy_underscore_id_only_link_explicitly(tmp_path):
    """`BARE_REF_RE` requires a `-<digits>` suffix, so an underscore-style former
    id like the CAN_00 example in finding 12 can never bare-autolink -- must
    stay reachable via [[CAN_00]], and the gap must be visible, not silent."""
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [CAN_00]\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "Bare mention CAN_00 stays plain text. Explicit [[CAN_00]] still resolves.\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    assert any(
        "'CAN_00' does not match the bare-reference shape" in d.message
        and "[[CAN_00]]" in d.message
        for d in project.warnings
    )
    html = project.items["DEC-001"].body_html
    assert "Bare mention CAN_00 stays plain text" in html
    assert html.count('class="ref ref-former"') == 1  # only the explicit one resolved


def test_cli_audit_lists_former_ids(tmp_path, capsys):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "audit"]) == 0
    out = capsys.readouterr().out
    assert "Former IDs:" in out
    assert "REQ-050" in out and "REQ-001" in out


def test_items_json_exports_former_ids(tmp_path):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    payload = render.items_json(project)
    entry = next(i for i in payload["items"] if i["id"] == "REQ-001")
    assert entry["former_ids"] == ["REQ-050"]


# ---------------------------------------------------- former-ids propose command


def _propose_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def test_propose_errors_with_no_baseline_stamped(tmp_path):
    root = _former_ids_project(tmp_path, "defaults: { type: requirement }\nitems: []\n")
    project = _propose_build(root)
    with pytest.raises(former_ids.ProposeError, match="no baseline stamped yet"):
        former_ids.propose(project)


def test_propose_matches_a_renumbered_item_by_title_similarity(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n"
        "    text: The bus shall recover from a bit error within one frame.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-002\n"
        "    text: The bus shall recover from a bit error within one frame.\n",
        encoding="utf-8",
    )
    project2 = _propose_build(root)
    candidates = former_ids.propose(project2)
    assert len(candidates) == 1
    c = candidates[0]
    assert (c.old_id, c.new_id) == ("REQ-001", "REQ-002")
    assert c.confidence == 1.0


def test_propose_ignores_a_removed_id_already_resolved(tmp_path):
    """An old id another item already claims via former_ids: is done -- it
    must not show up again as a fresh candidate."""
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-002\n    text: A requirement.\n    former_ids: [REQ-001]\n"
        "  - id: REQ-003\n    text: A different, unrelated requirement.\n",
        encoding="utf-8",
    )
    project2 = _propose_build(root)
    assert former_ids.propose(project2) == []


def test_propose_confirm_writes_former_ids_and_rejects_unknown_names(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A migrated requirement.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-002\n    text: A migrated requirement.\n",
        encoding="utf-8",
    )
    project2 = _propose_build(root)
    candidates = former_ids.propose(project2)

    with pytest.raises(former_ids.ProposeError, match="not a currently proposed candidate"):
        former_ids.confirm(project2, candidates, ["REQ-999"])

    confirmed = former_ids.confirm(project2, candidates, ["REQ-001"])
    assert [c.new_id for c in confirmed] == ["REQ-002"]
    assert project2.former_ids["REQ-001"] == "REQ-002"

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "former_ids: [REQ-001]" in text

    # And it's now durable: reparsing the rewritten file resolves cleanly.
    project3 = _propose_build(root)
    assert not project3.errors
    assert project3.former_ids["REQ-001"] == "REQ-002"


def test_cli_former_ids_propose_shows_candidates_then_writes_on_confirm(tmp_path, capsys):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A migrated requirement.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-002\n    text: A migrated requirement.\n",
        encoding="utf-8",
    )

    status = cli_mod.main(["-c", str(root / "refdes.yaml"), "former-ids", "propose"])
    assert status == 0
    out = capsys.readouterr().out
    assert "REQ-001" in out and "REQ-002" in out
    assert "Nothing written" in out
    assert "former_ids: [REQ-001]" not in (root / "items" / "r.yaml").read_text(encoding="utf-8")

    status = cli_mod.main(
        ["-c", str(root / "refdes.yaml"), "former-ids", "propose", "--confirm", "REQ-001"]
    )
    assert status == 0
    out = capsys.readouterr().out
    assert "wrote former_ids: [REQ-001] to REQ-002" in out
    assert "former_ids: [REQ-001]" in (root / "items" / "r.yaml").read_text(encoding="utf-8")


FLOW_STYLE_LIST_FILE = """\
defaults:
  type: requirement
  prefix: REQ-TMP
items:
  - id: REQ-TMP-001
    text: First.
  - {text: flow style entry}
"""


# -------------------------------------------------------------- multi-item markdown

MULTI_ITEM_DECISION_MD = """\
---
defaults:
  type: decision
  prefix: DEC-X
  status: accepted
---
id: DEC-X-001
title: First decision
---

Body of the first decision. Has some prose.

---
id: DEC-X-002
title: Second decision
---

Body of the second decision.
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


def test_a_refused_write_back_is_not_reported_as_allocated(flow_style_project):
    """The refusal used to sit one line above "allocated REQ-TMP-002" and
    "allocated 1 id(s)", for an id that was never written anywhere -- and the
    ledger recorded it as allocated and burned its number, so the next run
    handed the same item a different id and REQ-TMP-002 was gone for nothing.
    Nothing was written, so nothing is claimed."""
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
    assignments = ids.allocate(project)

    assert assignments == []
    ledger = ids.load_ledger(project)
    assert "REQ-TMP-002" not in (ledger.get("allocated") or [])
    assert int((ledger.get("burned") or {}).get("REQ-TMP", 0)) == 1
    # Still pending, so a later run retries it rather than skipping it.
    assert len(project.pending) == 1


def test_one_refused_write_back_does_not_block_its_neighbours(flow_style_project):
    """Per-item, not per-file: an entry that can be written still is, and is
    still reported and burned normally."""
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
              - text: A writable one.
            """
        ),
        encoding="utf-8",
    )
    project = load_project(config_path=str(flow_style_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)

    assert [new_id for _item, new_id in assignments] == ["REQ-TMP-003"]
    assert "id: REQ-TMP-003" in path.read_text(encoding="utf-8")
    ledger = ids.load_ledger(project)
    assert ledger["allocated"] == ["REQ-TMP-003"]
    assert any("could not write id" in d.message for d in project.errors)


@pytest.fixture
def multi_item_project(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "multi.md").write_text(MULTI_ITEM_DECISION_MD, encoding="utf-8")
    return tmp_path


def test_multi_item_markdown_file_parses_each_item_separately(multi_item_project):
    project = load_project(config_path=str(multi_item_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert not project.errors

    one = project.items["DEC-X-001"]
    two = project.items["DEC-X-002"]
    assert one.fields["title"] == "First decision"
    assert two.fields["title"] == "Second decision"
    # `defaults:` applied to both, and each keeps its own body -- no leakage
    # between items sharing one file.
    assert one.fields["status"] == "accepted"
    assert two.fields["status"] == "accepted"
    assert "first decision" in one.body.lower()
    assert "second decision" in two.body.lower()
    assert "Body of the first decision" not in two.body
    assert "Body of the second decision" not in one.body


def test_multi_item_source_lines_point_at_each_items_own_fence(multi_item_project):
    project = load_project(config_path=str(multi_item_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    text = (
        (multi_item_project / "items" / "decisions" / "multi.md")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    one = project.items["DEC-X-001"]
    two = project.items["DEC-X-002"]
    assert text[one.source_line - 1].strip() == "id: DEC-X-001"
    assert text[two.source_line - 1].strip() == "id: DEC-X-002"


def test_today_style_single_item_file_is_unaffected(tmp_path):
    """A one-document file, unchanged, must parse identically to before."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    text = open(
        os.path.join(REPO, "items", "decisions", "dec-pwr-001-regulator-topology.md"),
        encoding="utf-8",
    ).read()
    (items / "dec.md").write_text(text, encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert not project.errors
    assert len(project.items) == 1
    item = project.items["DEC-PWR-001"]
    assert item.source_line == 2
    assert item.body.startswith("\nThe 3V3 rail draws")


def test_literal_horizontal_rule_stays_in_the_body(tmp_path):
    """A `---` not followed by a YAML key is prose, not a second item."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "one.md").write_text(
        "---\n"
        "id: DEC-HR-001\n"
        "type: decision\n"
        "title: Solo\n"
        "---\n\n"
        "Some intro text.\n\n"
        "---\n\n"
        "More text after a horizontal rule.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert not project.errors
    assert len(project.items) == 1
    item = project.items["DEC-HR-001"]
    assert "More text after a horizontal rule." in item.body
    assert "---" in item.body


def test_horizontal_rule_with_no_closing_fence_stays_literal(tmp_path):
    """Key-shaped text after a `---` with nothing later to close it stays prose."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "one.md").write_text(
        "---\n"
        "id: DEC-HR-002\n"
        "type: decision\n"
        "title: Solo\n"
        "---\n\n"
        "Some intro text.\n\n"
        "---\n"
        "Note: this looks like a key but there is no closing fence.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert not project.errors
    assert len(project.items) == 1
    item = project.items["DEC-HR-002"]
    assert "Note: this looks like a key" in item.body


def test_defaults_block_alone_with_no_items_is_an_error(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "empty.md").write_text(
        "---\ndefaults:\n  type: decision\n---\n\nJust prose, no item.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert any("no items" in d.message for d in project.errors)


def test_refdes_id_writes_back_into_each_items_own_fence(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    path = items / "multi.md"
    path.write_text(
        "---\ndefaults:\n  type: decision\n  prefix: DEC-MULTI\n---\n"
        "title: First, no id yet\n---\n\nBody one.\n\n"
        "---\ntitle: Second, no id yet\n---\n\nBody two.\n",
        encoding="utf-8",
    )

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert [new_id for _item, new_id in assignments] == [
        "DEC-MULTI-001",
        "DEC-MULTI-002",
    ]

    # Re-parse from disk: both ids landed at the right fence, and each item still
    # has its own distinct body.
    project2 = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project2, require_ids=False)
    assert "Body one." in project2.items["DEC-MULTI-001"].body
    assert "Body two." in project2.items["DEC-MULTI-002"].body
    assert "Body two." not in project2.items["DEC-MULTI-001"].body


# ------------------------------------------------------------------- sections

SECTIONS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n"
    "  decision: { prefix: DEC, fields: { title: { type: text, required: true } }, body: {} }\n"
)


def test_section_elides_type_in_a_yaml_list_file(tmp_path):
    """Finding 6, built instead of the type-keyed items: mapping. A `section:`
    entry asserts the type for everything after it, so items no longer need
    to restate `type:` even though the file mixes two of them."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - section: requirement\n"
        "  - id: REQ-001\n    text: Elided via section.\n"
        "  - id: REQ-002\n    text: Also elided.\n"
        "  - section: decision\n"
        "  - id: DEC-001\n    title: Elided via a second section.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert not project.errors
    assert not project.warnings
    assert project.items["REQ-001"].type == "requirement"
    assert project.items["REQ-002"].type == "requirement"
    assert project.items["DEC-001"].type == "decision"


def test_section_elides_type_in_multi_item_markdown(tmp_path):
    """The Markdown spelling of the same marker: a fenced block whose only
    key is `section:`, as close to the list-file spelling as the format
    allows."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.md").write_text(
        "---\n"
        "section: decision\n"
        "---\n"
        "---\n"
        "id: DEC-101\n"
        "title: First, elided type via section.\n"
        "---\n"
        "Body one.\n"
        "\n"
        "---\n"
        "section: requirement\n"
        "---\n"
        "---\n"
        "id: REQ-101\n"
        "text: Second, elided type via a new section.\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert not project.errors
    assert not project.warnings
    assert project.items["DEC-101"].type == "decision"
    assert "Body one." in project.items["DEC-101"].body
    assert project.items["REQ-101"].type == "requirement"


def test_item_contradicting_its_section_is_an_error_not_a_silent_override(tmp_path):
    """The crux of why a section isn't just a second spelling of `defaults:`:
    under `defaults: {type: X}` an item may legally declare a different
    type -- a default is a fallback. Under a section, the container has
    already asserted what its items are, so a contradicting item is an
    error naming the conflict."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - section: requirement\n"
        "  - id: DEC-201\n    type: decision\n    title: Contradicts the active section.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "declares type 'decision'" in d.message and "section: requirement" in d.message
        for d in project.errors
    )
    assert "DEC-201" not in project.items


def test_file_defaults_type_conflicting_with_a_section_is_an_error(tmp_path):
    """Composition rule: if a file-level `defaults:` names a type and a
    section asserts a different one, that's the file contradicting itself --
    an error naming both, not a silent pick-a-winner."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: requirement\n"
        "items:\n"
        "  - section: decision\n"
        "  - id: DEC-301\n    title: Never legitimately typed.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "section: decision" in d.message and "defaults: {type: requirement}" in d.message
        for d in project.errors
    )


def test_section_composes_with_defaults_for_non_type_fields(tmp_path):
    """A file-level `defaults:` still supplies every other field exactly as
    today; a section only ever asserts `type:`, nothing else."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n"
        "      text:   { type: text, required: true }\n"
        "      status: { type: enum, choices: [draft, active], default: draft }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  status: active\n"
        "items:\n"
        "  - section: requirement\n"
        "  - id: REQ-401\n    text: Gets status from file defaults, type from the section.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert not project.errors
    item = project.items["REQ-401"]
    assert item.type == "requirement"
    assert item.fields["status"] == "active"


def test_later_defaults_block_in_markdown_is_now_an_error_not_silent(tmp_path):
    """The bug the investigation turned up: only the very first block in a
    multi-item Markdown file was ever read as file-wide defaults. A second
    `defaults:`-shaped block used to be silently misparsed as a malformed
    item, and everything after it silently kept the *original* file-wide
    type -- reproduced here exactly as found: an intended requirement lands
    as a decision, with nothing louder than an 'unknown field' warning to
    notice by. Must error now, independent of the section feature."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.md").write_text(
        "---\n"
        "defaults:\n"
        "  type: decision\n"
        "---\n"
        "---\n"
        "id: DEC-401\n"
        "title: First decision.\n"
        "---\n"
        "Body one.\n"
        "\n"
        "---\n"
        "defaults:\n"
        "  type: requirement\n"
        "---\n"
        "---\n"
        "id: REQ-401\n"
        "text: A requirement after a second defaults block.\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "'defaults:' only applies as the very first block" in d.message
        for d in project.errors
    )
    # The first block's type is unaffected; the real fix (turn this into a
    # 'section: requirement' marker) is left to the author -- this test only
    # needs to confirm the mistake is no longer silent.
    assert project.items["DEC-401"].type == "decision"


def test_malformed_later_markdown_block_is_reported_not_silently_dropped(tmp_path):
    """The same silent-drop shape as the `defaults:` bug above, one step
    quieter: a later `---`-fenced block that opens with a `key:` line -- so it
    was plainly meant as an item -- but whose YAML doesn't parse used to be
    skipped with no diagnostic at all. The item vanished from the project, its
    body text was folded into the *previous* item's, and the build exited 0
    with zero errors. The very first block in the same file has always
    reported this; every later one now reports it identically."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.md").write_text(
        "---\n"
        "defaults:\n"
        "  type: requirement\n"
        "---\n"
        "---\n"
        "id: REQ-601\n"
        "text: The first requirement.\n"
        "---\n"
        "Body one.\n"
        "\n"
        "---\n"
        "id: REQ-602\n"
        'text: "unclosed quote\n'
        "---\n"
        "Body two.\n"
        "\n"
        "---\n"
        "id: REQ-603\n"
        "text: The third requirement.\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    bad = [d for d in project.errors if "invalid YAML front-matter" in d.message]
    assert bad, [str(d) for d in project.errors]
    # Reported inside the offending block, not blamed on line 1 of the file.
    assert bad[0].line >= 12
    assert "REQ-602" not in project.items
    # Everything around it still parses -- one bad block is not a parse abort.
    assert "REQ-601" in project.items
    assert "REQ-603" in project.items


def test_later_markdown_block_that_is_not_a_mapping_is_reported(tmp_path):
    """A block that parses cleanly but isn't a mapping is the other half of
    the same gap -- also silently skipped before, also already reported when
    it happens to be the file's own head block."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.md").write_text(
        "---\n"
        "defaults:\n"
        "  type: requirement\n"
        "---\n"
        "---\n"
        "id: REQ-611\n"
        "text: The first requirement.\n"
        "---\n"
        "Body one.\n"
        "\n"
        "---\n"
        "key: value\n"
        "- a stray sequence entry\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "front-matter" in d.message and d.line > 1 for d in project.errors
    ), [str(d) for d in project.errors]


def test_section_marker_must_name_a_real_string(tmp_path):
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - section:\n"
        "  - id: REQ-501\n    type: requirement\n    text: Unaffected by the bad marker.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any("'section:' must name a type" in d.message for d in project.errors)
    assert project.items["REQ-501"].type == "requirement"


# ------------------------------------------------------------- reserved prefix key


def test_per_item_prefix_overrides_file_defaults_in_a_list_file(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "mixed.yaml").write_text(
        "defaults:\n  type: requirement\n  prefix: REQ-DEFAULT\n"
        "items:\n"
        "  - text: Uses the file default prefix.\n"
        "  - prefix: REQ-OVERRIDE\n"
        "    text: Uses its own prefix.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    got = {item.fields["text"]: new_id for item, new_id in assignments}
    assert got["Uses the file default prefix."] == "REQ-DEFAULT-001"
    assert got["Uses its own prefix."] == "REQ-OVERRIDE-001"
    # `prefix:` is consumed, never stored as a field.
    assert "prefix" not in project.items["REQ-OVERRIDE-001"].fields


def test_per_item_prefix_overrides_file_defaults_in_markdown(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "multi.md").write_text(
        "---\ndefaults:\n  type: decision\n  prefix: DEC-DEFAULT\n---\n"
        "title: Uses the file default\n---\n\nBody.\n\n"
        "---\nprefix: DEC-OWN\ntitle: Uses its own prefix\n---\n\nBody.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    got = {item.fields["title"]: new_id for item, new_id in assignments}
    assert got["Uses the file default"] == "DEC-DEFAULT-001"
    assert got["Uses its own prefix"] == "DEC-OWN-001"


# ------------------------------------------------------------------------ imports

UPSTREAM = {
    "title": "Platform Interfaces",
    "version": "2026.3",
    "items": [
        {
            "id": "IFC-CAN-001",
            "type": "bound",
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
constrained_by: [IFC-CAN-001]
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
        "defaults: { type: bound }\n"
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


# ------------------------------------------------------------------------ boards

BOARD_CONFIG = """\
site:
  title: "Board test"
  out: _site
id:
  width: 3
boards:
  board-a:
    label: "Board A"
    token: A
  board-b:
    label: "Board B"
    token: B
types:
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true }
"""


@pytest.fixture
def board_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BOARD_CONFIG, encoding="utf-8")

    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-A }\n"
        "items:\n  - id: REQ-A-001\n    text: On board A by its folder.\n",
        encoding="utf-8",
    )

    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-B }\n"
        "items:\n"
        "  - id: REQ-B-001\n    text: On board B by its folder.\n"
        "  - id: REQ-WRONG-001\n    prefix: REQ-WRONG\n"
        "    text: On board B but its own id prefix has no 'B' token.\n",
        encoding="utf-8",
    )

    shared = tmp_path / "items" / "shared"
    shared.mkdir(parents=True)
    (shared / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-S }\n"
        "items:\n"
        "  - id: REQ-S-001\n    text: In an unregistered folder, no board.\n"
        "  - id: REQ-S-002\n    board: board-a\n"
        "    text: Overridden onto board-a despite living in shared/.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_board_is_derived_from_the_first_path_segment_under_items(board_project):
    project = _build_at(board_project)
    assert project.items["REQ-A-001"].board == "board-a"
    assert project.items["REQ-B-001"].board == "board-b"


def test_unregistered_path_segment_gets_no_board(board_project):
    project = _build_at(board_project)
    assert project.items["REQ-S-001"].board == ""


def test_unregistered_path_segment_warns_that_it_has_no_board(board_project):
    project = _build_at(board_project)
    warned = [
        d for d in project.warnings
        if d.item_id == "REQ-S-001" and d.message.startswith("no board")
    ]
    assert len(warned) == 1
    message = warned[0].message
    assert "'shared' is not in the boards: registry" in message
    # Both remedies named: the file's defaults:, or moving it under a real board.
    assert "board: <name>" in message
    assert "items/<registered-board>/" in message


def test_item_directly_under_items_warns_that_it_has_no_board(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BOARD_CONFIG, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir(parents=True, exist_ok=True)
    (items / "loose.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-L }\n"
        "items:\n  - id: REQ-L-001\n    text: Sits directly in items/, no board folder.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.items["REQ-L-001"].board == ""
    warned = [
        d for d in project.warnings
        if d.item_id == "REQ-L-001" and d.message.startswith("no board")
    ]
    assert len(warned) == 1
    assert "outside any board folder" in warned[0].message


def test_item_level_board_override_beats_the_path(board_project):
    project = _build_at(board_project)
    assert project.items["REQ-S-002"].board == "board-a"


def test_item_level_board_override_does_not_warn_about_no_board(board_project):
    project = _build_at(board_project)
    assert not any(
        d.item_id == "REQ-S-002" and d.message.startswith("no board")
        for d in project.warnings
    )


def test_explicit_board_override_must_be_registered(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BOARD_CONFIG, encoding="utf-8")
    items = tmp_path / "items" / "shared"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-Z }\n"
        "items:\n  - id: REQ-Z-001\n    board: nonexistent\n    text: Bad board.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert any("nonexistent" in d.message and "not declared" in d.message for d in project.errors)


def test_token_lint_warns_on_prefix_mismatch(board_project):
    project = _build_at(board_project)
    warned = {d.item_id for d in project.warnings if "does not contain that token" in d.message}
    assert "REQ-WRONG-001" in warned
    assert "REQ-A-001" not in warned
    assert "REQ-B-001" not in warned


def test_token_lint_is_silent_without_a_declared_token(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n  board-a: { label: Board A }\n"  # no token
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "board-a"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-ANYTHING }\n"
        "items:\n  - id: REQ-ANYTHING-001\n    text: No token declared, nothing to check.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert not any("does not contain that token" in d.message for d in project.warnings)


def test_boards_registry_absent_is_inert(tmp_path):
    """No `boards:` block: every item's board stays empty, matching today.

    A dedicated, standalone fixture on purpose -- not a copy of this repo's own
    `refdes.yaml`, and not built from `_project()`, because that config now
    registers real boards (see test_real_project_registers_boards_and_renders_
    board_pages below). This is the regression guarantee that a project with no
    `boards:` block at all stays completely unaffected, kept independent of
    whatever the sample project does.
    """
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.boards == {}
    assert project.items["REQ-001"].board == ""
    out = render.render_site(project)
    assert not any(name.startswith("document-") for name in os.listdir(out))
    payload = render.items_json(project)
    assert "boards" not in payload
    assert "board" not in payload["items"][0]


def test_real_project_registers_boards_and_renders_board_pages(tmp_path):
    """This repo's own project now demonstrates the boards: registry itself.

    Board A is the existing items, retrofitted with a `board: board-a` default
    (their folders predate the registry, so path-based resolution alone would
    not reach them). Board B is a small, separate items/board-b/ tree that
    resolves purely from its folder name, with no override needed.
    """
    project = _project()
    assert set(project.boards) == {"board-a", "board-b"}
    assert project.items["REQ-PWR-001"].board == "board-a"
    assert project.items["REQ-B-PWR-001"].board == "board-b"
    project.out_dir = str(tmp_path / "_site")  # absolute: render outside the repo
    out = render.render_site(project)
    for board in ("board-a", "board-b"):
        for page in ("document", "coverage", "log", "summary"):
            assert os.path.isfile(os.path.join(out, f"{page}-{board}.html"))
    payload = render.items_json(project)
    assert set(payload["boards"]) == {"board-a", "board-b"}


def test_board_path_alias_matches_a_differently_named_folder(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n  board-a: { label: Board A, path: brdA }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "brdA"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-A }\n"
        "items:\n  - id: REQ-A-001\n    text: Folder spelled differently from the key.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.items["REQ-A-001"].board == "board-a"


def test_boards_registry_rejects_duplicate_path_segments(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n"
        "  board-a: { label: A, path: shared }\n"
        "  board-b: { label: B, path: shared }\n"
        "types:\n  requirement: { prefix: REQ }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="items/shared/"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


# --------------------------------------------------- project settings (refdes-project.yaml)

MINIMAL_PROJECT_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
)


def _write_minimal_project(tmp_path, settings_yaml: str | None = None):
    (tmp_path / "refdes.yaml").write_text(MINIMAL_PROJECT_SCHEMA, encoding="utf-8")
    if settings_yaml is not None:
        (tmp_path / "refdes-project.yaml").write_text(settings_yaml, encoding="utf-8")
    return tmp_path / "refdes.yaml"


def test_project_settings_absent_file_matches_pre_config_defaults(tmp_path):
    """A project with no refdes-project.yaml behaves exactly as today -- except
    publish_datasheets, whose default is a deliberate change (see its own
    docstring on Project)."""
    config = _write_minimal_project(tmp_path)
    project = load_project(config_path=str(config))
    assert project.sigfigs == 4
    assert project.item_layout == "flat"
    assert project.baseline_identity == "os_user"
    assert project.require_rejection_rationale is True
    assert project.publish_datasheets is False
    assert project.release_gate == {
        "draft_items":                {"release": True,  "revision": False},
        "unpinned_citations":         {"release": True,  "revision": False},
        "missing_vendored_copies":    {"release": True,  "revision": False},
        "uncovered_requirements":     {"release": True,  "revision": False},
        "unverified_requirements":    {"release": False, "revision": False},
        "info_check_failures":        {"release": False, "revision": False},
        "unaccepted_board_moves":     {"release": True,  "revision": False},
        "unaccepted_workspace_moves": {"release": True,  "revision": False},
    }


def test_project_settings_sigfigs_overrides_the_default(tmp_path):
    config = _write_minimal_project(tmp_path, "sigfigs: 6\n")
    project = load_project(config_path=str(config))
    assert project.sigfigs == 6


@pytest.mark.parametrize(
    "settings_yaml",
    ["sigfigs: 0\n", "sigfigs: 16\n", "sigfigs: 1.5\n", 'sigfigs: "4"\n', "sigfigs: true\n"],
)
def test_project_settings_sigfigs_out_of_range_or_wrong_type_is_a_schema_error(tmp_path, settings_yaml):
    config = _write_minimal_project(tmp_path, settings_yaml)
    with pytest.raises(SchemaError, match="sigfigs must be an integer between 1 and 15"):
        load_project(config_path=str(config))


def test_project_settings_item_layout_accepts_workspace(tmp_path):
    config = _write_minimal_project(tmp_path, "item_layout: workspace\n")
    project = load_project(config_path=str(config))
    assert project.item_layout == "workspace"


def test_project_settings_item_layout_rejects_a_free_form_pattern(tmp_path):
    """The user explicitly rejected general pattern syntax -- only the two
    fixed shapes are valid, not e.g. "<workspace>/<board>"."""
    config = _write_minimal_project(tmp_path, 'item_layout: "<workspace>/<board>"\n')
    with pytest.raises(SchemaError, match=r"item_layout must be one of \['flat', 'workspace'\]"):
        load_project(config_path=str(config))


def test_project_settings_baseline_identity_accepts_git_identity(tmp_path):
    config = _write_minimal_project(tmp_path, "baseline_identity: git_identity\n")
    project = load_project(config_path=str(config))
    assert project.baseline_identity == "git_identity"


def test_project_settings_baseline_identity_rejects_unknown_value(tmp_path):
    config = _write_minimal_project(tmp_path, "baseline_identity: ldap\n")
    with pytest.raises(SchemaError, match="baseline_identity must be one of"):
        load_project(config_path=str(config))


def test_project_settings_require_rejection_rationale_must_be_boolean(tmp_path):
    config = _write_minimal_project(tmp_path, "require_rejection_rationale: maybe\n")
    with pytest.raises(SchemaError, match="require_rejection_rationale must be true or false"):
        load_project(config_path=str(config))


def test_project_settings_publish_datasheets_must_be_boolean(tmp_path):
    config = _write_minimal_project(tmp_path, "publish_datasheets: on-request\n")
    with pytest.raises(SchemaError, match="publish_datasheets must be true or false"):
        load_project(config_path=str(config))


def test_project_settings_release_gate_overlay_only_touches_named_rules(tmp_path):
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  unverified_requirements: { release: true }\n",
    )
    project = load_project(config_path=str(config))
    assert project.release_gate["unverified_requirements"] == {"release": True, "revision": False}
    # everything else is untouched
    assert project.release_gate["draft_items"] == {"release": True, "revision": False}


def test_project_settings_release_gate_rejects_unknown_rule_with_a_suggestion(tmp_path):
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  draft_item: { release: true }\n",  # typo: missing 's'
    )
    with pytest.raises(SchemaError, match=r"draft_item.*Did you mean 'draft_items'"):
        load_project(config_path=str(config))


def test_project_settings_release_gate_rejects_unknown_inner_key(tmp_path):
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  draft_items: { relase: true }\n",  # typo: missing 'e'
    )
    with pytest.raises(SchemaError, match="release_gate.draft_items.relase"):
        load_project(config_path=str(config))


def test_project_settings_release_gate_rejects_non_boolean_value(tmp_path):
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  draft_items: { release: yes-please }\n",
    )
    with pytest.raises(SchemaError, match="release_gate.draft_items.release must be true or false"):
        load_project(config_path=str(config))


def test_project_settings_unknown_top_level_key_is_a_schema_error(tmp_path):
    config = _write_minimal_project(tmp_path, "sigffigs: 6\n")  # typo
    with pytest.raises(SchemaError, match=r"unknown setting 'sigffigs'.*Did you mean 'sigfigs'"):
        load_project(config_path=str(config))


def test_project_settings_file_must_be_a_mapping(tmp_path):
    config = _write_minimal_project(tmp_path, "- not\n- a\n- mapping\n")
    with pytest.raises(SchemaError, match="must be a mapping"):
        load_project(config_path=str(config))


def test_sigfigs_flows_through_calc_formatting(tmp_path):
    """Project.sigfigs, resolved once at load, reaches calc.format_value via
    build.run_calcs without every caller threading a digits= parameter."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
        encoding="utf-8",
    )
    (tmp_path / "refdes-project.yaml").write_text("sigfigs: 2\n", encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nP = 3.3 V * 1.2 A\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert project.items["DEC-001"].calcs[0].result == "4 W"  # 2 sigfigs, not "3.96 W"


def test_sigfigs_flows_through_check_messages(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  constraint: { prefix: CON, fields: { limit: { type: limit, required: true } } }\n"
        "  decision: { prefix: DEC, fields: {} }\n",
        encoding="utf-8",
    )
    (tmp_path / "refdes-project.yaml").write_text("sigfigs: 2\n", encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults: { type: constraint }\n"
        "items:\n  - id: CON-001\n    limit: \"<= 600 mA\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "checks:\n"
        "  - value: x\n"
        "    against: CON-001\n"
        "---\n\n"
        "```calc\nx : A = 0.6061 A\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    check = project.items["DEC-001"].checks[0]
    assert check.actual == "0.61 A"  # 2 sigfigs, not the default 4 (0.6061 A)


def test_per_board_pages_are_scoped_to_that_boards_items(board_project):
    project = _build_at(board_project)
    out = render.render_site(project)

    # previews_json embeds every item's data on every page for hover previews, so
    # scoping has to be checked against the actual rendered item section, not just
    # a bare substring search for the id anywhere on the page.
    doc_a = open(os.path.join(out, "document-board-a.html"), encoding="utf-8").read()
    doc_b = open(os.path.join(out, "document-board-b.html"), encoding="utf-8").read()
    assert 'id="req-a-001"' in doc_a
    assert 'id="req-b-001"' not in doc_a
    assert 'id="req-b-001"' in doc_b
    assert 'id="req-a-001"' not in doc_b

    cov_a = open(os.path.join(out, "coverage-board-a.html"), encoding="utf-8").read()
    assert 'data-ref="REQ-A-001"' in cov_a
    assert 'data-ref="REQ-B-001"' not in cov_a

    # The global pages are untouched -- every item still appears on them.
    doc_global = open(os.path.join(out, "document.html"), encoding="utf-8").read()
    assert 'id="req-a-001"' in doc_global and 'id="req-b-001"' in doc_global


def test_items_json_exports_board_registry_and_per_item_board(board_project):
    project = _build_at(board_project)
    payload = render.items_json(project)
    assert payload["boards"]["board-a"]["label"] == "Board A"
    assert payload["boards"]["board-a"]["token"] == "A"
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id["REQ-A-001"]["board"] == "board-a"
    assert by_id["REQ-S-001"]["board"] == ""


def test_reserved_filename_guard_covers_per_board_report_names(board_project):
    pages = board_project / "pages"
    pages.mkdir()
    (pages / "document-board-a.md").write_text("# Nope\n", encoding="utf-8")
    project = _build_at(board_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)


# ------------------------------------------------------------------------ nav


@pytest.fixture
def unboarded_project(tmp_path):
    """A project with no `boards:` registry at all -- a dedicated fixture, not
    `paged_project` (which copies this repo's own config, and this repo now
    registers boards -- see test_real_project_registers_boards_and_renders_
    board_pages)."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site, pages: pages }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text("# Overview\n\nSome prose.\n", encoding="utf-8")
    return tmp_path


def test_nav_tree_is_flat_with_no_boards_registered(unboarded_project):
    """No boards: registry -- nav degrades to the same flat list as before."""
    project = _build_at(unboarded_project)
    tree = nav_mod.build_nav(project, dashboard_href="items.html")
    assert [n.label for n in tree] == [
        "Overview", "Summary", "Items", "Coverage", "Full record", "JSON",
    ]
    assert all(n.href and not n.children for n in tree)


def test_navnode_contains_checks_self_and_descendants_at_any_depth():
    """Findings 5 and 7's shared plumbing: a group node must recognize a page
    living inside a nested descendant, not just its own direct href or
    immediate children -- board.py's own nesting (workspace > board > page)
    goes at least two levels deep."""
    leaf = nav_mod.NavNode("Coverage", "coverage-board-a.html")
    board_group = nav_mod.NavNode("Board A", children=[leaf])
    workspace_group = nav_mod.NavNode("Platform", children=[board_group])

    assert leaf.contains("coverage-board-a.html")
    assert board_group.contains("coverage-board-a.html")
    assert workspace_group.contains("coverage-board-a.html")
    assert not workspace_group.contains("coverage-board-b.html")
    assert not leaf.contains("")


def test_rendered_page_marks_current_page_with_aria_current(board_project):
    """Finding 5: the sidebar link for whatever page is actually being
    rendered gets aria-current="page" -- and no other link on that same page
    does, including the same-labeled link ("Coverage") in a sibling board's
    own group."""
    project = _build_at(board_project)
    out = render.render_site(project)
    coverage_a = open(os.path.join(out, "coverage-board-a.html"), encoding="utf-8").read()
    assert '<a href="coverage-board-a.html" aria-current="page">Coverage</a>' in coverage_a
    without_it = coverage_a.replace(
        '<a href="coverage-board-a.html" aria-current="page">Coverage</a>', ""
    )
    assert "aria-current" not in without_it


def test_sidebar_group_containing_current_page_is_pre_expanded(board_project):
    """Finding 7: the board group the reader is already standing inside opens
    pre-expanded (no click needed to see where you are); a sibling group with
    nothing to do with the current page stays collapsed."""
    project = _build_at(board_project)
    out = render.render_site(project)
    doc_a = open(os.path.join(out, "document-board-a.html"), encoding="utf-8").read()
    sidenav = doc_a.split('<div class="content">')[0]
    assert "<details open>\n      <summary>Board A</summary>" in sidenav
    assert "<details>\n      <summary>Board B</summary>" in sidenav


def test_sidebar_has_a_mobile_collapse_toggle_with_no_javascript(board_project):
    """Finding 7's narrow-viewport handling: the whole nav tree sits behind a
    checkbox-driven toggle (not a <details> wrapper -- verified directly
    against a real browser that a closed <details>'s non-summary content
    can't be forced open by CSS alone, since current browsers hide it via an
    internal, unstyleable mechanism) so a phone doesn't get several hundred
    pixels of expanded navigation before any real content. No <script> tag
    is involved in driving it -- the label/checkbox association is native
    HTML."""
    project = _build_at(board_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    sidenav = html.split('<div class="content">')[0]
    assert '<input type="checkbox" id="sidenav-toggle"' in sidenav
    assert '<label for="sidenav-toggle"' in sidenav
    app_js = open(
        os.path.join(REPO, "src", "refdes", "templates", "assets", "app.js"), encoding="utf-8"
    ).read()
    assert "sidenav" not in app_js  # native label/checkbox, no script drives it


def test_nav_tree_groups_pages_and_reports_under_their_board(board_project):
    pages = board_project / "pages"
    pages.mkdir()
    (pages / "power.md").write_text(
        "---\nboard: board-a\n---\n\n# Power overview\n", encoding="utf-8"
    )
    project = _build_at(board_project)
    tree = nav_mod.build_nav(project, dashboard_href="items.html")

    groups = {n.label: n for n in tree if not n.href}
    assert set(groups) == {"Board A", "Board B"}

    a_children = [c.label for c in groups["Board A"].children]
    assert a_children == ["Power overview", "Summary", "Coverage", "Full record"]
    # A board with no page of its own still gets a group -- just its reports.
    assert [c.label for c in groups["Board B"].children] == ["Summary", "Coverage", "Full record"]

    # The board-tagged page is not duplicated at the top level.
    root_labels = [n.label for n in tree if n.href]
    assert "Power overview" not in root_labels


def test_nav_group_appears_for_a_page_only_board_with_no_items(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site, pages: pages }\n"
        "boards:\n  power: { label: Power }\n"
        "types:\n  note: { prefix: NOTE }\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "overview.md").write_text(
        "---\nboard: power\n---\n\n# Power overview\n", encoding="utf-8"
    )
    project = _build_at(tmp_path)
    tree = nav_mod.build_nav(project, dashboard_href="index.html")
    groups = {n.label: n for n in tree if not n.href}
    assert set(groups) == {"Power"}
    assert [c.label for c in groups["Power"].children] == ["Power overview"]


def test_page_board_tag_must_be_registered(board_project):
    pages = board_project / "pages"
    pages.mkdir()
    (pages / "bad.md").write_text(
        "---\nboard: nonexistent\n---\n\n# Bad\n", encoding="utf-8"
    )
    project = _build_at(board_project)
    assert any(
        "nonexistent" in d.message and "not declared" in d.message
        for d in project.errors
    )
    page = next(p for p in project.pages if p.slug == "bad")
    assert page.board == ""


def test_rendered_nav_shows_board_groups(board_project):
    pages = board_project / "pages"
    pages.mkdir()
    (pages / "power.md").write_text(
        "---\nboard: board-a\n---\n\n# Power overview\n", encoding="utf-8"
    )
    project = _build_at(board_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "document.html"), encoding="utf-8").read()
    assert "<summary>Board A</summary>" in html
    assert 'href="power.html"' in html
    assert 'href="summary-board-a.html"' in html
    assert 'href="coverage-board-b.html"' in html


def test_rendered_nav_has_no_groups_without_boards_registered(unboarded_project):
    """Finding 7's explicit requirement: a project with no boards/workspaces
    registered must degrade to a flat list of links, not an empty rail or a
    single lonely disclosure -- nav.py's build_nav() already returns a flat
    root list with nothing to group in this case, so there is nothing for
    the sidebar to wrap in <details> at all."""
    project = _build_at(unboarded_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert "<details" not in html.split('<div class="content">')[0]
    assert '<a href="summary.html"' in html


# --------------------------------------------------------------- board drift


def test_first_build_records_the_manifest_without_warning(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    assert not project.board_moves
    manifest = boards_mod.load_manifest(project)
    assert manifest["boards"]["REQ-A-001"] == "board-a"


def test_moving_a_file_to_another_board_warns_but_does_not_error(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)  # records the manifest

    # Move REQ-A-001's file under board-b.
    (board_project / "items" / "board-a" / "r.yaml").rename(
        board_project / "items" / "board-b" / "moved.yaml"
    )

    project2 = _build_at(board_project)
    assert project2.items["REQ-A-001"].board == "board-b"
    assert ("REQ-A-001", "board-a", "board-b") in project2.board_moves
    assert not project2.errors
    assert any(
        "moved from board" in d.message and d.item_id == "REQ-A-001"
        for d in project2.warnings
    )
    # Not accepted: the manifest still remembers the old board.
    assert boards_mod.load_manifest(project2)["boards"]["REQ-A-001"] == "board-a"


def test_accept_board_move_updates_the_manifest_and_silences_future_builds(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)

    (board_project / "items" / "board-a" / "r.yaml").rename(
        board_project / "items" / "board-b" / "moved.yaml"
    )

    project2 = _build_at(board_project)
    build_mod.build(project2, seal_write=True, accept_board_move=True)
    assert boards_mod.load_manifest(project2)["boards"]["REQ-A-001"] == "board-b"

    project3 = _build_at(board_project)
    build_mod.build(project3, seal_write=True)
    assert not project3.board_moves


def test_audit_reports_board_moves(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    (board_project / "items" / "board-a" / "r.yaml").rename(
        board_project / "items" / "board-b" / "moved.yaml"
    )
    project2 = load_project(config_path=str(board_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)  # audit never writes
    assert ("REQ-A-001", "board-a", "board-b") in project2.board_moves


def test_a_move_off_the_registry_is_drift_too(board_project):
    """Finding 17: leaving the registry entirely is the drift most worth catching."""
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)  # records REQ-A-001 -> board-a

    # Rename board-a's folder to something the registry doesn't know -- same
    # repro shape as finding 16: the item now resolves to no board at all.
    (board_project / "items" / "board-a").rename(
        board_project / "items" / "board-a-renamed"
    )

    project2 = _build_at(board_project)
    assert project2.items["REQ-A-001"].board == ""
    assert ("REQ-A-001", "board-a", "") in project2.board_moves
    assert not project2.errors
    assert any(
        d.item_id == "REQ-A-001"
        and "was on board 'board-a' and now resolves to no board" in d.message
        for d in project2.warnings
    )
    # Not accepted: the manifest still remembers the old board.
    assert boards_mod.load_manifest(project2)["boards"]["REQ-A-001"] == "board-a"


def test_accept_board_move_off_the_registry_records_the_empty_board(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    (board_project / "items" / "board-a").rename(
        board_project / "items" / "board-a-renamed"
    )

    project2 = _build_at(board_project)
    build_mod.build(project2, seal_write=True, accept_board_move=True)
    assert boards_mod.load_manifest(project2)["boards"]["REQ-A-001"] == ""

    project3 = _build_at(board_project)
    assert not project3.board_moves  # drift silenced: recorded "" matches resolved ""


def test_audit_reports_a_board_move_off_the_registry(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    (board_project / "items" / "board-a").rename(
        board_project / "items" / "board-a-renamed"
    )
    project2 = load_project(config_path=str(board_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)  # audit never writes
    assert ("REQ-A-001", "board-a", "") in project2.board_moves


def test_item_that_never_had_a_board_does_not_trigger_drift(board_project):
    """REQ-S-001 lives in an unregistered folder from its very first build: it is
    never in the manifest, so verify() must stay silent about it. Finding 16's
    diagnostic covers it instead, and the two must not double up on one file."""
    seed = _build_at(board_project)
    build_mod.build(seed, seal_write=True)
    assert "REQ-S-001" not in boards_mod.load_manifest(seed)

    project = _build_at(board_project)
    assert not any(item_id == "REQ-S-001" for item_id, _, _ in project.board_moves)
    warned = [
        d for d in project.warnings
        if d.item_id == "REQ-S-001" and d.message.startswith("no board")
    ]
    assert len(warned) == 1


# ------------------------------------------------------------------ per-board seals

SEALED_BOARD_CONFIG = """\
site:
  title: "Seal test"
  out: _site
id:
  width: 3
boards:
  board-a:
    label: "Board A"
  board-b:
    label: "Board B"
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""


@pytest.fixture
def sealed_board_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(SEALED_BOARD_CONFIG, encoding="utf-8")

    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG-A }\n"
        "items:\n  - id: LOG-A-001\n    summary: first entry\n",
        encoding="utf-8",
    )

    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG-B }\n"
        "items:\n  - id: LOG-B-001\n    summary: first entry\n",
        encoding="utf-8",
    )

    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG-X }\n"
        "items:\n  - id: LOG-X-001\n    summary: first entry\n",
        encoding="utf-8",
    )
    return tmp_path


def test_seal_files_are_split_per_board(sealed_board_project):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    assert seal.load_seals(project, board="board-a") == {
        "LOG-A-001": project.items["LOG-A-001"].content_hash
    }
    assert seal.load_seals(project, board="board-b") == {
        "LOG-B-001": project.items["LOG-B-001"].content_hash
    }
    # No board: items keep using the base file, unchanged from before boards existed.
    assert seal.load_seals(project, board="") == {
        "LOG-X-001": project.items["LOG-X-001"].content_hash
    }
    assert os.path.isfile(seal.seal_path(project, "board-a"))
    assert os.path.isfile(seal.seal_path(project, "board-b"))


def test_reseal_scoped_to_one_board_only_accepts_that_boards_edits(sealed_board_project):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    project2 = _build_at(sealed_board_project)
    project2.items["LOG-A-001"].fields["summary"] = "edited"
    project2.items["LOG-B-001"].fields["summary"] = "edited"
    build_mod.compute_hashes(project2)
    seal.verify(project2, write=True, reseal="board-a")

    assert "LOG-A-001" not in project2.seal_violations
    assert "LOG-B-001" in project2.seal_violations
    assert (
        seal.load_seals(project2, board="board-a")["LOG-A-001"]
        == project2.items["LOG-A-001"].content_hash
    )
    # board-b's file is untouched: its edit was not accepted.
    assert (
        seal.load_seals(project2, board="board-b")["LOG-B-001"]
        != project2.items["LOG-B-001"].content_hash
    )


def test_reseal_bare_accepts_every_boards_edits(sealed_board_project):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    project2 = _build_at(sealed_board_project)
    project2.items["LOG-A-001"].fields["summary"] = "edited"
    project2.items["LOG-B-001"].fields["summary"] = "edited"
    build_mod.compute_hashes(project2)
    seal.verify(project2, write=True, reseal=seal.RESEAL_ALL)

    assert not project2.seal_violations
    assert (
        seal.load_seals(project2, board="board-a")["LOG-A-001"]
        == project2.items["LOG-A-001"].content_hash
    )
    assert (
        seal.load_seals(project2, board="board-b")["LOG-B-001"]
        == project2.items["LOG-B-001"].content_hash
    )


def test_check_finds_legacy_seal_history_without_writing(sealed_board_project):
    """A project newly adopting boards: may still have entries sealed in the old,
    pre-split single file. `refdes check` (write=False) must recognize that
    history via lookback -- not treat the entry as new, not error -- and must
    not create or touch any seal file while doing it."""
    project = _build_at(sealed_board_project)
    legacy_hash = project.items["LOG-A-001"].content_hash
    seal.save_seals(project, {"LOG-A-001": legacy_hash}, board="")
    assert not os.path.isfile(seal.seal_path(project, "board-a"))

    project2 = _build_at(sealed_board_project)  # build() defaults to seal_write=False
    assert not project2.seal_violations
    assert not os.path.isfile(seal.seal_path(project2, "board-a"))
    assert seal.load_seals(project2, board="") == {"LOG-A-001": legacy_hash}


def test_check_catches_an_edit_against_legacy_seal_history(sealed_board_project):
    """The lookback must actually compare, not just silence every legacy id."""
    project = _build_at(sealed_board_project)
    seal.save_seals(project, {"LOG-A-001": "0000000000000000"}, board="")

    project2 = _build_at(sealed_board_project)
    assert "LOG-A-001" in project2.seal_violations


def test_build_migrates_legacy_seal_entries_into_the_boards_own_file(sealed_board_project):
    project = _build_at(sealed_board_project)
    legacy_hash = project.items["LOG-A-001"].content_hash
    seal.save_seals(project, {"LOG-A-001": legacy_hash}, board="")

    # A fresh project, built once with seal_write=True -- a real `refdes build`.
    project2 = load_project(config_path=str(sealed_board_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2, seal_write=True)

    assert seal.load_seals(project2, board="board-a") == {"LOG-A-001": legacy_hash}
    assert "LOG-A-001" not in seal.load_seals(project2, board="")


def _load_and_build(root, **kwargs):
    """Load and build in one pass with the given seal flags -- unlike
    `_build_at`, which always runs a default (no-reseal) build first, and so
    would record a violation before the caller's own flags ever applied."""
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, **kwargs)
    return project


def _empty_the_board_log(root, board, prefix):
    (root / "items" / board / "log.yaml").write_text(
        "defaults: { type: log, prefix: %s }\nitems: []\n" % prefix, encoding="utf-8"
    )


def test_deleting_a_sealed_entry_is_an_error_not_silent(sealed_board_project):
    """Editing a sealed entry was already a build error; deleting one outright
    was not detected at all -- a clean build, a clean audit, and an orphaned
    hash left behind in the seal file. Deletion is the louder half of the same
    tamper-evidence question, so it is reported the same way now."""
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    _empty_the_board_log(sealed_board_project, "board-a", "LOG-A")

    project2 = _load_and_build(sealed_board_project, seal_write=False, reseal=False)
    assert any(
        "LOG-A-001" in d.message and "no item with that id" in d.message
        for d in project2.errors
    ), [str(d) for d in project2.errors]
    # A read-only check never mutates seal storage while reporting it.
    assert "LOG-A-001" in seal.load_seals(project2, board="board-a")


def test_deleting_a_sealed_entry_is_accepted_with_reseal(sealed_board_project):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    _empty_the_board_log(sealed_board_project, "board-a", "LOG-A")

    project2 = _load_and_build(sealed_board_project, seal_write=True, reseal="board-a")
    assert not project2.errors, [str(d) for d in project2.errors]
    assert any("no longer in the project" in d.message for d in project2.diagnostics)
    assert "LOG-A-001" not in seal.load_seals(project2, board="board-a")
    # Scoping holds: another board's seals are untouched.
    assert "LOG-B-001" in seal.load_seals(project2, board="board-b")


def test_reseal_scoped_to_one_board_does_not_accept_another_boards_deletion(
    sealed_board_project,
):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    _empty_the_board_log(sealed_board_project, "board-b", "LOG-B")

    project2 = _load_and_build(sealed_board_project, seal_write=True, reseal="board-a")
    assert any(
        "LOG-B-001" in d.message and "no item with that id" in d.message
        for d in project2.errors
    ), [str(d) for d in project2.errors]
    assert "LOG-B-001" in seal.load_seals(project2, board="board-b")


def test_a_renumbered_entry_claimed_by_former_ids_is_not_a_deletion(tmp_path):
    """`former_ids:` is exactly the mechanism for an id retired in favour of a
    new one, so its old seal entry has not been deleted -- the entry is still
    in the project, under a new name."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "id: { width: 3 }\n"
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    fields:\n"
        "      summary: { type: text, required: true }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG }\n"
        "items:\n  - id: LOG-001\n    summary: first entry\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    build_mod.build(project, seal_write=True)

    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG }\n"
        "items:\n  - id: LOG-009\n    former_ids: [LOG-001]\n    summary: first entry\n",
        encoding="utf-8",
    )
    project2 = _load_and_build(tmp_path, seal_write=False, reseal=False)
    assert not any("no item with that id" in d.message for d in project2.errors), [
        str(d) for d in project2.errors
    ]


def test_seal_storage_is_a_single_file_with_no_boards_registered(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  log: { prefix: LOG, append_only: true, "
        "fields: { summary: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG }\n"
        "items:\n  - id: LOG-001\n    summary: first entry\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    build_mod.build(project, seal_write=True)

    names = os.listdir(tmp_path / ".refdes")
    assert "log-seal.yaml" in names
    assert not any(n.startswith("log-seal-") for n in names)
    assert seal.load_seals(project, board="") == {
        "LOG-001": project.items["LOG-001"].content_hash
    }


def test_cli_reseal_rejects_unknown_board(sealed_board_project, capsys):
    status = cli_mod.main(
        ["-c", str(sealed_board_project / "refdes.yaml"), "build", "--reseal", "nonexistent"]
    )
    assert status != 0
    captured = capsys.readouterr()
    assert "not a board declared" in captured.err


def test_cli_build_reseal_scoped_to_board(sealed_board_project, capsys):
    assert cli_mod.main(["-c", str(sealed_board_project / "refdes.yaml"), "build"]) == 0

    log_a = sealed_board_project / "items" / "board-a" / "log.yaml"
    log_a.write_text(
        log_a.read_text(encoding="utf-8").replace("first entry", "edited entry"),
        encoding="utf-8",
    )

    status = cli_mod.main(
        ["-c", str(sealed_board_project / "refdes.yaml"), "build", "--reseal", "board-a"]
    )
    assert status == 0


# ------------------------------------------------------------------- check --board

CROSS_BOARD_CONFIG = """\
site: { title: "Cross-board Test", out: _site }
id: { width: 3 }
boards:
  board-a: { label: "Board A" }
  board-b: { label: "Board B" }
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
"""


@pytest.fixture
def cross_board_project(tmp_path):
    """A decision on board-b that satisfies a requirement on board-a -- the case
    that breaks if `check --board` ever scopes the file walk instead of just the
    report: board-b's own folder never mentions REQ-A-001 at all.
    """
    (tmp_path / "refdes.yaml").write_text(CROSS_BOARD_CONFIG, encoding="utf-8")
    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "req.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: Owned by board A.\n---\n",
        encoding="utf-8",
    )
    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "dec.md").write_text(
        "---\nid: DEC-B-001\ntype: decision\ntitle: Board B decision.\n"
        "satisfies: [REQ-A-001]\n---\n",
        encoding="utf-8",
    )
    return tmp_path


def test_check_board_scope_does_not_affect_link_resolution(cross_board_project):
    project = _build_at(cross_board_project)
    assert not project.errors
    assert project.items["DEC-B-001"].links["satisfies"] == ["REQ-A-001"]
    assert "DEC-B-001" in project.items["REQ-A-001"].backlinks.get("satisfied_by", [])


def test_cli_check_board_scopes_the_report_not_the_link_walk(cross_board_project, capsys):
    """`--board board-b` must still resolve REQ-A-001 -- it just doesn't get
    reported, since board-b's own item count is 1 (DEC-B-001 only)."""
    status = cli_mod.main(
        ["-c", str(cross_board_project / "refdes.yaml"), "check", "--board", "board-b"]
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "1 items, 0 errors" in out


def test_check_board_filters_diagnostics_to_that_board(board_project, capsys):
    status = cli_mod.main(
        ["-c", str(board_project / "refdes.yaml"), "check", "--board", "board-b"]
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "REQ-WRONG-001" in out  # board-b's own token-mismatch warning
    assert "REQ-S-001" not in out  # unboarded item's warning, filtered out
    # +1 over the item-scoped warnings: the project-level, once-per-type
    # 'coverable:' fallback nudge (this fixture's schema predates that flag).
    assert "2 items, 0 errors, 3 warnings" in out


def test_check_board_always_shows_project_level_diagnostics(board_project, capsys):
    """A diagnostic with no item_id isn't attributable to any one board, so
    --board must never hide it -- here, the project-wide 'no coverage' summary
    warning that `check` always emits for this fixture's uncovered items."""
    status = cli_mod.main(
        ["-c", str(board_project / "refdes.yaml"), "check", "--board", "board-a"]
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "no coverage" in out


def test_check_without_board_flag_is_unaffected_by_the_feature(board_project, capsys):
    status = cli_mod.main(["-c", str(board_project / "refdes.yaml"), "check"])
    out = capsys.readouterr().out
    assert "REQ-WRONG-001" in out
    assert "REQ-S-001" in out
    # +1 over the item-scoped warnings: the project-level, once-per-type
    # 'coverable:' fallback nudge (this fixture's schema predates that flag).
    assert "5 items, 0 errors, 5 warnings" in out


def test_cli_check_board_rejects_unknown_board(board_project, capsys):
    status = cli_mod.main(
        ["-c", str(board_project / "refdes.yaml"), "check", "--board", "bord-a"]
    )
    assert status == 1
    err = capsys.readouterr().err
    assert "not a board declared" in err
    assert "board-a" in err  # difflib suggestion


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
    assert "violates BND-THM-001" in " ".join(d.message for d in project.errors)


def _io_check_project(tmp_path, *, tolerance):
    """A single toleranced (or exact) check violating a `<=` constraint."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items"
    items.mkdir()
    (items / "io.yaml").write_text(
        "defaults: { type: bound }\n"
        "items:\n"
        "  - id: BND-IO-004\n"
        "    title: Input current budget\n"
        '    limit: "<= 600 mA"\n',
        encoding="utf-8",
    )
    calc_line = "CLIM : A = 0.6061 A ± 15%" if tolerance else "CLIM : A = 0.697 A"
    (items / "dec-io-002.md").write_text(
        "---\n"
        "id: DEC-IO-002\n"
        "type: decision\n"
        "title: Input current draw\n"
        "status: accepted\n"
        "constrained_by: [BND-IO-004]\n"
        "checks:\n"
        "  - value: CLIM\n"
        "    against: BND-IO-004\n"
        "---\n\n"
        f"```calc\n{calc_line}\n```\n",
        encoding="utf-8",
    )
    return _build_at(tmp_path)


def test_check_error_reports_worst_case_with_nominal_in_parens(tmp_path):
    """A toleranced breach must report its worst-case bound, not just the nominal.

    Reporting only the nominal (0.6061 A) makes a 97 mA / 16% worst-case breach
    read as a 6 mA overshoot. The nominal stays in a parenthetical because it is
    the number a reader recognises from the calc block.
    """
    project = _io_check_project(tmp_path, tolerance=True)
    check = project.items["DEC-IO-002"].checks[0]
    assert check.ok is False
    message = next(d.message for d in project.errors if "BND-IO-004" in d.message)
    assert (
        "CLIM violates BND-IO-004: worst case 0.697 A vs <= 600 mA (nominal 0.6061 A)"
        in message
    )


def test_check_error_omits_nominal_when_worst_case_equals_it(tmp_path):
    """No tolerance means worst case and nominal are the same number.

    The parenthetical would be pure noise here, so it must not appear.
    """
    project = _io_check_project(tmp_path, tolerance=False)
    check = project.items["DEC-IO-002"].checks[0]
    assert check.ok is False
    message = next(d.message for d in project.errors if "BND-IO-004" in d.message)
    assert "CLIM violates BND-IO-004: worst case 0.697 A vs <= 600 mA" in message
    assert "nominal" not in message


CHECK_SEVERITY_SCHEMA = """\
site: {title: "Check Severity Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
types:
  constraint:
    prefix: CON
    label: Constraint
    fields:
      title: { type: text, required: true, on_change: invalidate }
      limit: { type: limit, required: true, on_change: invalidate }
    body: { on_change: invalidate }
  option:
    prefix: OPT
    label: Option
    check_severity: info
    fields:
      title: { type: text, required: true, on_change: invalidate }
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    label: Decision
    fields:
      title: { type: text, required: true, on_change: invalidate }
    body: { on_change: invalidate }
"""


def _check_severity_project(tmp_path, *, item_type, item_id, prefix, checks_extra=""):
    """One item of `item_type`, with a failing check against CON-IO-004."""
    (tmp_path / "refdes.yaml").write_text(CHECK_SEVERITY_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults: { type: constraint }\n"
        "items:\n"
        "  - id: CON-IO-004\n"
        "    title: Input current budget\n"
        '    limit: "<= 600 mA"\n',
        encoding="utf-8",
    )
    (items / f"{prefix.lower()}.md").write_text(
        "---\n"
        f"id: {item_id}\n"
        f"type: {item_type}\n"
        "title: Candidate under evaluation\n"
        "checks:\n"
        "  - value: CLIM\n"
        "    against: CON-IO-004\n"
        f"{checks_extra}"
        "---\n\n"
        "```calc\nCLIM : A = 0.697 A\n```\n",
        encoding="utf-8",
    )
    return _build_at(tmp_path)


def test_check_severity_info_does_not_error_or_block_the_build(tmp_path):
    """finding 18: a candidate type can mark failing checks as findings, not defects."""
    project = _check_severity_project(
        tmp_path, item_type="option", item_id="OPT-IO-001", prefix="opt"
    )
    check = project.items["OPT-IO-001"].checks[0]
    assert check.ok is False  # the Checks table must still show the failure
    assert not project.errors
    info_messages = [d.message for d in project.infos]
    assert any("CLIM violates CON-IO-004" in m for m in info_messages)


def test_check_severity_defaults_to_error_when_unconfigured(tmp_path):
    """Back-compat: a type with no check_severity: still errors, same as before this existed."""
    project = _check_severity_project(
        tmp_path, item_type="decision", item_id="DEC-IO-001", prefix="dec"
    )
    check = project.items["DEC-IO-001"].checks[0]
    assert check.ok is False
    assert any("CLIM violates CON-IO-004" in d.message for d in project.errors)
    assert not project.infos


def test_check_severity_rejects_an_unrecognized_value(tmp_path):
    bad_schema = CHECK_SEVERITY_SCHEMA.replace(
        "check_severity: info", "check_severity: nonsense"
    )
    (tmp_path / "refdes.yaml").write_text(bad_schema, encoding="utf-8")
    with pytest.raises(SchemaError, match="check_severity"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_check_severity_info_still_errors_on_a_malformed_check_entry(tmp_path):
    """Only a failing (evaluated) check is downgraded -- a broken checks: entry is
    always an authoring mistake, regardless of the item's type."""
    project = _check_severity_project(
        tmp_path,
        item_type="option",
        item_id="OPT-IO-002",
        prefix="opt",
        checks_extra="  - value: CLIM\n    against: CON-DOES-NOT-EXIST\n",
    )
    assert any("does not exist" in d.message for d in project.errors)


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

    # Linked to a test, but that test is only 'planned', not 'passing' -- the
    # standard's test.verifying_statuses: [passing] means a merely-linked test
    # doesn't count as having verified anything yet.
    assert cov["REQ-PWR-002"].stage == "satisfied"
    assert cov["REQ-PWR-002"].verified_by == []

    # requirement.coverable_statuses: [active] excludes draft items from
    # coverage entirely -- REQ-PWR-004 (draft) isn't tracked at all.
    assert "REQ-PWR-004" not in cov

    # Written down and never touched again.
    assert cov["BND-THM-002"].stage == "open"

    # A log entry alone counts as addressed, not satisfied.
    assert cov["BND-THM-001"].stage == "addressed"
    assert "LOG-A-005" in cov["BND-THM-001"].addressed_by


def test_outstanding_work_is_aggregated_into_summary_lines():
    """The real project's own coverage gaps (issue #3, finding 8) roll up into
    two summary lines instead of one warning per requirement."""
    project = _project()

    open_count = sum(1 for c in project.coverage.values() if c.stage == "open")
    unverified_count = sum(
        1
        for item_id, c in project.coverage.items()
        if c.stage != "open"
        and c.stage != "claimed"
        and not c.verified_by
        and project.items[item_id].type == "requirement"
    )
    assert open_count > 0 and unverified_count > 0  # otherwise this proves nothing

    aggregate_messages = {d.message for d in project.warnings if d.item_id is None}
    assert f"{open_count} item(s) with no coverage — see coverage.html" in aggregate_messages
    assert (
        f"{unverified_count} requirement(s) satisfied but not verified — see coverage.html"
        in aggregate_messages
    )

    # Neither routine class leaves a per-item warning behind.
    assert not any(d.item_id == "REQ-PWR-003" for d in project.warnings)
    assert not any(d.item_id == "REQ-PWR-004" for d in project.warnings)
    assert not any(d.item_id == "REQ-PWR-001" for d in project.warnings)  # verified


def test_log_entries_are_sealed_and_edits_are_caught():
    project = _project()
    entry = project.items["LOG-A-003"]
    # Read the seal from whichever board the entry resolves to, not from the
    # base file: seals are split per board, so hard-coding board="" only
    # happened to work while this project's log entries resolved to no board
    # at all -- an incidental fact about where one file sat, not a property
    # of sealing.
    seals = seal.load_seals(project, board=entry.board)
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


# ------------------------------------------------------------------- citations

CITATION_SCHEMA = """\
site: {title: "Citation Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title:      { type: text, required: true, on_change: invalidate }
      datasheets: { type: citations, on_change: invalidate }
"""

CITATION_ITEM = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: Buck converter
    datasheets:
      - url: https://example.com/ds.pdf
        rev: C
        page: "14"
        part_number: TPS62913
        vendor: true
"""


@pytest.fixture
def citation_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(CITATION_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(CITATION_ITEM, encoding="utf-8")
    return tmp_path


def _cite_build(root, **kw):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, **kw)
    return project


def _write_citation_lockfile(root, records):
    path = root / ".refdes" / "citations.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"citations": records}), encoding="utf-8")


def _write_vendor_blob(root, sha256, ext, data):
    path = root / ".refdes" / "vendor" / f"{sha256}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _fake_fetcher(data: bytes = b"%PDF-1.4 fake"):
    def fetcher(url):
        return data

    return fetcher


# --------------------------------------------------------- structural validation


def test_citations_field_must_be_a_list(tmp_path):
    (tmp_path / "refdes.yaml").write_text(CITATION_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n    datasheets: not-a-list\n",
        encoding="utf-8",
    )
    project = _cite_build(tmp_path)
    assert any("must be a list of citation entries" in d.message for d in project.errors)


def test_citation_entry_without_url_is_an_error(tmp_path):
    (tmp_path / "refdes.yaml").write_text(CITATION_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n    datasheets:\n      - rev: C\n",
        encoding="utf-8",
    )
    project = _cite_build(tmp_path)
    assert any("each citation needs a 'url'" in d.message for d in project.errors)


# ---------------------------------------------------------------------- verify


def test_unpinned_citation_is_info_by_default(citation_project):
    """Routine until `refdes fetch` runs (issue #3, finding 8) -- default-hidden
    info, not a warning that competes with actionable diagnostics."""
    project = _cite_build(citation_project)
    status = project.items["CMP-001"].citations[0]
    assert status.state == "unpinned"
    assert any("has no fetched record" in d.message for d in project.infos)
    assert not any("has no fetched record" in d.message for d in project.warnings)
    assert not any("has no fetched record" in d.message for d in project.errors)


def test_require_citations_promotes_unpinned_to_error(citation_project):
    project = _cite_build(citation_project, require_citations=True)
    assert any("has no fetched record" in d.message for d in project.errors)


def test_hash_only_citation_is_ok_with_no_local_file_needed(citation_project):
    (citation_project / "items" / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n"
        "    datasheets:\n      - url: https://example.com/ds.pdf\n        vendor: false\n",
        encoding="utf-8",
    )
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "abc123", "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = _cite_build(citation_project)
    status = project.items["CMP-001"].citations[0]
    assert status.state == "ok"
    assert status.local_path == ""
    assert not project.warnings and not project.errors


def _enable_publish_datasheets(root):
    (root / "refdes-project.yaml").write_text("publish_datasheets: true\n", encoding="utf-8")


def test_vendored_citation_ok_when_blob_matches(citation_project):
    """publish_datasheets defaults off, so a vendored citation resolves 'ok' but
    is not exposed as a local copy -- the rendered link stays upstream-only."""
    data = b"%PDF-1.4 real bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    project = _cite_build(citation_project)
    status = project.items["CMP-001"].citations[0]
    assert status.state == "ok"
    assert status.local_path == ""
    assert not project.errors


def test_vendored_citation_published_when_publish_datasheets_is_on(citation_project):
    data = b"%PDF-1.4 real bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    _enable_publish_datasheets(citation_project)
    project = _cite_build(citation_project)
    status = project.items["CMP-001"].citations[0]
    assert status.state == "ok"
    assert status.local_path == f"datasheets/{sha}.pdf"  # flattened, not .refdes/vendor/...
    assert not project.errors


def test_cache_missing_and_hash_mismatch_are_unaffected_by_publish_datasheets(citation_project):
    """Local-cache integrity checks are unconditional -- publishing is a separate
    concern from whether the vendored copy is trustworthy."""
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "deadbeef", "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _enable_publish_datasheets(citation_project)
    project = _cite_build(citation_project)
    status = project.items["CMP-001"].citations[0]
    assert status.state == "cache_missing"
    assert status.local_path == ""


def test_vendored_citation_cache_missing_when_blob_absent(citation_project):
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "deadbeef", "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    project = _cite_build(citation_project)
    status = project.items["CMP-001"].citations[0]
    assert status.state == "cache_missing"
    assert any("is missing at" in d.message for d in project.warnings)


def test_vendored_citation_hash_mismatch_is_always_an_error(citation_project):
    """Never soft-failed: a corrupted local cache is an error even without --require-citations."""
    data = b"%PDF-1.4 real bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", b"tampered bytes")
    project = _cite_build(citation_project)
    status = project.items["CMP-001"].citations[0]
    assert status.state == "hash_mismatch"
    assert any("tampered or corrupt" in d.message for d in project.errors)


# ------------------------------------------------------------- items_json export


def _citation_entry(payload, item_id="CMP-001"):
    return next(i for i in payload["items"] if i["id"] == item_id)


def test_items_json_citations_unpinned(citation_project):
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    status = _citation_entry(payload)["citations"]["datasheets"][0]
    assert status["state"] == "unpinned"
    assert status["pinned"] is False
    assert status["vendored"] is False
    assert status["sha256"] == ""
    assert status["fetched"] == ""
    assert status["local_path"] == ""
    assert "has no fetched record" in status["detail"]
    # authored intent stays in `fields`, untouched by resolution
    assert _citation_entry(payload)["fields"]["datasheets"][0] == {
        "url": "https://example.com/ds.pdf",
        "rev": "C",
        "page": "14",
        "part_number": "TPS62913",
        "vendor": True,
    }


def test_items_json_citations_hash_only_pinned_not_vendored(citation_project):
    (citation_project / "items" / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n"
        "    datasheets:\n      - url: https://example.com/ds.pdf\n        vendor: false\n",
        encoding="utf-8",
    )
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "abc123", "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    status = _citation_entry(payload)["citations"]["datasheets"][0]
    assert status["state"] == "ok"
    assert status["pinned"] is True
    assert status["vendored"] is False
    assert status["sha256"] == "abc123"
    assert status["fetched"] == "2026-01-01T00:00:00Z"
    assert status["local_path"] == ""


def test_items_json_citations_vendored(citation_project):
    data = b"%PDF-1.4 real bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    status = _citation_entry(payload)["citations"]["datasheets"][0]
    assert status["state"] == "ok"
    assert status["pinned"] is True
    assert status["vendored"] is True
    assert status["sha256"] == sha
    assert status["local_path"] == ""  # publish_datasheets defaults off


def test_items_json_citations_cache_missing(citation_project):
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "deadbeef", "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    status = _citation_entry(payload)["citations"]["datasheets"][0]
    assert status["state"] == "cache_missing"
    assert status["pinned"] is True
    assert status["vendored"] is True
    assert status["sha256"] == "deadbeef"
    assert status["local_path"] == ""


def test_items_json_citations_empty_for_items_without_citation_fields(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    payload = render.items_json(project)
    assert payload["items"][0]["citations"] == {}


def test_items_json_types_expose_citations_field_type(citation_project):
    """The field-type/schema section is how a consumer discovers `datasheets`
    is a `citations` field in the first place -- pre-existing, unrelated to
    citation resolution, but this is the mechanism `citations` above pairs with.
    """
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    assert payload["types"]["component"]["fields"]["datasheets"]["type"] == "citations"


INCONSISTENT_VENDOR_ITEMS = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: A
    datasheets:
      - url: https://example.com/ds.pdf
        vendor: true
  - id: CMP-002
    title: B
    datasheets:
      - url: https://example.com/ds.pdf
        vendor: false
"""


def test_inconsistent_vendor_flags_across_citers_warns(tmp_path):
    (tmp_path / "refdes.yaml").write_text(CITATION_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(INCONSISTENT_VENDOR_ITEMS, encoding="utf-8")
    project = _cite_build(tmp_path)
    assert any("inconsistent vendor:" in d.message for d in project.warnings)


def test_content_hash_unaffected_by_lockfile_changes(citation_project):
    """Re-fetching a datasheet must never retroactively flag an item as edited."""
    project1 = _cite_build(citation_project)
    hash1 = project1.items["CMP-001"].content_hash

    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "abc", "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project2 = _cite_build(citation_project)
    hash2 = project2.items["CMP-001"].content_hash
    assert hash1 == hash2


# ----------------------------------------------------------------------- fetch


def test_fetch_all_pins_every_cited_url(citation_project):
    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    results = citations_mod.fetch_all(project, fetcher=_fake_fetcher())
    assert len(results) == 1
    assert results[0].url == "https://example.com/ds.pdf"
    assert results[0].vendored is True  # the one citer declares vendor: true
    lockfile = citations_mod.load_lockfile(project)
    assert "https://example.com/ds.pdf" in lockfile
    blob = citations_mod.vendor_path(project, results[0].sha256, results[0].url)
    assert os.path.isfile(blob)


TWO_URL_ITEMS = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: A
    datasheets: [{url: "https://example.com/a.pdf"}]
  - id: CMP-002
    title: B
    datasheets: [{url: "https://example.com/b.pdf"}]
"""


@pytest.fixture
def two_url_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(CITATION_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(TWO_URL_ITEMS, encoding="utf-8")
    return tmp_path


def test_fetch_scoped_to_item(two_url_project):
    project = load_project(config_path=str(two_url_project / "refdes.yaml"))
    parse.load_items(project)
    results = citations_mod.fetch_all(project, item_id="CMP-001", fetcher=_fake_fetcher())
    assert [r.url for r in results] == ["https://example.com/a.pdf"]


def test_fetch_scoped_to_url(two_url_project):
    project = load_project(config_path=str(two_url_project / "refdes.yaml"))
    parse.load_items(project)
    results = citations_mod.fetch_all(
        project, url="https://example.com/b.pdf", fetcher=_fake_fetcher()
    )
    assert [r.url for r in results] == ["https://example.com/b.pdf"]


def test_fetch_unknown_item_raises(citation_project):
    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    with pytest.raises(citations_mod.CitationError, match="CMP-999"):
        citations_mod.fetch_all(project, item_id="CMP-999", fetcher=_fake_fetcher())


def test_fetch_url_not_cited_raises(citation_project):
    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    with pytest.raises(citations_mod.CitationError, match="cites"):
        citations_mod.fetch_all(
            project, url="https://example.com/nope.pdf", fetcher=_fake_fetcher()
        )


def test_fetch_skips_already_pinned_unless_update(citation_project):
    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)

    first = citations_mod.fetch_all(project, fetcher=_fake_fetcher(b"version one"))
    assert first[0].skipped is False

    second = citations_mod.fetch_all(project, fetcher=_fake_fetcher(b"version two"))
    assert second[0].skipped is True
    assert second[0].sha256 == first[0].sha256

    third = citations_mod.fetch_all(project, update=True, fetcher=_fake_fetcher(b"version two"))
    assert third[0].skipped is False
    assert third[0].sha256 != first[0].sha256


def test_fetch_records_error_without_raising(citation_project):
    def bad_fetcher(url):
        raise OSError("network unreachable")

    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    results = citations_mod.fetch_all(project, fetcher=bad_fetcher)
    assert results[0].error == "network unreachable"
    assert citations_mod.load_lockfile(project) == {}  # nothing written on failure


# ----------------------------------------------------------------------- drift


def test_refresh_detects_drift(citation_project):
    sha_old = hashlib.sha256(b"old bytes").hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha_old, "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    drift = citations_mod.refresh(project, fetcher=_fake_fetcher(b"new bytes"))
    assert len(drift) == 1
    assert drift[0].url == "https://example.com/ds.pdf"
    assert drift[0].pinned_sha256 == sha_old
    assert drift[0].citers == ["CMP-001"]


def test_refresh_no_drift_when_hash_matches(citation_project):
    data = b"same bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    assert citations_mod.refresh(project, fetcher=_fake_fetcher(data)) == []


def test_refresh_skips_unpinned(citation_project):
    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    assert citations_mod.refresh(project, fetcher=_fake_fetcher()) == []


def test_refresh_writes_nothing(citation_project):
    sha_old = hashlib.sha256(b"old bytes").hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha_old, "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    citations_mod.refresh(project, fetcher=_fake_fetcher(b"new bytes"))
    assert citations_mod.load_lockfile(project)["https://example.com/ds.pdf"]["sha256"] == sha_old


def test_refresh_warns_on_fetch_failure_not_drift(citation_project):
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "abc", "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )

    def bad_fetcher(url):
        raise OSError("timeout")

    project = load_project(config_path=str(citation_project / "refdes.yaml"))
    parse.load_items(project)
    drift = citations_mod.refresh(project, fetcher=bad_fetcher)
    assert drift == []
    assert any("could not refresh" in d.message for d in project.warnings)


# ------------------------------------------------------------------------- cli


def test_cli_fetch_pins_via_monkeypatched_network(citation_project, monkeypatch, capsys):
    monkeypatch.setattr(citations_mod, "fetch_bytes", lambda url, timeout=30.0: b"%PDF-1.4 x")
    code = cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "fetch"])
    assert code == 0
    out = capsys.readouterr().out
    assert "fetched" in out
    assert "1 citation(s) processed, 0 failed" in out


def test_cli_fetch_unknown_item_returns_nonzero(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "fetch", "--item", "CMP-999"])
    assert code == 1
    assert "CMP-999" in capsys.readouterr().err


def test_cli_check_refresh_detects_drift(citation_project, monkeypatch, capsys):
    sha_old = hashlib.sha256(b"old").hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha_old, "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    monkeypatch.setattr(citations_mod, "fetch_bytes", lambda url, timeout=30.0: b"new bytes")
    code = cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "check", "--refresh"])
    assert code == 1
    assert "drifted" in capsys.readouterr().out


def test_cli_check_without_refresh_never_touches_the_network(citation_project, monkeypatch):
    def boom(url, timeout=30.0):
        raise AssertionError("check must not touch the network without --refresh")

    monkeypatch.setattr(citations_mod, "fetch_bytes", boom)
    # An unpinned citation is only a warning, so plain `check` still exits 0.
    assert cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "check"]) == 0


def test_cli_build_require_citations_promotes_to_error(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "build", "--require-citations"])
    assert code == 1
    assert "has no fetched record" in capsys.readouterr().err


def test_cli_build_without_require_citations_still_succeeds(citation_project):
    assert cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "build"]) == 0


def test_cli_check_hides_info_diagnostics_by_default(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "check"])
    assert code == 0
    out = capsys.readouterr().out
    assert "has no fetched record" not in out
    assert ", 0 info" not in out  # summary line unchanged unless --verbose


def test_cli_check_verbose_shows_info_diagnostics(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "check", "--verbose"])
    assert code == 0
    out = capsys.readouterr().out
    assert "INFO" in out
    assert "has no fetched record" in out
    assert ", 1 info" in out


def test_cli_audit_lists_citations(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes.yaml"), "audit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Citations:" in out
    assert "https://example.com/ds.pdf" in out
    assert "CMP-001" in out


# -------------------------------------------------------------------- rendering


def test_references_page_lists_citations_grouped_by_url(citation_project):
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "references.html"), encoding="utf-8").read()
    assert "https://example.com/ds.pdf" in html
    assert 'data-ref="CMP-001"' in html
    assert "pill-warn" in html  # unpinned


def test_item_page_excludes_citations_field_from_generic_table(citation_project):
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert "<h2>Citations</h2>" in html
    assert "<th>datasheets</th>" not in html


def test_reserved_name_guard_covers_references(citation_project):
    pages = citation_project / "pages"
    pages.mkdir()
    (pages / "references.md").write_text("# Nope\n", encoding="utf-8")
    project = _cite_build(citation_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)


def test_vendored_citation_pdf_is_not_published_by_default(citation_project):
    """publish_datasheets defaults off: nothing is copied into _site/, and the
    rendered citation links upstream only -- no 'local copy' link."""
    data = b"%PDF-1.4 vendored bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    project = _cite_build(citation_project)
    out = render.render_site(project)
    assert not os.path.isdir(os.path.join(out, "assets", "datasheets"))
    assert not os.path.isdir(os.path.join(out, "assets", ".refdes"))
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert "https://example.com/ds.pdf" in html
    assert "local copy" not in html


def test_vendored_citation_pdf_is_copied_into_the_site_when_published(citation_project):
    data = b"%PDF-1.4 vendored bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    _enable_publish_datasheets(citation_project)
    project = _cite_build(citation_project)
    out = render.render_site(project)
    copied = os.path.join(out, "assets", "datasheets", f"{sha}.pdf")
    assert os.path.isfile(copied)
    assert open(copied, "rb").read() == data
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert f"assets/datasheets/{sha}.pdf" in html
    assert "local copy" in html


def test_nav_shows_references_link_only_when_citations_exist(citation_project):
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert 'href="references.html"' in html


def test_no_references_link_without_any_citations(coverage_project):
    out = _build_and_render(coverage_project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert 'href="references.html"' not in html
    assert os.path.isfile(os.path.join(out, "references.html"))


BOARD_CITATION_SCHEMA = """\
site:
  title: "Board Citation Test"
  out: _site
boards:
  board-a: { label: "Board A" }
  board-b: { label: "Board B" }
types:
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true }
      datasheets: { type: citations }
"""


@pytest.fixture
def board_citation_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BOARD_CITATION_SCHEMA, encoding="utf-8")
    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "c.yaml").write_text(
        "defaults: {type: component}\n"
        'items:\n  - id: CMP-A-001\n    title: A\n    datasheets: [{url: "https://example.com/a.pdf"}]\n',
        encoding="utf-8",
    )
    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "c.yaml").write_text(
        "defaults: {type: component}\n"
        'items:\n  - id: CMP-B-001\n    title: B\n    datasheets: [{url: "https://example.com/b.pdf"}]\n',
        encoding="utf-8",
    )
    return tmp_path


def test_per_board_references_are_scoped(board_citation_project):
    project = _cite_build(board_citation_project)
    out = render.render_site(project)
    ref_a = open(os.path.join(out, "references-board-a.html"), encoding="utf-8").read()
    ref_b = open(os.path.join(out, "references-board-b.html"), encoding="utf-8").read()
    assert "example.com/a.pdf" in ref_a and "example.com/b.pdf" not in ref_a
    assert "example.com/b.pdf" in ref_b and "example.com/a.pdf" not in ref_b

    ref_global = open(os.path.join(out, "references.html"), encoding="utf-8").read()
    assert "example.com/a.pdf" in ref_global and "example.com/b.pdf" in ref_global


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


def test_standard_hardware_v2_renames_constraint_title_to_text(tmp_path):
    """Finding 4: v2 is the first version bump -- constraint.title becomes
    constraint.text, matching requirement.text's role as the type's one
    required content field."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    constraint = project.types["constraint"]
    assert "text" in constraint.fields
    assert constraint.fields["text"].required is True
    assert "title" not in constraint.fields
    assert constraint.preview == ["status", "text", "limit"]


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


# --------------------------------------------------------------------- workspaces

WORKSPACE_CONFIG = """\
site:
  title: "Workspace test"
  out: _site
id:
  width: 3
workspaces:
  platform:
    label: "Platform"
    shared: true
  product-a:
    label: "Product A"
  product-b:
    label: "Product B"
boards:
  board-a:
    label: "Board A"
  board-b:
    label: "Board B"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
"""


@pytest.fixture
def workspace_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(WORKSPACE_CONFIG, encoding="utf-8")
    (tmp_path / "refdes-project.yaml").write_text(
        "item_layout: workspace\n", encoding="utf-8"
    )

    platform = tmp_path / "items" / "platform" / "shared"
    platform.mkdir(parents=True)
    (platform / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-PLAT-001\n    text: Shared platform requirement.\n",
        encoding="utf-8",
    )

    a = tmp_path / "items" / "product-a" / "board-a"
    a.mkdir(parents=True)
    (a / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-A-001\n    text: Product A's own requirement.\n",
        encoding="utf-8",
    )
    (a / "decisions.yaml").write_text(
        "items:\n"
        "  - id: DEC-A-001\n    type: decision\n    title: Uses the shared platform.\n"
        "    satisfies: [REQ-PLAT-001]\n"
        "  - id: DEC-A-002\n    type: decision\n    title: Stays within product-a.\n"
        "    satisfies: [REQ-A-001]\n",
        encoding="utf-8",
    )
    # decisions.yaml has no `defaults: {type: decision}` on purpose -- both
    # entries name their own type explicitly, same shape reqs.yaml's items use.

    b = tmp_path / "items" / "product-b" / "board-b"
    b.mkdir(parents=True)
    (b / "decisions.yaml").write_text(
        "items:\n"
        "  - id: DEC-B-001\n    type: decision\n"
        "    title: Secretly depends on product A.\n"
        "    satisfies: [REQ-A-001]\n",
        encoding="utf-8",
    )
    return tmp_path


def test_flat_layout_with_no_workspaces_is_unaffected(board_project):
    """The core regression guarantee: item_layout defaults to flat, and with
    no workspaces: registry, workspace resolution, the lint, and the drift
    manifest's workspaces: section are all complete no-ops."""
    project = _build_at(board_project)
    assert all(item.workspace == "" for item in project.local_items)
    assert not project.workspace_moves
    assert not any("workspace" in d.message.lower() for d in project.diagnostics)
    assert project.items["REQ-A-001"].board == "board-a"  # boards: untouched

    build_mod.build(project, seal_write=True)
    manifest = boards_mod.load_manifest(project)
    assert manifest["workspaces"] == {}
    raw_data = yaml.safe_load(open(boards_mod.manifest_path(project), encoding="utf-8"))
    assert "workspaces" not in raw_data  # key omitted entirely, not just empty


def test_workspace_and_board_derive_from_the_two_path_segments(workspace_project):
    project = _build_at(workspace_project)
    assert project.items["REQ-A-001"].workspace == "product-a"
    assert project.items["REQ-A-001"].board == "board-a"
    assert project.items["DEC-B-001"].workspace == "product-b"
    assert project.items["DEC-B-001"].board == "board-b"


def test_workspace_override_beats_the_path(workspace_project):
    misc = workspace_project / "items" / "misc"
    misc.mkdir(parents=True)
    (misc / "extra.yaml").write_text(
        "items:\n"
        "  - id: REQ-X-001\n    type: requirement\n"
        "    text: Lives outside any workspace folder.\n"
        "    workspace: product-b\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    assert project.items["REQ-X-001"].workspace == "product-b"


def test_workspace_override_works_even_under_flat_layout(tmp_path):
    """The override is layout-independent; only the path fallback needs
    item_layout: workspace."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "workspaces:\n  platform: { label: Platform }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n      text: { type: text, required: true }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Tagged by hand.\n    workspace: platform\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.items["REQ-001"].workspace == "platform"


def test_unregistered_workspace_override_is_a_build_error(workspace_project):
    (workspace_project / "items" / "product-a" / "board-a" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-A-001\n    text: Bad override.\n    workspace: nope\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    assert any(
        "workspace: 'nope' is not declared" in d.message and d.item_id == "REQ-A-001"
        for d in project.errors
    )


def test_no_second_path_segment_under_workspace_layout_warns(workspace_project):
    lone = workspace_project / "items" / "platform"
    (lone / "orphan.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-LONE-001\n    text: One segment only.\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    assert project.items["REQ-LONE-001"].workspace == "platform"
    assert project.items["REQ-LONE-001"].board == ""
    assert any(
        d.item_id == "REQ-LONE-001"
        and "no second items/ path segment" in d.message
        for d in project.warnings
    )


def test_cross_workspace_link_into_a_non_shared_workspace_warns(workspace_project):
    project = _build_at(workspace_project)
    hits = [
        d for d in project.warnings
        if d.item_id == "DEC-B-001" and "workspace" in d.message
    ]
    assert len(hits) == 1
    assert "REQ-A-001" in hits[0].message
    assert "'product-a'" in hits[0].message
    assert "shared: true" in hits[0].message


def test_cross_workspace_link_into_a_shared_workspace_is_silent(workspace_project):
    project = _build_at(workspace_project)
    assert not any(
        d.item_id == "DEC-A-001" and "hidden dependency" in d.message
        for d in project.diagnostics
    )


def test_same_workspace_link_never_trips_the_lint(workspace_project):
    project = _build_at(workspace_project)
    assert not any(
        d.item_id == "DEC-A-002" and "hidden dependency" in d.message
        for d in project.diagnostics
    )


def test_lint_never_fires_from_the_backlink_direction(workspace_project):
    """DEC-B-001 -> REQ-A-001 crosses workspaces and is flagged once, attributed
    to DEC-B-001 (the authored end). REQ-A-001's computed backlink to DEC-B-001
    must never independently trip a second warning -- proving the lint walks
    item.links exclusively, never item.backlinks."""
    project = _build_at(workspace_project)
    assert "DEC-B-001" in project.items["REQ-A-001"].backlinks.get("satisfied_by", [])
    hits = [d for d in project.diagnostics if "hidden dependency" in d.message]
    assert len(hits) == 1
    assert hits[0].item_id == "DEC-B-001"


def test_derived_coverage_never_trips_the_lint(workspace_project):
    """Coverage is computed from backlinks into project.coverage, a structure
    entirely separate from any item's links -- two items in different,
    non-shared workspaces both contributing to the aggregate coverage picture
    must never be treated as a link between them."""
    project = _build_at(workspace_project)
    assert "REQ-A-001" in project.coverage  # satisfied by DEC-B-001 and DEC-A-002
    assert not any(
        "hidden dependency" in d.message and d.item_id == "REQ-A-001"
        for d in project.diagnostics
    )


def test_cross_workspace_severity_is_configurable(workspace_project):
    (workspace_project / "refdes-project.yaml").write_text(
        "item_layout: workspace\ncross_workspace_severity: error\n", encoding="utf-8"
    )
    project = _build_at(workspace_project)
    assert any(
        d.item_id == "DEC-B-001" and "hidden dependency" in d.message
        for d in project.errors
    )
    assert not any(
        d.item_id == "DEC-B-001" and "hidden dependency" in d.message
        for d in project.warnings
    )


def test_lint_ignores_imported_items_on_either_end(workspace_project):
    """An imported item's `workspace` describes the upstream project's own
    structure, not a dependency inside this one -- imports have their own
    boundary-crossing story and are exempt from this lint entirely."""
    import json

    upstream_dir = workspace_project / "upstream"
    upstream_dir.mkdir()
    (upstream_dir / "items.json").write_text(
        json.dumps({
            "items": [{
                "id": "REQ-UP-001",
                "type": "requirement",
                "fields": {"text": "Upstream requirement."},
                "links": {},
                "content_hash": "abc123",
            }]
        }),
        encoding="utf-8",
    )
    config = open(workspace_project / "refdes.yaml", encoding="utf-8").read()
    config += (
        '\nimports:\n  - name: upstream\n    items: upstream/items.json\n'
    )
    (workspace_project / "refdes.yaml").write_text(config, encoding="utf-8")
    (workspace_project / "items" / "product-a" / "board-a" / "extra.yaml").write_text(
        "items:\n"
        "  - id: DEC-A-003\n    type: decision\n    title: Satisfies an import.\n"
        "    satisfies: [REQ-UP-001]\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    assert not any(
        d.item_id == "DEC-A-003" and "hidden dependency" in d.message
        for d in project.diagnostics
    )


def test_board_and_workspace_names_may_not_collide(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n  power: { label: Power }\n"
        "workspaces:\n  power: { label: Power }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="declared as both a board and a workspace"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_workspace_drift_warns_and_accept_board_move_clears_it(workspace_project):
    project = _build_at(workspace_project)
    build_mod.build(project, seal_write=True)

    # Move DEC-A-002's file into product-b's tree, crossing the workspace
    # boundary without touching its board.
    src = workspace_project / "items" / "product-a" / "board-a" / "decisions.yaml"
    text = src.read_text(encoding="utf-8")
    src.write_text(
        "items:\n"
        "  - id: DEC-A-001\n    type: decision\n    title: Uses the shared platform.\n"
        "    satisfies: [REQ-PLAT-001]\n",
        encoding="utf-8",
    )
    dst = workspace_project / "items" / "product-b" / "board-a"
    dst.mkdir(parents=True)
    (dst / "moved.yaml").write_text(
        "items:\n"
        "  - id: DEC-A-002\n    type: decision\n    title: Stays within product-a.\n"
        "    satisfies: [REQ-A-001]\n",
        encoding="utf-8",
    )

    project2 = _build_at(workspace_project)
    assert ("DEC-A-002", "product-a", "product-b") in project2.workspace_moves
    assert any(
        d.item_id == "DEC-A-002" and "moved from workspace" in d.message
        for d in project2.warnings
    )

    project3 = _build_at(workspace_project)
    build_mod.build(project3, seal_write=True, accept_board_move=True)
    assert boards_mod.load_manifest(project3)["workspaces"]["DEC-A-002"] == "product-b"

    project4 = _build_at(workspace_project)
    build_mod.build(project4, seal_write=True)
    assert not project4.workspace_moves


def test_audit_reports_workspace_moves(workspace_project):
    project = _build_at(workspace_project)
    build_mod.build(project, seal_write=True)
    (workspace_project / "items" / "product-a" / "board-a" / "reqs.yaml").rename(
        workspace_project / "items" / "product-b" / "board-b" / "moved-req.yaml"
    )
    project2 = load_project(config_path=str(workspace_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)  # audit never writes
    assert ("REQ-A-001", "product-a", "product-b") in project2.workspace_moves


def test_check_workspace_flag_scopes_item_count(workspace_project, capsys):
    cli_mod.main(
        ["-c", str(workspace_project / "refdes.yaml"), "check", "--workspace", "product-a"]
    )
    out = capsys.readouterr().out
    # product-a has exactly REQ-A-001, DEC-A-001, DEC-A-002.
    assert "3 items," in out


def test_check_workspace_flag_hides_other_workspaces_warnings(workspace_project, capsys):
    status = cli_mod.main(
        ["-c", str(workspace_project / "refdes.yaml"), "check", "--workspace", "product-a"]
    )
    out = capsys.readouterr().out
    assert "DEC-B-001" not in out
    assert "hidden dependency" not in out


def test_check_unknown_workspace_flag_is_a_clear_error(workspace_project, capsys):
    status = cli_mod.main(
        ["-c", str(workspace_project / "refdes.yaml"), "check", "--workspace", "nope"]
    )
    err = capsys.readouterr().err
    assert status == 1
    assert "--workspace 'nope' is not a workspace declared" in err


def test_workspace_pages_render_with_nested_board_groups(workspace_project):
    project = _build_at(workspace_project)
    out = render.render_site(project)
    assert os.path.isfile(os.path.join(out, "coverage-platform.html"))
    assert os.path.isfile(os.path.join(out, "summary-product-a.html"))
    assert os.path.isfile(os.path.join(out, "document-product-b.html"))

    nav = nav_mod.build_nav(project, dashboard_href="index.html")
    labels = {node.label: node for node in nav}
    assert "Product A" in labels
    product_a_children = {
        child.label for child in labels["Product A"].children
    }
    assert "Board A" in product_a_children
    board_a_node = next(
        c for c in labels["Product A"].children if c.label == "Board A"
    )
    assert any(c.href == "coverage-board-a.html" for c in board_a_node.children)


def test_items_json_exports_workspace_registry_and_per_item_workspace(workspace_project):
    project = _build_at(workspace_project)
    payload = render.items_json(project)
    assert set(payload["workspaces"]) == {"platform", "product-a", "product-b"}
    assert payload["workspaces"]["platform"]["shared"] is True
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id["REQ-A-001"]["workspace"] == "product-a"


def test_page_workspace_tag_groups_it_and_must_be_registered(workspace_project):
    pages_dir = workspace_project / "pages"
    pages_dir.mkdir()
    (pages_dir / "overview.md").write_text(
        "---\ntitle: Product A overview\nworkspace: product-a\n---\n\nHello.\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    page = next(p for p in project.pages if p.slug == "overview")
    assert page.workspace == "product-a"

    (pages_dir / "bad.md").write_text(
        "---\ntitle: Bad tag\nworkspace: not-a-real-workspace\n---\n\nHello.\n",
        encoding="utf-8",
    )
    project2 = _build_at(workspace_project)
    bad_page = next(p for p in project2.pages if p.slug == "bad")
    assert bad_page.workspace == ""
    assert any(
        "page workspace: 'not-a-real-workspace' is not declared" in d.message
        for d in project2.errors
    )


# ------------------------------------------------------------------ lifecycle

LIFECYCLE_SCHEMA = """\
site: { title: "Lifecycle test", out: _site }
id: { width: 3 }
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text:   { type: text, required: true }
      status: { type: enum, choices: [draft, active, retired], default: draft }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
  component:
    prefix: CMP
    fields:
      title:      { type: text, required: true }
      datasheets: { type: citations }
"""

LIFECYCLE_ITEMS = (
    "defaults: { type: requirement }\n"
    "items:\n"
    "  - id: REQ-001\n    text: Uncovered active requirement.\n    status: active\n"
    "  - id: REQ-002\n    text: Draft requirement, exempt from the coverage rules.\n"
    "    status: draft\n"
)

LIFECYCLE_COMPONENT = (
    "defaults: { type: component }\n"
    "items:\n"
    "  - id: CMP-001\n    title: Cites an unfetched datasheet.\n"
    "    datasheets:\n      - url: https://example.com/datasheet.pdf\n"
)


@pytest.fixture
def lifecycle_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(LIFECYCLE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "reqs.yaml").write_text(LIFECYCLE_ITEMS, encoding="utf-8")
    (items / "cmp.yaml").write_text(LIFECYCLE_COMPONENT, encoding="utf-8")
    return tmp_path


def _lc_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    return project


# --------------------------------------------------------------- gate rules


def test_draft_items_rule_flags_only_the_draft_status_field(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["draft_items"].offenders == ["REQ-002"]


def test_uncovered_requirements_excludes_draft_items(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    # REQ-001 is open and active -> offender. REQ-002 is open too, but draft
    # -> exempt, same problem as draft_items, not counted twice.
    assert results["uncovered_requirements"].offenders == ["REQ-001"]


def test_unverified_requirements_disabled_by_default_for_release(lifecycle_project):
    """Settled by the user: unverified requirements never block a release by
    default -- boards go to fab in order to get tested."""
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unverified_requirements"].enabled is False
    assert results["unverified_requirements"].status == "skipped"


def test_unverified_requirements_when_explicitly_enabled_excludes_draft(lifecycle_project):
    (lifecycle_project / "refdes-project.yaml").write_text(
        "release_gate:\n  unverified_requirements: { release: true }\n",
        encoding="utf-8",
    )
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unverified_requirements"].offenders == ["REQ-001"]


def test_unpinned_citations_rule(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unpinned_citations"].offenders == ["CMP-001"]


def test_missing_vendored_copies_rule(lifecycle_project, tmp_path):
    root = lifecycle_project
    (root / ".refdes").mkdir(exist_ok=True)
    (root / ".refdes" / "citations.yaml").write_text(
        "citations:\n"
        "  https://example.com/datasheet.pdf:\n"
        "    sha256: deadbeef\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    vendored: true\n",
        encoding="utf-8",
    )
    project = _lc_build(root)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["missing_vendored_copies"].offenders == ["CMP-001"]
    # not simultaneously flagged as unpinned -- it IS pinned, just missing the blob
    assert results["unpinned_citations"].offenders == []


def test_unaccepted_board_moves_rule_reads_project_board_moves(lifecycle_project):
    """Drift detection itself is boards.py's own, extensively tested job --
    this only checks the gate rule reads project.board_moves correctly."""
    project = _lc_build(lifecycle_project)
    project.board_moves.append(("REQ-001", "board-a", "board-b"))
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unaccepted_board_moves"].offenders == ["REQ-001"]


def test_unaccepted_workspace_moves_rule_reads_project_workspace_moves(lifecycle_project):
    """Same shape as unaccepted_board_moves, reading project.workspace_moves
    instead -- a file silently changing workspace used to pass release
    unnoticed even though the same drift on board: already blocked it."""
    project = _lc_build(lifecycle_project)
    project.workspace_moves.append(("REQ-001", "alpha", "beta"))
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unaccepted_workspace_moves"].offenders == ["REQ-001"]
    assert results["unaccepted_workspace_moves"].status == "FAIL"
    # Same default posture as unaccepted_board_moves: on for release, off
    # for revision.
    revision_results = {r.name: r for r in lifecycle.evaluate_gate(project, "revision")}
    assert revision_results["unaccepted_workspace_moves"].status == "skipped"


def test_unaccepted_workspace_moves_blocks_a_release(lifecycle_project):
    project = _lc_build(lifecycle_project)
    project.workspace_moves.append(("REQ-001", "alpha", "beta"))
    outcome = lifecycle.stamp(project, kind="release", name="rev-a")
    assert outcome.status == "gate_failed"
    assert any(
        r.name == "unaccepted_workspace_moves" and r.status == "FAIL"
        for r in outcome.gate_results
    )


def test_info_check_failures_rule(tmp_path):
    project = _check_severity_project(
        tmp_path, item_type="option", item_id="OPT-001", prefix="opt"
    )
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "revision")}
    # off by default for revision too -- explicitly enable to see it fire.
    assert results["info_check_failures"].enabled is False
    project.release_gate["info_check_failures"]["release"] = True
    results2 = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results2["info_check_failures"].offenders == ["OPT-001"]


def test_nothing_defaults_on_for_revision(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = lifecycle.evaluate_gate(project, "revision")
    assert all(r.status == "skipped" for r in results)


# --------------------------------------------------------------------- stamp


def test_revision_stamps_unconditionally_despite_draft_and_uncovered_items(lifecycle_project):
    project = _lc_build(lifecycle_project)
    assert not project.errors
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"
    assert outcome.item_count == 3
    assert os.path.isfile(outcome.path)


def test_stamp_records_the_pinned_standard_version(tmp_path):
    """A baseline records `refdes_version` (the tool) but nothing said which
    *vocabulary* version produced its hashes -- revise.py needs this to know
    where to start migrating an existing baseline from."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n  - id: REQ-001\n    type: requirement\n    text: A requirement.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert project.standard_base == "hardware"
    assert project.standard_version == 2

    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"
    baseline = lifecycle.load_baseline(project, "rev-a")
    assert baseline.standard == {"base": "hardware", "version": 2}


def test_stamp_omits_standard_for_a_hand_rolled_schema(lifecycle_project):
    """`standard: none` (or no standard: key at all, as LIFECYCLE_SCHEMA has)
    must not fabricate a {base, version} -- there is no bundled vocabulary
    version to record."""
    project = _lc_build(lifecycle_project)
    assert project.standard_base == ""
    assert project.standard_version is None
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    baseline = lifecycle.load_baseline(project, "rev-a")
    assert baseline.standard is None


def test_baseline_written_before_this_field_existed_loads_as_none(tmp_path):
    """Backward compatibility: an old baseline file with no `standard:` key
    at all must load with `.standard is None`, not raise or default to
    something that looks like an answer."""
    (tmp_path / ".refdes" / "baselines").mkdir(parents=True)
    (tmp_path / ".refdes" / "baselines" / "old.yaml").write_text(
        "kind: revision\n"
        "name: old\n"
        "stamped_at: '2026-01-01T00:00:00Z'\n"
        "stamped_by: someone\n"
        "refdes_version: 0.3.0\n"
        "items: {}\n",
        encoding="utf-8",
    )
    (tmp_path / "refdes.yaml").write_text(
        "site: {title: t, out: _site}\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    baseline = lifecycle.load_baseline(project, "old")
    assert baseline.standard is None


def _pin_lifecycle_citation(root) -> None:
    (root / ".refdes").mkdir(exist_ok=True)
    (root / ".refdes" / "citations.yaml").write_text(
        "citations:\n"
        "  https://example.com/datasheet.pdf:\n"
        "    sha256: deadbeef\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    vendored: false\n",
        encoding="utf-8",
    )


def test_release_blocked_then_passes_once_resolved(lifecycle_project):
    project = _lc_build(lifecycle_project)
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    failing = {r.name for r in outcome.gate_results if r.enabled and r.offenders}
    assert failing == {"draft_items", "uncovered_requirements", "unpinned_citations"}
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))

    # Resolve all three: promote REQ-002 out of draft, cover REQ-001, pin CMP-001's citation.
    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Uncovered active requirement.\n    status: active\n"
        "  - id: REQ-002\n    text: No longer a draft.\n    status: active\n",
        encoding="utf-8",
    )
    (lifecycle_project / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n    title: Covers both requirements.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    _pin_lifecycle_citation(lifecycle_project)
    project2 = _lc_build(lifecycle_project)
    outcome2 = lifecycle.stamp(project2, kind="release", name="rel-a")
    assert outcome2.status == "stamped"
    baseline = lifecycle.load_baseline(project2, "rel-a")
    assert baseline.kind == "release"
    assert baseline.gate["draft_items"] == "pass"
    assert baseline.gate["unverified_requirements"] == "skipped"
    assert set(baseline.items) == {"REQ-001", "REQ-002", "DEC-001", "CMP-001"}


def test_rerun_same_name_identical_content_is_a_noop(lifecycle_project):
    project = _lc_build(lifecycle_project)
    first = lifecycle.stamp(project, kind="revision", name="rev-a")
    mtime_before = os.path.getmtime(first.path)

    project2 = _lc_build(lifecycle_project)
    second = lifecycle.stamp(project2, kind="revision", name="rev-a")
    assert second.status == "unchanged"
    assert second.stamped_at == first.stamped_at
    assert os.path.getmtime(first.path) == mtime_before  # file untouched


def test_rerun_same_name_different_content_is_a_conflict(lifecycle_project):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (lifecycle_project / "items" / "reqs.yaml").write_text(
        LIFECYCLE_ITEMS.replace("Uncovered active requirement.", "Edited text."),
        encoding="utf-8",
    )
    project2 = _lc_build(lifecycle_project)
    outcome = lifecycle.stamp(project2, kind="revision", name="rev-a")
    assert outcome.status == "conflict"
    assert "different content" in outcome.conflict_detail
    assert "rev-a" in outcome.conflict_detail


def test_release_and_revision_are_peers_no_special_handling(lifecycle_project):
    """No lineage: a release does not need to follow or supersede the latest
    revision. Stamping rel-a after rev-a (a newer revision) is unremarkable."""
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Now covered.\n    status: active\n"
        "  - id: REQ-002\n    text: No longer draft.\n    status: active\n",
        encoding="utf-8",
    )
    (lifecycle_project / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n  - id: DEC-001\n    title: Covers both.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    _pin_lifecycle_citation(lifecycle_project)
    project2 = _lc_build(lifecycle_project)
    outcome = lifecycle.stamp(project2, kind="release", name="rel-a")
    assert outcome.status == "stamped"


def test_kind_mismatch_under_the_same_name_is_a_conflict(lifecycle_project):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="shared-name")
    project2 = _lc_build(lifecycle_project)
    outcome = lifecycle.stamp(project2, kind="release", name="shared-name")
    # Same items, but kind differs (revision vs release) -- not a silent
    # kind upgrade; gate wasn't even satisfied here anyway (draft/uncovered).
    assert outcome.status in ("conflict", "gate_failed")


# ------------------------------------------------------------ revise (finding 12)

REVISE_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
)


@pytest.fixture
def revise_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(REVISE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-001\n    label: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_renames_a_prefix_standalone_no_schema_change_needed(tmp_path):
    """Core, plain `revise`, no mutate_config: a prefix rename never depends
    on the schema at all (prefixes aren't type-checked), so this is the one
    rename category that always works standalone -- confirmed here, then
    the field/type cases (which do need the schema to move too) get their
    own tests below via mutate_config."""
    (tmp_path / "refdes.yaml").write_text(REVISE_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(prefixes={"BND": "LIM"})
    result = revise.apply(str(tmp_path), mapping)
    assert result.ok, result.errors
    assert result.changed_files == ["items/i.yaml"]
    assert result.id_changes == {"BND-001": "LIM-001"}
    text = (tmp_path / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "prefix: LIM" in text
    assert "id: LIM-001" in text


def test_revise_renames_type_and_prefix_atomically_with_schema_via_mutate_config(tmp_path):
    """Type and prefix renames need the schema to move with the data --
    plain revise doesn't touch refdes.yaml, but a caller-supplied
    mutate_config (what standards.py's upgrade chain uses) can make the two
    move together as one verified operation."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  constraint: { prefix: CON, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON\n"
        "items:\n  - id: CON-001\n    text: Board power density\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(types={"constraint": "bound"}, prefixes={"CON": "BND"})

    def bump(config_path):
        with open(config_path, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("constraint:", "bound:").replace(
            "constraint, prefix: CON", "bound, prefix: BND"
        )
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write(text)

    result = revise.apply(str(tmp_path), mapping, mutate_config=bump)
    assert result.ok, result.errors
    assert result.id_changes == {"CON-001": "BND-001"}
    text = (tmp_path / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "type: bound" in text
    assert "prefix: BND" in text
    assert "id: BND-001" in text


def test_revise_refuses_and_rolls_back_a_required_field_rename_without_schema_update(revise_project):
    """A required-field rename where the schema hasn't moved is refused, not
    silently applied -- the safety net this whole engine exists for. The
    file is byte-identical afterward: refused all the way back, not
    partially applied."""
    before = (revise_project / "items" / "i.yaml").read_text(encoding="utf-8")
    mapping = revise.Mapping(fields={"bound": {"label": "text"}})
    # This project's schema already says `text:` (not `label:`), so before
    # even rewriting anything, the *current* file (still saying `label:`)
    # already conflicts with the schema -- refused up front.
    result = revise.apply(str(revise_project), mapping)
    assert not result.ok
    after = (revise_project / "items" / "i.yaml").read_text(encoding="utf-8")
    assert after == before


VIOLATING_SCHEMA = (
    "site: { title: T, out: _site }\n"
    'link_types:\n  constrained_by: { inverse: constrains, label: "Constrained by" }\n'
    "types:\n"
    "  constraint:\n"
    "    prefix: CON\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      checks: { type: checks }\n"
    "    links:\n"
    "      constrained_by: [constraint]\n"
    "    body: {}\n"
)


@pytest.fixture
def violating_project(tmp_path):
    """A project whose build fails on a *check* -- the design does not meet a
    declared limit -- and on nothing else. The tool working, not failing."""
    (tmp_path / "refdes.yaml").write_text(VIOLATING_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n"
        "  - id: CON-THM-001\n    text: Board power density\n"
        '    limit: "<= 0.15 W/in^2"\n',
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-THM-001]\n"
        "checks:\n"
        "  - value: P_dens\n"
        "    against: CON-THM-001\n"
        "---\n\n"
        "```calc\nP_dens : W/in^2 = 0.2366 W/in^2\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_failing_check_does_not_block_a_rename(violating_project):
    """A decision currently violating a bound is a normal, often long-lived
    state -- this repository's own sample project ships one deliberately, as
    the teaching example on the front page of the docs. Refusing every
    vocabulary migration until it is resolved made `revise` and `standard
    upgrade` unusable on exactly the projects most likely to need them, and
    protected nothing: a rename moves the arithmetic and the limit together,
    so it cannot change a check's verdict."""
    project = _build_at(violating_project)
    assert any(d.code == "check_violation" for d in project.errors), [
        str(d) for d in project.errors
    ]

    result = revise.apply(str(violating_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert result.ok, result.errors
    assert result.id_changes == {"CON-THM-001": "BND-THM-001"}
    assert "id: BND-THM-001" in (
        violating_project / "items" / "con.yaml"
    ).read_text(encoding="utf-8")


def test_a_content_error_still_blocks_a_rename(violating_project):
    """The rule the refusal exists for is unchanged: a hash change caused by
    the rename must not be able to hide behind a document that doesn't
    validate. A dangling link is exactly that, and still refuses."""
    (violating_project / "items" / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-THM-999]\n"
        "---\n",
        encoding="utf-8",
    )
    result = revise.apply(str(violating_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert not result.ok
    assert any("existing build errors" in e for e in result.errors), result.errors
    assert "id: CON-THM-001" in (
        violating_project / "items" / "con.yaml"
    ).read_text(encoding="utf-8")


def test_a_missing_required_field_still_blocks_a_rename(violating_project):
    """The other half of the same rule: a schema the data no longer satisfies
    is a content problem, not a finding about the design."""
    (violating_project / "items" / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n  - id: CON-THM-001\n    text: No limit on this one.\n",
        encoding="utf-8",
    )
    result = revise.apply(str(violating_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert not result.ok
    assert any("existing build errors" in e for e in result.errors), result.errors


def test_standard_upgrade_runs_on_a_project_with_a_failing_check(tmp_path):
    """The end-to-end version of the same thing, through the bundled
    standard's own chain rather than a hand-written mapping."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 3, presets: [] }\n"
        "id: { width: 3, ledger: .refdes/ids.yaml }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "b.yaml").write_text(
        "items:\n  - id: BND-001\n    type: bound\n    text: Board power density\n"
        '    limit: "<= 0.15 W/in^2"\n    status: active\n',
        encoding="utf-8",
    )
    (tmp_path / "items" / "d.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Regulator\nstatus: accepted\n"
        "constrained_by: [BND-001]\nchecks:\n  - value: P_dens\n    against: BND-001\n---\n\n"
        "```calc\nP_dens : W/in^2 = 0.2366 W/in^2\n```\n",
        encoding="utf-8",
    )
    steps = revise.apply_standard_upgrade(str(tmp_path), 4)
    assert [(s.from_version, s.to_version) for s in steps] == [(3, 4)]
    assert steps[0].result.ok, steps[0].result.errors
    # The pin moved even though no item file needed rewriting.
    assert steps[0].result.config_updated
    assert "version: 4" in (tmp_path / "refdes.yaml").read_text(encoding="utf-8")


def test_revise_refuses_ambiguous_target_already_in_use(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  bound: { prefix: BND, fields: { label: { type: text }, text: { type: text } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults: { type: bound, prefix: BND }\n"
        "items:\n  - id: BND-001\n    label: x\n    text: y\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(fields={"bound": {"label": "text"}})
    result = revise.apply(str(tmp_path), mapping)
    assert not result.ok
    assert any("already exists" in e for e in result.errors)


def test_revise_refuses_a_self_contradictory_mapping():
    """Two different old names both wanting the same new name -- caught
    without even needing a project, since the mapping contradicts itself."""
    project = load_project(config_path=os.path.join(REPO, "refdes.yaml"))
    mapping = revise.Mapping(prefixes={"REQ": "R", "RSK": "R"})
    errors = revise.check_ambiguous(project, mapping)
    assert any("collides" in e for e in errors)


def _label_schema(tmp_path) -> None:
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  bound:\n"
        "    prefix: BND\n"
        "    fields:\n"
        "      label: { type: text, required: true }\n"
        "      limit: { type: limit, required: true }\n",
        encoding="utf-8",
    )


def _bump_label_field_to_text(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace(
        "label: { type: text, required: true }", "text:  { type: text, required: true }"
    )
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture
def label_project(tmp_path):
    """Schema and item file agree on `label:` -- the state a real project is
    actually in before a rename, unlike revise_project above (deliberately
    pre-broken, for the refusal test)."""
    _label_schema(tmp_path)
    items = tmp_path / "items"
    items.mkdir()
    (items / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-001\n    label: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_carries_baseline_hash_forward(label_project):
    """The core promise: a cosmetic rename must not make an untouched
    baseline suddenly report every item as 'changed'."""
    project = load_project(config_path=str(label_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors
    old_hash = project.items["BND-001"].content_hash
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"

    mapping = revise.Mapping(fields={"bound": {"label": "text"}})
    result = revise.apply(str(label_project), mapping, mutate_config=_bump_label_field_to_text)
    assert result.ok, result.errors
    assert result.baselines_updated == ["rev-a"]

    project2 = load_project(config_path=str(label_project / "refdes.yaml"))
    baseline = lifecycle.load_baseline(project2, "rev-a")
    new_hash = baseline.items["BND-001"]["hash"]
    assert new_hash != old_hash

    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False, accept_board_move=False)
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == []
    assert diff.added == []
    assert diff.removed == []


def _log_schema(tmp_path) -> None:
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    fields:\n"
        "      summary: { type: text, required: true }\n",
        encoding="utf-8",
    )


def _bump_summary_field_to_note(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace(
        "summary: { type: text, required: true }", "note:    { type: text, required: true }"
    )
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture
def log_project(tmp_path):
    _log_schema(tmp_path)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(
        "defaults:\n  type: log\n  prefix: LOG\n"
        "items:\n  - id: LOG-001\n    summary: First entry.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_carries_seal_hash_forward(log_project):
    """seal.py's append-only comparison is driven by the same content_hash
    a rename touches, and a mismatch there is a hard build ERROR, not a
    diff -- the caveat finding 12 flagged beyond what the finding itself
    stated. A cosmetic field rename on a sealed log entry must not turn a
    clean build into a seal-violation failure."""
    project = load_project(config_path=str(log_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=True)
    assert not project.errors
    old_hash = seal.load_seals(project, board="")["LOG-001"]

    mapping = revise.Mapping(fields={"log": {"summary": "note"}})
    result = revise.apply(str(log_project), mapping, mutate_config=_bump_summary_field_to_note)
    assert result.ok, result.errors
    assert result.seals_updated == ["(base)"]

    reloaded_seals = seal.load_seals(
        load_project(config_path=str(log_project / "refdes.yaml")), board=""
    )
    assert reloaded_seals.keys() == {"LOG-001"}
    assert reloaded_seals["LOG-001"] != old_hash

    project2 = load_project(config_path=str(log_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False, accept_board_move=False)
    assert not project2.errors
    assert project2.seal_violations == []


def test_plain_revise_ignores_a_baselines_missing_standard_field(label_project):
    """Plain revise (no standard_transition -- there's no chain, so no
    ambiguity about which baseline started where) matches purely by hash:
    a baseline written before the standard: field existed (or, as here, a
    hand-rolled project with no bundled standard at all) still gets carried
    forward. The chained, standard-upgrade case where a missing standard:
    genuinely has to be skipped is tested separately, where the ambiguity
    is real."""
    project = load_project(config_path=str(label_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    baseline_path = lifecycle.baseline_path(project, "rev-a")
    text = open(baseline_path, encoding="utf-8").read()
    assert "standard:" not in text  # nothing to record: no bundled standard pinned

    mapping = revise.Mapping(fields={"bound": {"label": "text"}})
    result = revise.apply(str(label_project), mapping, mutate_config=_bump_label_field_to_text)
    assert result.ok, result.errors
    assert result.baselines_updated == ["rev-a"]
    assert result.baselines_skipped_no_standard == []


def _write_fake_versioned_standard(root, versions, migrations=None):
    """`<root>/fake/v<N>/base.yaml` for each version in `versions` (a dict of
    version number -> base.yaml document), plus `<root>/fake/v<N>/migration.yaml`
    for each version number present in `migrations` -- a synthetic multi-
    version standard, isolated from the real bundled `hardware` standard, for
    tests that need to drive `revise.apply_standard_upgrade` through more
    than one version step."""
    for version, doc in versions.items():
        version_dir = os.path.join(str(root), "fake", f"v{version}")
        os.makedirs(version_dir, exist_ok=True)
        with open(os.path.join(version_dir, "base.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh)
    for version, doc in (migrations or {}).items():
        version_dir = os.path.join(str(root), "fake", f"v{version}")
        os.makedirs(version_dir, exist_ok=True)
        with open(os.path.join(version_dir, "migration.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh)


def test_standard_upgrade_skips_a_baseline_with_no_recorded_standard(tmp_path, monkeypatch):
    """The chained case, where skipping is the real, needed behavior: a
    baseline written before Baseline.standard existed (simulated here by
    stamping normally, then stripping the field back out) has nowhere
    recorded to say which version its hashes started at, so a multi-version
    chain must not guess -- it's left alone, reported as skipped, rather
    than silently matched against whichever version happens to be current."""
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path / "std"))
    monkeypatch.setattr(standards, "_KNOWN_BASES", ("fake",))
    _write_fake_versioned_standard(
        tmp_path / "std",
        {
            1: {"types": {"widget": {"prefix": "WID", "fields": {"title": {"type": "text", "required": True}}}}},
            2: {"types": {"widget": {"prefix": "WID", "fields": {"text": {"type": "text", "required": True}}}}},
        },
        migrations={2: {"fields": {"widget": {"title": "text"}}}},
    )

    project_root = tmp_path / "proj"
    (project_root / "items").mkdir(parents=True)
    (project_root / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\nstandard: { base: fake, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (project_root / "items" / "i.yaml").write_text(
        "defaults:\n  type: widget\n  prefix: WID\n"
        "items:\n  - id: WID-001\n    title: A widget.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(project_root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    # Strip the standard: field back out, simulating a baseline stamped
    # before it existed.
    baseline_path = lifecycle.baseline_path(project, "rev-a")
    with open(baseline_path, encoding="utf-8") as fh:
        stripped = "\n".join(l for l in fh.read().splitlines() if not l.startswith(("standard:", "  base:", "  version:")))
    with open(baseline_path, "w", encoding="utf-8") as fh:
        fh.write(stripped + "\n")
    reloaded = lifecycle.load_baseline(project, "rev-a")
    assert reloaded.standard is None

    steps = revise.apply_standard_upgrade(str(project_root), 2)
    assert len(steps) == 1
    assert steps[0].result.ok, steps[0].result.errors
    assert steps[0].result.baselines_skipped_no_standard == ["rev-a"]
    assert steps[0].result.baselines_updated == []


def test_apply_standard_upgrade_chains_multiple_versions(tmp_path, monkeypatch):
    """v1 -> v4 works by chaining each version's own delta in order -- one
    apply() call per version step (extension 2), never a single merged
    jump straight from v1's schema to v4's."""
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path / "std"))
    monkeypatch.setattr(standards, "_KNOWN_BASES", ("fake",))
    _write_fake_versioned_standard(
        tmp_path / "std",
        {
            1: {"types": {"widget": {"prefix": "WID", "fields": {"a": {"type": "text", "required": True}}}}},
            2: {"types": {"widget": {"prefix": "WID", "fields": {"b": {"type": "text", "required": True}}}}},
            3: {"types": {"widget": {"prefix": "WID", "fields": {"c": {"type": "text", "required": True}}}}},
            4: {"types": {"widget": {"prefix": "WID", "fields": {"d": {"type": "text", "required": True}}}}},
        },
        migrations={
            2: {"fields": {"widget": {"a": "b"}}},
            3: {"fields": {"widget": {"b": "c"}}},
            4: {"fields": {"widget": {"c": "d"}}},
        },
    )
    project_root = tmp_path / "proj"
    (project_root / "items").mkdir(parents=True)
    (project_root / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\nstandard: { base: fake, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (project_root / "items" / "i.yaml").write_text(
        "defaults:\n  type: widget\n  prefix: WID\n"
        "items:\n  - id: WID-001\n    a: Original value.\n",
        encoding="utf-8",
    )

    steps = revise.apply_standard_upgrade(str(project_root), 4)
    assert [(s.from_version, s.to_version) for s in steps] == [(1, 2), (2, 3), (3, 4)]
    assert all(s.result.ok for s in steps), [s.result.errors for s in steps]

    text = (project_root / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "d: Original value." in text
    assert "a:" not in text and "b:" not in text and "c:" not in text

    final_project = load_project(config_path=str(project_root / "refdes.yaml"))
    assert final_project.standard_version == 4


def test_apply_standard_upgrade_reused_field_name_across_versions(tmp_path, monkeypatch):
    """v2 renames title -> text; v3 independently renames notes -> title,
    reusing the name v2 just freed up. Chaining each step fully in order
    (never collapsing into one merged mapping) is what keeps this from
    colliding: by the time v3's own rename runs, nothing in the project is
    named `title` any more, so `notes -> title` lands cleanly and each
    original value ends up under the right final key, not swapped or lost."""
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path / "std"))
    monkeypatch.setattr(standards, "_KNOWN_BASES", ("fake",))
    _write_fake_versioned_standard(
        tmp_path / "std",
        {
            1: {"types": {"widget": {"prefix": "WID", "fields": {
                "title": {"type": "text", "required": True},
                "notes": {"type": "text", "required": True},
            }}}},
            2: {"types": {"widget": {"prefix": "WID", "fields": {
                "text": {"type": "text", "required": True},
                "notes": {"type": "text", "required": True},
            }}}},
            3: {"types": {"widget": {"prefix": "WID", "fields": {
                "text": {"type": "text", "required": True},
                "title": {"type": "text", "required": True},
            }}}},
        },
        migrations={
            2: {"fields": {"widget": {"title": "text"}}},
            3: {"fields": {"widget": {"notes": "title"}}},
        },
    )
    project_root = tmp_path / "proj"
    (project_root / "items").mkdir(parents=True)
    (project_root / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\nstandard: { base: fake, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (project_root / "items" / "i.yaml").write_text(
        "defaults:\n  type: widget\n  prefix: WID\n"
        "items:\n  - id: WID-001\n    title: Title value.\n    notes: Notes value.\n",
        encoding="utf-8",
    )

    steps = revise.apply_standard_upgrade(str(project_root), 3)
    assert len(steps) == 2
    assert all(s.result.ok for s in steps), [s.result.errors for s in steps]

    text = (project_root / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "text: Title value." in text
    assert "title: Notes value." in text

    final_project = load_project(config_path=str(project_root / "refdes.yaml"))
    parse.load_items(final_project)
    build_mod.build(final_project, seal_write=False, reseal=False, accept_board_move=False)
    assert not final_project.errors


# ------------------------------------ revise: compound prefixes (finding 10)

COMPOUND_PREFIX_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  constrained_by: { inverse: constrains, label: \"Constrained by\" }\n"
    "types:\n"
    "  constraint:\n"
    "    prefix: CON\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      checks: { type: checks }\n"
    "    links:\n"
    "      constrained_by: [constraint]\n"
)


@pytest.fixture
def compound_prefix_project(tmp_path):
    """Mirrors this project's own convention: a `constraint` item using a
    compound prefix (`CON-THM`, base `CON` plus a board token) that a
    `decision` elsewhere references both through a `links:` field and a
    `checks:` entry, plus a prose mention that must never be rewritten."""
    (tmp_path / "refdes.yaml").write_text(COMPOUND_PREFIX_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n"
        "  - id: CON-THM-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-THM-001]\n"
        "checks:\n"
        "  - value: P_dens\n"
        "    against: CON-THM-001\n"
        "---\n\n"
        "The thermal budget in CON-THM-001 drives this choice.\n\n"
        "```calc\nP_dens : W/in^2 = 0.1 W/in^2\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_renames_a_compound_prefix_built_on_the_renamed_base(compound_prefix_project):
    """`ids.split_id`'s `PREFIX-NNN` shape treats a board-token-suffixed
    prefix (`CON-THM`) as one atomic string, so a bare dict lookup against
    `mapping.prefixes` (`{CON: BND}`) would silently miss it -- this project's
    own `refdes.yaml` documents exactly this convention (`REQ-PWR`, `CON-THM`,
    `DEC-PWR`, `TST-PWR`). Confirms the item's own `prefix:`/`id:` move.
    Prefix-only mapping, deliberately: renaming `types:` needs the schema to
    move with it (see `mutate_config`, covered by its own dedicated test
    above), which is orthogonal to what this is testing."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    assert result.id_changes == {"CON-THM-001": "BND-THM-001"}
    text = (compound_prefix_project / "items" / "con.yaml").read_text(encoding="utf-8")
    assert "prefix: BND-THM" in text
    assert "id: BND-THM-001" in text


def test_revise_does_not_rename_an_unrelated_prefix_sharing_a_letters(tmp_path):
    """`CONFIG` must never match a `CON` rename -- the required separator is
    the hyphen itself, not just the leading letters."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  widget: { prefix: CONFIG, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: widget\n  prefix: CONFIG\n"
        "items:\n  - id: CONFIG-001\n    text: Untouched.\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(tmp_path), mapping)
    assert result.ok, result.errors
    assert result.changed_files == []
    assert result.id_changes == {}


def test_revise_rewrites_a_link_value_and_a_checks_against_value(compound_prefix_project):
    """The item's own id relabeling (previous test) is only half of a real
    prefix rename -- every *other* item's structured reference to it
    (`constrained_by: [...]`, `checks: - against: ...`) must move too, or the
    rewritten project is left with dangling references (caught, and refused,
    before this fix existed -- see the commit message). A clean reload+build
    confirms it: nothing in the schema changed (prefix-only mapping), so a
    project that still validates end to end is proof every reference now
    agrees with the renamed id."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    text = (compound_prefix_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "constrained_by: [BND-THM-001]" in text
    assert "against: BND-THM-001" in text

    project = load_project(config_path=str(compound_prefix_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors


def test_revise_leaves_a_prose_mention_of_the_renamed_id_untouched(compound_prefix_project):
    """Only structured references move -- an id mentioned in body prose is
    never rewritten, the same posture `_rewrite_fields_and_links` already
    takes for field/link key renames."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    text = (compound_prefix_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "The thermal budget in CON-THM-001 drives this choice." in text


BLOCK_STYLE_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  constrained_by: { inverse: constrains, label: \"Constrained by\" }\n"
    "  addresses: { inverse: addressed_by, label: \"Addresses\" }\n"
    "types:\n"
    "  constraint:\n"
    "    prefix: CON\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "    links:\n"
    "      constrained_by: [constraint]\n"
    "  log:\n"
    "    prefix: LOG\n"
    "    fields:\n"
    "      summary: { type: text, required: true }\n"
    "    links:\n"
    "      addresses: [constraint]\n"
)


@pytest.fixture
def block_style_project(tmp_path):
    """The same references `compound_prefix_project` writes in flow style,
    written in the other legal YAML spelling instead: a bare key with
    `- TARGET` entries under it, in both a Markdown item and a list file."""
    (tmp_path / "refdes.yaml").write_text(BLOCK_STYLE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n"
        "  - id: CON-THM-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by:\n"
        "  - CON-THM-001\n"
        "---\n\n"
        "Prose mentioning CON-THM-001.\n",
        encoding="utf-8",
    )
    (items / "log.yaml").write_text(
        "defaults:\n  type: log\n  prefix: LOG\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Thermal review\n    addresses:\n      - CON-THM-001\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_rewrites_a_block_style_link_target_list(block_style_project):
    """Only flow-style values (`key: [A, B]`) had ever run through this
    engine. A block-style list -- the idiomatic spelling, and what a
    reference to a renamed id looks like in most real files -- was skipped,
    which did not leave those references merely untouched: the rewritten
    project then had a dangling link target, so the whole operation refused
    and rolled back, reporting the symptom ("constrained_by points at
    'CON-THM-001', which does not exist") and nothing about the cause."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(block_style_project), mapping)
    assert result.ok, result.errors
    assert result.id_changes == {"CON-THM-001": "BND-THM-001"}

    dec = (block_style_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "constrained_by:\n  - BND-THM-001\n" in dec
    log = (block_style_project / "items" / "log.yaml").read_text(encoding="utf-8")
    assert "addresses:\n      - BND-THM-001\n" in log

    project = load_project(config_path=str(block_style_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors, [str(d) for d in project.errors]


def test_block_sequence_rewrite_stops_before_the_next_item(block_style_project):
    """The walk down a block sequence must not run past the item it belongs
    to and into the next one's own lines."""
    (block_style_project / "items" / "log.yaml").write_text(
        "defaults:\n  type: log\n  prefix: LOG\n"
        "items:\n"
        "  - id: LOG-001\n    summary: First\n    addresses:\n      - CON-THM-001\n"
        "  - id: LOG-002\n    summary: Second\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(block_style_project), mapping)
    assert result.ok, result.errors
    log = (block_style_project / "items" / "log.yaml").read_text(encoding="utf-8")
    assert "      - BND-THM-001\n" in log
    assert "  - id: LOG-002\n" in log


def test_revise_reports_prose_left_pointing_at_a_renamed_id(compound_prefix_project):
    """Prose is deliberately never rewritten (see the test above), but leaving
    it alone *silently* is the wrong other half: a bare id that used to
    autolink renders as dead plain text afterward, and the command still
    reports success. The engine now names every line it did not touch and can
    no longer resolve."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    assert any(
        "items/dec.md" in ref and "CON-THM-001 -> BND-THM-001" in ref
        for ref in result.stale_references
    ), result.stale_references


def test_a_prose_id_that_still_resolves_is_not_reported_as_stale(tmp_path):
    """A mention that still resolves -- here through the renamed item's own
    `former_ids:` -- is not stale and must not be reported."""
    (tmp_path / "refdes.yaml").write_text(COMPOUND_PREFIX_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n"
        "  - id: CON-THM-002\n    former_ids: [CON-THM-001]\n"
        "    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-THM-002]\n"
        "---\n\n"
        "Prose mentioning CON-THM-001, which still resolves.\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(tmp_path), mapping)
    assert result.ok, result.errors
    assert result.stale_references == []


def test_revise_relabels_a_compound_prefix_in_the_id_ledger(compound_prefix_project):
    (compound_prefix_project / ".refdes").mkdir()
    (compound_prefix_project / ".refdes" / "ids.yaml").write_text(
        "burned:\n  CON-THM: 1\nallocated: []\n", encoding="utf-8"
    )
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    ledger_text = (compound_prefix_project / ".refdes" / "ids.yaml").read_text(encoding="utf-8")
    assert "BND-THM: 1" in ledger_text
    assert "CON-THM" not in ledger_text


# --------------------------------------------- hardware@3: constraint -> bound

def test_an_item_still_typed_constraint_at_v3_names_the_rename(tmp_path):
    """The type-level counterpart of the `constraint.title` -> `constraint.text`
    diagnostic (finding 4). Without it, moving the pin to v3 by hand reports a
    bare "unknown type 'constraint'." on every item in the project, and
    difflib's did-you-mean offers nothing: `constraint` and `bound` are not
    close enough to suggest."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 3, presets: [] }\n",
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
        "it is now 'bound'" in m and "hardware@3" in m and "standard upgrade" in m
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


def test_hardware_v4_restricts_equivalent_and_alternate_to_components(tmp_path):
    """`[]` in a `links:` target list means *unrestricted* -- that is what it
    deliberately means one type up on `decision.blocked_by:` -- so writing it
    on `equivalent`/`alternate` left the shipped dictionary accepting
    `equivalent: [REQ-001]` on a component with no diagnostic at all, while
    the spec (docs/design/standard-library.md 11) and every version of the
    docs said component -> component. v4 restores the intent."""
    project = _equivalence_project(tmp_path, version=4)
    assert any(
        "equivalent may point at ['component']" in d.message and "REQ-001" in d.message
        for d in project.errors
    ), [str(d) for d in project.errors]


def test_hardware_v4_still_allows_a_component_to_component_equivalence(tmp_path):
    """The restriction must not catch the case it exists to describe."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 4, presets: [] }\n",
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


@pytest.mark.parametrize("version", [1, 2, 3])
def test_earlier_versions_keep_the_unrestricted_behaviour(tmp_path, version):
    """Byte-identical forever: a project pinned below v4 sees no change at
    all, including the permissiveness v4 removes. Upgrading is what opts a
    project into the check."""
    project = _equivalence_project(tmp_path, version=version)
    assert not any("equivalent may point at" in d.message for d in project.errors), [
        str(d) for d in project.errors
    ]


def test_v4_is_the_version_init_pins(tmp_path):
    assert standards.latest_version("hardware") == 4


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


def test_hardware_v3_renames_constraint_to_bound_and_gains_refines(tmp_path):
    """finding 10 (narrower version): `bound` replaces `constraint`, prefix
    `CON` -> `BND`, additively gaining `refines: [bound]` alongside its
    existing `derives_from: [requirement, bound]`. `requirement` itself is
    untouched -- the finding's `capability` rename was explicitly rejected."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 3, presets: [] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert "constraint" not in project.types
    bound = project.types["bound"]
    assert bound.prefix == "BND"
    assert bound.links["refines"] == ["bound"]
    assert bound.links["derives_from"] == ["requirement", "bound"]

    requirement = project.types["requirement"]
    assert requirement.prefix == "REQ"
    assert requirement.links == {"refines": ["requirement"]}

    decision = project.types["decision"]
    assert decision.links["constrained_by"] == ["bound"]


def test_hardware_v1_and_v2_still_resolve_constraint_unchanged(tmp_path):
    """v3 is additive to the standard library, not a replacement -- a project
    still pinned at v1 or v2 sees no difference at all."""
    for version in (1, 2):
        (tmp_path / "refdes.yaml").write_text(
            "site: { title: T, out: _site }\n"
            f"standard: {{ base: hardware, version: {version}, presets: [] }}\n",
            encoding="utf-8",
        )
        project = load_project(config_path=str(tmp_path / "refdes.yaml"))
        assert "bound" not in project.types
        assert project.types["constraint"].prefix == "CON"


def test_standard_upgrade_to_3_renames_constraint_and_its_compound_prefix(tmp_path):
    """End-to-end against the real bundled standard: a v2-pinned project
    using this project's own compound-prefix convention, with a decision
    referencing the constraint through both a link and a checks: entry,
    upgrades cleanly to v3 -- the exact shape that blocked on first attempt
    against this project's own refdes.yaml (see the commit message)."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n  status: active\n"
        "items:\n"
        "  - id: CON-THM-001\n    text: Board power density\n    limit: \"<= 1 W/in^2\"\n",
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

    steps = revise.apply_standard_upgrade(str(tmp_path), 3)
    assert len(steps) == 1
    assert steps[0].result.ok, steps[0].result.errors
    assert steps[0].result.id_changes == {"CON-THM-001": "BND-THM-001"}

    con_text = (items / "con.yaml").read_text(encoding="utf-8")
    assert "type: bound" in con_text and "prefix: BND-THM" in con_text and "id: BND-THM-001" in con_text
    dec_text = (items / "dec.md").read_text(encoding="utf-8")
    assert "constrained_by: [BND-THM-001]" in dec_text
    assert "against: BND-THM-001" in dec_text

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    assert project.standard_version == 3
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors


# --------------------------------------------------------------------- diff


def test_diff_against_reports_changed_added_removed(lifecycle_project):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Edited.\n    status: active\n"
        "  - id: REQ-003\n    text: Brand new.\n    status: draft\n",
        encoding="utf-8",
    )
    project2 = _lc_build(lifecycle_project)
    baseline = lifecycle.load_baseline(project2, "rev-a")
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == ["REQ-001"]
    assert diff.added == ["REQ-003"]
    assert [r[0] for r in diff.removed] == ["REQ-002"]
    assert diff.removed[0][1] == "requirement"
    assert diff.unchanged_count == 1  # CMP-001


def test_latest_self_heals_after_a_baseline_is_deleted(lifecycle_project):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    # Resolve the release gate so the second stamp actually writes.
    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Covered.\n    status: active\n"
        "  - id: REQ-002\n    text: Active now.\n    status: active\n",
        encoding="utf-8",
    )
    (lifecycle_project / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n  - id: DEC-001\n    title: Covers both.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    _pin_lifecycle_citation(lifecycle_project)
    project2 = _lc_build(lifecycle_project)
    result = lifecycle.stamp(project2, kind="release", name="rel-a")
    assert result.status == "stamped"

    baselines = lifecycle.list_baselines(project)
    assert lifecycle.latest(baselines, kind="release").name == "rel-a"

    os.remove(lifecycle.baseline_path(project, "rel-a"))
    baselines2 = lifecycle.list_baselines(project)
    assert lifecycle.latest(baselines2, kind="release") is None
    assert lifecycle.latest(baselines2) is not None  # rev-a still there


# ----------------------------------------------------------------- identity


def test_stamped_by_defaults_to_os_username(lifecycle_project):
    project = _lc_build(lifecycle_project)
    assert project.baseline_identity == "os_user"
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    import getpass

    assert outcome.stamped_by == getpass.getuser()
    assert not any("baseline_identity" in d.message for d in project.warnings)


def test_git_identity_success(lifecycle_project, monkeypatch):
    (lifecycle_project / "refdes-project.yaml").write_text(
        "baseline_identity: git_identity\n", encoding="utf-8"
    )
    project = _lc_build(lifecycle_project)

    class _FakeResult:
        returncode = 0
        stdout = "J. Bin\n"

    monkeypatch.setattr(lifecycle.subprocess, "run", lambda *a, **k: _FakeResult())
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.stamped_by == "J. Bin"
    assert not any("baseline_identity" in d.message for d in project.warnings)


def test_git_identity_failure_falls_back_and_warns(lifecycle_project, monkeypatch):
    (lifecycle_project / "refdes-project.yaml").write_text(
        "baseline_identity: git_identity\n", encoding="utf-8"
    )
    project = _lc_build(lifecycle_project)

    def _boom(*a, **k):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(lifecycle.subprocess, "run", _boom)
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    import getpass

    assert outcome.stamped_by == getpass.getuser()
    assert any(
        "baseline_identity: git_identity" in d.message and "falls back" in d.message
        for d in project.warnings
    )


# ---------------------------------------------------------------- naming


@pytest.mark.parametrize("bad_name", ["../evil", "..", ".", "a/b", "a\\b", ""])
def test_invalid_baseline_names_are_rejected(bad_name):
    with pytest.raises(SchemaError):
        lifecycle.validate_name(bad_name)


def test_valid_baseline_names_are_accepted():
    for name in ("rev-b", "rev_c", "sent-to-fab-2026.08", "a"):
        lifecycle.validate_name(name)  # must not raise


# --------------------------------------------------------------------- CLI


def test_cli_revision_stamps_and_reports(lifecycle_project, capsys):
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "revision", "rev-a"])
    out = capsys.readouterr().out
    assert status == 0
    assert "revision 'rev-a' stamped: 3 items." in out
    assert os.path.isfile(lifecycle_project / ".refdes" / "baselines" / "rev-a.yaml")


def test_cli_release_blocked_prints_gate_table(lifecycle_project, capsys):
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "release", "rel-a"])
    captured = capsys.readouterr()
    assert status == 1
    assert "blocked -- not stamped" in captured.err
    assert "FAIL" in captured.err
    assert "draft_items" in captured.err
    assert not os.path.isfile(lifecycle_project / ".refdes" / "baselines" / "rel-a.yaml")


def test_the_whole_gate_table_lands_on_one_stream(lifecycle_project, capsys):
    """Rows used to pick their stream individually -- FAIL to stderr, pass and
    skipped to stdout -- so under any redirection the table arrived split
    across two files with its ordering destroyed. That is CI, which is the
    one place this report has to stay readable. The block is a failure report,
    so all of it goes to stderr, and none of it leaks into stdout."""
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "release", "rel-a"])
    captured = capsys.readouterr()
    assert status == 1

    assert "FAIL" in captured.err
    # Every row, not just the failing ones.
    for name in ("draft_items", "unpinned_citations", "uncovered_requirements",
                 "unverified_requirements", "info_check_failures",
                 "unaccepted_board_moves"):
        assert name in captured.err, name

    # No gate row on stdout: a row there is one that split off from the table.
    gate_rows = [
        line for line in captured.out.splitlines()
        if line.startswith(("  pass ", "  FAIL ", "  skipped "))
    ]
    assert gate_rows == [], gate_rows


def test_cli_release_success_prints_log_nudge(lifecycle_project, capsys):
    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Covered.\n    status: active\n"
        "  - id: REQ-002\n    text: Active now.\n    status: active\n",
        encoding="utf-8",
    )
    (lifecycle_project / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n  - id: DEC-001\n    title: Covers both.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    _pin_lifecycle_citation(lifecycle_project)
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "release", "rel-a"])
    out = capsys.readouterr().out
    assert status == 0
    assert "all gates passed" in out
    assert "Consider recording this in the design log" in out


def test_cli_invalid_name_exits_2(lifecycle_project, capsys):
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "revision", ".."])
    err = capsys.readouterr().err
    assert status == 2
    assert "not a valid revision/release name" in err


def test_cli_floor_violation_blocks_both_commands(tmp_path):
    """The unconditional error floor -- the same one `check` already has."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n",  # missing required text
        encoding="utf-8",
    )
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "revision", "rev-a"])
    assert status == 1
    assert not os.path.isdir(tmp_path / ".refdes" / "baselines")


def test_draft_project_is_the_regression_case(lifecycle_project, capsys):
    """A project that never stamps anything behaves exactly as today: check/
    build are unaffected, and audit reports the draft state rather than
    erroring on the absence of any baseline."""
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "check"])
    assert status == 0  # no build errors from lifecycle machinery existing

    status2 = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert status2 == 0
    assert "(none stamped yet -- project is in draft)" in out
    assert "(no revision stamped yet)" in out
    assert "(no release stamped yet)" in out


def test_audit_reports_both_diffs(lifecycle_project, capsys):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert status == 0
    assert "Since last revision (rev-a" in out
    assert "Since last release: (no release stamped yet)" in out
    assert "(3 unchanged)" in out


# ------------------------------------------------------------- generated blocks

BLOCKS_SCHEMA = """\
site: {title: "Blocks Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
boards:
  power: {label: Power}
  thermal: {label: Thermal}
link_types:
  satisfies:      { inverse: satisfied_by, label: "Satisfies" }
  constrained_by: { inverse: constrains,   label: "Constrained by" }
  verifies:       { inverse: verified_by,  label: "Verifies" }
  selects:        { inverse: selected_by,  label: "Selects", trace: false }
types:
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  constraint:
    prefix: CON
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    fields:
      title:          { type: text, required: true, on_change: invalidate }
      status:         { type: enum, choices: [proposed, accepted, on_hold], default: proposed, on_change: invalidate }
      schematic_page: { type: text, on_change: invalidate }
      tags:           { type: list, on_change: ignore }
      checks:         { type: checks, on_change: invalidate }
    links:
      satisfies:      [requirement]
      constrained_by: [constraint]
      selects:        [component]
    body: { on_change: invalidate }
  test:
    prefix: TST
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links:
      verifies: [requirement]
    body: { on_change: invalidate }
"""

BLOCKS_ITEMS = {
    "req-001.md": """\
---
id: REQ-001
type: requirement
text: Input voltage range.
---
""",
    "con-001.md": """\
---
id: CON-001
type: constraint
title: Thermal budget.
---
""",
    "cmp-001.md": """\
---
id: CMP-001
type: component
title: TPS62913.
---
""",
    "dec-001.md": """\
---
id: DEC-001
type: decision
title: Buck topology.
status: accepted
schematic_page: "12"
tags: [layout, review]
board: power
satisfies: [REQ-001]
constrained_by: [CON-001]
selects: [CMP-001]
---
""",
    "dec-002.md": """\
---
id: DEC-002
type: decision
title: Inductor choice.
status: proposed
schematic_page: "7"
tags: [review]
board: power
---
""",
    "dec-003.md": """\
---
id: DEC-003
type: decision
title: Enclosure material.
status: on_hold
schematic_page: "12"
board: thermal
---
""",
    "tst-001.md": """\
---
id: TST-001
type: test
title: Load regulation sweep.
verifies: [REQ-001]
---
""",
}


@pytest.fixture
def blocks_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BLOCKS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in BLOCKS_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    (tmp_path / "pages").mkdir()
    return tmp_path


def _page_with_block(project_root, directive):
    (project_root / "pages" / "index.md").write_text(
        f"# Overview\n\n{directive}\n", encoding="utf-8"
    )


def _index_page(blocks_project):
    project = _build_at(blocks_project)
    page = next(p for p in project.pages if p.slug == "index")
    return project, page


def test_index_groups_by_enum_in_declared_choices_order(blocks_project):
    """Heading order follows `choices:` (proposed, accepted, on_hold), not
    alphabetical (accepted, on_hold, proposed) -- a distinguishing case."""
    _page_with_block(blocks_project, '{{index by="status" type="decision"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    headings = [h for h in ["proposed", "accepted", "on_hold"] if f"<h4>{h}</h4>" in page.body_html]
    positions = [page.body_html.index(f"<h4>{h}</h4>") for h in headings]
    assert positions == sorted(positions)
    assert headings == ["proposed", "accepted", "on_hold"]
    assert "DEC-002" in page.body_html  # proposed
    assert "DEC-001" in page.body_html  # accepted
    assert "DEC-003" in page.body_html  # on_hold


def test_index_groups_by_text_field_lexicographically_with_unset_last(blocks_project):
    """`schematic_page` is text, not a number: "12" < "7" lexicographically.
    A decision with no schematic_page value groups under (unset), sorted last."""
    (blocks_project / "items" / "dec-004.md").write_text(
        "---\nid: DEC-004\ntype: decision\ntitle: No page yet.\n---\n", encoding="utf-8"
    )
    _page_with_block(blocks_project, '{{index by="schematic_page" type="decision"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    order = [h for h in ["12", "7", "(unset)"] if f"<h4>{h}</h4>" in page.body_html]
    assert order == ["12", "7", "(unset)"]


def test_index_list_valued_field_files_item_under_every_value(blocks_project):
    _page_with_block(blocks_project, '{{index by="tags" type="decision"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "<h4>layout</h4>" in page.body_html
    assert "<h4>review</h4>" in page.body_html
    # DEC-001 (tags: [layout, review]) appears under both headings -- the ID
    # cell's text is picked up by the page's own _linkify pass for free, so
    # each appearance is both an href and the link text: 2 headings x 2.
    assert page.body_html.count("DEC-001") == 4
    assert page.body_html.count('href="dec-001.html"') == 2


def test_index_board_scoping(blocks_project):
    _page_with_block(blocks_project, '{{index by="status" type="decision" board="thermal"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "DEC-003" in page.body_html
    assert "DEC-001" not in page.body_html
    assert "DEC-002" not in page.body_html


def test_index_empty_result_is_not_an_error(blocks_project):
    # TST-001 has no board, so board="thermal" matches zero test items.
    _page_with_block(blocks_project, '{{index by="title" type="test" board="thermal"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "No test items." in page.body_html


def test_index_unknown_type_suggests_a_correction(blocks_project):
    _page_with_block(blocks_project, '{{index by="status" type="decisoin"}}')
    project, _page = _index_page(blocks_project)
    assert any(
        "unknown type 'decisoin'" in d.message and "Did you mean 'decision'?" in d.message
        for d in project.errors
    )


def test_index_unknown_field_names_declared_fields(blocks_project):
    _page_with_block(blocks_project, '{{index by="pageno" type="decision"}}')
    project, _page = _index_page(blocks_project)
    msg = next(d.message for d in project.errors if "has no field" in d.message)
    assert "no field 'pageno'" in msg
    assert "schematic_page" in msg


def test_index_non_groupable_field_type_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{index by="checks" type="decision"}}')
    project, _page = _index_page(blocks_project)
    assert any("not a groupable field" in d.message for d in project.errors)


def test_index_unknown_board_suggests_a_correction(blocks_project):
    _page_with_block(blocks_project, '{{index by="status" type="decision" board="powr"}}')
    project, _page = _index_page(blocks_project)
    assert any(
        "unknown board 'powr'" in d.message and "Did you mean 'power'?" in d.message
        for d in project.errors
    )


def test_index_unknown_parameter_names_accepted_ones(blocks_project):
    _page_with_block(blocks_project, '{{index by="status" type="decision" sortt="asc"}}')
    project, _page = _index_page(blocks_project)
    msg = next(d.message for d in project.errors if "unknown parameter" in d.message)
    assert "'sortt'" in msg
    assert "by, type, board" in msg


def test_index_missing_required_parameter_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{index type="decision"}}')
    project, _page = _index_page(blocks_project)
    assert any("missing required parameter 'by'" in d.message for d in project.errors)


def test_block_directive_inside_a_fenced_code_example_is_not_executed(blocks_project):
    """A doc showing "here's how you write {{index ...}}" inside a fenced
    example must render that line as literal example text, not run it as a
    live directive -- the trap docs/blocks.md's own examples originally fell
    into (extraction happens on raw markdown before md.render, so it has no
    idea a fence is present unless it looks for one itself)."""
    _page_with_block(
        blocks_project,
        '```markdown\n{{index by="status" type="decision"}}\n```',
    )
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "index-table" not in page.body_html
    assert "{{index by=" in page.body_html  # survives, HTML-escaped, inside <pre><code>


def test_unrecognized_block_name_passes_through_as_literal_text(blocks_project):
    _page_with_block(blocks_project, '{{TBD some note to self}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "{{TBD some note to self}}" in page.body_html


def test_index_only_local_items_not_imports(blocks_project):
    """An imported item must never appear in a project-generated index --
    that is what makes the block trustworthy as *this* project's own view."""
    import json

    upstream = {
        "title": "Upstream",
        "version": "1",
        "items": [
            {
                "id": "DEC-X-001",
                "type": "decision",
                "title": "Foreign.",
                "fields": {"title": "Foreign.", "status": "accepted"},
                "links": {},
                "content_hash": "upstreamhash01",
            }
        ],
    }
    (blocks_project / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
    schema = BLOCKS_SCHEMA + (
        '\nimports:\n  - name: platform\n    items: upstream.json\n    version: "1"\n'
    )
    (blocks_project / "refdes.yaml").write_text(schema, encoding="utf-8")
    _page_with_block(blocks_project, '{{index by="status" type="decision"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "DEC-X-001" in project.items  # imported, resolvable...
    assert "DEC-X-001" not in page.body_html  # ...but never in a generated index


def test_cascade_up_follows_declared_links_within_trace_true_default(blocks_project):
    """`selects` is `trace: false` in this schema, so it's excluded from the
    default `via=` set -- CMP-001 must not appear."""
    _page_with_block(blocks_project, '{{cascade from="DEC-001" direction="up"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "REQ-001" in page.body_html
    assert "CON-001" in page.body_html
    assert "CMP-001" not in page.body_html


def test_cascade_explicit_via_can_include_a_non_traced_link(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="DEC-001" direction="up" via="selects"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "CMP-001" in page.body_html
    assert "REQ-001" not in page.body_html


def test_cascade_down_follows_backlinks(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="REQ-001" direction="down"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "DEC-001" in page.body_html  # satisfied_by
    assert "TST-001" in page.body_html  # verified_by


def test_cascade_both_renders_two_labeled_branches(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="REQ-001" direction="both"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert ">Upward<" in page.body_html
    assert ">Downward<" in page.body_html
    assert "DEC-001" in page.body_html


def test_cascade_depth_limits_the_walk(blocks_project):
    # DEC-002 has no outgoing links, so depth=1 from it should show nothing.
    _page_with_block(blocks_project, '{{cascade from="DEC-002" direction="up" depth="1"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "nothing found" in page.body_html


def test_cascade_unknown_root_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="REQ-999" direction="up"}}')
    project, _page = _index_page(blocks_project)
    assert any("REQ-999 does not exist" in d.message for d in project.errors)


def test_cascade_unknown_direction_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="DEC-001" direction="sideways"}}')
    project, _page = _index_page(blocks_project)
    assert any(
        "unknown direction 'sideways'" in d.message and "down, up, both" in d.message
        for d in project.errors
    )


def test_cascade_missing_required_parameter_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="DEC-001"}}')
    project, _page = _index_page(blocks_project)
    assert any("missing required parameter 'direction'" in d.message for d in project.errors)


def test_cascade_unknown_via_link_type_suggests_a_correction(blocks_project):
    _page_with_block(
        blocks_project, '{{cascade from="DEC-001" direction="up" via="satisfyes"}}'
    )
    project, _page = _index_page(blocks_project)
    assert any(
        "unknown link type 'satisfyes'" in d.message and "Did you mean 'satisfies'?" in d.message
        for d in project.errors
    )


def test_cascade_non_positive_depth_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="DEC-001" direction="up" depth="0"}}')
    project, _page = _index_page(blocks_project)
    assert any("depth must be a positive integer" in d.message for d in project.errors)


DIAMOND_SCHEMA = """\
site: {title: "Diamond Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
link_types:
  next: { inverse: prev, label: "Next" }
types:
  node:
    prefix: NODE
    fields:
      title: { type: text, required: true }
    links:
      next: [node]
"""


@pytest.fixture
def diamond_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(DIAMOND_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    # NODE-001 -> NODE-002 -> NODE-004, NODE-001 -> NODE-003 -> NODE-004:
    # two paths reconverge on NODE-004.
    graph = {
        "NODE-001": ("Root", ["NODE-002", "NODE-003"]),
        "NODE-002": ("Left", ["NODE-004"]),
        "NODE-003": ("Right", ["NODE-004"]),
        "NODE-004": ("Sink", []),
    }
    for node_id, (title, targets) in graph.items():
        next_yaml = f"next: [{', '.join(targets)}]\n" if targets else ""
        (items / f"{node_id.lower()}.md").write_text(
            f"---\nid: {node_id}\ntype: node\ntitle: {title}\n{next_yaml}---\n",
            encoding="utf-8",
        )
    (tmp_path / "pages").mkdir()
    return tmp_path


def test_cascade_marks_a_reconverged_node_already_shown(diamond_project):
    _page_with_block(diamond_project, '{{cascade from="NODE-001" direction="up"}}')
    project, page = _index_page(diamond_project)
    assert not project.errors
    # Rendered twice (once fully, once as the reconverged leaf) -- the page's
    # own _linkify pass also bare-links each occurrence's plain-text id, so
    # 'data-ref="NODE-004"' is the reliable count, not the raw substring.
    assert page.body_html.count('data-ref="NODE-004"') == 2
    assert page.body_html.count("already shown above") == 1


# --------------------------------------------------------- figure identity/numbering

FIG_SCHEMA = """\
site: {title: "Figures Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
boards:
  power: {label: Power}
types:
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links: {}
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true }
    links: {}
"""

FIG_PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def fig_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(FIG_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    figures = items / "figures"
    figures.mkdir()
    (figures / "curve.png").write_bytes(FIG_PNG)
    (items / "dec-001.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Buck topology.\nboard: power\n---\n\n"
        'See [[fig:fig-curve]] and [[fig:fig-curve|the curve above]].\n'
        'Also [[fig:fig-nope]].\n\n'
        '![the curve](figures/curve.png){id="fig-curve" caption="Efficiency"}\n',
        encoding="utf-8",
    )
    (items / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: TPS62913.\nboard: power\n---\n\n"
        "Cross-item: [[fig:fig-curve]].\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text(
        "# Overview\n\nPage ref: [[fig:fig-curve]].\n", encoding="utf-8"
    )
    return tmp_path


def test_figure_id_is_registered_and_gets_an_html_id(fig_project):
    project = _build_at(fig_project)
    assert not project.errors
    assert "fig-curve" in project.figures
    owner, source_file, _line = project.figures["fig-curve"]
    assert owner == "DEC-001"
    assert source_file == "items/dec-001.md"


def test_duplicate_figure_id_is_an_error_naming_both_locations(fig_project):
    (fig_project / "items" / "cmp-002.md").write_text(
        "---\nid: CMP-002\ntype: component\ntitle: Dup.\nboard: power\n---\n\n"
        '![dup](figures/curve.png){id="fig-curve"}\n',
        encoding="utf-8",
    )
    project = _build_at(fig_project)
    # cmp-002.md sorts before dec-001.md, so CMP-002 registers 'fig-curve'
    # first and DEC-001's own use of it is the one that collides.
    msg = next(d.message for d in project.errors if "figure id" in d.message)
    assert "figure id 'fig-curve' is already used by CMP-002" in msg
    assert "items/cmp-002.md" in msg
    assert "Figure ids must be unique across the project" in msg


def test_figure_numbers_per_document_own_item_page(fig_project):
    project = _build_at(fig_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert "<figcaption>Figure 1 — Efficiency</figcaption>" in html
    assert '<a class="ref fig-ref" href="#fig-curve">Figure 1</a>' in html
    assert '<a class="ref fig-ref" href="#fig-curve">the curve above</a>' in html
    assert '<span class="ref ref-missing" title="unknown figure">fig-nope</span>' in html
    assert any(
        "reference to figure 'fig-nope', which does not exist" in d.message
        for d in project.warnings
    )


def test_figure_cross_item_reference_fails_on_the_items_own_page(fig_project):
    out = _build_and_render(fig_project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert '<span class="ref ref-missing" title="unknown figure">fig-curve</span>' in html


def test_figure_cross_item_reference_resolves_in_the_combined_document(fig_project):
    out = _build_and_render(fig_project)
    html = open(os.path.join(out, "document.html"), encoding="utf-8").read()
    assert html.count("Figure 1") >= 2  # DEC-001's own figure and CMP-001's cross-ref
    assert '<a class="ref fig-ref" href="#fig-curve">Figure 1</a>' in html


def test_figure_reference_on_a_narrative_page_that_lacks_it_warns(fig_project):
    project = _build_at(fig_project)
    out = render.render_site(project)
    assert any(
        "exists on DEC-001 but is not rendered on this page" in d.message
        for d in project.warnings
    )
    index_html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert '<span class="ref ref-missing" title="unknown figure">fig-curve</span>' in index_html


def test_check_catches_a_dangling_figure_reference_without_rendering(fig_project):
    """`refdes check` never calls render_site, so a dangling [[fig:...]] has
    to be caught by build() itself -- the same way a dangling [[ITEM-ID]]
    already is -- or `check` would silently miss what `build` catches."""
    project = _build_at(fig_project)  # build() only, exactly what `check` runs
    assert any(
        "reference to figure 'fig-nope', which does not exist" in d.message
        for d in project.warnings
    )


def test_build_does_not_double_warn_a_dangling_figure_reference(fig_project):
    """The same project run through build() then render_site() (what `refdes
    build` actually does) must warn about a nonexistent figure id exactly
    once, not once from the eager check and again from every document
    resolve_figures happens to touch."""
    project = _build_at(fig_project)
    render.render_site(project)
    matches = [
        d.message for d in project.warnings
        if "reference to figure 'fig-nope', which does not exist" in d.message
    ]
    assert len(matches) == 1


# -------------------------------------------------- explicit reference regression

def test_explicit_item_reference_does_not_nest_duplicate_links(blocks_project):
    """Regression: _linkify's bare-reference pass used to re-scan its own
    explicit-reference substitutions, turning [[ID]] into nested <a><a>...
    tags because the target id also appears as the link's own text/attrs."""
    (blocks_project / "items" / "req-001.md").write_text(
        "---\nid: REQ-001\ntype: requirement\ntext: Input voltage range.\n---\n\n"
        "See [[CON-001]] for the thermal budget.\n",
        encoding="utf-8",
    )
    project = _build_at(blocks_project)
    html = project.items["REQ-001"].body_html
    assert html.count("<a") == 1
    assert '<a class="ref" href="con-001.html" data-ref="CON-001">CON-001</a>' in html


# --------------------------------------------------------------------- blocked_by

BLOCKED_SCHEMA = """\
site: {title: "Blocked Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies:  { inverse: satisfied_by, label: "Satisfies" }
  blocked_by: { inverse: blocks,       label: "Blocked by" }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [proposed, accepted, on_hold], default: proposed, on_change: invalidate }
    satisfying_statuses: [accepted]
    links:
      satisfies:  [requirement]
      blocked_by: []
    body: { on_change: invalidate }
"""

BLOCKED_ITEMS = {
    "req-001.md": """\
---
id: REQ-001
type: requirement
text: Connector pin allocation must be final.
---
""",
    "dec-001.md": """\
---
id: DEC-001
type: decision
title: Root open question.
status: on_hold
---
""",
    "dec-002.md": """\
---
id: DEC-002
type: decision
title: Depends on DEC-001.
status: proposed
blocked_by: [DEC-001]
---
""",
    "dec-003.md": """\
---
id: DEC-003
type: decision
title: Satisfies REQ-001, depends on DEC-002.
status: proposed
satisfies: [REQ-001]
blocked_by: [DEC-002]
---
""",
}


@pytest.fixture
def blocked_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BLOCKED_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in BLOCKED_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_blocked_by_resolves_the_transitive_root(blocked_project):
    project = _build_at(blocked_project)
    assert not project.errors
    chains = {c.item_id: c for c in project.blocked_chains}
    assert chains["DEC-002"].path == ["DEC-002", "DEC-001"]
    assert chains["DEC-002"].root_id == "DEC-001"
    assert chains["DEC-002"].root_status == "on_hold"
    # The declared edge is direct, but this one resolves through DEC-002 to
    # the same structural root -- the path is shown, not collapsed.
    assert chains["DEC-003"].path == ["DEC-003", "DEC-002", "DEC-001"]
    assert chains["DEC-003"].root_id == "DEC-001"


def test_blocked_by_target_of_any_type_no_status_restriction(blocked_project):
    """blocked_by may point at any item type, in any status, with nothing
    checked at declaration time."""
    (blocked_project / "items" / "dec-004.md").write_text(
        "---\nid: DEC-004\ntype: decision\ntitle: Blocked on a requirement.\n"
        "status: proposed\nblocked_by: [REQ-001]\n---\n",
        encoding="utf-8",
    )
    project = _build_at(blocked_project)
    assert not project.errors
    chain = next(c for c in project.blocked_chains if c.item_id == "DEC-004")
    assert chain.root_id == "REQ-001"


def test_blocked_by_cycle_is_a_hard_error_naming_the_full_path(blocked_project):
    text = (blocked_project / "items" / "dec-001.md").read_text(encoding="utf-8")
    text = text.replace("status: on_hold", "status: on_hold\nblocked_by: [DEC-003]")
    (blocked_project / "items" / "dec-001.md").write_text(text, encoding="utf-8")

    project = _build_at(blocked_project)
    errors = [d.message for d in project.errors if "blocked_by cycle" in d.message]
    assert len(errors) == 1  # reported once, not once per node in the cycle
    assert "DEC-001 -> DEC-003 -> DEC-002 -> DEC-001" in errors[0]
    # The graph is broken -- nothing downstream should trust partial chains.
    assert project.blocked_chains == []


def test_blocked_by_self_loop_is_a_cycle(blocked_project):
    text = (blocked_project / "items" / "dec-001.md").read_text(encoding="utf-8")
    text = text.replace("status: on_hold", "status: on_hold\nblocked_by: [DEC-001]")
    (blocked_project / "items" / "dec-001.md").write_text(text, encoding="utf-8")
    project = _build_at(blocked_project)
    assert any("blocked_by cycle: DEC-001 -> DEC-001" in d.message for d in project.errors)


def test_stale_blocker_is_an_info_diagnostic(blocked_project):
    """Settled per satisfying_statuses, edge still declared -- info, not a
    warning or error, and default-hidden like every other info finding."""
    text = (blocked_project / "items" / "dec-001.md").read_text(encoding="utf-8")
    text = text.replace("status: on_hold", "status: accepted")
    (blocked_project / "items" / "dec-001.md").write_text(text, encoding="utf-8")

    project = _build_at(blocked_project)
    assert not project.errors
    infos = [d.message for d in project.infos if "blocked_by DEC-001" in d.message]
    assert len(infos) == 1
    assert "which is now 'accepted'" in infos[0]
    assert "is it still blocked?" in infos[0]
    # Never counted as a warning/error -- only visible via project.infos.
    assert not any("blocked_by DEC-001" in d.message for d in project.warnings)


def test_no_stale_diagnostic_for_a_type_with_no_settled_notion(blocked_project):
    """A blocker of a type that declares neither satisfying_statuses nor
    verifying_statuses never triggers the stale check -- 'unconfigured means
    nothing special happens', same default used throughout the schema
    engine."""
    (blocked_project / "items" / "dec-004.md").write_text(
        "---\nid: DEC-004\ntype: decision\ntitle: Blocked on a requirement.\n"
        "status: proposed\nblocked_by: [REQ-001]\n---\n",
        encoding="utf-8",
    )
    project = _build_at(blocked_project)
    assert not any("blocked_by REQ-001" in d.message for d in project.infos)


def test_coverage_claimed_warning_includes_the_blocker_chain(blocked_project):
    project = _build_at(blocked_project)
    msg = next(
        d.message for d in project.warnings
        if d.item_id == "REQ-001" and "claimed but not verified" in d.message
    )
    assert "claimed by DEC-003, which is blocked_by DEC-002 <- DEC-001 (on_hold)" in msg


def test_coverage_aggregate_line_for_a_single_unambiguous_root(blocked_project):
    project = _build_at(blocked_project)
    assert any(
        "1 requirement(s) unsettled because DEC-001 is on_hold" in d.message
        for d in project.warnings
    )


def test_coverage_aggregate_line_excluded_when_claimers_trace_different_roots(blocked_project):
    """Deliberately conservative: a requirement whose several claimers trace
    to *different* root blockers is left out of the aggregate grouping --
    the per-item warning still names both chains in full."""
    (blocked_project / "items" / "dec-005.md").write_text(
        "---\nid: DEC-005\ntype: decision\ntitle: A second, independent root.\n"
        "status: on_hold\n---\n",
        encoding="utf-8",
    )
    (blocked_project / "items" / "dec-006.md").write_text(
        "---\nid: DEC-006\ntype: decision\ntitle: Also satisfies REQ-001.\n"
        "status: proposed\nsatisfies: [REQ-001]\nblocked_by: [DEC-005]\n---\n",
        encoding="utf-8",
    )
    project = _build_at(blocked_project)
    assert not any("unsettled because" in d.message for d in project.warnings)
    msg = next(
        d.message for d in project.warnings
        if d.item_id == "REQ-001" and "claimed but not verified" in d.message
    )
    assert "DEC-003, which is blocked_by DEC-002 <- DEC-001 (on_hold)" in msg
    assert "DEC-006, which is blocked_by DEC-005 (on_hold)" in msg


def test_audit_reports_blocked_chains(blocked_project):
    status = cli_mod.main(["-c", str(blocked_project / "refdes.yaml"), "audit"])
    assert status == 0


def test_audit_blocked_chains_section(blocked_project, capsys):
    cli_mod.main(["-c", str(blocked_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "Blocked chains:" in out
    assert "DEC-002 <- DEC-001 (on_hold, root)" in out
    assert "DEC-003 <- DEC-002 <- DEC-001 (on_hold, root)" in out


def test_audit_blocked_chains_section_is_none_with_no_edges(tmp_path, capsys):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "Blocked chains:\n  (none)" in out


def test_audit_marks_a_stale_chain(blocked_project, capsys):
    text = (blocked_project / "items" / "dec-001.md").read_text(encoding="utf-8")
    text = text.replace("status: on_hold", "status: accepted")
    (blocked_project / "items" / "dec-001.md").write_text(text, encoding="utf-8")
    cli_mod.main(["-c", str(blocked_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "stale: edge still declared, blocker settled" in out


def test_item_page_shows_the_blocked_panel_with_resolved_root(blocked_project):
    project = _build_at(blocked_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "dec-003.html"), encoding="utf-8").read()
    assert "Blocked" in html
    assert '<a class="ref" href="dec-002.html" data-ref="DEC-002">DEC-002</a>' in html
    assert '<a class="ref" href="dec-001.html" data-ref="DEC-001">DEC-001</a>' in html
    assert "on_hold, root" in html


def test_coverage_html_shows_the_inline_blocker_chain(blocked_project):
    project = _build_at(blocked_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "coverage.html"), encoding="utf-8").read()
    assert 'blocked-note">← DEC-002 ← DEC-001 (on_hold)' in html


# ------------------------------------------------ parts indexing and equivalence

PARTS_SCHEMA = """\
site: {title: "Parts Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
item_layout: workspace
workspaces:
  alpha: {label: Alpha}
  beta: {label: Beta}
boards:
  main: {label: Main}
link_types:
  equivalent: { inverse: equivalent, label: "Equivalent" }
  alternate:  { inverse: alternate,  label: "Alternate" }
types:
  component:
    prefix: CMP
    fields:
      title:       { type: text, required: true, on_change: invalidate }
      part_number: { type: text, on_change: invalidate }
      rationale:   { type: text, on_change: invalidate, required_when: {links: alternate} }
      datasheets:  { type: citations, on_change: invalidate }
    links:
      equivalent: [component]
      alternate:  [component]
    body: { on_change: invalidate }
"""

PARTS_ITEMS = {
    ("alpha", "main", "cmp-001.md"): """\
---
id: CMP-001
type: component
title: Main MCU.
part_number: STM32G474
workspace: alpha
board: main
---
""",
    ("beta", "main", "cmp-002.md"): """\
---
id: CMP-002
type: component
title: Also uses the same MCU, different workspace.
part_number: STM32G474
workspace: beta
board: main
---
""",
    ("alpha", "main", "cmp-003.md"): """\
---
id: CMP-003
type: component
title: A near-miss part number, deliberately different.
part_number: STM32G474RET6
workspace: alpha
board: main
---
""",
    ("alpha", "main", "cmp-004.md"): """\
---
id: CMP-004
type: component
title: Cited a datasheet for a part never made into a component.
workspace: alpha
board: main
datasheets:
  - url: "https://example.com/opamp.pdf"
    part_number: LM358
---
""",
}


@pytest.fixture
def parts_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(PARTS_SCHEMA, encoding="utf-8")
    for (workspace, board, name), text in PARTS_ITEMS.items():
        d = tmp_path / "items" / workspace / board
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")
    return tmp_path


def _parts_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def test_by_part_number_exact_string_near_miss_stays_separate(parts_project):
    project = _parts_build(parts_project)
    assert not project.errors
    parts = citations_mod.by_part_number(project)
    assert set(parts) == {"STM32G474", "STM32G474RET6", "LM358"}
    g474 = parts["STM32G474"]
    assert sorted(c.id for c in g474.components) == ["CMP-001", "CMP-002"]
    g474ret6 = parts["STM32G474RET6"]
    assert [c.id for c in g474ret6.components] == ["CMP-003"]
    # Sharing a component list would be the exact bug exact-string indexing
    # exists to prevent.
    assert g474.components != g474ret6.components


def test_by_part_number_covers_citation_only_parts(parts_project):
    project = _parts_build(parts_project)
    parts = citations_mod.by_part_number(project)
    lm358 = parts["LM358"]
    assert lm358.components == []
    assert [item.id for item, _status in lm358.citers] == ["CMP-004"]


def test_by_part_number_board_and_workspace_scoping(parts_project):
    project = _parts_build(parts_project)
    alpha_parts = citations_mod.by_part_number(project, workspace="alpha")
    assert "STM32G474" in alpha_parts
    assert [c.id for c in alpha_parts["STM32G474"].components] == ["CMP-001"]

    beta_parts = citations_mod.by_part_number(project, workspace="beta")
    assert [c.id for c in beta_parts["STM32G474"].components] == ["CMP-002"]

    board_parts = citations_mod.by_part_number(project, board="main")
    assert sorted(c.id for c in board_parts["STM32G474"].components) == ["CMP-001", "CMP-002"]


def test_part_usage_boards_property(parts_project):
    project = _parts_build(parts_project)
    usage = citations_mod.by_part_number(project)["STM32G474"]
    assert usage.boards == ["main"]


def test_cross_workspace_lint_does_not_fire_on_shared_part_numbers(parts_project):
    """The whole point of the parts page: it's a derived view, not an
    authored link. Two workspaces' components sharing a part_number is a
    coincidence of the BOM, never a declared dependency, so the lint built
    in an earlier step -- which walks item.links exclusively -- must never
    fire on it. CMP-001 (alpha) and CMP-002 (beta) share STM32G474 and
    declare no links to each other at all."""
    project = _parts_build(parts_project)
    project.cross_workspace_severity = "error"  # maximize the chance of catching a false positive
    workspaces_mod.lint_cross_workspace_references(project)
    assert not project.errors
    assert not project.warnings


def test_parts_pages_render_global_board_and_workspace_scoped(parts_project):
    project = _parts_build(parts_project)
    out = render.render_site(project)
    assert os.path.isfile(os.path.join(out, "parts.html"))
    assert os.path.isfile(os.path.join(out, "parts-main.html"))
    assert os.path.isfile(os.path.join(out, "parts-alpha.html"))
    assert os.path.isfile(os.path.join(out, "parts-beta.html"))

    global_html = open(os.path.join(out, "parts.html"), encoding="utf-8").read()
    assert "STM32G474" in global_html
    assert "STM32G474RET6" in global_html
    assert "LM358" in global_html

    alpha_html = open(os.path.join(out, "parts-alpha.html"), encoding="utf-8").read()
    assert 'data-ref="CMP-001"' in alpha_html
    # Different workspace -- previews_json legitimately embeds every item's
    # data regardless of page, so check the actual rendered table content.
    assert 'data-ref="CMP-002"' not in alpha_html


def test_a_page_named_parts_collides_with_the_report(parts_project):
    pages = parts_project / "pages"
    pages.mkdir()
    (pages / "parts.md").write_text("# Hand-written page\n", encoding="utf-8")
    project = _parts_build(parts_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)


def test_component_page_links_to_also_used_elsewhere(parts_project):
    project = _parts_build(parts_project)
    out = render.render_site(project)
    cmp001 = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert 'href="parts.html#part-stm32g474">also used elsewhere</a>' in cmp001
    # CMP-003's part number is used by no one else.
    cmp003 = open(os.path.join(out, "cmp-003.html"), encoding="utf-8").read()
    assert "also used elsewhere" not in cmp003


def test_audit_reports_a_parts_section(parts_project, capsys):
    cli_mod.main(["-c", str(parts_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "Parts:" in out
    assert "STM32G474" in out
    assert "used by CMP-001, CMP-002 (components)" in out
    assert "LM358" in out
    assert "used by CMP-004 (citation)" in out


def test_audit_parts_section_breaks_out_workspaces(parts_project, capsys):
    """CMP-001 (alpha) and CMP-002 (beta) share STM32G474 -- a project with a
    workspaces: registry should see that split named, the same way boards
    already are."""
    cli_mod.main(["-c", str(parts_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "— workspaces: alpha, beta" in out


def test_audit_parts_section_omits_workspace_line_for_a_flat_project(tmp_path, capsys):
    """A project with no workspaces: registry never populates item.workspace
    at all, so the line must not appear -- not even empty -- rather than
    growing a confusing always-blank row."""
    (tmp_path / "refdes.yaml").write_text(
        "site: {title: t, out: _site}\n"
        "boards:\n  power: {label: Power}\n"
        "types:\n"
        "  component:\n"
        "    prefix: CMP\n"
        "    fields:\n"
        "      title: {type: text, required: true}\n"
        "      part_number: {type: text}\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: t.\n"
        "part_number: TPS62913\nboard: power\n---\n",
        encoding="utf-8",
    )
    cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "— board: power" in out
    assert "workspace" not in out


def test_nav_parts_link_present_when_parts_exist(parts_project):
    project = _parts_build(parts_project)
    tree = nav_mod.build_nav(project, dashboard_href="index.html")

    def flatten(nodes):
        for n in nodes:
            yield n
            yield from flatten(n.children)

    hrefs = {n.href for n in flatten(tree)}
    assert "parts.html" in hrefs


def test_nav_parts_link_absent_with_no_part_numbers(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    project = _build_at(tmp_path)
    tree = nav_mod.build_nav(project, dashboard_href="index.html")

    def flatten(nodes):
        for n in nodes:
            yield n
            yield from flatten(n.children)

    hrefs = {n.href for n in flatten(tree)}
    assert "parts.html" not in hrefs


def test_equivalent_rationale_is_optional(parts_project):
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Drop-in second source.\n"
        "workspace: alpha\nboard: main\nequivalent: [CMP-001]\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    assert not project.errors


def test_alternate_requires_rationale(parts_project):
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Functionally close, not drop-in.\n"
        "workspace: alpha\nboard: main\nalternate: [CMP-001]\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    assert any(
        "'rationale' is required" in d.message and "alternate" in d.message
        for d in project.errors
    )


def test_alternate_with_rationale_passes(parts_project):
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Functionally close, not drop-in.\n"
        "workspace: alpha\nboard: main\nalternate: [CMP-001]\n"
        "rationale: Different tolerance; verify before substituting.\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    assert not project.errors


def test_self_inverse_link_merges_both_directions_on_the_declaring_side(parts_project):
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Functionally close.\n"
        "workspace: alpha\nboard: main\nalternate: [CMP-001]\n"
        "rationale: Different tolerance.\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    out = render.render_site(project)
    declaring = open(os.path.join(out, "cmp-005.html"), encoding="utf-8").read()
    assert 'class="tight self-inverse"' in declaring
    assert 'data-ref="CMP-001"' in declaring.split('class="tight self-inverse"')[1].split("</ul>")[0]


def test_self_inverse_link_appears_once_on_the_backlink_side_only(parts_project):
    """CMP-005 declares alternate: [CMP-001]; CMP-001 never declares it back.
    CMP-001's own page must still show the relationship (via the computed
    backlink), exactly once, not duplicated or missing."""
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Functionally close.\n"
        "workspace: alpha\nboard: main\nalternate: [CMP-001]\n"
        "rationale: Different tolerance.\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    out = render.render_site(project)
    receiving = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    block = receiving.split('class="tight self-inverse"')[1].split("</ul>")[0]
    assert block.count('data-ref="CMP-005"') == 1


def test_self_inverse_redundant_double_declaration_still_renders_once(parts_project):
    """Both sides separately, redundantly declaring the same equivalence is
    harmless -- the merge de-duplicates rather than showing it twice."""
    (parts_project / "items" / "alpha" / "main" / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: Main MCU.\n"
        "part_number: STM32G474\nworkspace: alpha\nboard: main\n"
        "equivalent: [CMP-002]\n---\n",
        encoding="utf-8",
    )
    (parts_project / "items" / "beta" / "main" / "cmp-002.md").write_text(
        "---\nid: CMP-002\ntype: component\ntitle: Also uses the same MCU.\n"
        "part_number: STM32G474\nworkspace: beta\nboard: main\n"
        "equivalent: [CMP-001]\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    block = html.split('class="tight self-inverse"')[1].split("</ul>")[0]
    assert block.count('data-ref="CMP-002"') == 1


def test_equivalent_and_alternate_are_ordinary_authored_links_for_the_lint(parts_project):
    """Unlike shared part_number usage, equivalent/alternate ARE declared
    item.links -- a genuine authored claim -- so the cross-workspace lint
    correctly still fires on those, distinguishing an authored dependency
    from a derived coincidence of the BOM."""
    (parts_project / "items" / "alpha" / "main" / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: Main MCU.\n"
        "part_number: STM32G474\nworkspace: alpha\nboard: main\n"
        "equivalent: [CMP-002]\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    assert any(
        "equivalent points at CMP-002" in d.message and "workspace 'beta'" in d.message
        for d in project.warnings
    )


# ------------------------------------------------ init, new, schema, presets

def test_latest_version_resolves_the_concrete_bundled_max():
    """Deliberately not a literal: this is the highest vN directory that
    actually ships, so hard-coding the number of the day just breaks on the
    next version bump without telling anyone anything."""
    bundled = [
        int(name[1:])
        for name in os.listdir(
            os.path.join(os.path.dirname(standards.__file__), "standards", "hardware")
        )
        if name.startswith("v")
    ]
    assert standards.latest_version("hardware") == max(bundled)
    assert standards.latest_version("hardware") >= 4


def test_available_presets_includes_design_debate():
    assert "design-debate" in standards.available_presets("hardware", 1)
    assert "design-debate" in standards.available_presets("hardware", 2)


def test_preset_providers_maps_names_to_the_preset():
    types, link_types = standards.preset_providers("hardware", 1)
    assert types["debate"] == "design-debate"
    assert types["option"] == "design-debate"
    assert link_types["raises"] == "design-debate"
    assert link_types["resolved_by"] == "design-debate"


def test_init_writes_the_exact_documented_file(tmp_path):
    path = scaffold_mod.init(str(tmp_path))
    assert path == str(tmp_path / "refdes.yaml")
    text = open(path, encoding="utf-8").read()
    assert "types:" not in text
    assert "link_types:" not in text
    assert "field_sets:" not in text
    assert "standard:" in text
    assert "base: hardware" in text
    # The concrete integer, never the word "latest" -- and read from the
    # bundle rather than hard-coded, so a version bump doesn't fail here.
    assert f"version: {standards.latest_version('hardware')}" in text
    assert "latest" not in text
    assert "presets: []" in text

    # The file must actually load and resolve to a real, usable schema.
    project = load_project(config_path=path)
    assert "requirement" in project.types
    assert "decision" in project.types


def test_init_standard_none_writes_the_escape_hatch(tmp_path):
    path = scaffold_mod.init(str(tmp_path), standard=None)
    text = open(path, encoding="utf-8").read()
    assert "standard: none" in text
    assert "base:" not in text


def test_init_with_preset_writes_it_into_the_list(tmp_path):
    path = scaffold_mod.init(str(tmp_path), standard="hardware", presets=["design-debate"])
    text = open(path, encoding="utf-8").read()
    assert "presets: [design-debate]" in text
    project = load_project(config_path=path)
    assert "debate" in project.types


def test_init_preset_with_standard_none_is_a_load_time_error(tmp_path):
    with pytest.raises(SchemaError, match="presets require a base standard"):
        scaffold_mod.init(str(tmp_path), standard=None, presets=["design-debate"])


def test_init_refuses_to_overwrite_an_existing_config(tmp_path):
    (tmp_path / "refdes.yaml").write_text("site: {title: t, out: _site}\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="already exists"):
        scaffold_mod.init(str(tmp_path))


def test_init_writes_vscode_yaml_schema_association(tmp_path):
    scaffold_mod.init(str(tmp_path))
    settings = (tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8")
    data = json.loads(settings)
    schema_keys = list(data["yaml.schemas"])
    assert len(schema_keys) == 1
    schema_key = schema_keys[0]
    assert data["yaml.schemas"][schema_key] == ["items/**/*.yaml"]
    # An absolute, this-project-only path -- not a bare relative one that two
    # different refdes projects would produce byte-identically (finding 9).
    assert os.path.isabs(schema_key)
    assert os.path.normpath(schema_key) == os.path.normpath(
        str(tmp_path / ".refdes" / "schema.json")
    )


def test_init_two_projects_get_disambiguated_schema_paths(tmp_path):
    """Finding 9: every generated .vscode/settings.json pointed at the same
    relative './.refdes/schema.json', so redhat.vscode-yaml -- which doesn't
    reliably scope a relative schema path to the workspace folder that
    declared it -- could apply one project's schema to another's files when
    both happened to be open in the same VS Code session (a multi-root
    workspace, or just switching folders without a full reload)."""
    proj_a = tmp_path / "a"
    proj_b = tmp_path / "b"
    scaffold_mod.init(str(proj_a))
    scaffold_mod.init(str(proj_b))

    settings_a = json.loads((proj_a / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    settings_b = json.loads((proj_b / ".vscode" / "settings.json").read_text(encoding="utf-8"))

    key_a = next(iter(settings_a["yaml.schemas"]))
    key_b = next(iter(settings_b["yaml.schemas"]))
    assert key_a != key_b, "two projects produced the identical, collision-prone schema key"


def test_cli_init_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    status = cli_mod.main(["init"])
    assert status == 0
    assert (tmp_path / "refdes.yaml").is_file()
    assert (tmp_path / ".vscode" / "settings.json").is_file()
    out = capsys.readouterr().out
    assert f"standard: hardware@{standards.latest_version('hardware')}" in out


# --------------------------------------------------------------- refdes new


def test_new_item_text_required_field_no_default_is_a_placeholder():
    project = _build_at_repo_schema()
    spec = project.types["requirement"]
    text = scaffold_mod.new_item_text("requirement", spec)
    assert "type: requirement" in text
    assert "text:  # required -- text" in text


def test_new_item_text_field_with_default_is_uncommented_with_the_default():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "status: proposed  # choices:" in text


def test_new_item_text_optional_field_is_commented_out():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# date:  # date" in text


def test_new_item_text_required_when_field_notes_the_condition():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# rationale:" in text
    assert "required when status is 'rejected'" in text


def test_new_item_text_links_are_commented_out_with_target_hint():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# satisfies: []  # target: requirement" in text


def _build_at_repo_schema():
    """A real project resolving the bundled hardware@2 standard, for
    refdes new / JSON schema tests that need its actual field shapes."""
    return load_project(config_path=os.path.join(REPO, "refdes.yaml"))


def test_cli_new_unknown_type_reports_a_hint(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "new", "decisoin"])
    assert status == 1
    err = capsys.readouterr().err
    assert "unknown type 'decisoin'" in err
    assert "Did you mean 'decision'?" in err


def test_cli_new_known_type_prints_scaffold(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "new", "requirement"])
    assert status == 0
    out = capsys.readouterr().out
    assert "type: requirement" in out


# ----------------------------------------------------------------- JSON schema


def test_build_schema_shape():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    assert doc["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert doc["oneOf"] == [
        {"$ref": "#/$defs/list_file"},
        {"$ref": "#/$defs/bare_item"},
    ]
    assert "requirement__bare" in doc["$defs"]
    assert "requirement__entry" in doc["$defs"]
    # JSON-serializable end to end.
    json.dumps(doc)


def test_build_schema_required_only_unconditional():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    branch = doc["$defs"]["decision__bare"]
    assert "title" in branch["required"]
    # rationale is required_when, not unconditionally required.
    assert "rationale" not in branch["required"]


def test_build_schema_enum_field_carries_choices_and_default():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    status = doc["$defs"]["decision__bare"]["properties"]["status"]
    assert status["enum"] == [
        "proposed", "in_progress", "accepted", "on_hold", "rejected", "superseded",
    ]
    assert status["default"] == "proposed"


def test_build_schema_limit_field_carries_quoting_examples():
    """Finding 13, item 3: a `limit:` value starting with '>'/'>=' needs
    quotes in YAML; `examples` on the JSON Schema fragment is a hint for the
    editor's own completion. Verified (not just shipped hopefully) against
    the real yaml-language-server -- see schema_json.py's comment on this
    fragment for how."""
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    limit = doc["$defs"]["bound__bare"]["properties"]["limit"]
    assert limit["type"] == "string"
    assert ">= 9 V" in limit["examples"]
    assert "<= 600 mA" in limit["examples"]


def test_build_schema_link_carries_target_description():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    satisfies = doc["$defs"]["decision__bare"]["properties"]["satisfies"]
    assert satisfies["type"] == "array"
    assert satisfies["description"] == "target: requirement"


def test_build_schema_additional_properties_false():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    # A type node must not be stricter than `refdes check`, which only warns
    # on an undeclared field rather than rejecting it (finding 3) -- so
    # additionalProperties is NOT false here, unlike the list_file envelope
    # below, whose {defaults, items} shape isn't an extensible per-type node.
    assert doc["$defs"]["decision__bare"]["additionalProperties"] is not False
    assert doc["$defs"]["list_file"]["additionalProperties"] is False
    # defaults: inside a list file is deliberately unvalidated.
    assert doc["$defs"]["list_file"]["properties"]["defaults"]["additionalProperties"] is True


def test_generated_schema_does_not_reject_what_check_only_warns_about(tmp_path):
    """Finding 3: adding a field a type doesn't declare produced two different
    verdicts -- `refdes check` warns and keeps building, but the generated
    schema's `additionalProperties: false` hard-rejects the identical input in
    the editor. The two must agree, and per instruction the schema is the side
    that has to yield here (an editor red-underlining valid input is worse than
    an editor missing something `check` will catch anyway)."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: REQ-001\n    type: requirement\n    text: A requirement.\n"
        "    datasheets: something extra\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert not project.errors
    assert any("unknown field 'datasheets'" in d.message for d in project.warnings)

    doc = schema_json_mod.build_schema(project)
    branch = doc["$defs"]["requirement__entry"]
    assert "datasheets" not in branch["properties"]  # still undeclared, just not fatal
    assert branch["additionalProperties"] is not False, (
        "the generated schema rejects a field the CLI only warns about"
    )


def test_build_schema_body_only_on_the_list_file_entry_branch():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    assert "body" not in doc["$defs"]["decision__bare"]["properties"]
    assert "body" in doc["$defs"]["decision__entry"]["properties"]


def test_build_schema_id_is_never_required():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    for key, branch in doc["$defs"].items():
        if key.endswith("__bare") or key.endswith("__entry"):
            assert "id" not in branch["required"]


def test_build_schema_prefix_board_workspace_omitted_when_shadowed(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: {title: t, out: _site}\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n"
        "      text: {type: text, required: true}\n"
        "      board: {type: text}\n",  # shadows the reserved OVERRIDABLE key
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    doc = schema_json_mod.build_schema(project)
    props = doc["$defs"]["requirement__bare"]["properties"]
    assert props["board"] == {"type": "string"}  # the field's own, not the override
    assert "prefix" in props  # not shadowed, still offered


def test_write_schema_creates_the_file_and_detects_staleness(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    was_stale = schema_json_mod.write_schema(project)
    assert was_stale is False  # nothing existed before this write
    schema_path = tmp_path / ".refdes" / "schema.json"
    assert schema_path.is_file()
    json.loads(schema_path.read_text(encoding="utf-8"))  # valid JSON

    # Freshly written -- not stale relative to the config that hasn't changed.
    was_stale_2 = schema_json_mod.write_schema(project)
    assert was_stale_2 is False

    # Make the schema file look older than a just-touched refdes.yaml.
    old = os.path.getmtime(schema_path) - 10
    os.utime(schema_path, (old, old))
    was_stale_3 = schema_json_mod.write_schema(project)
    assert was_stale_3 is True


def test_cli_schema_json_prints_valid_schema(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "schema", "--json"])
    assert status == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert "requirement__bare" in doc["$defs"]


def test_build_graph_emits_one_edge_per_declared_link(tmp_path):
    """Finding 11: the graph is a walk over the same resolved project.types
    build_schema() uses, with a different renderer -- one Mermaid edge per
    (type, link, target) triple, in the direction actually declared."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "link_types:\n"
        "  satisfies: { inverse: satisfied_by, label: Satisfies }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
        "  decision:\n"
        "    prefix: DEC\n"
        "    fields: { title: { type: text } }\n"
        "    links: { satisfies: [requirement] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    graph = schema_json_mod.build_graph(project)
    assert "graph LR" in graph
    assert "decision -- satisfies --> requirement" in graph
    # The inverse is computed, not separately declared -- must not appear as
    # its own edge (that would double the graph for every link verb).
    assert "satisfied_by" not in graph


def test_build_graph_unrestricted_target_draws_to_a_single_any_node():
    """An empty target list (`links: {blocked_by: []}`) means "any type" --
    the graph must draw one edge to a synthetic `any` node, not one edge per
    known type, which would imply N distinct semantic edges instead of one
    general one."""
    project = _build_at_repo_schema()
    graph = schema_json_mod.build_graph(project)
    assert "decision -- blocked_by --> any" in graph


def test_cli_schema_graph_prints_mermaid_source(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "schema", "--graph"])
    assert status == 0
    out = capsys.readouterr().out
    assert out.startswith("%%")
    assert "graph LR" in out
    assert "requirement -- refines --> requirement" in out


def test_check_refreshes_schema_json_and_warns_when_stale(tmp_path, capsys):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    schema_path = tmp_path / ".refdes" / "schema.json"

    cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "check"])
    assert schema_path.is_file()

    old = os.path.getmtime(schema_path) - 10
    os.utime(schema_path, (old, old))
    capsys.readouterr()
    cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "check"])
    out = capsys.readouterr().out
    assert "schema.json was older than refdes.yaml" in out


# ------------------------------------------------------- preset add/remove


def test_add_preset_appends_to_the_list(tmp_path):
    scaffold_mod.init(str(tmp_path))
    scaffold_mod.add_preset(str(tmp_path), "design-debate")
    text = (tmp_path / "refdes.yaml").read_text(encoding="utf-8")
    assert "presets: [design-debate]" in text


def test_add_preset_unknown_name_is_an_error(tmp_path):
    scaffold_mod.init(str(tmp_path))
    with pytest.raises(SchemaError, match="does not exist"):
        scaffold_mod.add_preset(str(tmp_path), "nope-preset")


def test_add_preset_already_selected_is_an_error(tmp_path):
    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    with pytest.raises(SchemaError, match="already selected"):
        scaffold_mod.add_preset(str(tmp_path), "design-debate")


def test_add_preset_preserves_hand_written_comments(tmp_path):
    scaffold_mod.init(str(tmp_path))
    config_path = tmp_path / "refdes.yaml"
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("site:", "# A hand-written comment nobody wants lost.\nsite:")
    config_path.write_text(text, encoding="utf-8")

    scaffold_mod.add_preset(str(tmp_path), "design-debate")
    after = config_path.read_text(encoding="utf-8")
    assert "# A hand-written comment nobody wants lost." in after


def test_remove_preset_removes_from_the_list(tmp_path):
    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    scaffold_mod.remove_preset(str(tmp_path), "design-debate")
    text = (tmp_path / "refdes.yaml").read_text(encoding="utf-8")
    assert "presets: []" in text


def test_remove_preset_not_selected_is_an_error(tmp_path):
    scaffold_mod.init(str(tmp_path))
    with pytest.raises(SchemaError, match="not currently selected"):
        scaffold_mod.remove_preset(str(tmp_path), "design-debate")


def test_remove_preset_reports_orphaned_items_before_writing(tmp_path):
    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    diagnostics = scaffold_mod.remove_preset(str(tmp_path), "design-debate")
    assert any(
        "unknown type 'debate'" in d.message and "design-debate" in d.message
        for d in diagnostics
    )
    # The report ran, but the config change still applied -- this command's
    # job is to surface the consequence, not block an author who already
    # decided to accept it.
    text = (tmp_path / "refdes.yaml").read_text(encoding="utf-8")
    assert "presets: []" in text
    # No leftover scratch file.
    assert not (tmp_path / "refdes.yaml.scratch").exists()


def test_cli_standard_add_and_remove_preset(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    config = str(tmp_path / "refdes.yaml")
    status = cli_mod.main(["-c", config, "standard", "add-preset", "design-debate"])
    assert status == 0
    assert "design-debate" in (tmp_path / "refdes.yaml").read_text(encoding="utf-8")

    status = cli_mod.main(["-c", config, "standard", "remove-preset", "design-debate"])
    assert status == 0
    assert "presets: []" in (tmp_path / "refdes.yaml").read_text(encoding="utf-8")


def test_cli_standard_remove_preset_exit_code_reflects_errors(tmp_path):
    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes.yaml")
    status = cli_mod.main(["-c", config, "standard", "remove-preset", "design-debate"])
    assert status == 1


# ---------------------------------------------- preset-provided diagnostics


def test_unknown_type_matching_a_preset_names_it(tmp_path):
    scaffold_mod.init(str(tmp_path))  # no presets selected
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "unknown type 'debate'" in d.message
        and "provided by the 'design-debate' preset" in d.message
        for d in project.errors
    )


def test_unknown_type_with_no_preset_match_is_the_ordinary_message(tmp_path):
    scaffold_mod.init(str(tmp_path))
    items = tmp_path / "items"
    items.mkdir()
    (items / "x.md").write_text(
        "---\nid: X-001\ntype: totallymadeup\ntitle: t.\n---\n", encoding="utf-8"
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    msg = next(d.message for d in project.errors if "unknown type" in d.message)
    assert "provided by" not in msg


def test_unknown_link_matching_a_preset_names_it(tmp_path):
    scaffold_mod.init(str(tmp_path))  # no presets selected
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-001.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: t.\nstatus: accepted\n"
        "resolved_by: []\n---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "unknown field 'resolved_by'" in d.message
        and "provided by the 'design-debate' preset" in d.message
        for d in project.errors
    )


# --------------------------------------------------------------- stub-tests

STUB_SCHEMA = """\
site: {title: "Stub Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
boards:
  power: {label: Power}
  thermal: {label: Thermal}
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
  verifies:  { inverse: verified_by,  label: Verifies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [proposed, accepted], default: proposed, on_change: invalidate }
    satisfying_statuses: [accepted]
    links:
      satisfies: [requirement]
    body: { on_change: invalidate }
  test:
    prefix: TST
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [planned, passing, failing], default: planned, on_change: invalidate }
      method: { type: text, on_change: invalidate }
    verifying_statuses: [passing]
    links:
      verifies: [requirement]
    body: { on_change: invalidate }
"""

STUB_ITEMS = {
    "req-001.md": """\
---
id: REQ-001
type: requirement
text: Fully open, nothing touches it.
board: power
---
""",
    "req-002.md": """\
---
id: REQ-002
type: requirement
text: Satisfied by an accepted decision, no test yet.
board: power
---
""",
    "dec-001.md": """\
---
id: DEC-001
type: decision
title: Settle REQ-002.
status: accepted
board: power
satisfies: [REQ-002]
---
""",
}


@pytest.fixture
def stub_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(STUB_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in STUB_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def _stub_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def test_generate_writes_one_stub_per_uncovered_item(stub_project):
    project = _stub_build(stub_project)
    written = stub_tests_mod.generate(project)
    assert len(written) == 1
    path, item_ids = written[0]
    assert path == "items/power/stub-tests.md"
    assert sorted(item_ids) == ["REQ-001", "REQ-002"]

    text = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")
    assert "type: test" in text
    assert "title: Verify REQ-001" in text
    assert "status: planned" in text
    assert 'method: ""' in text
    assert "verifies: [REQ-001]" in text
    assert "verifies: [REQ-002]" in text


def test_generate_dry_run_writes_nothing(stub_project):
    project = _stub_build(stub_project)
    written = stub_tests_mod.generate(project, dry_run=True)
    assert len(written) == 1
    assert not (stub_project / "items" / "power" / "stub-tests.md").exists()


def test_a_stub_status_planned_never_counts_as_verified(stub_project):
    """The prerequisite this feature relies on: verifying_statuses already
    means a status: planned test doesn't settle coverage, so a generated
    stub never retroactively marks its target verified. Getting this wrong
    would recreate, at scale, the exact coverage bug this project already
    fixed once in the verify half."""
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)
    project = _stub_build(stub_project)  # reload with real ids now in place

    cov1 = project.coverage["REQ-001"]
    assert cov1.verified_by == []
    assert cov1.stage != "verified"

    cov2 = project.coverage["REQ-002"]
    assert cov2.verified_by == []
    assert cov2.stage == "satisfied"  # not bumped to "verified"


def test_rerun_before_id_allocation_does_not_duplicate(stub_project):
    """A generated stub has no id yet, so resolve_links() never sees its
    verifies: edge -- the dedup check has to look at project.pending too,
    or running this twice in a row (with no `refdes id` in between) would
    generate a second stub for the same requirement."""
    project = _stub_build(stub_project)
    first = stub_tests_mod.generate(project)
    assert sum(len(ids) for _p, ids in first) == 2

    project2 = _stub_build(stub_project)  # re-parse; new items are still pending
    second = stub_tests_mod.generate(project2)
    assert second == []

    text = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")
    assert text.count("verifies: [REQ-001]") == 1
    assert text.count("verifies: [REQ-002]") == 1


def test_rerun_after_id_allocation_does_not_duplicate(stub_project):
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)

    project2 = _stub_build(stub_project)
    second = stub_tests_mod.generate(project2)
    assert second == []


def test_deleting_a_stub_makes_its_target_eligible_again(stub_project):
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)

    text = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")
    # Remove the REQ-002 stub block entirely, leaving REQ-001's alone.
    blocks = text.split("---\n")
    kept = [b for b in blocks if "REQ-002" not in b]
    (stub_project / "items" / "power" / "stub-tests.md").write_text(
        "---\n".join(kept), encoding="utf-8"
    )

    project2 = _stub_build(stub_project)
    third = stub_tests_mod.generate(project2)
    assert len(third) == 1
    _path, covered_ids = third[0]
    assert covered_ids == ["REQ-002"]


def test_new_requirement_appends_without_touching_existing_stubs(stub_project):
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)
    before = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")

    (stub_project / "items" / "req-003.md").write_text(
        "---\nid: REQ-003\ntype: requirement\ntext: Added later.\nboard: power\n---\n",
        encoding="utf-8",
    )
    project2 = _stub_build(stub_project)
    stub_tests_mod.generate(project2)

    after = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")
    assert after.startswith(before)
    assert "verifies: [REQ-003]" in after

    ids.allocate(project2)
    project3 = _stub_build(stub_project)
    assert not project3.errors


def test_groups_by_board(stub_project):
    (stub_project / "items" / "req-t1.md").write_text(
        "---\nid: REQ-T1\ntype: requirement\ntext: Thermal one.\nboard: thermal\n---\n",
        encoding="utf-8",
    )
    project = _stub_build(stub_project)
    written = stub_tests_mod.generate(project)
    paths = {p for p, _ids in written}
    assert paths == {"items/power/stub-tests.md", "items/thermal/stub-tests.md"}


def test_no_verifier_type_is_an_error(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: {title: t, out: _site}\n"
        "types:\n  requirement: {prefix: REQ, coverable: true, "
        "fields: {text: {type: text, required: true}}}\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "req.md").write_text(
        "---\nid: REQ-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    project = _stub_build(tmp_path)
    with pytest.raises(SchemaError, match="no type declares a 'verifies' link"):
        stub_tests_mod.generate(project)


def test_ambiguous_verifier_type_requires_type_flag(stub_project):
    text = STUB_SCHEMA + (
        "  inspection:\n"
        "    prefix: INSP\n"
        "    fields:\n"
        "      title: {type: text, required: true}\n"
        "    links:\n"
        "      verifies: [requirement]\n"
    )
    (stub_project / "refdes.yaml").write_text(text, encoding="utf-8")
    project = _stub_build(stub_project)
    with pytest.raises(SchemaError, match="multiple types declare 'verifies'"):
        stub_tests_mod.generate(project)
    written = stub_tests_mod.generate(project, verifier_type="test")
    assert written


def test_nothing_to_do_returns_empty_list(stub_project):
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)
    project2 = _stub_build(stub_project)
    assert stub_tests_mod.generate(project2) == []


def test_cli_stub_tests_end_to_end(stub_project, capsys):
    status = cli_mod.main(["-c", str(stub_project / "refdes.yaml"), "stub-tests"])
    assert status == 0
    out = capsys.readouterr().out
    assert "wrote 2 stub test(s)" in out
    assert "Run 'refdes id'" in out
    assert (stub_project / "items" / "power" / "stub-tests.md").is_file()


def test_cli_stub_tests_refuses_when_the_project_has_errors(stub_project, capsys):
    (stub_project / "items" / "broken.md").write_text(
        "---\nid: BAD-001\ntype: nonexistent\ntitle: t.\n---\n", encoding="utf-8"
    )
    status = cli_mod.main(["-c", str(stub_project / "refdes.yaml"), "stub-tests"])
    assert status == 1
    assert not (stub_project / "items" / "power" / "stub-tests.md").exists()


def test_cli_stub_tests_reports_nothing_to_do(stub_project, capsys):
    cli_mod.main(["-c", str(stub_project / "refdes.yaml"), "stub-tests"])
    ids.allocate(_stub_build(stub_project))
    capsys.readouterr()
    status = cli_mod.main(["-c", str(stub_project / "refdes.yaml"), "stub-tests"])
    assert status == 0
    out = capsys.readouterr().out
    assert "no coverable item is missing a verifying test" in out
