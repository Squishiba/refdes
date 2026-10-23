"""The editor's write routes must not embed the server's absolute project paths.

User-sim release-gate run 13, section 3.5: the JSON responses of
`POST /api/item/<ref>/edit` and `POST /api/items/create` carry the machine's
absolute path inside free-text fields --
`conflict: /home/jorb/.paseo/worktrees/.../items/REQ-001.md changed since this
edit was planned`,
`applied: md-front-matter REQ-007: insert source at /home/jorb/.../REQ-007.md:6`
-- while the sibling `path` field has long been project-relative through
`api.shown()`, whose comment says the browser "has no use for a server
filesystem root, and a path it cannot read is a path it cannot leak". The free
text bypasses that helper: `Applied.message` embeds `plan.describe()`, the
conflict message embeds `Conflict.path`, `Created.message` embeds the
destination, and a file whose own text names the root drags it into `diff`
and `current_text` as well.

The contract (f13-3):

- no string value anywhere in an edit/create response payload -- `message`,
  `reason`, `describe`, `diff`, `current_text`, diagnostics: the whole
  payload walked recursively -- contains the server's absolute project root,
  in the native spelling, the separator-flipped one, or a case variant (a
  Windows drive-letter root is matched case-insensitively);
- where an absolute path under the root appears, it is replaced by the
  project-relative spelling with forward slashes, line suffix included:
  `at items/reqs.yaml:7`, `conflict: items/reqs.yaml changed`,
  `created: REQ-011 (requirement) in items/reqs.yaml`;
- the fix is one helper applied at the api layer's single serialization
  choke point, so the existing `path` fields and all non-path text -- patch
  descriptions, diagnostics, diff headers -- come back exactly as the service
  wrote them (the control tests pin that unchanged text).

The drive layer is `api.handle` itself, thread-free, following
tests/test_serve_edit_keyless_handle.py: the exact (status, payload) contract
the socket layer hands the browser, the real `ProjectState` with the real
post-save refresh; the transport (socket, token, origin) is test_serve_edit_http's.
Every assertion here is a status code, a payload string, or file bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from itertools import product
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from serve_support import make_project, snapshot_tree

from refdes.serve import api as api_mod
from refdes.serve import state as state_mod


class Api:
    """A thread-free drive of the API routes: the real `ProjectState`, the
    real `api.handle`, the same (status, payload) the socket layer returns."""

    def __init__(self, root, read_only: bool = False):
        self.state = state_mod.ProjectState(str(root / "refdes-project.yaml"))
        self.state.load()
        self.read_only = read_only

    def get(self, path: str):
        return api_mod.handle(self, "GET", path, {}, None)

    def post(self, path: str, payload):
        return api_mod.handle(self, "POST", path, {}, payload)


def keyless_client(tmp_path):
    """The run-13 scenario: an ordinary served project. Keys minted or not is
    not the subject here; the keyless fixture is the one the editor rows (and
    the run) are described against, and it keeps every project independent."""
    make_project(tmp_path, mint_keys=False)
    return Api(tmp_path), tmp_path


def sha256(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def reqs_file(root) -> str:
    return str(root / "items" / "reqs.yaml")


def save(client, ref, *, field="status", value="draft", revision):
    """`POST /api/item/<ref>/edit`, the handle URL-encoded the way
    editor.js encodes it; the route unquotes."""
    return client.post(
        f"/api/item/{quote(ref, safe='')}/edit",
        {"op": "set_field", "field": field, "value": value, "expected_revision": revision},
    )


# ------------------------------------------------------------- the walk
#
# The contract's own test instrument: a recursive walk of the payload
# asserting no string -- value, key, any nesting -- contains the root in any
# spelling. `root_spellings` mirrors what the fix must handle: the native
# separator, the forward-slash spelling, and the lower-case form (the
# drive-letter root matched case-insensitively). On Linux the first two
# spellings coincide and the backslash spelling is the path with its
# separators flipped, which a correct payload can never contain on any
# platform; the test is written for both.


def root_spellings(root):
    native = str(root)
    slash = native.replace("\\", "/")
    backslash = native.replace("/", "\\")
    return [
        native,
        slash,
        backslash,
        native.lower(),
        slash.lower(),
        backslash.lower(),
    ]


def strings_of(value):
    """Every string in a JSON-shaped value: leaves, dict keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings_of(key)
            yield from strings_of(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings_of(item)


def assert_no_root(payload, root, note=""):
    texts = list(strings_of(payload))
    assert any(texts), "the walk found no string to check"
    for spelling in root_spellings(root):
        for text in texts:
            assert spelling not in text, (
                f"the server's absolute project root leaks into a response "
                f"string ({note}): {spelling!r} in {text!r}"
            )


# --------------------------------------------------------- successful save
#
# `message` embeds `plan.describe()`, which quotes the target file's absolute
# path (patcher.describe: "at {path}:{line}"); `describe` is that same string.
# These are the two fields run 13 named.


def test_applied_save_response_carries_no_project_root(tmp_path):
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 200 and payload["kind"] == "applied", payload
    assert_no_root(payload, root, "applied 200 (message, describe)")


def test_applied_message_and_describe_use_the_relative_spelling_with_line_suffix(tmp_path):
    """The replacement is the project-relative spelling WITH the line suffix
    the format already printed: `at items/reqs.yaml:7`, not a dropped path.
    Both patcher shapes -- the yaml item and the run-13 md-front-matter one
    (`applied: md-front-matter REQ-007: ... at .../REQ-007.md:6`) -- are
    pinned, on two independent projects."""
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 200, payload
    assert_no_root(payload, root, "yaml-item applied 200 (full payload)")
    assert payload["describe"].startswith("yaml-item REQ-001: set_field status at ")
    assert re.search(r"at items/reqs\.yaml:\d+ \[\d+:\d+\]$", payload["describe"]), (
        payload["describe"]
    )
    assert payload["message"] == "applied: " + payload["describe"]

    md_root = tmp_path / "md"
    md_root.mkdir()
    client2, root2 = keyless_client(md_root)
    _status, view2 = client2.get("/api/item/REQ-010")
    status, payload2 = save(
        client2,
        "REQ-010",
        field="text",
        value="A rewritten markdown requirement.",
        revision=view2["edit"]["file_revision"],
    )
    assert status == 200, payload2
    assert_no_root(payload2, root2, "md-front-matter applied 200 (full payload)")
    assert payload2["describe"].startswith("md-front-matter REQ-010: set_field text at ")
    assert re.search(r"at items/notes\.md:\d+ \[\d+:\d+\]$", payload2["describe"]), (
        payload2["describe"]
    )
    assert payload2["message"] == "applied: " + payload2["describe"]


def test_applied_response_shape_path_and_non_path_text_are_unchanged(tmp_path):
    """The control: the fix relativizes the path text and changes nothing
    else. Response keys, the already-relative `path`, the describe/message
    prefixes, the revision, the live handle, and the diagnostics' own words
    all come back exactly as the service wrote them. This passes on the old
    code and must pass on the new."""
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 200, payload
    assert set(payload) == {
        "kind", "ok", "message", "path", "revision", "describe",
        "id", "handle", "pinned", "diagnostics",
    }
    assert payload["path"] == "items/reqs.yaml"
    assert payload["describe"].startswith("yaml-item REQ-001: set_field status at ")
    assert payload["message"] == "applied: " + payload["describe"]
    assert payload["revision"] == sha256(reqs_file(root))
    assert payload["id"] == "REQ-001" and payload["handle"] == "REQ-001"
    assert payload["pinned"] == []
    # the post-save refresh's own words, verbatim, and the diagnostic shape
    assert any(
        d["message"].startswith("8 items have no key yet") for d in payload["diagnostics"]
    ), payload["diagnostics"]
    assert all(
        set(d) == {"level", "message", "file", "line", "code"} for d in payload["diagnostics"]
    )


# ------------------------------------------------------------------ 409
#
# The conflict message embeds `Conflict.path` verbatim. `diff` and
# `current_text` carry the file's text: clean for this fixture's own bytes,
# absolute once the FILE text names the root -- which is the payload-wide
# clause of the contract, so one scenario pins each.


def _stale_save(client, root, ref="REQ-002", *, field="status", value="draft"):
    """Read the view, move the file behind the server's back, post the read
    revision: the ordinary 409."""
    _status, view = client.get(f"/api/item/{ref}")
    stale = view["edit"]["file_revision"]
    with open(reqs_file(root), "a", encoding="utf-8") as fh:
        fh.write("# touched by an outside writer\n")
    status, payload = save(client, ref, field=field, value=value, revision=stale)
    return status, payload, stale


def test_conflict_response_carries_no_project_root(tmp_path):
    client, root = keyless_client(tmp_path)
    status, payload, _stale = _stale_save(client, root)
    assert status == 409 and payload["kind"] == "conflict", payload
    assert_no_root(payload, root, "conflict 409 (message, diff, current_text)")


def test_conflict_message_names_the_changed_file_project_relative(tmp_path):
    client, root = keyless_client(tmp_path)
    status, payload, stale = _stale_save(client, root)
    assert status == 409, payload
    assert payload["message"] == (
        f"conflict: items/reqs.yaml changed since this edit was planned "
        f"(expected {stale[:12]}, found {payload['current_revision'][:12]})"
    ), payload["message"]
    # unchanged siblings: the already-relative `path`, the revisions, and the
    # empty replaced span of a field insertion
    assert payload["path"] == "items/reqs.yaml"
    assert payload["expected_revision"] == stale
    assert payload["current_revision"] == sha256(reqs_file(root))
    assert payload["current_text"] == ""


def test_a_conflict_whose_file_text_names_the_root_is_all_relative(tmp_path):
    """The payload-wide clause: when the project's OWN text quotes an
    absolute path under the root (an author pasting one into a requirement),
    `current_text` and the `diff` carry it on base -- and the same clause
    that relativizes `message` relativizes them: `items/reqs.yaml` with
    forward slashes, no root in any string."""
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    status, payload = save(
        client,
        "REQ-001",
        field="text",
        value=f"See {root}/items/reqs.yaml: values",
        revision=view["edit"]["file_revision"],
    )
    assert status == 200, payload

    status, payload, _stale = _stale_save(
        client, root, "REQ-001", field="text", value="Rewritten."
    )
    assert status == 409, payload
    assert_no_root(payload, root, "conflict 409 with a root path in the file text")
    assert "See items/reqs.yaml" in payload["current_text"], payload["current_text"]
    assert 'text: "See items/reqs.yaml: values"' in payload["diff"], payload["diff"]


# ------------------------------------------------------- 422 invalid + refused
#
# The gate-blocked `invalid` (a blocked enum save, diagnostics included) and
# the ordinary `refused` are clean on base: these are controls pinning that
# the fix's walk leaves the gate's and the resolver's own words, and the
# diagnostics' relative `file`, untouched.


def test_gate_blocked_invalid_response_carries_no_project_root(tmp_path):
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    status, payload = save(
        client, "REQ-001", value="banana", revision=view["edit"]["file_revision"]
    )
    assert status == 422 and payload["kind"] == "invalid", payload
    assert payload["diagnostics"], "the gate must say which error it blocked"
    assert_no_root(payload, root, "invalid 422 (message, reason, diagnostics)")


def test_gate_blocked_invalid_response_text_is_unchanged(tmp_path):
    client, _root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    status, payload = save(
        client, "REQ-001", value="banana", revision=view["edit"]["file_revision"]
    )
    assert status == 422, payload
    blocked = (
        "blocked: the edit would leave 1 error(s): status: 'banana' is not"
        " one of draft, approved."
    )
    assert payload["message"] == payload["reason"] == blocked, payload
    assert payload["path"] == "items/reqs.yaml"
    assert payload["diagnostics"][0] == {
        "level": "error",
        "message": "status: 'banana' is not one of draft, approved.",
        "file": "items/reqs.yaml",
        "line": 4,
        "code": None,
    }, payload["diagnostics"]


def test_refused_response_carries_no_project_root(tmp_path):
    client, root = keyless_client(tmp_path)
    before_tree = snapshot_tree(root)
    status, payload = client.post(
        "/api/item/REQ-999/edit",
        {
            "op": "set_field",
            "field": "status",
            "value": "draft",
            "expected_revision": sha256(reqs_file(root)),
        },
    )
    assert status == 422 and payload["kind"] == "refused", payload
    assert payload["reason"] == "no item 'REQ-999' in this project", payload
    assert payload["path"] is None
    assert_no_root(payload, root, "refused 422")
    assert snapshot_tree(root) == before_tree


# ------------------------------------------------------------------ create
#
# `Created.message` embeds the destination: `created: REQ-011 (requirement)
# in {abs}/items/reqs.yaml`.


def test_created_response_carries_no_project_root(tmp_path):
    client, root = keyless_client(tmp_path)
    status, payload = client.post(
        "/api/items/create", {"type": "requirement", "fields": {"text": "Probe item."}}
    )
    assert status == 200 and payload["kind"] == "created", payload
    assert_no_root(payload, root, "created 200 (message)")


def test_created_message_names_the_destination_project_relative(tmp_path):
    client, root = keyless_client(tmp_path)
    status, payload = client.post(
        "/api/items/create", {"type": "requirement", "fields": {"text": "Probe item."}}
    )
    assert status == 200, payload
    assert payload["message"] == f"created: {payload['id']} (requirement) in items/reqs.yaml", (
        payload["message"]
    )
    # unchanged siblings
    assert payload["path"] == "items/reqs.yaml"
    assert payload["type"] == "requirement"
    assert payload["revision"] == sha256(reqs_file(root))


# ------------------------------------------------------------------- walk
#
# The contract's dedicated case: one walk per write-route response shape --
# applied, conflict, created -- over three independent projects, asserting
# every spelling of each project's own root (native, separator-flipped,
# lower-case) is absent from every string of the whole payload.


def test_recursive_walk_of_every_write_response_finds_no_root_spelling(tmp_path):
    projects = {}

    root = tmp_path / "applied"
    root.mkdir()
    make_project(root, mint_keys=False)
    client = Api(root)
    _status, view = client.get("/api/item/REQ-001")
    _status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert payload["kind"] == "applied", payload
    projects["applied 200"] = (root, payload)

    root = tmp_path / "conflict"
    root.mkdir()
    make_project(root, mint_keys=False)
    client = Api(root)
    _status, view = client.get("/api/item/REQ-002")
    stale = view["edit"]["file_revision"]
    with open(reqs_file(root), "a", encoding="utf-8") as fh:
        fh.write("# touched by an outside writer\n")
    _status, payload = save(client, "REQ-002", revision=stale)
    assert payload["kind"] == "conflict", payload
    projects["conflict 409"] = (root, payload)

    root = tmp_path / "created"
    root.mkdir()
    make_project(root, mint_keys=False)
    client = Api(root)
    _status, payload = client.post(
        "/api/items/create", {"type": "requirement", "fields": {"text": "Probe item."}}
    )
    assert payload["kind"] == "created", payload
    projects["created 200"] = (root, payload)

    for note, (root, payload) in projects.items():
        assert_no_root(payload, root, note)


# --------------------------------------------------- the helper, driven directly
#
# The two spellings the windows-latest run proved matter, pinned on any
# platform with a Windows-shaped root named in the test itself (chunk-1
# review finding 1): the patcher writes a value containing ': ' through
# `json.dumps` (`_double_quoted`, patcher.py), so the file bytes -- and
# through them `current_text` and `diff` -- carry the root with DOUBLED
# backslashes: `text: "See C:\\Users\\x\\proj/items/reqs.yaml: values"`.
# And the root quoted with its own trailing separator (finding 2), which
# the changelog promises becomes `.`.


def test_the_helper_relativeizes_the_json_escaped_windows_spelling():
    root = "C:\\Users\\x\\proj"
    escaped = json.dumps(f"See {root}/items/reqs.yaml: values")
    assert "\\\\" in escaped, "the emitter must double the backslashes to pin the bug"
    got = api_mod._relative_paths_in_text(escaped, root)
    assert got == '"See items/reqs.yaml: values"', got


def test_the_helper_relativeizes_the_escaped_spelling_with_doubled_continuation():
    # The Windows CI shape on any platform: the root is native-backslash,
    # the value JSON-escaped on the way into the file. The first pass
    # consumes the root and the separator run that follows it and leaves
    # the continuation exactly as written -- escaped text stays escaped
    # (round-4 design: nothing after the root is rewritten, so a `\\` in
    # the continuation is no one's business to collapse).
    root = "C:\\Users\\x\\proj"
    escaped = json.dumps(f"conflict: {root}\\items\\reqs.yaml changed")
    got = api_mod._relative_paths_in_text(escaped, root)
    assert got == '"conflict: items\\\\reqs.yaml changed"', got
    assert "C:" not in got, got


def test_the_helper_turns_a_root_with_a_trailing_separator_into_dot():
    assert (
        api_mod._relative_paths_in_text("locked root: /home/you/proj/ here", "/home/you/proj")
        == "locked root: . here"
    )
    assert (
        api_mod._relative_paths_in_text("locked: C:\\root\\ here", "C:\\root")
        == "locked: . here"
    )


def test_the_helper_walks_dict_keys_and_tuple_elements_too():
    root = "C:\\Users\\x\\proj"
    payload = {f"{root}/items/a.md": (f"at {root}/items/b.md:2", [f"{root}/items/c.md"])}
    got = api_mod._relative_paths(payload, root)
    assert got == {"items/a.md": ("at items/b.md:2", ["items/c.md"])}, got


def test_write_route_payloads_are_json_shaped_and_contain_no_tuples(tmp_path):
    """The guard behind the walk: every string of a write-route payload is
    reachable through the JSON shape -- dict keys, string values, list
    elements, and nothing tuple-shaped that a walker must be told about.
    The `walk` below IS that proof (it fails on any tuple and pins every
    key to a string); the json round-trip beside it pins only
    serializability, which a tuple survives as a list."""
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    payloads = [save(client, "REQ-001", revision=view["edit"]["file_revision"])[1]]
    payloads.append(
        client.post("/api/items/create", {"type": "requirement", "fields": {"text": "P."}})[1]
    )
    assert_no_root(payloads[0], root, "applied 200 (json-shape guard scenario)")

    def walk(value):
        assert not isinstance(value, tuple), f"tuple-shaped payload value: {value!r}"
        assert value is None or isinstance(
            value, (str, int, float, bool, list, dict)
        ), value
        if isinstance(value, dict):
            for key, item in value.items():
                assert isinstance(key, str), key
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for payload in payloads:
        json.loads(json.dumps(payload))
        walk(payload)


# ------------------------------------------------- round 3: spaces and file URIs
#
# The token rule stops at whitespace, so a root containing a space --
# `C:\Users\Jane Doe\...`, `/home/user/my project` -- is common, and real,
# and only half-scrubbed by a pass that cannot cross the space: the match
# ends at the space, the under-root test fails, and the fragment up to the
# space collapses to its basename while the rest of the root walks out as
# prose. A root matched LITERALLY has no such problem: spaces inside it are
# just characters. The rule that satisfies this (reviewer-prescribed, and
# the shape the round-4 span scanner kept): the KNOWN root matches as a
# literal in every spelling it normalises -- native separators, forward
# slashes, the JSON-escaped doubling, a drive letter at any case, optionally
# preceded by `file://`/`file:///` -- swallowing the separator that follows
# so `<root>/items/x.yaml:6` becomes `items/x.yaml:6` and the bare root
# becomes `.`. Absolute paths NOT under the root keep their own rule: reduce
# to the bare file name, the `file://` prefix included.


def test_the_helper_relativeizes_a_posix_root_with_spaces():
    root = "/home/user/my project"
    assert (
        api_mod._relative_paths_in_text(
            "see /home/user/my project/items/file.yaml:8 ok", root
        )
        == "see items/file.yaml:8 ok"
    )
    assert (
        api_mod._relative_paths_in_text("locked: /home/user/my project/ here", root)
        == "locked: . here"
    )


def test_the_helper_relativeizes_a_windows_root_with_spaces():
    # The continuation is left exactly as written (round-4 design): the
    # backslashes after the root stay the file's own bytes.
    root = "C:\\Users\\Jane Doe\\proj"
    assert (
        api_mod._relative_paths_in_text(
            "at C:\\Users\\Jane Doe\\proj\\items\\a.md:3 now", root
        )
        == "at items\\a.md:3 now"
    )
    assert (
        api_mod._relative_paths_in_text("at c:\\users\\jane doe\\PROJ\\items\\a.md now", root)
        == "at items\\a.md now"
    )


def test_the_helper_relativeizes_the_json_escaped_spelling_of_a_spaced_root():
    root = "C:\\Users\\Jane Doe\\proj"
    escaped = json.dumps(f"See {root}/items/reqs.yaml: values")
    assert "\\\\" in escaped, "the emitter must double the backslashes to pin the bug"
    assert api_mod._relative_paths_in_text(escaped, root) == '"See items/reqs.yaml: values"'


def test_the_helper_scrubs_file_uris_under_the_root():
    assert (
        api_mod._relative_paths_in_text(
            "See file:///home/user/project/items/a.md", "/home/user/project"
        )
        == "See items/a.md"
    )
    root = "C:\\Users\\Jane Doe\\proj"
    assert (
        api_mod._relative_paths_in_text(
            "open file:///C:/Users/Jane Doe/proj/items/a.md:2", root
        )
        == "open items/a.md:2"
    )
    assert api_mod._relative_paths_in_text("open file:///home/you/proj", "/home/you/proj") == (
        "open ."
    )


def test_the_scrubber_reduces_file_uris_outside_the_root():
    assert (
        api_mod._relative_paths_in_text("read file:///etc/private/secret.md:4", "/home/you/proj")
        == "read secret.md:4"
    )
    assert (
        api_mod._relative_paths_in_text("read file:///C:/Users/x/out.txt", "/home/you/proj")
        == "read out.txt"
    )
    # an ordinary URL keeps passing through untouched:
    assert (
        api_mod._relative_paths_in_text("spec: http://example.com/a/b", "/home/you/proj")
        == "spec: http://example.com/a/b"
    )


def test_an_outside_path_with_spaces_reduces_to_the_leaf():
    # The round-4 escalation: the scanner reads a quoted scalar whole, so
    # spaces inside it are part of the path; an unquoted token extends over
    # a space only when the next piece is unambiguously path-shaped (a
    # separator, an extension). The grammar limit of that rule is pinned
    # beside it: prose that merely contains a separator is not swallowed.
    assert (
        api_mod._relative_paths_in_text('"/etc/my conf/secret.md"', "/home/you/proj")
        == '"secret.md"'
    )
    assert (
        api_mod._relative_paths_in_text("read /etc/my conf/secret.md", "/home/you/proj")
        == "read secret.md"
    )
    assert (
        api_mod._relative_paths_in_text("read /etc/my config", "/home/you/proj")
        == "read my config"
    )


def test_the_root_as_a_prefix_of_a_longer_directory_name_is_not_matched():
    assert (
        api_mod._relative_paths_in_text("see /home/you/project/items/a.md", "/home/you/proj")
        == "see a.md"
    )


def test_the_helper_matches_the_windows_root_at_any_casing():
    # The plugin review (chunk-2): the direct Windows helper cases used the
    # SAME casing for root and text, so a drive letter cased the other way,
    # a directory cased the other way, or both, could regress while every
    # suite stayed green. The drive-letter rule promises a case-insensitive
    # match; pin it in all three spellings.
    root = "C:\\Users\\Jane Doe\\Proj"
    assert (
        api_mod._relative_paths_in_text("see c:/users/jane doe/proj/items/x.yaml:4", root)
        == "see items/x.yaml:4"
    )
    assert (
        api_mod._relative_paths_in_text("see C:/USERS/JANE DOE/PROJ\\items\\x.yaml", root)
        == "see items\\x.yaml"
    )  # continuation as written (round-4 design)
    escaped = json.dumps("see c:\\users\\jane doe\\proj/items/x.yaml:2")
    assert api_mod._relative_paths_in_text(escaped, root) == '"see items/x.yaml:2"'


def test_the_helper_reduces_absolute_paths_outside_the_root_to_their_names():
    # The plugin review (chunk-2): the ticket requires an absolute path NOT
    # under the root to lose its directories; pin the documented choice
    # (bare file name, `<outside project>` when there is none) for both
    # path shapes, the Windows one through the helper's drive-letter rule,
    # and the space case (pinned with its grammar in the leaf test above).
    root = "/home/you/proj"
    assert (
        api_mod._relative_paths_in_text("base /etc/refdes/base.yaml:9", root)
        == "base base.yaml:9"
    )
    assert (
        api_mod._relative_paths_in_text("base D:\\Data\\export.csv", root) == "base export.csv"
    )
    assert (
        api_mod._relative_paths_in_text("rooted at / for now", root)
        == "rooted at <outside project> for now"
    )
    assert (
        api_mod._relative_paths_in_text("read /etc/my conf/secret.md", root) == "read secret.md"
    )


def test_a_root_with_spaces_end_to_end(tmp_path):
    """The reviewer's scenario on the real filesystem: a project whose root
    contains a space, driven through the write routes. Today the applied
    `message`/`describe` carry `my project/items/reqs.yaml:6` -- a fragment
    of the root served as if it were the project-relative path, which is
    also WRONG as a path (the real relative path is `items/reqs.yaml:6`)."""
    spaced = tmp_path / "my project"
    spaced.mkdir()
    client, root = keyless_client(spaced)
    _status, view = client.get("/api/item/REQ-001")
    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 200, payload
    assert payload["path"] == "items/reqs.yaml"
    assert "my project/" not in payload["message"], payload["message"]
    assert not any("my project/" in text for text in strings_of(payload)), payload
    assert_no_root(payload, root, "spaced-root 200")


# ------------------------------------------- round 4: nothing after the root
#
# The plugin review (round 4, chunks 1+2): the first pass swallowed the
# whole whitespace-separated run following the root and re-emitted it with
# separator runs collapsed -- so `https://example.com/a//b` lost a slash,
# an outside `file:///etc/private/...` kept its directories (the leak the
# ticket forbids), and a `file://<root>/...` pasted after an under-root
# path re-emitted `file:/home/...`: the ROOT itself, in `current_text` and
# `diff`. The fix consumes ONLY the root and the separator run that follows
# it; the rest of the text is left exactly as written. (The round-4
# escalation below replaced the token pass with the span scanner; this
# section pins the boundary grammar and URI reduction both algorithms
# share.)


def test_a_pasted_file_uri_after_a_path_leaves_no_root_in_the_409(tmp_path):
    """The reviewer's HIGH reproducer, end to end: a project file whose
    text is an under-root path followed by a `file://` URI naming the root
    again. The continuation-swallowing first pass turned the URI into
    `file:/tmp/.../secret/x.md:4` -- the absolute project root in the 409
    `current_text` and `diff`, exactly the leak the ticket forbids."""
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    text = f"See {reqs_file(root)} then file://{root}/secret/x.md:4"
    status, payload = save(
        client,
        "REQ-001",
        field="text",
        value=text,
        revision=view["edit"]["file_revision"],
    )
    assert status == 200, payload
    status, payload, _stale = _stale_save(
        client, root, "REQ-001", field="text", value=text + " edited"
    )
    assert status == 409, payload
    assert_no_root(payload, root, "409: file:// URI naming the root after a path")


def test_the_text_after_a_scrubbed_path_is_left_exactly_as_written():
    """The reviewer's MEDIUM reproducer: prose and URLs after a scrubbed
    path are non-path text. The double slash of `https://` survives, and
    an outside `file://` path reaches the token pass whole and reduces to
    its file name -- not to `file:/etc/private/secret.md:4`."""
    root = "/home/you/proj"
    assert (
        api_mod._relative_paths_in_text(
            "saved /home/you/proj/items/a.md then https://example.com/a//b", root
        )
        == "saved items/a.md then https://example.com/a//b"
    )
    assert (
        api_mod._relative_paths_in_text(
            "saved /home/you/proj/items/a.md then file:///etc/private/secret.md:4",
            root,
        )
        == "saved items/a.md then secret.md:4"
    )


def test_a_root_at_punctuation_scrubs_whole_and_a_prefixed_sibling_not_at_all():
    """The reviewer's LOW: the bare-root boundary was both under- and
    over-inclusive. Missing `!`, `?`, `:` meant a space-bearing root
    before one of them leaked its tail (the token pass stops at the
    space). Including `.` meant a sibling sharing the root plus a dot
    (`/home/you/proj.old/items/a.md`) was scrubbed to `..old/items/a.md`
    instead of its file name, and a sentence-ending root became `..`."""
    spaced = "C:\\Users\\Jane Doe\\Proj"
    assert (
        api_mod._relative_paths_in_text("root is C:\\Users\\Jane Doe\\Proj! done", spaced)
        == "root is .! done"
    )
    assert (
        api_mod._relative_paths_in_text("root C:\\Users\\Jane Doe\\Proj? yes", spaced)
        == "root .? yes"
    )
    assert (
        api_mod._relative_paths_in_text("at C:\\Users\\Jane Doe\\Proj:6", spaced) == "at .:6"
    )
    assert (
        api_mod._relative_paths_in_text(
            "see /home/you/proj.old/items/a.md", "/home/you/proj"
        )
        == "see a.md"
    )
    assert (
        api_mod._relative_paths_in_text("see /home/you/proj.md", "/home/you/proj")
        == "see proj.md"
    )
    assert (
        api_mod._relative_paths_in_text("locked: /home/you/proj. ok", "/home/you/proj")
        == "locked: . ok"
    )


# ------------------------------------------- round 4 escalation: probe cells
#
# The deep analysis of `5cf61a2` (`.scratch/analysis/deep-analysis-pr372.md`)
# enumerated the whole contract surface as probe cells; the mandated fix is
# ONE span scanner -- quoted scalar spans first, `file:` URIs next, bare
# absolute spans last -- each classified by the literal root pattern, with
# replacement text never re-scanned. The cells below pin the report's
# golden strings. Its EXT cells (`file:/` single-slash and `FILE://` on a
# posix root, the `file://localhost` authority, `%20`/long-path aliases,
# 8.3 names, dot-segment canonicalization) stay documented grammar limits,
# as do the POLICY rows: the scanner is a grammar, never an intent
# detector.

P = "/home/you/proj"
SPACED = "/home/you/my project"
DRIVE = "C:/Users/Jane Doe/Proj"
UNC = "//server/share/proj"
LONG = "//?/C:/Users/x/proj"

PROBE_ROOTS = [
    ("posix", P),
    ("space", SPACED),
    ("drive", DRIVE),
    ("unc", UNC),
    ("long", LONG),
]


@pytest.mark.parametrize(
    "kind,root,spelling,tail,expected",
    [
        pytest.param(
            kind, root, root.replace("/", sep), tail, out, id=f"{kind}-{sep_name}-{tail_name}"
        )
        for (kind, root), (sep_name, sep), (tail_name, tail, out) in product(
            PROBE_ROOTS,
            [("slash", "/"), ("backslash", "\\"), ("escaped", "\\\\")],
            [
                ("child", "/items/a.md:6:2", "items/a.md:6:2"),
                ("bare", "", "."),
                ("trailing", "/", "."),
            ],
        )
    ],
)
def test_response_paths_root_spellings(kind, root, spelling, tail, expected):
    assert api_mod._relative_paths_in_text(spelling + tail, root) == expected


@pytest.mark.parametrize(
    "end,expected",
    [(end, "at ." + ("" if end == "." else end)) for end in
     [".", "!", "?", ":", ",", ";", ")", "]", "}", "'", '"', "`", ">", "\n", ":6", ":6:2"]],
)
@pytest.mark.parametrize("root", [P, SPACED], ids=["plain", "space"])
def test_response_paths_root_terminators(root, end, expected):
    # A root ending a sentence keeps ONE period; `:6`/`:6:2` ride along
    # whole; every declared boundary punctuation survives the scrub.
    assert api_mod._relative_paths_in_text("at " + root + end, root) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        (P + ".old", "proj.old"),
        (P + "2/a.md", "a.md"),
    ],
    ids=["prefix-dot", "prefix-alpha"],
)
def test_response_paths_component_boundary(text, expected):
    # Siblings that share the root as a string prefix are OUTSIDE paths,
    # never the root with a suffix of dots or digits.
    assert api_mod._relative_paths_in_text(text, P) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        (P + "/a.md see https://example.org/a/b", "a.md see https://example.org/a/b"),
        (P + "/a.md then /etc/private/b.md", "a.md then b.md"),
        (P + "/a.md then D:\\private\\b.md", "a.md then b.md"),
        (P + "/a.md then relative\\name", "a.md then relative\\name"),
        (P + "/a.md and " + P + "/b.md", "a.md and b.md"),
        (P + " https://example.org/a/b", ". https://example.org/a/b"),
        (P + " /etc/private/a.md", ". a.md"),
    ],
)
def test_response_paths_continuation_is_untouched(text, expected):
    assert api_mod._relative_paths_in_text(text, P) == expected


