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
indented code blocks, inline code spans and open HTML comments carry it
as literal text -- so the scan skips all four, the same regions
`inline_calc._scan_body` already skips. Consumption (stripping the marker
from the body copy handed to `md.render`, build.render_bodies) is what
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


def _scan_line(
    line: str, offset: int, in_comment: bool
) -> tuple[list[tuple[int, int, int, str]], bool]:
    """The `<!--navi:` markers of one line outside inline code spans and
    comments, as ``(line_offset, start, end, inner)`` (``inner`` is the text
    between ``<!--navi:`` and the first ``-->``), and the comment state at
    the line's end.

    Same character rules as `inline_calc._scan_comment_line`: comments do
    not nest and run to the first ``-->``; a code span is a backtick run
    closed by an equal run, its content inert; an unclosed run is literal
    text. A ``<!--navi:`` with no ``-->`` on its line is an opened comment
    (the grammar is one line, and the existing unclosed-comment warning --
    `build.py:1797-1803` -- owns that diagnostic; a marker must never be
    swallowed silently).
    """
    found: list[tuple[int, int, int, str]] = []
    n = len(line)
    i = 0
    while i < n:
        if in_comment:
            close = line.find(COMMENT_CLOSE, i)
            if close < 0:
                break  # the rest of the line is comment text
            in_comment = False
            i = close + len(COMMENT_CLOSE)
            continue
        if line.startswith(MARKER_OPEN, i):
            close = line.find(COMMENT_CLOSE, i + len(MARKER_OPEN))
            if close < 0:
                in_comment = True  # `<!--` opened; the line has no marker
                break
            found.append(
                (offset, i, close + len(COMMENT_CLOSE), line[i + len(MARKER_OPEN):close])
            )
            i = close + len(COMMENT_CLOSE)
            continue
        if line.startswith("<!--", i):
            in_comment = True
            i += 4
            continue
        if line[i] == "`":
            start = i
            while i < n and line[i] == "`":
                i += 1
            run = i - start
            close = i
            while close < n:
                if line[close] != "`":
                    close += 1
                    continue
                run_end = close
                while run_end < n and line[run_end] == "`":
                    run_end += 1
                if run_end - close == run:
                    i = run_end
                    break
                close = run_end
            else:
                # Unclosed run: literal text; scanning already sits past it.
                pass
            continue
        i += 1
    return found, in_comment


def _scan_body_lines(
    lines: list[str],
) -> list[tuple[int, int, int, str]]:
    """Every live marker occurrence of the given lines, in source order, as
    ``(line_offset, start, end, inner)``.

    Fenced code, indented code blocks and open comments are skipped across
    lines exactly like `inline_calc._scan_body` (a fence opened in ordinary
    text ignores comment markers; a comment opened in ordinary text ignores
    fence lines -- the two inert regions never open inside each other).
    """
    from . import inline_calc  # circular-import dance: inline_calc is import-light

    found: list[tuple[int, int, int, str]] = []
    fence: str | None = None
    in_comment = False
    for offset, line in enumerate(lines):
        if fence is not None:
            close = inline_calc.FENCE_CLOSE_RE.match(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                fence = None
            continue
        if not in_comment:
            open_match = inline_calc.FENCE_OPEN_RE.match(line)
            if open_match:
                fence = open_match.group(1)[0] * len(open_match.group(1))
                continue
            if line.startswith(("    ", "\t")):
                continue  # an indented code block carries no markers
        markers, in_comment = _scan_line(line, offset, in_comment)
        found.extend(markers)
    return found


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
    are returned as (offset, message) and never become Navis; an unclosed
    `<!--navi:` is not a malformed marker (the existing unclosed-comment
    warning owns it, §4) and is silently inert here because it is already
    reported there.
    """
    navis: list[Navi] = []
    bad: list[tuple[int, str]] = []
    for offset, _start, _end, inner in _scan_body_lines(body.split("\n")):
        key, text, error = parse_marker(inner)
        if error is not None:
            bad.append((offset, error))
            continue
        navis.append(Navi(key=key, text=text, line_offset=offset))
    return navis, bad


def strip_markers(body: str) -> str:
    """`body` with every live marker's bytes removed, so the published
    HTML contains no marker bytes (design §4) *and* removing them never
    re-flows the text around them. A reviewed defect: removing only the
    marker bytes left a marker alone on its line as an EMPTY line, and a
    blank line is a paragraph break -- so a marker inside a paragraph
    split it. The rules, in order of application per line:

    * a line that consists only of whitespace plus markers is dropped
      whole, line terminator with it, so the text around it stays one
      paragraph (dropping the line keeps CRLF endings intact -- a CRLF
      body's per-line `\r` rides along and disappears with the line);
    * a marker sharing a line with text is removed together with the
      whitespace runs on its sides, collapsed to a single space where
      text remains on both sides -- never a double space, never a
      leading-space line, never a line left with trailing whitespace
      (which markdown can read as a hard break);
    * occurrences the scan does not treat as markers -- inside fences,
      indented code, code spans, open comments -- are left exactly as
      written, and every other byte is untouched.

    A body with no `navi:` prefix at all returns the *same* string
    object, so a project without Navis cannot render a byte differently
    because this function ran.
    """
    if MARKER_OPEN not in body:
        return body
    lines = body.split("\n")
    spans_by_line: dict[int, list[tuple[int, int]]] = {}
    for offset, start, end, _inner in _scan_body_lines(lines):
        spans_by_line.setdefault(offset, []).append((start, end))
    if not spans_by_line:
        return body
    kept: list[str] = []
    for offset, line in enumerate(lines):
        spans = spans_by_line.get(offset)
        if not spans:
            kept.append(line)
            continue
        segments = []
        cursor = 0
        for start, end in sorted(spans):
            segments.append(line[cursor:start])
            cursor = end
        segments.append(line[cursor:])
        joined = segments[0]
        for segment in segments[1:]:
            joined = joined.rstrip(" \t")
            rest = segment.lstrip(" \t")
            joined += (" " if joined and rest else "") + rest
        if not joined.strip():
            continue  # whitespace + markers only: drop the whole line
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
                        "file": item.source_file,
                        "line": marker_line(item, navi.line_offset),
                    },
                }
            )
    rows.sort(key=lambda row: (row["source"]["file"], row["source"]["line"], row["text"]))
    return rows
