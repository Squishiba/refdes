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


def value_signature(value: Value) -> str:
    """A canonical, full-precision text of a Value -- nominal, low and high,
    each magnitude with its unit -- for content hashing (finding 35). Not the
    sigfig-formatted result: rounding the display digits must not move a hash,
    and a change the display would round away must still register."""
    return "|".join(
        f"{q.magnitude!r} {q.units}" for q in (value.nom, value.lo, value.hi)
    )


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


# ---------------------------------------------------------------- project equations


@dataclass
class Equation:
    """A named expression declared in `refdes-project.yaml`'s `equations:` and callable
    from any calc block: `current_limit(2500, 0.8 V, 3.3 kohm)`.

    Calling one is not a `FUNCTIONS` call: the arguments bind to `params` in a
    fresh environment and `expr` goes back through `evaluate`, so units, tolerances,
    and every diagnostic are exactly what the body would produce written inline.
    `note` is provenance (a datasheet page), read by whoever edits the definition
    and by nothing at build time.
    """

    name: str
    params: list[str]
    expr: str
    note: str = ""


# One project-wide namespace, replaced wholesale by `set_equations` on config
# load -- the same posture `set_unit_aliases` already takes.
EQUATIONS: dict[str, Equation] = {}

# `_q` is the quantity literal the lexer emits, intercepted ahead of any registry
# lookup, so an equation registered under it could never be reached.
RESERVED_NAMES = {"_q", "source"}

EQUATION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def set_equations(equations: dict[str, Equation] | None) -> None:
    """Replace the project equation namespace, validating it first.

    Validation lives here rather than in the caller so "shadowing a built-in is a
    hard error" has no route around it: nothing can populate `EQUATIONS` without
    passing `validate_equations`.
    """
    equations = dict(equations or {})
    validate_equations(equations)
    EQUATIONS.clear()
    EQUATIONS.update(equations)


def validate_equations(equations: dict[str, Equation]) -> None:
    """Reject an equation that shadows a built-in, and any cycle between them.

    Shadowing is an error rather than an override because `sqrt` has to mean one
    thing in every expression on the site: a project silently redefining it makes
    every other block's arithmetic wrong, and nothing downstream can tell.

    Cycles follow `blocked.py`'s precedent for `blocked_by` -- the walk reports the
    path that closes the loop and the build stops on it, rather than recursing.
    """
    for name in equations:
        if name in FUNCTIONS:
            raise CalcError(
                f"{name!r} is a built-in function; a project equation cannot "
                "shadow it — rename the equation"
            )
        if name in RESERVED_NAMES:
            raise CalcError(f"{name!r} is reserved; a project equation cannot use it")
        if not EQUATION_NAME_RE.match(str(name)):
            raise CalcError(
                f"{name!r} is not a usable equation name; use letters, digits, "
                "and underscores, starting with a letter or underscore"
            )
    for name, eq in equations.items():
        # docs/design/calc-sources.md §9: an equation is a project-wide formula,
        # so it may not reach into a file -- only an item's own calc line, whose
        # item cites the file, can. A source-derived Value may be passed in.
        for node in ast.walk(parse_expression(eq.expr)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "source"):
                raise CalcError(
                    f"equation {name!r} calls source(); source() is only valid "
                    "as the whole right-hand side of an item's own calc line"
                )
    for name in equations:
        _walk_equation_cycle(name, equations, [])


