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

A PDF is the other kind of source, and it is not a table: a datasheet row is a
band of a rendered page with several plausible numbers in it, and the value has
to be *found and read* rather than looked up (docs/design/editor-pdf-picker.md
§4). So `PdfReader` answers a different question -- `page_candidates()` gives
one page as positioned text with its runs grouped into rows and every number
grouped into candidates, each labelled with the value `parse_decimal` would pin
and with a *guessed* column header -- and the same ASCII decimal grammar, the
same registry, and the same refusal to invent a number. It deliberately does
NOT implement `extract()`: a PDF source value is picked by a human from a
page's candidates and re-extracted by quoted row at fetch time
(editor-pdf-picker.md §6), and until that lands a `source()` line naming a PDF
says so out loud rather than pinning a number nobody confirmed. pypdf is the
already-optional `refdes[pdf]` extra, so the reader registers on `.pdf` only
when it imports, and a project with no datasheet never needs it.

The registry is an internal seam (§7): one reader per filename extension,
registered in this module, no entry-point plugins. The fetch coordinator in
`citations.py` owns hashing, lockfile writes, and same-item authorization; a
reader only reads.
"""

from __future__ import annotations

import csv
import difflib
import importlib.util
import math
import re
import sys
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
        self,
        path: Path,
        requests: Collection[SourceRequest],
        *,
        label: str | None = None,
    ) -> Mapping[str, ExtractedSource]:
        """Return every requested key or raise SourceExtractionError.

        `label` names the file in the problems raised, exactly as it does on
        `list_entries`: a caller that read the bytes at a server path but serves
        a project-relative one has to say which name the messages may use.
        Default: the path it was handed."""

    # `list_entries` and `page_candidates` are deliberately NOT declared here.
    # Both are optional -- a format whose keys are not enumerable is a real
    # possibility, and so is a format with no pages -- and `sources.list_entries()`
    # reports a reader without the first as an error rather than as a file with
    # no keys, which is the one answer that must never be invented. `page_candidates`
    # says the same about a reader with no pages.


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
        self,
        path: Path,
        requests: Collection[SourceRequest],
        *,
        label: str | None = None,
    ) -> dict[str, ExtractedSource]:
        wanted = sorted({r.key for r in requests})
        # The name every problem below says. A caller serving a project-relative
        # path passes it here, so the filesystem path the bytes came from is
        # never in a string the caller did not choose (`list_entries` documents
        # why this is naming rather than a nicety: a post-hoc scrub covered one
        # branch and not the other).
        label = label if label else path.as_posix()
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
        label: str | None = None,
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

        `label` is the file's name in every message this produces, and it is a
        parameter rather than `path.as_posix()` because the two are not the same
        thing for a caller serving a path to somebody else: the editor reads
        `project.root + canon` and must not hand the root back inside a
        diagnostic. Anything embedded in a `SourceEntry.problem` is the author's
        to read, so the default here is the full path only because every
        non-serving caller is reading a file it already knows the name of.
        """
        name = label if label else path.as_posix()
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise _cannot_read(name, exc) from exc
        if size > max_bytes:
            raise SourceExtractionError([
                f"{name}: the file is {size} bytes and a source listing refuses "
                f"anything above {max_bytes} bytes ({max_bytes // 1024} KiB) -- "
                "split it, or point the citation at the rows you need"
            ])
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                header_line, header, records, truncated = _read_rows(
                    fh, name, max_rows
                )
        except UnicodeDecodeError as exc:
            raise SourceExtractionError(
                [f"{name}: not valid UTF-8 ({exc.reason} at byte {exc.start})"]
            ) from exc
        except OSError as exc:
            raise _cannot_read(name, exc) from exc

        problems: list[str] = []
        key_col = _header_column(header, "key", name, header_line, problems)
        value_col = _header_column(header, "value", name, header_line, problems)
        if problems:
            raise SourceExtractionError(problems)

        entries: list[SourceEntry] = []
        positions: dict[str, list[int]] = defaultdict(list)
        for line, row in records:
            context = _context(row, header, key_col, value_col)
            if len(row) != len(header):
                entries.append(SourceEntry(
                    _cell(row, key_col), _cell(row, value_col), "", line, context,
                    f"{name}:{line}: row has {len(row)} field(s) but the header "
                    f"has {len(header)} (an unquoted comma inside a cell?)",
                ))
                continue
            key = row[key_col]
            raw = row[value_col]
            if key == "":
                entries.append(SourceEntry(
                    key, raw, "", line, context,
                    f"{name}:{line}: the key cell is blank",
                ))
                continue
            positions[key].append(len(entries))
            try:
                value = str(parse_decimal(raw))
            except ValueError as exc:
                entries.append(SourceEntry(
                    key, raw, "", line, context,
                    f"{name}:{line}: key {key!r}: {exc}",
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
                f"{name}: key {key!r} appears on {len(spots)} rows (lines {where}); "
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


def _cannot_read(name: str, exc: OSError) -> SourceExtractionError:
    """`name` cannot be read, with the reason and without the path.

    `str(OSError)` interpolates the filename it was raised on -- the absolute
    path this reader was handed -- so a `label` is not enough on its own here:
    the one string that would undo it is the error's own text. `strerror` is
    the message the OS gave ("No such file or directory", "Permission denied")
    with no path in it, and the errno covers the rare OSErrors that carry none.
    """
    reason = exc.strerror or f"OS error {exc.errno}"
    return SourceExtractionError([f"{name}: cannot read file: {reason}"])


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


# ----------------------------------------------------------------------- PDF
#
# A datasheet is not a table (docs/design/editor-pdf-picker.md §4). What a human
# picking a value off a page needs is: the page as positioned text, so the row
# can be seen in its neighbourhood; the runs grouped into rows, because a table
# row is a y-band rather than a line of a file; the numbers in a row as a list,
# because a min/typ/max row has three plausible answers and choosing one is the
# author's job; and each number labelled with the column header above it, as a
# *guess*, so "which column is TYP?" is a question the panel can raise.
#
# What it must not do is the CSV reader's job differently: the numbers offered
# are the ones `parse_decimal` accepts, or they are not offered at all, so the
# picker cannot present a value `fetch` would refuse.

# A PDF is a bigger file than a CSV, so the byte cap is bigger, and two of the
# three bounds have no CSV analogue: one page's runs, and one page's numbers.
# The rule is the CSV one -- bounded where the file is read, named when hit --
# and the numbers are proposals (editor-pdf-picker.md §10 Q7).
MAX_PDF_BYTES = 32 << 20
MAX_PAGE_SPANS = 1000
MAX_PAGE_CANDIDATES = 200
# A run's advance width is not something pypdf reports (its visitor hands over
# the text, the two matrices and the font size, and no glyph widths), so a token
# and run width is *estimated* from the character count at a nominal half-em per
# character -- about right for the proportional fonts a datasheet is set in. It
# is used for where a token sits and for the column guess, never for the number
# itself, which comes out of the token's own text.
_NOMINAL_EM = 0.5
# One row is a band of the page: runs whose baselines are within half a font
# size of each other are the same row. Derived from the font size rather than a
# constant, so a 5-point parameter table and an 11-point heading both group and
# a superscript inside a cell does not become a row of its own.
_ROW_TOLERANCE = 0.5
# Whitespace, for splitting a run into words. Unicode-aware on purpose: a
# non-breaking space in an extracted run is a space, and a token the author can
# see whole is a token they can judge. The *value* grammar is unaffected --
# `parse_decimal` still accepts ASCII decimals only.
_TOKEN_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class PageSpan:
    """One extracted text run and where it sits on the page.

    `x`/`y` are the run's baseline in PDF user space (y grows upward, the same
    way the document does), `size` the font size scaled by both matrices, and
    `width` the *estimated* advance width -- see `_NOMINAL_EM`. `text` is
    verbatim, which is what makes a quoted row re-verifiable by eye later.
    """

    text: str
    x: float
    y: float
    size: float
    width: float


@dataclass(frozen=True)
class PageToken:
    """One word of one row, and -- if it reads as a number -- one candidate.

    `value` is what `parse_decimal` pins for `text`, and is what makes a token a
    candidate: the CSV reader's `SourceEntry` carries both spellings for the same
    reason (`.5` and `0.5` are one number and one decision), and a token that is
    not a plain ASCII decimal is context, never a number with a value guessed
    beside it. `numeric_index` is 0-based among the row's candidates -- the number
    a lockfile record names its value by (editor-pdf-picker.md §6) -- and is -1
    for a token that is not one. `header_guess` is the column-header *guess* and is
    presentation only: it is never recorded, because a guess the author can see
    and correct is worth carrying and a guess written down would be a fact.
    """

    text: str
    value: str
    x: float
    width: float
    index: int
    numeric_index: int = -1
    header_guess: str = ""

    @property
    def candidate(self) -> bool:
        return self.numeric_index >= 0


@dataclass(frozen=True)
class PageRow:
    """One y-band of a page: its tokens left to right, and its candidates.

    `text` is the quote -- the row's tokens joined by one space, verbatim -- and
    `labels` is that quote's identity: the non-numeric tokens, exactly as
    written and case-sensitively normalized by nothing at all. A recorded value
    is re-found by matching `labels` and taking the token at a numeric index
    (editor-pdf-picker.md §6), so a datasheet revision that moves a row to
    another page still resolves it, and a revision that changes the number
    surfaces as the drift the build already warns about.
    """

    index: int
    y: float
    tokens: tuple[PageToken, ...]

    @property
    def text(self) -> str:
        return " ".join(token.text for token in self.tokens)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(token.text for token in self.tokens if not token.candidate)

    @property
    def candidates(self) -> tuple[PageToken, ...]:
        return tuple(token for token in self.tokens if token.candidate)

    @property
    def candidate_count(self) -> int:
        return sum(1 for token in self.tokens if token.candidate)


@dataclass(frozen=True)
class PageListing:
    """One page as the picker needs it: the runs, the rows, the page's bounds.

    `span_count` is the number of runs collected, and is a *lower* bound when
    `too_dense` -- the page held more than the cap and reading stopped there.
    `candidate_count` counts the numeric candidates on the page and, like the CSV
    listing's `rows_read`, counts only what was read: `truncated` says the cap
    stopped the count, so the rest of the page is in no number here.
    `too_dense` is a page reported as not browsable rather than a page cut in
    half: half a page's rows is not a page, and a silently truncated one is a
    lie wearing a correct shape. `detail` is the visible-failure wording the
    panel shows in place of a value (editor-pdf-picker.md §3) -- a page with no
    extractable text, a page with no numbers, a page too dense to read -- and is
    empty when there is something to look at.
    """

    page: int
    pages: int
    spans: tuple[PageSpan, ...] = ()
    rows: tuple[PageRow, ...] = ()
    span_count: int = 0
    candidate_count: int = 0
    truncated: bool = False
    too_dense: bool = False
    detail: str = ""

    @property
    def prev(self) -> int | None:
        return self.page - 1 if self.page > 1 else None

    @property
    def next(self) -> int | None:
        return self.page + 1 if self.page < self.pages else None


class PdfReader:
    """A PDF datasheet, read one page at a time for a human choosing a value.

    Registered on `.pdf` only when pypdf imports (editor-pdf-picker.md §8), so
    the extra stays optional and a project with no datasheet never needs it.

    `extract()` is *not* implemented, on purpose. A PDF has no named keys: a
    value is named by a page and a quoted row, chosen by the author in the
    editor's confirm step, and pinned by re-extracting it from the quoted text
    at fetch time (editor-pdf-picker.md §6, §12 Slice P-C). Until that lands,
    `refdes fetch` on a `source()` line naming a PDF must say exactly that -- a
    file `fetch` cannot read is a file the picker must not browse, and this is
    the same rule read from the other side.
    """

    name = "pdf"
    extensions = (".pdf",)

    def extract(
        self,
        path: Path,
        requests: Collection[SourceRequest],
        *,
        label: str | None = None,
    ) -> Mapping[str, ExtractedSource]:
        # The keyword is the `SourceReader` protocol's, and every caller passes
        # it -- `citations._extract_source_values` does, which is how a `source()`
        # line naming a PDF reaches here. Refusing without accepting it would be
        # a `TypeError` where the answer is a `SourceExtractionError`, and a
        # caller serving a project-relative path is only allowed to say that
        # name, never the server path it read these bytes from.
        label = label if label else path.as_posix()
        keys = ", ".join(sorted({request.key for request in requests})) or "none"
        raise SourceExtractionError([
            f"{label}: the pdf reader does not extract values: a PDF's values "
            "are picked from a page's candidates and re-extracted from the "
            f"quoted row (editor-pdf-picker.md §6) -- no value was extracted for "
            f"key(s) {keys}"
        ])

    def list_entries(
        self,
        path: Path,
        *,
        label: str | None = None,
        max_rows: int = MAX_LIST_ROWS,
        max_bytes: int = MAX_LIST_BYTES,
    ) -> SourceListing:
        """Refuses, with the reason a PDF cannot be listed as a key table.

        Not an absent method, because an absent one would be reported as "the pdf
        reader can extract named keys but cannot list a file's entries" -- which
        is the wrong half of the story while `extract()` is unimplemented too.
        The row list a PDF has is a page's rows, and those are read per page.
        """
        name = label if label else path.as_posix()
        raise SourceExtractionError([
            f"{name}: a PDF has no key column -- its values are chosen from a "
            "page's numeric candidates and recorded by quoted row, not listed "
            "as a table of keys (editor-pdf-picker.md §4)"
        ])

    def page_candidates(
        self,
        path: Path,
        page: int = 1,
        *,
        label: str | None = None,
        max_bytes: int = MAX_PDF_BYTES,
        max_spans: int = MAX_PAGE_SPANS,
        max_candidates: int = MAX_PAGE_CANDIDATES,
    ) -> PageListing:
        """One page of the file: its runs, the rows they group into, and every
        number in them as a candidate.

        `label` is the file's name in every message, for exactly the reason
        `CsvReader.list_entries` documents: a caller serving a path to somebody
        else is handed `project.root + canon` to read and `canon` to say, so
        nothing this produces can carry a server path.

        The three caps are enforced here, where the file is read: the byte cap
        refuses before the file is opened, the span cap stops reading and
        reports the page as too dense rather than showing half of it, and the
        candidate cap stops the count and says so -- the same "truncated" shape
        `SourceListing` already uses, and the same reason: what was not read is
        in no count, rather than being a number of zero.
        """
        name = label if label else path.as_posix()
        if page < 1:
            raise SourceExtractionError([
                f"{name}: page {page} is not a page of a document; pages are "
                "counted from 1"
            ])
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise _cannot_read(name, exc) from exc
        if size > max_bytes:
            raise SourceExtractionError([
                f"{name}: the file is {size} bytes and a page read refuses "
                f"anything above {max_bytes} bytes ({max_bytes >> 20} MiB) -- "
                "cite the datasheet revision you need, or a smaller document"
            ])
        reader_cls = _pypdf_reader(name)
        try:
            with open(path, "rb") as fh:
                document = reader_cls(fh)
                count = len(document.pages)
                if page > count:
                    raise SourceExtractionError([
                        f"{name}: page {page} is not in this document -- it has "
                        f"{count} page(s)"
                    ])
                spans, too_dense = _page_spans(document.pages[page - 1], max_spans)
                if not too_dense and _positions_missing(spans):
                    version = _pypdf_version() or "unknown version"
                    raise SourceExtractionError([
                        f"{name}: this pypdf ({version}) does not report where "
                        "the text on a page is, so its rows cannot be placed on "
                        "the page -- the pdf source reader needs pypdf>=6.19: "
                        "pip install -U 'refdes[pdf]'"
                    ])
        except SourceExtractionError:
            raise
        except OSError as exc:
            raise _cannot_read(name, exc) from exc
        except Exception as exc:  # pypdf raises many types here, none of them ours
            raise SourceExtractionError([
                f"{name}: pypdf could not read the PDF: {exc}"
            ]) from exc

        if too_dense:
            return PageListing(
                page, count, (), (), span_count=len(spans), too_dense=True,
                detail=(
                    f"this page holds more than {max_spans} text runs, which is "
                    "too dense to browse as positioned text -- nothing past the "
                    "cap was read, so what is here is no part of the page"
                ),
            )
        if not spans:
            return PageListing(
                page, count, (), (), span_count=0,
                detail=(
                    f"could not read page {page} -- no extractable text (this "
                    "looks like a scanned or image-only PDF; OCR is out of scope)"
                ),
            )
        rows, candidates, truncated = _page_rows(spans, max_candidates)
        detail = ""
        if truncated:
            detail = (
                f"stopped at the {max_candidates}-candidate cap; the rest of "
                f"page {page} was not read, so it is in no count here"
            )
        elif not candidates:
            detail = (
                f"page {page} has {len(spans)} text run(s) but no number that "
                "reads as a plain ASCII decimal, so there is nothing to choose "
                "here"
            )
        return PageListing(
            page, count, tuple(spans), rows, len(spans), candidates, truncated,
            detail=detail,
        )


def _pypdf_reader(name: str):
    """pypdf's `PdfReader`, through the one import site that owns it.

    `citations._import_pypdf()` is the only place in the codebase that imports
    pypdf, and this calls it rather than importing it again: the extra has one
    install hint attached to it, and two import sites would be two places for
    them to drift apart. The import is inside the function because
    `citations` imports this module -- resolving either at import time would
    depend on which one was imported first -- and because a project with no
    datasheet must not import pypdf at all.

    A missing extra becomes this reader's own error, in the same words
    `section:` gets, because a cited `.pdf` is a perfectly normal thing for a
    project to have and the fix is one install away.
    """
    from . import citations as citations_mod

    try:
        return citations_mod._import_pypdf()
    except citations_mod.SectionError as exc:
        raise SourceExtractionError([
            f"{name}: the pdf source reader {citations_mod.PDF_EXTRA_HINT}"
        ]) from exc


def _pypdf_version() -> str:
    """The installed pypdf's version, read out of `sys.modules`.

    `_pypdf_reader` has already imported the package, so this asks the module
    object rather than importing it again -- the version is here to be quoted in
    a refusal an author can act on, and a second import site for a version
    string would be one more thing to keep in step."""
    return str(getattr(sys.modules.get("pypdf"), "__version__", "") or "")


def _positions_missing(spans: list[PageSpan]) -> bool:
    """Whether these runs came from a pypdf that does not report positions.

    Up to pypdf 6.18, `visitor_text` was handed a *zeroed* text matrix for every
    run it inserted a space in front of -- which is most of a table's cells --
    and reported the real position on the empty callback just before it. A
    datasheet page therefore came back with half its rows collapsed onto the
    page's bottom-left corner: numbers that read fine in rows nobody can place,
    and a page view drawn in the corner. 6.19 fixed it, and `pyproject.toml`
    asks for that version; this is the net for an install that predates the
    floor, because the alternative is drawing it.

    Half the runs sitting exactly on the origin is not a page -- that corner is
    outside every text margin a datasheet is set with -- so this does not
    misfire on a real document. A page with only a couple of runs to place is
    not caught here, which is deliberate: there the positions are mostly right,
    and a refusal would cost more than it protects.
    """
    if len(spans) < 2:
        return False
    at_origin = sum(1 for span in spans if span.x == 0.0 and span.y == 0.0)
    return at_origin * 2 >= len(spans)


def _page_spans(page, max_spans: int) -> tuple[list[PageSpan], bool]:
    """Every text run on one page, with the position pypdf reports for it.

    `visitor_text` hands each run's text, the current transformation matrix, the
    text matrix and the font size, and nothing else -- no glyph widths and no
    rectangles -- so the baseline is the text matrix composed with the
    transformation, the size is the font size scaled by both, and the width is
    the estimate `_NOMINAL_EM` documents. Whitespace-only runs are dropped: they
    carry no word, no column and no number, and a row of them would be a row of
    nothing.

    One thing this cannot repair, and does not pretend to: a producer that
    positions a space with a kerning offset instead of writing a space character
    hands pypdf one run whose text has no gap in it, so its words arrive glued
    (`VOUTEff0.93`) and a number glued to a label is not a number. That is a
    missing candidate rather than a wrong one, and the row carries the text it
    grouped, so the panel shows the author the glued row and offers nothing
    from it. Inventing the gap would mean guessing where a word ends, which is
    the one thing this whole feature exists not to do.

    Reading stops once the page has more runs than `max_spans`, and says so
    (True) rather than returning a prefix of the page.
    """
    spans: list[PageSpan] = []
    too_dense = False

    def visit(text, cm, tm, font_dict, font_size) -> None:
        nonlocal too_dense
        if too_dense or not text or not text.strip():
            return
        scale_x = math.hypot(tm[0], tm[1]) * math.hypot(cm[0], cm[1])
        scale_y = math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3])
        size = abs(font_size) * scale_y
        # device point = cm applied to the text matrix's own translation
        x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
        y = cm[1] * tm[4] + cm[3] * tm[5] + cm[5]
        spans.append(PageSpan(
            text=text, x=x, y=y, size=size,
            width=len(text) * size * _NOMINAL_EM * scale_x,
        ))
        if len(spans) > max_spans:
            too_dense = True

    page.extract_text(visitor_text=visit)
    return spans, too_dense


