"""`section:` -- resolving a human-written outline title to a page number.

Finding 23 Part 2. Resolution happens at `refdes fetch` time against the bytes
being pinned; `build`/`check` read the recorded page out of the lockfile and
never open a PDF. Every test here asserts on a *failure* message as often as on
a resolved page, because the value of this feature is that a section which
cannot be resolved is never silently left without one.

The fixture PDF deliberately has its outline entries added in an order that
does not match their page numbers, so an implementation that counted titles
instead of asking pypdf for the destination page fails rather than passing by
luck.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import yaml
from conftest import write_project_config
from pypdf import PdfWriter

from refdes import build as build_mod
from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes import parse, render
from refdes.schema import load_project

SECTION_SCHEMA = """\
site: {title: "Section Test", out: _site}
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

# Outline order deliberately does not match page order: "Thermal Design" is the
# first entry but points at page index 0 (page 1), "Deep Thing" is nested under
# it and points at page index 3 (page 4), "Intro" is third but page index 1.
OUTLINE = [
    ("Thermal Design", 0, None),
    ("Appendix", 2, None),
    ("Intro", 1, None),
    ("Deep Thing", 3, "Thermal Design"),
    ("Absolute  Maximum\nRatings", 2, None),
]

ITEM = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: Regulator
    datasheets:
      - path: docs/manual.pdf
        section: Thermal Design
  - id: CMP-002
    title: Layout
    datasheets:
      - path: docs/manual.pdf
        section: Deep Thing