@pytest.mark.parametrize(
    "root",
    ['/home/you/my"project', "/home/you/my\nproject", "/home/you/my\tproject"],
    ids=["quote", "newline", "tab"],
)
def test_response_paths_serialized_escapes(root):
    # The patcher quotes through `json.dumps`, so a root with a quote,
    # newline, or tab reaches the response as an escaped scalar; the
    # scalar decodes, the path inside it scrubs, the scalar re-encodes
    # with its full relative subdirectories.
    text = json.dumps(root + "/items/a.md", ensure_ascii=False)
    assert api_mod._relative_paths_in_text(text, root) == '"items/a.md"'


def test_response_paths_escaped_spans_keep_their_syntax():
    assert api_mod._relative_paths_in_text('"' + P + '/a.md\\nnext"', P) == '"a.md\\nnext"'
    assert api_mod._relative_paths_in_text('"' + P + '/a.md\\" end"', P) == '"a.md\\" end"'


@pytest.mark.parametrize(
    "text,expected",
    [
        ('"/etc/my conf/secret.md"', '"secret.md"'),
        ('"D:\\Jane Doe\\private\\a.md"', '"a.md"'),
        ("/etc/my conf/secret.md", "secret.md"),
        ("\\\\server\\share\\private\\a.md", "a.md"),
        ("/etc/private/a.md:6:2", "a.md:6:2"),
        ("/", "<outside project>"),
    ],
)
def test_response_paths_outside_paths_lose_every_directory(text, expected):
    assert api_mod._relative_paths_in_text(text, P) == expected


