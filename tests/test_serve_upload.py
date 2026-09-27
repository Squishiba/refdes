"""`POST /api/assets` -- Phase 1 "Bytes", Phase 2 "Conflicts" and Phase 3
"Seals" (docs/design/editor-image-upload.md §17).

The claims pinned here are the ones those two slices are scoped by:

* the bytes land where the request said they land -- the item's own source
  directory by default, an explicit project-relative `dest` on request -- and
  both halves of that path are validated on their own (§5), never a joined
  client path;
* the type is read from the bytes (§6). The extension has to agree with the
  signature, the client's `Content-Type` decides nothing, and SVG is refused
  because the only thing between an uploaded SVG and a same-origin script is a
  header;
* the §5 collision table, all four rows: absent writes, identical bytes are a
  no-op rather than a conflict, different bytes refuse naming path + size +
  hash, and a case-only collision refuses;
* `expected_hash`, the binary `expected_revision` (§8): it confirms a specific
  version and replaces through `_atomic_replace`; a hash that no longer matches
  refuses and hands back the *current* one; a hash for a file that is gone
  refuses rather than quietly becoming a create;
* the three checks against *other* documents (§9), which are the hole Phase 1
  shipped open: a write that would make an unrelated document's bare reference
  ambiguous refuses (§9.1), a write that would silently re-point another item's
  existing bare-name reference refuses (§9.2), and a replace discloses every
  item currently showing the file, before the author confirms it (§9.3);
* the write is a create that must not exist (`_atomic_create`) or a replace
  that re-reads and compares (`_atomic_replace`), so a raced destination is
  refused rather than clobbered, a failed verification restores the original
  bytes, and no temp file survives;
* the size cap is enforced twice, against `Content-Length` before a byte is
  read and against the bytes in hand (§6);
* the existing gate still applies -- token, `Origin`, Host, the content-type
  allowlist, `--no-write`;
* and the endpoint writes bytes only. It never touches a `.md` or `.yaml`, and
  the reference reaches disk through the ordinary `set_body` save (§7).

* the two §10 seal refusals, both decided before any byte is written: an upload
  *for* a sealed entry refuses outright (its body save is refused too, so the
  bytes could only be an orphan), and a file a sealed entry references cannot be
  replaced or created from here -- a seal hashes the body text, which holds the
  path, not the bytes. No `expected_hash` buys either write back; identical
  bytes, which change nothing, stay the §5 no-op they were.

Not here: the client (Phase 4) or the docs pass (Phase 5).
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import urllib.parse

import pytest
from serve_support import Client, make_filter_project, snapshot_tree

from refdes import build as build_mod
from refdes import parse as parse_mod
from refdes import seal as seal_mod
from refdes.schema import load_project
from refdes.serve import edit as edit_mod
from refdes.serve import upload as upload_mod
from refdes.serve.server import MAX_ASSET_BYTES, EditorApp

PNG = b"\x89PNG\r\n\x1a\n" + b"a png, honestly"
JPEG = b"\xff\xd8\xff\xe0" + b"a jpeg, honestly"
GIF = b"GIF89a" + b"a gif, honestly"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 "
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
PHP = b"<?php echo 'pwned'; ?>"

# Two distinguishable versions of one image, for every §8 replace test: the
# file that is there and the bytes that want to replace it.
OLD_CURVE = b"\x89PNG\r\n\x1a\n" + b"the curve as it was shot in March"
NEW_CURVE = b"\x89PNG\r\n\x1a\n" + b"the curve after the fix, longer than before"


def make_upload_project(tmp_path, files: dict[str, bytes] | None = None, *, assets=("figures",)):
    """The shared filter fixture plus the declared `site.assets:` directories
    the image rules are about, so the ambiguity and capture checks have a real
    search path and a real build input to test against. `files` maps a
    project-relative path to its bytes; `assets` is the `site.assets:` list."""
    root = tmp_path
    make_filter_project(root)
    config = root / "refdes-project.yaml"
    for rel_dir in assets:
        (root / rel_dir).mkdir(parents=True, exist_ok=True)
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'site:\n  title: "Filter test"\n',
            'site:\n  title: "Filter test"\n  assets: [' + ", ".join(assets) + "]\n",
        ),
        encoding="utf-8",
    )
    for rel, data in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


# Two items in `items/`, each with a bare `curve.png` in its body that the
# search path resolves to `figures/curve.png` today. That one state is both
# §9.2's capture (uploading `items/curve.png` would re-point both) and §9.3's
# blast radius (replacing `figures/curve.png` changes what both show).
DECS_WITH_IMAGE = """\
defaults: { type: decision, board: board-a, workspace: platform }
items:
  - id: DEC-001
    title: Use the buck regulator.
    status: accepted
    satisfies: [REQ-001]
    body: |
      ![the curve as drawn](curve.png)
"""

TESTS_WITH_IMAGE = """\
defaults: { type: test, board: board-a, workspace: platform }
items:
  - id: TST-001
    title: Measure the rail.
    verifies: [REQ-001]
    body: |
      ![the curve as measured](curve.png)
"""


def make_referencing_project(tmp_path, *, assets=("figures",)):
    """A project whose items already reference a bare image on the search
    path: the state §9.2 and §9.3 are both about."""
    root = make_upload_project(tmp_path, assets=assets)
    (root / "items" / "decs.yaml").write_text(DECS_WITH_IMAGE, encoding="utf-8")
    (root / "items" / "tests.yaml").write_text(TESTS_WITH_IMAGE, encoding="utf-8")
    (root / "figures" / "curve.png").write_bytes(OLD_CURVE)
    return root


def built_project(root):
    """The project as a build leaves it -- the input `store_asset` needs now
    that the §9 checks ask what the *build* resolves. `image_results` is
    recorded by the render pass, so this is load + items + build, the same
    three steps `tests/test_image_hash.py` uses. Writes nothing into the
    project."""
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse_mod.load_items(project)
    build_mod.build(project)
    return project


def _serve(root, *, read_only: bool = False):
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, read_only=read_only)
    app.start()
    return app, Client(app)


@pytest.fixture
def served(tmp_path):
    app, client = _serve(make_upload_project(tmp_path))
    try:
        yield app, client, tmp_path
    finally:
        app.stop()


@pytest.fixture
def referencing(tmp_path):
    """A served project whose items reference a bare `curve.png` that the
    search path resolves to `figures/curve.png` today."""
    app, client = _serve(make_referencing_project(tmp_path))
    try:
        yield app, client, tmp_path
    finally:
        app.stop()


@pytest.fixture
def two_asset_dirs(tmp_path):
    """A served project with two declared `site.assets:` directories and a file
    in the second one: uploading that leaf into the first is §9.1."""
    root = make_upload_project(
        tmp_path,
        {"photos/shared/curve.png": OLD_CURVE},
        assets=("figures", "photos/shared"),
    )
    app, client = _serve(root)
    try:
        yield app, client, tmp_path
    finally:
        app.stop()


def upload(
    client,
    *,
    name: str,
    dest: str | None = None,
    item: str | None = None,
    data: bytes = PNG,
    content_type: str | None = "application/octet-stream",
    token: bool = True,
    origin: bool = True,
    expected_hash: str | None = None,
):
    """One raw-bytes upload (§11): metadata in the query, bytes in the body."""
    params = {"name": name}
    if dest is not None:
        params["dest"] = dest
    if item is not None:
        params["item"] = item
    if expected_hash is not None:
        params["expected_hash"] = expected_hash
    headers = {}
    if content_type is not None:
        headers["Content-Type"] = content_type
    if origin:
        headers["Origin"] = f"http://127.0.0.1:{client.port}"
    status, _headers, body = client.request(
        "POST",
        "/api/assets?" + urllib.parse.urlencode(params),
        token=token,
        body=data,
        headers=headers,
    )
    try:
        return status, json.loads(body)
    except ValueError:
        return status, {"error": body.decode("utf-8", "replace")}


def text_files(root) -> dict[str, str]:
    """Every `.md`/`.yaml` under root, hashed -- the §14 posture for "the upload
    wrote bytes and nothing else"."""
    return {
        rel: digest
        for rel, digest in snapshot_tree(root).items()
        if rel.endswith((".md", ".yaml", ".yml"))
    }


