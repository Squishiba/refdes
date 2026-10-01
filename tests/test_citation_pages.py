"""`page:` -- a hand-read page number, checked against the document it names.

The companion to `tests/test_citation_sections.py`. A `section:` is resolved
against the pinned bytes at `refdes fetch` time; a `page:` is typed by a human
and was, until now, checked by nobody at any time -- `page: "99"` on an 8-page
PDF, `page: "0"` and `page: "eight"` all passed `check`, `build`,
`build --require-citations` and `audit`, and published a dead `#page=` fragment
(in-prog-logs/pdf-picker-exercise.md P1).

Two conditions, deliberately of different shapes:

- **Shape** needs no file, so it is a declaration error at load, beside
  `section: must be a non-empty string`. It shares one grammar with the
  editor picker (`citations.page_number`), because two page grammars in one
  tree is how `page: 0` ends up meaning page 1 on one surface and an error on
  another.
- **Range** needs the page count. `refdes fetch` has the bytes and records the
  count in the lockfile next to the sha256; `check`/`build` read it from there
  and never open a PDF, which is what keeps the hermetic promise.

Every test asserts on the diagnostic as much as on the verdict: the value of
this feature is that a wrong page is never quietly published.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from conftest import write_project_config
from pypdf import PdfWriter

from refdes import build as build_mod
from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes import docs_url, parse, render
from refdes.schema import load_project

PAGE_SCHEMA = """\
site: {title: "Page Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title:      { type: text, required: true, on_change: invalidate }
      datasheets: { type: citations, on_change: invalidate }
"""


def _item(*citations: str) -> str:
    """One item whose `datasheets:` block is the given citation mappings."""
    return (
        "defaults:\n"
        "  type: component\n"
        "items:\n"
        "  - id: CMP-001\n"
        "    title: Regulator\n"
        "    datasheets:\n" + "".join(f"      - {c}\n" for c in citations)
    )


def _page_item(page: str, path: str = "docs/manual.pdf") -> str:
    return _item(f"path: {path}\n        page: {json.dumps(page)}")


def pdf_bytes(pages=8) -> bytes:
    """`pages` blank pages as real PDF bytes -- the count is all this needs."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(200, 200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _write_pdf(path, pages=8):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes(pages))
    return path


def _project(tmp_path, item_text=None, pages=8):
    write_project_config(tmp_path, PAGE_SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "cmp.yaml").write_text(
        item_text if item_text is not None else _page_item("4"),
        encoding="utf-8",
    )
    _write_pdf(tmp_path / "docs" / "manual.pdf", pages=pages)
    return tmp_path


def _load_only(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    return project


def _build(root, **kw):
    project = _load_only(root)
    build_mod.build(project, **kw)
    return project


def _fetch(root, **kw):
    def no_network(url):
        raise AssertionError("a local citation must not touch the network")

    return citations_mod.fetch_all(_load_only(root), fetcher=no_network, **kw)


def _record(root, key="docs/manual.pdf"):
    text = (root / ".refdes" / "citations.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["citations"][key]


def _messages(project):
    return [str(d) for d in project.errors] + [str(d) for d in project.warnings]


# --------------------------------------------------------------- shape (load)

BAD_PAGES = ["0", "-1", "eight", "xiv", "1.5", "2-4", "  ", "", "9 9"]

RULE = "is not a page number -- page: must be a positive integer, counted from 1"


@pytest.mark.parametrize("page", BAD_PAGES)
def test_a_page_that_is_not_a_positive_integer_is_a_declaration_error(tmp_path, page):
    """Shape needs no file, so it is refused at load beside every other
    malformed citation -- `page: 0` used to render as `#page=0`, which most
    viewers read as page 1 and none of them as page 0."""
    root = _project(tmp_path, _page_item(page))
    project = _build(root)
    assert not project.warnings, _messages(project)
    assert [str(e) for e in project.errors] == [
        (
            f"ERROR   items/cmp.yaml:4 [CMP-001] — datasheets[0]: page: {page!r} "
            f"{RULE}.{_expected_remedy(page)}"
            f" See {docs_url.CITATION_PAGE_DOCS}."
        )
    ]


def _expected_remedy(page: str) -> str:
    """The remedy sentence `_page_remedy` picks for a refused value, written out
    rather than imported: a test that called the function it is testing would
    pass whatever that function returned, including nothing."""
    if re.fullmatch(r"\d+\s*[-\u2010\u2013\u2014]\s*\d+", page.strip()):
        return " One entry names one page, so a range is one entry per page for the same path."
    if page.strip() and not any(ch.isdigit() for ch in page):
        return (
            " A printed page number is not a page index: page: counts the"
            " PDF's own sheets from 1, the same number the rendered link opens."
        )
    return ""


@pytest.mark.parametrize("page", BAD_PAGES)
def test_a_malformed_page_fails_check(tmp_path, page, capsys):
    root = _project(tmp_path, _page_item(page))
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"]) == 1
    captured = capsys.readouterr()
    assert f"page: {page!r} is not a page number" in captured.out + captured.err
    assert "1 items, 1 errors, 0 warnings" in captured.out


# --------------------------------------------------- the remedy (F2)


@pytest.mark.parametrize(
    "page,remedy",
    [
        ("2-4", "a range is one entry per page"),
        ("2 – 4", "a range is one entry per page"),
        ("xiv", "counts the PDF's own sheets from 1"),
        ("eight", "counts the PDF's own sheets from 1"),
    ],
)
def test_a_refused_page_says_what_to_write_instead(tmp_path, page, remedy):
    """F2 of `in-prog-logs/user-sim-release-gate-run4.md`: this is the only
    diagnostic in the page-check delta that stopped at naming the rule, and it
    is the delta's only breaking change -- a project with `page: "14-15"` that
    passed yesterday now fails with nothing to act on. The two shapes named here
    are the ones where the rule is not a remedy on its own, because the author
    believes they have cited something: a span, and a printed page number (a
    book's front matter is numbered in roman numerals, which is why `xiv` is the
    common one)."""
    project = _build(_project(tmp_path, _page_item(page)))
    assert len(project.errors) == 1, _messages(project)
    message = project.errors[0].message
    assert remedy in message, message
    # The published docs, never a repo-relative path (docs_url.py's rule: the
    # wheel ships no docs/*.md).
    assert docs_url.CITATION_PAGE_DOCS in message
    assert "docs/troubleshooting.md" not in message


@pytest.mark.parametrize("page", ["0", "-1", "1.5", "9 9", ""])
def test_a_page_the_rule_already_answers_gets_no_filler_sentence(tmp_path, page):
    """This fires once per bad `page:`, so a remedy that restates the rule back
    at the user is noise on the shapes the rule already covers. The docs pointer
    is still there for all of them."""
    project = _build(_project(tmp_path, _page_item(page)))
    assert len(project.errors) == 1, _messages(project)
    message = project.errors[0].message
    assert message == (
        f"datasheets[0]: page: {page!r} {RULE}."
        f" See {docs_url.CITATION_PAGE_DOCS}."
    ), message


def test_a_span_is_cited_as_one_entry_per_page(tmp_path):
    """The remedy names a shape, so the shape has to work. One entry per page for
    the same path builds clean and renders one row per page, each with its own
    `#page=` fragment -- and `section:` is the other answer someone reaches for,
    which is one page, not a span (the next test)."""
    root = _project(
        tmp_path,
        _item(
            'path: docs/manual.pdf\n        page: "2"',
            'path: docs/manual.pdf\n        page: "4"',
        ),
    )
    _fetch(root)
    project = _build(root)
    assert not _messages(project), _messages(project)
    html = (Path(render.render_site(project)) / "cmp-001.html").read_text(
        encoding="utf-8"
    )
    assert "#page=2" in html and "#page=4" in html


def test_an_outline_title_resolves_to_one_page_not_a_span(tmp_path):
    """Why `section:` is not the remedy for a range: an 8-page PDF whose outline
    entry sits on sheet 3 resolves to `3`, and there is no shape of `section:`
    that says 'sheets 3 to 5'. A section title is the citation for a heading that
    moves between revisions, which is a different problem."""
    writer = PdfWriter()
    for _ in range(8):
        writer.add_blank_page(200, 200)
    writer.add_outline_item("Thermal Information", 2)  # 0-based: sheet 3
    buf = io.BytesIO()
    writer.write(buf)

    root = _project(
        tmp_path,
        _item('path: docs/manual.pdf\n        section: Thermal Information'),
    )
    (root / "docs" / "manual.pdf").write_bytes(buf.getvalue())
    _fetch(root)
    project = _build(root)
    assert not _messages(project), _messages(project)
    assert _record(root)["sections"] == {"Thermal Information": 3}


def test_an_unquoted_integer_page_is_accepted_as_the_number_it_is(tmp_path):
    """`page: 4` in YAML is an int, not a string. The schema types it as a
    string but nothing enforces that, and the number is unambiguous -- so it is
    read as the number it says rather than refused for its type."""
    root = _project(
        tmp_path,
        "defaults:\n  type: component\nitems:\n  - id: CMP-001\n"
        "    title: Regulator\n    datasheets:\n"
        "      - path: docs/manual.pdf\n        page: 4\n",
    )
    assert _fetch(root)[0].page_warnings == []
    project = _build(root)
    assert not _messages(project), _messages(project)
    assert project.item_by_id("CMP-001").citations[0].spec.page == "4"
    html = (Path(render.render_site(project)) / "cmp-001.html").read_text(
        encoding="utf-8"
    )
    assert "#page=4" in html


def test_the_declaration_check_and_the_editor_picker_share_one_grammar():
    """One grammar, not two: the picker's `_page_number` *is*
    `citations.page_number`, so a page the editor will not open is a page the
    loader will not accept."""
    from refdes.serve import sources as serve_sources

    assert serve_sources._page_number is citations_mod.page_number
    for text, expected in [
        ("2", 2), (" 14 ", 14), ("", None), ("0", None), ("-3", None),
        ("eight", None), ("xiv", None), ("1.5", None), ("２", None),
    ]:
        assert citations_mod.page_number(text) == expected, text


# -------------------------------------------------------------- range (count)


def test_a_page_past_the_end_is_warned_at_check_and_an_error_under_the_gate(tmp_path):
    """`page: 99` on an 8-page document. The picker's own sentence for it, at
    check time, with the severity a wrong link gets in this table: a warning
    naming the citer, escalated by `--require-citations`."""
    root = _project(tmp_path, _page_item("99"))
    _fetch(root)
    why = "docs/manual.pdf: page 99 is not in this document -- it has 8 page(s)"

    project = _build(root)
    assert not project.errors, _messages(project)
    assert [str(w) for w in project.warnings] == [
        f"WARNING items/cmp.yaml:4 [CMP-001] — {why}"
    ]

    gated = _build(root, require_citations=True)
    assert not gated.warnings
    assert [str(e) for e in gated.errors] == [f"ERROR   items/cmp.yaml:4 [CMP-001] — {why}"]

    # and it reaches the rendered Detail cell, the way a section failure does
    html = (Path(render.render_site(project)) / "cmp-001.html").read_text(
        encoding="utf-8"
    )
    assert "page 99 is not in this document" in html


def test_an_out_of_range_page_is_reported_for_every_citer(tmp_path):
    root = _project(
        tmp_path,
        "defaults:\n  type: component\nitems:\n"
        "  - id: CMP-001\n    title: One\n    datasheets:\n"
        "      - path: docs/manual.pdf\n        page: \"99\"\n"
        "  - id: CMP-002\n    title: Two\n    datasheets:\n"
        "      - path: docs/manual.pdf\n        page: \"99\"\n",
    )
    _fetch(root)
    project = _build(root)
    assert [w.item_id for w in project.warnings] == ["CMP-001", "CMP-002"], (
        _messages(project)
    )


def test_cli_check_warns_and_cli_build_require_citations_fails(tmp_path, capsys):
    root = _project(tmp_path, _page_item("16"))
    _fetch(root)
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"]) == 0
    out = capsys.readouterr().out
    assert "page 16 is not in this document -- it has 8 page(s)" in out
    assert "1 items, 0 errors, 1 warnings" in out

    assert cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "build", "--require-citations"]
    ) == 1
    built = capsys.readouterr()
    assert "ERROR" in built.out + built.err
    assert "page 16 is not in this document" in built.out + built.err


def test_fetch_reports_a_page_the_pinned_bytes_do_not_have(tmp_path, capsys):
    """`refdes fetch` is the command with the bytes in hand, so it is where the
    page count is read -- and a citation that does not fit the document is said
    out loud there, not only at build time."""
    root = _project(tmp_path, _page_item("99"))
    code = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "fetch"])
    captured = capsys.readouterr()
    assert code == 0  # the pin succeeded; the citation is what needs attention
    assert (
        "WARNING  docs/manual.pdf: page 99 is not in this document -- it has "
        "8 page(s) (cited by CMP-001)" in captured.err
    ), captured.err
    assert _record(root)["sha256"] == hashlib.sha256(
        (root / "docs" / "manual.pdf").read_bytes()
    ).hexdigest()
    assert _record(root)["page_count"] == 8


