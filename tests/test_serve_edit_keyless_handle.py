"""The editor's write route accepts the keyless item's handle (F13-2, EDIT-05).

In a project where surrogate keys were never minted (a fresh `refdes init`
plus `refdes serve`, which writes nothing), `/api/items` rows carry the
provisional `~<relpath>:<line>` dict key as the row `handle`, the read route
resolves it, and `editor.js` posts exactly that spelling to
`POST /api/item/<handle>/edit`. The write route resolved it at the model and
then handed the raw `~`-handle to the patcher, whose aliases are the file's
`id:`/`key:` values -- so every editor save in a keyless project answered 422
`refused: no item '~items/reqs.yaml:4' in this file (it holds: REQ-001)`.

The fix is a translation at the route: the save is planned against the
spelling the file carries -- the key when the item has one, else the display
id. The handle's relpath:line is not trusted past that: it is validated by
the resolution itself, which accepts the handle only by exact dict-key hit
against the tree loaded from disk under the write lock. A stale line (the
file changed, the item moved) and a hand-made handle naming no item both
resolve to nothing and keep the ordinary refusal, patching nothing.

The controls pin the rest of the identity space: the display-id save and the
surrogate-key save keep working, and a conflict under the keyless handle
keeps its diff (the conflict plans the draft against the file spelling, not
the view address).
"""

from __future__ import annotations

import hashlib

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Keyless handle test"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
      status: { type: enum, choices: [draft, approved] }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
"""

REQS = """\
# a comment that must survive every save
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.   # trailing comment
    status: approved
  - id: REQ-002
    text: The board shall boot within 2 s.
"""

DECS = """\
defaults: { type: decision, board: board-a }
items:
  - id: DEC-001
    title: Use the buck regulator.
    satisfies: [REQ-001]
"""

NOTES_MD = """\
---
id: REQ-010
type: requirement
board: board-a
text: A markdown requirement.
---

