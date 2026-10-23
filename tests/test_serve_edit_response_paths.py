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
from urllib.parse import quote

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
    assert all(set(d) == {"level", "message", "file", "line", "code"} for d in payload["diagnostics"])


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
    status, payload = save(client, "REQ-001", value="banana", revision=view["edit"]["file_revision"])
    assert status == 422 and payload["kind"] == "invalid", payload
    assert payload["diagnostics"], "the gate must say which error it blocked"
    assert_no_root(payload, root, "invalid 422 (message, reason, diagnostics)")


def test_gate_blocked_invalid_response_text_is_unchanged(tmp_path):
    client, root = keyless_client(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    status, payload = save(client, "REQ-001", value="banana", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    blocked = "blocked: the edit would leave 1 error(s): status: 'banana' is not one of draft, approved."
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
        {"op": "set_field", "field": "status", "value": "draft", "expected_revision": sha256(reqs_file(root))},
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


def test_the_helper_relativeizes_the_escaped_spelling_under_a_posix_root():
    # The CI shape: a native-separator root, the value JSON-escaped on the
    # way into the file. On Linux there is nothing to escape (the root
    # already has forward slashes), so the test feeds the helper the
    # escaped spelling of a Windows-shaped root it hands in explicitly.
    root = "C:\\Users\\x\\proj"
    escaped = json.dumps(f"conflict: {root}\\items\\reqs.yaml changed")
    got = api_mod._relative_paths_in_text(escaped, root)
    assert got == '"conflict: items/reqs.yaml changed"', got
    assert "\\\\" not in got and "C:" not in got, got


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
    The payloads are asserted json-serializable, which repacks tuples to
    lists and so proves none survived; the key types are pinned directly."""
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
# The token regex stops at whitespace, so a root containing a space --
# `C:\Users\Jane Doe\...`, `/home/user/my project` -- is common, and real,
# and only half-scrubbed by a token pass: the token ends at the space, the
# under-root test fails, and the fragment up to the space collapses to its
# basename while the rest of the root walks out as prose. A root matched
# LITERALLY has no such problem: spaces inside it are just characters. The
# fix design (reviewer-prescribed): a first pass that replaces the KNOWN
# root literally in every spelling it already normalises -- native
# separators, forward slashes, the JSON-escaped doubling, a drive letter at
# any case, optionally preceded by `file://`/`file:///` -- swallowing the
# separator that follows so `<root>/items/x.yaml:6` becomes
# `items/x.yaml:6` and the bare root becomes `.`. The token pass keeps its
# job for absolute paths NOT under the root (-> bare file name), and gains
# the `file://` prefix there too.


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
    root = "C:\\Users\\Jane Doe\\proj"
    assert (
        api_mod._relative_paths_in_text(
            "at C:\\Users\\Jane Doe\\proj\\items\\a.md:3 now", root
        )
        == "at items/a.md:3 now"
    )
    assert (
        api_mod._relative_paths_in_text("at c:\\users\\jane doe\\PROJ\\items\\a.md now", root)
        == "at items/a.md now"
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


def test_the_token_pass_scrubs_file_uris_outside_the_root():
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


def test_an_outside_root_path_with_spaces_keeps_the_token_pass_partial():
    # Pinned as a documented limit of the design (chunk-3 review): the token
    # pass cannot know where a path with spaces ends, and the literal pass
    # can only match the KNOWN root. The leak this protects is the project
    # root, which is scrubbed in every spelling; an outside path with spaces
    # reduces by its first token, and the remaining prose is unchanged.
    assert (
        api_mod._relative_paths_in_text("read /etc/my conf/secret.md", "/home/you/proj")
        == "read my conf/secret.md"
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
        == "see items/x.yaml"
    )
    escaped = json.dumps("see c:\\users\\jane doe\\proj/items/x.yaml:2")
    assert api_mod._relative_paths_in_text(escaped, root) == '"see items/x.yaml:2"'


def test_the_helper_reduces_absolute_paths_outside_the_root_to_their_names():
    # The plugin review (chunk-2): the ticket requires an absolute path NOT
    # under the root to lose its directories; pin the documented choice
    # (bare file name, `<outside project>` when there is none) for both
    # path shapes, the Windows one through the helper's drive-letter rule,
    # and the space case as the partial tokenization it is (pinned with its
    # reasoning in the documented-limit test above).
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
        api_mod._relative_paths_in_text("read /etc/my conf/secret.md", root)
        == "read my conf/secret.md"
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