def test_repinning_to_a_shorter_revision_reports_the_page_that_is_gone(tmp_path):
    """The sharpest case in the report: page 6 pinned against an 8-page
    document, then the document replaced by a 4-page revision. The re-pin
    re-hashed the file, could see it had four pages, and still published a link
    to page 6."""
    root = _project(tmp_path, _page_item("6"), pages=8)
    _fetch(root)
    assert _record(root)["page_count"] == 8
    assert not _build(root).warnings

    _write_pdf(root / "docs" / "manual.pdf", pages=4)
    results = _fetch(root, update=True)
    assert not results[0].error
    assert results[0].page_warnings == [
        (
            "docs/manual.pdf: page 6 is not in this document -- it has 4 page(s) "
            "(cited by CMP-001)"
        )
    ]
    assert _record(root)["page_count"] == 4

    project = _build(root)
    assert [str(w) for w in project.warnings] == [
        (
            "WARNING items/cmp.yaml:4 [CMP-001] — docs/manual.pdf: page 6 is not "
            "in this document -- it has 4 page(s)"
        )
    ]


def test_repinning_under_item_scope_still_checks_the_other_items_pages(tmp_path):
    """A re-pin replaces the whole record, so it has to re-check every item's
    page, not only this run's `--item` scope -- scoping a fetch narrows which
    paths are re-pinned, not what re-pinning them means."""
    root = _project(
        tmp_path,
        "defaults:\n  type: component\nitems:\n"
        "  - id: CMP-001\n    title: One\n    datasheets:\n"
        "      - path: docs/manual.pdf\n        page: \"2\"\n"
        "  - id: CMP-002\n    title: Two\n    datasheets:\n"
        "      - path: docs/manual.pdf\n        page: \"7\"\n",
        pages=8,
    )
    _fetch(root)
    _write_pdf(root / "docs" / "manual.pdf", pages=4)
    results = _fetch(root, item_id="CMP-001", update=True)
    assert results[0].page_warnings == [
        (
            "docs/manual.pdf: page 7 is not in this document -- it has 4 page(s) "
            "(cited by CMP-002)"
        )
    ]