def post_declaring_length(client, path: str, content_length: int) -> int:
    """POST an upload claiming `content_length`, and send no body at all.

    The size gate is only pinned if the request is deterministic without the
    bytes, which is also the point: an over-cap `Content-Length` is answered
    before a single body byte is read (§6). If that check ever moved after the
    read, this call blocks until the socket times out.
    """
    request = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{client.port}\r\n"
        f"Origin: http://127.0.0.1:{client.port}\r\n"
        f"Content-Type: application/octet-stream\r\n"
        f"X-Refdes-Token: {client.app.token}\r\n"
        f"Content-Length: {content_length}\r\n"
        f"\r\n"
    ).encode("ascii")
    with socket.create_connection(("127.0.0.1", client.port), timeout=10) as sock:
        sock.sendall(request)
        head = sock.recv(1024)
    return int(head.split(b"\r\n", 1)[0].split(b" ")[1])


# ------------------------------------------------------------- where they land


def test_upload_lands_beside_the_source_file(served):
    """§4's default and §7's return value: the item's own directory, and
    `from_source` spelled the way that item's body has to write it."""
    _app, client, root = served
    status, body = upload(client, name="curve.png", item="REQ-001")
    assert status == 200, body
    payload = body
    assert payload["kind"] == "uploaded"
    assert payload["created"] is True
    assert payload["rel"] == "items/curve.png"
    assert payload["from_source"] == "curve.png"
    assert payload["bytes"] == len(PNG)
    assert payload["hash"] == "sha256:" + hashlib.sha256(PNG).hexdigest()
    assert (root / "items" / "curve.png").read_bytes() == PNG


def test_upload_destination_override_lands_where_it_says(served):
    """An explicit `dest` is honored -- including a declared `site.assets:`
    directory, which the *default* never is (§4). The §9 checks that make a
    shared-directory upload safe are Phase 2; this slice says so in its scope,
    not here."""
    _app, client, root = served
    status, payload = upload(client, name="curve.png", item="REQ-001", dest="figures")
    assert status == 200, payload
    assert payload["rel"] == "figures/curve.png"
    assert payload["from_source"] == "../figures/curve.png"
    assert (root / "figures" / "curve.png").read_bytes() == PNG


def test_upload_without_an_item_needs_a_dest(served):
    """There is no project-wide upload directory to fall back to (§15.2), so a
    request that names neither an item nor a destination is a 400, not a guess."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png")
    assert status == 400
    assert "dest" in payload["error"]
    assert snapshot_tree(root) == before


def test_upload_for_an_item_that_matches_nothing_is_404(served):
    """The same posture as `_images` and `_item_view`: an unresolvable item is a
    404 naming what was asked for, before any byte is written."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png", item="NOT-9999")
    assert status == 404
    assert "NOT-9999" in payload["error"]
    assert snapshot_tree(root) == before


@pytest.mark.parametrize(
    "dest",
    [
        "../outside",
        "..",
        "items/../../elsewhere",
        "/etc",
        "C:/Windows",
        "C:\\Windows",
        "figures:ads",
        "CON",
        "NUL.png",
        "figures/../figures",
    ],
)
def test_upload_override_destination_is_validated(served, dest):
    """`dest` gets the same segment checks every other path in the editor gets
    (`security.safe_relative_parts`), and nothing is written on the way out."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png", dest=dest)
    assert status == 400, f"{dest!r} -> {status} {payload}"
    assert snapshot_tree(root) == before


def test_upload_destination_must_already_exist(served):
    """The endpoint creates no directories (§11) -- an upload that would need
    one refuses instead of quietly reshaping the tree."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png", dest="figures/2026/thermal")
    assert status == 400
    assert "creates no directories" in payload["error"]
    assert not (root / "figures" / "2026").exists()
    assert snapshot_tree(root) == before


def test_upload_refuses_dotrefdes_destination(served):
    """§4 and §13: `.refdes/` is refdes's own state, and `.refdes/copies/` is
    gitignored because those bytes are not the project's to publish. An author's
    image belongs in the tracked tree."""
    _app, client, root = served
    (root / ".refdes" / "copies").mkdir(parents=True, exist_ok=True)
    before = snapshot_tree(root)
    for dest in (".refdes", ".refdes/copies"):
        status, payload = upload(client, name="curve.png", dest=dest)
        assert status == 400, dest
        assert ".refdes" in payload["error"]
    assert not (root / ".refdes" / "copies" / "curve.png").exists()
    assert snapshot_tree(root) == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_upload_destination_cannot_escape_through_a_symlink(tmp_path):
    """Real-path containment, the `citations.classify` model (§4, §11): a
    symlinked destination directory is refused even though it stats as a
    directory inside the project."""
    root = make_upload_project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    os.symlink(str(outside), str(root / "escape"))
    app, client = _serve(root)
    try:
        status, payload = upload(client, name="curve.png", dest="escape")
        assert status == 400, payload
        assert "outside the project" in payload["error"]
        assert not (outside / "curve.png").exists()
    finally:
        app.stop()


@pytest.mark.parametrize(
    "name",
    ["../curve.png", "a/curve.png", "a\\curve.png", "..", ".", "CON.png", "curve.png ", "x\x00.png"],
)
def test_name_must_be_one_safe_segment(served, name):
    """§5: a client-supplied path is a refusal, not a normalization puzzle. The
    name is validated as a single segment before anything is joined."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(client, name=name, dest="figures")
    assert status == 400, f"{name!r} -> {status} {payload}"
    assert snapshot_tree(root) == before


# ------------------------------------------------------------------ the types


@pytest.mark.parametrize(
    "name,data",
    [
        ("curve.png", PNG),
        ("curve.jpg", JPEG),
        ("curve.jpeg", JPEG),
        ("curve.gif", GIF),
        ("curve.webp", WEBP),
    ],
)
def test_every_accepted_signature_lands_with_a_matching_extension(served, name, data):
    _app, client, root = served
    status, payload = upload(client, name=name, item="REQ-001", data=data)
    assert status == 200, payload
    assert (root / "items" / name).read_bytes() == data


def test_type_is_sniffed_not_trusted(served):
    """§6: the bytes decide. A `.png` name over JPEG bytes refuses, and so does
    every other name/bytes disagreement -- the extension is a claim, the
    signature is the fact."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png", item="REQ-001", data=JPEG)
    assert status == 422
    assert "signature" in payload["error"]
    assert "jpg" in payload["error"]
    assert snapshot_tree(root) == before