def _page_rows(
    spans: list[PageSpan], max_candidates: int
) -> tuple[list[PageRow], int, bool]:
    """(`(rows, candidate count, hit the cap)`) for one page's runs.

    Rows are the runs grouped by vertical proximity, top to bottom, and left to
    right within a row -- the same order a person reads the page in, so row 0 is
    the top of the page and a truncated page keeps its top rather than a
    random slice. Rotation is not second-guessed: pypdf reports a rotated run's
    baseline in its own frame, so rotated text groups wherever that lands. It
    shows: the row carries the text it grouped, so a merge is visible on the
    panel rather than a number that quietly changed meaning.
    """
    ordered = sorted(spans, key=lambda span: (-span.y, span.x))
    grouped: list[list[PageSpan]] = []
    for span in ordered:
        for row in reversed(grouped):
            if abs(span.y - row[0].y) <= _ROW_TOLERANCE * min(span.size, row[0].size):
                row.append(span)
                break
        else:
            grouped.append([span])

    rows: list[PageRow] = []
    found = 0
    truncated = False
    for index, row in enumerate(grouped):
        tokens: list[PageToken] = []
        for span in sorted(row, key=lambda s: s.x):
            # pypdf prepends a space to a run that starts a line of text away
            # from the last one, so a run's own text can begin with whitespace
            # that has no glyph behind it. That leading gap is dropped from the
            # offset arithmetic and nothing else is, which puts a run's first
            # token exactly on the run's origin -- the one position here that is
            # a fact rather than an estimate, and the one the column guess hangs
            # off -- while a real space between two words still takes its share
            # of the run's width.
            inked = list(_TOKEN_RE.finditer(span.text))
            lead = inked[0].start() if inked else 0
            inked_total = len(span.text) - lead
            for match in inked:
                text = match.group(0)
                step = span.width / inked_total if inked_total else 0.0
                tokens.append(PageToken(
                    text=text,
                    value=_numeric_value(text),
                    x=span.x + (match.start() - lead) * step,
                    width=len(text) * step,
                    index=0,  # left-to-right order, fixed once the row is built
                ))
        tokens.sort(key=lambda token: token.x)
        numeric = [t for t in tokens if t.value]
        if found + len(numeric) > max_candidates:
            # The cap stops the page, and the rest of it is in no count: the CSV
            # row cap's posture, on a page, for the same reason.
            truncated = True
            break
        found += len(numeric)
        rows.append(PageRow(index, row[0].y, tuple(_with_numbers(
            tokens, rows[-1] if rows else None,
        ))))
    return rows, found, truncated


