"""Cross-platform lint: mechanically visible Windows hazards and
post-3.11 APIs in tests, src and tools.

Two PRs went green on Linux and red on Windows CI the same month: a test
wrote multi-line fixtures with text-mode ``write_text`` (Windows rewrites
``\\n`` to ``\\r\\n``) and asserted on raw ``'\\n'`` byte reads; a
diagnostic path built with ``os.path.relpath`` was asserted with ``'/'``
separators. Separately, CI's floor is Python 3.11 while developers run
3.13 locally, so a ``Path.read_text(newline=...)`` (3.13-only) test passed
locally and died on CI twice in one week. These rules scan the tree for
that class of code. Hits on the
day the rules landed are frozen in ``crossplatform_lint_baseline.json``
(``rule -> file -> count``); the test fails if a count rises, a new file
appears, or a count falls below baseline. Lower the baseline in the same
PR as any improvement with ``python tests/crossplatform_lint_baseline_update.py``.

Rules (see the ``check_*`` functions for the exact shapes):

R1 (tests/**/*.py)
    A text-mode write of a multi-line fixture in a module that also reads
    raw bytes (``read_bytes()``/binary ``open``): ``write_text`` without a
    ``newline=`` keyword whose content argument is statically multi-line
    (string constant, f-string, ``'\\n'.join``, concatenation, a name bound
    to one of those, a loop target, a parameter, an unresolvable name), or
    a text-mode write-mode ``open`` with no ``newline=`` whose same-scope
    ``.write``/``.writelines`` argument is statically multi-line. The
    byte-read gate is what targets the real defect: a module that asserts
    on exact bytes.

R2 (src/refdes/**/*.py)
    ``os.path.relpath(...)`` whose result is not normalized to forward
    slashes in the same expression: accepted normalizations are
    ``.replace(os.sep, "/")``, ``.replace("\\\\", "/")`` and an enclosing
    ``.as_posix()`` call (``Path(os.path.relpath(...)).as_posix()``).
    Normalizing in a later statement is a hit (the six it froze were
    all normalised into the expression in the PR that lowered the
    baseline to zero); ``parse._relpath`` call sites are clean by
    construction since they contain no ``relpath`` call.

Python 3.11 floor (pyproject.toml's ``requires-python``): CI's ubuntu and
windows jobs run 3.11, developers and workers run 3.13 locally, so an
API newer than the floor passes locally and goes red on CI. R3/R4/R5
(over ``src/refdes``, ``tests`` and ``tools``) catch that class:

R3 (src/refdes/**/*.py, tests/**/*.py, tools/**/*.py)
    ``.read_text(..., newline=...)``: ``Path.read_text`` gained the
    ``newline=`` keyword in 3.13, so a test that reads with it is a
    ``TypeError`` on 3.11. (``write_text(newline=)`` is 3.10+, and
    ``open(newline=)`` has always worked -- both stay clean.)

R4 (same trees)
    Attribute/import use of stdlib APIs that are unambiguous by name and
    newer than 3.11: ``itertools.batched``, ``math.sumprod``,
    ``typing.override``, ``warnings.deprecated``, ``copy.replace``,
    ``os.path.isjunction``/``Path.is_junction``, ``Path.walk`` (only
    when the receiver is plausibly a Path, so ``os.walk``/``ast.walk``
    stay clean), and ``shutil.rmtree(onexc=)`` (3.11 spells it
    ``onerror=``). ``tomllib`` is 3.11 and stays clean.

R5 (same trees)
    Source the 3.11 parser rejects: ``ast.parse(source, feature_version=(3, 11))``
    over every scanned file, which on 3.12+ interpreters catches PEP 695
    (``type X = ...``, ``def f[T]()...``, ``class C[T]:``). See the
    ``check_syntax_311_floor`` docstring for what feature_version does
    and does not enforce (it does not re-tokenize f-strings with 3.11
    rules -- the 3.11 CI job's own parse is what rejects those).

Known limits, by design: R1 does not follow content through call
expressions (``write_text(json.dumps(x))`` is not flagged) and the
byte-read gate is module-wide; R2 accepts any enclosing ``as_posix()``;
R4 matches the qualified name (``import itertools as it`` aliasing
``it.batched`` is not followed), and a bare imported name (``from typing
import override`` + ``@override``) is caught at the import, not the use;
R5 is a parser check only -- stdlib APIs need R3/R4, and constructs
that parse on 3.11 are by definition not syntax violations.
"""

from __future__ import annotations

import ast
import json
import sys
import time
from collections import namedtuple
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).with_name("crossplatform_lint_baseline.json")
UPDATE_COMMAND = "python tests/crossplatform_lint_baseline_update.py"

R1 = "R1-multiline-text-write"
R2 = "R2-relpath-not-normalized"
R3 = "R3-read-text-newline-kwarg"
R4 = "R4-post-311-stdlib-api"
R5 = "R5-syntax-newer-than-311"

