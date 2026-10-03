"""Text checks over the VS Code extension source (docs/design/editor-vscode-adapter.md §7.2).

There is no JS test harness in this repo, so the extension's own invariants are
driven from pytest by reading the source as text. This module carries exactly
one of the named tests: the activation-marker regression that made the whole
extension dead in the water (§2.3) -- the activation glob and `findRoot` both
looked for the retired `refdes.yaml` instead of `refdes-project.yaml`, so the
extension never activated in a real project (fixed in PR #58).

The Slice V0 tests below follow the same posture and the same limit: they pin the
invariants that are *textual* -- the two-sided ones where the extension and the
server must spell the same thing the same way (`refdes serve:` launch line,
`X-Refdes-Token`, the item-view keys the hover renders), plus §4's ban on a second
write path. What they deliberately do not do is drive the client over a socket;
§7.2 names `tests/test_vscode_extension_http_client.py` for that and it needs a
live `EditorApp` fixture, which is a bigger investment than a slice whose whole
point is to stay small.

Read-only by construction: nothing here writes to `editors/vscode/`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE_DIR = os.path.join(REPO_ROOT, "editors", "vscode")
PACKAGE_JSON = os.path.join(VSCODE_DIR, "package.json")
EXTENSION_JS = os.path.join(VSCODE_DIR, "extension.js")
SERVE_CLIENT_JS = os.path.join(VSCODE_DIR, "serveClient.js")
CLI_PY = os.path.join(REPO_ROOT, "src", "refdes", "cli.py")
SECURITY_PY = os.path.join(REPO_ROOT, "src", "refdes", "serve", "security.py")
API_PY = os.path.join(REPO_ROOT, "src", "refdes", "serve", "api.py")

PROJECT_MARKER = "refdes-project.yaml"
# The retired name. `refdes.yaml` is not a substring of `refdes-project.yaml`,
# so this only ever matches the old, wrong marker.
RETIRED_MARKER = re.compile(r"(?<![\w.-])refdes\.yaml\b")

FIND_ROOT = re.compile(r"function\s+findRoot\s*\([^)]*\)\s*\{(.*?)\n\}", re.DOTALL)


def _find_root_body(source: str) -> str:
    """Return the body of `findRoot`, or fail loudly if the function is gone."""
    match = FIND_ROOT.search(source)
    assert match, "editors/vscode/extension.js no longer defines a findRoot() function"
    return match.group(1)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _item_view_body() -> str:
    """The body of `_item_view`, the handler `GET /api/item/<ref>` dispatches to."""
    source = _read(API_PY)
    start = source.find("def _item_view(")
    assert start != -1, "src/refdes/serve/api.py no longer defines _item_view()"
    body = source[start:]
    end = body.find("\n\n\n")
    return body if end == -1 else body[:end]


def test_extension_activates_on_current_project_marker():
    """Both halves of activation name `refdes-project.yaml`, neither names `refdes.yaml`."""
    with open(PACKAGE_JSON, encoding="utf-8") as fh:
        manifest = json.load(fh)
    activation_events = manifest["activationEvents"]

    assert any(PROJECT_MARKER in event for event in activation_events), (
        "editors/vscode/package.json activationEvents does not name "
        f"{PROJECT_MARKER!r}; it is {activation_events!r}, so the extension never "
        "activates in a current project"
    )
    retired_in_manifest = [event for event in activation_events if RETIRED_MARKER.search(event)]
    assert not retired_in_manifest, (
        f"editors/vscode/package.json activationEvents names the retired "
        f"'refdes.yaml': {retired_in_manifest!r}"
    )

    with open(EXTENSION_JS, encoding="utf-8") as fh:
        source = fh.read()
    body = _find_root_body(source)

    assert PROJECT_MARKER in body, (
        "editors/vscode/extension.js findRoot() does not check for "
        f"{PROJECT_MARKER!r}, so it cannot find a current project's root"
    )
    retired_in_find_root = RETIRED_MARKER.findall(body)
    assert not retired_in_find_root, (
        "editors/vscode/extension.js findRoot() checks for the retired "
        f"'refdes.yaml' ({len(retired_in_find_root)} occurrence(s))"
    )


# --------------------------------------------------------------- Slice V0

HOVER_BODY = re.compile(r"function\s+itemMarkdown\s*\(\s*item\s*,\s*view\s*\)")
# §4: "the extension must never write an item file with `workspace.applyEdit`",
# and §6 Q5 bans it outright -- every mutation is a POST the server decides.
FORBIDDEN_WRITE = re.compile(
    r"\bapplyEdit\b|\bWorkspaceEdit\b|\bfs\.(?:writeFile|appendFile|writeFileSync|appendFileSync)\b"
)


def test_hover_still_renders_the_index_body_and_adds_the_snapshot_facts():
    """§8: coverage stage, check state and attributed diagnostics are *added to*
    the existing hover -- and each one is spelled the way `_item_view` returns it."""
    source = _read(EXTENSION_JS)

    assert HOVER_BODY.search(source), (
        "editors/vscode/extension.js no longer defines itemMarkdown(item, view). "
        "Slice V0 extends the existing hover in place rather than replacing it, so a "
        "rewrite that drops the index-rendered body is a regression, not a refactor"
    )
    assert re.search(r"new vscode\.Hover\(itemMarkdown\(item, view\)", source), (
        "editors/vscode/extension.js hoverProvider no longer hands the hover body the "
        "item view, so the three snapshot facts never reach the hover"
    )

    view_body = _item_view_body()
    for fact in ("coverage", "check", "diagnostics"):
        assert f'"{fact}"' in view_body, (
            f"src/refdes/serve/api.py _item_view no longer returns {fact!r}, which "
            f"editors/vscode/extension.js still renders as one of V0's three facts"
        )
        assert re.search(rf"view\.{fact}\b", source), (
            f"editors/vscode/extension.js no longer reads {fact!r} off the item view"
        )


def test_serve_client_and_the_cli_agree_on_the_launch_line():
    """§3.2 option 1: the extension parses the one line `cmd_serve` prints.

    Two sides of one literal, pinned together -- the extension reads
    `LAUNCH_PREFIX`, the CLI writes it in `print(f"refdes serve: {app.launch_url}")`.
    If either moves, every hover in every window silently loses its facts.
    """
    cli_match = re.search(r'print\(f"(refdes serve: )\{app\.launch_url\}"', _read(CLI_PY))
    assert cli_match, (
        "src/refdes/cli.py no longer prints its launch URL behind the "
        "'refdes serve: ' prefix, which is the only thing the extension parses"
    )
    js_match = re.search(r'const LAUNCH_PREFIX = "([^"]*)"', _read(SERVE_CLIENT_JS))
    assert js_match, (
        "editors/vscode/serveClient.js no longer declares LAUNCH_PREFIX, so nothing "
        "is pinned against the CLI's launch line changing shape"
    )
    assert js_match.group(1) == cli_match.group(1), (
        f"the extension parses {js_match.group(1)!r} but `refdes serve` prints "
        f"{cli_match.group(1)!r}"
    )


def test_the_token_travels_only_in_the_header_the_server_checks():
    """§3.2: header yes, argv no, `localhost` no.

    The header name is read from `serve/security.py`, so a server-side rename that
    the client misses fails here rather than as an unexplained 403 in someone's
    window. Rows 3-5 of §3.2's table are all refusals to let the token live
    somewhere other than this process, and argv is the one that is mechanically
    checkable from source.
    """
    header_match = re.search(r'TOKEN_HEADER = "([^"]+)"', _read(SECURITY_PY))
    assert header_match, "src/refdes/serve/security.py no longer defines TOKEN_HEADER"
    source = _read(SERVE_CLIENT_JS)

    assert header_match.group(1) in source, (
        f"editors/vscode/serveClient.js does not send {header_match.group(1)!r}, "
        "which every /api/ request must carry -- reads included"
    )
    assert "--token" not in source, (
        "editors/vscode/serveClient.js passes a token on the command line: argv is "
        "readable by any local process (§3.2 row 4)"
    )
    assert re.search(r'this\.args\.concat\(\["serve", "--no-open"\]\)', source), (
        "editors/vscode/serveClient.js no longer spawns "
        "`<refdes.command> <configured args> serve --no-open` (§8)"
    )
    assert re.search(r'host: "127\.0\.0\.1"', source), (
        "editors/vscode/serveClient.js no longer dials the printed IPv4 form; "
        "localhost may resolve to ::1 while the server binds IPv4 only (§3.2)"
    )
    assert not re.search(r'host:\s*"localhost"', source), (
        "editors/vscode/serveClient.js dials localhost"
    )


def test_no_direct_item_file_writes_in_extension_source():
    """§7.2's named test: no second write path (§4, §6 Q5).

    Comments are skipped -- the ban is stated in prose in several places, and a
    comment naming `applyEdit` to say it is banned must not fail the test that
    bans it.
    """
    offenders = []
    for name in sorted(os.listdir(VSCODE_DIR)):
        if not name.endswith(".js"):
            continue
        path = os.path.join(VSCODE_DIR, name)
        for number, line in enumerate(_read(path).splitlines(), start=1):
            if line.strip().startswith(("//", "/*", "*")):
                continue
            match = FORBIDDEN_WRITE.search(line)
            if match:
                offenders.append(f"{name}:{number}: {match.group(0)}")

    assert not offenders, (
        "the extension writes a file directly: "
        + "; ".join(offenders)
        + ". Every mutation goes through POST /api/item/<ref>/edit with a "
        "freshly-read expected_revision, or it does not happen (§3.5, §6 Q5)"
    )


def test_hover_shows_former_ids_and_the_item_view_returns_them():
    """A renamed item's retired ids reach the hover, so someone reading a
    schematic or a commit message that still cites the old one sees where it
    went without leaving the editor (finding F3.2).

    Two sides pinned together, the same posture as the coverage/check/
    diagnostics facts above: `GET /api/item/<ref>` has to return the list, and
    the hover has to read it off the view. The index row already carries
    `former_ids` (`render.items_json`), so the fallback keeps the hover honest
    when no `refdes serve` is running.
    """
    source = _read(EXTENSION_JS)
    view_body = _item_view_body()

    assert '"former_ids"' in view_body, (
        "src/refdes/serve/api.py _item_view no longer returns 'former_ids', so a "
        "hover served from the live snapshot cannot name the retired ids"
    )
    assert re.search(r"view\.former_ids", source), (
        "editors/vscode/extension.js no longer reads former_ids off the item view"
    )
    assert re.search(r"formerly known as", source), (
        "editors/vscode/extension.js no longer says 'formerly known as' in the hover"
    )
    assert re.search(r"item\.former_ids", source), (
        "editors/vscode/extension.js no longer falls back to the index row's "
        "former_ids, so the fact disappears when no refdes serve is running"
    )


def _provide_completion_items_body(source: str) -> str:
    """The brace-balanced body of `completionProvider.provideCompletionItems`.

    Not a non-greedy regex like `_find_root_body` above: this method's body
    has its own nested `if`/`{}` blocks, so a lazy `.*?\\}` would stop at the
    first one of those rather than the method's own closing brace.
    """
    marker = "provideCompletionItems(document, position) {"
    start = source.find(marker)
    assert start != -1, (
        "editors/vscode/extension.js no longer defines "
        "completionProvider.provideCompletionItems"
    )
    i = start + len(marker)
    depth = 1
    while depth > 0:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    return source[start + len(marker) : i - 1]


def test_id_completion_sets_an_explicit_range_and_insert_text():
    """A completion over a hyphenated id must replace exactly what was
    already typed, not whatever VS Code infers from its own default word
    range (reported directly from a real authoring session: finishing a
    completion over a partly-typed id duplicated the already-typed prefix
    instead of completing it).

    VS Code's default word pattern does not treat `-` as part of a word, so
    an id like `LOG-MAIN-001` is several "words" to it. Left unset, the
    range VS Code infers and replaces is only the run of characters since the
    last hyphen -- accepting a completion for `LOG-MAIN-001` while
    `LOG-MAIN-0` was already typed replaced only the trailing `0`, inserting
    the full id after it (`LOG-MAIN-LOG-MAIN-001`). The same default-range
    guess is also what VS Code filters the open list against as more is
    typed, so once past the last hyphen it kept narrowing against only that
    trailing fragment and entries that should still have matched stopped
    appearing. One cause, and the fix below for both: give VS Code the real
    range.
    """
    source = _read(EXTENSION_JS)
    id_branch = _provide_completion_items_body(source)
    id_branch = id_branch[id_branch.index("Otherwise offer item IDs") :]
    assert re.search(r"\bc\.range\s*=\s*range\b", id_branch), (
        "the id-completion branch no longer sets an explicit range on each "
        "CompletionItem -- see this test's docstring for what breaks without it"
    )
    assert re.search(r"\bc\.insertText\s*=\s*item\.id\b", id_branch), (
        "the id-completion branch no longer sets insertText explicitly, so it "
        "falls back to the label with nothing for the explicit range above to "
        "pair with"
    )


NODE = shutil.which("node")

# How long to wait for the one node process this test starts.
#
# The test makes exactly one node spawn for all four cases, so there is no
# per-assertion startup to fold into one; what is being waited on is node's own
# process start. 10 s was generous for that on a warm Linux box -- the script
# is ~30 lines doing four regex matches and two Range constructions, which runs
# in tens of milliseconds. It is not generous on a shared windows-latest runner:
# run 37099058285 (PR #161), attempt 1, failed its pytest step there with
#
#   subprocess.TimeoutExpired: Command '['C:\\Program Files\\nodejs\\node.EXE',
#   '-e', ...]' timed out after 10 seconds
#
# naming this test, while the same job ran the other 3258 tests in ~370 s on a
# diff that never touched this file. Runs 36971922062 (PR #156) and 37052790310
# (PR #157) each failed their windows-latest pytest step on attempt 1 and went
# green on attempt 2; their attempt-1 logs are no longer downloadable, so those
# two are reported rather than re-read. Nothing here got slower -- a cold
# antivirus scan of node.EXE plus CPU contention is what makes a process start
# take over 10 s on a shared runner. So the timeout goes up rather than the test
# going away: the assertions below are the same assertions, and a node that
# really hangs still fails the test -- after 120 s instead of 10.
NODE_TIMEOUT_S = 120


@pytest.mark.skipif(NODE is None, reason="no node on PATH to execute the extracted logic")
def test_id_completion_range_covers_the_whole_typed_id():
    """Executes the trigger regex and range math lifted verbatim from the
    source -- not a hand-copied duplicate the source could drift away from
    unnoticed -- against partially-typed ids, including the one that exposed
    the bug: typing `LOG-MAIN-0` stopped matching `LOG-MAIN-001`/`-002`.
    """
    source = _read(EXTENSION_JS)
    id_branch = _provide_completion_items_body(source)
    id_branch = id_branch[id_branch.index("Otherwise offer item IDs") :]

    trigger_expr = re.search(r"const trigger =\s*\n(.*?);\n", id_branch, re.DOTALL)
    assert trigger_expr, "could not find the trigger expression to extract"
    range_stmt = re.search(
        r"const typed = trigger\[1\];\s*\n(.*?)\n\s*\n", id_branch, re.DOTALL
    )
    assert range_stmt, "could not find the range computation to extract"

    cases = ["something REQ-PWR-00", "LOG-MAIN-0", "[[LOG-MA", "[["]
    script = f"""