"""


def make_pdf(path, pages=4, outline=OUTLINE):
    """A real PDF with real bookmarks -- blank pages are enough for pypdf."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(200, 200)
    refs = {}
    for title, page, parent in outline:
        refs[title] = writer.add_outline_item(
            title, page, parent=refs[parent] if parent else None
        )
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def _project(tmp_path, item_text=ITEM, pdf_pages=4, outline=OUTLINE):
    write_project_config(tmp_path, SECTION_SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "cmp.yaml").write_text(item_text, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    make_pdf(tmp_path / "docs" / "manual.pdf", pages=pdf_pages, outline=outline)
    return tmp_path


def _load_only(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    return project


def _build(root, **kw):
    project = _load_only(root)
    build_mod.build(project, **kw)
    return project


def _fetch(root):
    def no_network(url):
        raise AssertionError("a local citation must not touch the network")

    return citations_mod.fetch_all(_load_only(root), fetcher=no_network)


def _lockfile(root):
    path = root / ".refdes" / "citations.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["citations"]


# ------------------------------------------------------------------- resolving


def test_section_resolves_top_level_and_nested_titles_to_the_right_page(tmp_path):
    """Nested outline entries are walked, and the page is the destination page
    -- not the entry's position in the outline."""
    _project(tmp_path)
    results = _fetch(tmp_path)
    assert not results[0].error and not results[0].section_errors
    assert results[0].sections == {"Deep Thing": 4, "Thermal Design": 1}

    record = _lockfile(tmp_path)["docs/manual.pdf"]
    assert record["sections"] == {"Deep Thing": 4, "Thermal Design": 1}
    # the pin itself is unaffected by the new field
    assert record["sha256"] == hashlib.sha256(
        (tmp_path / "docs" / "manual.pdf").read_bytes()
    ).hexdigest()


def test_lockfile_records_only_the_sections_actually_cited(tmp_path):
    _project(tmp_path, item_text=ITEM.split("  - id: CMP-002")[0])
    _fetch(tmp_path)
    assert _lockfile(tmp_path)["docs/manual.pdf"]["sections"] == {"Thermal Design": 1}


def test_section_matching_normalises_whitespace(tmp_path):
    """The outline title has a double space and a newline in it; the citation
    spells it on one line with single spaces."""
    _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Absolute maximum
    datasheets:
      - path: docs/manual.pdf
        section: Absolute Maximum Ratings
""",
    )
    results = _fetch(tmp_path)
    assert not results[0].section_errors
    assert results[0].sections == {"Absolute Maximum Ratings": 3}


def test_citation_without_section_never_needs_pypdf(tmp_path, monkeypatch):
    """No `section:` anywhere -- pypdf must not be imported at all."""
    _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: No section
    datasheets:
      - path: docs/manual.pdf
""",
    )

    def boom(*a, **kw):
        raise AssertionError("pypdf must not be imported without a section:")

    monkeypatch.setattr(citations_mod, "outline_titles", boom)
    results = _fetch(tmp_path)
    assert not results[0].error and not results[0].section_errors


# ------------------------------------------- scope: a re-pin re-resolves all


TWO_CITERS = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: Regulator
    datasheets:
      - path: docs/manual.pdf
        section: Thermal
  - id: CMP-002
    title: Placement
    datasheets:
      - path: docs/manual.pdf
        section: Intro
"""

V1 = [("Intro", 0, None), ("Thermal", 2, None)]
# The new revision moves both headings -- which is the entire point: a page
# resolved against v1 is simply wrong about v2.
V2 = [("Cover", 0, None), ("Intro", 1, None), ("Thermal", 4, None)]


def test_scoped_update_reresolves_other_items_sections(tmp_path):
    """`--update --item CMP-001` re-pins the file, and a re-pin changes what
    every page number in the record means. CMP-002's section is out of this
    run's scope but in the same document, so it is re-resolved too -- carrying
    its v1 page over would leave the build linking into the wrong page of the
    bytes it just pinned, with nothing said about it."""
    root = _project(tmp_path, item_text=TWO_CITERS, outline=V1)
    _fetch(root)
    assert _lockfile(root)["docs/manual.pdf"]["sections"] == {"Intro": 1, "Thermal": 3}

    make_pdf(root / "docs" / "manual.pdf", pages=5, outline=V2)
    results = citations_mod.fetch_all(
        _load_only(root), item_id="CMP-001", update=True, fetcher=lambda u: b""
    )
    assert not results[0].error and not results[0].section_errors
    record = _lockfile(root)["docs/manual.pdf"]
    assert record["sections"] == {"Intro": 2, "Thermal": 5}
    assert record["sections_sha256"] == record["sha256"]

    # and the build agrees, for the item that was never in scope
    project = _build(root)
    assert project.item_by_id("CMP-002").citations[0].section_page == "2"
    assert not project.warnings and not project.errors
    out = render.render_site(project)
    html = (Path(out) / "cmp-002.html").read_text(encoding="utf-8")
    assert "#page=2" in html


def test_scoped_update_reports_a_gone_section_whose_citer_is_out_of_scope(tmp_path):
    """Same scope argument on the failure side: the section that vanished is
    CMP-002's, and CMP-002 is the citer that has to be told, even though only
    CMP-001 was asked for."""
    root = _project(tmp_path, item_text=TWO_CITERS, outline=V1)
    _fetch(root)

    # the new revision keeps Thermal (CMP-001, the item in scope) and drops
    # Intro -- which is CMP-002's, and CMP-002 is not
    make_pdf(
        root / "docs" / "manual.pdf",
        pages=5,
        outline=[("Cover", 0, None), ("Thermal", 4, None)],
    )
    results = citations_mod.fetch_all(
        _load_only(root), item_id="CMP-001", update=True, fetcher=lambda u: b""
    )
    assert not results[0].error
    assert len(results[0].section_errors) == 1
    message = results[0].section_errors[0]
    assert "CMP-002" in message
    assert "Intro" in message
    assert "the section you cited no longer exists in the new revision (was page 1)" in message
    record = _lockfile(root)["docs/manual.pdf"]
    assert record["sections"] == {"Thermal": 5}
    assert record["sections_sha256"] == record["sha256"]


def test_fetch_drops_a_section_nobody_cites_anymore(tmp_path):
    """A section that stopped being cited stops being recorded -- it is a
    derived value, not a ledger entry."""
    root = _project(tmp_path, item_text=TWO_CITERS, outline=V1)
    _fetch(root)
    assert _lockfile(root)["docs/manual.pdf"]["sections"] == {"Intro": 1, "Thermal": 3}

    (root / "items" / "cmp.yaml").write_text(
        TWO_CITERS.replace("        section: Intro\n", ""), encoding="utf-8"
    )
    _fetch(root)
    assert _lockfile(root)["docs/manual.pdf"]["sections"] == {"Thermal": 3}


# ---------------------------------------- already pinned: bytes must be pinned


def test_already_pinned_changed_local_file_does_not_resolve_section(tmp_path):
    """The skip path resolves a newly cited section from the file on disk --
    but only if that file is still the pinned one. Resolving against a working
    copy that has already moved records a page for bytes nothing pinned, and
    the build has no way to know."""
    root = _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Regulator
    datasheets:
      - path: docs/manual.pdf
""",
        outline=V1,
    )
    _fetch(root)
    pinned = _lockfile(root)["docs/manual.pdf"]["sha256"]

    # the file moves, and a section: appears -- without --update
    make_pdf(root / "docs" / "manual.pdf", pages=5, outline=V2)
    (root / "items" / "cmp.yaml").write_text(
        "defaults:\n  type: component\n"
        "items:\n  - id: CMP-001\n    title: Regulator\n"
        "    datasheets:\n      - path: docs/manual.pdf\n"
        "        section: Thermal\n",
        encoding="utf-8",
    )
    results = _fetch(root)
    assert results[0].skipped is True
    assert len(results[0].section_errors) == 1
    message = results[0].section_errors[0]
    assert "changed since it was pinned" in message
    assert "refdes fetch --update --path docs/manual.pdf" in message
    assert "CMP-001" in message
    record = _lockfile(root)["docs/manual.pdf"]
    assert "sections" not in record and "sections_sha256" not in record
    # nothing was re-pinned behind --update: the pin still names the old bytes
    assert record["sha256"] == pinned