def _numeric_value(text: str) -> str:
    """`text` as the canonical decimal `parse_decimal` would pin, or "".

    The one place a token becomes a candidate, and it is the CSV reader's own
    grammar reached through the CSV reader's own function: a token the fetcher
    would refuse is a token the picker does not offer, which is the whole of
    editor-source-picker.md §5's one-parser rule applied to a page.
    """
    try:
        return str(parse_decimal(text))
    except ValueError:
        return ""


def _with_numbers(tokens: list[PageToken], above: PageRow | None) -> list[PageToken]:
    """`tokens` with their numeric indexes and column-header guesses filled in.

    The index is 0-based among the row's candidates, in left-to-right order, and
    is the number a lockfile record would name this value by. The header is the
    token in the row above whose x-range overlaps this one's -- a *guess*, for
    recognising which column of a min/typ/max table a number is in, and the
    reason it is allowed to be wrong: the row above may be another data row, in
    which case the overlapping token is a number. It is never recorded, and
    nothing is ever selected from it.
    """
    out: list[PageToken] = []
    numeric = 0
    for token in tokens:
        if not token.value:
            out.append(replace(token, index=len(out)))
            continue
        best, overlap_best = "", 0.0
        for other in above.tokens if above else ():
            overlap = min(
                token.x + token.width, other.x + other.width
            ) - max(token.x, other.x)
            if overlap > overlap_best:
                best, overlap_best = other.text, overlap
        out.append(replace(
            token, index=len(out), numeric_index=numeric, header_guess=best,
        ))
        numeric += 1
    return out


