"""`sources.list_entries`: enumerating a source file's rows
(docs/design/editor-source-picker.md §5, Slice A; the reader half of §10).

Every test here pairs a claim with the thing that would falsify it, and
asserts the row the picker would show -- never a reader internal. The contract
under test is the one §5 fixes: one parser shared with `extract()`, fatal
header failures, row-level problems that mark a row rather than emptying the
listing, and a duplicated key that makes *both* of its rows unselectable
instead of letting the listing choose one.
"""

from __future__ import annotations

import json

import pytest

from refdes import sources
from refdes.sources import SourceExtractionError, SourceRequest

CSV = "key,value,note\nrail_load,1.85,mW budget\neff,0.93,datasheet rev E\nother,7,x\n"


def _write(tmp_path, text: str | bytes, name: str = "t.csv"):
    path = tmp_path / name
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_bytes(text.encode("utf-8"))
    return path


def _entries(tmp_path, text: str | bytes, name: str = "t.csv"):
    return sources.list_entries(_write(tmp_path, text, name)).entries


def _by_key(entries):
    return {e.key: e for e in entries if e.key}


# ------------------------------------------------------------------ the rows


def test_list_entries_returns_every_key_with_raw_and_canonical_text(tmp_path):
    entries = _entries(tmp_path, CSV)
    assert [e.key for e in entries] == ["rail_load", "eff", "other"]
    got = _by_key(entries)
    # The raw cell and the canonical text are both on the row: `1.85` and
    # `.1.85` are the same number and different decisions to review.
    assert (got["rail_load"].raw, got["rail_load"].value) == ("1.85", "1.85")
    assert (got["eff"].raw, got["eff"].value) == ("0.93", "0.93")
    for entry in entries:
        assert entry.selectable and entry.problem == ""
        assert entry.value == sources.parse_decimal(entry.raw).normalize().__str__()
    # Context is the row's *other* columns, header -> cell, and never repeats
    # the key or the value: those are on the entry itself.
    assert got["rail_load"].context == (("note", "mW budget"),)
    assert got["other"].context == (("note", "x"),)
    # Line numbers are the physical lines, the same numbering extract() reports.
    assert [e.line for e in entries] == [2, 3, 4]
    # And the same keys, at the same values, as extract() -- one parser.
    extracted = sources.reader_for("t.csv").extract(
        _write(tmp_path, CSV), [SourceRequest("t.csv", "eff")]
    )
    assert extracted["eff"].text == got["eff"].value


def test_list_entries_keeps_the_canonical_text_of_the_forms_extract_accepts(tmp_path):
    # `extract()` accepts these spellings; the listing must show what it would
    # pin, not a re-parse that disagrees.
    entries = _by_key(_entries(
        tmp_path, "key,value\n" + "".join(f"k{i},{cell}\n" for i, cell in enumerate(
            ("+1.0", "-1.0", ".5", "1.", "1e-3", " \t2.5\t ", "0.0")
        ))
    ))
    assert [entries[f"k{i}"].value for i in range(7)] == [
        "1.0", "-1.0", "0.5", "1", "0.001", "2.5", "0.0",
    ]
    assert all(entries[f"k{i}"].selectable for i in range(7))


def test_list_entries_marks_a_non_numeric_row_unselectable_without_hiding_it(tmp_path):
    entries = _entries(tmp_path, "key,value,note\nok,1,fine\nbroken,abc,oops\n")
    assert [e.key for e in entries] == ["ok", "broken"]  # listed, not dropped
    broken = entries[1]
    assert broken.selectable is False
    assert broken.raw == "abc"  # what the author wrote is still shown
    assert broken.value == ""  # and no number is invented for it
    assert "not a plain ASCII decimal" in broken.problem
    assert entries[0].selectable is True