def test_already_pinned_unchanged_local_file_still_resolves(tmp_path):
    """The check above is about changed bytes, not a blanket refusal: an
    unchanged file is the pinned bytes, and resolving from it is correct."""
    root = _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Regulator
    datasheets:
      - path: docs/manual.pdf
""",
        outline=V1,
    )
    _fetch(root)
    (root / "items" / "cmp.yaml").write_text(
        "defaults:\n  type: component\n"
        "items:\n  - id: CMP-001\n    title: Regulator\n"
        "    datasheets:\n      - path: docs/manual.pdf\n"
        "        section: Thermal\n",
        encoding="utf-8",
    )
    results = _fetch(root)
    assert not results[0].section_errors
    assert results[0].sections == {"Thermal": 3}
    record = _lockfile(root)["docs/manual.pdf"]
    assert record["sections"] == {"Thermal": 3}
    assert record["sections_sha256"] == record["sha256"]


# ---------------------------------------------------------------- failures a-f


def test_pdf_with_no_outline_says_so_and_not_that_the_section_is_gone(tmp_path):
    """(a) A PDF with no bookmarks is a different problem from a missing
    section, and the message must not borrow the re-fetch wording."""
    _project(tmp_path, outline=[])
    results = _fetch(tmp_path)
    assert len(results[0].section_errors) == 1
    message = results[0].section_errors[0]
    assert "has no outline (bookmarks)" in message
    assert "cite page: instead" in message
    assert "no longer exists" not in message
    assert "docs/manual.pdf" in message
    assert "CMP-001" in message and "CMP-002" in message


def test_no_matching_title_names_it_and_offers_closest_titles(tmp_path):
    """(b)"""
    _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Typo
    datasheets:
      - path: docs/manual.pdf
        section: Thermal Considerations
""",
    )
    results = _fetch(tmp_path)
    assert len(results[0].section_errors) == 1
    message = results[0].section_errors[0]
    assert "no outline entry titled 'Thermal Considerations'" in message
    assert "Thermal Design" in message  # the closest title, as a hint
    assert "CMP-001" in message


def test_ambiguous_title_lists_every_page_and_picks_none(tmp_path):
    """(c) Two entries with the same title is the document refusing to be
    resolved by title -- taking the first would be a guessed page."""
    _project(
        tmp_path,
        outline=[("Notes", 0, None), ("Notes", 2, None)],
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Ambiguous
    datasheets:
      - path: docs/manual.pdf
        section: Notes
""",
    )
    results = _fetch(tmp_path)
    assert len(results[0].section_errors) == 1
    message = results[0].section_errors[0]
    assert "2 entries titled 'Notes'" in message
    assert "pages 1, 3" in message
    assert results[0].sections == {}
    assert "sections" not in _lockfile(tmp_path)["docs/manual.pdf"]


def test_missing_pypdf_names_the_extra_and_spares_other_citations(tmp_path, monkeypatch):
    """(d) The import is lazy and the error names the fix. A citation with no
    `section:` in the same project still pins normally."""
    _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Needs pypdf
    datasheets:
      - path: docs/manual.pdf
        section: Thermal Design
  - id: CMP-002
    title: Fine without it
    datasheets:
      - path: docs/plain.pdf
""",
    )
    (tmp_path / "docs" / "plain.pdf").write_bytes(b"%PDF plain")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    results = _fetch(tmp_path)
    by_path = {r.path: r for r in results}
    assert by_path["docs/manual.pdf"].section_errors == [
        (
            "docs/manual.pdf: sections 'Thermal Design' (cited by CMP-001): "
            "section: needs the optional PDF extra: pip install refdes[pdf]"
        )
    ]
    assert by_path["docs/plain.pdf"].error == ""
    assert by_path["docs/plain.pdf"].sha256 == hashlib.sha256(b"%PDF plain").hexdigest()