Body prose that must survive the save.
"""


def make_root(tmp_path, *, mint_keys: bool = False):
    """A keyless project (nothing mints keys) with both patcher item shapes:
    a YAML list item (REQ-001) and a Markdown front-matter item (REQ-010).
    With `mint_keys`, one ordinary writable check mints keys first, so the
    project starts in the keyed state the surrogate-key control needs."""
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in {"reqs.yaml": REQS, "decs.yaml": DECS}.items():
        (items / name).write_text(text, encoding="utf-8", newline="\n")
    (items / "notes.md").write_text(NOTES_MD, encoding="utf-8", newline="\n")
    if mint_keys:
        from refdes import cli as cli_mod

        cli_mod.main(["-c", str(tmp_path / "refdes-project.yaml"), "check"])
    return tmp_path


def start(root, **kw):
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, **kw)
    app.start()
    return app


@pytest.fixture
def served_keyless(tmp_path):
    root = make_root(tmp_path)
    app = start(root)
    try:
        yield app, Client(app), root
    finally:
        app.stop()


@pytest.fixture
def served_keyed(tmp_path):
    root = make_root(tmp_path, mint_keys=True)
    app = start(root)
    try:
        yield app, Client(app), root
    finally:
        app.stop()


def sha256(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read(path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def edit(client, ref: str, *, revision: str, **fields):
    payload = {"op": "set_field", "expected_revision": revision}
    payload.update(fields)
    return client.api_post(f"/api/item/{ref}/edit", payload)


def handle_for(client, item_id: str) -> str:
    """The `handle` the shipped list gives the browser for `item_id` -- the
    exact spelling `editor.js` puts into the edit URL."""
    status, listing = client.api_get("/api/items")
    assert status == 200
    for row in listing["items"]:
        if row["id"] == item_id:
            return row["handle"]
    raise AssertionError(f"no row for {item_id}")


# ------------------------------------------------------------------ the fix


def test_the_keyless_handle_saves_the_yaml_list_item(served_keyless):
    """The exact bug: the row handle of a keyless project's YAML item posts
    the save and it lands -- same patch, same response shape as the id."""
    _app, client, root = served_keyless
    handle = handle_for(client, "REQ-001")
    assert handle.startswith("~items/reqs.yaml:"), handle
    path = str(root / "items" / "reqs.yaml")
    status, payload = edit(
        client, handle, revision=sha256(path), field="status", value="draft"
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert payload["id"] == "REQ-001"
    assert payload["handle"] == handle
    text = read(path)
    assert "status: draft" in text.split("- id: REQ-001", 1)[1].split("- id:", 1)[0]
    assert "The rail shall supply 3.3 V.   # trailing comment" in text
    assert text.startswith("# a comment that must survive every save")


def test_the_keyless_handle_saves_the_md_front_matter_item(served_keyless):
    """The same save through the front-matter shape: REQ-010's row handle is
    `~items/notes.md:<line>`, and saving it must edit the front matter."""
    _app, client, root = served_keyless
    handle = handle_for(client, "REQ-010")
    assert handle.startswith("~items/notes.md:"), handle
    path = str(root / "items" / "notes.md")
    status, payload = edit(
        client,
        handle,
        revision=sha256(path),
        field="text",
        value="The rail shall supply 5 V.",
    )
    assert status == 200, payload
    assert payload["id"] == "REQ-010"
    text = read(path)
    _fence, front, body = text.split("---\n", 2)
    assert "text: The rail shall supply 5 V." in front
    assert "Body prose that must survive the save." in body


# ----------------------------------------------------------------- controls


def test_the_display_id_handle_still_saves(served_keyless):
    _app, client, root = served_keyless
    path = str(root / "items" / "reqs.yaml")
    status, payload = edit(
        client, "REQ-001", revision=sha256(path), field="status", value="draft"
    )
    assert status == 200, payload
    assert payload["id"] == "REQ-001"
    assert payload["handle"] == "REQ-001"
    assert "status: draft" in read(path)


def test_the_key_handle_still_saves(served_keyed):
    _app, client, root = served_keyed
    handle = handle_for(client, "REQ-001")
    assert handle and not handle.startswith("~"), handle
    path = str(root / "items" / "reqs.yaml")
    status, payload = edit(
        client, handle, revision=sha256(path), field="status", value="draft"
    )
    assert status == 200, payload
    assert payload["id"] == "REQ-001"
    assert payload["handle"] == handle
    assert "status: draft" in read(path)


# ------------------------------------------------------------- validation


def test_a_stale_keyless_handle_refuses_and_writes_nothing(served_keyless):
    """A handle whose line no longer names the item's definition resolves to
    nothing on a fresh load -- the ordinary refusal, nothing patched."""
    _app, client, root = served_keyless
    stale = handle_for(client, "REQ-001")
    assert stale.endswith(":4"), stale
    path = str(root / "items" / "reqs.yaml")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# a new header line\n" + read(path))
    client.request("GET", "/api/items")  # the client needs nothing; the
    # write route re-loads from disk under the lock, so no refresh dance:
    # the fresh dict key is `~items/reqs.yaml:5`, the stale `:4` is no
    # item's spelling.
    before = snapshot_tree(root)
    status, payload = edit(
        client, stale, revision=sha256(path), field="status", value="draft"
    )
    assert status == 422 and payload["kind"] == "refused", payload
    assert "no item" in payload["reason"]
    assert snapshot_tree(root) == before


def test_a_keyless_handle_naming_no_item_refuses(served_keyless):
    """A hand-made `~<relpath>:<line>` naming no item's definition resolves
    to nothing on both routes: 404 read, 422 refused write, file untouched."""
    _app, client, root = served_keyless
    forged = "~items/notes.md:99"
    assert client.api_get(f"/api/item/{forged}")[0] == 404
    path = str(root / "items" / "notes.md")
    before = snapshot_tree(root)
    status, payload = edit(
        client, forged, revision=sha256(path), field="text", value="x"
    )
    assert status == 422 and payload["kind"] == "refused", payload
    assert "no item" in payload["reason"]
    assert snapshot_tree(root) == before


def test_a_conflict_under_the_keyless_handle_keeps_its_diff(served_keyless):
    """The keyless save that loses the revision race comes back 409 with the
    current span text and a real diff -- the conflict plans the draft
    against the file spelling (the display id), not the `~` view address."""
    _app, client, root = served_keyless
    handle = handle_for(client, "REQ-001")
    path = str(root / "items" / "reqs.yaml")
    rev0 = sha256(path)
    first, payload = edit(client, handle, revision=rev0, field="status", value="draft")
    assert first == 200, payload
    second, payload = edit(
        client, handle, revision=rev0, field="text", value="Superseded text."
    )
    assert second == 409, payload
    assert payload["kind"] == "conflict"
    assert payload["current_text"]
    assert "REQ-001" in payload["diff"]
    assert "status: draft" in payload["diff"]
    assert "Superseded text." in payload["diff"]
    assert "Superseded text." not in read(path)
