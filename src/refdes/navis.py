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
later line) and open HTML comments carry it as literal text.

The scan is driven by the renderer itself, in ONE analysis per body value
(`analyze_navis`, cached, consumed by the scan, the render-local strip and
the projection alike). A dedicated MarkdownIt instance -- the production
configuration, the production rules, with wrappers recording exactly what
each block rule consumed -- parses the normalized source; the wrappers
prove which bytes of the source each inline token's content lines came
from (paragraph/setext getLines math, ATX heading math, GFM table cell
math), and the token's children (text, escapes, entities, code spans,
links, images, emphasis, breaks) are then walked against the source
position by position, classifying every byte of a content line as live
text (a marker opener is visible there) or inert (code spans, link
destinations/titles/labels, emphasis markup, escapes, container
prefixes). The marker/comment state machine runs body-wide over those
ranges with the contract `inline_calc` enforces: an opener is visible
only in live text, a closer is visible in every raw byte (a code span
cannot hide a ``-->``). Marker spans are therefore exact raw ranges --
no token text is ever searched back into the source (the substring
search, the reviews showed, locates the WRONG occurrence: an inert twin
earlier on the line, and strips the page's real text); a body whose
provenance cannot be replayed exactly fails CLOSED: one diagnostic,
source byte-intact, never a guessed deletion.

Consumption (stripping the markers from the body copy handed to
`md.render`, build.render_bodies) edits only those exact raw ranges, in
the original string with its original line terminators (LF, CRLF, lone
CR all preserved); a marker-only line is dropped whole, terminator with
it, only when the provenance proves the line's remaining bytes are its
container prefixes; a hard-break sequence (two+ trailing spaces) adjacent
to a marker is preserved, never consumed by the removal. It happens on a
render-local string, never on `Item.body`, so no hash, seal or history
input ever sees a scan-side change (§7).
"""

from __future__ import annotations

import bisect
import os
import re
import sys
import threading
from functools import lru_cache
from html import unescape as _html_unescape
from typing import TYPE_CHECKING

from . import keys as keys_mod
from . import textio
from .model import Diagnostic, Item, Navi

if TYPE_CHECKING:
    from .model import Project

MARKER_OPEN = "<!--navi:"
COMMENT_CLOSE = "-->"

# Every diagnostic this module raises about a marker's own grammar; the
# CLI filters on the code, never on the message text.
NAVI_DIAGNOSTIC_CODE = "NAVI_MARKER"

#: The mint step's own refusals (slice 2, design §5): a keyless marker whose
#: bytes cannot be located losslessly in the item's own file is reported and
#: left exactly as written -- the fail-closed contract of `analyze_navis`,
#: carried to the write side.
NAVI_MINT_REFUSED_CODE = "NAVI_MINT_REFUSED"

MULTILINE_MESSAGE = (
    "navi marker spans lines; a marker is one line: `<!--navi: the reminder-->`"
)
MAPPING_MESSAGE = (
    "navi markers in this body could not be located exactly; nothing was "
    "removed and none are listed -- report this as a tool bug"
)

# A key-shaped head: the 11 characters right after `navi:`, delimited by
# whitespace (or the marker's end). Exactly 11 non-space characters is
# key-shaped; a key-shaped head outside the key alphabet is a typo to
# report, not text to absorb (the closed-family posture, build.py:66-68).
_KEY_SHAPED_RE = re.compile(r"^(\S{11})(?:[ \t]+(.*)|\Z)", re.DOTALL)
_ALPHABET = frozenset(keys_mod.ALPHABET)

# markdown_it's own normalization, mirrored exactly (rules_core/normalize.py).
_NEWLINES_RE = re.compile(r"\r\n?|\n")
_LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")
# markdown_it's isStrSpace, and CommonMark's escapable ASCII punctuation.
_SPACES = " \t\n\v\f\r"
_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_ESCAPED = {c: c for c in _PUNCT}
_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]{0,30});")


class NavisMappingError(RuntimeError):
    """Provenance that cannot be replayed exactly: the analysis refuses to
    name the marker's bytes. This is an internal limitation, not author
    input; `analyze_navis` turns it into a diagnostic (fail closed, body
    byte-intact) -- it must never escape a build."""


class _Occurrence:
    """One closed single-line marker at its EXACT raw span: ``line`` is the
    0-indexed body line (LF, CRLF and lone-CR terminators all count),
    ``start``/``end`` are columns into the raw line, ``inner`` is the raw
    text between ``<!--navi:`` and ``-->``, and ``key``/``text``/``error``
    are the parsed grammar (``error`` set = malformed marker: consumed
    from the page, never a Navi)."""

    __slots__ = ("end", "error", "inner", "key", "line", "start", "text")

    def __init__(self, line, start, end, inner, key, text, error):
        self.line = line
        self.start = start
        self.end = end
        self.inner = inner
        self.key = key
        self.text = text
        self.error = error

    def __repr__(self):
        return (f"_Occurrence(line={self.line}, start={self.start}, "
                f"end={self.end}, inner={self.inner!r}, key={self.key!r}, "
                f"text={self.text!r}, error={self.error!r})")


class Analysis:
    """The one analysis of one exact body value: what the scan sees
    (`navis`, `diagnostics`), what the render consumes (`stripped`), and
    the exact raw spans (`occurrences`) both are built from. `stripped`
    is the SAME string object as `body` whenever no marker is live, so a
    project without Navis cannot render a byte differently because the
    analysis ran."""

    __slots__ = (
        "body",
        "diagnostics",
        "has_navi_syntax",
        "navis",
        "occurrences",
        "stripped",
    )

    def __init__(self, body, has_navi_syntax, navis, diagnostics, stripped,
                 occurrences=()):
        self.body = body
        self.has_navi_syntax = has_navi_syntax
        self.navis = navis
        self.diagnostics = diagnostics
        self.stripped = stripped
        self.occurrences = occurrences


# ---------------------------------------------------------------------------
# the instrumented parser: one instance, the production configuration
# ---------------------------------------------------------------------------

_MD_LOCAL = threading.local()


def _marker_parser():
    """The dedicated MarkdownIt instance: the production parser's own
    configuration (`MarkdownIt("gfm-like", {"html": False, "linkify": False})`
    -- the same face `build._markdown_parser` renders with) plus the
    provenance wrappers. Kept SEPARATE from the production instance, so a
    body with no `navi:` prefix in it is never parsed at all and the
    renderer's own rules are never decorated. Thread-local like the
    production parser's (a build renders items on several threads)."""
    md = getattr(_MD_LOCAL, "md", None)
    if md is None:
        from markdown_it import MarkdownIt

        md = MarkdownIt("gfm-like", {"html": False, "linkify": False})
        _instrument(md)
        _MD_LOCAL.md = md
    return md


def _instrument(md) -> None:
    """Replace the four block rules that emit `inline` tokens with wrappers
    that record, for every inline token the rule pushes, exactly which
    normalized-source ranges its content lines came from. The wrappers
    call the ORIGINAL rule unchanged -- inertness and the token stream stay
    markdown-it's own; this layer only proves what was consumed."""
    for name in ("paragraph", "lheading", "heading", "table"):
        original = next(r.fn for r in md.block.ruler.__rules__ if r.name == name)
        md.block.ruler.at(name, _wrap_block(name, original))


def _snapshot(state):
    return (list(state.bMarks), list(state.tShift), list(state.eMarks),
            list(state.bsCount), state.blkIndent)


def _wrap_block(name, original):
    def rule(state, startLine, endLine, silent):
        snap = _snapshot(state)
        before = len(state.tokens)
        result = original(state, startLine, endLine, silent)
        if not result or silent:
            return result
        provenance = state.env.setdefault("_navis_prov", {})
        window = state.tokens[before:]
        rows: dict = {}
        for token in window:
            if token.type == "inline" and token.map is not None:
                # The index within the row's emitted tokens is the column
                # index: the table rule emits exactly `columnCount` cells
                # per row, in source order (short rows pad with empty
                # content, which has no source bytes and is skipped).
                rows.setdefault(token.map[0], []).append(token)
        for row_tokens in rows.values():
            for idx, token in enumerate(row_tokens):
                provenance[id(token)] = (name, token.map, snap, idx)
        return result

    return rule


# ---- provenance replays: mirror markdown_it's own line math ----


def _getlines_line(src, snap, line):
    """Replay the line-cut of `StateBlock.getLines` for one line: the slice
    is ``src[first:last]`` prefixed by `pad` synthesized spaces (the
    partially-expanded leading tab of a deeper container)."""
    bMarks, tShift, eMarks, bsCount, blkIndent = snap
    lineStart = first = bMarks[line]
    last = eMarks[line]
    lineIndent = 0
    while first < last and lineIndent < blkIndent:
        ch = src[first]
        if ch == " " or ch == "\t":
            lineIndent += 1 if ch == " " else 4 - (lineIndent + bsCount[line]) % 4
        elif first - lineStart < tShift[line]:
            lineIndent += 1
        else:
            break
        first += 1
    pad = lineIndent - blkIndent if lineIndent > blkIndent else 0
    return first, last, pad


def _heading_span(src, snap, line):
    """Replay the ATX heading rule's content range (hashes, spaces, the
    closing-sequence trim of `heading.py`)."""
    bMarks, tShift, eMarks, _bsCount, _blkIndent = snap
    pos = bMarks[line] + tShift[line]
    maximum = eMarks[line]
    level = 1
    pos += 1
    while pos < maximum and src[pos] == "#" and level <= 6:
        level += 1
        pos += 1
    while pos < maximum and src[pos] in _SPACES:
        pos += 1
    end = maximum
    while end > pos and src[end - 1] in _SPACES:
        end -= 1
    tmp = end
    while tmp > pos and src[tmp - 1] == "#":
        tmp -= 1
    if tmp > pos and src[tmp - 1] in _SPACES:
        end = tmp
    return pos, end


def _table_cells(src, snap, line):
    """Replay `getLine` + `escapedSplit` + the cell `.strip()`s of
    `table.py`: the raw range of each cell's content. A cell's content is
    NOT a contiguous slice of the source: `escapedSplit` drops the
    backslash of an escaped pipe, and the walk (which scans source bytes
    and verifies the decoded content character by character) is what
    proves the alignment -- a cell whose bytes cannot be replayed raises
    and the analysis fails closed."""
    bMarks, tShift, eMarks, _bsCount, _blkIndent = snap
    start = bMarks[line] + tShift[line]
    stripped = src[start:eMarks[line]]
    lead = len(stripped) - len(stripped.lstrip(_SPACES))
    text = stripped.strip(_SPACES)
    start += lead
    cells = []
    cur = 0
    isEscaped = False
    for idx, ch in enumerate(text):
        if ch == "|" and not isEscaped:
            cells.append((cur, idx))
            cur = idx + 1
        isEscaped = ch == "\\"
    cells.append((cur, len(text)))
    if cells and text[cells[0][0]:cells[0][1]] == "":
        cells.pop(0)
    if cells and text[cells[-1][0]:cells[-1][1]] == "":
        cells.pop()
    out = []
    for a, b in cells:
        cell = text[a:b]
        lead2 = len(cell) - len(cell.lstrip(_SPACES))
        trail2 = len(cell) - len(cell.rstrip(_SPACES))
        out.append((start + a + lead2, start + b - trail2))
    return out


# ---- the source cursor: the children walk scans source bytes, verifying
# each token's decoded content against them ----


class _Ctx:
    """The walk cursor for one inline token: `pos_n` indexes the normalized
    source; the block rule's snapshot (bMarks/tShift/eMarks/bsCount) says
    which virtual column each source line starts at (tab expansion), and
    `starts` maps source positions to line numbers. There is no content
    coordinate: every consumed byte is a source byte, and pad spaces the
    block rule synthesized for an expanded tab simply consume no source."""

    __slots__ = ("cstarts", "hi", "lo", "norm", "pos_n", "snap", "starts")

    def __init__(self, norm, pos_n, snap, lo, hi, starts, cstarts):
        self.norm = norm
        self.pos_n = pos_n
        self.snap = snap
        self.lo = lo
        self.hi = hi
        self.starts = starts
        self.cstarts = cstarts

    def take(self, c, n, ranges, live):
        """Consume `n` source bytes as one inert range (the content
        characters a token decodes them to are the walk's business, not
        the cursor's)."""
        ranges.append((self.pos_n, self.pos_n + n, live))
        self.pos_n += n

    def line_of(self, pos_n):
        # `starts` is ascending (starts[0] == 0, so the result is never
        # negative): the line is the last entry at or before `pos_n`.
        # 5,000-marker bodies made the old downward walk the hot loop --
        # quadratic in body length.
        return bisect.bisect_right(self.starts, pos_n) - 1

    def ws_expand(self, pos, length):
        """`length` source bytes of whitespace starting at `pos`: how many
        content characters they expand to (markdown-it expands tabs to
        column stops, and a hard break counts CONTENT spaces, not bytes)."""
        bsCount = self.snap[3]
        li = min(self.hi - 1, max(self.lo, self.line_of(pos)))
        col = bsCount[li]
        n = 0
        for p in range(pos, pos + length):
            if self.norm[p] == "\t":
                step = 4 - (col + bsCount[li]) % 4
                col += step
                n += step
            else:
                col += 1
                n += 1
        return n


def _ctx_for(token, prov, norm, starts):
    """Build the cursor for one inline token from its recorded provenance,
    asserting the replay reproduces the rule's own content string exactly
    (any drift raises, and the analysis fails closed). Returns the cursor
    plus, for every content line, the source offset where that line's
    content starts -- everything between the line's first byte and that
    offset is the container prefix (a `>`, a list marker, a heading hash,
    the line's own indentation) the block rule consumed."""
    name, span, snap, cell = prov
    lo, hi = span[0], span[1]
    if name in ("paragraph", "lheading"):
        infos = [_getlines_line(norm, snap, ln) for ln in range(lo, hi)]
        chars = []
        for first, last, pad in infos:
            chars.append(" " * pad + norm[first:last])
        joined = "\n".join(chars)
        content = joined.strip()
        if content != token.content:
            raise NavisMappingError(f"{name} content replay mismatch at line {lo}")
        lead = len(joined) - len(joined.lstrip())
        ci = 0
        starts_ = []
        for j, (first, last, pad) in enumerate(infos):
            line_len = pad + (last - first)
            if ci + line_len <= lead:
                ci += line_len + 1
                continue
            starts_.append((lo + j, first + max(0, lead - ci - pad)))
            ci += line_len + 1
        if not starts_:
            raise NavisMappingError("paragraph provenance has no content lines")
        pos = starts_[0][1]
        return _Ctx(norm, pos, snap, lo, hi, starts,
                    dict(starts_)), starts_
    if name == "heading":
        pos, maximum = _heading_span(norm, snap, lo)
        segment = norm[pos:maximum]
        content = segment.strip()
        if content != token.content:
            raise NavisMappingError(f"heading content replay mismatch at line {lo}")
        if "\n" in content:
            raise NavisMappingError("heading content spans lines")
        lead2 = len(segment) - len(segment.lstrip(_SPACES))
        start = pos + lead2
        return _Ctx(norm, start, snap, lo, hi, starts, {lo: start}), [(lo, start)]
    if name == "table":
        cells = _table_cells(norm, snap, lo)
        if cell >= len(cells):
            raise NavisMappingError("table cell index beyond the replayed cells")
        s, e = cells[cell]
        raw = norm[s:e]
        # `escapedSplit` drops the backslash of an escaped pipe; the cell's
        # content is that raw range with `\|` reduced to `|`, then stripped.
        content = raw.replace("\\|", "|").strip()
        if content != token.content:
            raise NavisMappingError(f"table cell replay mismatch at line {lo}")
        s = s + len(raw) - len(raw.lstrip(_SPACES))
        return _Ctx(norm, s, snap, lo, hi, starts, {lo: s}), [(lo, s)]
    raise NavisMappingError(f"no provenance replay for rule {name!r}")


# ---- the children walk: classify every source byte of live text ----


def _literal(s, ctx, ranges, c):
    """Consume the exact source bytes `s` (inert). `c` (unused) documents
    how many content characters those bytes decode to: an escape pair and
    an entity reference produce content characters from source bytes the
    renderer does not show, and an opener needs every one of its bytes as
    live text, so the pair is inert as a whole."""
    if ctx.norm[ctx.pos_n:ctx.pos_n + len(s)] != s:
        raise NavisMappingError(
            f"expected {s!r} at source position {ctx.pos_n} "
            f"found {ctx.norm[ctx.pos_n:ctx.pos_n + len(s)]!r}"
        )
    ctx.take(0, len(s), ranges, False)


def _text_scan(ctx, content, ranges, inert, entity):
    """The raw run of a merged text token against the source, one content
    character at a time: a plain character consumes one source byte (a
    space in the content may be written as a tab in the source); an
    escape pair and an entity reference produce one content character
    from source bytes the renderer does not show, and an opener needs
    every one of its bytes as live text, so each pair is inert as a
    whole; the only content characters with no source byte are the pad
    spaces a block rule synthesized for an expanded leading tab, and
    they consume none. A character that does not match raises: the
    analysis fails closed. (The inline core rule `fragments_join` merges
    escape/entity tokens into the adjacent text token, carrying a
    merged escape's `\\x` markup on the text token -- the marker's own
    grammar, `<!--navi:` with no escapable character in it, means a
    token's `\\` markup is always the run's first escape, so the run
    re-derives every pair from the source bytes.)"""
    norm = ctx.norm
    live = not inert
    run = ctx.pos_n
    pos = ctx.pos_n
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if pos >= len(norm):
            ranges.append((run, pos, live))
            raise NavisMappingError("text run runs past the source")
        c = norm[pos]
        if c == ch or ch == " " and c in " \t":
            pos += 1
        elif ch == " " and i > 0:
            pass  # a synthesized pad space: no source byte at all
        elif (c == "\\" and pos + 1 < len(norm) and norm[pos + 1] in _PUNCT
                and norm[pos + 1] == ch):
            ranges.append((run, pos, live))
            ranges.append((pos, pos + 2, False))
            pos += 2
            run = pos
        elif entity and c == "&":
            match = _ENTITY_RE.match(norm, pos)
            if match is None or _html_unescape(match.group(0)) != ch:
                ranges.append((run, pos, live))
                raise NavisMappingError(
                    f"content char {ch!r} not an entity at source position {pos}"
                )
            ranges.append((run, pos, live))
            ranges.append((pos, match.end(), False))
            pos = match.end()
            run = pos
        else:
            ranges.append((run, pos, live))
            raise NavisMappingError(
                f"content char {ch!r} not at source position {pos} "
                f"({norm[pos:pos + 16]!r})"
            )
        i += 1
    ranges.append((run, pos, live))
    ctx.pos_n = pos


def _code_span(child, ctx, ranges):
    """Replay `backticks.py` + `code_inline.py`: the span's exact source
    range, inert (a marker inside a code span is literal text)."""
    norm = ctx.norm
    pos = ctx.pos_n
    if pos >= len(norm) or norm[pos] != "`":
        raise NavisMappingError("code span does not start at the walk position")
    start = pos
    while pos < len(norm) and norm[pos] == "`":
        pos += 1
    run = pos - start
    if len(child.markup) != run:
        raise NavisMappingError("code span delimiter length mismatch")
    match = -1
    scan = pos
    while True:
        find = norm.find("`", scan)
        if find < 0:
            raise NavisMappingError("code span has no closer")
        end = find
        while end < len(norm) and norm[end] == "`":
            end += 1
        if end - find == run:
            match = end
            break
        scan = end
    text = norm[pos:find].replace("\n", " ")
    if len(text) > 2 and text[0] == " " and text[-1] == " ":
        text = text[1:-1]
    if text != child.content:
        raise NavisMappingError("code span content mismatch")
    ctx.take(0, match - start, ranges, False)


def _label_end(norm, pos):
    """The offset of the `]` closing a link/image label, replaying
    `parseLinkLabel`'s nesting scan."""
    depth = 1
    while pos < len(norm):
        ch = norm[pos]
        if ch == "]":
            depth -= 1
            if depth == 0:
                return pos
        elif ch == "[":
            depth += 1
        elif ch == "\\":
            pos += 1
        pos += 1
    raise NavisMappingError("link label has no closer")


def _link_tail(ctx, ranges):
    """Consume what a `link`/`image` rule swallows after the closing `]`
    of the label: an inline destination ``(dest "title")`` or a reference
    label ``[label]``. Both are inert ranges (a marker written inside a
    destination, title or label is never a comment to the renderer)."""
    norm = ctx.norm
    n = len(norm)
    pos = ctx.pos_n
    ws = pos
    while ws < n and norm[ws] in " \t\n\v\f":
        ws += 1
    if ws < n and norm[ws] == "(":
        i = ws + 1
        while i < n and norm[i] in " \t\n\v\f":
            i += 1
        if i < n and norm[i] == "<":
            i += 1
            while i < n and norm[i] != ">":
                if norm[i] == "\\" and i + 1 < n:
                    i += 1
                i += 1
            i += 1
        else:
            level = 0
            while i < n:
                ch = norm[i]
                if ch in " \t\n\v\f" or ord(ch) < 32:
                    break
                if ch == "(":
                    level += 1
                elif ch == ")":
                    if level == 0:
                        break
                    level -= 1
                elif ch == "\\" and i + 1 < n:
                    i += 1
                i += 1
        while i < n and norm[i] in " \t\n\v\f":
            i += 1
        if i < n and norm[i] in "\"'(":
            quote = norm[i]
            closing = ")" if quote == "(" else quote
            i += 1
            while i < n and norm[i] != closing:
                if norm[i] == "\\" and i + 1 < n:
                    i += 1
                i += 1
            i += 1
            while i < n and norm[i] in " \t\n\v\f":
                i += 1
        if i < n and norm[i] == ")":
            i += 1
        ranges.append((pos, i, False))
        ctx.pos_n = i
        return
    if ws < n and norm[ws] == "[":
        i = ws + 1
        depth = 1
        while i < n and depth:
            if norm[i] == "[":
                depth += 1
            elif norm[i] == "]":
                depth -= 1
            elif norm[i] == "\\" and i + 1 < n:
                i += 1
            i += 1
        ranges.append((pos, i, False))
        ctx.pos_n = i


def _break(ctx, ranges, min_ws):
    """Consume a softbreak/hardbreak: the trailing whitespace before the
    newline (the newline rule strips it from the pending text), the
    newline, and the next line's leading whitespace. The break token
    itself has no content characters; a hard break is a trailing run of
    TWO OR MORE CONTENT spaces (tabs expand first) -- the C1 rule of the
    strip preserves exactly that sequence, so its length is checked
    against the token type here, and a mismatch fails closed. A backslash
    hard break consumes the two bytes of the backslash-newline pair."""
    norm = ctx.norm
    pos = ctx.pos_n
    k = 0
    if pos < len(norm) and norm[pos] == "\\" and pos + 1 < len(norm) \
            and norm[pos + 1] == "\n":
        ctx.take(0, 2, ranges, False)
        pos += 2
        ws = 0
        while pos + ws < len(norm) and norm[pos + ws] in " \t\v\f":
            ws += 1
        ranges.append((pos, pos + ws, False))
        ctx.pos_n = pos + ws
        if min_ws > 0:
            return
        raise NavisMappingError("backslash hard break is a hard break")
    while pos + k < len(norm) and norm[pos + k] in " \t":
        k += 1
    if pos + k >= len(norm) or norm[pos + k] != "\n":
        raise NavisMappingError("break sequence does not match the walk position")
    if (ctx.ws_expand(pos, k) >= 2) != (min_ws >= 2):
        raise NavisMappingError("break sequence does not match the token type")
    ctx.take(0, k + 1, ranges, False)
    ws = 0
    while ctx.pos_n < len(norm) and norm[ctx.pos_n] in " \t\v\f":
        ws += 1
        ctx.pos_n += 1
    ranges.append((ctx.pos_n - ws, ctx.pos_n, False))
    cs = ctx.cstarts.get(ctx.line_of(pos) + 1)
    if cs is not None and ctx.pos_n < cs:
        # the next content line's consumed container prefix (`> `, a list
        # marker): the block rule's getLines never puts it in the content
        ranges.append((ctx.pos_n, cs, False))
        ctx.pos_n = cs


def _walk(children, ctx, ranges):
    """Consume every token's source bytes through its children, appending
    the (start, end, live) source ranges they account for: a text run is
    live (an opener written there is a marker), escapes, entities, code
    spans, link destinations/titles/labels, autolink URLs, emphasis
    markup and breaks are inert. Anything the walk cannot match raises:
    the analysis fails closed."""
    pending_inert = False
    autolink = False
    for child in children:
        t = child.type
        if t == "text":
            _text_scan(ctx, child.content, ranges, pending_inert,
                       child.info == "entity")
            pending_inert = False
        elif t == "text_special":
            _literal(child.markup, ctx, ranges, 0)
        elif t == "code_inline":
            _code_span(child, ctx, ranges)
        elif t == "image":
            _literal("!", ctx, ranges, 0)
            _literal("[", ctx, ranges, 0)
            ls = ctx.pos_n
            le = _label_end(ctx.norm, ls)
            _walk(child.children,
                  _Ctx(ctx.norm, ls, ctx.snap, ctx.lo, ctx.hi, ctx.starts,
                       ctx.cstarts),
                  ranges)
            ctx.pos_n = le
            _literal("]", ctx, ranges, 0)
            _link_tail(ctx, ranges)
        elif t == "link_open":
            autolink = child.markup == "autolink"
            _literal("<" if autolink else "[", ctx, ranges, 0)
            pending_inert = autolink
        elif t == "link_close":
            _literal(">" if autolink else "]", ctx, ranges, 0)
            _link_tail(ctx, ranges)
            pending_inert = False
        elif t in ("em_open", "strong_open", "s_open",
                   "em_close", "strong_close", "s_close"):
            _literal(child.markup, ctx, ranges, 0)
        elif t == "softbreak":
            _break(ctx, ranges, 0)
        elif t == "hardbreak":
            _break(ctx, ranges, 2)
        elif t == "html_inline":
            _literal(child.content, ctx, ranges, 0)
        else:
            raise NavisMappingError(f"inline token {t!r} cannot be walked")


# ---- the marker/comment state machine (per inline token, inline_calc contract) ----


def _machine(norm_lines, token_ranges):
    """Every closed single-line marker of the normalized body, in document
    order, plus the two-line-marker warnings: ``((line, start, end, inner),
    ...)`` / ``((line, message), ...)``.

    Openers (``<!--navi:`` and ``<!--``) and closers (``-->``) are visible
    only in live text ranges: a closer consumed by a construct -- inside a
    code span, a fence, an open comment, behind a backslash escape -- is
    inert bytes, exactly the contract `inline_calc._scan_body` enforces for
    inline calc spans, so the two lexical layers agree about who owns a
    ``-->``. A ``<!--navi:`` that closes on a LATER line OF ITS OWN TOKEN
    is a warning naming the opening line (its bytes stay on the page as
    the escaped comment the renderer shows).

    Two comment scopes, from the body-wide contract the scan implements
    (§S4, the V4 probes): a plain ``<!--`` unclosed at a token's last line
    KEEPS its ownership into the following tokens -- across a blank line
    (``comment_blank``), into a heading (``comment_heading``), across a
    fence (``comment_fence``) -- swallowing every opener until the first
    closer; the renderer's ``html: False`` escaped-comment tokens alone
    cannot encode that. A ``<!--navi:`` unclosed at a token's last line
    (an ATX heading, a table cell, a list item that ends at the line --
    the matrix's ``span`` placements) is an unclosed marker, owned by the
    existing unclosed-comment warning (`build.py:1797-1803`), and is
    silent and inert here: it does not open the body-wide state."""
    occurrences = []
    warnings = []
    in_comment = False
    carry = False
    for ranges_by_line in token_ranges:
        pending = -1
        for li in sorted(ranges_by_line):
            line = norm_lines[li]
            ranges = sorted(ranges_by_line[li])

            def _closer(text, pos, ranges):
                """The first `-->` whose bytes are all live text (an opener's
                6 bytes must all be visible for the opener to open)."""
                while True:
                    p = text.find(COMMENT_CLOSE, pos)
                    if p < 0:
                        return -1
                    if any(rs <= p and p + len(COMMENT_CLOSE) <= re_
                           for rs, re_ in ranges):
                        return p
                    pos = p + 1

            pos = 0
            while True:
                if in_comment:
                    close = _closer(line, pos, ranges)
                    if close < 0:
                        break
                    pos = close + len(COMMENT_CLOSE)
                    in_comment = False
                    carry = False
                    if pending >= 0:
                        # the marker opened on `pending` closed on THIS line:
                        # it spans lines, which is the one authoring warning
                        # the scan owns (an opener that never closes at all
                        # belongs to the unclosed-comment warning in build.py
                        # and stays silent here).
                        warnings.append((pending, MULTILINE_MESSAGE))
                        pending = -1
                opener = -1
                for (rs, re_) in ranges:
                    p = line.find("<!--", max(rs, pos), re_)
                    if p >= 0 and (opener < 0 or p < opener):
                        opener = p
                if opener < 0:
                    break
                navi = line.startswith(MARKER_OPEN, opener)
                close = _closer(line, opener + (len(MARKER_OPEN) if navi
                                                 else len("<!--")), ranges)
                if close < 0:
                    if navi:
                        if pending < 0:
                            pending = li
                    else:
                        carry = True
                    in_comment = True
                    break
                if navi:
                    occurrences.append((li, opener, close + len(COMMENT_CLOSE),
                                        line[opener + len(MARKER_OPEN):close]))
                pos = close + len(COMMENT_CLOSE)
        if in_comment and not carry:
            in_comment = False
    occurrences.sort(key=lambda o: (o[0], o[1]))
    return occurrences, warnings


# ---- the raw edits ----


def _split_raw(body):
    """`body` as ``[(content, start_offset, terminator), ...]`` splitting on
    LF, CRLF and lone CR (lone CR is a line break, matching markdown_it)."""
    lines = []
    pos = 0
    for m in _LINE_SPLIT_RE.finditer(body):
        lines.append((body[pos:m.start()], pos, m.group(0)))
        pos = m.end()
    lines.append((body[pos:], pos, ""))
    return lines


def _normalize(body):
    """markdown_it's normalization of `body` (CRLF/CR to LF, NUL to
    U+FFFD) plus the normalized->raw index map (one entry per normalized
    character; a newline maps to where its terminator starts)."""
    chars = []
    n2r = []
    pos = 0
    for m in _NEWLINES_RE.finditer(body):
        s, e = m.span()
        for j in range(pos, s):
            c = body[j]
            chars.append("\ufffd" if c == "\x00" else c)
            n2r.append(j)
        chars.append("\n")
        n2r.append(s)
        pos = e
    for j in range(pos, len(body)):
        c = body[j]
        chars.append("\ufffd" if c == "\x00" else c)
        n2r.append(j)
    return "".join(chars), n2r


def _norm_line_starts(norm):
    starts = [0]
    start = 0
    while True:
        nl = norm.find("\n", start)
        if nl < 0:
            return starts
        starts.append(nl + 1)
        start = nl + 1


def _ws_chunks(text):
    """`text` split into maximal runs of (``ws``, spaces/tabs) and
    (``tx``, everything else), for the strip's run collapse."""
    chunks = []
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


def _strip_line(content, spans, prefixes, prose, fill):
    """One raw line containing markers: the marker runs collapsed with the
    whitespace around them on a prose line (a paragraph, a heading's text
    line), and removed byte-exactly on a structural line (a table cell,
    where a consumed cell's span covers its whitespace, and an ATX heading,
    whose closing hashes ride the same whitespace as the marker); a table
    row with every cell consumed is rebuilt as an all-blank row. The whole
    line is dropped when the provenance proves every byte of it is marker,
    whitespace, or a container prefix the block rule consumed (a `>`, a
    list marker, a heading hash, the line's own indentation). A line whose
    residue is real content -- a thematic break's `---`, an escaped pipe's
    `|`, prose -- is never dropped: only what the parser proved to be an
    empty container is.

    C1 (design review): a whitespace run of two or more characters that
    ends the line AFTER a marker is a hard-break sequence of the rendered
    page; the removal preserves it verbatim and never creates one from a
    single space, so deleting a marker can neither add nor destroy a
    forced line break."""
    if fill:
        # Cell count as `table.py`'s escapedSplit sees it: a `|` preceded
        # by an unescaped backslash is content, not a delimiter -- the
        # same walk `_table_cells` uses above.
        cells = 0
        isEscaped = False
        for ch in content:
            if ch == "|" and not isEscaped:
                cells += 1
            isEscaped = ch == "\\"
        return "|".join([""] + [" "] * cells).rstrip(), False
    tokens = []
    pos = 0
    for start, end in spans:
        tokens.extend(_ws_chunks(content[pos:start]))
        tokens.append(("mk", "", start, end))
        pos = end
    tokens.extend(_ws_chunks(content[pos:]))
    pieces = []
    i = 0
    while i < len(tokens):
        kind, text = tokens[i][0], tokens[i][1]
        if kind != "mk":
            pieces.append(text)
            i += 1
            continue
        if not prose:
            i += 1  # structural line: byte-exact removal, whitespace stays
            continue
        k = 0
        while k < i and tokens[i - 1 - k][0] == "ws":
            k += 1
        hi = i
        while hi + 1 < len(tokens) and tokens[hi + 1][0] in ("ws", "mk"):
            hi += 1
        left_ws = k > 0
        right_ws = tokens[hi][0] == "ws"
        c1 = right_ws and hi == len(tokens) - 1 and len(tokens[hi][1]) >= 2
        del pieces[len(pieces) - k:]  # the ws before the run rides back in
        if c1:
            # the hard-break sequence stays verbatim; the run on the
            # marker's left collapses to a single space exactly as it
            # would with text on both sides (the preserved sequence is
            # the "text" on the right).
            if left_ws:
                pieces.append(" ")
            pieces.append(tokens[hi][1])
        elif right_ws and hi == len(tokens) - 1:
            pieces.append("")  # trailing whitespace after the marker is gone
        else:
            pieces.append(" " if left_ws and right_ws else "")
        i = hi + 1
    joined = "".join(pieces)
    covered = list(spans) + list(prefixes)
    for idx, char in enumerate(content):
        if char in " \t":
            continue
        if any(s <= idx < e for s, e in covered):
            continue
        return joined, False
    chars = [c for c in joined if c not in " \t"]
    if len(chars) >= 3 and len(set(chars)) == 1 and chars[0] in "-*_":
        return joined, False  # a thematic break is real content, not residue
    return joined, True


def _strip(body, raw_lines, prefixes, policy):
    """`body` with every occurrence's exact raw range edited out, in one
    right-to-left pass; line terminators are never touched except that a
    dropped line's terminator rides along with it (the LF/CRLF/CR bytes of
    every kept line are the original bytes)."""
    edits = []
    for li, (content, start, term) in enumerate(raw_lines):
        entry = policy.get(li)
        if entry is None:
            continue
        spans, prose, fill = entry
        joined, drop = _strip_line(
            content, spans, prefixes.get(li, ()), prose, fill
        )
        if drop:
            edits.append((start, start + len(content) + len(term), ""))
        else:
            edits.append((start, start + len(content), joined))
    # Edits are ascending (one per line, in line order): one forward join
    # -- rebuilding `body` per edit is quadratic on a many-marker body.
    parts = []
    prev = 0
    for s, e, text in edits:
        parts.append(body[prev:s])
        parts.append(text)
        prev = e
    parts.append(body[prev:])
    return "".join(parts)


# ---- the one analysis ----


def _analyze(body):
    if MARKER_OPEN not in body:
        # The sentinel fast path: a body without the prefix is never
        # parsed at all (a project without Navis pays nothing, and the
        # renderer's own parse of the body is untouched).
        return Analysis(body, False, (), (), body)
    raw_lines = _split_raw(body)
    norm, n2r = _normalize(body)
    env = {}
    tokens = _marker_parser().parse(norm, env)
    prov = env.get("_navis_prov", {})
    norm_line_starts = _norm_line_starts(norm)
    norm_lines = norm.split("\n")
    norm_line_ends = [
        s + len(line) for s, line in zip(norm_line_starts, norm_lines)
    ]  # index just past the line's last char (the newline, or len(norm))
    token_ranges = []
    prefixes = {}
    prose_lines = set()
    table_cells = {}
    for token in tokens:
        if token.type != "inline" or token.map is None:
            continue
        if not token.content:
            continue  # an empty cell's token: no source bytes, nothing live
        record = prov.get(id(token))
        if record is None:
            if token.map[0] == 0 and token.map[1] > 1:
                # A label's inline tokens are children of a link/image
                # token, not a block rule's inline token: they carry the
                # link rule's synthetic map and are walked as part of
                # their parent, never as a content line of their own.
                continue
            raise NavisMappingError(
                f"inline token at {token.map!r} has no recorded provenance"
            )
        name, span, snap, cell = record
        if name in ("paragraph", "lheading", "heading"):
            prose_lines.update(range(span[0], span[1]))
        elif name == "table":
            cells = _table_cells(norm, snap, span[0])
            s, e = cells[cell]
            line_start = raw_lines[span[0]][1]
            table_cells.setdefault(span[0], []).append(
                (n2r[s] - line_start, n2r[e - 1] + 1 - line_start, s, e)
            )
        ctx, line_starts = _ctx_for(token, record, norm, norm_line_starts)
        ranges = []
        _walk(token.children, ctx, ranges)
        tok_lines = {}
        for s, e, live in ranges:
            if not live:
                continue
            li = 0
            while li + 1 < len(norm_line_starts) and norm_line_starts[li + 1] <= s:
                li += 1
            while li < len(norm_lines) and s < e:
                a = max(s, norm_line_starts[li])
                b = min(e, norm_line_ends[li])
                if a < b:
                    tok_lines.setdefault(li, []).append(
                        (a - norm_line_starts[li], b - norm_line_starts[li]))
                s = b
                li += 1
        token_ranges.append(tok_lines)
        for li, content_start in line_starts:
            nls = norm_line_starts[li]
            if content_start > nls:
                line_start = raw_lines[li][1]
                prefixes.setdefault(li, []).append(
                    (n2r[nls] - line_start, n2r[content_start - 1] + 1 - line_start)
                )
    occurrences, warnings = _machine(norm_lines, token_ranges)
    occ = []
    for li, s, e, inner in occurrences:
        ns = norm_line_starts[li]
        line_start = raw_lines[li][1]
        start = n2r[ns + s] - line_start
        end = n2r[ns + e - 1] + 1 - line_start
        raw_line = raw_lines[li][0]
        raw_inner = raw_line[start + len(MARKER_OPEN):end - len(COMMENT_CLOSE)]
        if raw_line[start:end] != MARKER_OPEN + raw_inner + COMMENT_CLOSE:
            raise NavisMappingError("marker bytes do not match the raw line at the span")
        key, text, error = parse_marker(raw_inner)
        occ.append(_Occurrence(li, start, end, raw_inner, key, text, error))
    policy = {}
    by_line = {}
    for o in occ:
        by_line.setdefault(o.line, []).append(o)
    for li, olist in by_line.items():
        cells = table_cells.get(li)
        if cells is None:
            spans = [(o.start, o.end) for o in olist]
            fill = False
        else:
            spans = []
            consumed = 0
            for o in olist:
                hit = next((c for c in cells if c[0] <= o.start < c[1]), None)
                marker = MARKER_OPEN + o.inner + COMMENT_CLOSE
                if hit is not None and norm[hit[2]:hit[3]].strip() == marker:
                    spans.append((hit[0], hit[1]))  # the cell's own whitespace too
                    consumed += 1
                else:
                    spans.append((o.start, o.end))
            fill = consumed == len(olist) == len(cells)
        policy[li] = (sorted(spans), li in prose_lines, fill)
    navis = tuple(Navi(key=o.key, text=o.text, line_offset=o.line)
                  for o in occ if not o.error)
    diagnostics = tuple(sorted(
        [(o.line, o.error) for o in occ if o.error] + list(warnings)
    ))
    stripped = _strip(body, raw_lines, prefixes, policy) if occ else body
    return Analysis(body, True, navis, diagnostics, stripped, tuple(occ))


@lru_cache(maxsize=256)
def analyze_navis(body: str) -> Analysis:
    """The single entry point -- scan data, render data, exact raw spans,
    cached for this exact body value (the scan, the render-local strip and
    the projection all consume this one analysis). It NEVER raises: a body
    the provenance layer cannot replay fails closed as a diagnostic with
    the source byte-intact, so no input can traceback a build. Cached by
    value, immutable, with the body identity kept on the result."""
    try:
        return _analyze(body)
    except Exception as exc:  # noqa: BLE001 -- the fail-closed promise:
        # ANY provenance failure degrades to a diagnostic with the source
        # byte-intact; nothing a body can contain may traceback a build.
        # The exception names itself in the warning so a bug report is
        # actionable without a reproduction.
        return Analysis(
            body, MARKER_OPEN in body, (),
            ((0, f"{MAPPING_MESSAGE} [{type(exc).__name__}]: {exc}"),),
            body)


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
    analysis = analyze_navis(body)
    return list(analysis.navis), list(analysis.diagnostics)


def strip_markers(body: str) -> str:
    """`body` with every live marker's bytes removed, at their exact raw
    spans, so the published HTML contains no marker bytes (design §4)
    *and* removing them never re-flows the text around them:

    * a line that is marker, whitespace and consumed container prefixes
      only is dropped whole, line terminator with it -- the text around
      it stays one paragraph, in plain text, in a list item and inside a
      quote (a leftover `>` is itself a blockquote paragraph break, a
      leftover bullet an empty item, and a leftover `---` a thematic
      break -- which is why the drop is proven by parser provenance,
      never by a character class);
    * a marker sharing a line with text is removed together with the
      whitespace runs on its sides, collapsed to a single space where
      text remains on both sides, and a two-space hard-break sequence
      next to a marker is preserved;
    * occurrences the scan does not treat as markers -- inside fences,
      indented code, code spans, link destinations/titles/labels, open
      comments, behind backslash escapes -- are left exactly as written,
      and every other byte is untouched.

    A body with no `navi:` prefix at all returns the *same* string
    object (as does one whose markers are all inert), so a project
    without Navis cannot render a byte differently because this function
    ran."""
    return analyze_navis(body).stripped


def marker_line(item: Item, line_offset: int) -> int:
    """The absolute 1-indexed source line of the marker at `line_offset`
    in `item`'s body -- the `inline_calc`/calc-fence line rule (falls back
    to the item's own line when the body has no cheap per-line position,
    e.g. a list file's `body:` key)."""
    if item.body_line is not None:
        return item.body_line + line_offset
    return item.source_line


def mint_keys(project: Project, write: bool = True) -> list[tuple[Item, str]]:
    """Slice 2 (design §5, §7.2): mint a key into every keyless live marker,
    written into the marker in the item's own source file -- the same
    posture as `keys.mint_missing()` (writable load, announced through
    `Project.load_writes`, never on `--no-write`).

    The write is exact-provenance or nothing: the target line is located by
    `Item.body_line + occurrence.line`, and the file's line must match the
    body's raw line byte for byte -- a body that is not the markdown file's
    own text (a list file's `body:` scalar has no `body_line`), a file that
    changed under the parse, or a line break `textio` splits at (e.g.
    U+2028) all REFUSE the mint with a `NAVI_MINT_REFUSED` warning and leave
    the marker keyless and the bytes untouched. The splice (``key + " "``
    after ``<!--navi:``) never changes line counts, so every parsed position
    stays valid; occurrences on one line are spliced right-to-left.

    Keys are a fresh namespace (§5): minted with `keys.mint()`, unique
    against every key currently declared in the project. A declared key is
    never rewritten (idempotence, and §5's corruption posture: minting
    mints, it does not repair)."""
    from .revise import FileRewrite, write_rewrites_verified

    unkeyed: list[tuple[Item, _Occurrence]] = []
    used: set[str] = set()
    for item in project.local_items:
        analysis = analyze_navis(item.body)
        for occ in analysis.occurrences:
            if occ.error:
                continue
            if occ.key:
                used.add(occ.key)
            else:
                unkeyed.append((item, occ))
    if not unkeyed:
        return []
    if not write:
        noun = "marker has" if len(unkeyed) == 1 else "markers have"
        project.info(
            f"{len(unkeyed)} navi {noun} no key yet; the next writable "
            "command will mint them."
        )
        return []

    by_file: dict[str, list[tuple[Item, _Occurrence, str]]] = {}
    for item, occ in unkeyed:
        key = keys_mod.mint()
        while key in used:
            key = keys_mod.mint()
        used.add(key)
        by_file.setdefault(item.source_file, []).append((item, occ, key))

    rewrites: list[FileRewrite] = []
    assignments: list[tuple[Item, str]] = []
    for rel, entries in by_file.items():
        path = os.path.join(project.root, rel)
        source = textio.SourceText.of(path)
        text = source.text
        lines = source.lines
        by_line: dict[int, list[tuple[_Occurrence, str]]] = {}
        for item, occ, key in entries:
            if item.body_line is None:
                project.warn(
                    "navi marker has no key, and its body is a `body:` scalar "
                    "in a YAML list file -- refdes mints keys only into "
                    "markdown item bodies, where the marker's bytes can be "
                    "located exactly; the marker stays keyless",
                    file=rel, line=item.source_line, item_id=item.id,
                    code=NAVI_MINT_REFUSED_CODE,
                )
                continue
            li = item.body_line - 1 + occ.line
            raw_line = _split_raw(item.body)[occ.line][0]
            if li >= len(lines) or lines[li] != raw_line:
                project.warn(
                    "navi marker has no key, and the source line at its "
                    f"position does not match the parsed body (line {li + 1} "
                    "of this file) -- the mint is refused so the bytes stay "
                    "byte-intact; the marker stays keyless",
                    file=rel, line=item.source_line, item_id=item.id,
                    code=NAVI_MINT_REFUSED_CODE,
                )
                continue
            by_line.setdefault(li, []).append((occ, key))
        for li, splices in by_line.items():
            line = lines[li]
            for occ, key in sorted(splices, key=lambda e: e[0].start, reverse=True):
                open_end = occ.start + len(MARKER_OPEN)
                # The key sits colon-adjacent (`<!--navi:KEY text-->`), so a
                # space the author left after `<!--navi:` is consumed by the
                # splice, not left in front of the key.
                ws = open_end
                while ws < len(line) and line[ws] in " \t":
                    ws += 1
                line = line[:open_end] + key + " " + line[ws:]
            lines[li] = line
        minted_ids = {id(occ) for splices in by_line.values() for occ, _ in splices}
        for _item, occ, key in entries:
            if id(occ) in minted_ids:
                assignments.append((_item, key))
        after = source.render(lines)
        if after != text:
            rewrites.append(FileRewrite(path=path, rel=rel, before=text, after=after))

    refused = write_rewrites_verified(project, rewrites)
    landed = [(item, key) for item, key in assignments if item.source_file not in refused]
    if landed:
        _announce_navi_mints(landed)
    return landed


def _announce_navi_mints(landed: list[tuple[Item, str]]) -> None:
    """Announced, never silent -- the `anchor_follows` precedent (design
    §13 slice 2): one line per minted marker on stderr, naming the key and
    where it landed. The machine-output commands keep their stdout pure;
    this line is a side-effect announcement, not an answer."""
    for item, key in landed:
        print(
            f"navis: minted key {key[:6]} ({key}) into {item.id} "
            f"({item.source_file})",
            file=sys.stderr,
        )


def scan(project: Project) -> list[Diagnostic]:
    """Populate `item.navis` for every local item and return the
    malformed-marker warnings, which the build pass appends to
    `project.diagnostics` at the marker's line. Read-only: nothing here
    writes, mints, or touches `item.body` (§7.3's hard invariant starts
    here).

    A declared key is validated the way an item key is (§5,
    `keys.malformed_key_message`): the corruption lint reports it at the
    marker's line and changes nothing -- a key is written by refdes, so a
    marker whose key fails validation is corrupt input to report, never a
    marker to repair.
    """
    diagnostics: list[Diagnostic] = []
    for item in project.local_items:
        analysis = analyze_navis(item.body)
        item.navis = list(analysis.navis)
        for offset, message in analysis.diagnostics:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    message,
                    file=item.source_file,
                    line=marker_line(item, offset),
                    item_id=item.id,
                    code=NAVI_DIAGNOSTIC_CODE,
                )
            )
        for navi in analysis.navis:
            message = keys_mod.malformed_key_message(navi.key) if navi.key else None
            if message is not None:
                diagnostics.append(
                    Diagnostic(
                        "warning",
                        message,
                        file=item.source_file,
                        line=marker_line(item, navi.line_offset),
                        item_id=item.id,
                        code=NAVI_DIAGNOSTIC_CODE,
                    )
                )
    return diagnostics