R1_SCOPE = "tests"
R2_SCOPE = "src/refdes"
R345_SCOPES = ("src/refdes", "tests", "tools")
SCANNED_SCOPES = ("src/refdes", "tests", "tools")

R1_FIX = (
    "write the fixture as bytes (write_bytes) or pass newline='' to "
    "write_text/open so the bytes are the same on every platform"
)
R2_FIX = (
    "normalize in the same expression: .replace(os.sep, '/') / "
    ".replace('\\\\', '/') / Path(...).as_posix()"
)
R3_FIX = (
    "use Path.open(newline='').read() or read_bytes().decode() -- "
    "Path.read_text gained newline= in 3.13, the floor is 3.11"
)
R4_FIX_SUFFIX = "is newer than the 3.11 floor (pyproject requires-python)"
R5_FIX = (
    "rewrite for the 3.11 floor: PEP 695 (type X = ..., def f[T]()) and "
    "PEP 701 f-strings are 3.12+"
)

R4_CHAINS = {
    ("itertools", "batched"): ("itertools.batched", "3.12", "chunk with a manual loop (e.g. over itertools.islice)"),
    ("math", "sumprod"): ("math.sumprod", "3.12", "use sum(a * b for a, b in zip(xs, ys))"),
    ("typing", "override"): (
        "typing.override",
        "3.12",
        "drop the decorator -- @override is a type-checker hint only",
    ),
    ("warnings", "deprecated"): (
        "warnings.deprecated",
        "3.13",
        "use typing_extensions.deprecated, which backports it",
    ),
    ("copy", "replace"): (
        "copy.replace",
        "3.13",
        "copy.copy()/copy.deepcopy() the object, then assign the changed fields",
    ),
    ("os", "path", "isjunction"): (
        "os.path.isjunction",
        "3.12",
        "inspect os.lstat() st_mode, or drop the junction check",
    ),
    ("Path", "walk"): ("Path.walk", "3.12", "use os.walk(...) on 3.11"),
}

R4_FROM_IMPORTS = {
    ("itertools", "batched"): R4_CHAINS[("itertools", "batched")],
    ("math", "sumprod"): R4_CHAINS[("math", "sumprod")],
    ("typing", "override"): R4_CHAINS[("typing", "override")],
    ("warnings", "deprecated"): R4_CHAINS[("warnings", "deprecated")],
    ("copy", "replace"): R4_CHAINS[("copy", "replace")],
    ("os.path", "isjunction"): R4_CHAINS[("os", "path", "isjunction")],
}

R4_PATH_ATTRS = {
    "is_junction": ("Path.is_junction", "3.12", "inspect os.lstat() st_mode, or drop the junction check"),
    "full_match": ("Path.full_match", "3.13", "use fnmatch.fnmatch(str(path), pattern)"),
}

PATH_CALL_NAMES = {"Path", "PurePath", "PosixPath", "WindowsPath"}
PATH_METHOD_NAMES = {
    "parent",
    "parents",
    "anchor",
    "name",
    "suffix",
    "stem",
    "parts",
    "joinpath",
    "with_name",
    "with_suffix",
    "with_stem",
    "with_parents",
    "absolute",
    "resolve",
    "home",
    "cwd",
}

Finding = namedtuple("Finding", "rule path line message fix")

FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _string_is_multiline(value):
    return isinstance(value, str) and "\n" in value


def _has_literal_newline(node):
    """True if a string constant, f-string, concatenation, or join of
    constants carries a literal newline."""
    if isinstance(node, ast.Constant):
        return _string_is_multiline(node.value)
    if isinstance(node, ast.JoinedStr):
        return any(_has_literal_newline(value) for value in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _has_literal_newline(node.left) or _has_literal_newline(node.right)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Constant)
        and _string_is_multiline(node.func.value.value)
    )


def _has_keyword(call, name):
    return any(keyword.arg == name for keyword in call.keywords)


def _open_mode(call):
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    return mode if isinstance(mode, str) else None


def _is_open_call(node):
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return True
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "open"
        and isinstance(func.value, ast.Name)
        and func.value.id == "io"
    )


def _is_text_write_open(call):
    mode = _open_mode(call)
    return mode is not None and any(char in mode for char in "wax") and "b" not in mode


