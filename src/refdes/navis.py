"""Navis: project-wide flying notes (in-prog-logs/navis-design-20261025.md).

A Navi is one hand-authored marker in an item body -- a closed, single-line
HTML comment on the `navi:` prefix:

    navi_marker = "<!--navi:" [ key wsp ] text "-->"      # one line only
    key         = 11 chars from keys.ALPHABET
    text        = any text, single line, not containing "-->"

Slice 1 (§13) is the grammar, the body scan, the malformed-marker
diagnostics, the read-only CLI and the `index` payload. Nothing here
mints a key, writes a file, or reads an archive record.

Inertness is the whole point of the comment form (§4): the marker is
invisible in every standard Markdown renderer, it cannot trigger inline
calc (comments suppress spans, `inline_calc.py:1-4`), and fenced code,
indented code blocks, inline code spans (including ones that close on a
later line) and open HTML comments carry it as literal text. Inertness
is therefore defined by the project's OWN renderer, not re-derived:
`_live_markers` parses the body with `build._markdown_parser` -- the
same parse the site renders with -- and scans only the `inline` tokens'
content, so a fence inside a list item, a fence inside a blockquote, a
multi-line code span and a CRLF body are inert exactly when the
renderer says they are (the reviews of the first line-based scanner kept
finding one more context it got wrong; the matrix in
`tests/test_navis_matrix.py` pins that this stays true).
Consumption (stripping the marker from the body copy handed to
`md.render`, build.render_bodies) is what
keeps the escaped comment text off the published site; it happens on a
render-local string, never on `Item.body`, so no hash, seal or history
input ever sees a scan-side change (§7).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import keys as keys_mod
from .model import Diagnostic, Item, Navi

if TYPE_CHECKING:
    from .model import Project

MARKER_OPEN = "<!--navi:"
COMMENT_CLOSE = "-->"

# A key-shaped head: the 11 characters right after `navi:`, delimited by
# whitespace (or the marker's end). Exactly 11 non-space characters is
# key-shaped; a key-shaped head outside the key alphabet is a typo to
# report, not text to absorb (the closed-family posture, build.py:66-68).
_KEY_SHAPED_RE = re.compile(r"^(\S{11})(?:[ \t]+(.*)|\Z)", re.DOTALL)
_ALPHABET = frozenset(keys_mod.ALPHABET)

# A line left with nothing but blockquote prefixes, list markers and
# whitespace once its markers go is a structural line: those prefixes are
# container markers, not content -- and a bare `>` line is a blockquote
# paragraph break while a bare bullet is an empty item, so the residue
# would change the page. Such a line is dropped whole, terminator with it,
# like a whitespace-only one.
_CONTAINER_ONLY_RE = re.compile(r"[ \t]*(?:(?:[>\-*+]|\d{1,9}[.)])[ \t]*)*")


class NavisMappingError(RuntimeError):
    """A live marker whose bytes cannot be named exactly on the raw source
    line. This is an internal bug, not author input: the scan-mapping
    layer guarantees every live marker maps to its raw span, and anything
    it cannot map must fail loud (the reviews of the text-search fallback
    showed a "best guess" locates the WRONG occurrence -- an inert twin
    earlier on the same line -- and strips the page's real text).
    """


def _raw_prefix(
    raw_lines: list[str], cursors: dict[int, int], line: int, content_line: str
) -> int:
    """The column where `content_line` (line `line` of an inline token's
    content) starts on the raw body line.

    Container prefixes (a list bullet, a `>` quote marker, an ATX `#`, a
    link's `[`, a table cell's pipes) are stripped by the block tokenizer,
    so the content line sits inside the raw line at some column. The true
    column is the occurrence that runs to the end of the line (paragraph
    bodies: the prefix is all that precedes the content), searched from a
    per-line cursor (a table row hosts several cells, visited left to
    right); a content line that does not run to the end of the raw line is
    a cell, taken at its first occurrence from the cursor. An occurrence
    cannot be found only if the parser changed content bytes -- that is a
    mapping bug: raise.
    """
    raw = raw_lines[line]
    cursor = cursors.get(line, 0)
    if not content_line:
        return cursor
    idx = raw.find(content_line, cursor)
    while idx >= 0:
        end = idx + len(content_line)
        if not raw[end:].strip(" \t\r"):
            cursors[line] = end
            return idx
        idx = raw.find(content_line, end)
    idx = raw.find(content_line, cursor)
    if idx < 0:
        raise NavisMappingError(
            f"inline content {content_line!r} is not on raw line {raw!r}: the scan "
            "cannot name the marker's bytes (internal mapping bug, not author input)"
        )
    cursors[line] = idx + len(content_line)
    return idx


def _scan_block(
    content: str, base_line: int
) -> tuple[list[tuple[int, int, int, str]], list[tuple[int, str]]]:
    """Markers and two-line-marker warnings of one `inline` token's raw
    content, whose first source line is `base_line`.

    One pass over the whole content -- comment state AND code-span state
    carry across its newlines, exactly as the renderer reads them: a code
    span opened on one line and closed on the next is inert, an open
    comment swallows every marker until its first ``-->``, and a
    ``<!--navi:`` that closes on a LATER line is a warning naming the
    one-line grammar (its bytes stay on the page as the escaped comment
    the renderer shows -- never a silent swallow). A ``<!--navi:`` that
    never closes belongs to the existing unclosed-comment warning
    (`build.py:1797-1803`), so nothing is reported for it here.

    CommonMark backslash escapes are honoured: a backslash before any
    ASCII punctuation makes it literal, so ``\\` `` cannot open a code span
    and ``\\<`` cannot start a comment -- exactly the renderer's reading.

    Spans are ``(line, start, end)`` offsets into `content`, whose line
    offsets index the body's lines.
    """
    found: list[tuple[int, int, int, str]] = []
    warnings: list[tuple[int, str]] = []
    n = len(content)
    i = 0
    line = 0
    in_comment = False
    while i < n:
        char = content[i]
        if char == "\n":
            line += 1
            i += 1
            continue
        if in_comment:
            close = content.find(COMMENT_CLOSE, i)
            if close < 0:
                break  # the rest is comment text (the unclosed-comment warning's)
            line += content.count("\n", i, close + len(COMMENT_CLOSE))
            i = close + len(COMMENT_CLOSE)
            in_comment = False
            continue
        if char == "\\":  # CommonMark: escapes the (punctuation) character
            if content[i + 1:i + 2] == "\n":
                line += 1  # a hard break, not a line for the scan to start on
            i += 2
            continue
        if content.startswith(MARKER_OPEN, i):
            close = content.find(COMMENT_CLOSE, i + len(MARKER_OPEN))
            if close < 0:
                break  # an unclosed `<!--navi:`: the unclosed-comment warning owns it
            end = close + len(COMMENT_CLOSE)
            inner = content[i + len(MARKER_OPEN):close]
            if "\n" in inner:
                warnings.append(
                    (
                        base_line + line,
                        "navi marker spans lines; a marker is one line: "
                        "`<!--navi: the reminder-->`",
                    )
                )
            else:
                line_start = content.rfind("\n", 0, i) + 1
                found.append((base_line + line, i - line_start, end - line_start, inner))
            line += content.count("\n", i, end)
            i = end
            continue
        if content.startswith("<!--", i):
            in_comment = True
            i += len("<!--")
            continue
        if char == "`":
            run_start = i
            while i < n and content[i] == "`":
                i += 1
            run = i - run_start
            close = content.find("`", i)
            while close >= 0:
                run_end = close
                while run_end < n and content[run_end] == "`":
                    run_end += 1
                if run_end - close == run:
                    # the span is inert, its newlines included
                    line += content.count("\n", run_start, run_end)
                    i = run_end
                    break
                close = content.find("`", run_end)
            # an unclosed run is literal text; i already sits past it
            continue
        i += 1
    return found, warnings


def _live_markers(body: str) -> tuple[list[tuple[int, int, int, str]], list[tuple[int, str]]]:
    """Every live marker of one body, in document order, as
    ``(line, start, end, inner)`` with the span being the marker's EXACT
    bytes on the raw body line (absolute columns), plus two-line-marker
    warnings as ``(line, message)``.

    Live means *outside the renderer's inert regions*: `md.parse` (the
    project's own parser, `build._markdown_parser`) tokenizes the body;
    every block that is not an `inline` token -- fenced code, tilde
    fences, indented code, code that lives inside a list item or a
    blockquote, on LF or CRLF source alike -- is inert by construction,
    and a marker inside an inline token's code spans, open comments, or
    backslash escapes is inert by the same character rules the renderer
    uses. The content-relative spans are mapped to raw columns through
    `_raw_prefix` (container prefixes), so a marker in a blockquote, a
    list item, a table cell, a link label, or an ATX heading is located
    at its absolute (line, column) -- never by a text search that can hit
    an inert twin of the same text earlier on the line. A body line's
    trailing ``\\r`` (CRLF) sits after every span's end, so absolute
    columns index the raw lines too.
    """
    from .build import _markdown_parser  # lazy: build imports this module

    raw_lines = body.split("\n")
    found: list[tuple[int, int, int, str]] = []
    warnings: list[tuple[int, str]] = []
    cursors: dict[int, int] = {}
    for token in _markdown_parser().parse(body):
        if token.type != "inline" or token.map is None:
            continue
        block_found, block_warnings = _scan_block(token.content, token.map[0])
        warnings.extend(block_warnings)
        if not block_found:
            continue
        prefixes = [
            _raw_prefix(raw_lines, cursors, token.map[0] + j, content_line)
            for j, content_line in enumerate(token.content.split("\n"))
        ]
        for line, start, _end, inner in block_found:
            prefix = prefixes[line - token.map[0]]
            marker = f"{MARKER_OPEN}{inner}{COMMENT_CLOSE}"
            abs_start = prefix + start
            raw_line = raw_lines[line]
            if raw_line[abs_start:abs_start + len(marker)] != marker:
                raise NavisMappingError(
                    f"marker {marker!r} not at column {abs_start} of {raw_line!r}: "
                    "the scan cannot name the marker's bytes (internal mapping bug)"
                )
            found.append((line, abs_start, abs_start + len(marker), inner))
    found.sort(key=lambda marker: (marker[0], marker[1]))
    warnings.sort()
    return found, warnings


def parse_marker(inner: str) -> tuple[str, str, str | None]:
    """``(key, text, error)`` for one marker's inner text (the bytes between
    ``<!--navi:`` and ``-->``). ``error`` is set for a malformed marker;
    the grammar is a closed family and a typo is reported, never absorbed.
    """
    match = _KEY_SHAPED_RE.match(inner)
    if match is not None:
        head = match.group(1)
        if all(ch in _ALPHABET for ch in head):
            text = (match.group(2) or "").strip()
            if not text:
                return head, "", "navi marker has no text; write `<!--navi: the reminder-->`"
            return head, text, None
        return "", "", (
            f"navi marker key {head!r} is not 11 characters of the key alphabet; "
            "write `<!--navi: the reminder-->` and the tool will mint the key"
        )
    text = inner.strip()
    if not text:
        return "", "", "navi marker has no text; write `<!--navi: the reminder-->`"
    return "", text, None


def scan_body(body: str) -> tuple[list[Navi], list[tuple[int, str]]]:
    """``([Navi...], [(line_offset, message)...])`` for one item body.

    `line_offset` is 0-indexed within the body (add `Item.body_line` for
    the absolute source line, the `inline_calc` pattern). Malformed
    markers -- empty text, a key-shaped head outside the key alphabet --
    and a marker that spans two lines are returned as (offset, message)
    and never become Navis; an unclosed `<!--navi:` is not a malformed
    marker (the existing unclosed-comment warning owns it, §4) and is
    silently inert here because it is already reported there.
    """
    navis: list[Navi] = []
    bad: list[tuple[int, str]] = []
    markers, warnings = _live_markers(body)
    for offset, _start, _end, inner in markers:
        key, text, error = parse_marker(inner)
        if error is not None:
            bad.append((offset, error))
            continue
        navis.append(Navi(key=key, text=text, line_offset=offset))
    bad.extend(warnings)
    bad.sort()
    return navis, bad


def _ws_chunks(text: str) -> list[tuple[str, str]]:
    """`text` split into maximal runs of (``ws``, spaces/tabs) and
    (``tx``, everything else), for `strip_markers`' run collapse."""
    chunks: list[tuple[str, str]] = []
    current = ""
    kind = ""
    for char in text:
        next_kind = "ws" if char in " \t" else "tx"
        if next_kind != kind:
            if current:
                chunks.append((kind, current))
            current, kind = char, next_kind
        else:
            current += char
    if current:
        chunks.append((kind, current))
    return chunks


def strip_markers(body: str) -> str:
    """`body` with every live marker's bytes removed, so the published
    HTML contains no marker bytes (design §4) *and* removing them never
    re-flows the text around them. A reviewed defect: removing only the
    marker bytes left a marker alone on its line as an EMPTY line, and a
    blank line is a paragraph break -- so a marker inside a paragraph
    split it. The removal works on the spans `_live_markers` recorded:
    the marker's EXACT bytes on the raw line are cut out, and a
    whitespace run is collapsed to one space only where the marker
    stood inside it (never before punctuation, never concatenating
    words that had no room between them). The rules, per line:

    * a line that consists only of whitespace, blockquote prefixes, list
      markers and markers is dropped whole, line terminator with it --
      the text around it stays one paragraph, in plain text and inside a
      quote (a leftover `>` is itself a blockquote paragraph break, a
      leftover bullet an empty item; CRLF bodies: a per-line `\r` rides
      along and disappears with the line);
    * occurrences the scan does not treat as markers -- inside fences,
      indented code, code spans, open comments, behind backslash escapes
      -- are left exactly as written, and every other byte is untouched.

    A body with no `navi:` prefix at all returns the *same* string
    object, so a project without Navis cannot render a byte differently
    because this function ran.
    """
    if MARKER_OPEN not in body:
        return body
    lines = body.split("\n")
    by_line: dict[int, list[tuple[int, int]]] = {}
    for offset, start, end, inner in _live_markers(body)[0]:
        marker = f"{MARKER_OPEN}{inner}{COMMENT_CLOSE}"
        if lines[offset][start:end] != marker:  # the scan guarantees this
            raise NavisMappingError(
                f"marker {marker!r} not at {offset}:{start}-{end} of {lines[offset]!r}"
            )
        by_line.setdefault(offset, []).append((start, end))
    if not by_line:
        return body
    kept: list[str] = []
    for offset, line in enumerate(lines):
        spans = by_line.get(offset)
        if not spans:
            kept.append(line)
            continue
        # Cut the validated spans out of the line, then collapse every
        # maximal run of whitespace+markers that carries a marker: to a
        # single space where it sits between whitespace on both sides,
        # to nothing where it touches text (a marker glued to
        # punctuation closes up; words with room between them keep it).
        tokens: list[tuple[str, str]] = []
        pos = 0
        for start, end in sorted(spans):
            tokens.extend(_ws_chunks(line[pos:start]))
            tokens.append(("mk", ""))
            pos = end
        tokens.extend(_ws_chunks(line[pos:]))
        pieces: list[str] = []
        i = 0
        while i < len(tokens):
            kind, text = tokens[i]
            if kind != "mk":
                pieces.append(text)
                i += 1
                continue
            k = 0
            while k < i and tokens[i - 1 - k][0] == "ws":
                k += 1
            hi = i
            while hi + 1 < len(tokens) and tokens[hi + 1][0] in ("ws", "mk"):
                hi += 1
            left_ws = k > 0
            right_ws = tokens[hi][0] == "ws"
            del pieces[len(pieces) - k:]  # the ws before the run rides back in
            pieces.append(" " if left_ws and right_ws else "")
            i = hi + 1
        joined = "".join(pieces)
        if not joined.strip() or _CONTAINER_ONLY_RE.fullmatch(joined.rstrip("\r")):
            continue  # markers (+whitespace/container prefixes) only: drop the line
        kept.append(joined)
    return "\n".join(kept)


def marker_line(item: Item, line_offset: int) -> int:
    """The absolute 1-indexed source line of the marker at `line_offset`
    in `item`'s body -- the `inline_calc`/calc-fence line rule (falls back
    to the item's own line when the body has no cheap per-line position,
    e.g. a list file's `body:` key).
    """
    if item.body_line is not None:
        return item.body_line + line_offset
    return item.source_line


def scan(project: Project) -> list[Diagnostic]:
    """Populate `item.navis` for every local item and return the
    malformed-marker warnings, which the build pass appends to
    `project.diagnostics` at the marker's line. Read-only: nothing here
    writes, mints, or touches `item.body` (§7.3's hard invariant starts
    here).
    """
    diagnostics: list[Diagnostic] = []
    for item in project.local_items:
        navis, bad = scan_body(item.body)
        item.navis = navis
        for offset, message in bad:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    message,
                    file=item.source_file,
                    line=marker_line(item, offset),
                    item_id=item.id,
                )
            )
    return diagnostics


def projection(project: Project) -> list[dict]:
    """Every Navi of the project, in (file, line) order, as plain JSON
    data: ``{key, text, source: {item, file, line}}`` (design §11: one
    projection, read by the `index` payload and the CLI alike -- no second
    implementation). `key` is None for a keyless marker (keys are minted
    by a later slice; the nullable always-present field is the item
    payload's convention, render.items_json).
    """
    rows = []
    for item in project.local_items:
        for navi in item.navis:
            rows.append(
                {
                    "key": navi.key or None,
                    "text": navi.text,
                    "source": {
                        "item": item.id,
                        # Design §10: identity resolves by key, never by
                        # display id (renames move display ids), so the
                        # row carries the key it should be resolved by.
                        "key": item.key or None,
                        "file": item.source_file,
                        "line": marker_line(item, navi.line_offset),
                    },
                }
            )
    # (file, line) only -- a stable sort keeps document order within a
    # line (two markers on one line are the page's order, not the
    # alphabet's), which is what `ls` numbers and `show <n>` addresses.
    rows.sort(key=lambda row: (row["source"]["file"], row["source"]["line"]))
    return rows
