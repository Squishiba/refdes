"""calc -- a math domain error is a diagnostic, never a traceback.

Every way an expression can leave the reals -- the square root of a negative,
a logarithm of zero, an exponential that overflows a float, a fractional power
of a negative -- used to end one of two ways, and neither was a diagnostic an
engineer could act on. The worst was `sqrt(-1)`: pint answers it with a
*complex* Quantity rather than raising, so evaluation succeeded, the value was
recorded, and the build then died inside the formatter with
`TypeError: float() argument must be a string or a real number, not 'complex'` --
an uncaught traceback with no file, no line, and no mention of the square root.

These tests pin the shape of the fix: a `CalcError` naming the function and the
domain, a build error on the calc line that asked for it, and a build that
reports and exits like any other bad calc.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import calc, cli as cli_mod, parse
from refdes.schema import load_project

# The whole family of leaving-the-reals failures, one expression each. Every one
# of them has to come out the same way: a CalcError, not a stray exception type
# and not a value that carries a complex magnitude into the formatter.
DOMAIN_CASES = [
    # sqrt: pint returns a complex Quantity instead of raising.
    ("sqrt(-1)", "sqrt"),
    ("sqrt(-1 m^2)", "sqrt"),
    ("ln(0)", "ln"),
    ("ln(-1)", "ln"),
    ("log10(0)", "log10"),
    ("log10(-1)", "log10"),
    ("exp(10000)", "exp"),
    # The `**` operator has its own route out of the reals.
    ("(-4) ** 0.5", "**"),
    ("(-8) ** (1/3)", "**"),
    ("0 ** -1", "**"),
    ("2 ** 10000", "**"),
]


def _project_with(tmp_path, body: str):
    write_project_config(
        tmp_path,
        "site: { title: D, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n```calc\n{body}\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    return project


# ------------------------------------------------------------- the evaluator


@pytest.mark.parametrize(("expression", "name"), DOMAIN_CASES)
def test_a_domain_failure_raises_calc_error(expression, name):
    """The one contract every function shares: leaving the reals is a CalcError.

    `math` says it three different ways -- ValueError for the log domain,
    OverflowError for exp, and a bare TypeError from comparing two complex
    tolerances -- and pint says it a fourth, by returning one.
    """
    with pytest.raises(calc.CalcError) as exc:
        calc.evaluate(expression, {})
    assert name in str(exc.value)


@pytest.mark.parametrize(("expression", "name"), DOMAIN_CASES)
def test_a_domain_failure_becomes_a_diagnostic_on_its_own_line(expression, name):
    """...and an error on the line, so the rest of the block still evaluates."""
    env: dict = {}
    outcomes = calc.evaluate_block(f"good = 1 V\nbad = {expression}\n", env)
    assert outcomes[0].error is None
    assert "good" in env, "a good line before the bad one still computes"
    assert outcomes[1].name == "bad"
    assert outcomes[1].error is not None
    assert name in outcomes[1].error
    assert "bad" not in env, "a line that failed does not bind a name"


def test_sqrt_of_a_negative_says_so_in_plain_words():
    with pytest.raises(calc.CalcError) as exc:
        calc.evaluate("sqrt(-1)", {})
    message = str(exc.value)
    assert "negative" in message
    assert "square root" in message


@pytest.mark.parametrize("expression", ["ln(0)", "ln(-1)", "log10(-1)"])
def test_a_log_of_a_non_positive_value_says_so(expression):
    with pytest.raises(calc.CalcError) as exc:
        calc.evaluate(expression, {})
    message = str(exc.value)
    assert "positive" in message


def test_a_range_that_dips_below_zero_is_caught_at_the_root_not_in_the_formatter():
    """`5 ± 6` is [-1, 11]: the nominal sqrt(5) is real, the low bound is not.

    Checking only the nominal value would let a complex tolerance through into
    `format_bounds`, which is where the original crash actually happened.
    """
    env: dict = {}
    outcomes = calc.evaluate_block("v = 5 ± 6\nw = sqrt(v)\n", env)
    assert outcomes[0].error is None
    assert outcomes[1].error is not None
    assert "sqrt" in outcomes[1].error


# ------------------------------------------------------------- the build


@pytest.mark.parametrize(("expression", "name"), DOMAIN_CASES)
def test_a_domain_failure_is_a_build_error_on_its_line(tmp_path, expression, name):
    project = _project_with(tmp_path, f"v = {expression}")
    build_mod.build(project)

    assert project.item_by_id("DEC-001")._calc_failed is True
    errors = [d for d in project.errors if name in d.message]
    assert errors, f"no build error mentioning {name!r}: {[d.message for d in project.errors]}"
    diagnostic = errors[0]
    assert diagnostic.file == "items/dec.md"
    assert diagnostic.item_id == "DEC-001"
    assert diagnostic.line is not None, "the diagnostic must name the calc line"
    # And the value never reaches the formatter, so there is nothing to crash on.
    assert project.item_by_id("DEC-001").calcs[0].result == ""
    assert project.item_by_id("DEC-001").calcs[0].bounds == ""


def test_sqrt_of_a_negative_fails_the_build_with_a_readable_diagnostic(tmp_path):
    project = _project_with(tmp_path, "v = sqrt(-1)")
    build_mod.build(project)
    message = next(d.message for d in project.errors)
    assert message == (
        "calc 'v': sqrt() of a negative value (-1) is not a real number — the "
        "square root of a negative number has no real value; check the sign of "
        "the argument"
    )


def test_the_cli_reports_a_domain_error_and_exits_1(tmp_path):
    """`refdes build` on a project with `v = sqrt(-1)`: a diagnostic and exit 1,
    the same as any other bad calc -- never a traceback."""
    _project_with(tmp_path, "v = sqrt(-1)")
    status = cli_mod.main(["-c", str(tmp_path / "refdes-project.yaml"), "build"])
    assert status == 1


def test_a_formatter_failure_is_still_a_diagnostic_not_a_crash(tmp_path, monkeypatch):
    """The last line of defence, and the one the original bug slipped past.

    `format_value` runs on a value the evaluator already accepted, outside the
    try/except that turns an evaluation failure into a line error. Anything that
    escapes it therefore has to be reported on that same line -- a diagnostic is
    recoverable, a traceback loses the whole build and the line that caused it.
    """
    project = _project_with(tmp_path, "v = 3.3 V * 1.2 A")

    def explode(*_args, **_kwargs):
        raise TypeError("float() argument must be a string or a real number")

    monkeypatch.setattr(calc, "format_value", explode)
    build_mod.build(project)

    diagnostic = next(d for d in project.errors if "P" in d.message or "v" in d.message)
    assert diagnostic.file == "items/dec.md"
    assert diagnostic.item_id == "DEC-001"
    assert diagnostic.line is not None