def projection(project: Project) -> list[dict]:
    """Every Navi of the project as plain JSON data (design §11: one
    projection, read by the `index` payload and the CLI alike -- no second
    implementation), merged with the `.refdes/navis/` archive store:
    **active first in (file, line) order, then archived, then the records
    whose marker is gone** (the §9 states; `ls` is the active prefix,
    `all` is the whole list, and the selector ordinals address this list).

    Marker rows are ``{key, text, source: {item, key, file, line},
    archived, snapshot, text_changed}``; `key` is None for a keyless
    marker (the nullable always-present field is the item payload's
    convention, render.items_json). An archived row's `snapshot` is the
    record's frozen text (``{text, archived_at}``); `text_changed` says
    the live marker text differs from it (§9 row 4: the note, shown by
    `show`/Show-all, snapshot never re-stamped). An archived Navi whose
    marker has been hand-deleted is an orphan row: `text` is the
    snapshot, `source` is the record's stored snapshot with
    ``marker_found: False`` (display labels it "marker not found", §9
    row 3), and the record's ``navis.archived_orphan`` diagnostic comes
    from the build (`build.py`), not from here."""
    from . import navis_archive

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

    records, _corrupt = navis_archive.load_records(str(project.root))
    by_key = {r.navi_key: r for r in records}
    active, archived, matched = [], [], set()
    for row in rows:
        record = by_key.get(row["key"]) if row["key"] else None
        if record is None:
            row["archived"] = False
            row["snapshot"] = None
            row["text_changed"] = False
            active.append(row)
            continue
        matched.add(record.navi_key)
        row["archived"] = True
        row["snapshot"] = {
            "text": record.text,
            "archived_at": record.archived_at,
        }
        row["text_changed"] = row["text"] != record.text
        archived.append(row)
    for record in records:
        if record.navi_key in matched:
            continue
        archived.append(
            {
                # §9 row 3: the marker is gone; the scan is the live truth
                # and it finds nothing, so this row IS the record -- text
                # and all. The live link is dead by design (the pointer
                # was the archive's subject, §2.3).
                "key": record.navi_key,
                "text": record.text,
                "source": {
                    "item": None,
                    "key": record.item_key or None,
                    "file": record.source["file"],
                    "line": record.source["line"],
                    "marker_found": False,
                },
                "archived": True,
                "snapshot": {
                    "text": record.text,
                    "archived_at": record.archived_at,
                },
                "text_changed": False,
            }
        )
    return active + archived