@pytest.mark.parametrize(
    "name,data,why",
    [
        ("diagram.svg", SVG, "SVG"),
        ("shell.php", PHP, "signature"),
        ("curve", PNG, "signature"),
        ("notes.txt", PNG, "signature"),
    ],
)
def test_svg_and_the_unaccepted_refuse(served, name, data, why):
    """SVG refuses with the CSP reason, before a byte of it is looked at;
    everything else outside the signature allowlist refuses as unrecognized."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(client, name=name, item="REQ-001", data=data)
    assert status == 422, f"{name} -> {status} {payload}"
    assert why in payload["error"]
    assert snapshot_tree(root) == before


def test_the_svg_refusal_says_why(served):
    """The reason is the point: an author told "no" without the CSP explanation
    will file it as an arbitrary restriction and go looking for a workaround."""
    _app, client, _root = served
    _status, payload = upload(client, name="diagram.svg", item="REQ-001", data=SVG)
    for fragment in ("script", "CSP", "PNG, JPEG, GIF and WebP"):
        assert fragment in payload["error"]


def test_a_lying_content_type_decides_nothing(served):
    """§6 again: `Content-Type` is attacker-controlled text. A PNG named `.png`
    is accepted whatever the header claims alongside it, and a `.png` name over
    GIF bytes still refuses with the header claiming PNG."""
    _app, client, root = served
    status, payload = upload(
        client,
        name="curve.png",
        item="REQ-001",
        data=PNG,
        content_type="application/octet-stream; charset=binary",
    )
    assert status == 200, payload
    assert (root / "items" / "curve.png").read_bytes() == PNG

    before = snapshot_tree(root)
    status, payload = upload(
        client,
        name="curve.png",
        item="REQ-001",
        data=GIF,
        content_type="application/octet-stream",
    )
    assert status == 422
    assert "gif" in payload["error"]
    assert snapshot_tree(root) == before


# ------------------------------------------------------------------ the sizes


def test_oversize_is_413_before_the_body_is_read(served):
    """§6, first half: the cap is a header comparison, answered without reading
    a byte -- the same posture as `MAX_BODY_BYTES` before it."""
    _app, client, root = served
    before = snapshot_tree(root)
    assert post_declaring_length(client, "/api/assets?name=curve.png", MAX_ASSET_BYTES + 1) == 413
    assert snapshot_tree(root) == before


def test_oversize_bytes_are_refused_after_the_read_too(tmp_path):
    """§6, second half: the service refuses the bytes in hand, so the bound does
    not depend on the transport having caught it first."""
    root = make_upload_project(tmp_path)
    project = built_project(root)
    before = snapshot_tree(root)
    result = upload_mod.store_asset(
        project, dest="figures", name="curve.png", data=PNG + b"\x00" * MAX_ASSET_BYTES
    )
    assert isinstance(result, upload_mod.Refused)
    assert result.status == 413
    assert not (root / "figures" / "curve.png").exists()
    assert snapshot_tree(root) == before


def test_exactly_at_the_cap_is_not_refused_for_size(tmp_path):
    """Off-by-one guard on the second check: at the cap is not over it."""
    root = make_upload_project(tmp_path)
    project = built_project(root)
    data = PNG + b"\x00" * (MAX_ASSET_BYTES - len(PNG))
    result = upload_mod.store_asset(project, dest="figures", name="curve.png", data=data)
    assert isinstance(result, upload_mod.Uploaded), result


# ------------------------------------------------- the §5 collision table


def test_identical_bytes_are_not_a_conflict(served):
    """§5 row 2: re-dropping the same file is idempotent. No write -- not even a
    rewrite of the same bytes -- and the client still inserts the reference."""
    _app, client, root = served
    target = root / "items" / "curve.png"
    first = upload(client, name="curve.png", item="REQ-001")
    assert first[0] == 200
    mtime = os.stat(target).st_mtime_ns

    status, payload = upload(client, name="curve.png", item="REQ-001")
    assert status == 200, payload
    assert payload["created"] is False
    assert payload["hash"] == "sha256:" + hashlib.sha256(PNG).hexdigest()
    assert "identical" in payload["message"]
    assert os.stat(target).st_mtime_ns == mtime, "the identical row must not write at all"


def test_different_bytes_at_target_refuse_without_replace(served):
    """§5 row 3: no silent overwrite and no silent `-1` suffix. The refusal
    names the existing path, its size and its hash, because those are the facts
    an author needs to choose between replacing it (Phase 2) and renaming."""
    _app, client, root = served
    target = root / "items" / "curve.png"
    upload(client, name="curve.png", item="REQ-001", data=PNG)
    newcomer = PNG + b" the bytes that want to replace them"

    status, payload = upload(client, name="curve.png", item="REQ-001", data=newcomer)
    assert status == 409
    assert payload["kind"] == "conflict"
    assert payload["path"] == "items/curve.png"
    assert str(len(PNG)) in payload["error"], "the refusal names the existing file's size"
    assert hashlib.sha256(PNG).hexdigest() in payload["error"]
    assert target.read_bytes() == PNG
    assert not (root / "items" / "curve-1.png").exists(), "nothing is renamed for the author"


@pytest.mark.skipif(os.name != "nt", reason="needs a case-insensitive filesystem")
def test_case_only_collision_refuses_on_a_case_insensitive_filesystem(tmp_path):
    """§5's fourth row on the platforms that actually have the problem:
    `curve.png` against an existing `Curve.png` is a write that appears to
    succeed and then names two files no two checkouts agree on."""
    root = make_upload_project(tmp_path, {"items/Curve.png": PNG})
    project = built_project(root)
    result = upload_mod.store_asset(project, dest="items", name="curve.png", data=PNG)
    assert isinstance(result, upload_mod.Conflict), result
    assert "Curve.png" in result.reason
    assert (root / "items" / "Curve.png").read_bytes() == PNG


def test_case_only_collision_refuses(tmp_path, monkeypatch):
    """The same row, pinned where the filesystem will not show it.

    `case_mismatch` answers only on a case-insensitive filesystem, so the test
    emulates one for the duration of the call: `os.path.isfile` answers for the
    case-folded name, which is what Windows and macOS do natively. The check
    under test is the real `citations.case_mismatch`.
    """
    root = make_upload_project(tmp_path, {"items/Curve.png": PNG})
    project = built_project(root)
    real_isfile = os.path.isfile

    def case_insensitive_isfile(path):
        if real_isfile(path):
            return True
        parent, _, leaf = str(path).rpartition(os.sep)
        try:
            names = os.listdir(parent)
        except OSError:
            return False
        return any(name.lower() == leaf.lower() for name in names)

    monkeypatch.setattr(os.path, "isfile", case_insensitive_isfile)
    result = upload_mod.store_asset(project, dest="items", name="curve.png", data=PNG)
    assert isinstance(result, upload_mod.Conflict), result
    assert "Curve.png" in result.reason
    assert (root / "items" / "Curve.png").read_bytes() == PNG


def test_a_collision_refusal_names_the_two_real_choices(served):
    """The refusal has to be actionable: replace it (re-issue with
    `expected_hash=<the hash just returned>`) or pick another name. Anything
    else leaves the author stuck at a 409."""
    _app, client, _root = served
    upload(client, name="curve.png", item="REQ-001", data=PNG)
    _status, payload = upload(client, name="curve.png", item="REQ-001", data=PNG + b"!")
    assert payload["kind"] == "conflict"
    assert payload["current_hash"] == upload_mod.digest_of(PNG)
    assert "replace" in payload["error"]
    assert "another name" in payload["error"]


def _hash(data: bytes) -> str:
    return upload_mod.digest_of(data)


# ------------------------------------------------- the §8 expected_hash replace


def test_a_matching_expected_hash_replaces_and_says_so(served):
    """§8 row 1, the whole point of the parameter: the client re-issues with the
    hash of the version it saw, which *is* the confirmation, and the bytes go
    down through `_atomic_replace` -- same-directory temp, fsync, `os.replace`,
    re-read, compare. The response says `replaced` rather than `created`, because
    those are different facts about the author's page."""
    _app, client, root = served
    upload(client, name="curve.png", dest="figures", data=OLD_CURVE)
    target = root / "figures" / "curve.png"

    status, payload = upload(
        client, name="curve.png", dest="figures", data=NEW_CURVE, expected_hash=_hash(OLD_CURVE)
    )
    assert status == 200, payload
    assert payload["kind"] == "uploaded"
    assert payload["replaced"] is True
    assert payload["created"] is False
    assert payload["hash"] == _hash(NEW_CURVE)
    assert payload["bytes"] == len(NEW_CURVE)
    assert target.read_bytes() == NEW_CURVE
    assert "replaced" in payload["message"]
    assert [n for n in os.listdir(root / "figures") if "refdes-tmp" in n] == []


def test_the_replace_goes_through_atomic_replace_not_atomic_create(tmp_path, monkeypatch):
    """The design names the write, not just the outcome: §8 row 1 is
    "`_atomic_replace`, which re-reads and compares bytes after the write". A
    replace routed through `_atomic_create` would fail on a destination that
    exists, and one routed through a plain write would have no verification at
    all -- so the call itself is pinned, and so is the absence of the create."""
    root = make_upload_project(tmp_path, {"figures/curve.png": OLD_CURVE})
    project = built_project(root)
    calls: list[str] = []
    real_replace = upload_mod._atomic_replace
    real_create = upload_mod._atomic_create

    def note(call, real):
        def wrapper(path, payload):
            calls.append(call)
            return real(path, payload)

        return wrapper

    monkeypatch.setattr(upload_mod, "_atomic_replace", note("replace", real_replace))
    monkeypatch.setattr(upload_mod, "_atomic_create", note("create", real_create))

    result = upload_mod.store_asset(
        project,
        dest="figures",
        name="curve.png",
        data=NEW_CURVE,
        expected_hash=_hash(OLD_CURVE),
    )
    assert isinstance(result, upload_mod.Uploaded), result
    assert result.replaced is True
    assert calls == ["replace"]
    assert (root / "figures" / "curve.png").read_bytes() == NEW_CURVE


