"""Locate a Navi marker's bytes inside a YAML list file's ``body:`` scalar.

The markdown mint (``navis.mint_keys``) writes at ``Item.body_line +
occ.line``: the item's body IS the file's text, so the marker's line is
the file's line. A list file has no ``body_line`` -- its ``body:`` scalar
is the body's only source, and the parsed value generally is not the
source text (indentation stripped, quotes removed, escapes decoded, line
folds joined). Minting there is safe only where the marker's bytes can be
pointed at exactly, and this module resolves them for the two shapes
where that is true:

* **literal block scalars** (``body: |``, with any chomping/indent
  indicator): every body line is a file line with one indentation run
  stripped, byte for byte -- the check is exact, the same byte equality
  the markdown path demands;
* **single-line quoted scalars** (``body: "..."`` / ``body: '...'``):
  decoded through a mirror of PyYAML's flow-scalar scanner, gated on the
  decoded text equalling the parsed body byte for byte.

Everything else REFUSES, and refusal is the whole answer -- the marker
stays keyless, the bytes stay untouched, the warning names the shape, the
same posture as every markdown refusal:

* folded (``>``) scalars: their lines fold into single spaces, so a
  marker's bytes are not a line of the file;
* plain scalars: a keyless marker's ``:`` + space cannot be written plain
  at all (it parses as a mapping), which is why this refusal is nearly
  unreachable -- the file that loads does not contain the marker;
* quoted scalars spanning more than one line (the same fold), and any
  scalar inside flow style;
* a ``body:`` supplied by a merge key (``<<:``) or by the file's
  ``defaults:``, and a body scalar an alias shares -- minting into one
  name would edit every body bound to the same node;
* anything whose reconstruction does not byte-equal the parsed body.

The splice is applied to the file's raw text (terminators included), so
CRLF/lone-CR files keep their terminators exactly as the markdown path
keeps them. The final gate re-parses the spliced text: the file must
parse, every item of the file must still be there, the minted bodies must
equal the originals with exactly the spliced keys, and no other body may
move. A gate that fails returns no rewrite at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from .navis import MARKER_OPEN, _split_raw

_LITERAL_HEADER = re.compile(r"^[+-]?([0-9])?[+-]?\s*(#.*)?$")

# PyYAML's flow-scalar escape tables (yaml.reader), mirrored for the quoted
# decoder. The decoder must match the scanner the parse used -- the equality
# gate (decoded == parsed value) is what makes "mirrored" verified, not
# trusted.
_ESCAPES = {
    "0": "\x00", "a": "\x07", "b": "\x08", "t": "\x09", "\t": "\x09",
    "n": "\x0a", "v": "\x0b", "f": "\x0c", "r": "\x0d", "e": "\x1b",
    " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0",
    "L": "\u2028", "P": "\u2029",
}
_ESCAPE_CODES = {"x": 2, "u": 4, "U": 8}

OPEN_LEN = len(MARKER_OPEN)

REFUSE_FOLDED = (
    "folded (>) scalar: its lines fold into single spaces, so the marker's "
    "bytes are not a line of the file"
)
REFUSE_PLAIN = (
    "plain scalar: a keyless marker's `: ` cannot be written in a plain scalar at all "
    "(it parses as a mapping) -- a file that loads does not carry the marker this way"
)
REFUSE_FLOW = "scalar inside flow style: refdes mints keys only into block-context bodies"
REFUSE_MULTIQUOTED = (
    "quoted scalar spanning more than one line: its folds join lines with spaces, "
    "so the marker's bytes are not a line of the file"
)
REFUSE_MERGED = (
    "`body:` is not a key of the item's own entry (a merge key `<<:` or the file's "
    "`defaults:` supplies it)"
)
REFUSE_SHARED = "`body:` scalar is shared (an alias names it more than once)"
REFUSE_NOT_SCALAR = "`body:` value is not a scalar string"
REFUSE_STYLE = "scalar style refdes does not locate"
REFUSE_RECONSTRUCT = "block scalar does not reconstruct the parsed body byte for byte"
REFUSE_BYTES = "the marker's bytes cannot be located in the scalar at its parsed position"
REFUSE_MAPPING = "the item's entry mapping is not on a line of its own (flow style?)"
REFUSE_GATE = "the spliced file failed the re-parse gate -- nothing was written"


@dataclass
class YamlPlan:
    """The result of planning one file's YAML body mints.

    ``after`` is the spliced text (``None``: nothing spliced), ``minted``
    the (item, key) pairs that landed in it, ``refused`` the (item,
    reason) pairs the caller turns into ``NAVI_MINT_REFUSED`` warnings.
    """

    after: str | None = None
    minted: list = field(default_factory=list)
    refused: list = field(default_factory=list)


def _normalize(text: str) -> tuple[str, list[int]]:
    """The parser's view of raw text (text mode's universal newlines)
    plus the normalized-index -> raw-index map.

    The parse reads files in text mode (``parse.read_source``), so scalar
    marks are positions in the LF-normalized text; the write goes to the
    raw file. The map is exact for the splice because every character the
    splice touches (``<!--navi:``, spaces, tabs, the key) is one raw
    character, never a line break.
    """
    chars: list[str] = []
    n2raw: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\r":
            chars.append("\n")
            n2raw.append(i)
            i += 2 if text.startswith("\n", i + 1) else 1
        else:
            chars.append(c)
            n2raw.append(i)
            i += 1
    return "".join(chars), n2raw


def _walk(doc):
    """Every node of ``doc``, each edge (parent, child) it names."""
    edges = []

    def visit(node):
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                edges.append(value)
                visit(key)
                visit(value)
        elif isinstance(node, yaml.SequenceNode):
            for value in node.value:
                edges.append(value)
                visit(value)

    visit(doc)
    return edges


def _parent_counts(docs) -> dict:
    """Every node counted once per parent that names it, over all docs.

    A body scalar an alias shares (or a merge key merges) is named more
    than once: minting a key into it would rewrite every body bound to
    the same node, so a count above 1 refuses the mint.
    """
    counts: dict[int, int] = {}
    for doc in docs:
        for node in _walk(doc):
            counts[id(node)] = counts.get(id(node), 0) + 1
    return counts


def _entry_maps(docs) -> list[yaml.MappingNode]:
    """Every mapping node of the docs, with its start line (1-indexed)."""
    out: list[yaml.MappingNode] = []

    def visit(node):
        if isinstance(node, yaml.MappingNode):
            out.append(node)
            for key, value in node.value:
                visit(key)
                visit(value)
        elif isinstance(node, yaml.SequenceNode):
            for value in node.value:
                visit(value)

    for doc in docs:
        visit(doc)
    return out


def _is_flow(node: yaml.MappingNode, n_lines: list[str]) -> bool:
    """True when the mapping is written in flow style (``{...: ...}``).

    Composed mapping nodes carry no style flag, but a flow mapping's
    ``start_mark`` points at the opening brace, a block mapping's at the
    first key -- the character at the mark is the test.
    """
    line = n_lines[node.start_mark.line]
    return line[node.start_mark.column : node.start_mark.column + 1] == "{"


def _renamed_fields() -> dict:
    """``parse._RENAMED_FIELDS``, imported lazily: navis imports this module
    inside ``mint_keys`` for the same cycle-avoiding reason."""
    from .parse import _RENAMED_FIELDS

    return _RENAMED_FIELDS


def _body_key(entry: yaml.MappingNode, item_type: str = ""):
    """The entry's own ``body:`` value node, or None.

    A legacy body field on its way out (hardware@2's ``text:`` on
    requirement/bound, ``method:`` on test -- ``parse._RENAMED_FIELDS``
    folds the value into ``item.body`` with a rename warning) IS this
    item's body, sits on the entry's own line, and mints the same. A
    real ``body:`` key anywhere in the entry wins over an alias,
    matching the loader's rule that a rename "never silently overwrites
    real body content".

    None is the merge-key/defaults answer: ``<<:`` is flattened by the
    constructor, not the composed graph, so an entry that inherits its
    body has no body-key node -- and neither has one the file-wide
    ``defaults:`` supplies, which is exactly the refusal wanted.
    """
    aliases = {
        old
        for (type_name, old), new in _renamed_fields().items()
        if type_name == item_type and new == "body"
    }
    fallback = None
    for key, value in entry.value:
        if not isinstance(key, yaml.ScalarNode):
            continue
        if key.value == "body":
            return value
        if fallback is None and key.value in aliases:
            fallback = value
    return fallback


def _decode_quoted(text: str, lo: int, hi: int, style: str):
    """Decode the quoted scalar ``text[lo:hi]`` (between the quotes) as
    PyYAML's flow-scalar scanner decodes it, returning ``(decoded, the
    source index of every decoded character)``.

    None for a malformed escape (the parse would have rejected the file;
    the equality gate is what makes this mirror verified, not trusted).
    """
    decoded: list[str] = []
    src: list[int] = []
    i = lo
    if style == '"':
        while i < hi:
            c = text[i]
            if c == "\\":
                e = text[i + 1]
                j = i + 2
                if e in _ESCAPES:
                    decoded.append(_ESCAPES[e])
                    src.append(i)
                    i = j
                elif e in _ESCAPE_CODES:
                    digits = text[j : j + _ESCAPE_CODES[e]]
                    if len(digits) < _ESCAPE_CODES[e] or any(
                        d not in "0123456789abcdefABCDEF" for d in digits
                    ):
                        return None
                    decoded.append(chr(int(digits, 16)))
                    src.append(i)
                    i = j + _ESCAPE_CODES[e]
                else:
                    return None
            elif c == '"':
                return None
            else:
                decoded.append(c)
                src.append(i)
                i += 1
    else:  # "'"
        while i < hi:
            c = text[i]
            if c == "'":
                if text.startswith("''", i):
                    decoded.append("'")
                    src.append(i)
                    i += 2
                    continue
                return None
            decoded.append(c)
            src.append(i)
            i += 1
    return "".join(decoded), src


def _marker_splice(n: str, item, occ, resolve) -> tuple[int, int, int, int] | None:
    """``(n_index, drop, open_abs, ws_end_abs)`` for one occurrence, or
    None.

    ``resolve`` maps a body character position to its ``n`` position (the
    style-specific locator); the checks that follow are the lossless
    contract: the source must carry the marker's own bytes at the mapped
    position, and the author's whitespace after the colon must be present
    in the source with the same length as in the body.
    """
    body = item.body
    raw_lines = _split_raw(body)
    _raw_line, line_start, _term = raw_lines[occ.line]
    open_abs = line_start + occ.start
    ws_end = open_abs + OPEN_LEN
    while ws_end < len(body) and body[ws_end] in " \t":
        ws_end += 1
    pos = resolve(open_abs)
    if pos is None:
        return None
    if n[pos : pos + OPEN_LEN] != MARKER_OPEN:
        return None
    if n[pos + OPEN_LEN : pos + OPEN_LEN + (ws_end - open_abs - OPEN_LEN)] != body[
        open_abs + OPEN_LEN : ws_end
    ]:
        return None
    return pos + OPEN_LEN, ws_end - open_abs - OPEN_LEN, open_abs, ws_end


def _literal_indent(n_lines, node, entry) -> int | None:
    """The block scalar's content indentation, or None for a header this
    module will not splice (e.g. an indicator run it cannot read).

    ``body: |`` auto-detects its indent from the first content line;
    ``body: |2`` states it as the parent mapping's indentation + 2. A
    chomping indicator (``-``/``+``) changes only the trailing breaks, so
    it does not change this.
    """
    header = n_lines[node.start_mark.line]
    suffix = header[node.start_mark.column + 1 :]
    if _LITERAL_HEADER.match(suffix) is None:
        return None
    digits = "".join(ch for ch in suffix.split("#")[0] if ch.isdigit())
    if digits:
        if len(digits) > 1:
            return None
        return entry.start_mark.column + int(digits)
    for line in n_lines[node.start_mark.line + 1 :]:
        if line.strip():
            return len(line) - len(line.lstrip(" "))
    return None


def _literal_resolver(n_lines, line_starts, node, item, occ, indent):
    """Body position -> ``n`` position for a literal block scalar: body
    line i is file line ``header + 1 + i`` at column ``indent + col``."""

    def resolve(open_abs):
        _raw_line, line_start, _term = _split_raw(item.body)[occ.line]
        source_line = header + 1 + occ.line
        if source_line >= len(n_lines):
            return None
        col = indent + (open_abs - line_start)
        if col > len(n_lines[source_line]):
            return None
        return line_starts[source_line] + col

    header = node.start_mark.line
    return resolve


def _quoted_resolver(decoded_src):
    """Body position -> ``n`` position for a single-line quoted scalar,
    via the decoder's per-character source map. The map is only valid
    where the source run is contiguous (no escape inside the marker), so
    the check lives here, next to the map."""
    _text, src = decoded_src

    def resolve(open_abs):
        if open_abs + OPEN_LEN > len(src):
            return None
        start = src[open_abs]
        for k in range(OPEN_LEN):
            if src[open_abs + k] != start + k:
                return None
        return start

    return resolve


def plan_yaml_mints(text: str, entries, file_items) -> YamlPlan:
    """Plan the YAML ``body:`` mints of one list file.

    ``text`` is the file's raw text, ``entries`` the
    ``(item, occurrence, key)`` triples the markdown mint left for YAML
    (``Item.body_line is None``), ``file_items`` every item of this file
    (the re-parse gate compares all of them, not just the targets).
    """
    plan = YamlPlan()
    n, n2raw = _normalize(text)
    n_lines = n.split("\n")
    line_starts = [0]
    for line in n_lines:
        line_starts.append(line_starts[-1] + len(line) + 1)
    try:
        docs = [d for d in yaml.compose_all(n, Loader=yaml.SafeLoader) if d is not None]
    except yaml.YAMLError:
        return YamlPlan(refused=[(item, REFUSE_RECONSTRUCT) for item, _occ, _key in entries])
    counts = _parent_counts(docs)
    maps = _entry_maps(docs)

    requests: list[tuple] = []  # (item, key, splice, drop, open_abs, ws_end)
    for item, occ, key in entries:
        item_maps = [m for m in maps if m.start_mark.line + 1 == item.source_line]
        if len(item_maps) != 1:
            plan.refused.append((item, REFUSE_MAPPING))
            continue
        entry = item_maps[0]
        if _is_flow(entry, n_lines):
            plan.refused.append((item, REFUSE_FLOW))
            continue
        node = _body_key(entry, item.type)
        if node is None:
            plan.refused.append((item, REFUSE_MERGED))
            continue
        if counts.get(id(node), 0) > 1:
            plan.refused.append((item, REFUSE_SHARED))
            continue
        if not isinstance(node, yaml.ScalarNode) or node.value != item.body:
            plan.refused.append((item, REFUSE_NOT_SCALAR))
            continue
        style = node.style
        if style == "|":
            indent = _literal_indent(n_lines, node, entry)
            if indent is None:
                plan.refused.append((item, REFUSE_RECONSTRUCT))
                continue
            if not _literal_reconstructs(n_lines, node, item.body, indent):
                plan.refused.append((item, REFUSE_RECONSTRUCT))
                continue
            resolve = _literal_resolver(n_lines, line_starts, node, item, occ, indent)
        elif style in ('"', "'"):
            lo = line_starts[node.start_mark.line] + node.start_mark.column + 1
            hi = line_starts[node.end_mark.line] + node.end_mark.column - 1
            decoded = _decode_quoted(n, lo, hi, style)
            if (
                node.start_mark.line != node.end_mark.line
                or decoded is None
                or decoded[0] != node.value
            ):
                plan.refused.append((item, REFUSE_MULTIQUOTED))
                continue
            resolve = _quoted_resolver(decoded)
        elif style == ">":
            plan.refused.append((item, REFUSE_FOLDED))
            continue
        elif style in (None, ""):
            plan.refused.append((item, REFUSE_PLAIN))
            continue
        else:
            plan.refused.append((item, REFUSE_STYLE))
            continue
        spliced = _marker_splice(n, item, occ, resolve)
        if spliced is None:
            plan.refused.append((item, REFUSE_BYTES))
            continue
        splice, drop, open_abs, ws_end = spliced
        requests.append((item, key, splice, drop, open_abs, ws_end))

    if not requests:
        return plan

    splices = sorted(requests, key=lambda r: r[2], reverse=True)
    raw = text
    for _item, key, splice, drop, _open_abs, _ws_end in splices:
        lo = n2raw[splice]
        hi = n2raw[splice + drop - 1] + 1 if drop else lo
        raw = raw[:lo] + key + " " + raw[hi:]

    expected = _expected_bodies(file_items, requests)
    if not _gate(raw, expected):
        return YamlPlan(
            refused=plan.refused + [(item, REFUSE_GATE) for item, _k, _s, _d, _o, _w in requests]
        )
    plan.after = raw
    plan.minted = [(item, key) for item, key, _s, _d, _o, _w in requests]
    return plan


def _literal_reconstructs(n_lines, node, body, indent: int) -> bool:
    """Every body line is the file line at ``header + 1 + i`` from column
    ``indent`` on, byte for byte (trailing spaces included, the way a
    literal block keeps them); blank body lines are blank file lines.

    Lines past the body's last are the next entry's -- a literal block
    ends at the first line dedented below its content indent -- so they
    are not this block's reconstruction and not checked here.
    """
    header = node.start_mark.line
    body_lines = [raw for raw, _start, _term in _split_raw(body)]
    if body_lines and body_lines[-1] == "":
        body_lines = body_lines[:-1]  # text after the body's final break
    for i, body_line in enumerate(body_lines):
        source_line = header + 1 + i
        if source_line >= len(n_lines):
            return False
        source = n_lines[source_line]
        if source.strip() == "":
            if body_line == "":
                continue
            return False
        if len(source) - len(source.lstrip(" ")) < indent:
            return False  # dedented below the block: not part of it
        if source[indent:] != body_line:
            return False
    return True


def _expected_bodies(file_items, requests) -> dict:
    """Each item of the file's body after the mint: the target bodies
    carry their keys (multiple markers per body spliced right-to-left),
    every other body is exactly as parsed."""
    expected = {item.id: item.body for item in file_items}
    by_item: dict = {}
    for request in requests:
        by_item.setdefault(id(request[0]), (request[0], []))[1].append(request)
    for item, item_requests in by_item.values():
        body = item.body
        # right-to-left in the body, exactly as the splices go right-to-left
        # in the file: one marker's insertion never moves the next's position.
        for _i, key, _splice, _drop, open_abs, ws_end in sorted(
            item_requests, key=lambda r: r[4], reverse=True
        ):
            insert = open_abs + OPEN_LEN
            body = body[:insert] + key + " " + body[ws_end:]
        expected[item.id] = body
    return expected


def _gate(raw_text: str, expected: dict) -> bool:
    """Re-parse the spliced text: it must parse, every named item must be
    there, and every body must be the expected one -- the mint's key in
    the targets, nothing moved anywhere else.

    ``str()`` of the parsed value, matching how the list-file loader
    turns a body into ``Item.body``; the count is the number of entries
    carrying an ``id``, so a splice that ate an entry fails.
    """
    n, _map = _normalize(raw_text)
    try:
        data = yaml.safe_load(n)
    except yaml.YAMLError:
        return False
    if not isinstance(data, dict):
        return False
    entries = data.get("items")
    if not isinstance(entries, list):
        return False
    seen = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("id")
        if item_id is None:
            continue
        seen += 1
        if str(item_id) not in expected:
            continue
        if "body" not in entry:
            # The body comes from `<<:`/`defaults:` -- this entry carries
            # no body bytes to compare, and the loader's inherited value
            # is not a splice target (its own item is refused upstream).
            continue
        body = entry["body"]
        if (str(body) if body is not None else "") != expected[str(item_id)]:
            return False
    return seen >= len(expected)