def test_list_entries_uses_the_same_number_grammar_as_extract(tmp_path):
    # The `test_sources_csv.py` hazard set. Every one of these is a row the
    # listing shows and marks unselectable -- never a selectable row carrying a
    # value `extract()` would refuse, which is the disagreement §5 exists to
    # prevent. The padding here is U+00A0 NO-BREAK SPACE, the hazard the CSV
    # tests use: an ASCII space or tab is trimmed and stays a valid number.
    hazards = [
        "100 mW", "3.3 V", "10%", "$1.20",
        '"1,000"', '"1 000"', '"1,23"', "1_000",
        "١٢٣", "１２", " 1", "1 ", '"1\n"', "1e999999",
        "", "   ", "NaN", "Infinity", "-inf",
    ]
    for cell in hazards:
        entries = _entries(tmp_path, f"key,value\nk,{cell}\n")
        (entry,) = entries
        assert entry.selectable is False, repr(cell)
        assert entry.value == "", repr(cell)
        assert entry.problem, repr(cell)
        # and the reader extract() uses refuses the same cell
        with pytest.raises(SourceExtractionError):
            sources.reader_for("t.csv").extract(
                _write(tmp_path, f"key,value\nk,{cell}\n"), [SourceRequest("t.csv", "k")]
            )
    # ASCII space and tab are not a hazard, and the listing agrees with
    # `extract()` about that too -- the grammar is one grammar.
    (padded,) = _entries(tmp_path, "key,value\nk, \t2.5\t \n")
    assert padded.selectable is True and padded.value == "2.5"


def test_list_entries_marks_both_rows_of_a_duplicated_key_unselectable(tmp_path):
    entries = _entries(tmp_path, "key,value,note\nrail,1.85,a\nrail,2.30,b\n")
    # Both are listed: hiding them would make a broken file look empty, and the
    # author cannot fix what they cannot see.
    assert [e.key for e in entries] == ["rail", "rail"]
    assert [e.line for e in entries] == [2, 3]
    for entry in entries:
        assert entry.selectable is False
        assert "appears on 2 rows (lines 2, 3)" in entry.problem
        assert "must be unique" in entry.problem
    # The values themselves are still shown, so the duplicate is recognisable.
    assert [e.raw for e in entries] == ["1.85", "2.30"]
    # Three copies read the same way, and extract() refuses the key outright
    # rather than taking first or last.
    three = _entries(tmp_path, "key,value\nd,1\nd,2\nd,3\n")
    assert [e.selectable for e in three] == [False, False, False]
    assert "lines 2, 3, 4" in three[0].problem


def test_list_entries_marks_a_duplicate_reason_even_when_the_row_is_also_broken(tmp_path):
    # A row can be wrong twice. The key is the identity being picked, so the
    # duplicate has to survive into the message rather than being crowded out
    # by the value problem that also applies.
    (broken, twin) = _entries(tmp_path, "key,value\nd,abc\nd,2\n")
    assert "not a plain ASCII decimal" in broken.problem
    assert "appears on 2 rows" in broken.problem
    assert "appears on 2 rows" in twin.problem


def test_list_entries_marks_a_blank_key_and_a_ragged_row_without_dropping_them(tmp_path):
    entries = _entries(tmp_path, "key,value\n,1\na,1,000\nb,2\n")
    blank, ragged, fine = entries
    assert blank.key == ""
    assert "the key cell is blank" in blank.problem
    assert blank.selectable is False
    assert "row has 3 field(s)" in ragged.problem
    assert ragged.selectable is False
    # A ragged row is still shown, key included, and still not pickable.
    assert (ragged.key, ragged.raw) == ("a", "1")
    assert fine.selectable is True and fine.key == "b"


# --------------------------------------------------------------- fatal failures


def test_list_entries_fails_on_a_bad_header_like_extract_does(tmp_path):
    # Header-level failures are fatal, exactly as in extract(): a file fetch
    # cannot read is a file the picker must not browse. Each of these raises
    # rather than listing rows.
    cases = {
        "key,value,value\nfoo,1,2\n": "2 'value' columns",
        "key,key,value\nfoo,x,2\n": "2 'key' columns",
        "Key,value\nfoo,1\n": "no 'key' column",
        "key,val\nfoo,1\n": "no 'value' column",
        "": "the file is empty",
        'key,value\nfoo,"1\n': "malformed CSV",
    }
    for text, fragment in cases.items():
        with pytest.raises(SourceExtractionError) as info:
            _entries(tmp_path, text)
        assert fragment in str(info.value), (text, str(info.value))
        # the same file refuses extract() too
        with pytest.raises(SourceExtractionError):
            sources.reader_for("t.csv").extract(
                _write(tmp_path, text), [SourceRequest("t.csv", "foo")]
            )
    # Non-UTF-8 is fatal here too, with the same words.
    with pytest.raises(SourceExtractionError, match="not valid UTF-8"):
        _entries(tmp_path, b"key,value\nfoo,\xff\n")
    # A file that is not there says so rather than listing nothing.
    with pytest.raises(SourceExtractionError, match="cannot read file"):
        sources.list_entries(tmp_path / "absent.csv")