@pytest.mark.parametrize("root", [P, SPACED], ids=["plain", "space"])
@pytest.mark.parametrize("variant", ["mixed", "runs"])
def test_response_paths_spaced_mixed_separators(root, variant):
    path = (
        root.replace("/you/", "\\you/") if variant == "mixed" else root.replace("/you/", "//you/")
    )
    assert api_mod._relative_paths_in_text(path + "/items/a.md", root) == "items/a.md"


@pytest.mark.parametrize(
    "component",
    ["(draft)", "[draft]", "{draft}", "a,b", "a;b", "a'b", "my draft"],
    ids=["parentheses", "brackets", "braces", "comma", "semicolon", "apostrophe", "space"],
)
def test_response_paths_quoted_child_components(component):
    # The whole relative path survives -- a punctuation-laden child name
    # must not split the path so far that the scanner mistakes `/sub/a.md`
    # for an outside path and eats `/sub/`.
    text = '"' + P + "/items/" + component + '/sub/a.md"'
    assert api_mod._relative_paths_in_text(text, P) == '"items/' + component + '/sub/a.md"'


@pytest.mark.parametrize(
    "prefix,root",
    [("file://", P), ("file:///", P), ("file://", DRIVE), ("file:///", DRIVE)],
)
def test_response_paths_file_uri_variants(prefix, root):
    assert api_mod._relative_paths_in_text(prefix + root + "/items/a.md", root) == "items/a.md"