# ----------------------------------------------------------------------- registry

_READERS: dict[str, SourceReader] = {}
# Extensions whose reader is registered only when an optional dependency imports,
# mapped to that reader's name. An extension here is not "unhandled": it is
# handled by something this install does not have, and the difference is the
# whole message -- "no source reader for '.pdf' files" would send an author
# looking for a code change, when the fix is one install away.
_GATED: dict[str, str] = {}


def register(reader: SourceReader) -> None:
    for ext in reader.extensions:
        _READERS[ext.lower()] = reader


def register_pdf_reader() -> None:
    """(Re)register the `pdf` reader, or record why it is missing.

    Import-gated (editor-pdf-picker.md §8): pypdf is the already-optional
    `refdes[pdf]` extra, and a project with no datasheet must not need it. The
    availability probe is `importlib.util.find_spec`, which finds the
    distribution without importing it, so importing this module does not pull
    pypdf in -- and cannot trip over a half-imported `citations`, which imports
    this module and is where the one real import lives
    (`citations._import_pypdf()`, called per read by `PdfReader`).

    Callable rather than a one-shot at import so the gate is testable: "what
    does this server do without the extra" is a question the design asks
    (editor-pdf-picker.md §11), and the honest way to answer it is to re-run the
    decision under a missing import rather than to argue about it.
    """
    for ext in PdfReader.extensions:
        _READERS.pop(ext, None)
        _GATED.pop(ext, None)
    if importlib.util.find_spec("pypdf") is None:
        for ext in PdfReader.extensions:
            _GATED[ext] = PdfReader.name
        return
    register(PdfReader())


