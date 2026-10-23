"""The editor's write route must save through a keyless item's provisional
handle `~<relpath>:<line>` (f13-2).

In a project where surrogate keys were never minted (a fresh `refdes init`
plus one item, where only `refdes serve` has run -- serve writes nothing),
the list route hands out the keyless handle `~items/REQ-001.md:2`, the read
route resolves it, and the browser editor posts exactly that handle back to
`POST /api/item/<handle>/edit` (serve/static/editor.js:234). Today the write
route resolves the handle at the model (so the find succeeds) and then hands
the raw `~` spelling to the patcher, whose aliases are only the `id:`/`key:`
values -- so EVERY editor save in such a project answers 422
`refused: no item '~items/reqs.yaml:4' in this file (it holds: REQ-001)`.

This is the third spelling of the same bug class as EDIT-01 (the editor
accepts the key handle) and EDIT-03 (the edit route resolves retired ids
like the read route): item identity has spellings -- display id, surrogate
key, and, for a keyless item, the `project.items` dict key -- and every route
that takes one must take all of them.

Contract the fix commits to:

- a save through the keyless handle succeeds exactly as a save through the
  display id does, for each item shape the patcher supports (tested here:
  yaml list item, md-front-matter item): same bytes on disk, same patch
  description, same response shape;
- the handle's `<relpath>:<line>` is still validated, never guessed: a
  handle whose line does not point at that item's definition (stale after
  the file changed), a handle naming a line that is no item's definition,
  and a handle naming a line in a file that holds no item there must all
  refuse and write nothing (today's refusal, kept);
- display-id and key handles keep saving; the list/read routes' handle
  minting is unchanged;
- the 200 payload reports the same handle the read route reports for the
  same ref (the browser's ref needs no correction).

The drive layer is `api.handle` itself -- the exact handler the socket layer
dispatches to, the exact (status, JSON payload) contract the browser
consumes, the same real `ProjectState` with the same post-save refresh
(following `test_serve_edit_retired_ids.py`, the EDIT-03 module: a route's
identity resolution must be gradeable on a box with no spare threads for a
live server -- RLIMIT_NPROC/pids.max -- and the direct drives need none).
What it leaves out is the transport -- the socket, the token, the origin gate
-- which `test_serve_edit_http` pins; every path in this module posts the
handle URL-encoded exactly as editor.js:234 does (`encodeURIComponent`), and
every assertion is a status code, a payload field, or file bytes.

The fixtures are the shared ones: `make_project(mint_keys=False)` is the
contract's scenario (keys never minted, rows carry the `~` handle), and
`make_project(mint_keys=True)` is the keyed control.
"""

from __future__ import annotations

import hashlib
from urllib.parse import quote

from serve_support import make_project, snapshot_tree

from refdes.serve import api as api_mod
from refdes.serve import state as state_mod


class Api:
    """A thread-free drive of the API routes: the real `ProjectState`, the
    real `api.handle`, the same (status, payload) the socket layer returns.

    The gates the transport owns -- token, origin, --no-write -- are pinned
    over the real socket in test_serve_edit_http; `read_only` here only
    needs to reach the route's own check, which reads the same attribute the
    server sets.
    """

    def __init__(self, root, read_only: bool = False):
        self.state = state_mod.ProjectState(str(root / "refdes-project.yaml"))
        self.state.load()
        self.read_only = read_only

    def get(self, path: str):
        return api_mod.handle(self, "GET", path, {}, None)

    def post(self, path: str, payload):
        return api_mod.handle(self, "POST", path, {}, payload)


def keyless_root(tmp_path):
    """The contract's scenario: keys were never minted (no writable check
    ever ran); `serve` writes nothing, so the rows carry the keyless
    provisional handle."""
    make_project(tmp_path, mint_keys=False)
    return tmp_path