@pytest.mark.parametrize("status", [200, 400, 403, 409, 422])
@pytest.mark.parametrize("field", ["message", "reason", "describe", "diff", "current_text",
                                   "diagnostics"])
def test_response_paths_all_payload_roles(status, field):
    app = SimpleNamespace(
        state=SimpleNamespace(snapshot=SimpleNamespace(project=SimpleNamespace(root=P)))
    )
    if field == "diagnostics":
        payload = {field: [{"message": P + "/items/a.md:6", "file": P + "/items/a.md"}]}
        expected = {field: [{"message": "items/a.md:6", "file": "items/a.md"}]}
    else:
        payload = {field: "at " + P + "/items/a.md:6"}
        expected = {field: "at items/a.md:6"}
    assert api_mod._write_outcome(app, (status, payload)) == (status, expected)


def test_response_paths_recursive_shapes_and_key_collisions():
    got = api_mod._relative_paths({P + "/a.md": [P + "/b.md", (P + "/c.md", None, 1, False)]}, P)
    assert got == {"a.md": ["b.md", ("c.md", None, 1, False)]}
    # Scrubbed keys that collide take a `#2`/`#3` suffix: the walk never
    # loses a record of the payload.
    assert api_mod._relative_paths({P + "/a.md": 1, "a.md": 2}, P) == {
        "a.md": 1,
        "a.md#2": 2,
    }
    assert api_mod._relative_paths(
        {P + "/a.md": 1, "\\home\\you\\proj\\a.md": 2, "a.md": 3}, P
    ) == {"a.md": 1, "a.md#2": 2, "a.md#3": 3}