def _equation_references(eq: Equation, equations: dict[str, Equation]) -> list[str]:
    """Equation names this body calls. A parameter of the same name binds locally,
    so it is not a reference to the equation."""
    params = set(eq.params)
    found = []
    for node in ast.walk(parse_expression(eq.expr)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name not in params and name in equations and name not in found:
                found.append(name)
    return found


def _walk_equation_cycle(
    name: str, equations: dict[str, Equation], path: list[str]
) -> None:
    if name in path:
        raise CalcError(f"equation cycle: {' -> '.join([*path, name])}")
    for dep in _equation_references(equations[name], equations):
        _walk_equation_cycle(dep, equations, [*path, name])


# Equations currently mid-evaluation. `validate_equations` should make this
# unreachable; it is the backstop for a registry populated some other way, so a
# cycle is still a diagnostic rather than a RecursionError.
_equation_stack: list[str] = []


def _call_equation(eq: Equation, node: ast.Call, env: dict[str, Value]) -> Value:
    if node.keywords:
        raise CalcError("keyword arguments are not supported")
    if len(node.args) != len(eq.params):
        expected = ", ".join(eq.params) if eq.params else "none"
        raise CalcError(
            f"{eq.name}() takes {len(eq.params)} argument(s) ({expected}), "
            f"got {len(node.args)}"
        )
    args = [_eval_node(a, env) for a in node.args]
    if eq.name in _equation_stack:
        raise CalcError(f"equation cycle: {' -> '.join([*_equation_stack, eq.name])}")
    local = dict(zip(eq.params, args))
    _equation_stack.append(eq.name)
    try:
        return _eval_node(parse_expression(eq.expr), local)
    finally:
        _equation_stack.pop()


# --------------------------------------------------------------------------- lexing

# A bare unit may only follow a numeric literal, and contains no whitespace.
# Segments are joined with '/' or '·'; exponents use '^'.
# Ω, µ (U+00B5), μ (U+03BC) and ° are legal anywhere in a segment, not just
# first: prefixed resistances (`kΩ`, `MΩ`) put Ω after the prefix, which is the
# normal spelling. `%` is its own alternative in the run, not a segment
# character, so `85 %` reads as a percent quantity without letting `%` leak
# into the middle of an ordinary unit.
# Brackets are the escape hatch: `0.5 [h]` is unambiguously half an hour even when
# a variable named `h` is in scope, and anything goes inside them.
_SEGMENT = r"[A-Za-zΩµμ°][A-Za-z0-9_Ωµμ°]*(?:\^-?\d+)?"
_UNIT_RUN = rf"(?:{_SEGMENT}(?:[/·]{_SEGMENT})*|%)"
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
        if name == "source":
            raise CalcError(
                "source() is only valid as the whole right-hand side of an item "
                'calc line: name = source("cited/file.csv", "key") | unit'
            )
        if name == "_q":
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if len(args) != 2:
                raise CalcError("malformed quantity literal")
            return quantity(str(args[0]), str(args[1]))
        fn = FUNCTIONS.get(name)
        if fn is None:
            eq = EQUATIONS.get(name)
            if eq is None:
                available = ", ".join(sorted([*FUNCTIONS, *EQUATIONS]))
                raise CalcError(f"unknown function {name!r}; available: {available}")
            return _call_equation(eq, node, env)
        if node.keywords:
            raise CalcError("keyword arguments are not supported")
        args = [_eval_node(a, env) for a in node.args]
        if name not in MULTI_ARG and len(args) != 1:
            raise CalcError(f"{name}() takes exactly one argument")
        if not args:
            raise CalcError(f"{name}() needs at least one argument")
        return fn(*args)

    raise CalcError(f"{type(node).__name__} is not allowed in an expression")


def parse_expression(expression: str):
    """Lex and parse an expression into an `ast.Expression`, without evaluating it.

    Split out so a stored expression (a project equation's body) can be checked
    for syntax when it is declared, not the first time something calls it."""
    source = _lex(expression)
    try:
        return ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise CalcError(
            f"could not parse expression {expression!r}: {exc.msg}"
        ) from exc


def evaluate(expression: str, env: dict[str, Value]) -> Value:
    return _eval_node(parse_expression(expression), env)


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

    return apply_tolerance(evaluate(parts[0], env), parts[1], env)


def apply_tolerance(base: Value, tol_text: str, env: dict[str, Value]) -> Value:
    """`base ± tol_text`: the tolerance half of `evaluate_assignment`, split out
    so a `source()` line (whose base is a locked scalar, not an expression)
    honours exactly the same grammar."""
    if base.has_width:
        raise CalcError("cannot apply ± to a value that already has a tolerance")

    tol_text = tol_text.strip()
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


class CalcFenceError(CalcError):
    """A ```calc fence info string that is not a valid attribute list
    (docs/design/named-calc-blocks.md §3.3, §7). Raised by `parse_fence_attrs`;
    the build reports it at the fence line as a build error."""


# A block name (docs/design/named-calc-blocks.md §3.3): lowercase-initial,
# lowercase-hyphen like citation ids and figure ids, 1-40 characters. Value
# names (`P_diss`, `V_in`) are a different namespace and unchanged.
BLOCK_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,39}")


