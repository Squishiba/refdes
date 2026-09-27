"""The PDF read endpoints (docs/design/editor-pdf-picker.md §2.1, §2.2, §4, §6,
§8, §11 -- Slice P-A; the endpoint half of the design's named tests).

Through the real HTTP surface against a real fixture project, in the posture
`test_serve_sources.py` uses: one `served` fixture, a real `EditorApp`, real PDF
bytes on disk, and for the refusals one `snapshot_tree` comparison proving the
whole project -- the item file, the datasheet, and the citation lockfile alike
-- came out byte for byte as it went in. These routes make the server read a
PDF, so the tests that matter most are the ones that try to make them read a
document the item has not cited, and the ones that prove no PDF byte and no
absolute server path ever leaves the process.

Nothing here writes. The page view and the confirm step are Slice P-B and
accept is Slice P-C, and the absence of a lockfile write is asserted rather than
assumed.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from conftest import write_project_config
from helpers import pdf_bytes, pdf_page, pdf_run
from serve_support import Client, snapshot_tree

from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes.schema import load_project
from refdes.serve.server import EditorApp

CONFIG = """\
site: { title: PDF picker, out: _site }
types:
  decision:
    prefix: DEC
    fields:
      citations: { type: citations, on_change: invalidate }
"""

# Four pages, so prev/next and an out-of-range page are all real: a prose page
# with no numbers, the min/typ/max table, a second table, and a page with no
# text on it at all.
PROSE = pdf_page(pdf_run(72, 700, "This page is a figure."))
TABLE = pdf_page(
    pdf_run(72, 700, "VOUT Efficiency"),
    pdf_run(200, 660, "MIN"),
    pdf_run(280, 660, "TYP"),
    pdf_run(360, 660, "MAX"),
    pdf_run(200, 640, "3.15"),
    pdf_run(280, 640, "3.30"),
    pdf_run(360, 640, "3.45"),
)
SECOND = pdf_page(
    pdf_run(72, 700, "Load Regulation"),
    pdf_run(200, 640, "0.98"),
)
BLANK = pdf_page()
PDF = pdf_bytes(PROSE, TABLE, SECOND, BLANK)

REMOTE = "https://example.com/ds.pdf"
HASH_ONLY = "https://example.com/hashonly.pdf"

ITEMS = f"""\
defaults: {{ type: decision }}
items:
  - id: DEC-001
    citations:
      - path: datasheets/sheet.pdf
        page: "2"
    body: |
      ```{{calc
      P = 1 | 1
      ```
  - id: DEC-002
    citations:
      - path: {REMOTE}
        keep_copy: true
        page: "3"
  - id: DEC-003
    citations:
      - path: {HASH_ONLY}
