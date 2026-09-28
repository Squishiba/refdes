"""`sources.page_candidates`: reading one page of a PDF for a human choosing a
value (docs/design/editor-pdf-picker.md §4, §8, §11 -- the reader half of Slice
P-A).

Every fixture here is a *real* PDF -- a catalog, a page tree, one Type1 font and
real text operators, written by `helpers.pdf_bytes` -- because the thing under
test is what pypdf makes of a page. A stub would only prove that this module can
read its own dict, and a stubbed visitor is exactly the mock the design's §7
one-reader-in-Python rule exists to prevent. Where a document's *shape* is the
claim (a kerned `TJ` array, a rotated run, a 5-point superscript in a table
cell, a page with no text on it), the fixture is that shape in PDF syntax.

Each test pairs a claim with the thing that would falsify it, in the posture
`test_sources_list.py` uses. The contract under test is the one §4 fixes: the
CSV reader's own numeric grammar and nothing else, runs grouped into rows by
vertical proximity, every number in a row offered and none of them chosen, a
column guess that is labelled as one and recorded nowhere, and the three caps
enforced where the file is read and named when hit.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import write_project_config
from helpers import pdf_bytes, pdf_page, pdf_run

from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes import sources
from refdes.schema import load_project
from refdes.sources import SourceExtractionError, SourceRequest

# A min/typ/max table, laid out the way a datasheet lays one out: a label row
# above the numbers, three columns, and the unit in prose beside them. The one
# number on a page nobody should want, `12` in the prose line, is there to keep
# the "every number is a candidate" rule honest.
TABLE = pdf_page(
    pdf_run(72, 700, "VOUT Efficiency"),
    pdf_run(72, 680, "VOUT=3.3 V, 12 V in, half load"),
    pdf_run(200, 660, "MIN"),
    pdf_run(280, 660, "TYP"),
    pdf_run(360, 660, "MAX"),
    pdf_run(200, 640, "3.15"),
    pdf_run(280, 640, "3.30"),
    pdf_run(360, 640, "3.45"),
    pdf_run(440, 640, "mA"),
)
PROSE = pdf_page(pdf_run(72, 700, "This page is a figure."))


def _write(tmp_path, data: bytes, name: str = "sheet.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _page(tmp_path, data: bytes, page: int = 1, **kwargs):
    return sources.page_candidates(_write(tmp_path, data), page, **kwargs)


def _row_texts(listing) -> list[str]:
    return [row.text for row in listing.rows]


# --------------------------------------------------------------- the rows


def test_page_candidates_returns_numeric_tokens_with_coordinates_and_rows(tmp_path):
    listing = _page(tmp_path, pdf_bytes(TABLE))
    assert (listing.page, listing.pages) == (1, 1)
    assert listing.too_dense is False and listing.truncated is False
    assert listing.detail == ""
    # Every run that carries text is here, and `span_count` counts them even
    # though the reader is one call.
    assert listing.span_count == len(listing.spans) == 9
    assert [span.text.strip() for span in listing.spans][0] == "VOUT Efficiency"
    # Rows are the page read top to bottom, which is also the order a person
    # reads it in -- and y grows downward in the payload while the document's
    # own y grows up.
    assert _row_texts(listing) == [
        "VOUT Efficiency",
        "VOUT=3.3 V, 12 V in, half load",
        "MIN TYP MAX",
        "3.15 3.30 3.45 mA",
    ]
    assert [row.index for row in listing.rows] == [0, 1, 2, 3]
    assert [round(row.y, 1) for row in listing.rows] == [700.0, 680.0, 660.0, 640.0]
    # A run's position and size are the ones in the page: the run painted at
    # x=200, y=640 in 9-point Helvetica is at 200, 640, 9.
    bottom = listing.rows[3]
    first = bottom.tokens[0]
    assert (first.text, first.x, round(bottom.y, 1)) == ("3.15", 200.0, 640.0)
    span = next(s for s in listing.spans if s.text.strip() == "3.15")
    assert (round(span.x, 2), round(span.y, 2), span.size) == (200.0, 640.0, 9.0)
    # A token's x is where the token starts inside its run, not where the run
    # did -- which is the whole reason a column guess can work at all.
    xs = [round(token.x, 2) for token in bottom.tokens]
    assert xs == sorted(xs) and xs == [200.0, 280.0, 360.0, 440.0]
    # A token carries both spellings, the way a CSV row does: `3.30` is 3.30.
    values = {token.text: token.value for token in bottom.tokens}
    assert values == {"3.15": "3.15", "3.30": "3.30", "3.45": "3.45", "mA": ""}
    assert listing.candidate_count == 4  # three in the table, one in the prose


def test_a_run_with_kerning_arrays_and_one_with_a_rotated_frame_both_read(tmp_path):
    # Real producers do not only emit one `Tj` per run on an unrotated page, and
    # a reader that only worked on the tidy shape would be a reader that only
    # worked on the test fixture. A `TJ` array splits into its strings with the
    # kerning offsets dropped, a rotated run is positioned by its own frame, and
    # a number inside either is still a number.
    content = (
        "BT /F1 9 Tf 1 0 0 1 72 700 Tm [(VOUT ) -120 (Efficiency 0.93)] TJ ET\n"
        "BT /F1 9 Tf 0 1 -1 0 500 300 Tm (rot 3.3) Tj ET\n"
        "BT /F1 12 Tf 1 0 0 1 72 500 Tm (Big 1.85) Tj ET"
    )
    listing = _page(tmp_path, pdf_bytes(pdf_page(content)))
    assert _row_texts(listing) == ["VOUT Efficiency 0.93", "Big 1.85", "rot 3.3"]
    numbers = [t.value for row in listing.rows for t in row.tokens if t.candidate]
    assert numbers == ["0.93", "1.85", "3.3"]
    # The kerned run's own tokens sit at their own offsets inside it.
    kerned = listing.rows[0].tokens
    assert [t.text for t in kerned] == ["VOUT", "Efficiency", "0.93"]
    assert round(kerned[2].x, 1) == 144.0  # where 0.93 actually starts
    # A rotated run is grouped by the origin of its own frame, which is the
    # documented coarseness: it is still read, and its text is still shown.
    rotated = listing.rows[2]
    assert rotated.text == "rot 3.3" and rotated.candidate_count == 1


def test_a_space_positioned_by_kerning_glues_its_words_and_offers_nothing(tmp_path):
    # The documented limit, pinned so it cannot change silently. A producer that
    # spaces its words with a kerning offset rather than a space character hands
    # pypdf one run with no gap in it, so the words arrive glued and a number
    # glued to a label is not a number. That is a missing candidate, not a wrong
    # one, and the row shows the author the glued text.
    content = "BT /F1 9 Tf 1 0 0 1 72 700 Tm [(VOUT) -120 (0.93)] TJ ET"
    listing = _page(tmp_path, pdf_bytes(pdf_page(content)))
    (row,) = listing.rows
    assert row.text == "VOUT0.93"
    assert [t.text for t in row.tokens] == ["VOUT0.93"]
    assert row.candidate_count == 0 and listing.candidate_count == 0
    assert "no number that reads as a plain ASCII decimal" in listing.detail


def test_rows_group_by_vertical_proximity_whose_tolerance_comes_from_the_font_size(
    tmp_path,
):
    # A table row is a y-band, and the tolerance is derived from the font size
    # rather than being a constant, so a 5-point parameter table groups the same
    # way an 11-point heading does. A 2pt baseline difference is one row; a 6pt
    # one is not. (The half-em tolerance is a proposal -- editor-pdf-picker.md
    # §10 Q7 -- and this is the test that would notice it being wrong for a
    # table at this size.)
    content = "".join([
        pdf_run(72, 700, "label", 9.0),
        pdf_run(200, 702, "same row", 9.0),
        pdf_run(320, 698, "also same row", 9.0),
        pdf_run(200, 688, "next row", 9.0),
    ])
    listing = _page(tmp_path, pdf_bytes(pdf_page(content)))
    assert _row_texts(listing) == [
        "label same row also same row",
        "next row",
    ]


def test_a_superscript_sized_run_stays_in_its_row(tmp_path):
    # Footnote markers and unit exponents are set smaller and raised; they belong
    # to the row they annotate, and a row of their own would put a number in a
    # context that does not exist.
    content = "".join([
        pdf_run(72, 700, "3.15", 9.0),
        pdf_run(120, 702, "mA", 5.0),
    ])
    listing = _page(tmp_path, pdf_bytes(pdf_page(content)))
    assert _row_texts(listing) == ["3.15 mA"]
    assert listing.rows[0].candidate_count == 1


# ---------------------------------------------------------- the numeric grammar


def test_page_candidates_uses_the_same_numeric_grammar_as_parse_decimal(tmp_path):
    # `editor-source-picker.md` §5's one-parser rule, on a page: every token is
    # offered iff `parse_decimal` -- the fetcher's own function -- accepts it, so
    # the picker cannot present a value `fetch` would refuse. The hazard set is
    # the one `test_sources_csv.py` and `test_sources_list.py` pin, on one page,
    # and the last line is the same function called directly.
    hazards = [
        "1,000", "1_000", "1e999999", "١٢٣", "１２", "NaN", "Infinity",
        "-inf", "10%", "$1.20", "3.3V", "0x10", "1/2",
    ]
    forms = {"+1.0": "1.0", "-1.0": "-1.0", ".5": "0.5", "1.": "1", "1e-3": "0.001"}
    content = "".join(
        [pdf_run(72, 700 - 12 * i, f"haz {cell}") for i, cell in enumerate(hazards)]
        + [pdf_run(400, 700 - 12 * i, cell) for i, cell in enumerate(forms)]
    )
    listing = _page(tmp_path, pdf_bytes(pdf_page(content)))
    for row in listing.rows:
        for token in row.tokens:
            try:
                sources.parse_decimal(token.text)
                is_number = True
            except ValueError:
                is_number = False
            assert token.candidate is is_number, token
            assert (token.value != "") is is_number, token
            if is_number:
                assert token.value == str(sources.parse_decimal(token.text)), token
    offered = {t.text: t.value for row in listing.rows for t in row.tokens}
    for cell in hazards:
        assert offered.get(cell, "") == "", cell
    assert {cell: offered[cell] for cell in forms} == forms
    # A number in prose is a candidate like any other -- there is no way to tell
    # a table cell from a sentence, and refusing to guess which is the rule.
    assert listing.candidate_count == len(forms)


def test_a_token_is_never_parsed_from_a_neighbour(tmp_path):
    # `VOUT=3.3` and `1-2` are one token each, and neither is a number: a
    # candidate that needed its neighbours to read would be a number this tool
    # assembled rather than one the document holds.
    content = "".join([
        pdf_run(72, 700, "VOUT=3.3"),
        pdf_run(72, 680, "1-2"),
        pdf_run(72, 660, "0.93mA"),
        pdf_run(72, 640, " 0.93 "),
    ])
    listing = _page(tmp_path, pdf_bytes(pdf_page(content)))
    assert _row_texts(listing) == ["VOUT=3.3", "1-2", "0.93mA", "0.93"]
    assert listing.rows[3].candidate_count == 1
    assert listing.candidate_count == 1
    # ...and the padded one is padded with a real space, which the token split
    # removed and `parse_decimal` would have trimmed anyway.
    (token,) = listing.rows[3].tokens
    assert (token.text, token.value) == ("0.93", "0.93")


# -------------------------------------------------------------- the min/typ/max


def test_a_table_row_with_min_typ_max_lists_every_candidate_and_selects_none(tmp_path):
    listing = _page(tmp_path, pdf_bytes(TABLE))
    data = listing.rows[3]
    assert [t.text for t in data.candidates] == ["3.15", "3.30", "3.45"]
    assert [t.numeric_index for t in data.candidates] == [0, 1, 2]
    assert [t.index for t in data.tokens] == [0, 1, 2, 3]
    # The mechanical part of the min/typ/max rule: three numbers in the row, a
    # list of three, and no field anywhere in the data structure that names one
    # of them. This is asserted on the types rather than on a payload, because
    # the guarantee is that a *future* consumer cannot find a selection to read
    # even if it wanted one.
    assert not any(
        word in name
        for name in (*sources.PageToken.__dataclass_fields__,
                     *sources.PageRow.__dataclass_fields__,
                     *sources.PageListing.__dataclass_fields__)
        for word in ("select", "chosen", "picked", "active")
    )
    assert [t.candidate for t in data.tokens] == [True, True, True, False]
    assert data.candidate_count == 3


def test_the_column_header_guess_is_labelled_a_guess_and_is_not_recorded(tmp_path):
    listing = _page(tmp_path, pdf_bytes(TABLE))
    data = listing.rows[3]
    # Each number is labelled with the token above it in its own column, which is
    # what answers "which of these is TYP?" on a datasheet.
    assert [t.header_guess for t in data.candidates] == ["MIN", "TYP", "MAX"]
    # The unit in prose gets no guess: it is not a number, and nothing above it
    # overlaps it. A guess is only ever made for a candidate.
    assert data.tokens[3].header_guess == ""
    # Nothing is recorded: the row's identity -- what a re-locating fetch matches
    # on -- is the row's own words, and the guess is not in them.
    assert data.labels == ("mA",)
    assert "MIN" not in data.text and "MAX" not in data.text
    # And the guess can be wrong, which is why it is a guess: when the row above
    # is another *data* row, the overlapping token is a number. It is still
    # offered, still unselected, and still not recorded.
    two_rows = "".join([
        pdf_run(72, 700, "3.15"),
        pdf_run(72, 680, "3.30"),
    ])
    listing = _page(tmp_path, pdf_bytes(pdf_page(two_rows)))
    assert [t.header_guess for t in listing.rows[1].candidates] == ["3.15"]
    assert listing.rows[1].labels == ()


def test_a_rows_own_words_are_its_identity_for_the_re_locating_fetch_will_do(tmp_path):
    # The lockfile will record a quoted row and a numeric index and re-find it
    # by exact text match (editor-pdf-picker.md §6), so the shape that makes that
    # possible is fixed here: the quote is the row's tokens joined by one space
    # and verbatim, and the identity is its non-numeric tokens. The same row on
    # another page of another revision has the same identity, which is what lets
    # a value survive its page moving; a changed number does not change the
    # identity, which is what leaves the change visible as drift.
    listing = _page(tmp_path, pdf_bytes(TABLE))
    data = listing.rows[3]
    assert data.text == "3.15 3.30 3.45 mA"
    moved = pdf_bytes(
        pdf_page(pdf_run(72, 700, "front matter")),
        pdf_page(
            pdf_run(200, 640, "3.15"),
            pdf_run(280, 640, "3.95"),
            pdf_run(360, 640, "3.45"),
            pdf_run(440, 640, "mA"),
        ),
    )
    later = _page(tmp_path, moved, page=2)
    assert [t.text for t in later.rows[0].candidates] == ["3.15", "3.95", "3.45"]
    assert later.rows[0].labels == data.labels
    assert later.rows[0].tokens[1].value == "3.95" != data.tokens[1].value


# ------------------------------------------------------------ the visible failures


def test_a_page_with_no_extractable_text_reports_could_not_read_not_zero_guesses(
    tmp_path,
):
    # A scanned or image-only datasheet page. It has no runs, so it has no
    # candidates -- and the answer says *that*, in the words the panel shows,
    # instead of reporting a page of zero values the author might mistake for a
    # datasheet that has no numbers in it.
    blank = pdf_bytes(pdf_page(), pdf_page(pdf_run(72, 700, "text")))
    listing = _page(tmp_path, blank, page=1)
    assert listing.spans == () and listing.rows == ()
    assert listing.candidate_count == 0
    assert "could not read page 1" in listing.detail
    assert "no extractable text" in listing.detail
    assert "scanned" in listing.detail and "OCR is out of scope" in listing.detail
    # ...and the next page of the same document still reads, so a scanned page
    # does not make the document unreadable.
    assert _page(tmp_path, blank, page=2).rows[0].text == "text"


def test_a_page_with_text_and_no_numbers_says_so_and_still_shows_the_text(tmp_path):
    listing = _page(tmp_path, pdf_bytes(PROSE))
    assert _row_texts(listing) == ["This page is a figure."]
    assert listing.candidate_count == 0 and listing.truncated is False
    assert "no number that reads as a plain ASCII decimal" in listing.detail
    assert "nothing to choose here" in listing.detail


def test_a_page_outside_the_document_says_how_many_pages_it_has(tmp_path):
    three = pdf_bytes(TABLE, PROSE, TABLE)
    assert _page(tmp_path, three, page=3).pages == 3
    for page, fragment in ((0, "pages are counted from 1"), (4, "page 4 is not in this document -- it has 3 page(s)")):
        with pytest.raises(SourceExtractionError) as info:
            _page(tmp_path, three, page=page)
        assert fragment in str(info.value), page


def test_a_pdf_pypdf_cannot_read_says_so_by_its_own_name_and_without_a_traceback(
    tmp_path,
):
    path = _write(tmp_path, b"this is not a PDF at all")
    with pytest.raises(SourceExtractionError) as info:
        sources.page_candidates(path, 1, label="analysis/sheet.pdf")
    message = str(info.value)
    assert message.startswith("analysis/sheet.pdf: ")
    assert "pypdf could not read the PDF" in message
    assert "Traceback" not in message


# ------------------------------------------------------------------- the bounds


def test_candidate_extraction_caps_an_oversized_pdf_and_names_the_limit(tmp_path):
    path = _write(tmp_path, pdf_bytes(TABLE))
    # The cap is a named constant beside the CSV ones, and it is a proposal
    # (editor-pdf-picker.md §10 Q7) -- the rule is that it is bounded and says so.
    assert sources.MAX_PDF_BYTES == 32 << 20
    with pytest.raises(SourceExtractionError) as info:
        sources.page_candidates(path, 1, label="analysis/sheet.pdf", max_bytes=10)
    message = str(info.value)
    assert "refuses anything above 10 bytes" in message
    assert str(path.stat().st_size) in message
    # It refuses *before* the file is parsed, which the ordering is what makes
    # the cap worth having: a document too big to browse is never opened by
    # pypdf to find out that it was too big to browse. Trailing padding makes
    # the same real PDF a big one, and the limit is named in the unit an author
    # would check it in.
    padded = _write(tmp_path, path.read_bytes() + b"%" + b"x" * (3 << 20))
    assert padded.stat().st_size > (2 << 20)
    with pytest.raises(SourceExtractionError) as info:
        sources.page_candidates(padded, 1, label="analysis/sheet.pdf",
                                max_bytes=2 << 20)
    assert "2 MiB" in str(info.value)
    # ...and the same padded file reads perfectly under a cap that admits it.
    assert _page(tmp_path, path.read_bytes() + b"%" + b"x" * (3 << 20)).rows
    with pytest.raises(SourceExtractionError, match="cannot read file"):
        sources.page_candidates(tmp_path / "absent.pdf", 1, label="analysis/sheet.pdf")


def test_the_candidate_cap_stops_the_page_and_names_what_it_did_not_read(tmp_path):
    # The CSV row cap's posture, on a page: reading stops where the cap is, and
    # what is past it is in no count. A page cut in half and reported as the
    # whole would be a wrong answer wearing a correct shape.
    rows = "".join(
        [pdf_run(200, 700 - 20 * i, f"label{i} {i}.5") for i in range(5)]
    )
    listing = _page(tmp_path, pdf_bytes(pdf_page(rows)), max_candidates=3)
    assert listing.truncated is True
    assert listing.candidate_count == 3
    assert len(listing.rows) == 3  # the fourth row would pass three
    assert "3-candidate cap" in listing.detail
    assert "not read" in listing.detail
    # Under the cap the same page reads whole.
    whole = _page(tmp_path, pdf_bytes(pdf_page(rows)))
    assert whole.truncated is False and whole.candidate_count == 5
    assert len(whole.rows) == 5


def test_a_page_too_dense_to_browse_is_reported_rather_than_truncated(tmp_path):
    # A page with more text runs than the cap is *too dense to browse*, not a
    # page with the back half of it missing: half a page's rows is not a page,
    # and the panel would draw it as one.
    dense = "".join(pdf_run(72, 700 - 10 * i, f"run {i}") for i in range(20))
    listing = _page(tmp_path, pdf_bytes(pdf_page(dense)), max_spans=5)
    assert listing.too_dense is True
    assert listing.spans == () and listing.rows == ()
    assert listing.span_count == 6  # a lower bound: reading stopped at the cap
    assert "more than 5 text runs" in listing.detail
    assert "too dense to browse" in listing.detail
    # The shipped cap is a named constant too, and the same page is fine under it.
    assert sources.MAX_PAGE_SPANS == 1000 and sources.MAX_PAGE_CANDIDATES == 200
    under = _page(tmp_path, pdf_bytes(pdf_page(dense)))
    assert under.too_dense is False and len(under.rows) == 20


# ------------------------------------------------------------ the label discipline


def test_page_candidates_names_the_file_with_the_label_it_is_given(tmp_path):
    # The reader-level half of the promise the editor's payload makes: a caller
    # serving `project.root + canon` to a reader must be able to say which file
    # without saying where on the server it is, and the label the caller passes
    # is the label the reader uses in every message -- the whole-file failures
    # and the pypdf message alike.
    path = _write(tmp_path, pdf_bytes(TABLE))
    where = str(tmp_path)
    cases = [
        (lambda: sources.page_candidates(path, 9, label="analysis/sheet.pdf"),
         "page 9 is not in this document"),
        (lambda: sources.page_candidates(path, 1, label="analysis/sheet.pdf",
                                         max_bytes=10),
         "refuses anything above 10 bytes"),
        (lambda: sources.page_candidates(_write(tmp_path, b"junk"), 1,
                                         label="analysis/sheet.pdf"),
         "pypdf could not read the PDF"),
        (lambda: sources.page_candidates(tmp_path / "absent.pdf", 1,
                                         label="analysis/sheet.pdf"),
         "cannot read file"),
    ]
    for call, fragment in cases:
        with pytest.raises(SourceExtractionError) as info:
            call()
        message = str(info.value)
        assert message.startswith("analysis/sheet.pdf: "), message
        assert fragment in message, message
        assert where not in message, message
        assert json.dumps(message)  # the message is a plain string, not a repr
    # Without a label the reader still names the file it read, for the callers
    # that are reading a file whose path they already have.
    with pytest.raises(SourceExtractionError) as info:
        sources.page_candidates(path, 9)
    assert str(info.value).startswith(path.as_posix() + ":")


def test_a_pypdf_that_does_not_report_positions_is_refused_not_drawn(tmp_path,
                                                                    monkeypatch):
    # Up to pypdf 6.18, `visitor_text` was handed a *zeroed* text matrix for
    # every run it inserted a space in front of -- most of a table's cells -- so
    # a datasheet page came back with half its rows collapsed onto the page's
    # bottom-left corner. `pyproject.toml` asks for 6.19; this is the net for an
    # install that predates the floor, because the alternative is drawing it.
    #
    # The old callback sequence is replayed here through a stand-in page, so the
    # check is tested on the exact symptom rather than on a version number: the
    # same visitor, the same zeroed matrices, the same positions afterwards.
    calls = [
        ("VOUT Efficiency", 72.0, 700.0),
        ("", 72.0, 700.0),
        (" MIN", 0.0, 0.0),
        ("", 200.0, 660.0),
        (" 0.90", 0.0, 0.0),
        ("", 260.0, 660.0),
        (" 0.93", 0.0, 0.0),
        ("", 320.0, 660.0),
        (" 0.95", 0.0, 0.0),
        ("\n", 0.0, 0.0),
    ]

    class OldPage:
        mediabox = (0, 0, 612, 792)

        def extract_text(self, visitor_text=None):
            for text, x, y in calls:
                visitor_text(text, [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, x, y], None, 9.0)
            return ""

    class OldReader:
        def __init__(self, _stream):
            self.pages = [OldPage()]

    monkeypatch.setattr(sources, "_pypdf_reader", lambda _name: OldReader)
    monkeypatch.setattr(sources, "_pypdf_version", lambda: "6.18.0")
    path = _write(tmp_path, pdf_bytes(TABLE))
    with pytest.raises(SourceExtractionError) as info:
        sources.page_candidates(path, 1, label="analysis/sheet.pdf")
    message = str(info.value)
    assert "does not report where the text on a page is" in message
    assert "6.18.0" in message  # the version is quoted, so the fix is checkable
    assert "pypdf>=6.19" in message
    assert "pip install -U 'refdes[pdf]'" in message
    assert str(tmp_path) not in message  # and still only the label

    # A page the pypdf *can* place is read as before: the check is about runs
    # piled on the origin, not about a position being zero.
    monkeypatch.undo()
    listing = _page(tmp_path, pdf_bytes(TABLE))
    assert [row.text for row in listing.rows][-1] == "3.15 3.30 3.45 mA"


def test_a_row_with_a_run_at_the_page_origin_is_not_mistaken_for_that(tmp_path,
                                                                     monkeypatch):
    # The other half of the check: a real page may have a run at the very
    # corner. A page whose runs are *mostly* placed is a page, whatever one run
    # does, so the refusal cannot fire on a document that reads fine.
    calls = [
        ("corner note", 0.0, 0.0),
        ("VOUT Efficiency", 72.0, 700.0),
        (" 3.15", 200.0, 640.0),
        (" 3.30", 280.0, 640.0),
    ]

    class CornerPage:
        mediabox = (0, 0, 612, 792)

        def extract_text(self, visitor_text=None):
            for text, x, y in calls:
                visitor_text(text, [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, x, y], None, 9.0)
            return ""

    class CornerReader:
        def __init__(self, _stream):
            self.pages = [CornerPage()]

    monkeypatch.setattr(sources, "_pypdf_reader", lambda _name: CornerReader)
    listing = _page(tmp_path, pdf_bytes(TABLE))
    assert listing.too_dense is False
    # Rows are the page read top to bottom, and the corner run is at the very
    # bottom of it.
    assert [row.text for row in listing.rows] == [
        "VOUT Efficiency", "3.15 3.30", "corner note",
    ]
    assert listing.candidate_count == 2


# ------------------------------------------------------------- the registration


@pytest.mark.parametrize("box", [b"1 2 900 500", b"1 2 001 500"])
def test_page_geometry_comes_from_the_pdf_and_invalid_bounds_fail_visibly(tmp_path, box):
    # Equal-length replacement preserves the real PDF's xref offsets.
    data = pdf_bytes(PROSE).replace(b"0 0 612 792", box)
    if box == b"1 2 001 500":
        with pytest.raises(SourceExtractionError, match="invalid page bounds"):
            _page(tmp_path, data)
    else:
        listing = _page(tmp_path, data)
        assert listing.page_box == (1.0, 2.0, 900.0, 500.0)
        assert listing.spans[0].x == 72.0 and listing.spans[0].y == 700.0


def test_the_pdf_reader_registers_on_pdf_case_insensitively():
    # One registry, one authority on which file types can be read: the picker and
    # `refdes fetch` dispatch through the same call, so a `.pdf` cannot be
    # browsable in one and not the other.
    reader = sources.reader_for("datasheets/tps62913.pdf")
    assert reader.name == "pdf" and reader.extensions == (".pdf",)
    assert sources.reader_for("DATASHEETS/TPS62913.PDF") is reader
    assert sources._GATED == {}


def test_the_pdf_reader_registers_only_when_pypdf_imports(tmp_path, monkeypatch):
    # The `refdes[pdf]` extra is optional and a project with no datasheet must
    # not need it, so the reader is registered only when pypdf imports. The
    # decision is re-runnable rather than a one-shot at import, which is the only
    # way to answer "what does a server without the extra do" honestly: the gate
    # is exercised, not argued about.
    monkeypatch.setitem(sys.modules, "pypdf", None)
    sources.register_pdf_reader()
    try:
        assert sources._GATED == {".pdf": "pdf"}
        assert ".pdf" not in sources._READERS
        for path in ("datasheets/sheet.pdf", "sheet.PDF"):
            with pytest.raises(SourceExtractionError) as info:
                sources.reader_for(path)
            message = str(info.value)
            # The install hint, in the words `section:` already uses -- one
            # sentence for the one extra, so it cannot read differently depending
            # on which feature the author hit.
            assert message == f"{path}: the pdf source reader {citations_mod.PDF_EXTRA_HINT}"
            assert citations_mod.PDF_EXTRA_HINT in citations_mod.PDF_EXTRA_ERROR
            assert "pip install refdes[pdf]" in message
            # and it is not the "no source reader" message, which would send an
            # author looking for a code change that does not exist
            assert "no source reader" not in message
        # A page read says the same thing, rather than raising ImportError.
        with pytest.raises(SourceExtractionError, match="pdf source reader"):
            sources.page_candidates(_write(tmp_path, pdf_bytes(TABLE)), 1)
    finally:
        del sys.modules["pypdf"]
        sources.register_pdf_reader()
    assert sources.reader_for("sheet.pdf").name == "pdf"
    assert sources._GATED == {}


def test_a_reader_without_pages_raises_instead_of_returning_an_empty_page(tmp_path):
    # The same posture as `list_entries`'s: a reader that cannot do this says so,
    # because "this document has nothing on it" is the one reply a page read must
    # never invent. A CSV is the case, and it is refused by the registry rather
    # than by a special case here.
    csv = _write(tmp_path, b"key,value\nfoo,1\n", "t.csv")
    with pytest.raises(SourceExtractionError) as info:
        sources.page_candidates(csv, 1, label="analysis/budget.csv")
    assert "the csv reader has no pages to read" in str(info.value)
    # And the shipped caps are what a caller gets when it passes none.
    assert sources.page_candidates.__defaults__ == (1,)
    for keyword, value in (
        ("max_bytes", sources.MAX_PDF_BYTES),
        ("max_spans", sources.MAX_PAGE_SPANS),
        ("max_candidates", sources.MAX_PAGE_CANDIDATES),
    ):
        assert sources.page_candidates.__kwdefaults__[keyword] == value


def test_the_pdf_reader_does_not_extract_a_value_or_list_a_key_table_yet(tmp_path):
    # Slice P-A is the read half. `extract()` is the write half's reader method
    # (editor-pdf-picker.md §6, §12 Slice P-C), and until it lands a `source()`
    # line naming a PDF has to say so out loud: a file `fetch` cannot read is a
    # file the picker must not browse, and the same rule read from the other
    # side. Silence here would be a fetch that pins nothing and says nothing.
    path = _write(tmp_path, pdf_bytes(TABLE))
    reader = sources.reader_for("analysis/sheet.pdf")
    with pytest.raises(SourceExtractionError) as info:
        reader.extract(path, [SourceRequest("analysis/sheet.pdf", "eff_typ")])
    message = str(info.value)
    assert "the pdf reader does not extract values" in message
    assert "quoted row" in message and "eff_typ" in message
    # A PDF has no key column either, and saying that is better than reporting
    # the reader as a keyed one that cannot enumerate.
    with pytest.raises(SourceExtractionError) as info:
        sources.list_entries(path, label="analysis/sheet.pdf")
    assert "a PDF has no key column" in str(info.value)
    assert str(tmp_path) not in str(info.value)


# ------------------------------------------------- the fetch path (regression)
#
# `citations._extract_source_values` calls `reader.extract(..., label=...)`, and
# every caller of it -- `refdes fetch`, the drift warning, and the editor's
# accept -- goes through that one call site. `PdfReader.extract` was left on the
# pre-`label` signature when `CsvReader.extract` gained the keyword, so a
# `source()` line naming a `.pdf` raised `TypeError: PdfReader.extract() got an
# unexpected keyword argument 'label'` out of the CLI instead of the reader's own
# `SourceExtractionError`. A unit call without the keyword cannot see that, so
# these go through the real caller.

FETCH_CONFIG = """\
site: { title: PDF source fetch, out: _site }
types:
  decision:
    prefix: DEC
    fields:
      citations: { type: citations, on_change: invalidate }
