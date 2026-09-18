"""calc -- and: sigfig format, limits, on_change, checks against temperatures.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config
from helpers import _project

from refdes import build as build_mod
from refdes import calc, parse
from refdes.model import SchemaError
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


def test_prefixed_ohm_parses_not_just_a_bare_ohm():
    """Backlog finding 18: Ω was only in the unit pattern's leading character
    class, so `kΩ` and `MΩ` -- the normal spelling for resistances -- failed
    while a bare `Ω` parsed."""
    env = {}
    outcomes = calc.evaluate_block("R1 = 4.7 kΩ\nR2 = 10 MΩ", env)
    assert [o.error for o in outcomes] == [None, None]
    assert env["R1"].nom.to("ohm").magnitude == pytest.approx(4700.0)
    assert env["R2"].nom.to("ohm").magnitude == pytest.approx(1.0e7)


def test_percent_parses_outside_a_tolerance():
    """Backlog finding 18: `%` was only reachable through the tolerance
    pre-parse, so `85 %` failed with a raw Python syntax error."""
    env = {}
    outcomes = calc.evaluate_block("d = 85 %", env)
    assert outcomes[0].error is None
    assert env["d"].nom.to("dimensionless").magnitude == pytest.approx(0.85)


def test_percent_scales_a_quantity():
    env = {}
    outcomes = calc.evaluate_block("drop = 100 V * 5 %", env)
    assert outcomes[0].error is None
    assert env["drop"].nom.to("V").magnitude == pytest.approx(5.0)


def test_percent_tolerance_still_routes_through_the_percent_form():
    """The tolerance pre-parse must keep winning for `± 15%`: it means 15% of
    the value, not 15 percent-units added to it."""
    v = calc.evaluate_assignment("12 V ± 15%", {})
    assert v.nom.to("V").magnitude == pytest.approx(12.0)
    assert v.lo.to("V").magnitude == pytest.approx(10.2)
    assert v.hi.to("V").magnitude == pytest.approx(13.8)


def test_malformed_unit_error_names_the_expression():
    with pytest.raises(calc.CalcError) as exc:
        calc.parse_quantity("3.3 V/")
    assert "3.3 V/" in str(exc.value)


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
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nV = 3.3 V\nI = 1.2 A\nP : W ± 10% = V * I\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    message = next(d.message for d in project.errors if "P" in d.message)
    assert "calc 'P': a tolerance belongs on the right-hand side — P : W = V * I ± 10%" == message


# ------------------------------------------------------- duplicate assignment


def test_duplicate_assignment_within_one_block_is_an_error():
    outcomes = calc.evaluate_block("x = 5 V\nx = 2 A", {})
    assert outcomes[0].error is None
    assert outcomes[1].error is not None
    assert "assigned twice" in outcomes[1].error


def test_duplicate_assignment_across_blocks_is_caught_when_origins_is_shared():
    """This is exactly how build.run_calcs threads `origins` across every
    block of one item -- the same way it already threads `env`."""
    env: dict = {}
    origins: dict = {}
    first = calc.evaluate_block("x = 5 V", env, start_line=10, origins=origins)
    second = calc.evaluate_block("x = 2 A", env, start_line=20, origins=origins)
    assert first[0].error is None
    assert second[0].error is not None
    assert "line 10" in second[0].error
    assert "line 20" in second[0].error


def test_duplicate_assignment_not_caught_across_blocks_without_shared_origins():
    """Documents the contract: a fresh `origins` per call only catches a
    repeat within that one call, exactly like a fresh `env` would."""
    env: dict = {}
    first = calc.evaluate_block("x = 5 V", env)
    second = calc.evaluate_block("x = 2 A", env)
    assert first[0].error is None
    assert second[0].error is None


def test_legitimate_forward_reference_is_not_a_duplicate():
    """A name used on the right-hand side of a later, different assignment is
    not a redefinition of anything -- only reusing a name as the left-hand
    side twice is."""
    env: dict = {}
    outcomes = calc.evaluate_block("x = 5 V\ny = x * 2", env)
    assert outcomes[0].error is None
    assert outcomes[1].error is None


def test_a_failed_first_attempt_does_not_block_a_retry():
    """The first line never actually defined `x` (it errored), so rewriting it
    under the same name is a fix, not a collision."""
    outcomes = calc.evaluate_block("x = 3.3 V + 1.2 A\nx = 3.3 V", {})
    assert outcomes[0].error is not None  # dimensional mismatch
    assert outcomes[1].error is None  # not flagged as a duplicate


def test_duplicate_assignment_across_blocks_fails_the_build(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nx = 5 V\n```\n\n"
        "```calc\nx = 2 A\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    message = next(d.message for d in project.errors if "assigned twice" in d.message)
    assert "'x' is assigned twice in this item" in message
    assert "first at line" in message and "again at line" in message
    # Both locations are real, distinct lines in the source file, not the same
    # coarse item-level line repeated twice -- that would defeat the point.
    import re

    first_line, second_line = (int(n) for n in re.findall(r"line (\d+)", message))
    assert first_line != second_line
    source = (items / "dec.md").read_text(encoding="utf-8").splitlines()
    assert source[first_line - 1].strip() == "x = 5 V"
    assert source[second_line - 1].strip() == "x = 2 A"

    # The diagnostic's own file:line points at the duplicate, not the item's
    # front-matter -- what makes "jump to the error" land somewhere useful.
    diag = next(d for d in project.errors if "assigned twice" in d.message)
    assert diag.line == second_line


def test_same_name_in_different_items_does_not_collide(tmp_path):
    """Two items in one file, each with their own calc block naming `x`, must
    build clean -- variables are item-scoped, not file-scoped (docs/math.md)."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nx = 5 V\n```\n"
        "---\nid: DEC-002\ntype: decision\n---\n\n"
        "```calc\nx = 2 A\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert not any("assigned twice" in d.message for d in project.errors)
    assert project.item_by_id("DEC-001").calc_values["x"] == "5 V"
    assert project.item_by_id("DEC-002").calc_values["x"] == "2 A"