def _suggest_block_name(name: str) -> str:
    """The fix a bad block name gets: lowercased, invalid characters dropped,
    leading digits dropped ('Losses' -> 'losses', '1losses' -> 'losses').
    Falls back to the lowercased original when nothing survives."""
    candidate = re.sub(r"[^a-z0-9_-]", "", name.lower()).lstrip("0123456789")
    if not BLOCK_NAME_RE.fullmatch(candidate):
        return name.lower()
    return candidate


def parse_fence_attrs(info: str) -> str | None:
    """Parse the info string of a ```calc fence -- everything between the
    fence marker and the newline -- and return the block's `id` or None.

    The grammar (docs/design/named-calc-blocks.md §3.3):

        calc-fence  = "```calc" [ 1*WSP attribute *(" " attribute) ] EOL
        attribute   = "id=" dquote name dquote
        name        = lowercase-letter [ *( lowercase-letter | digit | "_" | "-" ) ]

    `id` is the only attribute defined; anything else is a CalcFenceError
    naming the accepted set (§7's messages, verbatim). This replaces "any
    trailing text is silently ignored" (§2) with a validated attribute --
    a deliberate compatibility change (§3.4).
    """
    text = info.strip()
    if not text:
        return None
    block_id: str | None = None
    for token in text.split():
        key, sep, value = token.partition("=")
        if not sep:
            raise CalcFenceError(
                f"calc fence: {token!r} is not an attribute -- attributes are "
                f'key="value"; write id="{token}".'
            )
        if key != "id":
            raise CalcFenceError(
                f"calc fence: unknown attribute {key!r} -- a calc fence accepts "
                f'id="..."; write id="{value.strip(chr(34))}".'
            )
        if block_id is not None:
            raise CalcFenceError(
                'calc fence: id is given twice -- a calc fence accepts one '
                'id="..."; keep one.'
            )
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            name = value[1:-1]
            if not BLOCK_NAME_RE.fullmatch(name):
                raise CalcFenceError(
                    f"calc fence: block name {name!r} must match "
                    f"[a-z][a-z0-9_-]* -- write '{_suggest_block_name(name)}'."
                )
            block_id = name
            continue
        bare = value.strip('"')
        raise CalcFenceError(
            f"calc fence: {bare!r} is not an attribute -- attributes are "
            f'key="value"; write id="{bare}".'
        )
    return block_id


def _fence_info(match: re.Match) -> str:
    """The info string of a CALC_BLOCK_RE match: the fence line's text after
    the opening ```calc."""
    head = match.group(0).split("\n", 1)[0]
    return head[len("```calc"):]