def _reads_raw_bytes(tree):
    """True if the module reads file contents as exact bytes: the defect
    needs assertions on raw bytes, which text-mode round-trips hide."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "read_bytes":
            return True
        if _is_open_call(node):
            mode = _open_mode(node)
            if mode is not None and "b" in mode:
                return True
    return False


def _module_constants(tree):
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                    constants[target.id] = _string_is_multiline(node.value)
    return constants


def _static_multiline(value, scope, module_constants):
    if _has_literal_newline(value):
        return True
    if isinstance(value, ast.Name):
        if value.id in scope:
            return scope[value.id]
        return module_constants.get(value.id)
    if isinstance(value, (ast.Constant, ast.JoinedStr, ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return False
    return None


def _bind_function_scope(fn, module_constants):
    """name -> True (statically multi-line), False (provably not) or None
    (unknown: parameter, loop target, dynamic value) for one function."""
    scope = {}
    for arg in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs:
        scope.setdefault(arg.arg, None)
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    scope[target.id] = _static_multiline(node.value, scope, module_constants)
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None) or (
            isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name)
        ):
            scope[node.target.id] = _static_multiline(node.value, scope, module_constants)
        elif isinstance(node, ast.For):
            for name in _for_target_names(node.target):
                scope.setdefault(name, None)
    return scope


def _for_target_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names = []
        for element in target.elts:
            names.extend(_for_target_names(element))
        return names
    return []


def _content_is_multiline(node, scope, module_constants):
    if _has_literal_newline(node):
        return True
    if isinstance(node, ast.Name):
        if node.id in scope:
            return scope[node.id] is not False
        return node.id not in module_constants or module_constants[node.id] is not False
    return False


def _write_body_is_multiline(scope_root, open_call):
    """True if a .write/.writelines inside the same function (or module
    body) writes a statically multi-line constant."""
    for node in ast.walk(scope_root):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("write", "writelines")
            and node is not open_call
            and node.args
            and _has_literal_newline(node.args[0])
        ):
            return True
    return False


def _set_parents(tree):
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node
    tree._parent = None


def _enclosing(node, types):
    while node is not None:
        if isinstance(node, types):
            return node
        node = getattr(node, "_parent", None)
    return None


def check_multiline_text_writes(relpath, tree):
    """R1: multi-line text-mode writes in test modules that read raw bytes.

    Flags ``write_text`` calls (and text-mode write-mode ``open`` with a
    statically multi-line ``.write``) that pass no ``newline=`` keyword, in
    modules containing ``read_bytes()``/binary ``open`` -- a module
    asserting on exact bytes, where a text-mode write turns LF fixtures
    into CRLF on Windows and the byte assertions end up testing the writer.
    """
    if not _reads_raw_bytes(tree):
        return []
    _set_parents(tree)
    module_constants = _module_constants(tree)
    scopes = {}
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = _enclosing(node, FUNCTION_TYPES)
        key = id(fn)
        if key not in scopes:
            scopes[key] = _bind_function_scope(fn, module_constants) if fn is not None else {}
        scope = scopes[key]
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_text"
            and node.args
            and not _has_keyword(node, "newline")
        ):
            if _content_is_multiline(node.args[0], scope, module_constants):
                findings.append(_finding(R1, relpath, node, "multi-line fixture written in text mode", R1_FIX))
        elif (
            _is_open_call(node)
            and _is_text_write_open(node)
            and not _has_keyword(node, "newline")
            and _write_body_is_multiline(fn if fn is not None else tree, node)
        ):
            findings.append(_finding(R1, relpath, node, "multi-line fixture written via text-mode open()", R1_FIX))
    return findings


def _is_os_path_relpath(node):
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "relpath"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "path"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
    )


def _normalized_in_expression(node):
    """True if an enclosing call normalizes separators: an ``as_posix()``
    call anywhere outside (including ``Path(relpath(...)).as_posix()``), or
    a ``.replace(os.sep | '\\\\', '/')`` directly around the call."""
    current = node
    child = node
    while True:
        parent = getattr(current, "_parent", None)
        if isinstance(parent, ast.Attribute) and parent.value is current:
            current = parent
            continue
        if not isinstance(parent, ast.Call) or parent.func is child:
            return False
        if isinstance(parent.func, ast.Attribute):
            attr = parent.func.attr
            if attr == "as_posix":
                return True
            if attr == "replace" and len(parent.args) == 2:
                sep, to = parent.args
                to_slash = isinstance(to, ast.Constant) and to.value == "/"
                sep_is_backslash = isinstance(sep, ast.Constant) and sep.value in {"\\", "\\\\"}
                sep_is_ossep = (
                    isinstance(sep, ast.Attribute)
                    and sep.attr == "sep"
                    and isinstance(sep.value, ast.Name)
                    and sep.value.id == "os"
                )
                if to_slash and (sep_is_backslash or sep_is_ossep):
                    return True
        child = current
        current = parent


def check_relpath_not_normalized(relpath, tree):
    """R2: ``os.path.relpath`` results reaching strings unnormalized.

    Flags every ``os.path.relpath(...)`` in ``src/refdes`` that is not
    normalized to forward slashes in the same expression
    (``.replace(os.sep, '/')``, ``.replace('\\\\', '/')``, or an enclosing
    ``.as_posix()``); on Windows the bare result carries backslashes, and
    diagnostics built from it read wrong in logs, JSON, and test
    assertions.
    """
    _set_parents(tree)
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_os_path_relpath(node) and not _normalized_in_expression(node):
            findings.append(_finding(R2, relpath, node, "os.path.relpath result not normalized to '/'", R2_FIX))
    return findings


def check_read_text_newline(relpath, tree):
    """R3: ``.read_text(newline=...)``, a Python 3.13 keyword.

    Flags every ``read_text`` call passed ``newline=``. ``Path.read_text``
    gained the keyword in 3.13, so the call is a ``TypeError`` on the 3.11
    floor. The 3.10+ spellings stay clean: ``write_text(newline=)`` and
    ``open(newline=)`` are exactly what the fix suggests.
    """
    findings = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_text"
            and _has_keyword(node, "newline")
        ):
            findings.append(
                _finding(R3, relpath, node, "Path.read_text(newline=...) is Python 3.13+ (floor is 3.11)", R3_FIX)
            )
    return findings


def _attr_chain(node):
    """Names of a plain dotted attribute chain, e.g. ``os.path.isjunction``
    -> ``('os', 'path', 'isjunction')``; () if the base is not a Name."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return ()