def test_a_stale_expected_hash_refuses_and_names_the_current_hash(served):
    """§8 row 2, and the reason the conflict carries a hash at all: the bytes
    the client confirmed are not the bytes that are there. Nothing is written,
    and the *current* hash goes back so the client can re-fetch and decide
    again rather than guess which version it is looking at."""
    _app, client, root = served
    upload(client, name="curve.png", dest="figures", data=OLD_CURVE)
    target = root / "figures" / "curve.png"
    before = snapshot_tree(root)
    stale = _hash(b"some bytes that were never there")

    status, payload = upload(
        client, name="curve.png", dest="figures", data=NEW_CURVE, expected_hash=stale
    )
    assert status == 409, payload
    assert payload["kind"] == "conflict"
    assert payload["conflict"] == "expected_hash"
    assert payload["current_hash"] == _hash(OLD_CURVE)
    assert payload["current_size"] == len(OLD_CURVE)
    assert _hash(OLD_CURVE) in payload["error"], "the current hash is in the message too"
    assert stale in payload["error"]
    assert target.read_bytes() == OLD_CURVE
    assert snapshot_tree(root) == before


def test_a_hand_edit_between_the_two_uploads_moves_the_hash_again(served):
    """The conflict is not a formality: the author is holding a hash from a
    moment ago, and the file can move in between -- by another editor session,
    by a branch switch, by a hand edit. The second refusal names the newer
    hash, which is the only thing the next decision can be based on."""
    _app, client, root = served
    upload(client, name="curve.png", dest="figures", data=OLD_CURVE)
    first = upload(client, name="curve.png", dest="figures", data=NEW_CURVE)[1]
    assert first["current_hash"] == _hash(OLD_CURVE)

    (root / "figures" / "curve.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"edited by hand")
    status, payload = upload(
        client,
        name="curve.png",
        dest="figures",
        data=NEW_CURVE,
        expected_hash=first["current_hash"],
    )
    assert status == 409
    assert payload["conflict"] == "expected_hash"
    assert payload["current_hash"] == _hash(b"\x89PNG\r\n\x1a\n" + b"edited by hand")
    assert (root / "figures" / "curve.png").read_bytes().endswith(b"edited by hand")


def test_expected_hash_for_a_file_that_is_gone_refuses(served):
    """§8 row 4: the file the author meant to replace is not there. A create was
    not what they asked for, so this does not quietly become one -- it says so
    and names the way to ask for it."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(
        client, name="curve.png", dest="figures", data=NEW_CURVE, expected_hash=_hash(OLD_CURVE)
    )
    assert status == 409, payload
    assert payload["conflict"] == "expected_hash"
    assert "gone" in payload["error"]
    assert payload["current_hash"] is None, "there is no current hash; the file is not there"
    assert not (root / "figures" / "curve.png").exists()
    assert snapshot_tree(root) == before


@pytest.mark.parametrize(
    "expected_hash",
    ["sha256:", "deadbeef", "sha256:xyz", "sha256:" + "0" * 63, "sha256:" + "0" * 65, "1" * 64],
)
def test_a_malformed_expected_hash_is_400(served, expected_hash):
    """A hash that could never match anything is a typo, not a conflict: a 400
    for a malformed request, before the service looks at the file at all."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = upload(
        client, name="curve.png", dest="figures", data=NEW_CURVE, expected_hash=expected_hash
    )
    assert status == 400, f"{expected_hash!r} -> {status} {payload}"
    assert "expected_hash" in payload["error"]
    assert not (root / "figures" / "curve.png").exists()
    assert snapshot_tree(root) == before


def test_a_matching_hash_with_identical_bytes_still_writes_nothing(served):
    """§5 row 2 outranks the replace: re-issuing with the right hash but the
    same bytes is a no-op, not a rewrite. The file's mtime is the observable."""
    _app, client, root = served
    upload(client, name="curve.png", dest="figures", data=OLD_CURVE)
    target = root / "figures" / "curve.png"
    mtime = os.stat(target).st_mtime_ns

    status, payload = upload(
        client, name="curve.png", dest="figures", data=OLD_CURVE, expected_hash=_hash(OLD_CURVE)
    )
    assert status == 200, payload
    assert payload["replaced"] is False
    assert payload["created"] is False
    assert "identical" in payload["message"]
    assert os.stat(target).st_mtime_ns == mtime


def test_an_expected_hash_on_an_absent_destination_still_creates_without_one(served):
    """The empty string is the ordinary create (§8: "or the empty string when
    the file does not exist"), and an absent `expected_hash` is the same thing
    -- so the Phase 1 path is unchanged for every client that has not learned
    the parameter yet."""
    _app, client, root = served
    status, payload = upload(client, name="curve.png", dest="figures", data=OLD_CURVE)
    assert status == 200, payload
    assert payload["created"] is True
    assert (root / "figures" / "curve.png").read_bytes() == OLD_CURVE


# ------------------------------------ the §9 checks against other documents


def test_upload_that_would_create_ambiguity_refuses(two_asset_dirs):
    """§9.1: the leaf is already in another declared `site.assets:` directory,
    and a bare `src` is resolved by searching those directories -- so a second
    file with that name turns every existing bare reference to it into the
    build's ambiguity error, in a document the author never opened. The refusal
    comes before the write and names both paths."""
    _app, client, root = two_asset_dirs
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png", dest="figures", data=NEW_CURVE)
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert payload["refusal"] == "ambiguity"
    assert "figures/curve.png" in payload["error"]
    assert "photos/shared/curve.png" in payload["error"]
    assert not (root / "figures" / "curve.png").exists()
    assert snapshot_tree(root) == before


def test_the_ambiguity_refusal_names_the_rule_not_just_the_paths(two_asset_dirs):
    """A refusal that names two files and no reason reads as a bug report. The
    rule is the part the author can act on: two matches is an error rather than
    a tie-break, so the ways out are a different name, a different directory,
    or renaming the file that is there."""
    _app, client, _root = two_asset_dirs
    _status, payload = upload(client, name="curve.png", dest="figures", data=NEW_CURVE)
    message = payload["error"]
    assert "ambiguous" in message or "ambiguity" in message
    assert "tie-break" in message
    assert "different name" in message
    assert [row["path"] for row in payload["details"]] == ["photos/shared/curve.png"]
    assert str(_app.state.snapshot.project.root) not in message


def test_an_upload_that_cannot_make_anything_ambiguous_is_not_refused(tmp_path):
    """The negative, and the reason §4's default destination is safe by
    construction: a file that lands outside every declared directory is not on
    the search path, so the same leaf already existing in `figures/` changes
    nothing for anyone. A leaf nobody else has is likewise not a second
    match."""
    root = make_upload_project(tmp_path, {"figures/curve.png": OLD_CURVE})
    app, client = _serve(root)
    try:
        status, payload = upload(client, name="curve.png", item="REQ-001", data=NEW_CURVE)
        assert status == 200, payload
        assert (root / "items" / "curve.png").read_bytes() == NEW_CURVE

        status, payload = upload(client, name="new-plot.png", dest="figures", data=NEW_CURVE)
        assert status == 200, payload
        assert (root / "figures" / "new-plot.png").read_bytes() == NEW_CURVE
    finally:
        app.stop()


def test_a_replace_adds_nothing_to_the_search_path(tmp_path):
    """The boundary of §9.1: it is about *adding* a second file with that leaf.
    When the leaf is already duplicated -- the project is already ambiguous, by
    a hand copy or an earlier commit -- overwriting one of the two copies
    changes no reference's resolution, so refusing it would be refusing a
    repair."""
    root = make_upload_project(
        tmp_path,
        {"figures/curve.png": OLD_CURVE, "photos/shared/curve.png": OLD_CURVE},
        assets=("figures", "photos/shared"),
    )
    project = built_project(root)
    result = upload_mod.store_asset(
        project,
        dest="figures",
        name="curve.png",
        data=NEW_CURVE,
        expected_hash=_hash(OLD_CURVE),
    )
    assert isinstance(result, upload_mod.Uploaded), result
    assert result.replaced is True
    assert (root / "figures" / "curve.png").read_bytes() == NEW_CURVE
    assert (root / "photos" / "shared" / "curve.png").read_bytes() == OLD_CURVE


def test_upload_that_would_capture_a_bare_reference_refuses(referencing):
    """§9.2, the silent one. The relative lookup runs first and always wins, so
    landing `items/curve.png` re-points the bare `curve.png` in every item in
    `items/` -- nothing errors, the page just shows a different picture. The
    refusal names the item and what its image resolves to right now."""
    _app, client, root = referencing
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png", dest="items", data=NEW_CURVE)
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert payload["refusal"] == "capture"
    assert "DEC-001" in payload["error"]
    assert "items/decs.yaml" in payload["error"]
    assert "figures/curve.png" in payload["error"], "and what it resolves to today"
    assert not (root / "items" / "curve.png").exists()
    assert snapshot_tree(root) == before