def _gated_problem(path: str, name: str) -> SourceExtractionError:
    """`path` has no reader because an optional extra is not installed.

    The hint is the one `section:` already shows, read out of the module that
    owns it: `citations` imports this one, so it is imported here at raise time
    rather than at import time, and in either order.
    """
    from . import citations as citations_mod

    return SourceExtractionError(
        [f"{path}: the {name} source reader {citations_mod.PDF_EXTRA_HINT}"]
    )


def reader_for(path: str) -> SourceReader:
    """The one reader for `path`'s extension (case-insensitive). No reader is an
    error, never a fallback to CSV or a best-effort text parse. An extension
    whose reader is gated on an optional extra is refused with that extra's
    install hint, which is a different instruction from "this file type is not
    a source"."""
    ext = Path(path).suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        gated = _GATED.get(ext)
        if gated is not None:
            raise _gated_problem(path, gated)
        known = ", ".join(sorted(_READERS)) or "none"
        raise SourceExtractionError(
            [f"{path}: no source reader for {ext or 'a file with no extension'!r} "
             f"files (readers exist for: {known})"]
        )
    return reader


def list_entries(
    path: Path,
    *,
    label: str | None = None,
    max_rows: int = MAX_LIST_ROWS,
    max_bytes: int = MAX_LIST_BYTES,
) -> SourceListing:
    """Every entry of `path`, through the reader its extension selects.

    Dispatch is the same `reader_for()` registry `extract()` goes through, so
    there is one authority on which rows exist and one on which file types can
    be read at all. A reader that cannot enumerate raises, rather than
    answering with nothing: "this file has no keys" is the one reply a listing
    must never invent.

    `label` is the file's name in every message the result carries, and it
    reaches the reader for exactly the reason `CsvReader.list_entries` documents:
    a caller serving a path to somebody else must not hand back the filesystem
    path it read the bytes from.
    """
    name = label if label else path.as_posix()
    reader = reader_for(name)
    lister = getattr(reader, "list_entries", None)
    if lister is None:
        raise SourceExtractionError(
            [f"{name}: the {reader.name} reader can extract named "
             "keys but cannot list a file's entries"]
        )
    return lister(path, label=label, max_rows=max_rows, max_bytes=max_bytes)