def _is_pathish(node, path_names):
    """True if the receiver of a ``.walk()`` call is plausibly a Path: a
    name assigned from a Path expression, a ``/`` join (the path-join
    idiom, left non-constant), a Path() call, a Path method/property
    chain, or a subscript of one. Deliberately conservative --
    ``os.walk``/``ast.walk``/unknown attribute receivers stay clean."""
    if isinstance(node, ast.Name):
        return node.id in path_names
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return not isinstance(node.left, ast.Constant)
    if isinstance(node, ast.Attribute):
        return node.attr in PATH_METHOD_NAMES and _is_pathish(node.value, path_names)
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in PATH_CALL_NAMES:
            return True
        return (
            isinstance(func, ast.Attribute)
            and func.attr in PATH_METHOD_NAMES
            and _is_pathish(func.value, path_names)
        )
    if isinstance(node, ast.Subscript):
        return _is_pathish(node.value, path_names)
    return False


def _pathish_names(tree):
    names = set()
    assigns = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigns.append((target.id, node.value))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            assigns.append((node.target.id, node.value))
    for _ in range(3):
        added = False
        for name, value in assigns:
            if name not in names and _is_pathish(value, names):
                names.add(name)
                added = True
        if not added:
            break
    return names


def _is_shutil_rmtree(node, bare_rmtree_imported):
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "rmtree":
        return isinstance(func.value, ast.Name) and func.value.id == "shutil"
    return bare_rmtree_imported and isinstance(func, ast.Name) and func.id == "rmtree"


def check_post_311_apis(relpath, tree):
    """R4: stdlib APIs newer than the 3.11 floor, unambiguous by name.

    Flags qualified attribute uses (``itertools.batched``, ``math.sumprod``,
    ``typing.override``, ``warnings.deprecated``, ``copy.replace``,
    ``os.path.isjunction``, ``Path.walk``), the matching
    ``from <module> import <name>`` lines (a bare ``@override`` after
    ``from typing import override`` is caught at the import), the
    Path-only attribute names ``is_junction``/``full_match`` on any
    receiver, ``.walk()`` calls whose receiver is plausibly a Path, and
    ``shutil.rmtree(onexc=)`` (3.11's spelling is ``onerror=``). Aliased
    imports (``import itertools as it``) are not followed, by design.
    """
    findings = []
    path_names = None
    bare_rmtree_imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                if node.module == "shutil" and alias.name == "rmtree":
                    bare_rmtree_imported = True
                spec = R4_FROM_IMPORTS.get((node.module, alias.name))
                if spec is not None:
                    findings.append(_r4_finding(relpath, node, spec))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            spec = R4_CHAINS.get(_attr_chain(node))
            if spec is None and node.attr in R4_PATH_ATTRS:
                spec = R4_PATH_ATTRS[node.attr]
            if spec is not None:
                findings.append(_r4_finding(relpath, node, spec))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "walk":
                if path_names is None:
                    path_names = _pathish_names(tree)
                if _is_pathish(node.func.value, path_names):
                    findings.append(_r4_finding(relpath, node, ("Path.walk", "3.12", "use os.walk(...) on 3.11")))
            elif _has_keyword(node, "onexc") and _is_shutil_rmtree(node, bare_rmtree_imported):
                findings.append(
                    _r4_finding(
                        relpath,
                        node,
                        ("shutil.rmtree(onexc=...)", "3.12", "use the 3.11 spelling, onerror="),
                    )
                )
    return findings


def _r4_finding(relpath, node, spec):
    label, since, fix = spec
    return _finding(R4, relpath, node, f"{label} is Python {since}+ -- {R4_FIX_SUFFIX}", fix)


