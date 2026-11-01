"""Cross-platform lint: mechanically visible Windows hazards in tests and src.

Two PRs went green on Linux and red on Windows CI the same month: a test
wrote multi-line fixtures with text-mode ``write_text`` (Windows rewrites
``\\n`` to ``\\r\\n``) and asserted on raw ``'\\n'`` byte reads; a
diagnostic path built with ``os.path.relpath`` was asserted with ``'/'``
separators. These rules scan the tree for that class of code. Hits on the
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
    Normalizing in a later statement (the scaffold.py pattern) is a
    baseline hit; ``parse._relpath`` call sites are clean by construction
    since they contain no ``relpath`` call.

Known limits, by design: R1 does not follow content through call
expressions (``write_text(json.dumps(x))`` is not flagged) and the
byte-read gate is module-wide; R2 accepts any enclosing ``as_posix()``.
"""

from __future__ import annotations

import ast
import json
import time
from collections import namedtuple
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).with_name("crossplatform_lint_baseline.json")
UPDATE_COMMAND = "python tests/crossplatform_lint_baseline_update.py"

R1 = "R1-multiline-text-write"
R2 = "R2-relpath-not-normalized"

R1_SCOPE = "tests"
R2_SCOPE = "src/refdes"

R1_FIX = (
    "write the fixture as bytes (write_bytes) or pass newline='' to "
    "write_text/open so the bytes are the same on every platform"
)
R2_FIX = (
    "normalize in the same expression: .replace(os.sep, '/') / "
    ".replace('\\\\', '/') / Path(...).as_posix()"
)

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


def _finding(rule, relpath, node, message, fix):
    return Finding(rule, relpath, node.lineno, message, fix)


RULE_CHECKS = {R1: check_multiline_text_writes, R2: check_relpath_not_normalized}
RULE_SCOPES = {R1: R1_SCOPE, R2: R2_SCOPE}


def _rule_for(relpath):
    posix = Path(relpath).as_posix()
    for rule, scope in RULE_SCOPES.items():
        if posix.startswith(scope + "/") and posix.endswith(".py"):
            return rule
    return None


def scan_source(source, relpath):
    """Run the rule that applies to `relpath` over a source string."""
    rule = _rule_for(relpath)
    if rule is None:
        return []
    return RULE_CHECKS[rule](relpath, ast.parse(source))


def iter_scanned_files(root):
    for rule, scope in RULE_SCOPES.items():
        base = root / scope
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield rule, path.relative_to(root).as_posix(), path


def scan_repo(root=REPO_ROOT):
    findings = []
    for rule, relpath, path in iter_scanned_files(root):
        findings.extend(RULE_CHECKS[rule](relpath, ast.parse(path.read_bytes())))
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
    """The lint runs inside the suite, so it must stay fast. The spec
    budget is under five seconds of scanning; the assert leaves headroom
    for a loaded CI runner so a busy box cannot turn a slow CPU into a
    red suite (measured on the dev box: well under the budget).
    """
    started = time.perf_counter()
    findings = scan_repo()
    elapsed = time.perf_counter() - started
    assert len(findings) > 0
    assert elapsed < 10.0, f"cross-platform lint took {elapsed:.1f}s"