def page_candidates(
    path: Path,
    page: int = 1,
    *,
    label: str | None = None,
    max_bytes: int = MAX_PDF_BYTES,
    max_spans: int = MAX_PAGE_SPANS,
    max_candidates: int = MAX_PAGE_CANDIDATES,
) -> PageListing:
    """One page of `path` as positioned text plus its numeric candidates,
    through the reader its extension selects.

    Dispatch is the same `reader_for()` registry the other two entry points go
    through, so there is one authority on which file types can be read at all --
    and a CSV asked for a page is refused by the same registry that would
    refuse it for a value, not by a special case here. A reader with no pages
    raises rather than answering with an empty page: "this document has nothing
    on it" is the one reply a page read must never invent.

    `label` and the three caps mean what they mean for `list_entries`, and
    reach the reader for the same reason.
    """
    name = label if label else path.as_posix()
    reader = reader_for(name)
    reader_page = getattr(reader, "page_candidates", None)
    if reader_page is None:
        raise SourceExtractionError(
            [f"{name}: the {reader.name} reader has no pages to read -- a page "
             "of positioned text is a PDF thing (editor-pdf-picker.md §4)"]
        )
    return reader_page(
        path, page, label=label, max_bytes=max_bytes, max_spans=max_spans,
        max_candidates=max_candidates,
    )


register(CsvReader())
register_pdf_reader()