def check_syntax_311_floor(relpath, tree):
    """R5: source the Python 3.11 parser rejects.

    ``ast.parse(source, feature_version=(3, 11))`` re-parses the file as
    the floor interpreter would see it. feature_version=(3, 11) rejects
    PEP 695: the ``type X = ...`` statement and ``[T]`` type-parameter
    lists on functions and classes (verified on 3.13: SyntaxError "only
    supported in Python 3.12 and greater"). What it does NOT catch: the
    PEP 701 f-string changes (nested same quotes, newlines inside
    f-strings) -- the f-string tokenizer follows the *running*
    interpreter, not feature_version -- so those are only caught where
    they are caught today, by the 3.11 CI job's own parse of the file;
    nor anything the 3.11 parser also accepts, i.e. runtime stdlib
    additions (new functions, new keywords like ``read_text(newline=)``
    parse fine on 3.11 -- that is R3/R4's job). In short: on 3.12+ this
    catches PEP 695 syntax; the floor's real teeth are CI's 3.11
    interpreter parsing every file.
    """
    source = getattr(tree, "_source", None)
    if source is None:
        return []
    try:
        ast.parse(source, feature_version=(3, 11))
    except SyntaxError as exc:
        snippet = (exc.text or "").strip()
        message = f"syntax newer than Python 3.11: {exc.msg}"
        if snippet:
            message = f"{message} ({snippet})"
        return [Finding(R5, relpath, exc.lineno or 1, message, R5_FIX)]
    return []


def _finding(rule, relpath, node, message, fix):
    return Finding(rule, relpath, node.lineno, message, fix)


RULE_CHECKS = {
    R1: check_multiline_text_writes,
    R2: check_relpath_not_normalized,
    R3: check_read_text_newline,
    R4: check_post_311_apis,
    R5: check_syntax_311_floor,
}
RULE_SCOPES = {
    R1: (R1_SCOPE,),
    R2: (R2_SCOPE,),
    R3: R345_SCOPES,
    R4: R345_SCOPES,
    R5: R345_SCOPES,
}


def rules_for(relpath):
    """Every rule whose scope contains `relpath` (a file can carry several)."""
    posix = Path(relpath).as_posix()
    if not posix.endswith(".py"):
        return []
    return [
        rule
        for rule, scopes in RULE_SCOPES.items()
        if any(posix.startswith(scope + "/") for scope in scopes)
    ]


def scan_source(source, relpath):
    """Run every rule that applies to `relpath` over a source string."""
    rules = rules_for(relpath)
    if not rules:
        return []
    tree = ast.parse(source)
    tree._source = source
    findings = []
    for rule in rules:
        findings.extend(RULE_CHECKS[rule](relpath, tree))
    return findings


def iter_scanned_files(root):
    for scope in SCANNED_SCOPES:
        base = root / scope
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" not in path.parts:
                relpath = path.relative_to(root).as_posix()
                yield tuple(rules_for(relpath)), relpath, path


def scan_repo(root=REPO_ROOT):
    findings = []
    for rules, relpath, path in iter_scanned_files(root):
        try:
            source = path.read_bytes()
            tree = ast.parse(source)
        except SyntaxError as exc:
            # a file the running interpreter (3.11 on CI) cannot parse is
            # itself the floor violation: report it, do not crash the scan
            snippet = (exc.text or "").strip()
            message = f"syntax newer than Python 3.11: {exc.msg}"
            if snippet:
                message = f"{message} ({snippet})"
            findings.append(Finding(R5, relpath, exc.lineno or 1, message, R5_FIX))
            continue
        tree._source = source
        for rule in rules:
            findings.extend(RULE_CHECKS[rule](relpath, tree))
    return findings


def counts_by_file(findings):
    counts = {}
    for finding in findings:
        per_file = counts.setdefault(finding.rule, {})
        per_file[finding.path] = per_file.get(finding.path, 0) + 1
    return counts


def load_baseline(path=BASELINE_PATH):
    return json.loads(path.read_bytes().decode("utf-8"))


def baseline_dict(findings):
    return {rule: dict(sorted(files.items())) for rule, files in sorted(counts_by_file(findings).items())}


def compare(current, baseline):
    problems = []
    for rule in sorted(set(current) | set(baseline)):
        cur = current.get(rule, {})
        base = baseline.get(rule, {})
        for path in sorted(set(cur) | set(base)):
            cur_count, base_count = cur.get(path, 0), base.get(path, 0)
            if cur_count > base_count:
                origin = "new file" if path not in base else f"baseline {base_count}"
                problems.append(f"{rule} {path}: {cur_count} hits, {origin} -- count rose")
            elif cur_count < base_count:
                problems.append(
                    f"{rule} {path}: {cur_count} hits, baseline {base_count} "
                    "(good news: lower the baseline in the same PR)"
                )
    return problems


def format_findings(findings):
    return [
        f"  {f.rule} {f.path}:{f.line}: {f.message} -- fix: {f.fix}"
        for f in sorted(findings, key=lambda f: (f.rule, f.path, f.line))
    ]