def archive_diagnostics(project: Project) -> list:
    """The store's build-time diagnostics (design §9): every unreadable
    record (`navis.archive_corrupt`, naming its file) and every record
    with no marker (`navis.archived_orphan`, attached to the record's
    stored file -- the §9 row-3 posture). Reads the same records the
    projection merges; one read per build, the standing rule for
    task-pane data (PR #197 review P4)."""
    from . import navis_archive

    records, diagnostics = navis_archive.load_records(str(project.root))
    keyed = set()
    for item in project.local_items:
        for navi in item.navis:
            if navi.key:
                keyed.add(navi.key)
    for record in records:
        if record.navi_key in keyed:
            continue
        diagnostics.append(
            Diagnostic(
                level="warning",
                message=(
                    f"navis.archived_orphan: Navi {record.navi_key} is "
                    f"archived with no marker found at its stored source "
                    f"({record.source['file']}:{record.source['line']}) -- "
                    "the marker was hand-deleted or moved out of scope. "
                    "Show-all reveals it by snapshot; restore refuses "
                    "(§9) -- hand-restore the marker to re-pair them by key"
                ),
                file=os.path.relpath(record.path, str(project.root)),
                line=record.source["line"],
                code=navis_archive.NAVI_ARCHIVED_ORPHAN_CODE,
            )
        )
    return diagnostics