"""


def make_root(tmp_path, *, pdf: bytes = PDF, items: str = ITEMS):
    tmp_path.mkdir(parents=True, exist_ok=True)
    write_project_config(tmp_path, CONFIG)
    (tmp_path / "datasheets").mkdir(exist_ok=True)
    (tmp_path / "datasheets" / "sheet.pdf").write_bytes(pdf)
    (tmp_path / "items").mkdir(exist_ok=True)
    (tmp_path / "items" / "decisions.yaml").write_text(items, encoding="utf-8")
    return tmp_path


def start(root, **kw):
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, **kw)
    app.start()
    return app


def fetch(root, *extra):
    """`refdes fetch` against this fixture, before the server is started, scoped
    to the local datasheet. The two remote citations are pinned by hand instead
    (see `keep_copy`): a test that let fetch reach the network would be a test
    that fails when the network is down, and one that *did* succeed would be
    fetching bytes nothing pinned.

    Order matters: the served model is built once, when the app starts, so a
    lockfile written after that would not be in the model a request reads.
    """
    assert cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "fetch",
         "--path", "datasheets/sheet.pdf", *extra]
    ) == 0


def add_lock(root, records: dict) -> None:
    """Merge `records` into the citation lockfile, through the tool's own writer.

    A remote datasheet's bytes are written by `refdes fetch` from the network,
    which a test must not do; what a *fetched* project has afterwards is exactly
    this: a record keyed by the URL, with the sha256 of the bytes, and the kept
    copy itself under `.refdes/copies/` named for that hash. The record for a
    `section:` is written the same way, which is the point: the picker reads
    what the fetch recorded and never re-reads the outline itself.
    """
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    merged = citations_mod.load_lockfile(project)
    merged.update(records)
    citations_mod.save_lockfile(project, merged)


def keep_copy(root, url: str, data: bytes, **extra) -> str:
    """Pin `url` to `data` and keep the bytes, as a `keep_copy: true` fetch does.
    Returns the sha256."""
    sha = hashlib.sha256(data).hexdigest()
    blobs = root / ".refdes" / "copies"
    blobs.mkdir(parents=True, exist_ok=True)
    (blobs / f"{sha}.pdf").write_bytes(data)
    record = {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "kept_copy": True}
    record.update(extra)
    add_lock(root, {url: record})
    return sha


def hash_only(root, url: str) -> None:
    """Pin `url` as a hash with no kept copy -- the common posture for a
    copyrighted datasheet, and the one with no bytes to browse."""
    add_lock(root, {url: {
        "sha256": hashlib.sha256(url.encode()).hexdigest(),
        "fetched": "2026-01-01T00:00:00Z",
        "kept_copy": False,
    }})


def served_project(tmp_path, *, keep=True, sections=None):
    """A project with a real local pin, and a `keep_copy: true` remote datasheet
    beside it unless `keep` is false."""
    root = make_root(tmp_path)
    fetch(root)
    if keep:
        keep_copy(root, REMOTE, PDF, sections=sections or {})
    hash_only(root, HASH_ONLY)
    return root


@pytest.fixture
def served(tmp_path):
    root = served_project(tmp_path)
    app = start(root)
    try:
        yield app, Client(app), root
    finally:
        app.stop()


def sources_url(ref, *parts):
    return "/api/item/" + ref + "/sources" + "".join(parts)


def page_url(ref, path, page=None):
    url = sources_url(ref, "/page") + "?path=" + path
    return url + (f"&page={page}" if page is not None else "")


def strings(payload):
    """Every string anywhere in a JSON payload, for the no-leak assertion."""
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, dict):
        for value in payload.values():
            yield from strings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from strings(value)


# ---------------------------------------------------------------- 1: the files


def test_the_picker_lists_a_cited_local_pdf_and_a_keep_copy_remote_one(served):
    """§2.1. Both datasheets reach the list, each with `reader: "pdf"` and the
    page-mode marker, and each with the page its own citation names -- the thing
    that makes the file list enough to open the picker in the right place."""
    _app, client, root = served
    status, payload = client.api_get(sources_url("DEC-001"))
    assert status == 200, payload
    assert [(f["path"], f["reader"], f["browse"], f["open_page"])
            for f in payload["files"]] == [
        ("datasheets/sheet.pdf", "pdf", "pages", 2),
    ]
    local = payload["files"][0]
    assert local["state"] == "ok" and len(local["sha256"]) == 64
    # A PDF has no keys, so the CSV panel's "values already pinned" is empty
    # rather than invented.
    assert local["pinned_values"] == {}

    # The remote one is browsable because the fetch kept its bytes -- and it is
    # keyed by the URL as the citation spells it, because a URL has no
    # project-relative form to canonicalize into.
    status, payload = client.api_get(sources_url("DEC-002"))
    assert status == 200, payload
    assert [(f["path"], f["reader"], f["browse"], f["open_page"], f["state"])
            for f in payload["files"]] == [
        (REMOTE, "pdf", "pages", 3, "ok"),
    ]
    assert payload["problems"] == []
    # An item that cites a datasheet it can read no longer gets an empty picker
    # because the file is not a CSV.
    status, payload = client.api_get(sources_url("DEC-003"))
    assert status == 200 and payload["files"] == []
    assert len(payload["problems"]) == 1


def test_the_picker_refuses_a_hash_only_remote_citation_with_the_keep_copy_hint(
    tmp_path,
):
    """§10 Q4, option A: a TI URL datasheet kept as a hash has no bytes in this
    process's reach, and the answer names the fix rather than fetching them. The
    editor performs no network I/O, and browsing bytes nothing pinned would
    quietly reopen what a pin means."""
    root = served_project(tmp_path)
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(sources_url("DEC-003"))
        assert status == 200, payload
        assert payload["files"] == []
        (problem,) = payload["problems"]
        assert problem["path"] == HASH_ONLY
        assert "no local copy of the bytes" in problem["problem"]
        assert "keep_copy: true" in problem["problem"]
        assert "local `path:` PDF" in problem["problem"]
        # and the page read refuses the same way, rather than reading nothing
        status, payload = client.api_get(page_url("DEC-003", HASH_ONLY))
        assert status == 422 and payload["kind"] == "refused"
        assert "no local copy of the bytes" in payload["error"]
        # An unfetched remote citation says so before it says anything about
        # bytes -- there is nothing pinned to be a copy of.
        root = make_root(tmp_path / "unfetched")
        app2 = start(root)
        try:
            status, payload = Client(app2).api_get(sources_url("DEC-003"))
            assert payload["files"] == []
            assert "no fetched record" in payload["problems"][0]["problem"]
        finally:
            app2.stop()
    finally:
        app.stop()


def test_a_kept_copy_that_is_missing_or_tampered_is_named_not_read(tmp_path):
    # The kept copy is content-addressed, so these are the two ways it can be
    # wrong and both are visible: it was deleted, or it is not the bytes the
    # lockfile pinned. Browsing either would be browsing a document no pin
    # describes.
    absent = "f" * 64
    root = served_project(tmp_path / "absent")
    add_lock(root, {REMOTE: {
        "sha256": absent, "fetched": "2026-01-01T00:00:00Z", "kept_copy": True,
    }})
    app = start(root)
    try:
        status, payload = Client(app).api_get(sources_url("DEC-002"))
        assert status == 200, payload
        assert payload["files"] == []
        assert "is missing at" in payload["problems"][0]["problem"]
        assert f"copies/{absent}.pdf" in payload["problems"][0]["problem"]
    finally:
        app.stop()

    # ...and the same record with a blob that is not the bytes it names: the copy
    # is content-addressed, so a mismatch is a tampered or corrupt cache rather
    # than a moved file, and `verify()` treats that as an error, not a warning.
    root = served_project(tmp_path / "tampered")
    add_lock(root, {REMOTE: {
        "sha256": absent, "fetched": "2026-01-01T00:00:00Z", "kept_copy": True,
    }})
    blobs = root / ".refdes" / "copies"
    blobs.mkdir(parents=True, exist_ok=True)
    (blobs / f"{absent}.pdf").write_bytes(b"%PDF-1.4 tampered\n")
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(sources_url("DEC-002"))
        assert status == 200 and payload["files"] == []
        assert "does not match its pinned hash" in payload["problems"][0]["problem"]
        # and the page read refuses it the same way, rather than browsing it
        status, payload = client.api_get(page_url("DEC-002", REMOTE))
        assert status == 422 and "does not match its pinned hash" in payload["error"]
    finally:
        app.stop()


def test_a_cited_pdf_is_not_a_row_list_and_a_csv_is_not_a_page(tmp_path):
    # One file list, two shapes. A PDF reaches the two key-shaped endpoints and
    # is told what it actually has -- pages of candidates, not a key column --
    # rather than returning an empty table or composing a `source()` call against
    # a row that does not exist. Both are refusals with words, never an empty
    # success.
    root = served_project(tmp_path)
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=datasheets/sheet.pdf"
        )
        assert status == 200, payload
        assert payload["entries"] == [] and payload["problems"]
        assert "a PDF has no key column" in payload["problems"][0]
        status, payload = client.api_get(
            sources_url("DEC-001", "/propose")
            + "?path=datasheets/sheet.pdf&key=3.30&unit=V"
        )
        assert status == 422 and payload["kind"] == "refused"
        assert "a PDF has no key column" in payload["error"]
        status, payload = client.api_get(
            sources_url("DEC-001", "/page") + "?path=datasheets/sheet.pdf"
            + "&page=0"
        )
        assert status == 400 and "page must be a positive integer" in payload["error"]
    finally:
        app.stop()


# -------------------------------------------------------------- 2: the page


def test_the_page_view_opens_at_the_cited_page_and_at_the_resolved_section_page(
    served, tmp_path,
):
    """§2.2: the picker opens where the citation already points -- `page:`
    directly, or the page the lockfile resolved for a `section:` -- and the
    payload says which it followed, so the panel can show the author."""
    _app, client, _root = served
    status, payload = client.api_get(page_url("DEC-001", "datasheets/sheet.pdf"))
    assert status == 200, payload
    assert (payload["page"], payload["pages"]) == (2, 4)
    assert payload["open_at"] == {"page": 2, "from": "page"}
    assert payload["cited"] == {"page": "2", "section": "", "detail": ""}
    # ...and it is page 2's content, not page 1's.
    assert [row["text"] for row in payload["rows"]][0] == "VOUT Efficiency"

    # A `section:` opens at the page the fetch resolved for it, read out of the
    # lockfile -- the picker never re-reads the outline.
    root = make_root(tmp_path / "sectioned")
    fetch(root)
    sha = keep_copy(root, REMOTE, PDF, sections={"Load Regulation": 3},
                    sections_sha256=hashlib.sha256(PDF).hexdigest())
    assert sha
    (root / "items" / "decisions.yaml").write_text(
        f"defaults: {{ type: decision }}\n"
        f"items:\n"
        f"  - id: DEC-004\n"
        f"    citations:\n"
        f"      - path: {REMOTE}\n"
        f"        keep_copy: true\n"
        f"        section: Load Regulation\n",
        encoding="utf-8",
    )
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(page_url("DEC-004", REMOTE))
        assert status == 200, payload
        assert payload["open_at"] == {"page": 3, "from": "section"}
        assert payload["cited"]["section"] == "Load Regulation"
        assert payload["page"] == 3
        assert payload["rows"][0]["text"] == "Load Regulation"
    finally:
        app.stop()


def test_a_section_whose_page_is_unusable_says_why_and_opens_page_one(tmp_path):
    # Three ways a `section:` can fail to give a page to open, all of which the
    # rendered link already has words for, and none of which may silently open
    # page 1 as though the author had asked for it.
    cases = {
        "no resolved page": (
            {}, "has no resolved page in the lockfile"
        ),
        "resolved against other bytes": (
            {"sections": {"Load Regulation": 3}, "sections_sha256": "0" * 64},
            "was resolved against different bytes than the ones now pinned",
        ),
    }
    for label, (extra, fragment) in cases.items():
        root = make_root(tmp_path / label.replace(" ", "-"))
        fetch(root)
        keep_copy(root, REMOTE, PDF, **extra)
        (root / "items" / "decisions.yaml").write_text(
            f"defaults: {{ type: decision }}\n"
            f"items:\n"
            f"  - id: DEC-005\n"
            f"    citations:\n"
            f"      - path: {REMOTE}\n"
            f"        keep_copy: true\n"
            f"        section: Load Regulation\n",
            encoding="utf-8",
        )
        app = start(root)
        try:
            status, payload = Client(app).api_get(page_url("DEC-005", REMOTE))
            assert status == 200, (label, payload)
            assert payload["page"] == 1
            assert payload["open_at"] == {"page": 1, "from": "default"}
            assert fragment in payload["cited"]["detail"], (label, payload)
            assert "refdes fetch" in payload["cited"]["detail"]
        finally:
            app.stop()

    # A `page:` that is not a number is a real citation the rendered link can
    # carry, and not something a page index can open.
    root = make_root(tmp_path / "roman")
    (root / "items" / "decisions.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-006\n"
        "    citations:\n"
        "      - path: datasheets/sheet.pdf\n"
        "        page: \"xiv\"\n",
        encoding="utf-8",
    )
    app = start(root)
    try:
        status, payload = Client(app).api_get(
            page_url("DEC-006", "datasheets/sheet.pdf")
        )
        assert status == 200, payload
        assert payload["page"] == 1
        assert "is not a page number this can open at" in payload["cited"]["detail"]
    finally:
        app.stop()


def test_a_cited_page_the_document_does_not_have_opens_page_one_and_says_why(tmp_path):
    # A page number from another revision is a wrong link, not a near miss
    # (docs/markdown.md), and this is the same rule at the read boundary: the
    # refusal names the page and the count, and the document still opens.
    root = make_root(tmp_path)
    (root / "items" / "decisions.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-007\n"
        "    citations:\n"
        "      - path: datasheets/sheet.pdf\n"
        "        page: \"99\"\n",
        encoding="utf-8",
    )
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            page_url("DEC-007", "datasheets/sheet.pdf")
        )
        assert status == 200, payload
        assert payload["page"] == 1
        assert "page 99 is not in this document" in payload["cited"]["detail"]
        assert "it has 4 page(s)" in payload["cited"]["detail"]
        # The same page the *request* names is a refusal, not a redirect: the
        # caller asked for page 99 and page 99 is not a thing.
        status, payload = client.api_get(
            page_url("DEC-007", "datasheets/sheet.pdf", 99)
        )
        assert status == 422 and payload["kind"] == "refused"
        assert "page 99 is not in this document" in payload["error"]
    finally:
        app.stop()


def test_a_page_with_no_numbers_and_a_page_with_no_text_are_panel_states(served):
    """§3: "visible failure is a panel state, not an error page". A page the
    reader can read but that holds nothing to pick is a 200 with the reader's
    words and no candidates -- never a guessed number and never a refusal."""
    _app, client, _root = served
    status, payload = client.api_get(
        page_url("DEC-001", "datasheets/sheet.pdf", 1)
    )
    assert status == 200, payload
    assert [row["text"] for row in payload["rows"]] == ["This page is a figure."]
    assert payload["candidate_count"] == 0
    assert "no number that reads as a plain ASCII decimal" in payload["detail"]

    status, payload = client.api_get(
        page_url("DEC-001", "datasheets/sheet.pdf", 4)
    )
    assert status == 200, payload
    assert payload["rows"] == [] and payload["spans"] == []
    assert "no extractable text" in payload["detail"]
    assert "scanned" in payload["detail"]

    # A page outside the document is the other thing: the page *is* the request,
    # so a page that cannot be read is a refused request, not an empty page.
    status, payload = client.api_get(
        page_url("DEC-001", "datasheets/sheet.pdf", 5)
    )
    assert status == 422 and "it has 4 page(s)" in payload["error"]


def test_the_page_payload_carries_the_rows_the_min_typ_max_rule_needs(served):
    # The confirm step's inputs, on the wire: the verbatim row, every number in
    # it with the value `fetch` would pin, its 0-based index among the row's
    # candidates, and the column guess labelled as a guess. And nothing that
    # names one of them as chosen.
    _app, client, _root = served
    status, payload = client.api_get(
        page_url("DEC-001", "datasheets/sheet.pdf", 2)
    )
    assert status == 200, payload
    data = [row for row in payload["rows"] if row["candidate_count"] == 3]
    assert len(data) == 1
    (row,) = data
    assert row["text"] == "3.15 3.30 3.45"
    assert row["labels"] == []
    assert [t["text"] for t in row["tokens"]] == ["3.15", "3.30", "3.45"]
    assert [t["value"] for t in row["tokens"]] == ["3.15", "3.30", "3.45"]
    assert [t["numeric_index"] for t in row["tokens"]] == [0, 1, 2]
    assert [t["header_guess"] for t in row["tokens"]] == ["MIN", "TYP", "MAX"]
    assert all(t["candidate"] is True for t in row["tokens"])
    assert not any(
        word in key
        for key in payload
        for word in ("selected", "chosen", "picked")
    ), sorted(payload)
    # the runs, with coordinates, are what the page view draws
    assert payload["spans"][0] == {
        "text": "VOUT Efficiency", "x": 72.0, "y": 700.0, "size": 9.0, "width": 67.5,
    }
    assert payload["span_count"] == len(payload["spans"])
    assert payload["candidate_count"] == 3
    assert payload["limits"] == {
        "max_bytes": 33554432, "max_spans": 1000, "max_candidates": 200,
    }
    assert (payload["prev"], payload["next"]) == (1, 3)
    # the bytes this page was read out of, beside the bytes the lockfile pins
    assert payload["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert payload["pinned_sha256"] == payload["sha256"]
    assert payload["drifted"] is False


def test_a_page_read_reports_drift_from_the_bytes_that_were_pinned(tmp_path):
    """§4: a page's rows and coordinates are facts about specific bytes, and a
    pick is only valid against those. The build keeps using the pin; the picker
    says the file has moved on rather than presenting coordinates from bytes
    nothing pinned as if they were the pinned ones."""
    root = make_root(tmp_path)
    fetch(root)
    changed = pdf_bytes(PROSE, pdf_page(
        pdf_run(72, 700, "VOUT Efficiency"),
        pdf_run(200, 660, "MIN"),
        pdf_run(280, 660, "TYP"),
        pdf_run(200, 640, "3.15"),
        pdf_run(280, 640, "3.95"),
    ), SECOND, BLANK)
    (root / "datasheets" / "sheet.pdf").write_bytes(changed)
    app = start(root)
    try:
        client = Client(app)
        status, files = client.api_get(sources_url("DEC-001"))
        assert status == 200, files
        assert files["files"][0]["state"] == "hash_mismatch"
        status, payload = client.api_get(
            page_url("DEC-001", "datasheets/sheet.pdf", 2)
        )
        assert status == 200, payload
        assert payload["drifted"] is True
        assert payload["sha256"] == hashlib.sha256(changed).hexdigest()
        assert payload["pinned_sha256"] != payload["sha256"]
        # ...and the number on the page is the file's, with the pin still the one
        # a build would evaluate.
        values = [t["value"] for row in payload["rows"] for t in row["tokens"]]
        assert "3.95" in values and "3.30" not in values
    finally:
        app.stop()


# ------------------------------------------------------------- confinement


def test_the_picker_refuses_a_pdf_the_item_does_not_cite(served):
    """§8, first rule: only a file this item cites. The refusal is
    `authorize_source_path`'s own message, so the picker and the fetcher cannot
    disagree about what a `source()` line is allowed to name -- and a datasheet
    cited by *another* item does not authorize this one."""
    _app, client, root = served
    (root / "other.pdf").write_bytes(PDF)
    before = snapshot_tree(root)
    for path in ("other.pdf", "datasheets/other.pdf", "items/decisions.yaml"):
        status, payload = client.api_get(page_url("DEC-001", path))
        assert status == 422, (path, payload)
        assert payload["kind"] == "refused"
        assert "does not cite" in payload["error"], (path, payload)
    # DEC-003 cites a datasheet of its own and no other item's, so it authorizes
    # neither DEC-001's local file nor DEC-002's kept copy.
    for path in ("datasheets/sheet.pdf", REMOTE):
        status, payload = client.api_get(page_url("DEC-003", path))
        assert status == 422, (path, payload)
        assert "another item does not authorize this one" in payload["error"]
    # A remote URL this item does not cite at all is refused the same way, with
    # the same sentence, rather than with the fetch rule that would send the
    # author looking for a lockfile record.
    status, payload = client.api_get(page_url("DEC-001", "https://example.com/x.pdf"))
    assert status == 422
    assert "does not cite 'https://example.com/x.pdf'" in payload["error"]
    assert snapshot_tree(root) == before, "a refused read wrote something"


def test_the_picker_refuses_an_absolute_path_and_a_path_that_escapes_the_root(served):
    # Canonicalization is `classify()`'s, not this slice's, and it refuses
    # rather than guesses: an absolute path, a scheme, a backslash, a `..` that
    # leaves the root, and a symlink out of it.
    _app, client, root = served
    outside = root.parent / "outside.pdf"
    outside.write_bytes(PDF)
    (root / "datasheets" / "escape.pdf").symlink_to(outside)
    before = snapshot_tree(root)
    for path in (
        "/etc/passwd",
        str(outside),
        "../../etc/passwd",
        "datasheets/../../outside.pdf",
        "C:/Windows/win.ini",
        "file:///etc/passwd",
        "datasheets\\sheet.pdf",
    ):
        status, payload = client.api_get(page_url("DEC-001", path))
        assert status == 422, (path, payload)
        assert payload["kind"] == "refused"
        assert "citation path" in payload["error"], (path, payload)
    status, payload = client.api_get(page_url("DEC-001", "datasheets/escape.pdf"))
    assert status == 422
    assert "resolves outside the project root" in payload["error"]
    assert snapshot_tree(root) == before, "a refused read wrote something"


def test_without_the_pdf_extra_the_picker_offers_no_pdfs_and_shows_the_hint(
    tmp_path, monkeypatch,
):
    """§8, §11. A server without `refdes[pdf]` offers no PDFs and says what to
    install, in the one sentence `section:` already uses -- not "no source
    reader for '.pdf' files", which would send an author looking for a code
    change that does not exist.

    The gate is exercised rather than argued about: the import is taken away and
    the registration decision re-run, which is the same decision a machine
    without the extra makes at import time.
    """
    import sys

    from refdes import sources as sources_mod

    root = served_project(tmp_path)
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(sources_url("DEC-001"))
        assert status == 200 and payload["files"][0]["reader"] == "pdf"
    finally:
        app.stop()

    monkeypatch.setitem(sys.modules, "pypdf", None)
    sources_mod.register_pdf_reader()
    try:
        app = start(root)
        try:
            client = Client(app)
            for ref, path in (
                ("DEC-001", "datasheets/sheet.pdf"),
                ("DEC-002", REMOTE),
            ):
                status, payload = client.api_get(sources_url(ref))
                assert status == 200, (ref, payload)
                assert payload["files"] == [], (ref, payload)
                reasons = " ".join(p["problem"] for p in payload["problems"])
                assert citations_mod.PDF_EXTRA_HINT in reasons, (ref, reasons)
                assert "pip install refdes[pdf]" in reasons
                assert "no source reader" not in reasons
            status, payload = client.api_get(
                page_url("DEC-001", "datasheets/sheet.pdf")
            )
            assert status == 422
            assert citations_mod.PDF_EXTRA_HINT in payload["error"]
        finally:
            app.stop()
    finally:
        del sys.modules["pypdf"]
        sources_mod.register_pdf_reader()


def test_no_pdf_bytes_and_no_absolute_server_path_appear_in_any_response(tmp_path):
    """§8: under option A no PDF byte leaves the process at all -- the responses
    are JSON of extracted text, coordinates and numbers. Every string in every
    payload is walked, on the succeeding and the failing paths, because the leak
    this project has already had came from a fixup that covered one branch."""
    root = served_project(tmp_path)
    (root / "datasheets" / "junk.pdf").write_bytes(b"this is not a PDF")
    (root / "items" / "decisions.yaml").write_text(
        ITEMS + "  - id: DEC-008\n"
        "    citations:\n"
        "      - path: datasheets/junk.pdf\n"
        "      - path: datasheets/missing.pdf\n",
        encoding="utf-8",
    )
    app = start(root)
    try:
        client = Client(app)
        absolute = str(root.resolve())
        payloads = [
            client.api_get(sources_url(ref))[1]
            for ref in ("DEC-001", "DEC-002", "DEC-003", "DEC-008")
        ]
        payloads += [
            client.api_get(page_url("DEC-001", "datasheets/sheet.pdf", page))[1]
            for page in (1, 2, 3, 4, 5, 0, 99)
        ]
        payloads += [
            client.api_get(page_url("DEC-008", "datasheets/junk.pdf"))[1],
            client.api_get(page_url("DEC-001", "/etc/passwd"))[1],
            client.api_get(page_url("DEC-003", "datasheets/sheet.pdf"))[1],
        ]
        for payload in payloads:
            for text in strings(payload):
                assert absolute not in text, text
                assert not text.startswith("/"), text
                assert "\\" not in text, text
                assert "%PDF" not in text, text
        # the unreadable datasheet is named by its project-relative label, with
        # pypdf's own message under it and no traceback
        junk = payloads[-3]
        assert junk["kind"] == "refused"
        assert "datasheets/junk.pdf: pypdf could not read the PDF" in junk["error"]
        assert "Traceback" not in junk["error"]
        # a missing file is named without the server path the OS error carries
        missing = client.api_get(page_url("DEC-008", "datasheets/missing.pdf"))[1]
        assert missing["kind"] == "refused"
        assert "datasheets/missing.pdf: cannot read file" in missing["error"]
        assert absolute not in missing["error"]
        # and the raw response is JSON, not a byte of the document
        status, _headers, body = client.request(
            "GET", page_url("DEC-001", "datasheets/sheet.pdf", 2), token=True
        )
        assert status == 200
        assert b"%PDF" not in body
        assert json.loads(body)["reader"] == "pdf"
    finally:
        app.stop()


def test_the_picker_requires_the_launch_token_on_pdf_reads(served):
    # The launch token is required on reads as well as writes, and that is
    # inherited: these are `/api/` routes, so the framework's check runs before
    # any of this code does. The session cookie alone is not enough -- the
    # header is what a cross-site page cannot set.
    _app, client, _root = served
    for path in (
        sources_url("DEC-001"),
        page_url("DEC-001", "datasheets/sheet.pdf"),
        page_url("DEC-001", "datasheets/sheet.pdf", 2),
        sources_url("DEC-001", "/entries") + "?path=datasheets/sheet.pdf",
    ):
        status, headers, body = client.request("GET", path)
        assert status == 403, path
        assert b"token" in body
        status, _h, _b = client.request(
            "GET", path, headers={"X-Refdes-Token": "wrong"}
        )
        assert status == 403, path
        status, _h, _b = client.request("GET", path, cookie=True)
        assert status == 403, path
        assert client.api_get(path)[0] in (200, 422), path


def test_a_no_write_server_still_browses_pdf_pages(tmp_path):
    # A read-only server is still a reader: browsing a datasheet is a read, and
    # the refusal that belongs to a write is the one the edit route already
    # carries. This is the read half of the accept half that Slice P-C adds.
    root = served_project(tmp_path)
    app = start(root, read_only=True)
    try:
        client = Client(app)
        status, payload = client.api_get(
            page_url("DEC-001", "datasheets/sheet.pdf")
        )
        assert status == 200, payload
        assert payload["page"] == 2
        before = snapshot_tree(root)
        status, payload = client.api_post(
            "/api/item/DEC-001/edit",
            {"op": "set_field", "field": "x", "value": "y",
             "expected_revision": "0" * 64},
        )
        assert status == 403 and "--no-write" in payload["error"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


# ------------------------------------------------------------ nothing was written


def test_reading_a_pdf_page_writes_nothing_anywhere(tmp_path):
    """The whole surface, in one assertion. These routes are reads, so the
    project -- item files, the datasheet, the kept copy and the citation
    lockfile -- must come out byte for byte as it went in. Accept, which writes
    the lockfile, is Slice P-C; this is the line that keeps Slice P-A honest
    until then."""
    root = served_project(tmp_path)
    lock = (root / ".refdes" / "citations.yaml").read_bytes()
    assert b"datasheets/sheet.pdf" in lock  # the fixture really did pin something
    app = start(root)
    try:
        client = Client(app)
        before = snapshot_tree(root)
        calls = [
            sources_url("DEC-001"),
            sources_url("DEC-002"),
            page_url("DEC-001", "datasheets/sheet.pdf"),
            page_url("DEC-001", "datasheets/sheet.pdf", 1),
            page_url("DEC-001", "datasheets/sheet.pdf", 4),
            page_url("DEC-001", "datasheets/sheet.pdf", 99),
            page_url("DEC-002", REMOTE),
            page_url("DEC-003", REMOTE),
            page_url("DEC-001", "other.pdf"),
            page_url("DEC-001", "/etc/passwd"),
            sources_url("NOPE-999"),
            page_url("DEC-001", "datasheets/sheet.pdf"),
        ]
        for call in calls:
            status, _payload = client.api_get(call)
            assert status in (200, 400, 404, 422), (call, status)
            assert snapshot_tree(root) == before, call
        assert (root / ".refdes" / "citations.yaml").read_bytes() == lock
    finally:
        app.stop()