def test_a_page_the_document_does_have_is_never_reported(tmp_path):
    root = _project(tmp_path, _page_item("4"))
    _fetch(root)
    project = _build(root)
    assert not _messages(project), _messages(project)
    assert project.item_by_id("CMP-001").citations[0].state == "ok"
    html = (Path(render.render_site(project)) / "cmp-001.html").read_text(
        encoding="utf-8"
    )
    assert "#page=4" in html


def test_check_never_opens_the_pdf_to_range_check_a_page(tmp_path, monkeypatch):
    """The hermetic promise, asserted rather than assumed: the page count is
    read out of the lockfile, so `check`/`build` work with no PDF machinery at
    all -- including with pypdf entirely absent."""
    root = _project(tmp_path, _page_item("99"))
    _fetch(root)

    def boom(*a, **kw):
        raise AssertionError("a build must not parse the document")

    monkeypatch.setattr(citations_mod, "page_count", boom)
    monkeypatch.setattr(citations_mod, "outline_titles", boom)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    project = _build(root)
    assert [str(w) for w in project.warnings] == [
        (
            "WARNING items/cmp.yaml:4 [CMP-001] — docs/manual.pdf: page 99 is not "
            "in this document -- it has 8 page(s)"
        )
    ]


def test_a_remote_hash_only_citation_records_its_page_count_too(tmp_path):
    """The bytes are downloaded either way, so the count is known at pin time
    even when no copy is kept -- and it stays a fact about the pinned sha256
    whether or not those bytes are still on this machine."""
    root = _project(tmp_path, _page_item("99", path="https://example.com/ds.pdf"))
    results = citations_mod.fetch_all(
        _load_only(root), fetcher=lambda url: pdf_bytes(8)
    )
    assert not results[0].error
    assert results[0].page_warnings == [
        (
            "https://example.com/ds.pdf: page 99 is not in this document -- it has "
            "8 page(s) (cited by CMP-001)"
        )
    ]
    record = _record(root, "https://example.com/ds.pdf")
    assert record["page_count"] == 8 and record["kept_copy"] is False


