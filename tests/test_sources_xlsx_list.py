"""`XlsxReader.list_entries`: enumerating a workbook's defined names for the
source picker (docs/design/editor-source-picker.md §8's open xlsx bullet; the
listing half of `calc-sources.md` §4's key grammar).

The contract is §5's, applied to a workbook: the keys the listing offers are
exactly the keys `extract()` accepts (qualified sheet-scoped names included),
a name `extract()` would refuse is listed and marked, never hidden, and the
listing never writes the workbook. Every pairing test asserts both halves:
selectable ⇔ extract accepts the same key at the same canonical value,
unselectable ⇔ extract refuses it.
"""

from __future__ import annotations

import json

import pytest

from refdes import sources
from refdes.sources import SourceExtractionError, SourceRequest

pytest.importorskip("openpyxl")

from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName


def make_workbook(path, *, names=True):
    """A fixture workbook with one visible sheet, one hidden sheet, a merged
    range, a formula cell with no cached value, and names that exercise every
    refusal `extract()` makes (range, external, unparseable destination)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet["B2"] = 1.85
    sheet["C1"] = "3.2"
    sheet["A3"] = "=1+2"
    sheet.merge_cells("D4:E5")
    sheet["D4"] = 7.5
    hidden = workbook.create_sheet("Hidden")
    hidden["B2"] = 2.3
    hidden.sheet_state = "hidden"
    odd = workbook.create_sheet("Odd!Name")
    odd["A1"] = 9.0
    if names:
        workbook.defined_names.add(DefinedName("power", attr_text="'Sheet1'!$B$2"))
        sheet.defined_names.add(DefinedName("anchor", attr_text="'Sheet1'!$B$2"))
        sheet.defined_names.add(DefinedName("merged_top", attr_text="'Sheet1'!$D$4"))
        sheet.defined_names.add(DefinedName("merged_inside", attr_text="'Sheet1'!$E$5"))
        sheet.defined_names.add(DefinedName("text_cell", attr_text="'Sheet1'!$C$1"))
        sheet.defined_names.add(DefinedName("formula", attr_text="'Sheet1'!$A$3"))
        sheet.defined_names.add(DefinedName("wide", attr_text="'Sheet1'!$A$1:$B$2"))
        sheet.defined_names.add(
            DefinedName("external", attr_text="'[other.xlsx]Sheet1'!$A$1")
        )
        sheet.defined_names.add(DefinedName("bare", attr_text="A1:B2"))
        hidden.defined_names.add(DefinedName("local", attr_text="'Hidden'!$B$2"))
        odd.defined_names.add(DefinedName("odd", attr_text="'Odd!Name'!$A$1"))
    workbook.save(path)
    workbook.close()
    return path


@pytest.fixture
def workbook(tmp_path):
    return make_workbook(tmp_path / "budget.xlsx")


def _list(path, **kw):
    return sources.list_entries(path, **kw)


def _by_key(entries):
    return {e.key: e for e in entries}


def _extract(path, key):
    return sources.reader_for("budget.xlsx").extract(
        path, [SourceRequest("budget.xlsx", key)], label="budget.xlsx"
    )


# ------------------------------------------------------------------ the keys


def test_xlsx_listing_offers_every_defined_name_with_qualified_sheet_scope(workbook):
    listing = _list(workbook)
    keys = [e.key for e in listing.entries]
    # Workbook-scope names first, then each sheet's names in workbook order,
    # qualified the way `extract()`'s key grammar spells them.
    assert keys == [
        "power",
        "Sheet1!anchor", "Sheet1!merged_top", "Sheet1!merged_inside",
        "Sheet1!text_cell", "Sheet1!formula", "Sheet1!wide", "Sheet1!external",
        "Sheet1!bare",
        "Hidden!local",
        "Odd!Name!odd",
    ]
    assert listing.truncated is False
    assert listing.rows_read == len(keys)
    # A resolved destination shows the cell, and a hidden sheet says so.
    got = _by_key(listing.entries)
    assert dict(got["power"].context) == {"cell": "Sheet1!B2"}
    assert dict(got["Hidden!local"].context) == {"cell": "Hidden!B2", "sheet": "hidden"}
    assert got["power"].line == 2  # the destination's row
    assert all("!" not in name for name, _text in got["power"].context)


def test_xlsx_listing_keys_and_values_are_what_extract_accepts(workbook):
    # The one-parser promise, paired on every entry: a row the picker offers
    # is a row `fetch` will extract at the same canonical value, and a row it
    # marks broken is one `fetch` refuses.
    for entry in _list(workbook).entries:
        if entry.selectable:
            extracted = _extract(workbook, entry.key)
            assert extracted[entry.key].text == entry.value, entry.key
        else:
            with pytest.raises(SourceExtractionError):
                _extract(workbook, entry.key)


def test_xlsx_listing_carries_raw_and_canonical_text_like_csv(workbook):
    got = _by_key(_list(workbook).entries)
    # The cell's stored number as written, and the canonical text `extract()`
    # pins, are both on the entry (the CSV listing's reason: 1850 and 1.85 are
    # different decisions to review).
    assert (got["power"].raw, got["power"].value) == ("1.85", "1.85")
    assert (got["Hidden!local"].raw, got["Hidden!local"].value) == ("2.3", "2.3")
    assert (got["Sheet1!merged_top"].raw, got["Sheet1!merged_top"].value) == ("7.5", "7.5")
    assert got["power"].selectable and got["power"].problem == ""


# ----------------------------------------------------------------- the refusals


def test_xlsx_listing_marks_every_refusal_unselectable_without_hiding_it(workbook):
    got = _by_key(_list(workbook).entries)
    assert "is not a numeric cell" in got["Sheet1!text_cell"].problem
    assert "one cell" in got["Sheet1!wide"].problem
    assert "external workbook" in got["Sheet1!external"].problem
    # The openpyxl destination crash is named by the destination's own text,
    # not by a Python repr (the `xlsx-malformed-destination` lesson).
    assert "A1:B2" in got["Sheet1!bare"].problem
    assert "NoneType" not in got["Sheet1!bare"].problem
    # A formula cell with no cached value gets the same actionable hint
    # `extract()` gives.
    assert "open the workbook in a calculating application" in got["Sheet1!formula"].problem
    # A merged range's inside cell is blank -- exactly what `extract()` sees.
    assert "is blank" in got["Sheet1!merged_inside"].problem
    # A sheet name containing the key grammar's separator cannot be named by a
    # qualified key; the listing says why rather than offering a key `fetch`
    # would refuse.
    assert "!" in got["Odd!Name!odd"].problem
    for entry in got.values():
        assert not entry.selectable or entry.problem == ""
        assert entry.value == "" if not entry.selectable else entry.value


def test_xlsx_listing_names_rows_with_the_label_it_is_given(tmp_path, workbook):
    listing = _list(workbook, label="analysis/budget.xlsx")
    blob = json.dumps([e.problem for e in listing.entries])
    assert str(tmp_path) not in blob
    for entry in listing.entries:
        if entry.problem:
            assert entry.problem.startswith("analysis/budget.xlsx: key "), entry.problem
    with pytest.raises(SourceExtractionError) as info:
        _list(tmp_path / "absent.xlsx", label="analysis/budget.xlsx")
    assert str(info.value).startswith("analysis/budget.xlsx: cannot read file: ")
    assert str(tmp_path) not in str(info.value)


# ------------------------------------------------------- unreadable workbooks


def test_xlsx_listing_refuses_corrupt_empty_and_encrypted_without_traceback(tmp_path):
    cases = {
        "corrupt.xlsx": b"not a zip file",
        "empty.xlsx": b"",
        "encrypted.xlsx": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 512,
    }
    for name, payload in cases.items():
        path = tmp_path / name
        path.write_bytes(payload)
        with pytest.raises(SourceExtractionError) as info:
            _list(path, label=name)
        message = str(info.value)
        assert name in message
        assert "Traceback" not in message
    with pytest.raises(SourceExtractionError) as info:
        _list(tmp_path / "encrypted.xlsx", label="encrypted.xlsx")
    assert "the workbook is encrypted" in str(info.value)
    assert "password" in str(info.value)


def test_xlsx_listing_of_a_workbook_with_no_names_is_empty_not_an_error(tmp_path):
    path = make_workbook(tmp_path / "plain.xlsx", names=False)
    listing = _list(path)
    assert listing.entries == ()
    assert listing.rows_read == 0
    assert listing.truncated is False


# ------------------------------------------------------------------- the bounds


def test_xlsx_listing_stops_at_the_row_cap_and_says_so(tmp_path):
    path = tmp_path / "many.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    for i in range(60):
        sheet.cell(row=i + 1, column=2, value=i)
        sheet.defined_names.add(
            DefinedName(f"k{i}", attr_text=f"'{sheet.title}'!$B${i + 1}")
        )
    workbook.save(path)
    workbook.close()
    full = _list(path)
    assert full.rows_read == 60 and full.truncated is False
    capped = _list(path, max_rows=10)
    assert capped.rows_read == 10
    assert capped.truncated is True
    assert [e.key for e in capped.entries] == [f"Sheet!k{i}" for i in range(10)]


def test_xlsx_listing_refuses_a_workbook_above_the_byte_cap_before_opening_it(tmp_path):
    path = make_workbook(tmp_path / "big.xlsx")
    with pytest.raises(SourceExtractionError) as info:
        _list(path, label="big.xlsx", max_bytes=path.stat().st_size - 1)
    assert "refuses anything above" in str(info.value)
    assert str(tmp_path) not in str(info.value)
    # The shipped caps are the documented listing bounds, shared with CSV.
    assert sources.MAX_LIST_ROWS == 5000
    assert sources.MAX_LIST_BYTES == 1 << 20


# ------------------------------------------------------------------- no writes


def test_xlsx_listing_never_writes_the_workbook(workbook):
    before = workbook.read_bytes()
    _list(workbook)
    _list(workbook, max_rows=3)
    with pytest.raises(SourceExtractionError):
        _list(workbook, max_bytes=1)
    assert workbook.read_bytes() == before


# ------------------------------------------------------------ the optional extra


def test_xlsx_listing_missing_extra_names_install_command(tmp_path, monkeypatch):
    original_import = sources.importlib.import_module

    def missing_openpyxl(name, *args, **kwargs):
        if name == "openpyxl":
            raise ModuleNotFoundError("No module named 'openpyxl'", name="openpyxl")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(sources.importlib, "import_module", missing_openpyxl)
    with pytest.raises(SourceExtractionError) as info:
        _list(tmp_path / "budget.xlsx", label="budget.xlsx")
    assert 'pip install "refdes[xlsx]"' in str(info.value)