def test_list_entries_names_the_file_with_the_label_it_is_given(tmp_path):
    # `label` is the file's name in every message the result carries, including
    # the per-row `problem` a successful listing ships. A caller reading a file
    # on an author's behalf -- the editor serving `project.root + canon` -- must
    # be able to say which file without saying where on the server it is, and
    # this is the reader-level half of that promise: the label the caller passes
    # is the label the reader uses, in both the failing and the succeeding case.
    path = _write(tmp_path, "key,value\nd,1\nd,2\nbad,abc\n")
    listing = sources.list_entries(path, label="analysis/budget.csv")
    assert str(tmp_path) not in json.dumps([e.problem for e in listing.entries])
    for entry in listing.entries:
        assert entry.problem.startswith("analysis/budget.csv:"), entry.problem
    assert "appears on 2 rows (lines 2, 3)" in listing.entries[0].problem
    assert "not a plain ASCII decimal" in listing.entries[2].problem
    # A file that is not there is named by the label, and the OS error's own
    # text -- which interpolates the path it was raised on -- does not undo it.
    with pytest.raises(SourceExtractionError) as info:
        sources.list_entries(tmp_path / "absent.csv", label="analysis/budget.csv")
    assert "analysis/budget.csv: cannot read file: No such file or directory" in str(
        info.value
    )
    assert str(tmp_path) not in str(info.value)
    # The label reaches the whole-file failures too, not just the row ones.
    for text, fragment in (
        ("Key,value\nfoo,1\n", "no 'key' column"),
        ('key,value\nfoo,"1\n', "malformed CSV"),
        ("", "the file is empty"),
    ):
        with pytest.raises(SourceExtractionError) as info:
            sources.list_entries(_write(tmp_path, text), label="analysis/budget.csv")
        assert fragment in str(info.value)
        assert str(tmp_path) not in str(info.value)
    with pytest.raises(SourceExtractionError) as info:
        sources.list_entries(path, label="analysis/budget.csv", max_bytes=1)
    assert "analysis/budget.csv: the file is" in str(info.value)
    assert str(tmp_path) not in str(info.value)
    # And without a label the reader still names the file it read, for the
    # callers that are reading a file whose path they already have.
    default = sources.list_entries(_write(tmp_path, "key,value\nd,1\nd,2\n"))
    assert default.entries[0].problem.startswith(
        (tmp_path / "t.csv").as_posix() + ":"
    )
    # A reader that cannot enumerate is named by the label too.
    class NoEnumerate:
        name = "opaque"
        extensions = (".opaque",)

    sources.register(NoEnumerate())
    try:
        with pytest.raises(SourceExtractionError, match="analysis/budget.csv:"):
            sources.list_entries(
                _write(tmp_path, "x\n", "t.opaque"), label="analysis/budget.csv"
            )
    finally:
        sources._READERS.pop(".opaque", None)


def test_a_reader_without_list_entries_raises_instead_of_returning_nothing(tmp_path):
    class NoEnumerate:
        name = "opaque"
        extensions = (".opaque",)

        def extract(self, path, requests):  # pragma: no cover - never called
            raise SourceExtractionError(["not implemented"])

    sources.register(NoEnumerate())
    try:
        path = _write(tmp_path, "anything at all\n", "t.opaque")
        with pytest.raises(SourceExtractionError) as info:
            sources.list_entries(path)
        assert "cannot list a file's entries" in str(info.value)
    finally:
        for ext in (".opaque",):
            sources._READERS.pop(ext, None)