def test_unreadable_pdf_names_the_file_and_pypdf_without_a_traceback(tmp_path):
    """(e)"""
    root = _project(tmp_path)
    (root / "docs" / "manual.pdf").write_bytes(b"this is not a PDF")
    results = _fetch(root)
    assert len(results[0].section_errors) == 1
    message = results[0].section_errors[0]
    assert "docs/manual.pdf" in message
    assert "could not read" in message
    assert "Traceback" not in message


def test_update_reports_a_cited_section_that_no_longer_exists(tmp_path):
    """(f) The sharpest signal of the set: the section you cited is gone from
    the new revision, and here is the page it used to be on."""
    root = _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Regulator
    datasheets:
      - path: docs/manual.pdf
        section: Thermal Design
""",
    )
    first = _fetch(root)
    assert first[0].sections == {"Thermal Design": 1}

    make_pdf(root / "docs" / "manual.pdf", outline=[("Something Else", 1, None)])
    results = citations_mod.fetch_all(_load_only(root), update=True, fetcher=lambda u: b"")
    assert not results[0].error  # the file was fetched fine
    assert len(results[0].section_errors) == 1
    message = results[0].section_errors[0]
    assert "the section you cited no longer exists in the new revision (was page 1)" in message
    assert "CMP-001" in message
    # the stale page is dropped, not left behind for the build to render
    assert "sections" not in _lockfile(root)["docs/manual.pdf"]


# ----------------------------------------------------------------- validation


def test_section_on_a_remote_citation_without_keep_copy_is_an_error(tmp_path):
    """The bytes of a hash-only remote citation are not guaranteed local, so
    resolution would depend on the network -- refuse it, and say what to do."""
    root = _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Remote
    datasheets:
      - path: https://example.com/ds.pdf
        section: Thermal Design
""",
    )
    project = _build(root)
    matches = [d for d in project.errors if "section:" in d.message]
    assert len(matches) == 1
    assert "needs keep_copy: true" in matches[0].message
    assert "cite a local path" in matches[0].message
    assert matches[0].item_id == "CMP-001"
    assert matches[0].file and matches[0].line


@pytest.mark.parametrize("value", ["5", "'   '"])
def test_non_string_or_empty_section_is_an_error(tmp_path, value):
    root = _project(
        tmp_path,
        item_text=f"""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Bad section
    datasheets:
      - path: docs/manual.pdf
        section: {value}
""",
    )
    project = _build(root)
    assert any(
        "section: must be a non-empty string" in d.message for d in project.errors
    )


# ------------------------------------------------------- build/check from lockfile


def _pin_with_sections(root, sections, extra_item=""):
    data = (root / "docs" / "manual.pdf").read_bytes()
    record = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "fetched": "2026-01-01T00:00:00Z",
        "kept_copy": False,
        "bytes": len(data),
    }
    if sections is not None:
        record["sections"] = sections
        # Pages are only meaningful next to the bytes they were read out of.
        record["sections_sha256"] = record["sha256"]
    path = root / ".refdes" / "citations.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"citations": {"docs/manual.pdf": record}}), encoding="utf-8"
    )
    return root


def test_build_resolves_the_page_from_the_lockfile_without_opening_the_pdf(tmp_path):
    root = _project(tmp_path)
    _pin_with_sections(root, {"Thermal Design": 1, "Deep Thing": 4})
    project = _build(root)
    assert project.item_by_id("CMP-001").citations[0].section_page == "1"
    assert project.item_by_id("CMP-002").citations[0].section_page == "4"
    assert not project.warnings and not project.errors

    payload = render.items_json(project)
    entry = next(i for i in payload["items"] if i["id"] == "CMP-001")
    assert entry["citations"]["datasheets"][0]["section_page"] == "1"


def test_build_renders_the_resolved_page_in_the_href_and_the_page_cell(tmp_path):
    root = _project(tmp_path)
    _pin_with_sections(root, {"Thermal Design": 1, "Deep Thing": 4})
    project = _build(root)
    out = render.render_site(project)
    html = (Path(out) / "cmp-001.html").read_text(encoding="utf-8")
    sha = hashlib.sha256((root / "docs" / "manual.pdf").read_bytes()).hexdigest()
    assert f'href="assets/citations/{sha}.pdf#page=1"' in html
    assert "<td class=\"mono\">1</td>" in html