def build_failure_report(findings, current, baseline):
    """The failing message: every hit in a regressed file (file:line + the
    fix), the per-file count deltas, and the regenerate command."""
    regressions = [
        finding
        for finding in findings
        if current[finding.rule][finding.path] > baseline.get(finding.rule, {}).get(finding.path, 0)
    ]
    return "\n".join(
        [
            "cross-platform lint ratchet broken; hits in files at/over baseline:",
            *format_findings(regressions),
            "",
            *compare(current, baseline),
            "",
            (
                "counts that FELL are also failures (the baseline only ratchets down): "
                f"run `{UPDATE_COMMAND}` and commit the lowered baseline in the same PR"
            ),
        ]
    )


def test_crossplatform_lint_ratchet():
    baseline = load_baseline()
    findings = scan_repo()
    current = counts_by_file(findings)
    problems = compare(current, baseline)
    if problems:
        raise AssertionError(build_failure_report(findings, current, baseline))


def test_ratchet_compare_detects_rise_new_file_and_fall():
    baseline = {R1: {"tests/test_a.py": 1}}
    text = "\n".join(compare({R1: {"tests/test_a.py": 2, "tests/test_new.py": 1}}, baseline))
    assert "tests/test_a.py: 2 hits, baseline 1 -- count rose" in text
    assert "tests/test_new.py: 1 hits, new file -- count rose" in text
    fell = "\n".join(compare({R1: {}}, baseline))
    assert "good news: lower the baseline in the same PR" in fell
    assert compare({R1: {"tests/test_a.py": 1}}, baseline) == []


def test_ratchet_failure_message_names_location_fix_and_command():
    finding = Finding(R1, "tests/test_a.py", 7, "multi-line fixture written in text mode", R1_FIX)
    report = build_failure_report([finding], {R1: {"tests/test_a.py": 1}}, {R1: {}})
    assert "tests/test_a.py:7" in report
    assert "newline=''" in report
    assert UPDATE_COMMAND in report


def test_r1_flags_the_navis_yaml_mint_fixture_writer():
    source = (
        "from pathlib import Path\n"
        "\n"
        "def _bytes(root, name):\n"
        "    return (root / 'items' / name).read_bytes()\n"
        "\n"
        "def _setup(tmp_path, files):\n"
        "    items = tmp_path / 'items'\n"
        "    for name, text in files.items():\n"
        "        (items / name).write_text(text, encoding='utf-8')\n"
    )
    findings = scan_source(source, "tests/test_navis_mint_yaml.py")
    assert [f.line for f in findings] == [9]
    assert findings[0].rule == R1


def test_r1_flags_literal_multiline_write_text():
    source = (
        "def test_x(tmp_path):\n"
        "    (tmp_path / 'a.md').write_text('---\\ntitle: T\\n---\\n', encoding='utf-8')\n"
        "    raw = (tmp_path / 'a.md').read_bytes()\n"
        "    assert b'\\n' in raw\n"
    )
    findings = scan_source(source, "tests/test_a.py")
    assert [f.line for f in findings] == [2]


def test_r1_flags_multiline_open_write():
    source = (
        "def test_x(tmp_path):\n"
        "    with open(tmp_path / 'a.md', 'w', encoding='utf-8') as fh:\n"
        "        fh.write('---\\nbody\\n')\n"
        "    assert (tmp_path / 'a.md').read_bytes()\n"
    )
    findings = scan_source(source, "tests/test_a.py")
    assert [f.line for f in findings] == [2]


def test_r1_ignores_safe_writes():
    source = (
        "def test_x(tmp_path):\n"
        "    (tmp_path / 'a.md').write_bytes(b'---\\nbody\\n')\n"
        "    (tmp_path / 'b.md').write_text('one line', encoding='utf-8', newline='')\n"
        "    (tmp_path / 'c.md').write_text('a\\nb')\n"
        "    raw = (tmp_path / 'a.md').read_bytes()\n"
        "    assert raw\n"
    )
    assert [f.line for f in scan_source(source, "tests/test_a.py")] == [4]
    no_byte_reads = scan_source(
        "def test_x(tmp_path):\n"
        "    (tmp_path / 'c.md').write_text('a\\nb')\n"
        "    assert (tmp_path / 'c.md').read_text().count('\\n') == 1\n",
        "tests/test_b.py",
    )
    assert no_byte_reads == []


def test_r1_ignores_outside_scope():
    source = (
        "def _helper(p, text):\n"
        "    p.write_text(text)\n"
        "    p.read_bytes()\n"
    )
    assert scan_source(source, "src/refdes/util.py") == []


def test_r2_flags_relpath_in_diagnostic():
    source = (
        "import os\n"
        "\n"
        "def _entry(path, root):\n"
        "    return {'file': os.path.relpath(path, root) if root else path}\n"
    )
    findings = scan_source(source, "src/refdes/navis_archive.py")
    assert [f.line for f in findings] == [4]
    assert findings[0].rule == R2


def test_r2_ignores_normalized_forms():
    source = (
        "import os\n"
        "from pathlib import Path\n"
        "import posixpath\n"
        "\n"
        "a = os.path.relpath('x', '.').replace('\\\\', '/')\n"
        "b = os.path.relpath('x', '.').replace(os.sep, '/')\n"
        "c = Path(os.path.relpath('x', '.')).as_posix()\n"
        "d = posixpath.relpath('x/y', 'x')\n"
    )
    assert scan_source(source, "src/refdes/thing.py") == []


