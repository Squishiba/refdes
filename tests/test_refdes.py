"""Tests for the invariants that must never quietly break.

The rest of the tool can be rewritten freely. These four cannot: IDs must never
shift, the calc DSL must never execute code, the content hash must follow the
on_change policy exactly, and checks must be evaluated at the worst-case tolerance
bound rather than the nominal.
"""

from __future__ import annotations

import hashlib
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
    assert "split it into separate constraint items" in str(exc.value)


def test_unreadable_limit_does_not_hint_on_an_ordinary_typo():
    """A single-bound typo shouldn't get told to split into multiple constraints."""
    with pytest.raises(calc.CalcError) as exc:
        calc.parse_limit("somewhere under 2 watts")
    assert "split it into separate constraint items" not in str(exc.value)


def test_unreadable_limit_does_not_hint_on_a_tolerance_alone():
    """Two numbers with no list-like conjunction (a tolerance, not a list of
    bounds) should not trigger the hint either."""
    with pytest.raises(calc.CalcError) as exc:
        calc.parse_limit("100 ohm ±5%")
    assert "split it into separate constraint items" not in str(exc.value)


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


# ------------------------------------------------------------- images and assets


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
    item = project.items["DEC-A-001"]
    assert 'src="assets/items/figures/present.png"' in item.body_html
    # A remote src is never touched or registered.
    assert "assets/https" not in item.body_html
    assert 'src="https://example.com/photo.png"' in item.body_html


def test_local_image_is_copied_into_the_site(image_project):
    out = _build_and_render(image_project)
    copied = os.path.join(out, "assets", "items", "figures", "present.png")
    assert os.path.isfile(copied)
    assert open(copied, "rb").read() == b"\x89PNG\r\n\x1a\n"


def test_deleting_an_image_reference_prunes_its_copied_asset(image_project):
    out = _build_and_render(image_project)
    copied = os.path.join(out, "assets", "items", "figures", "present.png")
    assert os.path.isfile(copied)

    text = (image_project / "items" / "dec-a.md").read_text(encoding="utf-8")
    text = text.replace("![present](figures/present.png)\n\n", "")
    (image_project / "items" / "dec-a.md").write_text(text, encoding="utf-8")

    out = _build_and_render(image_project)
    assert not os.path.isfile(copied)


def test_asset_colliding_with_a_template_reserved_name_is_an_error(tmp_path):
    """An image path that would land on assets/style.css must not clobber it."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    # Escapes items/ via '..' so its root-relative destination is exactly
    # "style.css" -- the template's own reserved top-level asset name.
    (items / "dec-a.md").write_text(
        "---\nid: DEC-A-001\ntype: decision\ntitle: Clobbers style.css.\n"
        "status: accepted\n---\n\n![bad](../style.css)\n",
        encoding="utf-8",
    )
    (tmp_path / "style.css").write_text("body { color: red }", encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)

    assert any("would be written to assets/style.css" in d.message for d in project.errors)
    real_style = open(os.path.join(out, "assets", "style.css"), encoding="utf-8").read()
    assert "color: red" not in real_style  # the template's own stylesheet survived


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

    assert '<figure class="md-figure" style="width: 60%">' in html
    assert "<figcaption>Figure 3 — the curve</figcaption>" in html
    assert '<img src="assets/items/figures/present.png" alt="the curve" />' in html


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

    assert '<img src="assets/items/figures/present.png" alt="plain, no suffix" />' in html
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
    assert os.path.isfile(os.path.join(out, "assets", "pages", "img", "board.png"))
    index_html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert 'src="assets/pages/img/board.png"' in index_html


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
        "  - id: REQ-WRONG-001\n"
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
        "draft_items":              {"release": True,  "revision": False},
        "unpinned_citations":       {"release": True,  "revision": False},
        "missing_vendored_copies":  {"release": True,  "revision": False},
        "uncovered_requirements":   {"release": True,  "revision": False},
        "unverified_requirements":  {"release": False, "revision": False},
        "info_check_failures":      {"release": False, "revision": False},
        "unaccepted_board_moves":   {"release": True,  "revision": False},
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
    assert '<span class="nav-group-label">Board A</span>' in html
    assert 'href="power.html"' in html
    assert 'href="summary-board-a.html"' in html
    assert 'href="coverage-board-b.html"' in html


def test_rendered_nav_has_no_groups_without_boards_registered(unboarded_project):
    project = _build_at(unboarded_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert "nav-group" not in html


# --------------------------------------------------------------- board drift


def test_first_build_records_the_manifest_without_warning(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    assert not project.board_moves
    manifest = boards_mod.load_manifest(project)
    assert manifest["REQ-A-001"] == "board-a"


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
    assert boards_mod.load_manifest(project2)["REQ-A-001"] == "board-a"


def test_accept_board_move_updates_the_manifest_and_silences_future_builds(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)

    (board_project / "items" / "board-a" / "r.yaml").rename(
        board_project / "items" / "board-b" / "moved.yaml"
    )

    project2 = _build_at(board_project)
    build_mod.build(project2, seal_write=True, accept_board_move=True)
    assert boards_mod.load_manifest(project2)["REQ-A-001"] == "board-b"

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
    assert boards_mod.load_manifest(project2)["REQ-A-001"] == "board-a"


def test_accept_board_move_off_the_registry_records_the_empty_board(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    (board_project / "items" / "board-a").rename(
        board_project / "items" / "board-a-renamed"
    )

    project2 = _build_at(board_project)
    build_mod.build(project2, seal_write=True, accept_board_move=True)
    assert boards_mod.load_manifest(project2)["REQ-A-001"] == ""

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
    assert "violates CON-THM-001" in " ".join(d.message for d in project.errors)


def _io_check_project(tmp_path, *, tolerance):
    """A single toleranced (or exact) check violating a `<=` constraint."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items"
    items.mkdir()
    (items / "io.yaml").write_text(
        "defaults: { type: constraint }\n"
        "items:\n"
        "  - id: CON-IO-004\n"
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
        "constrains: [CON-IO-004]\n"
        "checks:\n"
        "  - value: CLIM\n"
        "    against: CON-IO-004\n"
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
    message = next(d.message for d in project.errors if "CON-IO-004" in d.message)
    assert (
        "CLIM violates CON-IO-004: worst case 0.697 A vs <= 600 mA (nominal 0.6061 A)"
        in message
    )


def test_check_error_omits_nominal_when_worst_case_equals_it(tmp_path):
    """No tolerance means worst case and nominal are the same number.

    The parenthetical would be pure noise here, so it must not appear.
    """
    project = _io_check_project(tmp_path, tolerance=False)
    check = project.items["DEC-IO-002"].checks[0]
    assert check.ok is False
    message = next(d.message for d in project.errors if "CON-IO-004" in d.message)
    assert "CLIM violates CON-IO-004: worst case 0.697 A vs <= 600 mA" in message
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

    # Fully covered.
    assert cov["REQ-PWR-002"].stage == "verified"

    # Written down and never touched again.
    assert cov["REQ-PWR-004"].stage == "open"

    # A log entry alone counts as addressed, not satisfied.
    assert cov["CON-THM-001"].stage == "addressed"
    assert "LOG-A-005" in cov["CON-THM-001"].addressed_by


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
