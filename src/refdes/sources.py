"""Calc source readers: pull one named scalar out of a cited, repo-local file.

`source("analysis/power-budget.csv", "some_key")` in a calc block never opens
that file during `check` or `build` -- `refdes fetch` runs the reader here once,
and the extracted decimal is pinned in the citation lockfile
(`citations.py`, docs/design/calc-sources.md §5). A reader's whole job is
therefore narrow: given a file and the exact keys asked of it, return every
one as a finite decimal, or raise `SourceExtractionError` naming what was
wrong. It never returns a fallback, a fuzzy match, or a partial answer.

The one other thing a reader can be asked is the inverse: *what keys does this
file hold?* `list_entries` answers it for a human choosing one
(docs/design/editor-source-picker.md §5), and it is deliberately the same
parse -- same headers, same line numbering, same numeric grammar, same reader
registry -- so a row the picker offers is a row `extract()` will accept. Its
one difference from `extract()` is failure policy, and that is a display
decision: a header-level failure is fatal exactly as it is for `extract()`
(a file `fetch` cannot read is a file the picker must not browse), while a
row-level problem marks that row unselectable and is shown on it rather than
emptying the listing.

The registry is an internal seam (§7): one reader per filename extension,
registered in this module, no entry-point plugins. The fetch coordinator in
`citations.py` owns hashing, lockfile writes, and same-item authorization; a
reader only reads.
"""

from __future__ import annotations

import csv
import difflib
import math
import re
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol


class SourceExtractionError(Exception):
    """A reader could not produce every requested key.

    `problems` is the full diagnostic set, one line each: a reader reports
    everything it found in one pass (§3), so a duplicated key that is not the
    one currently failing still surfaces."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class SourceRequest:
    path: str  # canonical project-relative citation path
    key: str  # source() key, opaque and exact


@dataclass(frozen=True)
class ExtractedSource:
    reader: str  # stable reader identifier, e.g. "csv"
    key: str
    value: Decimal  # finite, unitless scalar only

    @property
    def text(self) -> str:
        """The canonical decimal text the lockfile records."""
        return str(self.value)


@dataclass(frozen=True)
class SourceEntry:
    """One row of a source file, as a human choosing a key needs to see it
    (docs/design/editor-source-picker.md §5).

    `raw` is the value cell exactly as written and `value` is what `extract()`
    would pin for the same cell, or "" when the cell is not a plain decimal.
    Both are on the entry because `1850` and `1.85` are different decisions and
    the canonical text alone hides the formatting surprise. `problem` is empty
    exactly when the row could be picked, and when it is not it carries the
    reader's own words -- a broken row is shown as broken, never hidden, and
    never quietly repaired into a value.
    """

    key: str
    raw: str
    value: str
    line: int
    context: tuple[tuple[str, str], ...]  # the row's other columns, header -> cell
    problem: str = ""

    @property
    def selectable(self) -> bool:
        return not self.problem


@dataclass(frozen=True)
class SourceListing:
    """`list_entries`' answer plus what it had to leave out.

    `truncated` says the file held more data rows than the cap allows and the
    parse *stopped* there, so the rows past it were never read and appear in
    no count here. `rows_read` is what was kept.
    """

    entries: tuple[SourceEntry, ...]
    truncated: bool = False
    rows_read: int = 0


class SourceReader(Protocol):
    name: str
    extensions: tuple[str, ...]

    def extract(
        self, path: Path, requests: Collection[SourceRequest]
    ) -> Mapping[str, ExtractedSource]:
        """Return every requested key or raise SourceExtractionError."""

    # `list_entries` is deliberately NOT declared here. Enumeration is optional
    # -- a format whose keys are not enumerable is a real possibility -- and
    # `sources.list_entries()` reports a reader without it as an error rather
    # than as a file with no keys, which is the one answer that must never be
    # invented.


# ------------------------------------------------------------------------ numbers

# The explicit ASCII grammar (§3). `re.fullmatch` + ASCII flag: no locale
# notation, no units, no underscores, no non-ASCII digits, and -- because it
# must consume the whole cell -- no trailing newline that `$` would forgive.
_NUMBER_RE = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", flags=re.ASCII)
_TRIM = " \t"  # ASCII space and tab only; Unicode whitespace is never erased


def parse_decimal(raw: str) -> Decimal:
    """`raw` as a finite Decimal that also converts to a finite calc float, or
    ValueError naming why not. The reason text is what the diagnostic quotes."""
    text = raw.strip(_TRIM)
    if not text:
        raise ValueError("the value cell is empty (absence is not zero)")
    if not _NUMBER_RE.fullmatch(text):
        raise ValueError(
            f"{raw!r} is not a plain ASCII decimal number (no units, digit "
            "grouping, locale notation, or non-ASCII characters -- declare the "
            "unit on the calc line)"
        )
    try:
        value = Decimal(text)
    except InvalidOperation as exc:  # unreachable past the grammar; belt and braces
        raise ValueError(f"{raw!r} is not a number") from exc
    if not value.is_finite():
        raise ValueError(f"{raw!r} is not finite")
    try:
        as_float = float(value)
    except OverflowError as exc:
        raise ValueError(f"{raw!r} overflows the calculator's numeric range") from exc
    if not math.isfinite(as_float):
        raise ValueError(f"{raw!r} overflows the calculator's numeric range")
    return value


# ---------------------------------------------------------------------------- CSV

# A listing is bounded so one large file cannot pin the server's thread
# (docs/design/editor-source-picker.md §6). Neither limit is a security
# boundary -- the path is confined long before this -- and both are enforced
# where the file is read, not after: the byte cap refuses before the file is
# opened, and the row cap stops the parse rather than truncating a listing
# that has already materialised the whole file.
MAX_LIST_ROWS = 5000
MAX_LIST_BYTES = 1 << 20
# Context columns are here for human recognition ("half load, 12 V in"), not
# as a data channel, so they are cut to a readable size with an explicit mark.
_CONTEXT_COLUMNS = 8
_CONTEXT_CHARS = 80


class CsvReader:
    """UTF-8 (optional BOM) table with exactly one `key` and one `value` header.

    Rows are selected by the exact `key` cell -- never by position, prefix, or
    a label in another column -- and every declared key for the file is
    extracted in this one parse (§3)."""

    name = "csv"
    extensions = (".csv",)

    def extract(
        self, path: Path, requests: Collection[SourceRequest]
    ) -> dict[str, ExtractedSource]:
        wanted = sorted({r.key for r in requests})
        label = path.as_posix()
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                header_line, header, records, _truncated = _read_rows(fh, label)
        except UnicodeDecodeError as exc:
            raise SourceExtractionError(
                [f"{label}: not valid UTF-8 ({exc.reason} at byte {exc.start})"]
            ) from exc
        except OSError as exc:
            raise SourceExtractionError([f"{label}: cannot read file: {exc}"]) from exc

        problems: list[str] = []
        key_col = _header_column(header, "key", label, header_line, problems)
        value_col = _header_column(header, "value", label, header_line, problems)
        if problems:
            raise SourceExtractionError(problems)

        matches: dict[str, list[tuple[int, list[str]]]] = {}
        for line, row in records:
            if len(row) != len(header):
                problems.append(
                    f"{label}:{line}: row has {len(row)} field(s) but the header "
                    f"has {len(header)} (an unquoted comma inside a cell?)"
                )
                continue
            if row[key_col] == "":
                problems.append(f"{label}:{line}: the key cell is blank")
                continue
            matches.setdefault(row[key_col], []).append((line, row))

        out: dict[str, ExtractedSource] = {}
        for key in wanted:
            found = matches.get(key, [])
            if not found:
                # Close keys are prose in the diagnostic only, never a value.
                close = difflib.get_close_matches(key, list(matches), n=3)
                hint = f" (close keys: {', '.join(map(repr, close))})" if close else ""
                problems.append(f"{label}: no row has the key {key!r}{hint}")
                continue
            if len(found) > 1:
                lines = ", ".join(str(line) for line, _ in found)
                problems.append(
                    f"{label}: key {key!r} appears on {len(found)} rows "
                    f"(lines {lines}); a source key must be unique"
                )
                continue
            line, row = found[0]
            try:
                value = parse_decimal(row[value_col])
            except ValueError as exc:
                problems.append(f"{label}:{line}: key {key!r}: {exc}")
                continue
            out[key] = ExtractedSource(self.name, key, value)
        if problems:
            raise SourceExtractionError(problems)
        return out

    def list_entries(
        self,
        path: Path,
        *,
        max_rows: int = MAX_LIST_ROWS,
        max_bytes: int = MAX_LIST_BYTES,
    ) -> SourceListing:
        """Every data row of the file, in file order, as `SourceEntry`.

        Same header rules, same physical line numbers and same numeric grammar
        as `extract()` -- `_read_rows`, `_header_column` and `parse_decimal`
        below are the only things that read a cell -- and one difference in
        failure policy, which is a display decision: a header-level failure
        raises exactly as `extract()` does, because a file `fetch` cannot read
        is a file that must not be browsed, while a row-level problem marks
        *that row* unselectable and leaves the rest of the file listed. The
        author is being shown their own file, and "this row is broken, here is
        why" is more use than an empty panel.
        """
        label = path.as_posix()
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise SourceExtractionError([f"{label}: cannot read file: {exc}"]) from exc
        if size > max_bytes:
            raise SourceExtractionError([
                f"{label}: the file is {size} bytes and a source listing refuses "
                f"anything above {max_bytes} bytes ({max_bytes // 1024} KiB) -- "
                "split it, or point the citation at the rows you need"
            ])
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                header_line, header, records, truncated = _read_rows(
                    fh, label, max_rows
                )
        except UnicodeDecodeError as exc:
            raise SourceExtractionError(
                [f"{label}: not valid UTF-8 ({exc.reason} at byte {exc.start})"]
            ) from exc
        except OSError as exc:
            raise SourceExtractionError([f"{label}: cannot read file: {exc}"]) from exc

        problems: list[str] = []
        key_col = _header_column(header, "key", label, header_line, problems)
        value_col = _header_column(header, "value", label, header_line, problems)
        if problems:
            raise SourceExtractionError(problems)

        entries: list[SourceEntry] = []
        positions: dict[str, list[int]] = defaultdict(list)
        for line, row in records:
            context = _context(row, header, key_col, value_col)
            if len(row) != len(header):
                entries.append(SourceEntry(
                    _cell(row, key_col), _cell(row, value_col), "", line, context,
                    f"{label}:{line}: row has {len(row)} field(s) but the header "
                    f"has {len(header)} (an unquoted comma inside a cell?)",
                ))
                continue
            key = row[key_col]
            raw = row[value_col]
            if key == "":
                entries.append(SourceEntry(
                    key, raw, "", line, context,
                    f"{label}:{line}: the key cell is blank",
                ))
                continue
            positions[key].append(len(entries))
            try:
                value = str(parse_decimal(raw))
            except ValueError as exc:
                entries.append(SourceEntry(
                    key, raw, "", line, context,
                    f"{label}:{line}: key {key!r}: {exc}",
                ))
                continue
            entries.append(SourceEntry(key, raw, value, line, context))

        # A duplicated key marks *both* rows unselectable. `extract()` refuses
        # a repeated key rather than picking first or last, so offering either
        # copy here would be this tool making the exact choice the reader
        # exists to refuse -- both are listed, both say what to fix.
        for key, spots in positions.items():
            if len(spots) < 2:
                continue
            where = ", ".join(str(entries[i].line) for i in spots)
            duplicate = (
                f"{label}: key {key!r} appears on {len(spots)} rows (lines {where}); "
                f"a source key must be unique -- both rows are listed, and neither "
                f"can be picked until the file names one of them differently"
            )
            for i in spots:
                entry = entries[i]
                entries[i] = replace(
                    entry, problem=f"{entry.problem}; {duplicate}" if entry.problem
                    else duplicate,
                )
        return SourceListing(tuple(entries), truncated, len(entries))


def _cell(row: list[str], index: int) -> str:
    """The cell at `index`, or "" when a ragged row is short of it. A ragged row
    is reported as a problem on the row itself, so reading its other cells must
    not raise on the way to that report."""
    return row[index] if 0 <= index < len(row) else ""


def _clip(text: str) -> str:
    """`text` cut to a readable length, with an explicit `…` when it was cut --
    a silent cut would look like the author's own data ending there."""
    return text if len(text) <= _CONTEXT_CHARS else text[:_CONTEXT_CHARS] + "…"