def fence_errors(body: str) -> list[tuple[int, str]]:
    """(0-indexed line of the fence within `body`, message) for every calc
    fence whose info string fails `parse_fence_attrs`. The caller turns each
    into a build error at the fence's absolute line -- `extract_blocks_with_lines`
    stays lenient (an unnamed `None` for a bad fence) so hashing, rendering
    and citation walks never crash on a project that is already failing."""
    out: list[tuple[int, str]] = []
    for match in CALC_BLOCK_RE.finditer(body):
        try:
            parse_fence_attrs(_fence_info(match))
        except CalcFenceError as exc:
            out.append((body.count("\n", 0, match.start()), str(exc)))
    return out

ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
# Retired spelling of the unit assertion: `P_diss : W = V_out * I_load`.
# Matched only to produce the error that names the fix -- it is no longer
# evaluated. `refdes calc-rewrite` migrates a whole project at once.
ANNOTATED_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^=]+?)\s*=\s*(.+?)\s*$"
)
# The unit a result is presented in, after the expression: `P = V * I | mW`.
# The last `|` on the line is the separator, so a stray `|` inside the
# expression (bitwise-or is not in the language, so it can only be a typo)
# still leaves the trailing unit where the author wrote it. Comments are
# stripped before this runs, and the language has no string literals, so a
# `|` anywhere on a live line is this separator or a parse error.
PIPE_UNIT_RE = re.compile(r"^(?P<lhs>.+?)\s*\|\s*(?P<unit>[^|]+?)\s*$")
# A cross-item calc reference (finding 35 chunk 1): the whole right-hand side
# is one dotted reference into another item -- `V_in = DEC-PWR-001.V_in`, or
# with the composite key half `V_in = DEC-PWR-001@k7f3m2q9x4a.V_in`, or with
# the pipe unit `V_in = DEC-PWR-001.V_in | V`. The target half is exactly what
# `resolve_link_target` accepts (a bare display id, a bare key, or a
# `DISPLAY-ID@key` composite); the name half is any name the target's calc
# blocks assign. A dotted RHS is *only* a reference: nothing else in the
# language has attribute access, so there is no other parse it could shadow.
CROSS_REF_RE = re.compile(
    r"^(?P<target>[A-Za-z0-9][A-Za-z0-9_-]*(?:@[A-Za-z0-9_-]+)?)"
    r"\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)$"
)
# A dotted reference with a block half spliced in: `DEC-PWR-001.losses.P_diss`.
# Rejected, never resolved (docs/design/named-calc-blocks.md §4.2, §7): a calc
# value is named by ITEM.NAME and that is already unique per item. CROSS_REF_RE
# allows exactly one dot, so any dotted reference with two or more is this.
BLOCK_QUALIFIED_REF_RE = re.compile(
    r"^(?P<target>[A-Za-z0-9][A-Za-z0-9_-]*(?:@[A-Za-z0-9_-]+)?)"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*){2,}$"
)
# `eff = source("analysis/power-budget.csv", "tps62913_half_load_eff") | 1`
# (docs/design/calc-sources.md §1): the whole right-hand side is one call with
# exactly two string literals, optionally followed by `± tolerance`. Strings
# have no escapes -- a quote inside a path or key is not supported -- so the
# grammar has one reading. The pipe unit has already been split off by then.
_STRING = r"""(?:"([^"]*)"|'([^']*)')"""
SOURCE_CALL_RE = re.compile(
    rf"^source\(\s*{_STRING}\s*,\s*{_STRING}\s*\)\s*(?:(?:±|\+/-)\s*(?P<tol>.+?))?\s*$"
)
SOURCE_START_RE = re.compile(r"^source\s*\(")


def parse_source_call(expression: str) -> tuple[str, str, str] | None:
    """`(path, key, tolerance text or "")` for a well-formed source() right-hand
    side, or None when the text is not one. A caller that sees
    SOURCE_START_RE match but this return None reports a malformed call."""
    match = SOURCE_CALL_RE.match(expression.strip())
    if not match:
        return None
    path = match.group(1) if match.group(1) is not None else match.group(2)
    key = match.group(3) if match.group(3) is not None else match.group(4)
    return path, key, match.group("tol") or ""