def test_response_paths_urls_and_relative_text_are_never_paths():
    for text in [
        "items/a.md:6 and/or 5/6 path/to/x",
        "https://example.org/a/b?q=yes",
        "https://example.org" + P + "/a.md",
        "prefix" + P + "/a.md",
    ]:
        assert api_mod._relative_paths_in_text(text, P) == text


def test_response_paths_documented_ambiguity_limits():
    # The S12 boundary, pinned as chosen grammar: a bare token that reads
    # as a path is scrubbed as one (a switch is a path; there is no intent
    # detector), a POSIX filename containing a backslash under the root
    # keeps its spelling, and an unquoted outside token crosses a space
    # only when the next piece is path-shaped.
    assert api_mod._relative_paths_in_text("pattern /a+/g", P) == "pattern g"
    assert api_mod._relative_paths_in_text("use /verbose", P) == "use verbose"
    assert api_mod._relative_paths_in_text(P + "/a\\b.md", P) == "a\\b.md"
    assert api_mod._relative_paths_in_text("read /etc/my config", P) == "read my config"


def test_response_paths_conflict_preserves_quoted_source(tmp_path):
    """Escaped scalars, quote pairs, URLs and file URIs in one source line,
    on a real 409: every non-path byte (backslashes, escapes, double
    slashes) comes back as written; only the paths are rewritten."""
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    text = (
        f"See {reqs_file(root)}\\nthen \"quoted\" and https://example.org/a//b "
        f"then file://{root}/secret/x.md:4"
    )
    status, payload = save(
        client, "REQ-001", field="text", value=text, revision=view["edit"]["file_revision"]
    )
    assert status == 200, payload
    status, payload, _stale = _stale_save(
        client, root, "REQ-001", field="text", value=text + " edited"
    )
    assert status == 409, payload
    assert_no_root(payload, root, "409: escaped and URL text survives scrubbing")
    assert "See items/reqs.yaml" in payload["current_text"], payload["current_text"]
    assert "https://example.org/a//b" in payload["current_text"], payload["current_text"]
    assert 'secret/x.md:4' in payload["current_text"], payload["current_text"]