def _context(
    row: list[str], header: list[str], key_col: int, value_col: int
) -> tuple[tuple[str, str], ...]:
    """The row's other columns as `(header, cell)`, capped (§5): at most 8
    columns, 80 characters each. The key and the value are the entry itself, so
    they are not repeated here; everything else is context, and context exists
    to let an author recognise the row they meant."""
    out: list[tuple[str, str]] = []
    for index, name in enumerate(header):
        if len(out) >= _CONTEXT_COLUMNS:
            break
        if index in (key_col, value_col):
            continue
        out.append((_clip(name), _clip(_cell(row, index))))
    return tuple(out)


def _read_rows(fh, label: str, max_rows: int | None = None):
    """(header line, header cells, [(line, cells)...], truncated) from a strict
    csv.reader. Line numbers are the physical line a record starts on. Fully
    blank physical lines carry no fields and cannot shift a column or carry a
    number, so they are skipped; everything else is kept for width checks.

    `max_rows` stops the parse once that many data records have been kept, so a
    bounded listing never materialises the whole file; `truncated` says the file
    had more. Header handling, line numbering and blank-line handling are
    identical either way, and a caller that passes no cap is unaffected.
    """
    reader = csv.reader(fh, strict=True)
    records: list[tuple[int, list[str]]] = []
    previous_end = 0
    truncated = False
    try:
        for row in reader:
            start = previous_end + 1
            previous_end = reader.line_num
            if not row:
                continue
            # `records` still holds the header at index 0, so a data row is one
            # past it.
            if max_rows is not None and len(records) > max_rows:
                truncated = True
                break
            records.append((start, row))
    except csv.Error as exc:
        raise SourceExtractionError(
            [f"{label}:{reader.line_num}: malformed CSV: {exc}"]
        ) from exc
    if not records:
        raise SourceExtractionError([f"{label}: the file is empty (no header row)"])
    header_line, header = records[0]
    return header_line, header, records[1:], truncated