def test_a_capturing_upload_names_every_item_it_would_silently_re_point(referencing):
    """Both items in `items/` carry the bare reference, so the disclosure has to
    be both of them -- one is not a summary. The rows are project-relative, for
    the same reason every other response path is: the browser has no use for a
    server filesystem root."""
    _app, client, root = referencing
    _status, payload = upload(client, name="curve.png", dest="items", data=NEW_CURVE)
    rows = payload["details"]
    assert [row["item"] for row in rows] == ["DEC-001", "TST-001"]
    assert [row["source_file"] for row in rows] == ["items/decs.yaml", "items/tests.yaml"]
    assert all(row["resolves_to"] == "figures/curve.png" for row in rows)
    assert all(not os.path.isabs(row["source_file"]) for row in rows)
    assert "TST-001" in payload["error"], "the message names them too, not only the rows"
    assert str(root) not in payload["error"]


def test_a_bare_reference_one_directory_away_is_not_captured(tmp_path):
    """The scope of §9.2 is exactly the items whose relative lookup would find
    the new file: an item in `items/decs/` looks in `items/decs/`, so landing
    `items/curve.png` leaves its bare `curve.png` resolving on the search path
    where it resolves today. Directory equality, not a prefix match -- a prefix
    match would refuse uploads into a shared parent directory for no reason."""
    root = make_upload_project(tmp_path, {"figures/curve.png": OLD_CURVE})
    (root / "items" / "decs").mkdir(parents=True, exist_ok=True)
    (root / "items" / "decs" / "more.yaml").write_text(
        "defaults: { type: decision, board: board-a }\n"
        "items:\n"
        "  - id: DEC-009\n"
        "    title: An item one directory down.\n"
        "    status: proposed\n"
        "    body: |\n"
        "      ![curve](curve.png)\n",
        encoding="utf-8",
    )
    app, client = _serve(root)
    try:
        status, payload = upload(client, name="curve.png", dest="items", data=NEW_CURVE)
        assert status == 200, payload
        assert (root / "items" / "curve.png").read_bytes() == NEW_CURVE
    finally:
        app.stop()


def test_replacing_the_file_a_bare_reference_resolves_to_is_not_a_capture(referencing):
    """§9.2 is about a *new* file stealing a reference that points somewhere
    else. Overwriting the file the reference already resolves to is the replace
    case, and what it needs is §9.3's disclosure, not a refusal -- otherwise
    re-shooting a shared diagram would be impossible from the editor."""
    _app, client, root = referencing
    status, payload = upload(
        client,
        name="curve.png",
        dest="figures",
        data=NEW_CURVE,
        expected_hash=_hash(OLD_CURVE),
    )
    assert status == 200, payload
    assert payload["replaced"] is True
    assert (root / "figures" / "curve.png").read_bytes() == NEW_CURVE


def test_replace_reports_every_referencing_item(referencing):
    """§9.3, the first half: the author who is about to confirm a replace of a
    file two items show has to learn that here, from the `Conflict` they are
    looking at -- not from the two changed pages afterwards. An author who
    re-shoots a diagram expects every document using it to change; the editor's
    job is to say so before they click, not to forbid it."""
    _app, client, root = referencing
    status, payload = upload(client, name="curve.png", dest="figures", data=NEW_CURVE)
    assert status == 409, payload
    assert payload["kind"] == "conflict"
    assert payload["conflict"] == "collision"
    assert [row["item"] for row in payload["referenced_by"]] == ["DEC-001", "TST-001"]
    assert payload["referenced_by"][0]["source_file"] == "items/decs.yaml"
    assert payload["referenced_by"][0]["srcs"] == ["curve.png"]
    assert not any(os.path.isabs(row["source_file"]) for row in payload["referenced_by"])
    assert (root / "figures" / "curve.png").read_bytes() == OLD_CURVE


def test_a_confirmed_replace_names_the_items_it_changed(referencing):
    """§9.3, the second half: the disclosure rides the successful replace too, so
    a client that re-issues without re-reading the first conflict (or a client
    that got the hash from somewhere else entirely) still learns what moved."""
    _app, client, root = referencing
    conflict = upload(client, name="curve.png", dest="figures", data=NEW_CURVE)[1]
    status, payload = upload(
        client,
        name="curve.png",
        dest="figures",
        data=NEW_CURVE,
        expected_hash=conflict["current_hash"],
    )
    assert status == 200, payload
    assert payload["replaced"] is True
    assert [row["item"] for row in payload["referenced_by"]] == ["DEC-001", "TST-001"]
    assert (root / "figures" / "curve.png").read_bytes() == NEW_CURVE


def test_a_collision_nobody_references_discloses_nobody(served):
    """The disclosure is computed, not asserted: a file no body resolves to has
    an empty blast radius, and the field says so instead of inventing rows."""
    _app, client, _root = served
    upload(client, name="curve.png", dest="figures", data=OLD_CURVE)
    status, payload = upload(client, name="curve.png", dest="figures", data=NEW_CURVE)
    assert status == 409
    assert payload["referenced_by"] == []


def test_a_dangling_bare_reference_is_still_a_capture(tmp_path):
    """The other half of §9.2's rule, and the one the phrase "currently resolves
    to a different file" does not cover: a src that resolves to *nothing* today
    is a build error, and landing this file changes that page from an error to a
    picture without asking. `rel` is None, which is not the destination
    directory either."""
    root = make_upload_project(tmp_path)
    (root / "items" / "decs.yaml").write_text(
        "defaults: { type: decision, board: board-a }\n"
        "items:\n"
        "  - id: DEC-004\n"
        "    title: References a figure that is not there yet.\n"
        "    status: proposed\n"
        "    body: |\n"
        "      ![not yet](todo.png)\n",
        encoding="utf-8",
    )
    project = built_project(root)
    assert project.image_results["DEC-004"] == [
        {"src": "todo.png", "ok": False, "rel": None, "dest": None}
    ], "the precondition: the build really did record it as unresolved"
    result = upload_mod.store_asset(project, dest="items", name="todo.png", data=NEW_CURVE)
    assert isinstance(result, upload_mod.Refused), result
    assert result.kind == "capture"
    assert "DEC-004" in result.reason
    assert not (root / "items" / "todo.png").exists()


def _resave_body(client, item_ref: str, text: str) -> None:
    """An ordinary `set_body`, which is what makes a file beside the source
    visible to the build at all: §7's orphan is not an input until a body
    references it, and a save is the rebuild that finds it. The text has to
    *differ* -- re-saving the same bytes leaves the revision where it was, and a
    revision that does not move is a rebuild that does not happen."""
    _status, item = client.api_get(f"/api/item/{item_ref}")
    status, payload = client.api_post(
        f"/api/item/{item_ref}/edit",
        {"op": "set_body", "text": text, "expected_revision": item["edit"]["file_revision"]},
    )
    assert status == 200, payload


def test_the_capture_the_check_prevents_is_real(referencing):
    """The premise of §9.2, pinned so the check cannot be waved away as
    hypothetical: the relative lookup really does win, really does re-point both
    items' image to the new file, and really does not error. Written by hand
    here, because the endpoint refuses to do it -- which is the point of the
    refusal."""
    _app, client, root = referencing
    _status, _headers, before = client.page("/preview/dec-001.html")
    assert b'<img src="assets/figures/curve.png"' in before

    (root / "items" / "curve.png").write_bytes(NEW_CURVE)
    _resave_body(client, "DEC-001", "![the curve, redrawn](curve.png)\n")
    _status, _headers, after = client.page("/preview/dec-001.html")
    assert b'<img src="assets/items/curve.' in after, "the same src now shows a different file"
    assert b'<img src="assets/figures/curve.png"' not in after
    _status, _headers, sibling = client.page("/preview/tst-001.html")
    assert b'<img src="assets/items/curve.' in sibling, "and the item nobody opened, too"


