"""JSON API handlers for `refdes serve`, kept free of HTTP details.

`handle()` is given an already-authenticated request (see `server`) and
returns `(status, payload)`. Reads answer from the *built* project snapshot,
never from a file scan.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import urllib.parse

from .. import build as build_mod
from .. import citations as citations_mod
from .. import inline_calc
from ..model import (
    CHECK_VIOLATION,
    NON_SCALAR_FIELD_TYPES,
    Diagnostic,
    Item,
    Project,
)
from ..patcher import PROTECTED_FIELDS, AddLink, RemoveLink, SetBody, SetField
from ..seal import is_sealed
from . import edit as edit_mod
from . import filters as filters_mod
from . import resolution
from . import sources as sources_mod
from . import state as state_mod
from . import upload as upload_mod
from .filters import FilterError, check_state, item_tags, validate_facet


def item_pages(project: Project) -> dict[str, str]:
    """`project.items` dict key (surrogate key or provisional handle) ->
    the rendered page filename `render_site` writes for that item."""
    return {key: f"{item.slug}.html" for key, item in project.items.items()}


# Three source-read routes are dispatched below through `_SOURCE_ROUTES`, which
# is declared with their handlers further down this file. They are all GET: a
# non-GET on one is a 405 here, the same as any other `/api/item/` route.
def handle(app, method: str, path: str, query: dict[str, list[str]], body) -> tuple[int, dict]:
    if path == "/api/revision" and method in ("GET", "HEAD"):
        return 200, app.state.revision_info()
    if path == "/api/items" and method in ("GET", "HEAD"):
        return _items(app, query)
    if path.startswith("/api/item/") and path.endswith("/edit"):
        ref = urllib.parse.unquote(path[len("/api/item/"):-len("/edit")])
        if method == "POST":
            return _write_outcome(app, _apply_edit(app, ref, body))
        return 405, {"error": "method not allowed"}
    if path.startswith("/api/item/") and path.endswith("/calc"):
        ref = urllib.parse.unquote(path[len("/api/item/"):-len("/calc")])
        if method == "POST":
            return _calc_preview(app, ref, body)
        return 405, {"error": "method not allowed"}
    if path == "/api/create/schema" and method in ("GET", "HEAD"):
        return _create_schema(app)
    if path == "/api/create/preview" and method in ("GET", "HEAD"):
        return _create_preview(app, query)
    if path == "/api/images" and method in ("GET", "HEAD"):
        return _images(app, (query.get("item") or [""])[0])
    if path == "/api/assets":
        if method == "POST":
            return _upload_asset(app, query, body)
        return 405, {"error": "method not allowed"}
    if path == "/api/items/create" and method == "POST":
        return _write_outcome(app, _create_item(app, body))
    if path.startswith("/api/item/"):
        for suffix, handler in _SOURCE_ROUTES:
            if not path.endswith(suffix):
                continue
            if method not in ("GET", "HEAD"):
                return 405, {"error": "method not allowed"}
            ref = urllib.parse.unquote(path[len("/api/item/"):-len(suffix)])
            return handler(app, ref, query)
    if path.startswith("/api/item/") and method in ("GET", "HEAD"):
        ref = urllib.parse.unquote(path[len("/api/item/"):])
        return _item_view(app, ref)
    if path in ("/api/items", "/api/images", "/api/items/create", "/api/assets") or path.startswith("/api/item/"):
        return 405, {"error": "method not allowed"}
    return 404, {"error": "not found"}


def _items(app, query: dict[str, list[str]]) -> tuple[int, dict]:
    project = app.state.snapshot.project
    try:
        filters = filters_mod.parse_filters(project, query)
        limit = filters_mod.parse_limit(query)
    except FilterError as exc:
        return exc.status, {"error": str(exc)}
    return 200, filters_mod.items_payload(project, filters, limit)


def _find_item(project: Project, ref: str) -> tuple[Item | None, str | None]:
    """Resolve an item-view reference. Accepted spellings, in order: the
    `project.items` dict key (surrogate key, or the provisional handle of a
    keyless item — what `/api/items` rows carry as `handle`), then display id,
    then surrogate key via `item_by_ref`, then a retired id some item still
    records in `former_ids:`. A provisional handle is never a linkable
    identity, so the resolver accepts it only by exact dict hit and echoes it
    back, letting the UI address the item again.

    The retired-id step is what makes the hover promise of docs/ids.md true:
    the id people have from a schematic or a commit message is the retired
    one, and `refdes ls` already answers it. Without this step the API 404'd
    on it (run-5 finding B5), so the hover card for a schematic id was
    silent. A retired id that is also a live display id resolves to the live
    item: the live lookups run first, the retired scan is never reached. A
    retired id claimed by two items resolves to nothing on this route (404)
    and on the write route (422 naming the claimants) -- the resolver refuses
    to pick. That is a real change from the map this route used to consult:
    `ids.collect_former_ids` keeps the FIRST claimant of a contested id in
    `project.former_ids`, and the old route answered 200 with it.

    The resolution itself lives in `serve.resolution.resolve_ref` -- the
    write route calls the same function, which is the point: two routes over
    one set of spellings, so they cannot drift.
    """
    resolved = resolution.resolve_ref(project, ref)
    if resolved.item is None:
        return None, None
    return resolved.item, resolved.handle


def _diagnostics_for(project: Project, item: Item, handle: str) -> list[dict]:
    refs = {r for r in (item.id, item.key, handle) if r}
    out = []
    for d in project.diagnostics:
        if d.item_id and d.item_id in refs:
            out.append(
                {
                    "level": d.level,
                    "message": d.message,
                    "file": d.file,
                    "line": d.line,
                    "code": d.code,
                }
            )
    return out


def diag_dict(d: Diagnostic) -> dict:
    return {
        "level": d.level,
        "message": d.message,
        "file": d.file,
        "line": d.line,
        "code": d.code,
    }


# ---------------------------------------------------- root-relative write answers
#
# One choke point for both write routes: `handle()` runs the (status, payload)
# of the edit and create routes through `_write_outcome`, which rewrites
# every absolute path under the project root in the whole payload to the
# project-relative spelling the sibling `path` fields already carry. Those
# fields got `shown()` from the start; the free-text ones -- `message`,
# `reason`, `describe`, the diff, the diagnostics -- kept the machine path
# inside sentences built at the service layer (user-sim run 13, section 3.5),
# and a per-field patch at each site is the rule re-implemented ten times.
# The walk is payload-wide so a field added next month is covered by the
# same rule.

# The scanner grammar (round-4 escalation, per the deep analysis of the
# previous head): ONE left-to-right pass over each string, no rewriting of
# anything the scan did not match. At each position, in this documented
# precedence: a quoted scalar span (`"`-delimited, escapes honored -- a
# path with spaces inside it is unambiguously one path), a local `file:`
# URI span (scheme at any casing, 0-3 slashes, optional `localhost`
# authority -- its prefix is removed with the path; a dotted authority is
# a web URL and passes through), a long-path prefix (`\\?\`, `//?/` ->
# `<outside project>`; the
# scanner does not discover aliases of the root), a drive-absolute span
# (`C:\...`), an absolute span (`/...` or `\...`). A span is classified by
# trying the literal root pattern anchored at its start: the root is ONE
# separator-run pattern (the native spelling, the forward-slash one, and
# the JSON-escaped doubling all match -- there is no spelling list to keep
# in step), it ends only at a boundary (not a letter/digit/`_`/`-`, not a
# `.` that starts a name; the sentence-ending `.` IS consumed, so a root
# ending a sentence keeps ONE period), a drive-letter root matches at any
# case, and a bare root keeps its `:line[:col]` suffix. Under the root the
# span renders its remainder AS WRITTEN -- separator normalization lives
# only inside the matched root, never in the text after it; outside, the
# whole token reduces to its leaf (`<outside project>` when it has none),
# crossing a single space only when the next piece is unambiguously
# path-shaped (contains a separator, ends in a file extension) -- a
# documented grammar limit, not an intent detector: `/verbose` reads as a
# path and scrubs as one. Quoted scalars decode (JSON first, a YAML-ish
# fallback), scrub, and re-encode; content that decodes to itself is
# re-emitted as the original bytes. Replacement text is never re-scanned,
# so a scrubbed path is never reclassified.
_SEPS = r"[\\/]+"
_TRAILING = ".,;:!?)]}'\"`>"
_DRIVE_ROOT = re.compile(r"[A-Za-z]:")
_SCALAR = re.compile(r"\"(?:[^\"\\\n\r]|\\[^\n\r])*\"")
# Span starts: a `/` or `\` at a boundary (a `/` inside a word, behind a
# colon+slash, behind a dot, or inside a separator run is not a path
# start -- this is what keeps `and/or`, `5/6`, `path/to/x`, `http://x/y`,
# `prefix/home/you/proj` untouched), and a drive letter likewise.
_PATH_START = re.compile(r"(?<![A-Za-z0-9_\-:/\\.])(?=[/\\])")
_DRIVE_START = re.compile(r"(?<![A-Za-z0-9_\-:/\\.])(?=[A-Za-z]:[\\/])")
_FILE_PREFIX = re.compile(r"(?<![A-Za-z0-9_\-])file:", re.IGNORECASE)
_PIECE = re.compile(r"[^\s:;\"'`\\/]+(?:[\\/][^\s:;\"'`]+)*\.[A-Za-z0-9]+")
_RUN_END = re.compile(r"[\s`\"'<>]|\Z")
_SUFFIX = re.compile(r"(:\d+(?::\d+)?)\Z")
_EXT_END = re.compile(r"\.[A-Za-z0-9]+\Z")
# A root occurrence preceded by anything OTHER than start, whitespace, a
# quote, or opening punctuation (a word, `=`, a URL host, a `/`) is not a
# path span the reader can act on -- the root text is replaced by the
# marker and the surrounding text survives byte for byte.
_BOUND_PREV = re.compile(r"[\s\"'`([{<]")
_PROJECT_ROOT_MARK = "<project root>"
# The windows-flavored under-root remainder converts WHOLE: every piece
# up to the span end renders its separators as `/` (the spelling the
# response's `path` field uses) -- no piece needs a file extension. The
# one termination is escape notation: a SINGLE separator followed by a
# word with no file extension that opens with a JSON escape letter ends
# the path span BEFORE it, so the two characters of a `\n`/`\"`-style
# escape survive intact (`items\reqs.yaml\then` renders
# `items/reqs.yaml` and leaves `\then`).
_WIN_WORD = re.compile(r"[^\\/]+")
_WIN_STEP = re.compile(r"([\\/]+)([^\\/]+)")
_WIN_ESCAPES = frozenset('"\\/bfnrtu')
_EXT_TAIL = re.compile(r"\.[A-Za-z0-9]+\Z")


def _scrub_rules(root_cmp: str, fold: bool):
    """The per-response scanner rules, compiled once and cached: the
    separator-run root pattern (with the boundary and the consumed
    sentence period), the `file:` URI prefix, and the root's flavor --
    Windows-flavored means drive-letter or UNC, derived from the root
    string alone (so the Windows logic runs on Linux too). No filesystem
    access happens here: the comparison is lexical, on the root as
    supplied."""
    key = (root_cmp.casefold() if fold else root_cmp, fold)
    rules = _SCRUB_CACHE.get(key)
    if rules is None:
        parts = re.split(_SEPS, root_cmp)
        root_pat = (
            re.compile(
                _SEPS.join(re.escape(part) for part in parts)
                + r"(?:(?P<sw>"
                + _SEPS
                + r")(?=[^\s\\/])"
                + r"|(?:[\\/]+)?(?:\.(?![A-Za-z0-9])"
                + r"|(?![A-Za-z0-9_\-])(?!\.(?=[A-Za-z0-9]))))",
                re.IGNORECASE if fold else 0,
            )
            if len(root_cmp) > 1
            else None
        )
        rules = (
            root_pat,
            _FILE_PREFIX,
            root_cmp.startswith("//?/"),
            bool(_DRIVE_ROOT.match(root_cmp)) or root_cmp.startswith("//"),
        )
        _SCRUB_CACHE[key] = rules
    return rules


_SCRUB_CACHE: dict = {}


def _strip_trailing(text: str) -> tuple[str, str]:
    stripped = text.rstrip(_TRAILING)
    return stripped, text[len(stripped):]


_DOT_SEG = re.compile(r"(?:^|(?<=[/\\]))\.\.?\Z")


def _strip_trailing_keep_dots(text: str) -> tuple[str, str]:
    """Like _strip_trailing, but a trailing `.`/`..` that forms a complete
    DOT SEGMENT of the path is kept: it is path syntax, not the sentence's
    punctuation (and the normalization's `.` IS that period)."""
    end = len(text)
    while end > 0 and text[end - 1] in _TRAILING:
        if _DOT_SEG.search(text, 0, end) is not None:
            break
        end -= 1
    return text[:end], text[end:]


def _dot_segments(body: str, windows: bool):
    """Lexically collapse the `.` and `x/..` segments of an under-root
    remainder: the normalized spelling (empty string == the root itself),
    or None when a `..` climbs ABOVE the root -- the whole path then
    resolves outside the project. A POSIX root keeps backslashes as
    file-name characters, so only `/` separates there; a Windows
    remainder splits on both spellings (it renders forward-slash
    throughout anyway)."""
    parts = re.split(_SEPS if windows else r"/+", body)
    stack: "list[str]" = []
    for part in parts:
        if not part or part == ".":
            continue
        if part == "..":
            if stack:
                stack.pop()
            else:
                return None
        else:
            stack.append(part)
    return "/".join(stack)


def _run_end(text: str, pos: int) -> int:
    return _RUN_END.search(text, pos).start()


def _extend_over_space(text: str, end: int) -> tuple[int, "tuple[int, int] | None"]:
    """Extend an ended run over AT MOST ONE space when the next piece is
    unambiguously path-shaped (`_PIECE`: a separator, an extension) --
    the documented grammar for `read /etc/my conf/secret.md`. Prose that
    merely contains a separator is not swallowed, and crossing stops at
    one space: a list of paths (`a.md b.md`) is a list of separate
    references, not one path with a space in it. Returns the new end and
    the span of the crossed piece (an outside token's leaf is the last
    piece: `/opt/my notes.txt` reduces to `notes.txt`, not to the
    fragment `my notes.txt` before the space)."""
    cross = None
    piece = _PIECE.match(text, end + 1)
    if end < len(text) and text[end] == " " and piece is not None:
        end = piece.end()
        cross = piece.span()
    return end, cross


def _leaf(body: str) -> str:
    norm = re.sub(_SEPS, "/", body).rstrip("/")
    return norm.rpartition("/")[2] or "<outside project>"


def _render_relative(rest: str, pos: int, end: int, root_is_slash: bool,
                     windows: bool):
    """Under-root render of a scrubbed span: the remainder with its line
    suffix riding along, its trailing punctuation re-emitted after it,
    and the whole run consumed (the suffix and punctuation travel INSIDE
    the replacement, never back through the scan). A WINDOWS-flavored
    root renders the WHOLE remainder with forward slashes -- the same
    spelling the response's `path` field uses, on every platform -- piece
    by piece, with no extension required anywhere (`items\\sub\\NOEXT`
    renders `items/sub/NOEXT`); the span ends only at escape notation:
    a single separator followed by a word with no file extension that
    opens with a JSON escape letter (`items\\reqs.yaml\\nthen` renders
    `items/reqs.yaml` and leaves `\\nthen`), and text after the path
    span is re-emitted as written. A posix root keeps backslashes as
    file-name characters (the documented POLICY case), so there its
    remainder stays exactly as written."""
    def render(body: str, windows: bool) -> str:
        norm = _dot_segments(body, windows)
        return _leaf(body) if norm is None else norm

    if root_is_slash:
        rest = rest.lstrip("/\\")
        if not rest:
            return "<outside project>", end - pos
    if windows:
        word = _WIN_WORD.match(rest)
        if word is not None:
            span_end = word.end()
            step = _WIN_STEP.match(rest, span_end)
            while step is not None:
                seps, piece = step.group(1), step.group(2)
                base = _strip_trailing(re.sub(r":\d+(?::\d+)?\Z", "", piece))[0]
                if (
                    len(seps) == 1
                    and piece[0] in _WIN_ESCAPES
                    and not _EXT_TAIL.search(base)
                ):
                    break
                span_end = step.end()
                step = _WIN_STEP.match(rest, span_end)
            body, punct = _strip_trailing_keep_dots(rest[:span_end])
            found = _SUFFIX.search(body)
            if found:
                body, punct2 = _strip_trailing_keep_dots(body[: found.start()])
                return (
                    (render(body, True) or ".")
                    + found.group(1)
                    + punct2
                    + punct
                    + rest[span_end:],
                    end - pos,
                )
            tail = rest[span_end:]
            rendered = render(body, True)
            return (
                rendered + punct + tail
                if rendered or punct or tail
                else "."
            ), end - pos
    body, punct = _strip_trailing_keep_dots(rest)
    found = _SUFFIX.search(body)
    if found:
        body, punct2 = _strip_trailing_keep_dots(body[: found.start()])
        return (
            (render(body, windows) or ".") + found.group(1) + punct2 + punct,
            end - pos,
        )
    rendered = render(body, windows)
    return (
        rendered + punct
        if rendered or punct
        else "."
    ), end - pos


def _classify(text: str, pos: int, root_cmp: str, root_pat, windows: bool):
    """The span starting at ``pos`` -> (rendered, characters consumed);
    consumed 0 means the position is not the start of a path span."""
    if root_pat is not None:
        match = root_pat.match(text, pos)
        if match is not None:
            end = _run_end(text, match.end())
            if match.group("sw") is not None:
                if windows:
                    end, _ = _extend_over_space(text, end)
                return _render_relative(
                    text[match.end():end], pos, end, root_cmp == "/", windows
                )
            tail = text[match.end():end]
            found = _SUFFIX.search(tail)
            if found:
                return "." + found.group(1), end - pos
            # The consumed boundary may swallow a sentence-ending `.` --
            # the replacement `.` IS the sentence's single period.
            return ".", match.end() - pos
    end = _run_end(text, pos)
    if root_cmp == "/":
        return _render_relative(text[pos:end], pos, end, True, windows)
    head, _head_punct = _strip_trailing(text[pos:end])
    if head == "/" and (pos, end) != (0, len(text)):
        # A `/` standing alone in running text (arithmetic, a table cell)
        # is prose, not a path -- it passes through. The one exception is
        # the whole value being exactly `/`, which stays a path below.
        return "", 0
    cross = None
    # The `:line[:col]` suffix and a trailing extension CLOSE the
    # reference: a token that is already a completed path -- `plan.md`,
    # `x.md:3` -- does not reach across the space for the next word.
    token, _punct = _strip_trailing(text[pos:end])
    found = _SUFFIX.search(token)
    body, _punct2 = _strip_trailing(token[: found.start()] if found is not None else token)
    if found is None and not _EXT_END.search(body):
        end, cross = _extend_over_space(text, pos + len(body))
    token, punct = _strip_trailing(text[pos:end])
    found = _SUFFIX.search(token)
    if found:
        body, punct2 = _strip_trailing(token[: found.start()])
        leaf_src = text[cross[0]:cross[1]] if cross is not None else body
        return _leaf(leaf_src) + found.group(1) + punct2 + punct, end - pos
    leaf_src = text[cross[0]:cross[1]] if cross is not None else token
    return _leaf(leaf_src) + punct, end - pos


_YAML_ESCAPES = {"\\": "\\", '"': '"', "'": "'", "n": "\n", "r": "\r", "t": "\t"}


def _yaml_unescape(raw: str) -> str:
    out = []
    i = 0
    while i < len(raw):
        c = raw[i]
        nxt = raw[i + 1 : i + 2]
        if c == "\\" and nxt in _YAML_ESCAPES:
            out.append(_YAML_ESCAPES[nxt])
            i += 2
        elif c == "\\" and nxt == "x" and i + 4 <= len(raw):
            try:
                out.append(chr(int(raw[i + 2 : i + 4], 16)))
                i += 4
            except ValueError:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _yaml_escape(text: str) -> str:
    out = []
    for c in text:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20:
            out.append("\\x{:02x}".format(ord(c)))
        else:
            out.append(c)
    return "".join(out)


def _scrub_scalar(quoted: str, root_cmp: str, fold: bool, rules) -> str:
    """One quoted scalar: decode it (JSON first, the way the patcher
    writes values; a YAML-ish fallback for what JSON refuses, including
    `\\xHH`), scrub the decoded text, re-encode in the same syntax.
    Unchanged content is re-emitted as the original bytes."""
    try:
        decoded = json.loads(quoted)
        style = "json"
    except ValueError:
        decoded = _yaml_unescape(quoted[1:-1])
        style = "yaml"
    if not isinstance(decoded, str):
        return quoted
    scrubbed = _scan(decoded, root_cmp, fold, rules)
    if scrubbed == decoded:
        return quoted
    if style == "json":
        return json.dumps(scrubbed, ensure_ascii=False)
    return '"' + _yaml_escape(scrubbed) + '"'


def _scan(text: str, root_cmp: str, fold: bool, rules) -> str:
    root_pat, file_prefix, long_root, windows = rules
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            span = _SCALAR.match(text, i)
            if span is not None:
                out.append(_scrub_scalar(span.group(0), root_cmp, fold, rules))
                i = span.end()
                continue
        if not long_root and (
            text.startswith("\\\\?\\", i)
            or (text.startswith("//?/", i) and _PATH_START.match(text, i))
        ):
            out.append("<outside project>")
            i = _run_end(text, i)
            continue
        prefix = file_prefix.match(text, i)
        if prefix is not None:
            # A `file` scheme (any casing) with 0-3 slashes -- and its
            # `localhost` authority -- is a LOCAL FILE URI: the prefix goes
            # and the path scrubs like any bare path. The slashes split
            # between prefix and path by what the path keeps: a posix path
            # keeps its leading slash (`file:/home`, `file:///home`), a
            # drive path takes the slashes after it (`file:C:`,
            # `file://C:/`, `file:///C:/`). An authority that is not
            # `localhost` (a dotted host) is a web URL: the span passes
            # through untouched.
            base = prefix.end()
            slashes = 0
            while slashes < 3 and text[base + slashes : base + slashes + 1] == "/":
                slashes += 1
            candidates: list[int] = []
            if slashes <= 1:
                candidates.append(base)
            elif slashes == 2:
                authority_end = _run_end(text, base + 2)
                slash = text.find("/", base + 2)
                if 0 <= slash < authority_end:
                    authority_end = slash
                authority = text[base + 2 : authority_end]
                if authority.lower() == "localhost":
                    candidates.append(authority_end)
                    if text[authority_end : authority_end + 1] == "/":
                        candidates.append(authority_end + 1)
                elif "." not in authority:
                    candidates.append(base + 2)
            elif root_pat is not None and root_pat.match(text, base + 3):
                candidates.append(base + 3)
            else:
                candidates.append(base + 2)
            landed = False
            for pos in candidates:
                if root_pat is not None and root_pat.match(text, pos):
                    rendered, consumed = _classify(text, pos, root_cmp, root_pat, windows)
                    out.append(rendered)
                    i = pos + consumed
                    landed = True
                    break
            if not landed:
                for pos in candidates:
                    rendered, consumed = _classify(text, pos, root_cmp, root_pat, windows)
                    if consumed:
                        out.append(rendered)
                        i = pos + consumed
                        landed = True
                        break
            if landed:
                continue
            out.append(text[i:base])
            i = base
            continue
        span_at = None
        if ch == "/" and _PATH_START.match(text, i):
            span_at = i
        elif ch == "\\" and _PATH_START.match(text, i):
            span_at = i
        elif ch.isascii() and ch.isalpha() and _DRIVE_START.match(text, i):
            span_at = i
        if span_at is not None and (i == 0 or _BOUND_PREV.match(text, i - 1)):
            # The path-span rules (relative rendering, leaf, `.`) only
            # govern spans the reader can act on: a span preceded by
            # start, whitespace, a quote, or opening punctuation.
            rendered, consumed = _classify(text, span_at, root_cmp, root_pat, windows)
            if consumed:
                out.append(rendered)
                i = span_at + consumed
                continue
        if root_pat is not None and i > 0 and not _BOUND_PREV.match(text, i - 1):
            # A root occurrence glued to a word, an `=`, a URL host, or a
            # `/` is not a path span -- the reader cannot act on it. The
            # root TEXT becomes the marker; everything else (the URL, the
            # word, the rest of the path, a `:line` suffix) survives byte
            # for byte. The root pattern's own boundary check keeps a
            # longer sibling sharing the root's prefix from matching.
            match = root_pat.match(text, i)
            if match is not None:
                core = match.group(0).rstrip("/\\")
                if core.endswith("."):
                    core = core[:-1]
                if core:
                    out.append(_PROJECT_ROOT_MARK)
                    i += len(core)
                    continue
        out.append(ch)
        i += 1
    return "".join(out)


def _relative_paths(value, root: str):
    r"""Every string in a response payload, with the project root rewritten away.

    A path under ``root`` becomes its project-relative spelling. For a
    posix root the remainder of the path is left exactly as written
    (``items/REQ-001.md``, ``items\\reqs.yaml``); for a Windows-flavored
    root (drive-letter or UNC) the WHOLE remainder renders with forward
    slashes -- ``items/reqs.yaml`` in every input spelling (native
    backslash, forward-slash, JSON-escaped-doubled) and for every
    remainder (``items/sub/NOEXT`` included) -- except an escape-notation
    tail (``\\nthen``) and text after the path span, which are re-emitted
    as written; ``items/REQ-007.md:6`` when a line suffix follows; the
    root itself, with or without a trailing separator,
    becomes ``.``, a root ending a sentence keeps one period, and a bare
    root keeps its ``:6``/``:6:2`` suffix. Dot segments resolve
    LEXICALLY: the under-root remainder's ``.`` and ``x/..`` collapse to
    the normalized relative spelling (``items/../a.md`` renders ``a.md``,
    ``./a.md`` renders ``a.md``, a trailing ``..`` lands on the root),
    and a ``..`` that climbs above the root makes the whole path outside
    -- only the bare file name (with any line suffix) survives. The root matches as ONE
    separator-run pattern -- native, forward-slash, and JSON-escaped-doubled
    spellings are one match, spaces in the root are ordinary characters,
    a drive-letter root matches at any case (a UNC root is NOT folded --
    it matches as spelled), a local `file:` URI span
    (scheme at any casing, 0-3 slashes, optional `localhost` authority)
    is consumed with the path -- a dotted authority is a web URL and
    passes through -- and a root ending at a boundary never
    eats a sibling name sharing the root's prefix. The root TEXT survives
    nowhere in a response: an occurrence of the root with a path boundary
    in a position no path rule can rewrite -- inside a web URL, glued
    onto a preceding word (anything other than start, whitespace, a
    quote, or opening punctuation) -- has the root text replaced with the
    marker `<project root>` and every other byte left as written. A path OUTSIDE the root
    keeps only its bare file name (with any line suffix) -- the file name
    is the part an author can act on, and the directory outside the project
    is exactly what this response must not disclose; a token with no file
    name at all becomes ``<outside project>``, a QUOTED path keeps its
    spaces and reduces whole to its leaf, and an unquoted token crosses
    AT MOST ONE space, and only when the next piece is path-shaped and
    the token is not already a completed path -- a trailing extension or
    a ``:line`` suffix closes the reference, so ``plan.md draft.md`` and
    ``x.md:3 draft.md`` keep their second word (a documented grammar
    limit). Quoted scalars decode (JSON, a YAML-ish fallback), scrub, and
    re-encode ONLY when the scrubbing changed something -- a quoted scalar
    with no path in it is returned byte-identical, escapes and all; when
    it DOES contain a rewritten path the whole scalar re-encodes, so
    other escape sequences in that same string may come back as their
    plain characters (a documented limit). The surrounding syntax --
    escapes, URLs, prose -- survives byte for
     byte. Relative spellings are untouched. Known limits: a root path
     spelled with a backslash-escaped space (``proj\ demo``) is not
     recognized as under-root, an isolated ``/`` in running text
     (arithmetic, a table cell) passes through while a single-segment
     ``/word`` token (``/verbose``) is still treated as a path, and a
     project root of ``/`` takes the root branch before that
     isolated-slash rule. The walk
     covers the whole
    payload shape -- dict keys and values, list and tuple elements --
    because a path is a string anywhere; a key whose scrubbed form collides
    with one already taken gets a ``#2``/``#3`` suffix, so no record is
    ever lost."""
    if isinstance(value, str):
        return _relative_paths_in_text(value, root)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            new_key = _relative_paths(key, root)
            if new_key in out:
                n = 2
                while f"{new_key}#{n}" in out:
                    n += 1
                new_key = f"{new_key}#{n}"
            out[new_key] = _relative_paths(item, root)
        return out
    if isinstance(value, list):
        return [_relative_paths(item, root) for item in value]
    if isinstance(value, tuple):
        return tuple(_relative_paths(item, root) for item in value)
    return value


def _relative_paths_in_text(text: str, root: str) -> str:
    if not text:
        return text
    root_norm = (root or "").replace("\\", "/")
    if not (os.path.isabs(root_norm) or _DRIVE_ROOT.match(root_norm)):
        # On Linux a Windows-shaped root must not go through abspath (it
        # prefixes cwd and destroys the drive spelling).
        root_norm = os.path.abspath(root).replace("\\", "/")
    root_cmp = root_norm.rstrip("/") or "/"
    fold = bool(_DRIVE_ROOT.match(root_cmp))
    return _scan(text, root_cmp.casefold() if fold else root_cmp, fold,
                 _scrub_rules(root_cmp, fold))


def _write_outcome(app, result: tuple[int, dict]) -> tuple[int, dict]:
    """The serialization point of the write routes: every edit/create response
    leaves `handle()` through here, so the root-relative rule of
    `_relative_paths` is applied to the whole payload once, at the choke
    point, for both routes."""
    status, payload = result
    return status, _relative_paths(payload, app.state.snapshot.project.root)


# ------------------------------------------------------------- edit affordances

# Field types whose values are collections: the patcher replaces scalar spans
# only, so these are read-only in the form (docs/design/browser-editor.md,
# "Editing fields" -- links have their own picker, a later slice). The create
# path and the loader enforce the same rule from the one constant in model.py,
# imported above and named here so `api.NON_SCALAR_FIELD_TYPES` keeps
# resolving for whatever reads it from this module.


def _value_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return "string"


def _calc_preview(app, ref: str, body) -> tuple[int, dict]:
    """`POST /api/item/<ref>/calc` -- the live editor's read-only inline-calc
    preview (docs/design/inline-calc-live-editor-design.md §3.3): the draft
    body text goes in, the span rows come out. The browser never assembles
    the grammar and never learns it -- the same posture as `_source_propose`'s
    "composed and checked here". The pass (`build.preview_inline_spans`)
    mutates nothing: no file, no snapshot state, no diagnostics; the response
    carries spans, text and messages only, so the write routes'
    path-scrubbing contract is satisfied by construction. `fields` is the
    draft's field bag: validated for shape and carried, and unused until the
    field-reference slice (item G1) lands. Unknown keys are ignored, the
    `_apply_edit` posture -- the forward-compat the §3.3 contract names.
    """
    if not isinstance(body, dict):
        return 400, {"error": "expected a JSON object"}
    text = body.get("text")
    if not isinstance(text, str):
        return 400, {"error": "text is required: the draft body as one string"}
    if "fields" in body and not isinstance(body["fields"], dict):
        return 400, {"error": "fields must be an object: the draft's field values"}
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    # The edit affordance is the single source of editability (sealed entry,
    # imported item): a body the author cannot save is a body this route does
    # not evaluate -- "stop the false affordance" (editor.js:45-53), answered
    # with the edit_state reason verbatim.
    state = edit_state(app, project, item)
    if not state["body"]["editable"]:
        return 403, {"error": state["body"]["reason"]}
    spans = build_mod.preview_inline_spans(project, item, text, fields=body.get("fields"))
    payload = {
        # The item's file revision, from the same edit_state the 403 above
        # consulted: the string the form holds as `file_revision` and sends
        # as `expected_revision`, so the browser's stale-response guard
        # (design §3.6) compares like with like -- not the project-wide
        # `/api/revision` revision, which the form does not hold (§3.3).
        "revision": state["file_revision"],
        "spans": spans,
    }
    if len(inline_calc.triggered_spans(text)) > build_mod.PREVIEW_SPAN_LIMIT:
        payload["truncated"] = True
    return 200, payload


def edit_state(app, project: Project, item: Item) -> dict:
    """What the browser may change on this item, and the proof it must send
    back to change it: the content revision of the item's own source file (the
    same spelling `serve.edit.apply_edit` compares), so the form holds a
    revision per item rather than one for the whole project.

    Read-only reasons are spelled out, not implied: a sealed entry, an imported
    item, an identity field, a collection. The UI renders what is here instead
    of reimplementing the rules."""
    rel = (item.source_file or "").replace("\\", "/")
    revision = app.state.snapshot.hashes.get(rel)
    if revision is None:
        revision = edit_mod.file_revision(os.path.join(project.root, rel))

    blocked = None
    if item.external:
        blocked = "imported items are read-only in the editor"
    elif is_sealed(project, item):
        blocked = "a sealed entry is append-only: a correction is a new entry, not this edit"

    spec = project.types.get(item.type)
    fields = {}
    for name in ("id", "key", "type"):
        fields[name] = {
            "editable": False,
            "reason": "identity: id, key and type are not editable in v1",
        }
    for name, value in item.fields.items():
        if name in fields:
            continue
        if blocked:
            fields[name] = {"editable": False, "reason": blocked}
            continue
        fspec = spec.fields.get(name) if spec else None
        ftype = fspec.type if fspec else None
        if name in PROTECTED_FIELDS:
            fields[name] = {
                "editable": False,
                "reason": "identity: id and key are not editable in v1",
            }
        elif ftype in NON_SCALAR_FIELD_TYPES or isinstance(value, (list, dict)):
            fields[name] = {"editable": False, "reason": "not a scalar value: collections are not editable here"}
        else:
            control = "select" if ftype == "enum" and fspec.choices else "text"
            fields[name] = {
                "editable": True,
                "control": control,
                "choices": list(fspec.choices) if control == "select" else None,
                "required": bool(fspec.required) if fspec else False,
                "value_type": _value_type(value),
            }
    # Slice 2's link pickers: one entry per verb the item's type declares,
    # with the target types the schema allows (the UI feeds these to the
    # /api/items filter) and the targets currently written on the item, so
    # the picker can mark them and offer removal without a second request.
    link_verbs = {}
    for verb, allowed in sorted((spec.links if spec else {}).items()):
        if blocked:
            link_verbs[verb] = {"editable": False, "reason": blocked}
            continue
        link_verbs[verb] = {
            "editable": True,
            "target_types": list(allowed),
            "targets": sorted(item.links.get(verb) or []),
        }
    return {
        "file_revision": revision,
        "editable": blocked is None,
        "reason": blocked,
        "fields": fields,
        "links": link_verbs,
        "body": {"editable": blocked is None, "reason": blocked},
    }


def _item_view(app, ref: str) -> tuple[int, dict]:
    project = app.state.snapshot.project
    item, handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    cov = project.coverage.get(item.id) if item.id else None
    spec = project.types.get(item.type)
    return 200, {
        "revision": app.state.snapshot.revision,
        "handle": handle,
        "page": f"{item.slug}.html",
        "key": item.key,
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "board": item.board,
        "workspace": item.workspace,
        "tags": item_tags(item),
        "source_file": item.source_file.replace("\\", "/"),
        "source_line": item.source_line,
        "body": item.body,
        "fields": item.fields,
        "inherited_fields": sorted(item.inherited_fields),
        "external": item.external,
        "origin": item.origin,
        "former_ids": list(item.former_ids),
        "append_only": bool(spec.append_only) if spec else False,
        "sealed": is_sealed(project, item),
        "links": {
            "outgoing": {v: list(t) for v, t in sorted(item.resolved_links.items())},
            "incoming": {v: list(t) for v, t in sorted(item.backlinks.items())},
        },
        "coverage": (
            None
            if cov is None
            else {
                "stage": cov.stage,
                "addressed_by": list(cov.addressed_by),
                "claimed_by": list(cov.claimed_by),
                "satisfied_by": list(cov.satisfied_by),
                "verified_by": list(cov.verified_by),
            }
        ),
        "edit": edit_state(app, project, item),
        "check": check_state(item),
        "checks": [
            {
                "value_name": c.value_name,
                "against": c.against,
                "ok": c.ok,
                "detail": c.detail,
                "actual": c.actual,
            }
            for c in item.checks
        ],
        "diagnostics": _diagnostics_for(project, item, handle),
    }


# ----------------------------------------------------------- reading source files
#
# docs/design/editor-source-picker.md §2, §5, §6, §7 -- Slice A, "the service
# reads", and docs/design/editor-pdf-picker.md §2, §4, §8 -- Slice P-A, the same
# for a PDF's pages. Four GET routes, no writes. Each names one item, and the
# service authorizes the path with `citations.authorize_source_path` -- the same
# call `refdes fetch` and the source resolver make -- so the picker can never be
# authorized for a file the fetcher would refuse. They are added as routes here
# and nowhere else, which is what makes them inherit the launch-token, Host and
# Origin checks every other `/api/` request already passes: no new surface, no
# new security posture, just a new path into the same one.
#
# There is no seal or external-item gate here, and that is deliberate rather
# than forgotten (§9 Q6, recommended A): these are reads, seeing where a value
# came from is review, and the refusal that belongs to a sealed or imported
# item is Accept's -- a body write, already refused by the edit route with the
# existing reason.


def _item_sources(app, ref: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    """`GET /api/item/<ref>/sources` -- the item's own cited files a reader can
    read, each with its pin state and the values already pinned for it."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    try:
        return 200, sources_mod.files_payload(project, item)
    except sources_mod.SourceRefusal as exc:
        # The file list reads the lockfile before it can name any pin state,
        # and an unreadable one refuses the whole answer -- which is a 422 in
        # the same vocabulary the other three source routes already speak.
        return _refused(exc)


def _source_entries(app, ref: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    """`GET /api/item/<ref>/sources/entries?path=&q=` -- the rows of one cited
    file, read live, each labelled with the value the lockfile pins beside it."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    path = (query.get("path") or [""])[0]
    if not path:
        return 400, {"error": "path is required: ?path=<a citation path this item declares>"}
    try:
        return 200, sources_mod.entries_payload(
            project, item, path, (query.get("q") or [""])[0]
        )
    except sources_mod.SourceRefusal as exc:
        return _refused(exc)


def _source_propose(app, ref: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    """`GET /api/item/<ref>/sources/propose?path=&key=&unit=&name=` -- the calc
    line this `(path, key, unit, name)` composes to, composed and checked here
    so the browser never assembles the text and never learns the grammar.
    A PDF pick also supplies page/row/token/sha256; key is initially proposed.
    Its preview and accept use the same confirm and edit contracts."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    pdf_pick = any(field in query for field in ("page", "row", "token"))
    for name in (("path",) if pdf_pick else ("path", "key")):
        if not (query.get(name) or [""])[0]:
            what = "a citation path this item declares" if name == "path" else (
                "a key from the file's key column"
            )
            return 400, {"error": f"{name} is required: ?{name}=<{what}>"}
    try:
        return 200, sources_mod.propose_payload(
            project, item,
            path=(query.get("path") or [""])[0],
            key=(query.get("key") or [""])[0],
            unit=(query.get("unit") or [""])[0],
            name=(query.get("name") or [""])[0],
            page=(query.get("page") or [""])[0],
            row=(query.get("row") or [""])[0],
            token=(query.get("token") or [""])[0],
            sha256=(query.get("sha256") or [""])[0],
        )
    except sources_mod.SourceRefusal as exc:
        return _refused(exc)


def _source_page(app, ref: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    """`GET /api/item/<ref>/sources/page?path=&page=` -- one page of a cited PDF
    as positioned text, its runs grouped into rows, and every number in them as
    a candidate with its column-header guess.

    `page` is optional: without it the page is the one the citation names
    (`page:`, else the page the lockfile resolved for a `section:`), which is
    where the picker opens. The browser receives the runs and their coordinates
    and never a PDF byte (editor-pdf-picker.md §5, option A)."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    path = (query.get("path") or [""])[0]
    if not path:
        return 400, {"error": "path is required: ?path=<a citation path this item declares>"}
    page = (query.get("page") or [""])[0].strip()
    if page and citations_mod.page_number(page) is None:
        # A page is a positive integer or it is not a page this can open, and
        # saying so here is cheaper than opening a document to find out. The
        # test is `citations.page_number` -- the same one that decides whether a
        # `page:` is a declaration error at load, so `?page=0` means the same
        # thing here as `page: 0` does there.
        return 400, {"error": "page must be a positive integer: ?page=<a page number>"}
    try:
        return 200, sources_mod.page_payload(project, item, path, page)
    except sources_mod.SourceRefusal as exc:
        return _refused(exc)


def _refused(exc: sources_mod.SourceRefusal) -> tuple[int, dict]:
    """A read the authorizer, the registry or the row itself refused. 422 with
    the reason verbatim, in the edit route's `refused` vocabulary, because that
    is the shape the browser already knows how to read off an authoring
    outcome -- the request was well-formed; what it asked for is not this
    item's to read."""
    return 422, {"kind": "refused", "ok": False, "error": str(exc), "reason": str(exc)}


# Longest suffix first: `/sources` is a suffix of the other three, and a plain
# `endswith("/sources")` would swallow them.
_SOURCE_ROUTES = (
    ("/sources/entries", _source_entries),
    ("/sources/propose", _source_propose),
    ("/sources/page", _source_page),
    ("/sources", _item_sources),
)


# ------------------------------------------------------------------ the write


def _parse_pins(raw) -> tuple[tuple, str]:
    """The request's `pin` field as `SourcePin`s, or a reason it is not one.

    One pin or a list of them -- an accept is usually one key, and the shape that
    reads best for one should not be a special case of the shape for several.
    Each names a path, a key, and the unit and name of the line that must be in
    the body. A PDF session pick adds page/row/token/sha256; the server derives
    its quote and numeric-token index again. Other fields, a `value` included,
    are ignored because the number comes from the reader (§5).
    """
    if raw is None:
        return (), ""
    entries = raw if isinstance(raw, list) else [raw]
    pins = []
    for entry in entries:
        if not isinstance(entry, dict):
            return (), "pin must be an object with a path and a key, or a list of them"
        for name in ("path", "key"):
            if not isinstance(entry.get(name), str) or not entry.get(name):
                return (), f"pin needs a {name}: the citation path and the source key it pins"
        for name in ("unit", "name", "sha256"):
            if entry.get(name) is not None and not isinstance(entry[name], str):
                return (), f"pin {name} must be a string"
        selection = {}
        for name in ("page", "row", "token"):
            value = entry.get(name, "")
            if not isinstance(value, str) and type(value) is not int:
                return (), f"pin {name} must be an integer or an integer string"
            selection[name] = str(value)
        pins.append(
            edit_mod.SourcePin(
                path=entry["path"],
                key=entry["key"],
                unit=entry.get("unit") or "",
                name=entry.get("name") or "",
                sha256=entry.get("sha256") or "",
                **selection,
            )
        )
    return tuple(pins), ""


def _apply_edit(app, ref: str, body) -> tuple[int, dict]:
    """`POST /api/item/<ref>/edit` -- the HTTP face of `serve.edit.apply_edit`.

    The service decides everything (revision check, seal check, patcher, delta
    gate, atomic write); this only turns its four results into status codes:
    Applied 200, Conflict 409 (with the current span text and the diff),
    Refused 422 (a reason), Invalid 422 (the blocking diagnostics). A malformed
    request -- not an authoring outcome -- is a 400. `who` is `local`: today
    every caller is the same local author, and the seam lives in the service."""
    if getattr(app, "read_only", False):
        return 403, {"kind": "refused", "error": "this server was started with --no-write: edits are disabled"}
    if not isinstance(body, dict):
        return 400, {"error": "expected a JSON object"}

    expected = body.get("expected_revision")
    if not isinstance(expected, str) or not expected:
        return 400, {"error": "expected_revision is required: the file_revision from GET /api/item/<ref>"}

    op_name = body.get("op")
    pins, bad_pins = _parse_pins(body.get("pin"))
    if bad_pins:
        return 400, {"error": bad_pins}
    if op_name == "set_field":
        field = body.get("field")
        value = body.get("value")
        if not isinstance(field, str) or not field:
            return 400, {"error": "set_field needs a field name"}
        if value is None or isinstance(value, (dict, list)):
            return 400, {"error": "set_field takes a scalar value: collections and null are not editable"}
        op = SetField(field, value)
    elif op_name == "set_body":
        text = body.get("text")
        if not isinstance(text, str):
            return 400, {"error": "set_body needs a text string"}
        op = SetBody(text)
    elif op_name in ("add_link", "remove_link"):
        verb = body.get("verb")
        target = body.get("target")
        if not isinstance(verb, str) or not verb:
            return 400, {"error": f"{op_name} needs a verb"}
        if not isinstance(target, str) or not target:
            return 400, {"error": f"{op_name} needs a target: an item handle, display id or key"}
        op = AddLink(verb, target) if op_name == "add_link" else RemoveLink(verb, target)
    else:
        return 400, {"error": "op must be 'set_field', 'set_body', 'add_link' or 'remove_link'"}
    if pins and op_name != "set_body":
        # Not a refusal, and not a silent drop either: a pin has nowhere to live
        # without a body naming it, and saving the body separately would be the
        # half-commit §4 exists to prevent.
        return 400, {"error": "pin is only accepted on op 'set_body': a source value is pinned by the body that names it"}

    project = app.state.snapshot.project
    result = edit_mod.apply_edit(
        project.root,
        edit_mod.EditRequest(
            who="local", ref=ref, op=op, expected_revision=expected, pins=pins
        ),
        # The launch's own settings file, so an edit against a project served
        # from `-c custom-project.yaml` loads the file the model was built
        # from instead of rebuilding the default marker's path from the root.
        config_path=app.state.config_path,
    )

    def shown(path):
        """Project-relative when possible: the browser has no use for a server
        filesystem root, and a path it cannot read is a path it cannot leak."""
        if not path:
            return None
        text = os.path.relpath(path, project.root).replace("\\", "/")
        return path.replace("\\", "/") if text.startswith("..") else text

    if isinstance(result, edit_mod.Applied):
        # The design's "full rebuild after save": the model and the preview
        # come back from the same refresh the file watcher uses, so the next
        # GET and the rendered site both show the saved bytes.
        app.state.refresh()
        return 200, {
            "kind": "applied",
            "ok": True,
            "message": result.message,
            "path": shown(result.path),
            "revision": result.revision,
            "describe": result.plan.describe(),
            # The item's CURRENT display id and live handle. When the edit was
            # posted under a retired id these differ from the URL's ref, which
            # is exactly the correction the browser needs to make (EDIT-03).
            "id": result.item_id,
            "handle": result.handle,
            # What the reader read and the lockfile now pins, for an accept.
            # Nothing here came from the request: a `value` sent by the client is
            # ignored, which is the point (§5 -- one parser of a source file).
            "pinned": [dict(entry) for entry in result.pinned],
            "diagnostics": [diag_dict(d) for d in result.diagnostics if d.level != CHECK_VIOLATION],
        }
    if isinstance(result, edit_mod.Conflict):
        return 409, {
            "kind": "conflict",
            "ok": False,
            "message": result.message,
            "path": shown(result.path),
            "expected_revision": result.expected_revision,
            "current_revision": result.current_revision,
            "current_text": result.current_text,
            "diff": result.diff,
        }
    if isinstance(result, edit_mod.Invalid):
        return 422, {
            "kind": "invalid",
            "ok": False,
            "message": result.message,
            "reason": result.message,
            "path": shown(result.path),
            "diagnostics": [diag_dict(d) for d in result.diagnostics],
        }
    return 422, {
        "kind": "refused",
        "ok": False,
        "message": result.message,
        "reason": result.reason,
        "path": shown(result.path),
    }


# ---------------------------------------------------------------- creation


def _create_schema(app) -> tuple[int, dict]:
    """What a New Item form needs, answered from the resolved schema: every
    declared type with its prefix, whether it is append-only (the amend
    flow), whether it declares `amends`, its fields with control-relevant
    metadata, and the project's boards/workspaces/date_format. The client
    interprets nothing it is not told here."""
    project = app.state.snapshot.project
    types = []
    for name, spec in sorted(project.types.items()):
        fields = {}
        for fname, fspec in spec.fields.items():
            fields[fname] = {
                "type": fspec.type,
                "required": bool(fspec.required),
                "choices": list(fspec.choices) if fspec.type == "enum" else None,
                "default": fspec.default,
                "creatable": fspec.type not in NON_SCALAR_FIELD_TYPES,
            }
        types.append(
            {
                "name": name,
                "prefix": spec.prefix,
                "label": spec.label,
                "append_only": bool(spec.append_only),
                "amends": "amends" in spec.links,
                "fields": fields,
            }
        )
    return 200, {
        "types": types,
        "boards": list(project.boards),
        "workspaces": list(project.workspaces),
        "date_format": project.date_format,
    }


def _create_preview(app, query: dict[str, list[str]]) -> tuple[int, dict]:
    """The id that WOULD be minted and the destination that WOULD be used,
    planned purely (serve.edit.preview_creation) -- nothing is reserved.

    A `workspace` scope must name a registered workspace, checked with the
    list route's own facet rule: `/api/items?workspace=ghost` is a 400 naming
    the value and the registered ones, and the preview refuses the same way
    (run-9 R9-F3). It used to ignore the unknown name and fall back to the
    unscoped suggestion -- a 200 pointing into some other workspace's tree,
    silently. `board` gets the same check (run-11 R11-F4, the parameter right
    next to the one #326 fixed): `/api/items?board=ghost` refuses it from
    `parse_filters`, and the preview answered 200 with a suggestion nothing
    in the project pointed at. The create form offers only registered values
    of both, so both gates are the direct-caller path."""
    project = app.state.snapshot.project
    type_name = (query.get("type") or [""])[0]
    if not type_name:
        return 400, {"error": "type is required: ?type=<declared type>"}
    board = (query.get("board") or [""])[0] or None
    workspace = (query.get("workspace") or [""])[0] or None
    explicit = (query.get("id") or [""])[0] or None
    destination = (query.get("destination") or [""])[0] or None
    if workspace is not None:
        try:
            validate_facet(project, "workspace", workspace)
        except FilterError as exc:
            return exc.status, {"error": str(exc)}
    if board is not None:
        # The R9-F3 gate's sibling parameter (run-11 R11-F4): the same
        # check as above, so `board` is refused here exactly as
        # `/api/items?board=` refuses it -- same call, same message shape.
        try:
            validate_facet(project, "board", board)
        except FilterError as exc:
            return exc.status, {"error": str(exc)}
    return 200, edit_mod.preview_creation(
        project,
        type_name,
        explicit_id=explicit,
        board=board,
        workspace=workspace,
        destination=destination,
    )


def _create_item(app, body) -> tuple[int, dict]:
    """`POST /api/items/create` -- the HTTP face of `serve.edit.create_item`.
    Same result-to-status mapping as the edit route: Created 200, Refused and
    Invalid 422, malformed request 400."""
    if getattr(app, "read_only", False):
        return 403, {
            "kind": "refused",
            "error": "this server was started with --no-write: creation is disabled",
        }
    if not isinstance(body, dict):
        return 400, {"error": "expected a JSON object"}
    type_name = body.get("type")
    if not isinstance(type_name, str) or not type_name:
        return 400, {"error": "type is required: a declared item type"}
    fields = body.get("fields", {})
    if not isinstance(fields, dict):
        return 400, {"error": "fields must be an object"}
    for key_name in ("id", "destination", "amends"):
        value = body.get(key_name)
        if value is not None and not isinstance(value, str):
            return 400, {"error": f"{key_name} must be a string when given"}
    # `links`: verb -> one or more target refs. Whether the verb is declared
    # and whether each target resolves to a linkable item is the create
    # service's call, under the write lock, against the state it is about to
    # write -- this only refuses what could not be a request at all, the same
    # split as `fields` above.
    links_body = body.get("links", {})
    if not isinstance(links_body, dict):
        return 400, {"error": "links must be an object mapping link verbs to lists of targets"}
    for verb, targets in links_body.items():
        if not isinstance(verb, str) or not verb:
            return 400, {"error": "links keys must be link verb names"}
        if not isinstance(targets, list) or not targets:
            return 400, {"error": f"links {verb!r} must be a non-empty list of target refs"}
        if not all(isinstance(target, str) and target for target in targets):
            return 400, {"error": f"links {verb!r} takes its target refs as strings"}

    project = app.state.snapshot.project
    # An empty `id` reads as "not given" -- exactly what `_create_preview`
    # makes of `?id=`: an empty id box previews the next free id, so the
    # POST that saves that preview must not die on the empty string it
    # carried. The collapse is spelled `== ""` and not `or None` on purpose:
    # the loop above already refuses a non-string `id` as a 400, so a falsy
    # JSON value (0, false, []) can never reach this line as an "empty"
    # auto, and a reordering that ever moved the shape gate upstream must
    # not silently turn a malformed explicit id into one. A malformed id
    # that is not empty ("  ", "not-an-id") still reaches the id layer and
    # is refused there, on both routes alike.
    explicit_id = body.get("id")
    result = edit_mod.create_item(
        project.root,
        edit_mod.CreateRequest(
            who="local",
            type=type_name,
            fields=fields,
            id=None if explicit_id == "" else explicit_id,
            destination=body.get("destination"),
            amends=body.get("amends"),
            links=links_body,
        ),
        # Same threading as the edit route above: the configured settings file,
        # not a path rebuilt from the default marker name.
        config_path=app.state.config_path,
    )

    def shown(path):
        if not path:
            return None
        text = os.path.relpath(path, project.root).replace("\\", "/")
        return path.replace("\\", "/") if text.startswith("..") else text

    if isinstance(result, edit_mod.Created):
        app.state.refresh()
        return 200, {
            "kind": "created",
            "ok": True,
            "message": result.message,
            "id": result.item_id,
            "key": result.key,
            "type": result.type,
            "path": shown(result.path),
            "revision": result.revision,
        }
    if isinstance(result, edit_mod.Invalid):
        return 422, {
            "kind": "invalid",
            "ok": False,
            "message": result.message,
            "reason": result.message,
            "path": shown(result.path),
            "diagnostics": [diag_dict(d) for d in result.diagnostics],
        }
    return 422, {
        "kind": "refused",
        "ok": False,
        "message": result.message,
        "reason": result.reason,
        "path": shown(result.path),
    }


# ---------------------------------------------------------------- image picker
#
# docs/design/editor-image-upload.md §17, Phase 0: list the images the project
# already has so the author can reference one, and nothing else. Read-only --
# no upload, no write endpoint, no bytes accepted -- and the reference the
# author picks travels out through the ordinary `set_body` save like any other
# body edit (the client inserts it into the draft; design §7).
#
# What the list can name is decided by the build, not here. `state.asset_files`
# is the walk `project_inputs` already watches and `build.collect_static_assets`
# already publishes: every file under a declared `site.assets:` directory, with
# no reference needed, because a bare `<img src>` is resolved by searching those
# directories (`build._search_image_src`). So a file this endpoint can offer is a
# file the build can already resolve, and one it cannot offer was never
# reachable by a reference in the first place.
#
# The bytes come from the preview surface rather than a new read endpoint: a
# file under a declared asset directory is identity-mapped in `project.assets`
# (`collect_static_assets`), so the build's own answer for it is `assets/<rel>`
# in the current generation, and the existing `/preview/` route serves that with
# `PreviewManager.open_file`'s real-path containment, the session cookie,
# `nosniff`, and `PREVIEW_CSP` (docs/design/browser-editor.md, Security: no
# generic file-read endpoint; design §16.10, whose "unnecessary: the preview
# generation already serves the asset" holds here too). The client names no
# path, so there is no client path to confine.

# The image file types the picker offers. This is a *display* filter on the walk
# above, not a resolution rule: the build resolves a src by exact filename with
# no extension test at all (`build._process_images`), so a file outside this set
# is still perfectly valid to reference by hand -- the picker just does not
# volunteer it. SVG is listed, not refused, for the same reason: refusing it is
# an upload-side policy decision (design §6, about bytes arriving from a
# browser), and this endpoint accepts no bytes and reads none.
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff", ".avif", ".ico"}
)


def image_alt(name: str) -> str:
    """Default alt text for a picked image: the filename's stem, never empty
    (design §7 -- an empty `alt` is a silent accessibility failure). Brackets
    are escaped because the stem lands inside `![...]`."""
    stem = name.rsplit(".", 1)[0] if "." in name.lstrip(".") else name
    return (stem or name).replace("[", "\\[").replace("]", "\\]").replace("\n", " ").strip() or name


def image_markdown(src: str, alt: str) -> str:
    """The exact `![alt](src)` line the client inserts, composed here so the
    browser never builds a path spelling of its own. A destination containing a
    space or a parenthesis takes markdown's `<...>` form, which is what makes a
    file called `thermal curve.png` insertable at all."""
    target = f"<{src}>" if any(ch in src for ch in " ()<>") else src
    return f"![{alt}]({target})"


def referenceable(src: str) -> bool:
    """Whether the build could resolve `src` exactly as written.

    Markdown's renderer percent-encodes a destination it does not consider
    URL-safe, and the build decodes only the HTML attribute entities
    markdown-it's escaper emitted (`build.image_src_from_html`), never a
    percent-escape, so a file whose name carries a space or a non-ASCII
    character cannot be referenced by any spelling: `![a](<figures/thermal
    curve.png>)` renders a src of `figures/thermal%20curve.png` and the
    lookup misses. Rather than hand the author a reference the save would
    refuse, the picker reports the file and says why it is not offerable.

    `&` is the one rewrite the build undoes: the renderer escapes it to
    `&amp;` in the attribute, `image_src_from_html` decodes exactly that, so
    a name like `a&b.png` resolves and is offerable.

    `quote(src, safe="/&") == src` is the conservative direction: the
    renderer's encoder is narrower than `quote`, so a name refused here can
    still work when typed by hand (`a(b).png`, `a#b.png`), while a name
    accepted here is one no encoder rewrites beyond the `&amp;` the build
    decodes back."""
    return urllib.parse.quote(src, safe="/&") == src


def _image_row(project: Project, item: Item, full_path: str) -> dict | None:
    """One row of `GET /api/images`, or None when the file is not an image the
    picker offers. `rel` is the build's own project-relative spelling and `src`
    is that path as this item's source file must spell it -- the relative lookup
    that runs first and always wins (docs/markdown.md), so the inserted text
    resolves to this exact file whatever else shares the leaf name."""
    rel = os.path.relpath(full_path, project.root).replace("\\", "/")
    name = rel.rpartition("/")[2]
    if os.path.splitext(name)[1].lower() not in IMAGE_SUFFIXES:
        return None
    source_dir = os.path.join(project.root, os.path.dirname(item.source_file.replace("\\", "/")))
    src = os.path.relpath(os.path.join(project.root, rel), source_dir).replace("\\", "/")
    try:
        size = os.path.getsize(full_path)
    except OSError:
        size = 0
    alt = image_alt(name)
    row = {
        "rel": rel,
        "name": name,
        "alt": alt,
        "bytes": size,
        "src": src,
        "insertable": referenceable(src),
    }
    if row["insertable"]:
        row["markdown"] = image_markdown(src, alt)
    else:
        row["note"] = (
            "this filename cannot be referenced as written: markdown "
            "percent-encodes it and the build resolves the encoded form. It "
            "needs renaming before any body can point at it."
        )
    dest = project.assets.get(rel)
    if dest:
        # The build's own answer, not a guess: a declared asset-directory file
        # is identity-mapped, so this is the file the preview already serves.
        row["thumb"] = "/preview/assets/" + urllib.parse.quote(dest)
    return row


def _images(app, ref: str) -> tuple[int, dict]:
    """`GET /api/images?item=<handle>` -- the picker's list.

    Item-scoped because the answer depends on the item: a src is relative to
    *that* item's source file, and only the item's own draft can receive the
    insertion. An unknown item 404s like `_item_view`; an item with no source
    file has no base to be relative to and says so rather than guessing a root."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    if not item.source_file:
        return 400, {"error": "this item has no source file, so no relative path to offer"}
    rows = [
        row
        for row in (_image_row(project, item, path) for path in state_mod.asset_files(project))
        if row is not None
    ]
    rows.sort(key=lambda row: row["rel"])
    return 200, {
        "item": item.id or ref,
        "source_file": item.source_file.replace("\\", "/"),
        "asset_dirs": list(project.asset_dirs),
        "images": rows,
        "total": len(rows),
    }


# ------------------------------------------------------------------ upload
#
# docs/design/editor-image-upload.md §17 Phase 1 "Bytes" and Phase 2
# "Conflicts": `POST /api/assets`. The upload endpoint writes bytes and returns
# a path; it never touches any body (§7) -- the reference reaches disk through
# the ordinary `set_body` save, with the ordinary revision check and delta
# gate. The ordering upload-then-save is forced by the gate (§2), not chosen.
# The service rules -- destination and name validation, sniffed type, the §5
# collision table, the atomic create and replace, and the three §9 checks
# against other documents -- live in `serve/upload.py`; this is the HTTP face,
# mapping results to statuses like `_apply_edit` and `_create_item` do.
#
# `expected_hash` (§8) is the binary `expected_revision`: the hash the last
# response returned, re-issued to say "yes, replace this exact version". A hash
# that no longer matches comes back as a 409 carrying the *current* hash, so a
# client can re-fetch and decide again without guessing.
#
# Phase 3 ("Seals") is here too: the request's `item` is passed to `store_asset`
# so a sealed target is refused under the write lock before any byte is written,
# and a replace or a create that would change what a sealed entry displays comes
# back as a 422 `refusal: "sealed"` naming the sealed item, not as a confirmable
# 409. The item view already carries `sealed` and `edit.editable: false` for the
# client to grey the control out with (Phase 4); the endpoint does not rely on it.


def _upload_asset(app, query: dict[str, list[str]], body) -> tuple[int, dict]:
    """`POST /api/assets?dest=<dir>&name=<file>`, or `item=<handle>` to
    default the destination to that item's own source directory (§4), with
    the raw bytes as the request body (§11: raw bytes, not multipart, not
    base64; metadata only in the query). The response carries `from_source`
    -- `rel` rewritten relative to the item's source file -- because that is
    the exact spelling the client inserts into the draft (§7).

    An `item` that is sealed is refused outright (§10), whether or not `dest`
    was given as well: the upload is for that entry, and its body can never
    carry the reference."""
    if getattr(app, "read_only", False):
        return 403, {
            "kind": "refused",
            "error": "this server was started with --no-write: uploads are disabled",
        }
    if not isinstance(body, bytes):
        return 400, {"error": "expected raw request bytes"}
    name = (query.get("name") or [""])[0]
    dest = (query.get("dest") or [""])[0]
    item_ref = (query.get("item") or [""])[0]
    expected_hash = (query.get("expected_hash") or [""])[0]
    project = app.state.snapshot.project

    item = None
    if item_ref:
        item, _handle = _find_item(project, item_ref)
        if item is None:
            return 404, {"error": f"no item matches {item_ref!r}"}
    if not dest:
        if item is None:
            return 400, {
                "error": "dest is required when no item is given: the upload writes beside something"
            }
        if not item.source_file:
            return 400, {
                "error": "this item has no source file, so there is no directory beside it to write to"
            }
        dest = posixpath.dirname(item.source_file.replace("\\", "/"))

    result = upload_mod.store_asset(
        project,
        dest=dest,
        name=name,
        data=body,
        expected_hash=expected_hash,
        # §10: the item this upload is for, not just the directory it implies. A
        # sealed target is refused inside `store_asset`, under the write lock,
        # before any byte is written.
        item=item,
    )

    if isinstance(result, upload_mod.Uploaded):
        # §12: force the rebuild now rather than wait for the debounced
        # two-tick poller -- the author is about to look at the preview to
        # decide whether the file just dropped is the one they meant. An
        # upload into a declared `site.assets:` directory is a semantic
        # input (§15.1), so refresh() rebuilds the model and the generation;
        # an upload beside the source is not an input until a body
        # references it (§7's orphan), and refresh() is a correct no-op
        # there. The poller stays the backstop for files the editor did not
        # write.
        app.state.refresh()
        source_dir = (
            posixpath.dirname(item.source_file.replace("\\", "/"))
            if item is not None and item.source_file
            else None
        )
        from_source = (
            posixpath.relpath(result.rel, source_dir) if source_dir is not None else result.rel
        )
        return 200, {
            "kind": "uploaded",
            "ok": True,
            "message": result.message,
            "rel": result.rel,
            "from_source": from_source,
            "hash": result.digest,
            "bytes": result.size,
            "created": result.created,
            # §8 row 1, §9.3: a replace changed what these items show. The
            # disclosure is the confirmation's other half -- not a second
            # modal, but not something to discover afterwards either.
            "replaced": result.replaced,
            "referenced_by": list(result.referenced_by),
        }
    if isinstance(result, upload_mod.Conflict):
        return 409, {
            "kind": "conflict",
            "ok": False,
            "error": result.reason,
            "message": result.reason,
            "path": result.rel,
            # Which of §5's collision and §8's hash check said no, and the
            # hash a re-issue must carry: a client that has to branch on this
            # should not have to parse the message to find out.
            "conflict": result.kind,
            "current_hash": result.current_hash,
            "current_size": result.current_size,
            # §9.3: the blast radius of the replace the author is about to
            # confirm, named before they confirm it.
            "referenced_by": list(result.referenced_by),
        }
    return result.status, {
        "kind": "refused",
        "ok": False,
        "error": result.reason,
        "message": result.reason,
        "reason": result.reason,
        # "ambiguity" (§9.1) and "capture" (§9.2) name the two checks against
        # other documents, each with its own way out; everything else is a
        # plain refusal of this request.
        "refusal": result.kind,
        "details": list(result.details),
    }
