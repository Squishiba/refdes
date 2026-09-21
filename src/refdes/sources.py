"""Calc source readers: pull one named scalar out of a cited, repo-local file.

`source("analysis/power-budget.csv", "some_key")` in a calc block never opens
that file during `check` or `build` -- `refdes fetch` runs the reader here once,
and the extracted decimal is pinned in the citation lockfile
(`citations.py`, docs/design/calc-sources.md §5). A reader's whole job is
therefore narrow: given a file and the exact keys asked of it, return every
one as a finite decimal, or raise `SourceExtractionError` naming what was
wrong. It never returns a fallback, a fuzzy match, or a partial answer.

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
from collections.abc import Collection, Mapping
from dataclasses import dataclass
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


class SourceReader(Protocol):
    name: str
    extensions: tuple[str, ...]

    def extract(
        self, path: Path, requests: Collection[SourceRequest]
    ) -> Mapping[str, ExtractedSource]:
        """Return every requested key or raise SourceExtractionError."""


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
                rows = _read_rows(fh, label)
        except UnicodeDecodeError as exc:
            raise SourceExtractionError(
                [f"{label}: not valid UTF-8 ({exc.reason} at byte {exc.start})"]
            ) from exc
        except OSError as exc:
            raise SourceExtractionError([f"{label}: cannot read file: {exc}"]) from exc

        header_line, header, records = rows
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


def _read_rows(fh, label: str):
    """(header line, header cells, [(line, cells)...]) from a strict csv.reader.
    Line numbers are the physical line a record starts on. Fully blank
    physical lines carry no fields and cannot shift a column or carry a
    number, so they are skipped; everything else is kept for width checks."""
    reader = csv.reader(fh, strict=True)
    records: list[tuple[int, list[str]]] = []
    previous_end = 0
    try:
        for row in reader:
            start = previous_end + 1
            previous_end = reader.line_num
            if not row:
                continue
            records.append((start, row))
    except csv.Error as exc:
        raise SourceExtractionError(
            [f"{label}:{reader.line_num}: malformed CSV: {exc}"]
        ) from exc
    if not records:
        raise SourceExtractionError([f"{label}: the file is empty (no header row)"])
    header_line, header = records[0]
    return header_line, header, records[1:]


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


register(CsvReader())