const vscode = {{ Range: class {{
  constructor(sl, sc, el, ec) {{
    this.start = {{ line: sl, character: sc }};
    this.end = {{ line: el, character: ec }};
  }}
}} }};
const cases = {json.dumps(cases)};
const results = [];
for (const before of cases) {{
  const position = {{ line: 0, character: before.length }};
  const trigger =
    {trigger_expr.group(1).strip()};
  if (!trigger) {{ results.push({{ before, covers: null }}); continue; }}
  const typed = trigger[1];
  {range_stmt.group(1).strip()}
  results.push({{
    before,
    covers: before.slice(range.start.character, range.end.character),
  }});
}}
console.log(JSON.stringify(results));
"""
    proc = subprocess.run(
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    results = {r["before"]: r["covers"] for r in json.loads(proc.stdout)}

    assert results["LOG-MAIN-0"] == "LOG-MAIN-0", (
        "the computed replace range no longer covers the whole typed id -- "
        f"got {results['LOG-MAIN-0']!r}. Accepting a completion would insert "
        "the full id on top of only part of what was typed, and VS Code's "
        "incremental filtering would narrow against only that leftover part"
    )
    assert results["something REQ-PWR-00"] == "REQ-PWR-00"
    # The `[[` form's range must not swallow the brackets themselves.
    assert results["[[LOG-MA"] == "LOG-MA"
    assert results["[["] == ""