def test_the_page_count_is_recorded_only_while_a_page_is_cited(tmp_path):
    """Lockfile hygiene, the same rule a section follows: nothing is recorded
    for a citation that names no page, so an existing project's lockfile does
    not change under it."""
    root = _project(tmp_path, _item("path: docs/manual.pdf"))
    _fetch(root)
    assert "page_count" not in _record(root)


def test_a_citation_with_no_page_never_counts_pages(tmp_path, monkeypatch):
    root = _project(tmp_path, _item("path: docs/manual.pdf"))
    monkeypatch.setattr(
        citations_mod,
        "page_count",
        lambda *a, **kw: pytest.fail("no page is cited; nothing to count"),
    )
    assert _fetch(root)[0].page_warnings == []


def test_a_page_on_a_document_that_is_not_a_pdf_is_not_a_pdf_problem(tmp_path):
    """Only a PDF has pages. A `page:` on some other kind of cited file is not
    something the page counter can check, and it must not be reported as if it
    had tried and failed."""
    root = _project(tmp_path, _page_item("3", path="docs/notes.txt"))
    (root / "docs" / "notes.txt").write_text("three pages if you print it\n")
    assert _fetch(root)[0].page_warnings == []


def test_a_local_file_that_changed_is_reported_as_changed_not_out_of_range(tmp_path):
    """The recorded count belongs to the pinned bytes. Once the file on disk is
    something else, "the page is out of range" against the *recorded* count would
    be describing a document nobody is linking to -- the changed-file warning
    already names the remedy."""
    root = _project(tmp_path, _page_item("99"))
    _fetch(root)
    _write_pdf(root / "docs" / "manual.pdf", pages=2)

    project = _build(root)
    assert [str(w) for w in project.warnings] == [
        (
            "WARNING <project> — local citation 'docs/manual.pdf' has changed "
            "since it was pinned -- review the change, then run 'refdes fetch "
            "--update --path docs/manual.pdf' (cited by CMP-001)"
        )
    ]