def _header_column(header, name, label, line, problems) -> int:
    hits = [i for i, cell in enumerate(header) if cell == name]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        near = [c for c in header if c.strip().lower() == name and c != name]
        hint = f" (found {near[0]!r}; headers are case- and byte-exact)" if near else ""
        problems.append(f"{label}:{line}: the header row has no {name!r} column{hint}")
    else:
        problems.append(
            f"{label}:{line}: the header row has {len(hits)} {name!r} columns; "
            "exactly one is required"
        )
    return -1


# ----------------------------------------------------------------------- registry

_READERS: dict[str, SourceReader] = {}


def register(reader: SourceReader) -> None:
    for ext in reader.extensions:
        _READERS[ext.lower()] = reader


def reader_for(path: str) -> SourceReader:
    """The one reader for `path`'s extension (case-insensitive). No reader is an
    error, never a fallback to CSV or a best-effort text parse."""
    ext = Path(path).suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        known = ", ".join(sorted(_READERS)) or "none"
        raise SourceExtractionError(
            [f"{path}: no source reader for {ext or 'a file with no extension'!r} "
             f"files (readers exist for: {known})"]
        )
    return reader


def list_entries(
    path: Path,
    *,
    max_rows: int = MAX_LIST_ROWS,
    max_bytes: int = MAX_LIST_BYTES,
) -> SourceListing:
    """Every entry of `path`, through the reader its extension selects.

    Dispatch is the same `reader_for()` registry `extract()` goes through, so
    there is one authority on which rows exist and one on which file types can
    be read at all. A reader that cannot enumerate raises, rather than
    answering with nothing: "this file has no keys" is the one reply a listing
    must never invent.
    """
    reader = reader_for(path.as_posix())
    lister = getattr(reader, "list_entries", None)
    if lister is None:
        raise SourceExtractionError(
            [f"{path.as_posix()}: the {reader.name} reader can extract named "
             "keys but cannot list a file's entries"]
        )
    return lister(path, max_rows=max_rows, max_bytes=max_bytes)


register(CsvReader())