def test_r2_flags_relpath_normalized_in_a_later_statement():
    source = (
        "import os\n"
        "\n"
        "def f(path, root):\n"
        "    rel = os.path.relpath(path, root)\n"
        "    return rel.replace(os.sep, '/')\n"
    )
    assert [f.line for f in scan_source(source, "src/refdes/thing.py")] == [4]


def test_rules_scan_the_tree_fast():
    """The lint runs inside the suite, so it must stay fast -- measured in
    CPU seconds, not wall clock. A wall-clock bound flakes by construction
    in a parallel suite: with 10-way xdist on a loaded box this scan was
    measured at 11.1s of wall for the same ~3.4s of work (run 15), because
    preemption inflates only wall time. ``time.process_time`` counts this
    process's CPU seconds, which other jobs on other cores cannot inflate;
    the 60s ceiling is ~17x the measured cost, so it fires only on a real
    algorithmic blow-up -- a pathological rule check (e.g. quadratic
    scanning) burns CPU seconds and crosses it. Measured on this tree
    (296 files, five rules, R5 reparsing each file under
    ``feature_version=(3, 11)``): 6.0s of CPU; a per-file burn of 0.25s
    CPU (~4 files' worth per second) reaches ~75s and trips the assert.
    """
    scanned = list(iter_scanned_files(REPO_ROOT))
    assert len(scanned) >= 250  # a scan that skipped the tree is also "fast"
    started = time.process_time()
    findings = scan_repo()
    elapsed = time.process_time() - started
    assert len(findings) > 0
    assert elapsed < 60.0, f"cross-platform lint burned {elapsed:.1f}s of CPU"


def test_rules_for_returns_every_applicable_rule():
    assert set(rules_for("tests/test_a.py")) == {R1, R3, R4, R5}
    assert rules_for("README.md") == []
    assert rules_for("docs/index.md") == []
    assert set(rules_for("src/refdes/build.py")) == {R2, R3, R4, R5}
    assert set(rules_for("tools/pr_size.py")) == {R3, R4, R5}
    assert rules_for("README.md") == []
    assert rules_for("docs/index.md") == []
    assert set(rules_for("src/refdes/model.py")) == {R2, R3, R4, R5}


def test_r3_flags_read_text_newline_kwarg():
    source = (
        "def test_x(tmp_path):\n"
        "    text = (tmp_path / 'a.md').read_text(encoding='utf-8', newline='')\n"
    )
    findings = scan_source(source, "tests/test_serve_navis_mint.py")
    assert [f.line for f in findings] == [2]
    assert findings[0].rule == R3
    assert "3.13" in findings[0].message
    assert findings[0].fix.startswith("use Path.open(newline='').read()")


def test_r3_ignores_the_always_available_spellings():
    source = (
        "def test_x(tmp_path):\n"
        "    a = (tmp_path / 'a.md').read_text(encoding='utf-8')\n"
        "    (tmp_path / 'b.md').write_text('x', newline='')\n"
        "    fh = open(tmp_path / 'c.md', 'w', newline='')\n"
        "    raw = (tmp_path / 'd.md').read_bytes()\n"
    )
    assert scan_source(source, "tests/test_a.py") == []


def test_r4_flags_itertools_batched_use_and_import():
    use = scan_source(
        "import itertools\n"
        "\n"
        "for group in itertools.batched(range(9), 3):\n"
        "    pass\n",
        "tests/test_a.py",
    )
    assert [f.line for f in use] == [3]
    assert use[0].rule == R4
    assert "3.12" in use[0].message
    imported = scan_source("from itertools import batched\n", "tools/pr_size.py")
    assert [f.line for f in imported] == [1]
    clean = scan_source(
        "import itertools\n"
        "\n"
        "for pair in itertools.pairwise(range(9)):\n"
        "    pass\n",
        "tests/test_a.py",
    )
    assert clean == []


def test_r4_flags_path_walk_only_on_plausible_paths():
    source = (
        "import os\n"
        "import ast\n"
        "from pathlib import Path\n"
        "\n"
        "def f(root):\n"
        "    base = Path('items')\n"
        "    for dirpath, _dirs, names in os.walk(root):\n"
        "        pass\n"
        "    for entry in (root / 'items').walk():\n"
        "        pass\n"
        "    for entry in base.walk():\n"
        "        pass\n"
        "    for node in ast.walk(ast.parse('x = 1')):\n"
        "        pass\n"
        "    obj.walk()\n"
    )
    findings = scan_source(source, "tests/test_a.py")
    assert [f.line for f in findings] == [9, 11]
    assert all("Path.walk" in f.message for f in findings)