def test_the_ambiguity_the_check_prevents_is_real(tmp_path):
    """The premise of §9.1, likewise: a second file with the leaf on the search
    path turns a bare reference that resolves today into the build's ambiguity
    error -- in a document nobody touched. Both files here are what one upload
    into `figures/` would have added to the tree, had the endpoint allowed it."""
    root = make_referencing_project(tmp_path, assets=("figures", "photos/shared"))
    app, client = _serve(root)
    try:
        _status, _headers, before = client.page("/preview/dec-001.html")
        assert b'<img src="assets/figures/curve.png"' in before
        assert not [e for e in app.state.snapshot.project.errors if "ambiguous" in e.message]

        (root / "photos" / "shared" / "curve.png").write_bytes(OLD_CURVE)
        (root / "figures" / "curve2.png").write_bytes(OLD_CURVE)
        os.replace(root / "figures" / "curve2.png", root / "figures" / "curve.png")
        assert app.state.refresh() is True, "a file under site.assets: is a build input"

        errors = [e.message for e in app.state.snapshot.project.errors if "ambiguous" in e.message]
        assert errors, "the build error the check exists to prevent"
        assert "photos/shared/curve.png" in errors[0]
        assert "items/decs.yaml" in errors[0], "and it names the document nobody edited"
    finally:
        app.stop()


def test_the_checks_see_only_what_the_last_build_recorded(tmp_path):
    """The input is `Project.image_results`, so it is a build's answer, not a
    live one. An item whose reference is still an unsaved browser draft is
    invisible to the check -- the same thing that makes the check cheap. Pinned
    so the boundary is a decision on the record rather than an accident: nothing
    here re-renders or re-searches per reference."""
    root = make_upload_project(tmp_path, {"figures/curve.png": OLD_CURVE})
    project = built_project(root)
    before = dict(project.image_results)
    upload_mod.store_asset(project, dest="items", name="curve.png", data=NEW_CURVE)
    assert project.image_results == before
    assert (root / "items" / "curve.png").read_bytes() == NEW_CURVE


# ------------------------------------------------------------------ §10 seals
#
# Two refusals, both decided before any byte is written. An upload *for* a
# sealed entry has no outcome that is not an orphan -- the body save that would
# carry the reference is refused under the same lock, so the image would sit
# beside an entry that can never point at it. And a file a sealed entry
# references cannot be replaced or created from here, because a seal hashes the
# entry's fields and normalized body text: the `![alt](path)` path, not the
# bytes behind it. Swap the file and the sealed record displays a different
# picture while its hash still verifies -- which is why §9.3's *disclose and let
# the author confirm* turns into a refusal here, and why no `expected_hash` buys
# the write back.

LOG_WITH_IMAGE = """\
defaults: { type: log, board: board-a, workspace: platform }
items:
  - id: LOG-001
    summary: Bench notes for the rail.
    body: |
      ![the curve as measured on the bench](curve.png)
"""


def seal_the_project(root):
    """Seal what is on disk the way it gets sealed in real life: one writable
    build records each append-only entry's content hash in
    `.refdes/log-seal*.yaml`. That file is what `seal.is_sealed` reads, so a
    fixture that wants a sealed item has to build once with `seal_write=True`
    -- the same move `tests/test_serve_edit.py::test_sealed_item_is_refused_and_untouched`
    makes."""
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse_mod.load_items(project)
    build_mod.build(project, seal_write=True)
    assert list((root / ".refdes").glob("log-seal*.yaml")), "the fixture sealed nothing"
    sealed = project.item_by_id("LOG-001")
    assert sealed is not None and seal_mod.is_sealed(project, sealed)
    return project


def make_sealed_project(tmp_path):
    """A project with one sealed log entry whose body references a bare
    `curve.png` that resolves to `figures/curve.png`: the exact state §10's
    second refusal is about. The image is a real build input and `image_results`
    really does name LOG-001 as a referrer -- `sealed_image` asserts it."""
    root = make_upload_project(tmp_path)
    (root / "items" / "log.yaml").write_text(LOG_WITH_IMAGE, encoding="utf-8")
    (root / "figures" / "curve.png").write_bytes(OLD_CURVE)
    seal_the_project(root)
    return root


@pytest.fixture
def sealed_image(tmp_path):
    """The served form of `make_sealed_project`."""
    root = make_sealed_project(tmp_path)
    project = built_project(root)
    assert [row["item"] for row in upload_mod._referencing_items(
        project, "figures/curve.png", upload_mod._source_files_by_id(project)
    )] == ["LOG-001"], "the precondition: the build records the sealed entry as a referrer"
    app, client = _serve(root)
    try:
        yield app, client, tmp_path
    finally:
        app.stop()


def test_sealed_item_refuses_upload_before_any_write(sealed_image):
    """§14's test, §10's first half. The upload carries the item it is for, and
    that item is sealed, so the request refuses: the body edit that would
    reference the image is itself refused, which makes any bytes written here an
    orphan on an entry that can never take the reference. Nothing lands on disk,
    in a project that was clean to begin with."""
    _app, client, root = sealed_image
    before = snapshot_tree(root)
    status, payload = upload(client, name="bench.png", item="LOG-001", data=PNG)
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert payload["refusal"] == "sealed"
    assert "LOG-001" in payload["error"], "the refusal names the entry it refused for"
    assert not (root / "items" / "bench.png").exists()
    assert snapshot_tree(root) == before, "not one byte of the project moved"


def test_a_sealed_upload_refusal_says_why_and_where_to_go_instead(sealed_image):
    """A refusal that only says "sealed" leaves the author holding a rejected
    drop. The actionable facts are the two the design names: the body edit is
    what is refused (so this is not the upload endpoint being fussy), and a
    correction to a sealed entry means appending one that `amends:` it -- which
    is an entry an upload *can* be for."""
    _app, client, _root = sealed_image
    _status, payload = upload(client, name="bench.png", item="LOG-001", data=PNG)
    message = payload["error"]
    assert "sealed" in message and "amends" in message
    assert "Nothing was written" in message
    assert [row["item"] for row in payload["details"]] == ["LOG-001"]
    assert payload["details"][0]["source_file"] == "items/log.yaml"
    assert str(_root) not in message


def test_the_upload_refusal_and_the_body_save_refusal_agree(sealed_image):
    """The two refusals use the same predicate -- `seal.is_sealed`, the one
    `apply_edit` applies under the write lock -- so an author cannot be told the
    body is frozen and then handed an upload that assumes it is not. Pinned by
    refusing both mutations on the same item in the same session."""
    _app, client, root = sealed_image
    _status, item = client.api_get("/api/item/LOG-001")
    status, edit = client.api_post(
        "/api/item/LOG-001/edit",
        {
            "op": "set_body",
            "text": "![a different curve](bench.png)\n",
            "expected_revision": item["edit"]["file_revision"],
        },
    )
    assert status == 422 and "sealed" in edit["reason"], edit
    upload_status, upload_payload = upload(client, name="bench.png", item="LOG-001", data=PNG)
    assert upload_status == 422 and upload_payload["refusal"] == "sealed"
    assert not (root / "items" / "bench.png").exists()


def test_a_sealed_target_is_refused_whatever_destination_it_is_given(sealed_image):
    """The refusal is about the entry the upload is *for*, not about where the
    bytes would land: an explicit `dest` somewhere else does not launder it, since
    the reference still has to reach LOG-001's body. Nor does a name that would
    collide with nothing."""
    _app, client, root = sealed_image
    status, payload = upload(
        client, name="somewhere-else.png", item="LOG-001", dest="figures", data=PNG
    )
    assert status == 422 and payload["refusal"] == "sealed", payload
    assert not (root / "figures" / "somewhere-else.png").exists()


def test_an_append_only_entry_that_is_not_yet_sealed_takes_the_upload(tmp_path):
    """The negative, and the reason the check is `is_sealed` rather than
    `type.append_only`: an append-only entry is only frozen once a build has
    sealed it, and the first image for a brand-new log entry is the ordinary
    case. Mirrors `test_append_only_item_without_a_seal_may_be_edited`."""
    root = make_sealed_project(tmp_path)
    (root / "items" / "log.yaml").write_text(
        LOG_WITH_IMAGE
        + "  - id: LOG-002\n"
        "    summary: A second entry, written after the build that sealed the first.\n",
        encoding="utf-8",
    )
    project = built_project(root)
    fresh = project.item_by_id("LOG-002")
    assert fresh is not None and not seal_mod.is_sealed(project, fresh)
    result = upload_mod.store_asset(
        project, dest="items", name="bench-2.png", data=PNG, item=fresh
    )
    assert isinstance(result, upload_mod.Uploaded), result
    assert (root / "items" / "bench-2.png").read_bytes() == PNG


