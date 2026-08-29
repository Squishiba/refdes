"""Units-aware expression evaluation.

Deliberately not a programming language: assignments, arithmetic, units, and a
whitelist of functions. No loops, no conditionals, no imports, no attribute
access, no I/O. Nothing here can execute arbitrary code, so untrusted documents
are safe to build and every result is deterministic and cacheable.

Values carry a tolerance interval (nominal, lo, hi). Arithmetic propagates the
interval by corner evaluation, which is exact for monotonic expressions and
conservative-but-loose where a variable appears more than once (the classic
interval dependency problem: x - x reports a non-zero width).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

import pint

UREG = pint.UnitRegistry()
Q = UREG.Quantity


class CalcError(Exception):
    pass


# --------------------------------------------------------------------------- values


@dataclass
class Value:
    nom: object  # pint Quantity
    lo: object
    hi: object

    @classmethod
    def exact(cls, quantity) -> "Value":
        return cls(quantity, quantity, quantity)

    @property
    def has_width(self) -> bool:
        try:
            return bool(self.lo != self.hi)
        except Exception:
            return False

    @property
    def dimensionality(self):
        return self.nom.dimensionality


def _corners(*values: Value) -> list:
    out = []
    for v in values:
        out.append(v.lo)
        out.append(v.hi)
    return out


def _span(candidates: list, nominal) -> Value:
    unit = nominal.units
    converted = []
    for c in candidates:
        try:
            converted.append(c.to(unit))
        except pint.DimensionalityError as exc:
            raise CalcError(str(exc)) from exc
    return Value(nominal, min(converted), max(converted))


def _binary(op: str, a: Value, b: Value) -> Value:
    try:
        if op == "+":
            return Value(a.nom + b.nom, a.lo + b.lo, a.hi + b.hi)
        if op == "-":
            return Value(a.nom - b.nom, a.lo - b.hi, a.hi - b.lo)
        if op == "*":
            nom = a.nom * b.nom
            return _span([x * y for x in (a.lo, a.hi) for y in (b.lo, b.hi)], nom)
        if op == "/":
            if _spans_zero(b):
                raise CalcError("division by a value whose tolerance range includes zero")
            nom = a.nom / b.nom
            return _span([x / y for x in (a.lo, a.hi) for y in (b.lo, b.hi)], nom)
    except pint.DimensionalityError as exc:
        verb = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide"}[op]
        raise CalcError(
            f"cannot {verb} {a.nom.units:~P} and {b.nom.units:~P} "
            f"— the units do not match"
        ) from exc
    raise CalcError(f"unsupported operator {op!r}")


def _spans_zero(v: Value) -> bool:
    zero = 0 * v.lo.units
    return bool(v.lo <= zero <= v.hi)


def _power(base: Value, exponent: Value) -> Value:
    if exponent.has_width:
        raise CalcError("exponent must be an exact value, not a tolerance range")
    if not exponent.nom.dimensionless:
        raise CalcError("exponent must be dimensionless")
    e = float(exponent.nom.to("dimensionless").magnitude)
    if e != int(e) and _spans_zero(base):
        raise CalcError("fractional power of a range that includes zero")
    nom = base.nom**e
    candidates = [base.lo**e, base.hi**e]
    if _spans_zero(base) and int(e) == e and int(e) % 2 == 0:
        candidates.append(0 * nom.units)
    return _span(candidates, nom)


# ------------------------------------------------------------------------ functions


def _monotonic(fn, name: str):
    def apply(v: Value) -> Value:
        try:
            return Value(fn(v.nom), fn(v.lo), fn(v.hi))
        except pint.DimensionalityError as exc:
            raise CalcError(f"{name}() {exc}") from exc

    return apply


def _fn_abs(v: Value) -> Value:
    nom = abs(v.nom)
    if _spans_zero(v):
        return _span([0 * v.lo.units, abs(v.lo), abs(v.hi)], nom)
    return _span([abs(v.lo), abs(v.hi)], nom)


def _fn_min(*vs: Value) -> Value:
    nom = min(v.nom for v in vs)
    return _span(_corners(*vs), nom)


def _fn_max(*vs: Value) -> Value:
    nom = max(v.nom for v in vs)
    return _span(_corners(*vs), nom)


def _dimensionless(fn, name: str):
    def apply(v: Value) -> Value:
        if not v.nom.dimensionless:
            raise CalcError(f"{name}() needs a dimensionless argument, got {v.nom.units:~P}")

        wrap = lambda q: Q(fn(float(q.to("dimensionless").magnitude)), "dimensionless")  # noqa: E731
        return Value(wrap(v.nom), wrap(v.lo), wrap(v.hi))

    return apply


def _build_functions() -> dict:
    import math

    return {
        "sqrt": _monotonic(lambda q: q**0.5, "sqrt"),
        "abs": _fn_abs,
        "min": _fn_min,
        "max": _fn_max,
        "exp": _dimensionless(math.exp, "exp"),
        "ln": _dimensionless(math.log, "ln"),
        "log10": _dimensionless(math.log10, "log10"),
    }


FUNCTIONS = _build_functions()
MULTI_ARG = {"min", "max"}


# --------------------------------------------------------------------------- lexing

# A bare unit may only follow a numeric literal, and contains no whitespace.
# Segments are joined with '/' or '·'; exponents use '^'.
# Brackets are the escape hatch: `0.5 [h]` is unambiguously half an hour even when
# a variable named `h` is in scope, and anything goes inside them.
_SEGMENT = r"[A-Za-zΩµμ°][A-Za-z0-9_]*(?:\^-?\d+)?"
_UNIT_RUN = rf"{_SEGMENT}(?:[/·]{_SEGMENT})*"
_NUMBER = r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
QUANTITY_RE = re.compile(
    rf"(?<![A-Za-z0-9_.])({_NUMBER})\s*(?:\[\s*([^\]]+?)\s*\]|({_UNIT_RUN}))?"
)


# Units whose everyday hardware meaning differs from pint's default.
#
# `mil` is the worst offender: pint reads it as the angular mil (a dimensionless
# NATO artillery unit), while every PCB engineer means a thousandth of an inch.
# Left alone, `62 mil` silently becomes a dimensionless 62 instead of 1.5748 mm --
# precisely the silent wrong answer this tool exists to prevent.
DEFAULT_UNIT_ALIASES = {"mil": "thou", "mils": "thou"}
_unit_aliases = dict(DEFAULT_UNIT_ALIASES)

_ALIAS_TOKEN_RE = re.compile(r"[A-Za-zΩµμ°]+")


def set_unit_aliases(extra: dict | None = None) -> None:
    _unit_aliases.clear()
    _unit_aliases.update(DEFAULT_UNIT_ALIASES)
    for name, target in (extra or {}).items():
        _unit_aliases[str(name)] = str(target)


def _to_pint_units(unit: str) -> str:
    unit = unit.replace("^", "**").replace("·", "*").replace("µ", "μ")
    if not _unit_aliases:
        return unit
    return _ALIAS_TOKEN_RE.sub(
        lambda m: _unit_aliases.get(m.group(0), m.group(0)), unit
    )


def _lex(expression: str) -> str:
    """Rewrite `1.2 A` into `_q('1.2','A')` so the result is valid Python syntax."""

    def repl(match: re.Match) -> str:
        number = match.group(1)
        unit = match.group(2) if match.group(2) is not None else match.group(3)
        if unit is None:
            return f"_q('{number}','')"
        return f"_q('{number}','{_to_pint_units(unit)}')"

    return QUANTITY_RE.sub(repl, expression)


def is_known_unit(token: str) -> bool:
    try:
        UREG.parse_expression(_to_pint_units(token))
        return True
    except Exception:
        return False


def check_ambiguity(expression: str, names: set[str]) -> str | None:
    """Flag `0.5 h` when `h` is both a valid unit and a variable in this block.

    This is a warning rather than an error, because the grammar is not actually
    ambiguous: juxtaposition never means multiplication, so `0.5 h` has exactly one
    parse. The risk is only that the author *believed* it meant `0.5 * h`. Single
    letter variables collide with SI units constantly -- A for area, C for
    capacitance, L for inductance, R for resistance -- so erroring here would reject
    normal engineering notation.

    Only bare units are checked; a bracketed `[h]` is an explicit statement of
    intent. Only whole single-token unit runs count, since a segment inside a
    compound like `W/h` cannot be anything but a unit.
    """
    for match in QUANTITY_RE.finditer(expression):
        bare = match.group(3)
        if not bare or bare not in names:
            continue
        if is_known_unit(bare):
            return (
                f"`{match.group(1)} {bare}` reads {bare!r} as a unit, but a variable "
                f"of that name is also defined here. Write `{match.group(1)} [{bare}]` "
                f"to silence this, or rename the variable if you meant to multiply."
            )
    return None


def quantity(number: str, unit: str) -> Value:
    try:
        q = Q(float(number), unit) if unit else Q(float(number), "dimensionless")
    except Exception as exc:  # pint raises several types for bad unit strings
        raise CalcError(f"unknown unit {unit!r}") from exc
    return Value.exact(q)


def parse_quantity(text: str) -> Value:
    """Parse a standalone quantity such as '2 W/in^2' or '3.3 V'."""
    return evaluate(text.strip(), {})


# ------------------------------------------------------------------------ evaluating

_ALLOWED_BINOPS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
}


def _eval_node(node: ast.AST, env: dict[str, Value]) -> Value:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, env)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError(f"unsupported literal {node.value!r}")
        return Value.exact(Q(float(node.value), "dimensionless"))

    if isinstance(node, ast.Name):
        if node.id not in env:
            raise CalcError(f"unknown name {node.id!r}")
        return env[node.id]

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            v = _eval_node(node.operand, env)
            return Value(-v.nom, -v.hi, -v.lo)
        if isinstance(node.op, ast.UAdd):
            return _eval_node(node.operand, env)
        raise CalcError("unsupported unary operator")

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, env)
        right = _eval_node(node.right, env)
        if isinstance(node.op, ast.Pow):
            return _power(left, right)
        op = _ALLOWED_BINOPS.get(type(node.op))
        if op is None:
            raise CalcError(f"unsupported operator {type(node.op).__name__}")
        return _binary(op, left, right)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalcError("only plain function calls are allowed")
        name = node.func.id
        if name == "_q":
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if len(args) != 2:
                raise CalcError("malformed quantity literal")
            return quantity(str(args[0]), str(args[1]))
        fn = FUNCTIONS.get(name)
        if fn is None:
            raise CalcError(
                f"unknown function {name!r}; available: {', '.join(sorted(FUNCTIONS))}"
            )
        if node.keywords:
            raise CalcError("keyword arguments are not supported")
        args = [_eval_node(a, env) for a in node.args]
        if name not in MULTI_ARG and len(args) != 1:
            raise CalcError(f"{name}() takes exactly one argument")
        if not args:
            raise CalcError(f"{name}() needs at least one argument")
        return fn(*args)

    raise CalcError(f"{type(node).__name__} is not allowed in an expression")


def evaluate(expression: str, env: dict[str, Value]) -> Value:
    source = _lex(expression)
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"could not parse expression: {exc.msg}") from exc
    return _eval_node(tree, env)


# ------------------------------------------------------------------- tolerance forms

TOLERANCE_SPLIT = re.compile(r"\s*(?:±|\+/-)\s*")
PERCENT_RE = re.compile(rf"^({_NUMBER})\s*%$")


def evaluate_assignment(expression: str, env: dict[str, Value]) -> Value:
    """Evaluate a right-hand side, honouring a trailing `± tolerance`."""
    parts = TOLERANCE_SPLIT.split(expression)
    if len(parts) == 1:
        return evaluate(expression, env)
    if len(parts) > 2:
        raise CalcError("only one ± tolerance is allowed per assignment")

    base = evaluate(parts[0], env)
    if base.has_width:
        raise CalcError("cannot apply ± to a value that already has a tolerance")

    tol_text = parts[1].strip()
    percent = PERCENT_RE.match(tol_text)
    if percent:
        fraction = float(percent.group(1)) / 100.0
        delta = abs(base.nom) * fraction
    else:
        tol = evaluate(tol_text, env)
        if tol.has_width:
            raise CalcError("tolerance must be an exact value")
        try:
            delta = abs(tol.nom.to(base.nom.units))
        except pint.DimensionalityError as exc:
            raise CalcError(f"tolerance units do not match the value: {exc}") from exc

    return Value(base.nom, base.nom - delta, base.nom + delta)


# -------------------------------------------------------------------------- limits


@dataclass
class Limit:
    kind: str          # "<=" | ">=" | "<" | ">" | "==" | "range"
    low: Value | None
    high: Value | None
    text: str

    def check(self, value: Value, digits: int = 4) -> tuple[bool, str]:
        """Evaluate worst-case: the tolerance bound that is hardest to satisfy."""
        try:
            if self.kind in ("<=", "<"):
                worst = value.hi
                bound = self.high.nom
                ok = worst <= bound if self.kind == "<=" else worst < bound
                return ok, f"worst case {format_quantity(worst, digits)} vs {self.text}"
            if self.kind in (">=", ">"):
                worst = value.lo
                bound = self.low.nom
                ok = worst >= bound if self.kind == ">=" else worst > bound
                return ok, f"worst case {format_quantity(worst, digits)} vs {self.text}"
            if self.kind == "==":
                ok = bool(value.lo == self.low.nom and value.hi == self.low.nom)
                return ok, f"{format_value(value, digits)} vs {self.text}"
            if self.kind == "range":
                ok = bool(value.lo >= self.low.nom and value.hi <= self.high.nom)
                return ok, f"range {format_value(value, digits)} vs {self.text}"
        except pint.DimensionalityError as exc:
            raise CalcError(f"cannot compare: {exc}") from exc
        raise CalcError(f"unsupported limit kind {self.kind!r}")

    def margin(self, value: Value) -> float | None:
        """Fractional headroom against the worst-case bound, or None if meaningless.

        Positive is slack, negative is a violation, and 0.05 means "five percent
        away from the limit". Pass/fail alone hides the difference between a design
        that clears a thermal limit by half and one that clears it by a hair, which
        is exactly the distinction a design review needs.

        Measured relative to the limit itself, so it is comparable across unrelated
        quantities -- a 3% thermal margin and a 3% voltage margin mean the same
        thing to a reviewer.

        None for an *offset* unit (`degC`, `degF`) on a one-sided comparison:
        dividing a temperature difference by a temperature reading is the
        ambiguous operation pint refuses outright, and rightly so -- "45 degC
        of slack against an 85 degC limit" is 53% or 13% depending entirely
        on where you put zero, so there is no fraction to report. The check
        itself is unaffected: comparing two temperatures is well-defined, and
        a limit written on an absolute scale (`<= 350 K`) or as a range
        (`0 degC .. 60 degC`, whose reference is itself a difference) still
        gets a real margin.
        """
        try:
            if self.kind in ("<=", "<"):
                bound = self.high.nom
                return _relative(bound - value.hi, bound)
            if self.kind in (">=", ">"):
                bound = self.low.nom
                return _relative(value.lo - bound, bound)
            if self.kind == "range":
                span = self.high.nom - self.low.nom
                below = value.lo - self.low.nom
                above = self.high.nom - value.hi
                # The nearer edge is the one that will fail first.
                return _relative(min(below, above), span)
            # An equality has no notion of "how close", only met or not.
            return None
        except (pint.PintError, ZeroDivisionError, ValueError):
            return None


def _relative(slack, reference) -> float | None:
    """slack / |reference| as a plain float, or None if the reference is zero."""
    magnitude = abs(float(reference.magnitude)) if hasattr(reference, "magnitude") else abs(float(reference))
    if magnitude == 0:
        return None
    ratio = slack / abs(reference)
    return float(ratio.magnitude if hasattr(ratio, "magnitude") else ratio)


RANGE_RE = re.compile(r"^(.*?)\s*\.\.\s*(.*)$")
COMPARE_RE = re.compile(r"^\s*(<=|>=|==|<|>)\s*(.+)$")

# Heuristic for the parse-failure hint below: text with two or more numbers
# *and* a list-like conjunction (", ", "; ", " and ", " with ") reads as
# several bounds run together in prose -- e.g. "±1 % ... 0-60 degC, with 12 V
# TVS protection" -- rather than one malformed comparison or range. Neither
# signal alone is enough (a tolerance like "100 ohm ±5%" has two numbers but
# no conjunction; "somewhere under 2 watts" has a conjunction-free typo and
# only one number), so both are required to keep the hint rare.
_LIMIT_NUMBER_RE = re.compile(r"[-+±]?\d+(?:\.\d+)?")
_LIMIT_CONJUNCTION_RE = re.compile(r",\s|;\s|\band\b|\bwith\b", re.IGNORECASE)


def _multi_bound_hint(raw: str) -> str:
    if len(_LIMIT_NUMBER_RE.findall(raw)) >= 2 and _LIMIT_CONJUNCTION_RE.search(raw):
        return (
            "\nnote: if this limit describes more than one bound, split it into "
            "one item per bound"
        )
    return ""


def parse_limit(text: str) -> Limit:
    raw = str(text).strip()
    compare = COMPARE_RE.match(raw)
    if compare:
        op, rest = compare.group(1), compare.group(2)
        value = parse_quantity(rest)
        if op in ("<=", "<"):
            return Limit(op, None, value, raw)
        if op in (">=", ">"):
            return Limit(op, value, None, raw)
        return Limit("==", value, value, raw)

    span = RANGE_RE.match(raw)
    if span:
        low_text, high_text = span.group(1), span.group(2)
        high = parse_quantity(high_text)
        # "9 .. 36 V" -- borrow the unit from the upper bound when the lower omits it.
        low = parse_quantity(low_text)
        if low.nom.dimensionless and not high.nom.dimensionless:
            low = Value.exact(Q(low.nom.magnitude, high.nom.units))
        return Limit("range", low, high, raw)

    raise CalcError(
        f"could not read limit {raw!r}; expected a comparison such as '<= 2 W/in^2' "
        f"or a range such as '9 V .. 36 V'" + _multi_bound_hint(raw)
    )


# ------------------------------------------------------------------------ formatting

_preferred_cache: list = []

# Named derived units worth collapsing to by default, so formatting is sensible
# even when no project config has been loaded.
DEFAULT_PREFERRED = ["W", "V", "A", "ohm", "F", "H", "Hz", "J", "N", "Pa", "s", "m", "g"]


def set_preferred_units(units: list[str]) -> None:
    _preferred_cache.clear()
    for name in units or DEFAULT_PREFERRED:
        try:
            _preferred_cache.append((UREG.parse_expression(name).units, name))
        except Exception:
            continue


set_preferred_units(DEFAULT_PREFERRED)


def _unit_map(q) -> dict:
    """{'ampere': 1, 'volt': 1, 'inch': -2} for the units of a quantity."""
    try:
        return dict(q.units._units)
    except Exception:
        return {}


def _simplify(q):
    """Name derived sub-products without overriding the author's own units.

    `volt*ampere/inch**2` becomes `W/in^2`: the {volt, ampere} subset carries the
    dimensionality of a watt, so it collapses to W and the inch**2 the author wrote
    is left exactly as they wrote it. An author who writes `W/in^2` gets it back
    unchanged, because the matching subset is already a single named unit.
    """
    from itertools import combinations

    from pint.util import UnitsContainer

    units = _unit_map(q)
    if not units:
        return q

    # A single unit at exponent +1 is something the author typed -- `1.4 inch`,
    # `0.5 h`, `12 V`. Never rewrite it. Reciprocals and compounds are derived
    # results, so `1/µs` collapsing to kHz is still fair game.
    if len(units) == 1 and next(iter(units.values())) == 1:
        return q

    names = list(units)
    # Prefer collapsing larger subsets first: {volt, ampere} -> W beats {volt} -> V.
    for size in range(len(names), 0, -1):
        for subset in combinations(names, size):
            part = UnitsContainer({n: units[n] for n in subset})
            try:
                part_q = Q(1, part)
            except Exception:
                continue
            for target, _name in _preferred_cache:
                if _unit_count_units(target) != 1:
                    continue
                if part_q.dimensionality != Q(1, target).dimensionality:
                    continue
                try:
                    rest = UnitsContainer(
                        {n: e for n, e in units.items() if n not in subset}
                    )
                    combined = (Q(1, target) * Q(1, rest)).units
                    if combined == q.units:
                        return q
                    return q.to(combined).to_compact()
                except Exception:
                    continue
    return q


def _unit_count_units(units) -> int:
    try:
        return len(dict(units._units))
    except Exception:
        return 1


def _sigfig_str(magnitude: float, digits: int) -> str:
    """Render `magnitude` to `digits` significant figures.

    Plain `:.{digits}g` flips to scientific notation as soon as the integer part
    outgrows `digits` -- 606.0606 at 2 sigfigs becomes "6.1e+02", which no
    datasheet or review would write. This prefers positional notation as long as
    only a couple of trailing zeros have to be invented to reach the right order
    of magnitude (issue #3 finding 14): 606.0606 at 2 sigfigs becomes "610" (one
    invented zero). 1234567 at 4 sigfigs would need three invented zeros to stay
    positional, so it keeps the exponent: "1.235e+06".
    """
    text = f"{magnitude:.{digits}g}"
    if "e" not in text:
        return text
    exponent = int(text.split("e")[1])
    if exponent < 0 or exponent - digits + 1 > 2:
        return text
    return f"{float(text):.0f}"


def format_quantity(q, digits: int = 4) -> str:
    # Only a genuinely unitless number prints bare. `50 ppm` and `10 dBm` are
    # dimensionless but carry a unit, and dropping it would hide what the value is.
    if not _unit_map(q):
        return _sigfig_str(float(q.magnitude), digits)
    if q.dimensionless:
        return f"{_sigfig_str(float(q.magnitude), digits)} {q.units:~P}"
    try:
        shown = _simplify(q)
    except Exception:
        shown = q
    return f"{_sigfig_str(float(shown.magnitude), digits)} {shown.units:~P}"


def format_value(value: Value, digits: int = 4) -> str:
    return format_quantity(value.nom, digits)


def format_bounds(value: Value, digits: int = 4) -> str:
    if not value.has_width:
        return ""
    return f"{format_quantity(value.lo, digits)} … {format_quantity(value.hi, digits)}"


# ------------------------------------------------------------------------ calc blocks

CALC_BLOCK_RE = re.compile(r"^```calc[^\n]*\n(.*?)^```\s*$", re.DOTALL | re.MULTILINE)
ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
# Optional unit assertion: `P_diss : W = V_out * I_load`
ANNOTATED_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^=]+?)\s*=\s*(.+?)\s*$"
)


@dataclass
class CalcOutcome:
    name: str
    expression: str
    comment: str
    value: Value | None
    error: str | None
    annotation: str = ""
    warning: str | None = None
    # Absolute 1-indexed source line, or None when the caller didn't supply
    # evaluate_block a start_line to compute one from.
    line: int | None = None


def assigned_names(source: str) -> set[str]:
    """Every name a block assigns, collected before evaluation.

    Needed up front because a variable can be defined below the line where its
    name first collides with a unit.
    """
    names: set[str] = set()
    for raw_line in source.splitlines():
        line = raw_line.partition("#")[0].strip()
        if not line:
            continue
        match = ANNOTATED_RE.match(line) or ASSIGN_RE.match(line)
        if match:
            names.add(match.group(1))
    return names


def convert_value(value: Value, unit: str) -> Value:
    """Re-express a value in the author's declared unit, asserting dimensionality."""
    target = _to_pint_units(unit)
    try:
        return Value(value.nom.to(target), value.lo.to(target), value.hi.to(target))
    except pint.DimensionalityError as exc:
        raise CalcError(
            f"declared as {unit} but the expression evaluates to "
            f"{value.nom.units:~P}"
        ) from exc
    except Exception as exc:
        raise CalcError(f"unknown unit {unit!r} in declaration") from exc