def test_r4_flags_path_predicates_and_os_path_isjunction():
    source = (
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "def f(p: Path):\n"
        "    if p.is_junction():\n"
        "        return os.path.isjunction(str(p))\n"
        "    return p.full_match('items/*.md')\n"
    )
    findings = scan_source(source, "tests/test_a.py")
    assert sorted(f.line for f in findings) == [5, 6, 7]
    good = scan_source(
        "def f(p):\n"
        "    return p.is_dir() and p.match('items/*.md')\n",
        "tests/test_b.py",
    )
    assert good == []


def test_r4_flags_copy_replace_sumprod_override_deprecated():
    source = (
        "import copy\n"
        "import math\n"
        "import typing\n"
        "import warnings\n"
        "\n"
        "a = copy.replace(obj, x=1)\n"
        "b = math.sumprod([1], [2])\n"
        "\n"
        "class C:\n"
        "    @typing.override\n"
        "    def m(self):\n"
        "        return warnings.deprecated('use n')(self.m)\n"
    )
    findings = scan_source(source, "tests/test_a.py")
    assert [f.line for f in findings] == [6, 7, 10, 12]
    imported = scan_source(
        "from typing import override\n"
        "\n"
        "class C:\n"
        "    @override\n"
        "    def m(self):\n"
        "        pass\n",
        "tests/test_a.py",
    )
    assert [f.line for f in imported] == [1]
    good = scan_source(
        "import copy\n"
        "import math\n"
        "import warnings\n"
        "\n"
        "a = copy.deepcopy(obj)\n"
        "b = math.fsum([1, 2])\n"
        "warnings.warn('x')\n",
        "tests/test_b.py",
    )
    assert good == []


def test_r4_flags_shutil_rmtree_onexc_keyword():
    source = (
        "import shutil\n"
        "\n"
        "shutil.rmtree(path, onexc=_handler)\n"
    )
    assert [f.line for f in scan_source(source, "tests/test_a.py")] == [3]
    good = scan_source(
        "import shutil\n"
        "\n"
        "shutil.rmtree(path)\n"
        "shutil.rmtree(path, ignore_errors=True)\n"
        "shutil.rmtree(path, onerror=_handler)\n",
        "tests/test_b.py",
    )
    assert good == []
    bare = scan_source(
        "from shutil import rmtree\n"
        "\n"
        "rmtree(path, onexc=_handler)\n",
        "tools/pr_size.py",
    )
    assert [f.line for f in bare] == [3]
    local = scan_source(
        "def rmtree(path, onexc):\n"
        "    pass\n"
        "\n"
        "rmtree(path, onexc=_handler)\n",
        "tests/test_a.py",
    )
    assert local == []


def test_r4_ignores_tomllib():
    assert scan_source("import tomllib\n", "src/refdes/parse.py") == []
    assert scan_source("from tomllib import loads\n", "src/refdes/parse.py") == []


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.11 cannot parse the snippet at all")
def test_r5_flags_pep695_syntax():
    findings = scan_source("type Numbers = list[int]\n", "tests/test_a.py")
    assert [f.line for f in findings] == [1]
    assert findings[0].rule == R5
    assert "3.11" in findings[0].message
    assert "PEP 695" in findings[0].fix
    assert [f.line for f in scan_source("def f[T](x: T) -> T:\n    return x\n", "tests/test_a.py")] == [1]
    assert [f.line for f in scan_source("class Box[T]:\n    pass\n", "tests/test_a.py")] == [1]


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.11 cannot parse the snippet at all")
def test_r5_fstring_changes_are_a_documented_feature_version_limit():
    # feature_version=(3, 11) does NOT re-tokenize f-strings with 3.11
    # rules on a 3.12+ interpreter (verified: parses clean), so PEP 701
    # nesting is not catchable here -- the 3.11 CI job rejects it at its
    # own parse. The check_syntax_311_floor docstring records the limit.
    assert scan_source('print(f"{d["key"]}")\n', "tests/test_a.py") == []


def test_r5_ignores_311_valid_syntax():
    source = (
        "from typing import Generic, TypeAlias, TypeVar\n"
        "\n"
        "T = TypeVar('T')\n"
        "Numbers: TypeAlias = list[int]\n"
        "\n"
        "class Box(Generic[T]):\n"
        "    def __init__(self, x: T) -> None:\n"
        "        self.x = x\n"
    )
    assert scan_source(source, "tests/test_a.py") == []


def test_r5_failure_report_names_location_fix_and_command():
    finding = Finding(R5, "tests/test_a.py", 1, "syntax newer than Python 3.11: invalid syntax", R5_FIX)
    report = build_failure_report([finding], {R5: {"tests/test_a.py": 1}}, {})
    assert "tests/test_a.py:1" in report
    assert "PEP 695" in report
    assert UPDATE_COMMAND in report


def test_new_rules_find_no_hits_on_the_real_tree():
    hits = [f for f in scan_repo() if f.rule in (R3, R4, R5)]
    assert format_findings(hits) == []