def test_replacing_a_file_a_sealed_item_references_refuses(sealed_image):
    """§14's test, §10's sharp case. `figures/curve.png` is not part of any
    sealed entry's hashed text -- the seal hashes the *path* in
    `![alt](curve.png)`, not the bytes behind it -- so replacing it changes what
    a sealed record displays while that record still verifies as untouched. The
    refusal names the sealed item, and the file keeps its bytes."""
    _app, client, root = sealed_image
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png", dest="figures", data=NEW_CURVE)
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert payload["refusal"] == "sealed"
    assert "LOG-001" in payload["error"], "the sealed item is named, not 'an item is sealed'"
    assert "items/log.yaml" in payload["error"]
    assert "figures/curve.png" in payload["error"]
    assert (root / "figures" / "curve.png").read_bytes() == OLD_CURVE
    assert snapshot_tree(root) == before


def test_no_expected_hash_confirms_a_sealed_entrys_image_away(sealed_image):
    """The difference from §9.3, and the reason this is a refusal rather than a
    409: a conflict is a question, and there is no answer here. Carrying the
    current hash -- the exact confirmation that replaces any other file -- changes
    nothing, because what is protected is not the author's ownership of the file
    but the sealed record's immutability."""
    _app, client, root = sealed_image
    current = "sha256:" + hashlib.sha256(OLD_CURVE).hexdigest()
    status, payload = upload(
        client,
        name="curve.png",
        dest="figures",
        data=NEW_CURVE,
        expected_hash=current,
    )
    assert status == 422, payload
    assert payload["refusal"] == "sealed"
    assert "expected_hash" in payload["error"], "and the message says a hash does not help"
    assert (root / "figures" / "curve.png").read_bytes() == OLD_CURVE


def test_identical_bytes_to_a_sealed_entrys_image_are_still_a_no_op(sealed_image):
    """§5's idempotence outranks §10 when nothing would change: re-uploading the
    bytes that are already there leaves every sealed page displaying exactly what
    it displays now, so there is nothing to refuse. The refusal is about changing
    the file, not about touching its path."""
    _app, client, root = sealed_image
    status, payload = upload(client, name="curve.png", dest="figures", data=OLD_CURVE)
    assert status == 200, payload
    assert payload["created"] is False and payload["replaced"] is False
    assert (root / "figures" / "curve.png").read_bytes() == OLD_CURVE


def test_creating_a_file_a_sealed_entry_would_capture_refuses(sealed_image):
    """§10's "refuse to *create* a file at a path a sealed entry references":
    §9.2's capture with a seal on it. LOG-001 writes a bare `curve.png` that
    resolves to `figures/curve.png` today, and a src that resolves beside its own
    source file always wins -- so `items/curve.png` would silently re-point a
    sealed record. Same scan as Phase 2's capture check, and now the sharper of
    the two refusals."""
    _app, client, root = sealed_image
    before = snapshot_tree(root)
    status, payload = upload(client, name="curve.png", dest="items", data=NEW_CURVE)
    assert status == 422, payload
    assert payload["refusal"] == "sealed"
    assert "LOG-001" in payload["error"]
    assert "figures/curve.png" in payload["error"], "and what it resolves to today"
    assert not (root / "items" / "curve.png").exists()
    assert snapshot_tree(root) == before


def test_a_sealed_refusal_still_discloses_every_referrer(tmp_path):
    """The refusal is about the sealed entries; the disclosure stays the whole
    blast radius. Two items reference the file and only one is sealed, so the
    message names the sealed one and `details` carries both rows, each flagged,
    so a dialog can say "this one is why, and this other one would have changed
    too"."""
    root = make_sealed_project(tmp_path)
    (root / "items" / "decs.yaml").write_text(DECS_WITH_IMAGE, encoding="utf-8")
    project = built_project(root)
    sealed = project.item_by_id("LOG-001")
    assert seal_mod.is_sealed(project, sealed)
    result = upload_mod.store_asset(
        project, dest="figures", name="curve.png", data=NEW_CURVE
    )
    assert isinstance(result, upload_mod.Refused) and result.kind == "sealed", result
    assert [row["item"] for row in result.details] == ["DEC-001", "LOG-001"]
    assert {row["sealed"] for row in result.details} == {True, False}
    assert "LOG-001" in result.reason
    assert (root / "figures" / "curve.png").read_bytes() == OLD_CURVE


def test_an_unsealed_referrer_is_still_a_confirmable_conflict(referencing):
    """Phase 3 must not have turned every replace into a refusal: with no sealed
    entry looking at the file, §9.3's disclose-and-confirm still applies, and the
    disclosure rows now carry the `sealed` flag that says so -- the same field
    that makes the refusal, computed the same way."""
    _app, client, root = referencing
    status, payload = upload(client, name="curve.png", dest="figures", data=NEW_CURVE)
    assert status == 409, payload
    assert payload["conflict"] == "collision"
    assert [row["item"] for row in payload["referenced_by"]] == ["DEC-001", "TST-001"]
    assert all(row["sealed"] is False for row in payload["referenced_by"])
    status, payload = upload(
        client,
        name="curve.png",
        dest="figures",
        data=NEW_CURVE,
        expected_hash=_hash(OLD_CURVE),
    )
    assert status == 200 and payload["replaced"] is True, payload
    assert all(row["sealed"] is False for row in payload["referenced_by"])


def test_a_sealed_item_that_never_referenced_the_file_does_not_freeze_it(tmp_path):
    """The scope of the second refusal is *referenced*, not *present*: a sealed
    entry in the same project, or even the same directory, does not make every
    upload in sight illegal. The check reads the build's own per-item
    resolutions, so an entry that does not resolve to this file has no say."""
    root = make_sealed_project(tmp_path)
    project = built_project(root)
    result = upload_mod.store_asset(
        project, dest="items", name="unrelated.png", data=NEW_CURVE
    )
    assert isinstance(result, upload_mod.Uploaded), result
    assert (root / "items" / "unrelated.png").read_bytes() == NEW_CURVE
    captured = upload_mod.store_asset(
        project, dest="items", name="curve.png", data=NEW_CURVE
    )
    assert isinstance(captured, upload_mod.Refused) and captured.kind == "sealed", captured


def test_what_the_refusal_prevents_is_only_loud_at_the_next_build(sealed_image):
    """§10's premise, pinned the way Phase 2 pinned §9.1 and §9.2: the damage is
    real, and the editor is the only place it can be stopped *before* it shows.
    Hand-write the bytes the endpoint refuses to write and the sealed page shows
    the new picture; the build catches it afterwards -- HASH_FORMAT 5 folds each
    referenced image's digest into the entry's hash, so the seal now reports the
    entry as modified (tests/test_image_hash.py pins that half). Loud eventually
    is not the same as refused, which is why this refusal ships alongside it."""
    app, _client, root = sealed_image
    assert not [d for d in app.state.snapshot.project.errors if "sealed" in d.message]
    (root / "figures" / "curve.png").write_bytes(NEW_CURVE)
    assert app.state.refresh() is True, "a file under site.assets: is a build input"
    messages = [d.message for d in app.state.snapshot.project.errors if "sealed" in d.message]
    assert messages, "the build-side loudness this refusal exists to pre-empt"
    assert "LOG-001" in messages[0]


# ---------------------------------------------------------------- atomicity


@pytest.mark.skipif(not hasattr(os, "link"), reason="needs hard links")
def test_a_race_for_the_destination_is_refused_not_clobbered(tmp_path, monkeypatch):
    """The collision table is a check-then-act, and the write underneath it is
    `edit._atomic_create`: create-must-not-exist, via a hard link. So even when
    the pre-check loses the race, the destination's bytes survive and the upload
    refuses."""
    root = make_upload_project(tmp_path, {"items/curve.png": PNG})
    project = built_project(root)
    monkeypatch.setattr(os.path, "exists", lambda path: False)
    result = upload_mod.store_asset(project, dest="items", name="curve.png", data=JPEG)
    assert isinstance(result, upload_mod.Refused), result
    assert (root / "items" / "curve.png").read_bytes() == PNG
    assert [n for n in os.listdir(root / "items") if "refdes-tmp" in n] == []


