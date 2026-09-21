"""CSV source reader (docs/design/calc-sources.md §3, required tests 2-7).

Reader-level tests: each asserts the extracted decimal or a specific
diagnostic, never reader internals. The end-to-end `source()` calc tests live
in test_calc_sources.py."""

from __future__ import annotations

from decimal import Decimal

import pytest

from refdes import sources
from refdes.sources import SourceExtractionError, SourceRequest


def _extract(tmp_path, text: str | bytes, *keys: str):
    path = tmp_path / "t.csv"
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_bytes(text.encode("utf-8"))
    reader = sources.reader_for("t.csv")
    return reader.extract(path, [SourceRequest("t.csv", k) for k in keys])


def _fails(tmp_path, text, key, fragment):
    with pytest.raises(SourceExtractionError) as info:
        _extract(tmp_path, text, key)
    assert fragment in str(info.value), str(info.value)


def test_csv_source_selects_same_row_value_by_exact_key(tmp_path):
    a = _extract(tmp_path, "key,value\nx,1\nfoo,0.93\nbar,7\n", "foo")
    b = _extract(tmp_path, "key,value\nbar,7\nfoo,0.93\nx,1\n", "foo")
    assert a["foo"].value == b["foo"].value == Decimal("0.93")


def test_csv_source_duplicate_key_errors_instead_of_first_or_last_wins(tmp_path):
    _fails(tmp_path, "key,value\nfoo,1\nfoo,1\n", "foo", "appears on 2 rows (lines 2, 3)")


def test_csv_source_duplicate_header_errors_before_column_overwrite(tmp_path):
    _fails(tmp_path, "key,value,value\nfoo,1,2\n", "foo", "2 'value' columns")
    _fails(tmp_path, "key,key,value\nfoo,x,2\n", "foo", "2 'key' columns")
    _fails(tmp_path, "Key,value\nfoo,1\n", "foo", "no 'key' column")


def test_csv_source_missing_key_blank_value_and_non_numeric_value_error(tmp_path):
    _fails(tmp_path, "key,value\nfoo,1\n", "fo", "no row has the key 'fo'")
    _fails(tmp_path, "key,value\nfoo,\n", "foo", "empty")
    _fails(tmp_path, "key,value\nfoo,  \n", "foo", "empty")
    for bad in ("abc", "NaN", "Infinity", "-inf"):
        _fails(tmp_path, f"key,value\nfoo,{bad}\n", "foo", "not a plain ASCII decimal")
    _fails(tmp_path, "key,value\n,1\nfoo,1\n", "foo", "key cell is blank")
    for zero in ("0", "0.0", "0e0"):
        assert _extract(tmp_path, f"key,value\nfoo,{zero}\n", "foo")["foo"].value == 0


@pytest.mark.parametrize("cell", [
    "100 mW", "3.3 V", "10%", "$1.20",
    '"1,000"', '"1 000"', '"1,23"', "1_000",
    "١٢٣", "１２", " 1", "1 ", '"1\n"', "1e999999",
])
def test_csv_source_rejects_unit_suffix_grouping_locale_unicode_and_overflow(tmp_path, cell):
    with pytest.raises(SourceExtractionError):
        _extract(tmp_path, f"key,value\nfoo,{cell}\n", "foo")


def test_csv_source_unquoted_thousands_is_a_ragged_row(tmp_path):
    _fails(tmp_path, "key,value\nfoo,1,000\n", "foo", "row has 3 field(s)")


def test_csv_source_accepted_numeric_forms(tmp_path):
    for text, want in {"+1.0": "1.0", "-1.0": "-1.0", ".5": "0.5", "1.": "1", "1e-3": "0.001",
                       " \t2.5\t ": "2.5"}.items():
        got = _extract(tmp_path, f"key,value\nfoo,{text}\n", "foo")["foo"]
        assert got.text == want, (text, got.text)


def test_csv_source_handles_utf8_bom_and_standard_quoted_context(tmp_path):
    got = _extract(tmp_path, b"\xef\xbb\xbfkey,value,note\nfoo,4.5,\"a, b\nc\"\n", "foo")
    assert got["foo"].value == Decimal("4.5")
    # A BOM anywhere but the very start is not forgiven.
    _fails(tmp_path, "key,﻿value\nfoo,1\n", "foo", "no 'value' column")
    # Keys are never trimmed.
    _fails(tmp_path, "key,value\n foo,1\n", "foo", "no row has the key 'foo'")
    got = _extract(tmp_path, 'value,note,key\n2,"x,y",foo\n', "foo")
    assert got["foo"].value == 2


def test_csv_source_rejects_malformed_quote_and_ragged_row(tmp_path):
    _fails(tmp_path, 'key,value\nfoo,"1\n', "foo", "malformed CSV")
    _fails(tmp_path, 'key,value\nfoo,1\nbar\n', "foo", "row has 1 field(s)")
    _fails(tmp_path, b"key,value\nfoo,\xff\n", "foo", "not valid UTF-8")


def test_csv_source_reads_every_key_in_one_parse_and_reports_all_problems(tmp_path):
    got = _extract(tmp_path, "key,value\na,1\nb,2\n", "a", "b")
    assert {k: v.text for k, v in got.items()} == {"a": "1", "b": "2"}
    with pytest.raises(SourceExtractionError) as info:
        _extract(tmp_path, "key,value\na,1\nb,x\nb2,1\n", "a", "b", "c")
    assert len(info.value.problems) == 2  # b non-numeric, c missing


def test_no_reader_for_unknown_extension_is_an_error():
    with pytest.raises(SourceExtractionError, match="no source reader"):
        sources.reader_for("notes.txt")