def split_comment(line: str) -> tuple[str, str]:
    """`(code, comment)` at the first `#` that is not inside a quoted string --
    a source() key may legitimately contain one. Every other line has no
    quotes, so this is `line.partition("#")` for them."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i], line[i + 1:]
    return line, ""


# `P | mW = V * I` -- the unit in the one place it does not go. Caught to name
# the fix rather than the generic "expected an assignment".
LEADING_PIPE_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|\s*[^|=]+?\s*=\s*(.+?)\s*$"
)


def rewrite_line(line: str) -> str | None:
    """The pipe-form spelling of one old-spelling calc line, or None when the
    line is not an old-spelling assignment. Indentation and any trailing
    comment (and the whitespace before it) are preserved exactly.

    Alignment: an author who padded the name before the colon, or padded
    before the equals sign, was aligning the block's `=` in a column -- and
    a calc block is prose-adjacent text a person reads. So on a padded line
    the `=` stays in exactly the column it was in (the name is padded to
    reach it, the text after the `=` keeps its own spacing), and the
    `| unit` simply follows the expression. An unpadded line stays compact:
    `name = expression | unit`.

    This is the one spelling transformation: the build error for a retired
    line quotes its suggestion from here, and `refdes calc-rewrite` applies
    it."""
    code, hash_sign, comment = line.partition("#")
    stripped = code.strip()
    if not stripped or "|" in stripped:
        # A `|` on the code part means the line already uses the pipe form
        # (or spells both, which is a build error the run never reaches).
        return None
    match = ANNOTATED_RE.match(stripped)
    if not match:
        return None
    name, unit, expression = match.groups()
    indent = line[: len(line) - len(line.lstrip())]
    tol_parts = TOLERANCE_SPLIT.split(unit, maxsplit=1)
    if len(tol_parts) == 2:
        # `P : W ± 10% = expr` -- the tolerance moves to the right-hand side
        # in the same step (it was never a legal part of the unit).
        new = f"{name} = {expression} ± {tol_parts[1].strip()} | {tol_parts[0].strip()}"
        new = indent + new.lstrip()
        if hash_sign:
            new += f"{code[len(code.rstrip()):]}{hash_sign}{comment}"
        return new
    gap = code[len(code.rstrip()):] if hash_sign else ""
    eq_idx = code.find("=")
    pad_before_eq = len(code[:eq_idx]) - len(code[:eq_idx].rstrip())
    pad_before_colon = code.find(":") - (len(indent) + len(name))
    if pad_before_eq >= 2 or pad_before_colon >= 2:
        # Aligned line: keep the `=` in its column, keep everything from the
        # `=` on (spacing included) exactly as written, append the unit.
        tail = code[eq_idx + 1:].rstrip()
        new = f"{(indent + name).ljust(eq_idx)}={tail} | {unit}"
    else:
        new = f"{indent}{name} = {expression} | {unit}"
    if hash_sign:
        new += f"{gap}{hash_sign}{comment}"
    return new


@dataclass
class CalcOutcome:
    name: str
    expression: str
    comment: str
    value: Value | None
    error: str | None
    annotation: str = ""
    warning: str | None = None
    # Which spelling declared the unit: "|" for `name = expr | unit`, ":" for
    # the retired `name : unit = expr`. Renderers show the author's own marker.
    unit_style: str = ":"
    # Absolute 1-indexed source line, or None when the caller didn't supply
    # evaluate_block a start_line to compute one from.
    line: int | None = None
    # The error is about the retired `name : unit = expr` spelling itself, so
    # a sealed append-only entry -- which cannot be edited without resealing
    # -- downgrades to a warning instead of failing the build.
    retired: bool = False
    # Set on a cross-item reference line (`V_in = DEC-PWR-001.V_in`): the
    # reference text exactly as authored. The value itself is resolved by the
    # caller -- evaluation order across items is a build-level concern, so
    # `evaluate_block` hands the reference to the resolver installed in the
    # environment under `RESOLVER_KEY` (a callable taking the reference text
    # and returning a `Value`, or raising with the message to report).
    reference: str = ""
    # Set on a `source("path", "key")` line: the path and key exactly as
    # authored. The value comes from the resolver installed under
    # SOURCE_RESOLVER_KEY -- the citation lockfile, never the file itself.
    source: tuple[str, str] | None = None


# Key under which the caller installs a cross-item reference resolver in the
# environment `evaluate_block` threads through a project's calc blocks. It
# starts with `__` so it can never collide with an authored calc name (names
# are `[A-Za-z_][A-Za-z0-9_]*` and the lexer never produces `__`-prefixed
# lookups).
RESOLVER_KEY = "__refdes_calc_resolver__"
# Same idea for `source()` lines: a callable taking (path, key) exactly as
# authored and returning the locked decimal text, or raising CalcError with
# the message to report. Absent, a source() line is an error rather than a
# guess -- evaluation never opens the cited file (docs/design/calc-sources.md §5).
SOURCE_RESOLVER_KEY = "__refdes_calc_source_resolver__"


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
            line, comment = split_comment(line)
            comment = comment.strip()
            line = line.rstrip()

        leading = LEADING_PIPE_RE.match(line)
        if leading:
            outcomes.append(
                CalcOutcome(leading.group(1), leading.group(2), comment, None,
                            f"the unit goes after the expression: "
                            f"{leading.group(1)} = {leading.group(2)} | unit — "
                            "`name | unit = expression` is not the syntax",
                            line=line_number)
            )
            continue

        # Split a trailing `| unit` off the line before the assignment
        # grammars see it, so both spellings -- and the both-at-once error --
        # fall out of the same matching below.
        full_line = line
        unit_after = ""
        pipe_match = PIPE_UNIT_RE.match(line)
        if pipe_match:
            unit_after = pipe_match.group("unit")
            line = pipe_match.group("lhs").rstrip()

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
                        "a tolerance belongs on the right-hand side, and the "
                        "': unit =' spelling was retired — "
                        f"write `{name} = {expression} ± {tol_part} | {unit_part}`; "
                        "run 'refdes calc-rewrite' to fix a whole project",
                        annotation, retired=True, line=line_number,
                    )
                )
                continue
        else:
            match = ASSIGN_RE.match(line)
            if not match:
                outcomes.append(
                    CalcOutcome("", full_line.strip(), comment, None,
                                "expected an assignment of the form 'name = expression'",
                                line=line_number)
                )
                continue
            name, expression = match.group(1), match.group(2)

        if annotation and unit_after:
            outcomes.append(
                CalcOutcome(
                    name, expression, comment, None,
                    f"{name} declares a unit twice -- ': {annotation}' before "
                    f"the = and '| {unit_after}' after the expression; keep one",
                    annotation, line=line_number,
                )
            )
            continue

        if annotation:
            # Only the retired colon spelling can still carry an annotation
            # here: the pipe form sets its own below. The line still
            # evaluates -- a sealed append-only entry downgrades to a
            # warning and must still render its numbers, and calc-rewrite's
            # value guard compares before against after -- but the outcome
            # carries an error, so any unsealed use fails the build. The
            # suggestion comes from rewrite_line, the same function
            # `refdes calc-rewrite` applies, so the transformation lives once.
            suggested = rewrite_line(line)
            fix = f" -- write `{suggested.strip()}`" if suggested else ""
            retired_msg = (
                f"the 'name : unit = expression' spelling was retired{fix}; "
                "run 'refdes calc-rewrite' to fix a whole project"
            )
            warning = check_ambiguity(expression, names)
            try:
                value = evaluate_assignment(expression, env)
                value = convert_value(value, annotation)
            except Exception as exc:  # noqa: BLE001 -- pint and math surface a variety of types
                outcomes.append(
                    CalcOutcome(name, expression, comment, None,
                                f"{retired_msg} (and: {exc})", annotation,
                                warning, retired=True, line=line_number)
                )
                continue
            env[name] = value
            origins[name] = line_number
            outcomes.append(
                CalcOutcome(name, expression, comment, value, retired_msg,
                            annotation, warning, retired=True, line=line_number)
            )
            continue

        unit_style = ":"
        if unit_after:
            # The finding-9 guard, mirrored for the new spelling: a tolerance
            # parked after the unit gets a message naming the fix.
            tol_parts = TOLERANCE_SPLIT.split(unit_after, maxsplit=1)
            if len(tol_parts) == 2:
                outcomes.append(
                    CalcOutcome(
                        name, expression, comment, None,
                        "a tolerance belongs on the right-hand side — "
                        f"{name} = {expression} ± {tol_parts[1].strip()} "
                        f"| {tol_parts[0].strip()}",
                        annotation=unit_after, unit_style="|", line=line_number,
                    )
                )
                continue
            annotation = unit_after
            unit_style = "|"

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
                    annotation, unit_style=unit_style, line=line_number,
                )
            )
            continue

        if SOURCE_START_RE.match(expression.strip()):
            outcomes.append(_evaluate_source_line(
                name, expression, comment, annotation, unit_style, line_number, env,
            ))
            if outcomes[-1].value is not None:
                env[name] = outcomes[-1].value
                origins[name] = line_number
            continue

        qualified = BLOCK_QUALIFIED_REF_RE.match(expression.strip())
        if qualified:
            ref = expression.strip()
            parts = ref.split(".")
            plain = f"{parts[0]}.{parts[-1]}"
            dropped = "".join(f".{part}" for part in parts[1:-1])
            outcomes.append(
                CalcOutcome(
                    name, expression, comment, None,
                    f"cross-item reference {ref!r} names a block -- a calc "
                    f"value is named by ITEM.NAME, and {plain} already names "
                    f"it uniquely. Drop '{dropped}'.",
                    annotation, unit_style=unit_style, line=line_number,
                )
            )
            continue

        ref_match = CROSS_REF_RE.match(expression.strip())
        if ref_match:
            reference = expression.strip()
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
                        annotation, unit_style=unit_style, line=line_number,
                        reference=reference,
                    )
                )
                continue
            resolver = env.get(RESOLVER_KEY)
            if resolver is None:
                outcomes.append(
                    CalcOutcome(name, expression, comment, None,
                                f"cross-item calc reference {reference!r} is not "
                                "supported in this evaluation context",
                                annotation, unit_style=unit_style,
                                line=line_number, reference=reference)
                )
                continue
            try:
                value = resolver(reference)
                if annotation:
                    value = convert_value(value, annotation)
            except CalcError as exc:
                outcomes.append(
                    CalcOutcome(name, expression, comment, None, str(exc),
                                annotation, unit_style=unit_style,
                                line=line_number, reference=reference)
                )
                continue
            except Exception as exc:  # noqa: BLE001 -- resolver may surface pint errors too
                outcomes.append(
                    CalcOutcome(name, expression, comment, None, str(exc),
                                annotation, unit_style=unit_style,
                                line=line_number, reference=reference)
                )
                continue
            env[name] = value
            origins[name] = line_number
            outcomes.append(
                CalcOutcome(name, expression, comment, value, None, annotation,
                            None, unit_style=unit_style, line=line_number,
                            reference=reference)
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
                            warning, unit_style=unit_style, line=line_number)
            )
            continue
        except Exception as exc:  # pint and math surface a variety of types
            outcomes.append(
                CalcOutcome(name, expression, comment, None, str(exc), annotation,
                            warning, unit_style=unit_style, line=line_number)
            )
            continue

        env[name] = value
        origins[name] = line_number
        outcomes.append(
            CalcOutcome(name, expression, comment, value, None, annotation,
                        warning, unit_style=unit_style, line=line_number)
        )
    return outcomes


def _evaluate_source_line(
    name: str, expression: str, comment: str, annotation: str, unit_style: str,
    line_number: int | None, env: dict,
) -> CalcOutcome:
    """One `name = source("path", "key") [± tol] | unit` assignment.

    The unit assertion is mandatory (§6): the reader supplies no unit, so a
    bare `1850` from a milliwatt spreadsheet would otherwise flow into the
    arithmetic as an unlabelled number. `| 1` states "dimensionless" out loud.
    """
    parsed = parse_source_call(expression)

    def fail(message: str, source=None) -> CalcOutcome:
        return CalcOutcome(name, expression, comment, None, message, annotation,
                           unit_style=unit_style, line=line_number, source=source)

    if parsed is None:
        return fail(
            "malformed source() call -- it takes exactly two string literals and "
            'must be the whole right-hand side: source("cited/file.csv", "key") | unit'
        )
    path, key, tol = parsed
    if not annotation:
        return fail(
            f"source({path!r}, {key!r}) needs an explicit unit -- the file supplies "
            f"a bare number, so declare what it is: `{name} = {expression.strip()} "
            "| unit` (`| 1` for a dimensionless value)",
            (path, key),
        )
    resolver = env.get(SOURCE_RESOLVER_KEY)
    if resolver is None:
        return fail("source() is not supported in this evaluation context", (path, key))
    try:
        text = resolver(path, key)
        # The declared unit LABELS the file's bare number (section 6): 1850 in
        # a milliwatt sheet under `| W` is 1850 W, on screen, not a converted
        # 1.85 W -- so this is not convert_value's dimensionality assertion.
        unit = annotation.strip()
        unit = "" if unit == "1" else _to_pint_units(unit)
        try:
            value = quantity(text, unit)
        except CalcError:
            raise CalcError(f"unknown unit {annotation!r} in declaration") from None
        if tol:
            value = apply_tolerance(value, tol, env)
    except Exception as exc:  # noqa: BLE001 -- resolver/pint/math surface many types
        return fail(str(exc), (path, key))
    return CalcOutcome(name, expression, comment, value, None, annotation,
                       unit_style=unit_style, line=line_number, source=(path, key))


def source_calls_in_block(block: str) -> list[tuple[int, str, str, str]]:
    """Every well-formed `name = source("path", "key")` line in one calc block,
    as `(0-indexed line offset, name, path, key)` -- what `refdes fetch` walks
    to learn which keys to extract, without evaluating anything. A malformed
    call is not listed here; evaluation reports it at the line."""
    out = []
    for offset, raw_line in enumerate(block.splitlines()):
        line = split_comment(raw_line)[0].rstrip()
        pipe = PIPE_UNIT_RE.match(line)
        if pipe:
            line = pipe.group("lhs").rstrip()
        match = ASSIGN_RE.match(line)
        if not match:
            continue
        parsed = parse_source_call(match.group(2)) if SOURCE_START_RE.match(match.group(2).strip()) else None
        if parsed:
            out.append((offset, match.group(1), parsed[0], parsed[1]))
    return out


def extract_blocks(body: str) -> list[str]:
    return [block for block, _, _ in extract_blocks_with_lines(body)]


def extract_blocks_with_lines(body: str) -> list[tuple[str, int, str | None]]:
    """Like extract_blocks, but each block paired with its 0-indexed line
    offset within `body` -- the piece a caller needs to turn a line number
    inside the block into an absolute source line (add Item.body_line) -- and
    its fence name (`id="..."`, docs/design/named-calc-blocks.md §3) or None.
    A fence whose info string fails the grammar reports None here; the build
    surfaces the error via `fence_errors`, at the fence line."""
    out = []
    for match in CALC_BLOCK_RE.finditer(body):
        block = match.group(1)
        offset = body.count("\n", 0, match.start(1))
        try:
            block_id = parse_fence_attrs(_fence_info(match))
        except CalcFenceError:
            block_id = None
        out.append((block, offset, block_id))
    return out