# ----------------------------------------------------------- source position


def test_extract_blocks_with_lines_offset_matches_block_position():
    body = "prose\n\n```calc\nx = 1\n```\n\nmore prose\n\n```calc\ny = 2\n```\n"
    blocks = calc.extract_blocks_with_lines(body)
    lines = body.split("\n")
    assert lines[blocks[0][1]] == "x = 1"
    assert lines[blocks[1][1]] == "y = 2"


def test_calc_line_records_absolute_source_position(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    source = (
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "prose\n\n```calc\nV = 3.3 V\nI = 1.2 A\n```\n"
    )
    (items / "dec.md").write_text(source, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    item = project.item_by_id("DEC-001")
    lines = source.splitlines()
    by_name = {c.name: c for c in item.calcs}
    assert lines[by_name["V"].line - 1].strip() == "V = 3.3 V"
    assert lines[by_name["I"].line - 1].strip() == "I = 1.2 A"


def test_calc_line_position_reaches_items_json(tmp_path):
    from refdes import render

    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n```calc\nV = 3.3 V\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    payload = render.items_json(project)
    item_json = next(i for i in payload["items"] if i["id"] == "DEC-001")
    expected_line = project.item_by_id("DEC-001").calcs[0].line
    assert item_json["calcs"][0]["line"] == expected_line
    assert isinstance(expected_line, int)


def test_body_line_is_none_for_a_list_file_item():
    """A list file's `body:` key has no cheap per-line position (see
    Item.body_line's docstring) -- calc line numbers degrade to None rather
    than a guess, and the duplicate-assignment message still works, just
    without pinpointing a line."""
    project = _project()
    checked = 0
    for item in project.local_items:
        if item.source_file.endswith((".yaml", ".yml")) and item.body:
            assert item.body_line is None
            checked += 1
    assert checked > 0  # otherwise this is vacuously true -- confirm the fixture still has one


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
    item = project.item_by_id(item_id)
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
    before = project.item_by_id("REQ-PWR-001").content_hash
    assert _hash_after(project, "REQ-PWR-001", "owner", "Someone Else") == before


def test_log_and_ignore_are_indistinguishable_for_hashing():
    """`log` is reserved for a future history layer; today it behaves as `ignore`."""
    project = _project()
    before = project.item_by_id("REQ-PWR-001").content_hash
    log_hash = _hash_after(project, "REQ-PWR-001", "owner", "Someone Else")  # on_change: log
    ignore_hash = _hash_after(project, "REQ-PWR-001", "last_reviewed", "2020-01-01")  # on_change: ignore
    assert log_hash == before == ignore_hash


def test_invalidate_field_changes_the_content_hash():
    project = _project()
    before = project.item_by_id("BND-THM-001").content_hash
    assert _hash_after(project, "BND-THM-001", "limit", "<= 1.5 W/in^2") != before


def test_item_level_override_beats_the_schema():
    """REQ-PWR-004 sets owner -> ignore, so even a `log` field goes fully silent."""
    project = _project()
    spec = project.types["requirement"]
    item = project.item_by_id("REQ-PWR-004")
    assert item.on_change_for("owner", spec, project.default_on_change) == "ignore"
    assert project.item_by_id("REQ-PWR-001").on_change_for(
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
    write_project_config(tmp_path, TEMPERATURE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "b.yaml").write_text(
        "items:\n"
        "  - id: BND-001\n    type: bound\n    text: Junction temperature\n"
        f'    limit: "{limit}"\n',
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
        f"```calc\nT_j : degC = {value}\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
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
    result = project.item_by_id("DEC-001").checks[0]
    assert result.ok, result.detail
    # The comparison itself is well-defined and still reported.
    assert "40" in result.detail


def test_a_temperature_margin_is_undefined_not_invented(tmp_path):
    """A fraction of an offset-unit reading has no meaning -- 45 degC of slack
    against an 85 degC limit is 53% or 13% depending purely on where zero
    sits -- so there is no number to report. `margin: None` is the same
    already-supported state an `==` limit produces."""
    project = _temperature_project(tmp_path, "<= 85 degC")
    assert project.item_by_id("DEC-001").checks[0].margin is None


def test_an_absolute_temperature_scale_still_gets_a_real_margin(tmp_path):
    """Kelvin has no offset, so the division is well-defined and the margin is
    a real number -- the None above is specific to offset units, not a blanket
    give-up on temperature."""
    project = _temperature_project(tmp_path, "<= 350 K", value="300 K")
    margin = project.item_by_id("DEC-001").checks[0].margin
    assert margin is not None
    assert margin == pytest.approx((350 - 300) / 350, rel=1e-6)


def test_a_temperature_range_limit_still_gets_a_real_margin(tmp_path):
    """A range measures slack against its own span -- a difference divided by a
    difference -- so offset units are not ambiguous there and never were."""
    project = _temperature_project(tmp_path, "0 degC .. 60 degC")
    assert project.item_by_id("DEC-001").checks[0].margin is not None


# ------------------------------------------------- project-defined equations


@pytest.fixture
def equation_registry():
    """An equation namespace this test can overwrite, restored afterwards --
    `calc.EQUATIONS` is project-wide state, exactly like the unit aliases."""
    saved = dict(calc.EQUATIONS)
    yield calc
    calc.set_equations(saved)


CURRENT_LIMIT = calc.Equation(
    "current_limit", ["K", "V", "R"], "K * V / R", "TPS1H200A datasheet p.22"
)


def test_a_project_equation_evaluates_with_units_from_its_arguments(equation_registry):
    """The feature itself. Nothing about a body is special: units come from the
    arguments, so a parameter needs no declared dimension."""
    equation_registry.set_equations({"current_limit": CURRENT_LIMIT})
    value = calc.evaluate("current_limit(2500, 0.8 V, 3.3 kohm)", {})
    assert value.nom.to("A").magnitude == pytest.approx(2500 * 0.8 / 3300)
    assert value.dimensionality == calc.Q(1, "A").dimensionality


def test_equations_compose(equation_registry):
    """An equation body is an expression like any other, so it may call another
    equation -- which is exactly why cycles need a rule of their own."""
    equation_registry.set_equations({
        "current_limit": CURRENT_LIMIT,
        "pwr": calc.Equation("pwr", ["V", "I"], "V * I"),
        "rail": calc.Equation("rail", ["V"], "pwr(V, current_limit(2500, V, 3.3 kohm))"),
    })
    value = calc.evaluate("rail(0.8 V)", {})
    assert value.nom.to("W").magnitude == pytest.approx(0.8 * (2500 * 0.8 / 3300))
    assert value.dimensionality == calc.Q(1, "W").dimensionality


def test_a_wrong_dimension_argument_is_caught_by_the_unit_assertion(equation_registry):
    """`3.3 kg` where a resistance belongs is not a new kind of error. The call
    site's own unit assertion catches it the way it catches any other
    dimensional drift, because the equation returned an ordinary value."""
    equation_registry.set_equations({"current_limit": CURRENT_LIMIT})
    outcomes = calc.evaluate_block(
        "CLIM_out1 : A = current_limit(2500, 0.8 V, 3.3 kg)", {}
    )
    assert outcomes[0].error is not None
    assert "declared as A but the expression evaluates to" in outcomes[0].error


def test_a_wrong_dimension_argument_errors_inside_the_equation_body(equation_registry):
    """Where the body's own arithmetic is what fails, the diagnostic is the
    ordinary one, raised while evaluating the call."""
    equation_registry.set_equations(
        {"series": calc.Equation("series", ["a", "b"], "a + b")}
    )
    with pytest.raises(calc.CalcError, match="units do not match"):
        calc.evaluate("series(1 kohm, 3.3 kg)", {})


def test_tolerance_propagates_through_an_equation_result(equation_registry):
    """`Value` arithmetic already propagates, so a ± on an equation result
    behaves exactly as it does on any other expression."""
    equation_registry.set_equations({"current_limit": CURRENT_LIMIT})
    value = calc.evaluate_assignment(
        "current_limit(2500, 0.8 V, 3.3 kohm) ± 15%", {}
    )
    assert value.has_width
    assert value.lo.magnitude == pytest.approx(value.nom.magnitude * 0.85)
    assert value.hi.magnitude == pytest.approx(value.nom.magnitude * 1.15)
    assert value.dimensionality == calc.Q(1, "A").dimensionality


def test_a_tolerance_in_an_argument_propagates_through_an_equation(equation_registry):
    """The other direction: a tolerance carried by an argument reaches the
    result, because arguments are evaluated as `Value`s like everything else."""
    equation_registry.set_equations({"current_limit": CURRENT_LIMIT})
    env = {"Vin": calc.evaluate_assignment("0.8 V ± 10%", {})}
    value = calc.evaluate("current_limit(2500, Vin, 3.3 kohm)", env)
    assert value.has_width
    assert value.lo.magnitude == pytest.approx(value.nom.magnitude * 0.9)


def test_arity_is_enforced_by_the_existing_call_path(equation_registry):
    """Not reimplemented: the call path that already checks `sqrt()` checks an
    equation against its declared `params`."""
    equation_registry.set_equations({"current_limit": CURRENT_LIMIT})
    with pytest.raises(calc.CalcError, match=r"current_limit\(\) takes 3 argument"):
        calc.evaluate("current_limit(2500, 0.8 V)", {})


def test_an_unknown_equation_name_still_names_what_is_available(equation_registry):
    equation_registry.set_equations({"current_limit": CURRENT_LIMIT})
    with pytest.raises(calc.CalcError) as excinfo:
        calc.evaluate("current_limi(2500, 0.8 V, 3.3 kohm)", {})
    message = str(excinfo.value)
    assert "unknown function 'current_limi'" in message
    assert "current_limit" in message  # the equation is offered alongside...
    assert "sqrt" in message  # ...every built-in


def test_an_equation_cannot_shadow_a_builtin(equation_registry):
    """A silent override would make every other expression on the site compute
    the wrong thing with nothing to say so, so the rule is a hard error."""
    with pytest.raises(calc.CalcError, match="built-in function"):
        equation_registry.set_equations(
            {"sqrt": calc.Equation("sqrt", ["x"], "x * 2")}
        )
    assert "sqrt" not in calc.EQUATIONS
    assert calc.evaluate("sqrt(4 m^2)", {}).nom.magnitude == pytest.approx(2.0)


def test_an_equation_cycle_is_reported_not_followed(equation_registry):
    """Reported the way `blocked_by` cycles are -- the path that closes the
    loop -- rather than hanging the build on infinite recursion."""
    with pytest.raises(calc.CalcError, match=r"equation cycle: a -> b -> a"):
        equation_registry.set_equations({
            "a": calc.Equation("a", ["x"], "b(x)"),
            "b": calc.Equation("b", ["x"], "a(x)"),
        })


def test_a_cycle_installed_bypassing_validation_is_still_not_a_hang(equation_registry):
    """The runtime backstop: even a registry populated without going through
    `set_equations` reports the cycle instead of recursing forever."""
    calc.EQUATIONS.update({
        "a": calc.Equation("a", ["x"], "b(x)"),
        "b": calc.Equation("b", ["x"], "a(x)"),
    })
    with pytest.raises(calc.CalcError, match="equation cycle"):
        calc.evaluate("a(1)", {})


# ------------------------------------------------ equations in project config


def _equation_config(tmp_path, equations_yaml):
    config = write_project_config(
        tmp_path,
        "site: { title: E, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n"
        f"{equations_yaml}",
    )
    return load_project(config_path=str(config))


CURRENT_LIMIT_YAML = """\
equations:
  current_limit:
    params: [K, V, R]
    expr: K * V / R
    note: TPS1H200A datasheet p.22
"""


def test_equations_load_from_the_project_config(tmp_path):
    project = _equation_config(tmp_path, CURRENT_LIMIT_YAML)
    assert list(project.equations) == ["current_limit"]
    assert project.equations["current_limit"].params == ["K", "V", "R"]
    assert project.equations["current_limit"].note == "TPS1H200A datasheet p.22"
    value = calc.evaluate("current_limit(2500, 0.8 V, 3.3 kohm)", {})
    assert value.nom.to("A").magnitude == pytest.approx(2500 * 0.8 / 3300)


def test_an_equation_call_in_a_calc_block_reaches_the_build(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: E, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n"
        f"{CURRENT_LIMIT_YAML}",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nCLIM_out1 : A = current_limit(2500, 0.8 V, 3.3 kohm)\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors
    assert project.item_by_id("DEC-001").calcs[0].result == "0.6061 A"


def test_a_project_without_equations_installs_none(tmp_path):
    """Loading a project replaces the namespace rather than merging into the
    last one, so one project's equations can't leak into the next build."""
    calc.set_equations({"current_limit": CURRENT_LIMIT})
    _equation_config(tmp_path, "")
    assert calc.EQUATIONS == {}


def test_a_builtin_equation_name_in_the_project_config_is_an_error(tmp_path):
    with pytest.raises(SchemaError, match="built-in function"):
        _equation_config(
            tmp_path, "equations:\n  sqrt: { params: [x], expr: 'x * 2' }\n"
        )


def test_an_equation_cycle_in_the_project_config_is_an_error(tmp_path):
    with pytest.raises(SchemaError) as excinfo:
        _equation_config(
            tmp_path,
            "equations:\n"
            "  a: { params: [x], expr: 'b(x)' }\n"
            "  b: { params: [x], expr: 'a(x)' }\n",
        )
    assert "equation cycle: a -> b -> a" in str(excinfo.value)


def test_an_equation_body_that_does_not_parse_is_caught_at_load(tmp_path):
    """A broken body is a config error naming the equation, not a surprise for
    whoever first calls it three weeks later."""
    with pytest.raises(SchemaError, match="could not parse"):
        _equation_config(tmp_path, "equations:\n  bad: { params: [], expr: '1 +' }\n")


def test_an_unknown_equation_definition_key_is_an_error(tmp_path):
    with pytest.raises(SchemaError, match="equations.ok.unit is not valid"):
        _equation_config(
            tmp_path,
            "equations:\n  ok: { params: [x], expr: 'x', unit: A }\n",
        )