def test_atomic_replace_rolls_back_on_verify_mismatch(tmp_path, monkeypatch):
    """§8 row 1's write verifies itself, and the verification is not
    decoration: `_atomic_replace` re-reads the file after `os.replace` and, if
    the bytes on disk are not the bytes planned, puts the original back. A
    replace that trusted its own write would leave an image neither the old
    author nor the new one chose. Sabotage-paired: `os.replace` does its real
    work and then scribbles, which is the only way to reach the branch."""
    root = make_upload_project(tmp_path, {"figures/curve.png": OLD_CURVE})
    project = built_project(root)
    real_replace = os.replace

    def replace_then_scribble(src, dst, **kwargs):
        real_replace(src, dst, **kwargs)
        with open(dst, "wb") as fh:
            fh.write(b"neither version")

    monkeypatch.setattr(edit_mod.os, "replace", replace_then_scribble)
    result = upload_mod.store_asset(
        project,
        dest="figures",
        name="curve.png",
        data=NEW_CURVE,
        expected_hash=_hash(OLD_CURVE),
    )
    monkeypatch.undo()

    assert isinstance(result, upload_mod.Refused), result
    assert result.status == 500
    assert (root / "figures" / "curve.png").read_bytes() == OLD_CURVE, "the original bytes are back"
    assert [n for n in os.listdir(root / "figures") if "refdes-tmp" in n] == []


def test_no_temp_file_survives_an_upload(served):
    """`_atomic_create` writes a same-directory temp and links it in; a leftover
    `.curve.png.refdes-tmp` is a file the author did not choose and `git status`
    has to explain."""
    _app, client, root = served
    upload(client, name="curve.png", item="REQ-001")
    assert [n for n in os.listdir(root / "items") if "refdes-tmp" in n] == []


def test_the_write_lock_is_held_for_the_whole_decision(tmp_path):
    """The decide-then-write sequence is one critical section: two uploads of
    different bytes to one absent destination cannot both write."""
    root = make_upload_project(tmp_path)
    project = built_project(root)
    results: list = []
    started = threading.Barrier(2)

    def go(data):
        started.wait()
        results.append(upload_mod.store_asset(project, dest="items", name="c.png", data=data))

    threads = [threading.Thread(target=go, args=(data,)) for data in (PNG, PNG + b"!")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(type(r).__name__ for r in results) == ["Conflict", "Uploaded"]
    assert (root / "items" / "c.png").read_bytes() in (PNG, PNG + b"!")


# ------------------------------------------------------- bytes and only bytes


def test_upload_never_writes_a_body(served):
    """§7: the endpoint writes bytes and returns a path. Every `.md`/`.yaml` in
    the project is byte-identical after every outcome -- success, collision,
    refusal."""
    _app, client, root = served
    before = text_files(root)
    upload(client, name="curve.png", item="REQ-001")
    upload(client, name="curve.png", item="REQ-001", data=PNG + b"!")  # 409
    upload(client, name="curve.png", item="REQ-001", data=PHP)  # 422
    upload(client, name="diagram.svg", item="REQ-001", data=SVG)  # 422
    assert text_files(root) == before


def test_body_edit_before_upload_is_blocked_by_the_gate(served):
    """§2's forcing fact, pinned as a contract: a body referencing a file that
    is not on disk cannot be saved, which is why upload-then-save is the only
    ordering the design admits."""
    _app, client, root = served
    _status, item = client.api_get("/api/item/REQ-001")
    before = (root / "items" / "reqs.yaml").read_text(encoding="utf-8")
    status, payload = client.api_post(
        "/api/item/REQ-001/edit",
        {
            "op": "set_body",
            "text": "![curve](curve.png)",
            "expected_revision": item["edit"]["file_revision"],
        },
    )
    assert status == 422, payload
    assert payload["kind"] == "invalid"
    assert any("curve.png" in d["message"] for d in payload["diagnostics"])
    assert (root / "items" / "reqs.yaml").read_text(encoding="utf-8") == before


def test_upload_then_body_edit_saves(served):
    """The ordering §7 forces, end to end: upload, insert `from_source`, save
    through the ordinary `set_body`, and the rendered page shows the image."""
    _app, client, _root = served
    _status, uploaded = upload(client, name="curve.png", item="REQ-001")
    _status, item = client.api_get("/api/item/REQ-001")
    status, result = client.api_post(
        "/api/item/REQ-001/edit",
        {
            "op": "set_body",
            "text": f"![curve]({uploaded['from_source']})",
            "expected_revision": item["edit"]["file_revision"],
        },
    )
    assert status == 200, result
    _status, _headers, page = client.page("/preview/req-001.html")
    assert b'<img src="assets/items/curve.' in page


# ------------------------------------------------------------ preview freshness


def test_upload_moves_the_revision(served):
    """§15.1's decision, at the endpoint: a file under a declared `site.assets:`
    directory is a semantic input, so writing one moves the revision."""
    app, client, _root = served
    before = client.api_get("/api/revision")[1]["revision"]
    upload(client, name="curve.png", dest="figures")
    assert client.api_get("/api/revision")[1]["revision"] != before


def test_upload_forces_a_preview_rebuild(served):
    """§12: the author looks at the preview the moment the drop finishes, so the
    endpoint rebuilds rather than waiting for the debounced two-tick poller. The
    new asset is in the current generation with no body save in between."""
    _app, client, root = served
    status, _headers, _body = client.page("/preview/assets/figures/curve.png")
    assert status == 404
    upload(client, name="curve.png", dest="figures")
    status, _headers, body = client.page("/preview/assets/figures/curve.png")
    assert status == 200, "the upload did not rebuild the preview"
    assert body == PNG
    assert (root / "figures" / "curve.png").read_bytes() == PNG


def test_an_upload_outside_an_asset_directory_is_a_correct_no_op(served):
    """§7's orphan: a file beside the source is not a build input until a body
    references it, so the forced refresh rebuilds nothing and the revision does
    not move. It is on disk, visible to `git status`, and left alone."""
    _app, client, root = served
    before = client.api_get("/api/revision")[1]["revision"]
    upload(client, name="curve.png", item="REQ-001")
    assert (root / "items" / "curve.png").exists()
    assert client.api_get("/api/revision")[1]["revision"] == before


# ------------------------------------------------------------------ the gate


def test_upload_requires_token_and_origin(served):
    """§11: the one new endpoint is behind the gate every other mutation is
    behind, because it is routed in `api.handle` and not around it."""
    _app, client, root = served
    before = snapshot_tree(root)
    assert upload(client, name="curve.png", item="REQ-001", token=False)[0] == 403
    assert upload(client, name="curve.png", item="REQ-001", origin=False)[0] == 403
    assert snapshot_tree(root) == before


def test_a_foreign_host_is_refused_before_routing(served):
    _app, client, _root = served
    status, _headers, _body = client.request(
        "POST",
        "/api/assets?item=REQ-001&name=curve.png",
        token=True,
        body=PNG,
        headers={
            "Content-Type": "application/octet-stream",
            "Origin": f"http://127.0.0.1:{client.port}",
        },
        host="evil.example",
    )
    assert status == 403


@pytest.mark.parametrize(
    "content_type", ["multipart/form-data", "text/plain", "application/json", None]
)
def test_upload_content_type_allowlist(served, content_type):
    """§11: exactly one additional literal is admitted, and only on this route.
    Multipart is refused because there is no standard-library parser to trust
    with untrusted bytes; a missing header is refused too."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, _headers, body = client.request(
        "POST",
        "/api/assets?item=REQ-001&name=curve.png",
        token=True,
        body=PNG,
        headers={
            **({"Content-Type": content_type} if content_type else {}),
            "Origin": f"http://127.0.0.1:{client.port}",
        },
    )
    assert status == 415, f"{content_type} -> {status} {body!r}"
    assert snapshot_tree(root) == before


def test_a_read_only_server_refuses_the_upload(tmp_path):
    """§11: `--no-write` refuses it exactly as it refuses edits."""
    root = make_upload_project(tmp_path)
    app, client = _serve(root, read_only=True)
    try:
        before = snapshot_tree(root)
        status, payload = upload(client, name="curve.png", item="REQ-001")
        assert status == 403
        assert "--no-write" in payload["error"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


def test_get_on_the_upload_route_is_405(served):
    """One method, and the route says so rather than 404-ing the fact."""
    _app, client, _root = served
    status, _payload = client.api_get("/api/assets?item=REQ-001&name=curve.png")
    assert status == 405


def test_the_response_never_leaks_a_server_path(served):
    """The `shown()` posture of every other route: what the browser gets is
    project-relative."""
    _app, client, root = served
    _status, payload = upload(client, name="curve.png", item="REQ-001")
    assert str(root) not in repr(payload)
    assert not os.path.isabs(payload["rel"])
    assert not os.path.isabs(payload["from_source"])