def test_build_ignores_section_page_resolved_against_other_bytes(tmp_path):
    """Defence in depth: the pages in `sections` were read out of the bytes
    `sections_sha256` names. If that is not the sha256 now pinned, the page
    belongs to a document this one is not -- so no page is rendered, and the
    build says why, instead of linking confidently into the wrong revision."""
    root = _project(tmp_path)
    _pin_with_sections(root, {"Thermal Design": 1, "Deep Thing": 4})
    path = root / ".refdes" / "citations.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["citations"]["docs/manual.pdf"]["sections_sha256"] = "0" * 64
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    project = _build(root)
    assert project.item_by_id("CMP-001").citations[0].section_page == ""
    assert project.item_by_id("CMP-002").citations[0].section_page == ""
    assert len(project.warnings) == 2
    assert all("resolved against" in d.message and "different bytes" in d.message for d in project.warnings)
    assert all(d.item_id in ("CMP-001", "CMP-002") for d in project.warnings)

    out = render.render_site(project)
    html = (Path(out) / "cmp-001.html").read_text(encoding="utf-8")
    sha = hashlib.sha256((root / "docs" / "manual.pdf").read_bytes()).hexdigest()
    assert f'href="assets/citations/{sha}.pdf"' in html
    assert "#page=" not in html

    strict = _build(root, require_citations=True)
    assert any("resolved against" in d.message for d in strict.errors)


def test_unresolved_section_warns_and_never_renders_bare(tmp_path):
    """Pinned, but the lockfile has no resolved page (never fetched with the
    extra, or resolution failed): a warning, an error under --require-citations."""
    root = _project(tmp_path)
    _pin_with_sections(root, None)
    project = _build(root)
    assert any(
        "has no resolved page" in d.message and d.item_id == "CMP-001"
        for d in project.warnings
    )
    assert not project.errors

    strict = _build(root, require_citations=True)
    assert any("has no resolved page" in d.message for d in strict.errors)


def test_page_and_section_disagreement_warns_and_page_wins(tmp_path):
    """An explicit `page:` is the author's decision; a resolved section is an
    inference. The explicit value renders, and the disagreement is reported."""
    root = _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Disagreeing
    datasheets:
      - path: docs/manual.pdf
        page: "9"
        section: Thermal Design
""",
    )
    _pin_with_sections(root, {"Thermal Design": 1})
    project = _build(root)
    assert len(project.warnings) == 1
    message = project.warnings[0].message
    assert "page: '9'" in message and "page 1" in message
    assert project.item_by_id("CMP-001").citations[0].section_page == "1"

    out = render.render_site(project)
    html = (Path(out) / "cmp-001.html").read_text(encoding="utf-8")
    assert "#page=9" in html


# ------------------------------------------------------------------------- cli


def test_cli_fetch_reports_a_resolved_section_and_exits_zero(tmp_path, capsys):
    root = _project(tmp_path)
    code = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "fetch"])
    out = capsys.readouterr().out
    assert code == 0
    assert "fetched  docs/manual.pdf" in out
    assert "section 'Thermal Design' -> page 1" in out


def test_cli_fetch_no_outline_fails_loudly_with_the_pin_still_recorded(tmp_path, capsys):
    """The characteristic bug of this codebase is reporting success while doing
    nothing: a failed section resolution exits non-zero, names the problem, and
    still leaves the sha256 pinned -- the file was fetched fine."""
    root = _project(tmp_path, outline=[])
    code = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "fetch"])
    captured = capsys.readouterr()
    assert code == 1
    assert "FAILED" in captured.err
    assert "has no outline (bookmarks)" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert "1 citation(s) processed, 1 failed" in captured.out

    record = _lockfile(root)["docs/manual.pdf"]
    assert record["sha256"] == hashlib.sha256(
        (root / "docs" / "manual.pdf").read_bytes()
    ).hexdigest()


def test_fetch_resolves_a_section_added_to_an_already_pinned_path(tmp_path):
    """Already pinned, no --update: the pin is skipped, but a `section:` added
    since the last run still has to be resolved -- or fetch reports success
    while having done nothing about it."""
    root = _project(
        tmp_path,
        item_text="""\
defaults:
  type: component
items:
  - id: CMP-001
    title: Regulator
    datasheets:
      - path: docs/manual.pdf
""",
    )
    _fetch(root)
    assert "sections" not in _lockfile(root)["docs/manual.pdf"]

    (root / "items" / "cmp.yaml").write_text(
        "defaults:\n  type: component\n"
        "items:\n  - id: CMP-001\n    title: Regulator\n"
        "    datasheets:\n      - path: docs/manual.pdf\n"
        "        section: Appendix\n",
        encoding="utf-8",
    )
    results = _fetch(root)
    assert results[0].skipped is True
    assert results[0].sections == {"Appendix": 3}
    assert _lockfile(root)["docs/manual.pdf"]["sections"] == {"Appendix": 3}