def evaluate_block(
    source: str,
    env: dict[str, Value],
    start_line: int | None = None,
    origins: dict[str, int | None] | None = None,
) -> list[CalcOutcome]:
    """Evaluate one ```calc block, threading `env` through the lines.

    `start_line` is the absolute 1-indexed source line of this block's first
    line (`source.splitlines()[0]`), or None when the caller has no source
    position for it (see Item.body_line) -- every CalcOutcome.line is then
    None too, rather than a guess.

    `origins` maps every name already assigned -- in this block or an earlier
    one -- to the line it was first assigned on, and is mutated in place so a
    caller threading the same dict across every block of one item (exactly
    how `env` itself is already threaded, per the "not shared between items"
    rule in docs/math.md) gets whole-item duplicate detection for free. A
    fresh call with no `origins` only catches a repeat within this one call.
    """
    outcomes: list[CalcOutcome] = []
    names = assigned_names(source)
    if origins is None:
        origins = {}

    for offset, raw_line in enumerate(source.splitlines()):
        line_number = start_line + offset if start_line is not None else None
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue

        comment = ""
        if "#" in line:
            line, _, comment = line.partition("#")
            comment = comment.strip()
            line = line.rstrip()

        annotation = ""
        match = ANNOTATED_RE.match(line)
        if match:
            name, annotation, expression = match.groups()
            # Finding 9: a tolerance belongs on the right-hand side (evaluate_
            # assignment splits on it there); one character to the left, next to
            # the unit assertion, "W ± 10%" can never parse as a unit. Caught
            # here, ahead of evaluation, so the message names the fix instead of
            # describing what the parser saw ("unknown unit 'W ± 10%'").
            tol_parts = TOLERANCE_SPLIT.split(annotation, maxsplit=1)
            if len(tol_parts) == 2:
                unit_part, tol_part = tol_parts[0].strip(), tol_parts[1].strip()
                outcomes.append(
                    CalcOutcome(
                        name, expression, comment, None,
                        "a tolerance belongs on the right-hand side — "
                        f"{name} : {unit_part} = {expression} ± {tol_part}",
                        annotation, line=line_number,
                    )
                )
                continue
        else:
            match = ASSIGN_RE.match(line)
            if not match:
                outcomes.append(
                    CalcOutcome("", line.strip(), comment, None,
                                "expected an assignment of the form 'name = expression'",
                                line=line_number)
                )
                continue
            name, expression = match.group(1), match.group(2)

        if name in origins:
            first_line = origins[name]
            first_where = f"line {first_line}" if first_line is not None else "earlier in this item"
            here_where = f"line {line_number}" if line_number is not None else "here"
            outcomes.append(
                CalcOutcome(
                    name, expression, comment, None,
                    f"{name!r} is assigned twice in this item -- first at "
                    f"{first_where}, again at {here_where}. A name can only be "
                    f"assigned once per item (blocks share one item-wide scope); "
                    f"rename one of them, e.g. {name!r} -> {name + '_2'!r}.",
                    annotation, line=line_number,
                )
            )
            continue

        warning = check_ambiguity(expression, names)
        try:
            value = evaluate_assignment(expression, env)
            if annotation:
                value = convert_value(value, annotation)
        except CalcError as exc:
            outcomes.append(
                CalcOutcome(name, expression, comment, None, str(exc), annotation,
                            warning, line=line_number)
            )
            continue
        except Exception as exc:  # pint and math surface a variety of types
            outcomes.append(
                CalcOutcome(name, expression, comment, None, str(exc), annotation,
                            warning, line=line_number)
            )
            continue

        env[name] = value
        origins[name] = line_number
        outcomes.append(
            CalcOutcome(name, expression, comment, value, None, annotation,
                        warning, line=line_number)
        )
    return outcomes


def extract_blocks(body: str) -> list[str]:
    return [block for block, _ in extract_blocks_with_lines(body)]


def extract_blocks_with_lines(body: str) -> list[tuple[str, int]]:
    """Like extract_blocks, but paired with each block's 0-indexed line offset
    within `body` -- the piece a caller needs to turn a line number inside the
    block into an absolute source line (add Item.body_line)."""
    out = []
    for match in CALC_BLOCK_RE.finditer(body):
        block = match.group(1)
        offset = body.count("\n", 0, match.start(1))
        out.append((block, offset))
    return out