def test_list_entries_refuses_a_file_type_no_reader_is_registered_for(tmp_path):
    with pytest.raises(SourceExtractionError, match="no source reader"):
        sources.list_entries(_write(tmp_path, "key,value\nfoo,1\n", "t.txt"))


# ------------------------------------------------------------------- the bounds


def test_list_entries_stops_reading_at_the_row_cap_instead_of_loading_the_file(tmp_path):
    # The cap is enforced where the file is read, so a file far larger than the
    # cap is never materialised: the parse stops at `max_rows` and says so. A
    # 20,000-row file read as 5,000 rows and then cut would answer the same
    # question while holding the whole file in memory, which is the thing the
    # cap exists to prevent.
    path = tmp_path / "big.csv"
    with path.open("w", encoding="utf-8") as fh:
        fh.write("key,value\n")
        for i in range(20000):
            fh.write(f"key_{i},{i}\n")

    full = sources.list_entries(path)  # the shipped default
    assert full.rows_read == sources.MAX_LIST_ROWS == 5000
    assert full.truncated is True
    assert len(full.entries) == 5000
    assert full.entries[-1].key == "key_4999"
    # and the parse really did stop there: a file under the cap is not truncated
    small = sources.list_entries(path, max_rows=25000)
    assert small.rows_read == 20000
    assert small.truncated is False
    assert small.entries[-1].key == "key_19999"


def test_list_entries_refuses_a_file_above_the_byte_cap_before_opening_it(tmp_path):
    path = tmp_path / "huge.csv"
    path.write_text(
        "key,value\n" + "".join(f"key_{i},{i}\n" for i in range(200000)),
        encoding="utf-8",
    )
    assert path.stat().st_size > sources.MAX_LIST_BYTES
    with pytest.raises(SourceExtractionError) as info:
        sources.list_entries(path)
    # The refusal names the limit, because a cap an author cannot see is a cap
    # they will report as "the tool is broken".
    assert "refuses anything above 1048576 bytes" in str(info.value)
    # Under both caps the very same reader answers normally.
    whole = sources.list_entries(
        path, max_bytes=path.stat().st_size + 1, max_rows=200000
    )
    assert whole.rows_read == 200000 and whole.truncated is False


def test_list_entries_caps_context_columns_and_marks_what_it_cut(tmp_path):
    (entry,) = _entries(
        tmp_path,
        "key,value," + ",".join(f"c{i}" for i in range(10))
        + "\n" + "k,1," + ",".join(f"v{i}" for i in range(10)) + "\n",
    )
    # The key and value columns are not repeated in the context, and only eight
    # of the ten remaining columns survive.
    names = [name for name, _text in entry.context]
    assert len(entry.context) == 8
    assert "key" not in names and "value" not in names
    assert names == [f"c{i}" for i in range(8)]
    # An over-long cell is cut with an explicit mark, never silently: a cut
    # that looked like the author's data ending there would be a wrong answer
    # wearing a correct shape.
    (wide,) = _entries(tmp_path, "key,value,note\nk,1," + "x" * 200 + "\n")
    assert wide.context[0][1] == "x" * 80 + "…"
    (short,) = _entries(tmp_path, "key,value,note\nk,1,brief\n")
    assert short.context[0][1] == "brief"


def test_list_entries_reads_a_bom_and_quoted_context_like_extract_does(tmp_path):
    (entry,) = _entries(
        tmp_path, b'\xef\xbb\xbfkey,value,note\nfoo,4.5,"a, b\nc"\n'
    )
    assert (entry.key, entry.value, entry.line) == ("foo", "4.5", 2)
    assert entry.context == (("note", "a, b\nc"),)
    assert entry.selectable is True


def test_list_entries_skips_fully_blank_lines_without_shifting_a_line_number(tmp_path):
    # A blank physical line carries no fields, so it cannot shift a column --
    # but the line numbers still name the physical lines, which is what lets an
    # author go and look at the row.
    entries = _entries(tmp_path, "key,value\n\nfoo,1\n\n\nbar,2\n")
    assert [(e.key, e.line) for e in entries] == [("foo", 3), ("bar", 6)]
    assert all(e.selectable for e in entries)
