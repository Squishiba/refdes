"""`POST /api/assets` -- Phase 1, "Bytes" (docs/design/editor-image-upload.md §17).

The claims pinned here are the ones that slice is scoped by:

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
* the write is a create that must not exist (`_atomic_create`), so a raced
  destination is refused rather than clobbered, and no temp file survives;
* the size cap is enforced twice, against `Content-Length` before a byte is
  read and against the bytes in hand (§6);
* the existing gate still applies -- token, `Origin`, Host, the content-type
  allowlist, `--no-write`;
* and the endpoint writes bytes only. It never touches a `.md` or `.yaml`, and
  the reference reaches disk through the ordinary `set_body` save (§7).

Not here: `expected_hash` and the replace path, the §9.1 ambiguity check and
the §9.2 capture check (Phase 2), and the §10 sealed-target and
sealed-referenced refusals (Phase 3). Phase 1 ships with that hole open by
design -- an upload can break another document -- and Phase 2 exists to close
it.
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

from refdes.serve import upload as upload_mod
from refdes.serve.server import MAX_ASSET_BYTES, EditorApp

PNG = b"\x89PNG\r\n\x1a\n" + b"a png, honestly"
JPEG = b"\xff\xd8\xff\xe0" + b"a jpeg, honestly"
GIF = b"GIF89a" + b"a gif, honestly"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 "
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
PHP = b"<?php echo 'pwned'; ?>"


def make_upload_project(tmp_path, files: dict[str, bytes] | None = None):
    """The shared filter fixture plus a declared `site.assets:` directory, so
    the preview-rebuild claim has a real build input to test against. `files`
    maps a project-relative path to its bytes."""
    root = tmp_path
    make_filter_project(root)
    (root / "figures").mkdir(exist_ok=True)
    config = root / "refdes-project.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'site:\n  title: "Filter test"\n',
            'site:\n  title: "Filter test"\n  assets: [figures]\n',
        ),
        encoding="utf-8",
    )
    for rel, data in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


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
):
    """One raw-bytes upload (§11): metadata in the query, bytes in the body."""
    params = {"name": name}
    if dest is not None:
        params["dest"] = dest
    if item is not None:
        params["item"] = item
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
    before = snapshot_tree(root)
    result = upload_mod.store_asset(
        str(root), dest="figures", name="curve.png", data=PNG + b"\x00" * MAX_ASSET_BYTES
    )
    assert isinstance(result, upload_mod.Refused)
    assert result.status == 413
    assert not (root / "figures" / "curve.png").exists()
    assert snapshot_tree(root) == before


def test_exactly_at_the_cap_is_not_refused_for_size(tmp_path):
    """Off-by-one guard on the second check: at the cap is not over it."""
    root = make_upload_project(tmp_path)
    data = PNG + b"\x00" * (MAX_ASSET_BYTES - len(PNG))
    result = upload_mod.store_asset(str(root), dest="figures", name="curve.png", data=data)
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
    result = upload_mod.store_asset(str(root), dest="items", name="curve.png", data=PNG)
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
    result = upload_mod.store_asset(str(root), dest="items", name="curve.png", data=PNG)
    assert isinstance(result, upload_mod.Conflict), result
    assert "Curve.png" in result.reason
    assert (root / "items" / "Curve.png").read_bytes() == PNG


def test_a_collision_refusal_names_the_two_real_choices(served):
    """The refusal has to be actionable: replace (Phase 2's `expected_hash`) or
    pick another name. Anything else leaves the author stuck at a 409."""
    _app, client, _root = served
    upload(client, name="curve.png", item="REQ-001", data=PNG)
    _status, payload = upload(client, name="curve.png", item="REQ-001", data=PNG + b"!")
    assert payload["kind"] == "conflict"
    assert "replace" in payload["error"]
    assert "another name" in payload["error"]


# ---------------------------------------------------------------- atomicity


@pytest.mark.skipif(not hasattr(os, "link"), reason="needs hard links")
def test_a_race_for_the_destination_is_refused_not_clobbered(tmp_path, monkeypatch):
    """The collision table is a check-then-act, and the write underneath it is
    `edit._atomic_create`: create-must-not-exist, via a hard link. So even when
    the pre-check loses the race, the destination's bytes survive and the upload
    refuses."""
    root = make_upload_project(tmp_path, {"items/curve.png": PNG})
    monkeypatch.setattr(os.path, "exists", lambda path: False)
    result = upload_mod.store_asset(str(root), dest="items", name="curve.png", data=JPEG)
    assert isinstance(result, upload_mod.Refused), result
    assert (root / "items" / "curve.png").read_bytes() == PNG
    assert [n for n in os.listdir(root / "items") if "refdes-tmp" in n] == []


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
    results: list = []
    started = threading.Barrier(2)

    def go(data):
        started.wait()
        results.append(upload_mod.store_asset(str(root), dest="items", name="c.png", data=data))

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
