"""calc -- and: sigfig format, limits, on_change, checks against temperatures.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import pytest
from helpers import _project

from refdes import build as build_mod
from refdes import calc, parse
from refdes.schema import load_project

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
