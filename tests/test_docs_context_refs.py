"""Contract tests for the docs-context reference tool (tools/docs_context/refs.py).

The tool parses a docs page with the SAME markdown parser the docs site uses
(``refdes.build._markdown_parser()``), extracts the references each block
makes (code refs like ``src/refdes/cli.py:3227``, backticked file paths,
``refdes`` commands, markdown links), and resolves each one into a JSON card
of facts from the repo. It never writes, and never touches the network.

The module is imported from its file path the way ``tests/test_pr_size.py``
imports ``tools/pr_size.py``: ``tools/`` is not a shipped package, and a
namespace-package import off a sys.path entry needs no ``__init__.py``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from docs_context import refs

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "docs_context" / "refs.py"

DOC_LINES = [
    "# Title",  # 1
    "",  # 2
    "Intro `src/pkg/mod.py:4` and file `src/pkg/mod.py` and run `refdes rm` now.",  # 3
    "",  # 4
    "- item one `src/pkg/mod.py:5`",  # 5
    "- item two",  # 6
    "",  # 7
    "| a | b |",  # 8
    "| --- | --- |",  # 9
    "| `src/pkg/mod.py:6` | x |",  # 10
    "",  # 11
    "```python",  # 12
    "refdes navis archive 4jp6qy",  # 13
    "```",  # 14
    "",  # 15
    "```console",  # 16
    "$ refdes navis archive 4jp6qy  # do it",  # 17
    "output line",  # 18
    "```",  # 19
    "",  # 20
    "## Sec",  # 21
    "",  # 22
    "Links [u](b.md#usage) [ext](https://example.com/x) [a](#sec) `[x](b.md)`.",  # 23
    "",  # 24
    (
        "Negatives: `key: value` at `12:30` and `localhost:8080` and "
        "`std::vector` and `a:b` and `file.py` and `e.g.:3` and `v1.2:3`; "
        "bare http://host:80/x."
    ),  # 25
    "",  # 26
    (
        "Symbols: see `src/pkg/mod.py:2` for `alpha42` and `ZZZ_missing`; "
        "run `refdes widgetize`."
    ),  # 27
    "",  # 28
    "Range `src/pkg/mod.py:10-12` and past-end `src/pkg/mod.py:999`.",  # 29
    "",  # 30
    "Bare prose src/pkg/mod.py:7 with no backticks.",  # 31
    "",  # 32
    "Outside `../outside.txt:2` and git `.git/hook.sh:1`.",  # 33
    "",  # 34
    "Binary `sub/data.bin:2` and big `sub/big.bin:2`.",  # 35
    "",  # 36
    "Gone `src/pkg/gone.py:3` and outside file `../outside.txt`.",  # 37
    "",  # 38
    (
        "Links2 [g](b.md#blocked-by-and-the-cascade-report) "
        "[h](b.md#blocked_by-and-the-cascade-report) [w](b.md#usage-2) "
        "[w3](b.md#usage-3) [m](c.md#x)."
    ),  # 39
]
DOC = "\n".join(DOC_LINES) + "\n"

B_DOC_LINES = [
    "# B page",  # 1
    "",  # 2
    "## Usage",  # 3
    "",  # 4
    "first para of usage.",  # 5
    "",  # 6
    "## Usage",  # 7
    "",  # 8
    "second usage section.",  # 9
    "",  # 10
    "## blocked_by and the cascade report",  # 11
    "",  # 12
    "- one",  # 13
    "- two",  # 14
    "- three",  # 15
    "- four",  # 16
    "- five",  # 17
    "- six",  # 18
    "- seven",  # 19
    "- eight",  # 20
    "- nine",  # 21
]
B_DOC = "\n".join(B_DOC_LINES) + "\n"


def make_mod_py():
    lines = ["# mod.py", "def alpha42():", "    return 42"]
    lines += [f"# line {n}" for n in range(4, 31)]
    return lines


MOD_PY = make_mod_py()


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "mod.py").write_text(
        "\n".join(MOD_PY) + "\n", encoding="utf-8", newline=""
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text(DOC, encoding="utf-8", newline="")
    (repo / "docs" / "b.md").write_text(B_DOC, encoding="utf-8", newline="")
    (repo / "sub").mkdir()
    (repo / "sub" / "data.bin").write_bytes(b"\x00\x01\x02\nbinary\n")
    with open(repo / "sub" / "big.bin", "wb") as fh:
        fh.truncate(3 * 1024 * 1024)
    (repo / ".git").mkdir()
    (repo / ".git" / "hook.sh").write_text("# hook\n", encoding="utf-8", newline="")
    (tmp_path / "outside.txt").write_text("outside file\n", encoding="utf-8", newline="")
    (tmp_path / "abs_probe.txt").write_text("probe\n", encoding="utf-8", newline="")
    return repo


def block_at(text, kind, start_line):
    for block in refs.parse_doc(text):
        if block.start_line == start_line:
            return block
    raise AssertionError(f"no {kind} block starting at line {start_line}")


def refs_of(text, kind, start_line):
    return [r for r in block_at(text, kind, start_line).refs if r.kind == kind]


def first_ref(text, kind, start_line):
    found = refs_of(text, kind, start_line)
    assert found, f"no {kind} ref in block {start_line}"
    return found[0]


def resolve_ref(ref, repo, doc=None):
    if doc is None:
        return refs.resolve(ref, str(repo))
    return refs.resolve(ref, str(repo), doc_path=str(doc))


def cli_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_cli(repo, doc, extra=(), timeout=600):
    argv = [sys.executable, str(TOOL), str(doc), "--repo", str(repo)]
    argv.extend(extra)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env=cli_env(),
        cwd=str(repo),
        timeout=timeout,
    )


# --------------------------------------------------------------- parse_doc


def test_parse_doc_block_kinds_and_line_ranges():
    blocks = refs.parse_doc(DOC)
    kinds = [b.kind for b in blocks]
    assert kinds == [
        "heading",
        "paragraph",
        "list_item",
        "list_item",
        "table",
        "code",
        "console",
        "heading",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
    ]
    by_start = {b.start_line: b for b in blocks}
    assert by_start[1].kind == "heading" and by_start[1].end_line == 1
    assert by_start[3].kind == "paragraph" and by_start[3].end_line == 3
    assert by_start[8].kind == "table" and by_start[8].end_line == 10
    assert by_start[12].kind == "code" and by_start[12].end_line == 14
    assert by_start[16].kind == "console" and by_start[16].end_line == 19
    assert by_start[3].text == DOC_LINES[2]
    assert by_start[12].text == "\n".join(DOC_LINES[11:14])


def test_parse_doc_empty_text_has_no_blocks():
    assert refs.parse_doc("") == []


def test_plain_code_fence_is_code_kind_with_no_refs():
    block = block_at(DOC, "code", 12)
    assert block.text == "\n".join(DOC_LINES[11:14])
    assert block.refs == []


def test_console_fence_is_console_kind():
    block = block_at(DOC, "console", 16)
    assert block.text == "\n".join(DOC_LINES[15:19])


def test_heading_block_carries_refs():
    text = "## Uses `src/pkg/mod.py:3` today\n"
    block = block_at(text, "heading", 1)
    assert [r.kind for r in block.refs] == ["code_ref"]
    assert block.refs[0].path == "src/pkg/mod.py"
    assert block.refs[0].line_start == 3


# ---------------------------------------------------------------- code_ref


def test_code_ref_line_and_range_fields():
    single = first_ref(DOC, "code_ref", 3)
    assert single.path == "src/pkg/mod.py"
    assert single.line_start == 4 and single.line_end == 4
    rng = first_ref(DOC, "code_ref", 29)
    assert rng.path == "src/pkg/mod.py"
    assert rng.line_start == 10 and rng.line_end == 12
    assert rng.raw == "src/pkg/mod.py:10-12"


def test_code_ref_found_in_bare_prose():
    ref = first_ref(DOC, "code_ref", 31)
    assert ref.path == "src/pkg/mod.py" and ref.line_start == 7


def test_non_code_ref_shapes_are_not_refs():
    assert refs_of(DOC, "code_ref", 25) == []
    block = block_at(DOC, "paragraph", 25)
    assert block.refs == []


def test_ref_offsets_slice_the_block_text_exactly():
    for block in refs.parse_doc(DOC):
        for ref in block.refs:
            assert block.text[ref.start : ref.end] == ref.raw


def test_code_ref_card_window_and_cited(tmp_path):
    repo = make_repo(tmp_path)
    card = resolve_ref(first_ref(DOC, "code_ref", 3), repo)
    assert card["kind"] == "code_ref"
    assert card["path"] == "src/pkg/mod.py"
    assert card["exists"] is True
    assert card["cited"] == [4, 4]
    ns = [entry["n"] for entry in card["lines"]]
    assert ns == list(range(1, 10))  # line 4 +/- 5, clamped at the top
    assert card["lines"][3]["text"] == "# line 4"
    assert all(set(entry) == {"n", "text"} for entry in card["lines"])
    assert json.dumps(card)


def test_code_ref_card_range_window(tmp_path):
    repo = make_repo(tmp_path)
    card = resolve_ref(first_ref(DOC, "code_ref", 29), repo)
    assert card["cited"] == [10, 12]
    assert [entry["n"] for entry in card["lines"]] == list(range(5, 18))


def test_code_ref_missing_file_card(tmp_path):
    repo = make_repo(tmp_path)
    card = resolve_ref(first_ref(DOC, "code_ref", 37), repo)
    assert card["exists"] is False
    assert "lines" not in card


def test_code_ref_past_eof_not_in_range(tmp_path):
    repo = make_repo(tmp_path)
    past = [r for r in block_at(DOC, "paragraph", 29).refs if r.line_start == 999][0]
    card = resolve_ref(past, repo)
    assert card["exists"] is True
    assert card["in_range"] is False
    assert card.get("lines", []) == []


def test_code_ref_symbols_missing_heuristic(tmp_path):
    repo = make_repo(tmp_path)
    card = resolve_ref(first_ref(DOC, "code_ref", 27), repo)
    assert "ZZZ_missing" in card["symbols_missing"]
    assert "alpha42" not in card["symbols_missing"]
    assert "widgetize" not in card["symbols_missing"]  # a refdes command word
    assert "src" not in card["symbols_missing"]  # part of the ref itself
    assert "mod.py" not in card["symbols_missing"]


# ----------------------------------------------------------------- safety


def test_dotdot_path_is_outside_repo_and_not_opened(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("resolve opened a file")

    monkeypatch.setattr("builtins.open", boom)
    card = resolve_ref(first_ref(DOC, "code_ref", 33), repo)
    assert card == {"error": "outside repo"}


def test_absolute_path_is_outside_repo(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    ref = refs.Ref(
        kind="code_ref",
        raw="abs",
        start=0,
        end=3,
        path=str(tmp_path / "abs_probe.txt"),
        line_start=1,
        line_end=1,
    )

    def boom(*args, **kwargs):
        raise AssertionError("resolve opened a file")

    monkeypatch.setattr("builtins.open", boom)
    assert resolve_ref(ref, repo) == {"error": "outside repo"}


def test_git_paths_are_refused(tmp_path):
    repo = make_repo(tmp_path)
    card = resolve_ref(refs_of(DOC, "code_ref", 33)[1], repo)
    assert card.get("error")


def test_symlink_outside_repo_is_refused(tmp_path):
    if os.name == "nt":
        pytest.skip("symlink creation needs privileges on Windows")
    repo = make_repo(tmp_path)
    (repo / "sub2").mkdir()
    (repo / "sub2" / "link.py").symlink_to(tmp_path / "outside.txt")
    text = "Link `sub2/link.py:1` here.\n"
    card = resolve_ref(first_ref(text, "code_ref", 1), repo)
    assert card == {"error": "outside repo"}


def test_binary_file_is_not_text(tmp_path):
    repo = make_repo(tmp_path)
    card = resolve_ref(first_ref(DOC, "code_ref", 35), repo)
    assert card["error"] in {"not a text file", "too large"}


def test_file_over_two_megabytes_is_too_large(tmp_path):
    repo = make_repo(tmp_path)
    card = resolve_ref(refs_of(DOC, "code_ref", 35)[1], repo)
    assert card["error"] == "too large"


def test_file_ref_outside_repo_is_refused(tmp_path):
    repo = make_repo(tmp_path)
    ref = first_ref(DOC, "file_ref", 37)
    assert ref.path == "../outside.txt"
    assert resolve_ref(ref, repo) == {"error": "outside repo"}


# ---------------------------------------------------------------- file_ref


def test_file_ref_needs_slash_and_no_line():
    found = refs_of(DOC, "file_ref", 3)
    assert [r.path for r in found] == ["src/pkg/mod.py"]
    block = block_at(DOC, "paragraph", 25)
    assert [r for r in block.refs if r.kind == "file_ref"] == []


def test_file_ref_card_first_twelve_lines(tmp_path):
    repo = make_repo(tmp_path)
    card = resolve_ref(first_ref(DOC, "file_ref", 3), repo)
    assert card["exists"] is True
    assert [entry["n"] for entry in card["lines"]] == list(range(1, 13))
    assert card["lines"][0]["text"] == "# mod.py"
    assert card["lines"][11]["text"] == "# line 12"


# ------------------------------------------------------------------ links


def test_link_ref_fields_internal_external_anchor_only():
    found = refs_of(DOC, "link", 23)
    assert [r.text for r in found] == ["u", "ext", "a"]
    assert found[0].target == "b.md#usage"
    assert found[0].page == "b.md" and found[0].anchor == "usage"
    assert found[0].external is False
    assert found[1].external is True
    assert found[1].page is None and found[1].anchor is None
    assert found[2].page is None and found[2].anchor == "sec"


def test_link_in_code_span_is_not_a_ref():
    assert len(refs_of(DOC, "link", 23)) == 3
    plain = [b for b in refs.parse_doc(DOC) if b.kind == "code"]
    assert plain and all(b.refs == [] for b in plain)


def test_internal_link_card_anchor_and_excerpt(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    card = resolve_ref(first_ref(DOC, "link", 23), repo, doc=doc)
    assert card["target_exists"] is True
    assert card["anchor_ok"] is True
    assert card["heading"] == "Usage"
    assert card["excerpt"] == ["first para of usage."]


def test_duplicate_heading_anchor_suffixes(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    links = refs_of(DOC, "link", 39)
    by_text = {r.text: r for r in links}
    card = resolve_ref(by_text["w"], repo, doc=doc)
    assert card["anchor_ok"] is True and card["heading"] == "Usage"
    assert resolve_ref(by_text["w3"], repo, doc=doc)["anchor_ok"] is False


def test_site_slug_rules_underscore_case(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    links = {r.text: r for r in refs_of(DOC, "link", 39)}
    hyphen = resolve_ref(links["g"], repo, doc=doc)
    assert hyphen["anchor_ok"] is True
    assert hyphen["heading"] == "blocked_by and the cascade report"
    underscore = resolve_ref(links["h"], repo, doc=doc)
    assert underscore["anchor_ok"] is False


def test_section_excerpt_first_eight_lines(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    links = {r.text: r for r in refs_of(DOC, "link", 39)}
    card = resolve_ref(links["g"], repo, doc=doc)
    assert card["excerpt"] == [
        "- one",
        "- two",
        "- three",
        "- four",
        "- five",
        "- six",
        "- seven",
        "- eight",
    ]


def test_missing_page_card(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    links = {r.text: r for r in refs_of(DOC, "link", 39)}
    card = resolve_ref(links["m"], repo, doc=doc)
    assert card["target_exists"] is False
    assert card["anchor_ok"] is False


def test_anchor_only_link_resolves_against_doc_itself(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    anchor_only = [r for r in refs_of(DOC, "link", 23) if r.text == "a"][0]
    card = resolve_ref(anchor_only, repo, doc=doc)
    assert card["target_exists"] is True
    assert card["anchor_ok"] is True
    assert card["heading"] == "Sec"


def test_external_link_card_never_fetched(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("resolve used the network")

    monkeypatch.setattr(socket, "socket", boom)
    ext = [r for r in refs_of(DOC, "link", 23) if r.text == "ext"][0]
    card = resolve_ref(ext, repo, doc=repo / "docs" / "a.md")
    assert card["external"] is True
    assert card["url"] == "https://example.com/x"


# ---------------------------------------------------------------- commands


def test_command_verbs_stopping_rules():
    doc = "\n".join(
        [
            "Run `refdes navis archive 4jp6qy` now.",  # 1
            "",  # 2
            "Global flags `refdes --no-write navis archive X` skip.",  # 3
            "",  # 4
            "Quote stop `refdes check \"some text\"` here.",  # 5
            "",  # 6
            "Path stop `refdes navis archive docs/a.md` here.",  # 7
        ]
    ) + "\n"
    assert first_ref(doc, "command", 1).verbs == ["navis", "archive"]
    assert first_ref(doc, "command", 3).verbs == ["navis", "archive"]
    assert first_ref(doc, "command", 5).verbs == ["check"]
    assert first_ref(doc, "command", 7).verbs == ["navis", "archive"]


def test_console_fence_yields_command_from_dollar_line_only():
    found = refs_of(DOC, "command", 16)
    assert len(found) == 1
    ref = found[0]
    assert ref.verbs == ["navis", "archive"]
    assert ref.raw == DOC_LINES[16]
    block = block_at(DOC, "console", 16)
    assert block.text[ref.start : ref.end] == ref.raw


def _no_spawn(monkeypatch):
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("subprocess.run must not be called")

    def popen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("subprocess.Popen must not be called")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    return calls


def test_unknown_commands_never_spawn(tmp_path, monkeypatch):
    calls = _no_spawn(monkeypatch)
    repo = make_repo(tmp_path)
    card = resolve_ref(first_ref(DOC, "command", 3), repo)
    assert card["verbs"] == ["rm"]
    assert card["known"] is False
    assert card["help"] == ""
    card2 = resolve_ref(first_ref(DOC, "command", 27), repo)
    assert card2["known"] is False
    assert calls == []


def test_shell_metacharacters_never_spawn(tmp_path, monkeypatch):
    calls = _no_spawn(monkeypatch)
    repo = make_repo(tmp_path)
    doc = (
        'A `refdes navis archive; rm -rf` here.\n\n'
        "B `refdes build | sh` there.\n\n"
        "C `refdes navis nope` nowhere.\n"
    )
    for start in (1, 3, 5):
        card = resolve_ref(first_ref(doc, "command", start), repo)
        assert card["known"] is False
        assert card["help"] == ""
    assert calls == []


def _fake_help(monkeypatch, stdout):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Popen used"))
    return calls


def test_known_command_runs_help_once_with_list_argv(tmp_path, monkeypatch):
    calls = _fake_help(monkeypatch, "usage: refdes navis archive [-h]\n")
    repo = make_repo(tmp_path)
    doc = "Run `refdes navis archive 4jp6qy` now.\n"
    card = resolve_ref(first_ref(doc, "command", 1), repo)
    assert card["verbs"] == ["navis", "archive"]
    assert card["known"] is True
    assert card["help"] == "usage: refdes navis archive [-h]\n"
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert isinstance(argv, list)
    assert argv[0] == sys.executable and argv[1] == "-c"
    assert argv[-3:] == ["navis", "archive", "--help"]
    assert kwargs.get("shell") is not True
    env = kwargs["env"]
    assert env["PYTHONPATH"] == os.path.join(str(repo), "src")
    assert env["COLUMNS"] == "100"
    assert kwargs.get("timeout") == 10


def test_help_output_truncated_to_4000(tmp_path, monkeypatch):
    _fake_help(monkeypatch, "x" * 5000)
    repo = make_repo(tmp_path)
    doc = "Run `refdes navis archive 4jp6qy` now.\n"
    card = resolve_ref(first_ref(doc, "command", 1), repo)
    assert len(card["help"]) == 4000


# -------------------------------------------------------------------- CLI


def test_cli_prints_one_json_object(tmp_path):
    repo = make_repo(tmp_path)
    proc = run_cli(repo, "docs/a.md")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["doc"].replace("\\", "/").endswith("docs/a.md")
    blocks = data["blocks"]
    assert blocks[0]["kind"] == "heading" and blocks[0]["start_line"] == 1
    for block in blocks:
        assert set(block) >= {"kind", "start_line", "end_line", "text", "refs"}
        for ref in block["refs"]:
            assert isinstance(ref["card"], dict)
    console = [b for b in blocks if b["kind"] == "console"][0]
    command = console["refs"][0]["card"]
    assert command["verbs"] == ["navis", "archive"]
    assert command["known"] is True and command["help"]
    rm_cards = [
        r["card"]
        for b in blocks
        for r in b["refs"]
        if r["kind"] == "command" and r["card"]["verbs"] == ["rm"]
    ]
    assert rm_cards and rm_cards[0]["known"] is False
    code_refs = [
        r for b in blocks for r in b["refs"] if r["kind"] == "code_ref"
    ]
    unsafe = {"../outside.txt", "sub/data.bin", "sub/big.bin", ".git/hook.sh"}
    for ref in code_refs:
        if ref["path"] in unsafe:
            assert "error" in ref["card"]
        else:
            assert "exists" in ref["card"]
    link_cards = [
        r["card"] for b in blocks for r in b["refs"] if r["kind"] == "link"
    ]
    usage = [c for c in link_cards if c.get("target_exists") is not None][0]
    assert usage["target_exists"] is True and usage["anchor_ok"] is True


def test_cli_missing_doc_exits_two(tmp_path):
    repo = make_repo(tmp_path)
    proc = run_cli(repo, "docs/nope.md")
    assert proc.returncode == 2
    assert proc.stderr.strip()
    assert proc.stdout.strip() == ""


def test_cli_output_is_deterministic(tmp_path):
    repo = make_repo(tmp_path)
    first = run_cli(repo, "docs/a.md")
    second = run_cli(repo, "docs/a.md")
    assert first.returncode == 0 and second.returncode == 0
    assert first.stdout == second.stdout


def test_cli_navis_smoke():
    proc = run_cli(ROOT, "docs/navis.md", timeout=1200)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["blocks"]
    for block in data["blocks"]:
        for ref in block["refs"]:
            card = ref["card"]
            if ref["kind"] == "code_ref":
                assert "exists" in card
            elif ref["kind"] == "command":
                assert isinstance(card["known"], bool)
                assert isinstance(card["help"], str)
            elif ref["kind"] == "link" and ref["external"]:
                assert card == {"external": True, "url": ref["target"]}

# ---- appended by the implementer: DC-1 review round 1 (A fenced headings,
# ---- B fence inside a list item, C image syntax). Existing tests untouched.


def test_fenced_heading_is_not_indexed(tmp_path):
    repo = make_repo(tmp_path)
    page = "x\n\n```\n## Fake\n```\n\n## Real\n\ntext line.\n"
    (repo / "docs" / "f.md").write_text(page, encoding="utf-8", newline="")
    doc = repo / "docs" / "a.md"
    fake = refs.Ref(
        kind="link", raw="", start=0, end=0, page="f.md", anchor="fake",
        target="f.md#fake",
    )
    assert resolve_ref(fake, repo, doc=doc)["anchor_ok"] is False
    real = refs.Ref(
        kind="link", raw="", start=0, end=0, page="f.md", anchor="real",
        target="f.md#real",
    )
    card = resolve_ref(real, repo, doc=doc)
    assert card["anchor_ok"] is True
    assert card["heading"] == "Real"
    assert card["excerpt"] == ["text line."]


def test_setext_heading_is_indexed_as_h2(tmp_path):
    repo = make_repo(tmp_path)
    page = "top\n\n===\n\nTitle Two\n---\n\nafter setext.\n"
    (repo / "docs" / "s.md").write_text(page, encoding="utf-8", newline="")
    doc = repo / "docs" / "a.md"
    two = refs.Ref(
        kind="link", raw="", start=0, end=0, page="s.md", anchor="title-two",
        target="s.md#title-two",
    )
    card = resolve_ref(two, repo, doc=doc)
    assert card["anchor_ok"] is True
    assert card["excerpt"] == ["after setext."]
    top = refs.Ref(
        kind="link", raw="", start=0, end=0, page="s.md", anchor="top",
        target="s.md#top",
    )
    assert resolve_ref(top, repo, doc=doc)["anchor_ok"] is False


def test_fence_inside_list_item_yields_no_refs():
    text = (
        "- Item:\n"
        "\n"
        "  ```\n"
        "  refdes build\n"
        "  src/pkg/mod.py:10-12\n"
        "  ```\n"
        "\n"
        "- Next `src/pkg/mod.py:7`.\n"
    )
    fenced = block_at(text, "list_item", 1)
    assert fenced.refs == []
    other = block_at(text, "list_item", 8)
    assert [r.path for r in other.refs if r.kind == "code_ref"] == ["src/pkg/mod.py"]


def test_image_syntax_is_not_a_link_ref():
    text = "See ![alt text](img.png) and [real](b.md#usage).\n"
    found = refs_of(text, "link", 1)
    assert [r.text for r in found] == ["real"]