def sha256(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read(path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def reqs_file(root) -> str:
    return str(root / "items" / "reqs.yaml")


def scrub(obj, root):
    """Replace every string mention of `root` with `<root>`, recursively.

    The plan's `describe()` (and the `message` that embeds it) quotes the
    target file's absolute path (patcher.py:118), and the two projects of
    the equivalence test live in sibling directories under tmp_path -- so
    the root is the one difference the payloads are ALLOWED to carry. The
    scrub covers the native spelling and the slash-normalized one the
    server's `shown()` emits (the Windows trap), and walks every string in
    the payload so a path in any other field -- a diagnostic's `file`, say
    -- is normalized the same way and cannot leak past the comparison.
    """
    native = str(root)
    slashed = native.replace("\\", "/")

    def walk(value):
        if isinstance(value, str):
            return value.replace(native, "<root>").replace(slashed, "<root>")
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value

    return walk(obj)


def notes_file(root) -> str:
    return str(root / "items" / "notes.md")


def row_handle(client, item_id) -> str:
    """The handle the list route hands out -- exactly what the browser's row
    carries and what the editor posts back."""
    status, listing = client.get("/api/items")
    assert status == 200, listing
    return next(row["handle"] for row in listing["items"] if row["id"] == item_id)


def save(client, ref, *, field="status", value="draft", revision):
    """`POST /api/item/<ref>/edit` with the handle URL-encoded exactly the
    way the browser encodes it (editor.js:234 uses encodeURIComponent); the
    route unquotes, so this is the same ref the browser's fetch sends."""
    return client.post(
        f"/api/item/{quote(ref, safe='')}/edit",
        {"op": "set_field", "field": field, "value": value, "expected_revision": revision},
    )


# ------------------------------------------------- the handle the browser holds


def test_the_row_handle_of_a_keyless_item_is_the_provisional_handle(tmp_path):
    """Minting control: the list route hands the keyless row its `~` handle,
    and the read route answers it -- both unchanged by this task, and they
    are what makes the editor post it back."""
    client = Api(keyless_root(tmp_path))
    handle = row_handle(client, "REQ-001")
    assert handle.startswith("~items/reqs.yaml:"), handle

    status, item = client.get(f"/api/item/{quote(handle, safe='')}")
    assert status == 200, item
    assert item["id"] == "REQ-001"
    assert item["handle"] == handle
    # a GET by the display id reports the display id: nothing about
    # minting moves
    _status, by_id = client.get("/api/item/REQ-001")
    assert _status == 200 and by_id["handle"] == "REQ-001"


# ------------------------------------------------------------- the bug, verbatim


def test_saving_through_the_keyless_handle_lands_on_the_yaml_item(tmp_path):
    """The yaml-list-item shape, end to end: the save resolves the handle
    (200 applied, not the 422 "in this file" refusal), lands inside REQ-001's
    own span, and the save does not mint a key on the side."""
    root = keyless_root(tmp_path)
    client = Api(root)
    handle = row_handle(client, "REQ-001")
    _status, view = client.get(f"/api/item/{quote(handle, safe='')}")
    assert _status == 200 and view["edit"]["editable"] is True

    def block_of(text, item_id):
        return text.split(f"- id: {item_id}", 1)[1].split("- id:", 1)[0]

    text_before = read(reqs_file(root))
    req002_before = block_of(text_before, "REQ-002")

    status, payload = save(
        client, handle, value="draft", revision=view["edit"]["file_revision"]
    )
    assert status == 200, payload
    assert payload["kind"] == "applied" and payload["ok"] is True
    assert payload["id"] == "REQ-001"
    # the response reports the handle the read route reports for this
    # same ref: the browser's ref needs no correction
    assert payload["handle"] == view["handle"]
    assert payload["describe"].startswith("yaml-item REQ-001:")

    text = read(reqs_file(root))
    assert "status: draft" in block_of(text, "REQ-001"), (
        "the edit landed inside REQ-001's own block"
    )
    assert block_of(text, "REQ-002") == req002_before, (
        "REQ-002's block is byte-for-byte untouched"
    )
    assert "# Requirements for the project" in text
    assert "# trailing comment" in text
    assert "key:" not in text, "a save does not mint a key"


def test_saving_through_the_keyless_handle_lands_on_the_markdown_item(tmp_path):
    """The md-front-matter shape: REQ-010 lives in items/notes.md and its
    row carries `~items/notes.md:<line>`; a save through it rewrites the
    front-matter field and leaves the body prose standing."""
    root = keyless_root(tmp_path)
    client = Api(root)
    handle = row_handle(client, "REQ-010")
    assert handle.startswith("~items/notes.md:"), handle
    _status, view = client.get(f"/api/item/{quote(handle, safe='')}")
    assert _status == 200 and view["edit"]["editable"] is True

    status, payload = save(
        client,
        handle,
        field="text",
        value="A rewritten markdown requirement.",
        revision=view["edit"]["file_revision"],
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert payload["id"] == "REQ-010"
    assert payload["describe"].startswith("md-front-matter REQ-010:")

    text = read(notes_file(root))
    assert "text: A rewritten markdown requirement." in text
    assert "id: REQ-010" in text
    assert "Body prose before a rule." in text, "the body prose survives"


def test_the_keyless_handle_save_matches_the_display_id_save(tmp_path):
    """The equivalence clause, verbatim: saving the same item with the same
    op through the keyless handle and through the display id (in two
    byte-identical projects) produces byte-identical files and identical
    responses -- same patch (`describe`), same new revision, same shape.

    `handle` is the one response field allowed to differ, and it must not
    differ by more than the read route itself differs on the two spellings:
    each response reports exactly what GET of its own ref reports."""
    roots = {}
    payloads = {}
    for name, ref_mode in (("by-id", "id"), ("by-handle", "handle")):
        root = tmp_path / name
        root.mkdir()
        keyless_root(root)
        client = Api(root)
        ref = "REQ-001" if ref_mode == "id" else row_handle(client, "REQ-001")
        _status, view = client.get(f"/api/item/{quote(ref, safe='')}")
        assert _status == 200
        status, payload = save(
            client, ref, value="draft", revision=view["edit"]["file_revision"]
        )
        assert status == 200, (ref_mode, payload)
        payload["posted_ref"] = ref
        payload["reported_for_ref"] = view["handle"]
        payloads[name] = payload
        roots[name] = root

    by_id = scrub(payloads["by-id"], roots["by-id"])
    by_handle = scrub(payloads["by-handle"], roots["by-handle"])
    assert set(by_id) == set(by_handle), "same response shape"
    for key in set(by_id) - {"handle", "posted_ref", "reported_for_ref"}:
        assert by_id[key] == by_handle[key], f"`{key}` differs: {by_id[key]!r} vs {by_handle[key]!r}"
    assert by_id["revision"] == by_handle["revision"]
    assert by_id["describe"] == by_handle["describe"], "same patch"
    # each response reports what the read route reports for the ref it saved
    assert by_id["handle"] == by_id["reported_for_ref"] == "REQ-001"
    assert by_handle["posted_ref"] == by_handle["reported_for_ref"]
    assert by_handle["handle"] == by_handle["posted_ref"], (
        "the save reports the row's own keyless handle, not a renamed spelling"
    )
    assert read(reqs_file(roots["by-id"])) == read(reqs_file(roots["by-handle"])), (
        "same bytes on disk"
    )


# ------------------------------------------------ the handle stays validated


def test_a_stale_keyless_handle_refuses_without_touching_the_file(tmp_path):
    """The handle's line is a claim about the file, and a stale claim must
    not be guessed. Insert two lines at the top of reqs.yaml: the handle
    `~items/reqs.yaml:<line-of-REQ-002>` now names a line inside REQ-001's
    block -- not REQ-002's definition. Saving with a revision that matches
    the file exactly (so the revision gate passes) must refuse and write
    nothing -- neither REQ-002 (whose id a fix might translate to, ignoring
    the line) nor REQ-001 (whose span the line now falls inside) may absorb
    the write."""
    root = keyless_root(tmp_path)
    client = Api(root)
    handle = row_handle(client, "REQ-002")
    assert handle.startswith("~items/reqs.yaml:")

    path = reqs_file(root)
    shifted = "# inserted line\n# and another\n" + read(path)
    with open(path, "wb") as fh:
        fh.write(shifted.encode("utf-8"))
    after_shift = snapshot_tree(root)

    status, payload = save(
        client, handle, field="text", value="x", revision=sha256(path)
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "no item" in payload["reason"], payload
    assert snapshot_tree(root) == after_shift, "the stale handle writes nothing"


def test_a_keyless_handle_naming_a_line_that_is_not_an_item_definition_refuses(tmp_path):
    """A hand-built handle naming a real file and a line that is no item's
    definition (the header comment) must refuse and write nothing."""
    root = keyless_root(tmp_path)
    client = Api(root)
    before_tree = snapshot_tree(root)
    status, payload = save(
        client,
        "~items/reqs.yaml:1",
        field="text",
        value="x",
        revision=sha256(reqs_file(root)),
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "no item" in payload["reason"], payload
    assert snapshot_tree(root) == before_tree


def test_a_keyless_handle_naming_a_line_in_another_file_refuses(tmp_path):
    """A handle's file is part of its identity: REQ-002's line number in
    reqs.yaml is a body line in notes.md, where no item is defined. A fix
    that matched by line alone (searching files for the number) would patch
    REQ-002 through the notes.md spelling; the correct posture is the
    ordinary refusal, with nothing written."""
    root = keyless_root(tmp_path)
    client = Api(root)
    reqs_handle = row_handle(client, "REQ-002")
    line = reqs_handle.rsplit(":", 1)[1]
    assert line.isdigit()

    before_tree = snapshot_tree(root)
    status, payload = save(
        client,
        f"~items/notes.md:{line}",
        field="text",
        value="x",
        revision=sha256(notes_file(root)),
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "no item" in payload["reason"], payload
    assert snapshot_tree(root) == before_tree


# ------------------------------------------------------------------ the spine
#
# The two live spellings keep saving (the same save the keyless handle must
# now match), and the keyless handle's conflict keeps its diff.


def test_the_display_id_save_still_saves_on_the_keyless_project(tmp_path):
    root = keyless_root(tmp_path)
    client = Api(root)
    status, payload = save(
        client, "REQ-001", value="draft", revision=sha256(reqs_file(root))
    )
    assert status == 200, payload
    assert payload["kind"] == "applied" and payload["id"] == "REQ-001"
    assert "status: draft" in read(reqs_file(root))


def test_the_key_handle_save_still_saves_on_the_keyed_project(tmp_path):
    root = tmp_path
    make_project(root, mint_keys=True)
    client = Api(root)
    handle = row_handle(client, "REQ-001")
    assert handle != "REQ-001" and "-" not in handle, handle
    _status, view = client.get(f"/api/item/{quote(handle, safe='')}")
    assert _status == 200

    status, payload = save(
        client, handle, value="draft", revision=view["edit"]["file_revision"]
    )
    assert status == 200, payload
    assert payload["kind"] == "applied" and payload["id"] == "REQ-001"
    text = read(reqs_file(root))
    assert "status: draft" in text and f"key: {handle}" in text


def test_the_keyless_handle_stale_revision_conflict_keeps_its_diff(tmp_path):
    """A save through the keyless handle with a stale revision is the
    ordinary 409, and -- like the same save through the display id -- it
    comes with the diff: the conflict plans the author's draft, and planning
    against a spelling the file does not hold used to strip the screen of
    its text. The handle's line is still valid here (the file changed within
    its lines), so the plan must resolve it after the fix."""
    root = keyless_root(tmp_path)
    client = Api(root)
    handle = row_handle(client, "REQ-001")
    path = reqs_file(root)
    stale = sha256(path)
    moved = read(path).replace("3.3 V", "5.0 V")
    assert len(moved.splitlines()) == len(read(path).splitlines())
    with open(path, "wb") as fh:
        fh.write(moved.encode("utf-8"))
    before_tree = snapshot_tree(root)

    status, payload = save(client, handle, value="draft", revision=stale)
    assert status == 409, payload
    assert payload["kind"] == "conflict"
    assert payload["current_text"], payload
    assert payload["diff"], payload
    assert "5.0 V" in payload["diff"]
    assert snapshot_tree(root) == before_tree, "a conflict writes nothing"