"""
PDF_CITE = "datasheets/sheet.pdf"
PDF_SOURCE = f'```calc\nP = source("{PDF_CITE}", "eff_typ") | 1\n```\n'


def _fetch_project(tmp_path, *, body: str = PDF_SOURCE) -> str:
    """A real project citing a real PDF, with one `source()` line naming it.

    Returns the config path, so the test runs the real `refdes fetch`."""
    write_project_config(tmp_path, FETCH_CONFIG)
    (tmp_path / "datasheets").mkdir()
    (tmp_path / "datasheets" / "sheet.pdf").write_bytes(pdf_bytes(TABLE))
    items = tmp_path / "items"
    items.mkdir()
    (items / "a.md").write_text(
        f"---\nid: DEC-001\ntype: decision\ncitations:\n  - path: {PDF_CITE}\n---\n\n"
        f"{body}",
        encoding="utf-8",
    )
    return str(tmp_path / "refdes-project.yaml")


def test_a_pdf_cited_source_key_fails_fetch_as_a_source_error_not_a_crash(
    tmp_path, capsys
):
    # The regression: `refdes fetch` on a `source()` line naming a PDF must come
    # back as the reader's refusal -- a reported failure, exit 1, nothing pinned
    # -- and not as an uncaught `TypeError` traceback out of `main`.
    config = _fetch_project(tmp_path)
    code = cli_mod.main(["-c", config, "fetch"])
    err = capsys.readouterr().err
    assert code == 1, err
    assert "the pdf reader does not extract values" in err, err
    assert "TypeError" not in err, err
    assert not (tmp_path / ".refdes" / "citations.yaml").exists(), (
        "the refusal still wrote a lockfile"
    )


def test_the_source_value_call_site_passes_its_label_to_the_pdf_reader(tmp_path):
    # The accept path's call, made directly: `_extract_source_values` hands the
    # reader `label=canon` so a browser-facing failure can never carry the
    # server path it read the bytes from. The pdf reader has to honour that the
    # way `list_entries` and `page_candidates` already do.
    config = _fetch_project(tmp_path)
    project = load_project(config_path=config)
    with pytest.raises(SourceExtractionError) as info:
        citations_mod._extract_source_values(
            project, PDF_CITE, {"eff_typ": []}, label=PDF_CITE
        )
    message = str(info.value)
    assert message.startswith(f"{PDF_CITE}: "), message
    assert "the pdf reader does not extract values" in message
    assert str(tmp_path) not in message, message


# ------------------------------------------------------------------ multi-page


def test_a_multi_page_document_reads_the_page_asked_for_with_its_neighbours(tmp_path):
    three = pdf_bytes(PROSE, TABLE, PROSE)
    middle = _page(tmp_path, three, page=2)
    assert (middle.page, middle.pages) == (2, 3)
    assert (middle.prev, middle.next) == (1, 3)
    assert _row_texts(middle) == _row_texts(_page(tmp_path, three, page=2))
    # The ends have no neighbour on one side, said as null rather than as a page
    # number that does not exist.
    first = _page(tmp_path, three, page=1)
    assert (first.prev, first.next) == (None, 2)
    last = _page(tmp_path, three, page=3)
    assert (last.prev, last.next) == (2, None)
    # Page 1 is the default, so a caller that does not care gets the front.
    assert _page(tmp_path, three).page == 1


def test_the_values_offered_are_decimals_a_lockfile_could_hold(tmp_path):
    # The last step of the one-parser rule, stated on the payload: every offered
    # value round-trips through `Decimal` and through the text a lockfile record
    # stores, so nothing the picker shows is a value the lockfile could not
    # carry verbatim.
    listing = _page(tmp_path, pdf_bytes(TABLE))
    for row in listing.rows:
        for token in row.candidates:
            assert Decimal(token.value) == Decimal(token.text)
            assert str(Decimal(token.value)) == token.value