# --------------------------------------------------------- the missing extra

UNCARRIED = (
    "counting a document's pages needs the optional PDF extra: "
    "pip install refdes[pdf]"
)
UNCHECKED = (
    "the pages could not be counted to check the page numbers cited here -- "
    + UNCARRIED
)


def test_without_the_pdf_extra_the_page_is_not_checked_and_fetch_says_so(
    tmp_path, monkeypatch
):
    """The documented `section:` fallback, in the same words: the pin lands, the
    page is not checked, and the reason names the install."""
    root = _project(tmp_path, _page_item("99"))
    monkeypatch.setitem(sys.modules, "pypdf", None)
    results = _fetch(root)
    assert results[0].page_warnings == [f"docs/manual.pdf: {UNCHECKED}"]
    record = _record(root)
    assert "page_count" not in record
    assert record["page_count_error"] == UNCARRIED
    assert record["sha256"] == hashlib.sha256(
        (root / "docs" / "manual.pdf").read_bytes()
    ).hexdigest()

    project = _build(root)
    assert [str(w) for w in project.warnings] == [
        (
            "WARNING items/cmp.yaml:4 [CMP-001] — the page numbers cited for "
            "docs/manual.pdf are not checked: the lockfile records no page count "
            f"for this document because {UNCARRIED} -- run 'refdes fetch --update "
            "--path docs/manual.pdf' to establish it"
        )
    ]
    assert _build(root, require_citations=True).errors


def test_without_the_extra_a_section_citation_still_fails_loudly(tmp_path, monkeypatch):
    """The two fallbacks stay distinguishable: a `section:` that could not be
    resolved is a FAILED (nothing was recorded), while a `page:` that could not
    be checked is a warning (the number is the author's, and was not recorded
    as checked either way)."""
    root = _project(
        tmp_path,
        _item("path: docs/manual.pdf\n        page: \"4\"\n        section: Deep"),
    )
    monkeypatch.setitem(sys.modules, "pypdf", None)
    results = _fetch(root)
    assert results[0].section_errors == [
        (
            "docs/manual.pdf: sections 'Deep' (cited by CMP-001): section: needs "
            "the optional PDF extra: pip install refdes[pdf]"
        )
    ]
    assert results[0].page_warnings == [f"docs/manual.pdf: {UNCHECKED}"]


def test_a_page_on_an_unreadable_pdf_is_reported_as_unreadable(tmp_path):
    """pypdf's own message, never a traceback -- the same shape `section:`
    already has for bytes it cannot open."""
    root = _project(tmp_path, _page_item("99"))
    (root / "docs" / "manual.pdf").write_bytes(b"this is not a PDF")
    results = _fetch(root)
    assert len(results[0].page_warnings) == 1
    message = results[0].page_warnings[0]
    assert message.startswith("docs/manual.pdf: the pages could not be counted")
    assert "pypdf could not read the PDF" in message
    assert "Traceback" not in message
    # A document whose pages cannot be counted is not a document with no pages.
    assert "page_count" not in _record(root)