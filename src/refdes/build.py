"""Turn parsed items into a resolved, evaluated, validated project."""

from __future__ import annotations

import difflib
import errno
import hashlib
import html as html_entities
import itertools
import json
import os
import re
import stat
import threading
from collections.abc import Iterator

import yaml
from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml

from . import blocked as blocked_mod
from . import blocks as blocks_mod
from . import boards as boards_mod
from . import calc, dates, imports, inline_calc, seal
from . import chains as chains_mod
from . import citations as citations_mod
from . import docs_url as docs_url_mod
from . import history as history_mod
from . import ids as ids_mod
from . import keys as keys_mod
from . import nav as nav_mod
from . import navis as navis_mod
from . import pages as pages_mod
from . import status_links as status_links_mod
from . import workspaces as workspaces_mod
from .model import (
    CHECK_VIOLATION,
    ERROR,
    INFO,
    INLINE_CALC_STALE,
    INVALIDATE,
    NON_SCALAR_FIELD_TYPES,
    RETIRED_UNIT_SPELLING,
    TASK_STATES,
    WARNING,
    CalcLine,
    CheckResult,
    Coverage,
    Item,
    ItemType,
    Project,
    is_subtype,
)

# Explicit reference: [[REQ-PWR-002]] or [[REQ-PWR-002|the input range]]. The
# ':' admits the "fig:" namespace (docs/design/index-blocks.md §9) -- item ids
# are allocated as PREFIX-BOARD-NNN and never contain one, so this only ever
# matches the new namespace on real projects, never an existing item id. The
# optional '#field' fragment (finding 19 Part A) links to one field's row on
# the target item's page; it is never inlined, and a composite `ID@key` target
# is not admitted here because those only ever appear in structured link
# fields, never in prose (docs/design/keys.md).
# The fragment may instead be `calc:<name>` (docs/design/named-calc-blocks.md
# §5.3), which links to that named block's table on the target's page. A colon
# is admitted in the fragment at most once. `calc:` is the only namespace
# defined, and field names never contain a colon, so any other `a:b` is a
# typo'd namespace -- `field_anchor` reports it by name rather than letting it
# fall through to the field check or reach the page as literal text (the same
# "silently-ignored author intent is the failure" call §3.4 makes for the
# fence line).
EXPLICIT_REF_RE = re.compile(
    r"\[\[\s*([A-Za-z0-9\-_:]+)(?:#([A-Za-z0-9_\-]+(?::[A-Za-z0-9_\-]+)?))?\s*"
    r"(?:\|\s*([^\]]+?)\s*)?\]\]"
)
# The one namespaced fragment this project defines. A bare `#losses` would land
# in the same namespace as schema-declared field names and have to be resolved
# by a precedence rule nobody reading the page can see (§5.3).
CALC_FRAGMENT_PREFIX = "calc:"
# Bare reference: REQ-PWR-002 appearing in prose.
BARE_REF_RE = re.compile(r"(?<![\w\-/])([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{1,6})(?![\w\-])")
# Inline calc value: {{P_diss}}, optionally presented in another unit:
# {{P_diss | mW}}. The unit group accepts everything a `| unit` annotation
# accepts; a wrong dimension is an error at the reference site.
INLINE_VALUE_RE = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s*\|\s*([^{}|]+?))?\s*\}\}"
)
# Regions of rendered HTML where references must not be linkified.
#
# `<pre>`/`<code>` because a code sample is text *about* ids, not ids in prose.
# `<a>` for the same reason with a sharper edge: the only markup that reaches
# `_linkify` already carrying anchors is a generated block that reuses another
# page's markup -- `{{tree}}` ships `tree.render_tree_html`'s output, which is
# the same HTML `tree.html` shows, with every item id already the text of an
# `<a class="ref">`. Re-wrapping those produced
# `<a class="ref" href="g.html" data-ref="<a class="ref" ...>ID</a>`, an anchor
# start tag inside another anchor start tag, with a fragment of markup in
# `data-ref`. Non-greedy, because an anchor cannot contain another element and
# an unclosed `<a>` is not something this pipeline can produce.
PROTECTED_RE = re.compile(
    r"<pre\b[\s\S]*?</pre>|<code\b[\s\S]*?</code>|<a\b[\s\S]*?</a>", re.IGNORECASE
)
# `<img src="...">` as markdown-it emits it -- html is off, so this only ever comes
# from `![alt](src)`, never from a literal tag the author typed. Three groups so a
# rewrite can replace just the URL and leave the rest of the tag untouched.
IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.IGNORECASE)
# A URL (has a scheme) or protocol-relative reference: not ours to validate.
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:|^//")


# ---------------------------------------------------------------- image src canon
#
# One canonical spelling of an image `src`, shared by the hash pass and the
# render pass (IMAGE-ASSET-002). The canonical form is the **markdown-it token
# src**: the authored URL as the parser recorded it, mdurl-normalised
# (percent-escaped), before any HTML-attribute escaping. The hash pass reads
# exactly that (`child.attrGet("src")`), and it is the spelling the filesystem
# is named in. The render pass cannot: `_process_images` scans *rendered*
# HTML, where markdown-it's renderer has escaped the attribute value with
# `escapeHtml` (`& < > "` -> `&amp; &lt; &gt; &quot;`). Resolving the escaped
# spelling against the filesystem is the bug: `![a](a&b.png)` renders
# `src="a&amp;b.png"`, which names no file, so the build errored on and
# unpublished an image its own content hash had already recorded.
#
# The pair below is the exact inverse of markdown-it's own escaper -- decode
# the four entities it emits, in reverse order of its escape order (the
# `&amp;` decode last, so `&amp;lt;` round-trips to `&lt;`, never to `<`).
# `html.unescape` is NOT this: it decodes every named and numeric entity,
# which over-decodes srcs that literally contain `&not;` or `&#38;` and
# breaks the round-trip. Importing `escapeHtml` from markdown-it (rather than
# re-typing the four replacements) keeps the encode side literally the
# function that produced the render pass's input, so the pair cannot drift
# from it: `image_src_from_html(escapeHtml(x)) == x` for every token src `x`.

_IMG_ATTR_ENTITIES = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&amp;", "&"))


def image_src_from_html(src: str) -> str:
    """The canonical src behind an `<img src="...">` attribute value taken
    from rendered HTML: markdown-it's attribute escaping, decoded. Feed the
    result to the shared resolvers (`_local_image_path`, `_search_image_src`,
    the `_URL_SCHEME_RE` skip) -- never the raw attribute text -- so the
    render pass resolves the identical string the hash pass hashed."""
    for entity, char in _IMG_ATTR_ENTITIES:
        src = src.replace(entity, char)
    return src


def image_src_to_html(src: str) -> str:
    """The renderable attribute value for a canonical src: markdown-it's own
    escaper, so the rewritten page spells the src exactly the way the render
    pass's input was spelled before the swap -- a browser decoding the
    attribute reaches the real asset filename."""
    return escapeHtml(src)
# A whole paragraph that is nothing but one image immediately followed by a
# Quarto-style attribute suffix: `![alt](src){width=60% caption="..."}`. Anything
# else -- no suffix, other text in the paragraph -- is left completely alone.
FIGURE_RE = re.compile(
    r'<p>\s*(<img\b[^>]*?>)\s*\{([^{}]*)\}\s*</p>', re.IGNORECASE
)
# The same suffix on an image that is *not* alone in its paragraph -- inline
# with text, in a list item, in a table cell. There is no `<figure>` here to
# carry a width, caption, or number, so `width=` goes on the `<img>` itself and
# the rest of the suffix is dropped with a warning: what must never happen is
# the author's markup reaching the page as literal text. Braces with no `=` in
# them (`the set {a, b}`) are prose, not a suffix, and pass through untouched.
INLINE_FIGURE_RE = re.compile(r'(<img\b[^>]*?>)\s*\{([^{}]*)\}', re.IGNORECASE)
FIGURE_ATTR_RE = re.compile(r'([A-Za-z_][\w-]*)\s*=\s*(?:"([^"]*)"|(\S+))')
# The attribute names an image suffix understands, in either position. Anything
# else is a typo waiting to be reported, not a thing to ignore quietly.
IMAGE_ATTR_NAMES = ("width", "caption", "id")
IMG_ALT_RE = re.compile(r'\balt="([^"]*)"', re.IGNORECASE)
# A resolved figure's number, filled in once the whole rendered document is
# known (docs/design/index-blocks.md §9) -- emitted by _apply_figure_attrs,
# consumed by resolve_figures.
FIG_NUM_MARKER_RE = re.compile(r'<span class="fig-num" data-fig="([^"]*)"></span>')
# A `[[fig:id]]` reference, deferred the same way: the id's existence anywhere
# in the project, and whether it lands in *this* rendered document, both
# depend on state that isn't complete until every item and page has been
# processed. Context is smuggled through as data attributes so the deferred
# warning can still be attributed to the line that wrote the reference.
FIG_REF_PENDING_RE = re.compile(
    r'<span class="fig-ref-pending" data-fig="([^"]*)" data-label="([^"]*)"'
    r' data-where-file="([^"]*)" data-where-line="([^"]*)" data-where-id="([^"]*)"></span>'
)
# A declared citation `id:` (finding 19 Part B) -- the same character set
# EXPLICIT_REF_RE's own id group admits, so anything this rejects could never
# be addressed by `[[cite:id]]` in the first place. Unlike a figure's `id=`
# attribute, which is never format-checked and can end up silently
# unreferenceable, a citation id is rejected outright at declaration time
# instead of accepted and left permanently unreachable.
CITATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ----------------------------------------------------------------------- validation


def _required_when_satisfied(item: Item, condition: dict[str, object]) -> bool:
    """All condition keys AND together; a key's own value(s) OR together.

    The reserved key "links" checks whether the item declares at least one
    target under any of the named links; every other key names a sibling field
    and matches against its current value. See
    docs/design/standard-library.md §2 and §11.
    """
    for key, raw_values in condition.items():
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        if key == "links":
            if not any(item.links.get(str(name)) for name in values):
                return False
        elif item.fields.get(key) not in values:
            return False
    return True


def _format_required_when(condition: dict[str, object]) -> str:
    clauses = []
    for key, raw_values in condition.items():
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        if key == "links":
            joined = " or ".join(repr(str(v)) for v in values)
            clauses.append(f"it has a link under {joined}")
        else:
            joined = " or ".join(repr(v) for v in values)
            clauses.append(f"{key} is {joined}")
    return " and ".join(clauses)


def _page_remedy(value: object) -> str:
    """The one sentence that says what to write instead, for the two shapes of
    a refused `page:` where the rule alone leaves the user stuck.

    Finding F2 of `in-prog-logs/user-sim-release-gate-run4.md`: this is the
    only diagnostic in the page-`#fragment` delta that stops at naming the rule,
    and it is the only *breaking* change in it, so it is the first thing an
    upgrading project meets. Two of the refused shapes are not typos the reader
    can see -- someone who wrote `2-4` or `xiv` believes they have cited
    something, and needs to be told the shape that citation takes instead:

    - A **range** has no representation. One entry names one page, so a span is
      one entry per page for the same path (verified: two entries for one
      `path:`, one page each, build clean). Not `section:` -- a section title
      resolves to the single page it starts on, which is the answer for a
      heading that moves between revisions, not for a span.
    - A **printed page number** -- a book's front matter is numbered in roman
      numerals, which is why `xiv` is the common one -- is not a page index.
      The rendered `#page=N` fragment opens the PDF's own sheet, counted from
      1 (docs/markdown.md, `## Citing a section by name`). A value with no
      digits at all is a word or a printed label, never a number that could be
      counted, and one wording covers both.

    Every other refused shape (`0`, `-1`, `1.5`, `9 9`, an empty string) *is*
    fully answered by the rule, so it gets no sentence here: this fires once per
    bad `page:`, and a remedy that restates the rule back at the user is noise
    on the shapes the rule already covers.
    """
    text = str(value).strip()
    if not text:
        return ""
    if re.fullmatch(r"\d+\s*[-\u2010\u2013\u2014]\s*\d+", text):
        return (
            " One entry names one page, so a range is one entry per page for"
            " the same path."
        )
    if not any(ch.isdigit() for ch in text):
        return (
            " A printed page number is not a page index: page: counts the"
            " PDF's own sheets from 1, the same number the rendered link"
            " opens."
        )
    return ""


def _field_error(project: Project, item: Item, fname: str, message: str) -> None:
    """Finding 6: a `defaults:` block is merged into every item in its file
    unconditionally, regardless of whether the item overrode `type:` to
    something the value doesn't apply to (`status: active` from a file's
    `requirement` defaults, merged onto a `component` entry whose own status
    vocabulary is `candidate`/`selected`/`obsolete`). When the failing value
    is one `item` never wrote itself, say so and point at the `defaults:`
    block instead of reporting it identically to a value the item actually
    typed -- `defaults_line` is only ever unset when the file has no
    `defaults:` at all, which is also exactly when a field can't be
    inherited, so the two conditions can only ever agree.
    """
    if fname in item.inherited_fields and item.defaults_line is not None:
        project.error(
            f"{message} -- inherited from this file's defaults:, not set on "
            f"{item.id or 'this item'} itself; defaults: doesn't apply to "
            f"every value once an item overrides type:",
            file=item.source_file, line=item.defaults_line, item_id=item.id,
        )
    else:
        project.error(
            message, file=item.source_file, line=item.source_line, item_id=item.id,
        )


# One fenced code block in a raw markdown body (fence run of 3+, any info
# string, closed by a line that is just the opening fence run again) --
# `iter_yaml_fences` walks these. Scanning fence-by-fence (not regex-matching
# yaml openers) is the point: a fence *inside* an open fence is that fence's
# content, never a fence of its own, so a ```yaml example escaped by an outer
# ```text fence is literal text and not scanned (R10-F4). An unterminated
# fence likewise swallows the rest of the body, exactly as markdown renders
# it. Mirrors blocks._RAW_FENCE_RE's fence recognition (same closer rule).
_FENCE_LINE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^\n]*)$")
# The fence's language tag, narrowed to the two yaml spellings -- a tag that
# continues into a word character or hyphen (`yaml-lens`) is not yaml.
_YAML_TAG_RE = re.compile(r"(?:yaml|yml)(?![\w-])", re.IGNORECASE)
# A markdown blockquote marker (R10-F3): `> ```yaml ... > ``` in an item body
# renders as a *real* code block (the build emits
# `<blockquote><pre><code class="language-yaml">`), so markers are stripped
# line-wise before the fence walk. One line in, one line out: line numbers
# are untouched, so a match's offset is still the source line.
_QUOTE_MARKER_RE = re.compile(r"^[ \t]*(?:>[ \t]?)+")

# `id`/`type` are meaningful front-matter keys (parse.py's RESERVED: the
# front matter is what picks an item's identity and type), so a body fence
# declaring them is the same inert trap as a field fence (R10-F2).
_INERT_META_KEYS = ("id", "type")


def iter_yaml_fences(body: str) -> list[tuple[int, str]]:
    """(0-indexed opener line, fence content) for every top-level
    ```yaml/```yml fence in a raw markdown body, blockquote markers
    stripped. Content of an open fence is never re-scanned as a fence."""
    lines = [
        _QUOTE_MARKER_RE.sub("", line, count=1) for line in body.split("\n")
    ]
    fences: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        opener = _FENCE_LINE_RE.match(lines[i])
        if opener is None:
            i += 1
            continue
        run, rest = opener.group(1), opener.group(2)
        tag = rest.strip().split(maxsplit=1)[0] if rest.strip() else ""
        is_yaml = bool(_YAML_TAG_RE.fullmatch(tag))
        # Same closer rule as blocks._RAW_FENCE_RE: a line that is just the
        # opening fence run again (whitespace around it, nothing after).
        closer = re.compile(r"^[ \t]*" + re.escape(run) + r"[ \t]*$")
        j = i + 1
        while j < len(lines) and not closer.match(lines[j]):
            j += 1
        if j < len(lines):
            if is_yaml:
                fences.append((i, "\n".join(lines[i + 1:j])))
            i = j + 1
        else:
            i = len(lines)  # unterminated fence: the rest is its content
    return fences


def declares_inert_keys(
    body: str, field_names, link_names=()
) -> list[tuple[int, dict[str, list[str]]]]:
    """(0-indexed line of the fence within `body`, {kind: keys}) for every
    ```yaml fence in an item body whose content parses as a mapping naming a
    key the front matter reads and the body never will -- the
    inert-front-matter trap (R9-F1): a `checks:` written as a body fence next
    to the calc fence renders as literal prose, the check silently never
    runs, and `check` reports 0 errors. Kinds are 'field' (a field of the
    item's type), 'link' (a link verb the item's type declares, R10-F1 --
    `satisfies:` in a body fence lands in no `links:` at all) and 'meta'
    (`id`/`type`, R10-F2). A yaml fence of genuine example code (no such key,
    including a fence escaped inside an outer fence) is not a match; the body
    itself is never modified.

    The caller turns each pair into a warning at the fence's absolute line
    -- same `body_line + offset` shape as `calc.fence_errors`'s report in
    `_run_item_calcs`."""
    out: list[tuple[int, dict[str, list[str]]]] = []
    for fence_line, content in iter_yaml_fences(body):
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError:
            continue
        if not isinstance(parsed, dict):
            continue
        groups: dict[str, list[str]] = {}
        for key in parsed:
            name = str(key)
            if name in field_names:
                kind = "field"
            elif name in link_names:
                kind = "link"
            elif name in _INERT_META_KEYS:
                kind = "meta"
            else:
                continue
            groups.setdefault(kind, []).append(name)
        if groups:
            out.append((fence_line, groups))
    return out


def inert_fence_message(type_name: str, groups: dict[str, list[str]]) -> str:
    """The R9-F1 warning text, naming each declared key by what it is: a
    field of the item's type, a link verb of it, or a front-matter key --
    the remedy is the same for all three (docs/links.md authors links in
    front matter exactly like fields)."""
    def quoted(names: list[str]) -> str:
        return ", ".join(f"'{name}'" for name in names)

    parts, kinds = [], []
    if fields := groups.get("field"):
        kinds.append("field")
        noun = "fields" if len(fields) > 1 else "a field"
        parts.append(f"{quoted(fields)} -- {noun} of type '{type_name}'")
    if links := groups.get("link"):
        kinds.append("link")
        noun = "links" if len(links) > 1 else "a link"
        parts.append(f"{quoted(links)} -- {noun} of type '{type_name}'")
    if meta := groups.get("meta"):
        kinds.append("meta")
        noun = "keys" if len(meta) > 1 else "a key"
        parts.append(f"{quoted(meta)} -- {noun} only the front matter reads")
    consequence = (
        {"field": "the field never takes effect",
         "link": "the link never takes effect",
         "meta": "the key never takes effect"}[kinds[0]]
        if len(kinds) == 1
        else "nothing in the fence takes effect"
    )
    return (
        f"a ```yaml fence in this item's body declares {'; '.join(parts)}. "
        "In the body a YAML fence is prose: it renders as literal text and "
        f"{consequence}. Move it into the item's front matter (the '---' "
        "block at the top of the file)."
    )


def validate_items(project: Project) -> None:
    # Built once for the whole pass: `citations: - item:` resolves through the
    # same helper as every other target spelling, and `_key_index` is one dict
    # comprehension over items already in memory.
    by_key = _key_index(project)
    for item in project.local_items:
        spec = project.types[item.type]

        if spec.body_required and not item.body.strip():
            project.warn(
                "body: is empty -- title: is an optional short label, not a "
                "substitute for the content itself. A warning, not an error, "
                "so a stub can exist while it's still being drafted.",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )

        # R9-F1: a `checks:` (or any field the type declares, any link verb
        # it declares, or `id`/`type`) written as a ```yaml fence in the body
        # is inert -- it renders as prose and never takes effect. Warning,
        # not error: the item is valid, just not doing what the page shows;
        # and a yaml fence of pure example code (no such key, including a
        # fence escaped inside an outer fence) never reaches this.
        for fence_offset, inert_groups in declares_inert_keys(
            item.body, spec.fields, spec.links
        ):
            fence_line = (
                item.body_line + fence_offset
                if item.body_line is not None else item.source_line
            )
            project.warn(
                inert_fence_message(item.type, inert_groups),
                file=item.source_file, line=fence_line, item_id=item.id,
            )

        for fname, fspec in spec.fields.items():
            value = item.fields.get(fname)
            effective_required = fspec.required or (
                fspec.required_when is not None
                and _required_when_satisfied(item, fspec.required_when)
            )
            if effective_required and (value is None or str(value).strip() == ""):
                if fspec.required_when is not None:
                    project.error(
                        f"{fname!r} is required when "
                        f"{_format_required_when(fspec.required_when)} "
                        f"(required_when: {fspec.required_when})",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                else:
                    project.error(
                        f"missing required field {fname!r}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                continue
            if value is None:
                continue
            if fspec.type == "enum" and fspec.choices and value not in fspec.choices:
                close = difflib.get_close_matches(str(value), fspec.choices, n=1, cutoff=0.5)
                hint = f" Did you mean {close[0]!r}?" if close else ""
                _field_error(
                    project, item, fname,
                    f"{fname}: {value!r} is not one of "
                    f"{', '.join(fspec.choices)}.{hint}",
                )
            elif fspec.type == "date":
                try:
                    dates.parse_date(value, project.date_format)
                except ValueError:
                    _field_error(
                        project,
                        item,
                        fname,
                        f"{fname}: {value!r} is not a valid date; expected {project.date_format}",
                    )
            elif fspec.type == "limit":
                try:
                    calc.parse_limit(str(value))
                except calc.CalcError as exc:
                    _field_error(project, item, fname, f"{fname}: {exc}")
            elif fspec.type == "options":
                # Each option is read as a mapping by the templates --
                # `opt.get('name')` in item.html.j2's options panel -- so a
                # list of bare strings is a shape error the build has to own:
                # it passed `check` with 0 errors and then died in the render
                # with `UndefinedError: 'str object' has no attribute 'get'`,
                # exit 1, a raw Jinja2 traceback and a half-written site.
                # Same posture as the `citations:` branch below and `checks:`
                # in `run_checks`: the shape of an entry is diagnosed at the
                # item, not discovered by the template that consumes it.
                # A non-list `options:` (scalar or mapping) is already the
                # loader's error -- `_reject_scalar_collection` owns that
                # keystroke, and reporting it twice helps nobody.
                if not isinstance(value, list):
                    continue
                for index, entry in enumerate(value):
                    if isinstance(entry, dict):
                        continue
                    _field_error(
                        project, item, fname,
                        f"{fname}[{index}]: {entry!r} is not an option -- an "
                        f"option is a mapping with a 'name' and, optionally, "
                        f"a 'verdict' and a 'because', as in "
                        f"{fname}: [{{name: LDO, verdict: rejected, because: "
                        f"dissipates 10 W at full load}}]",
                    )
            elif fspec.type == "tasks":
                # living-notes.md §5, phase H6. Rows are `{id, text, state}`
                # with `state` one of open | done | dropped. Two rules,
                # decided with the fold: task ids are unique within a list
                # (the fold replaces whole lists, so identity across entries
                # is what a row's stable id is for), and a state outside the
                # three known words is an error -- a row that means `done`
                # but says `closed` would silently never tick. Row shape
                # follows the `options:` posture above: the shape of an entry
                # is diagnosed at the item, not discovered by the fold or a
                # template that consumes it. A non-list `tasks:` (scalar or
                # mapping) is the loader's error -- `_reject_scalar_collection`
                # owns that keystroke (`tasks` is in NON_SCALAR_FIELD_TYPES).
                if not isinstance(value, list):
                    continue
                seen_task_ids: dict[str, int] = {}
                for index, entry in enumerate(value):
                    if not isinstance(entry, dict):
                        _field_error(
                            project, item, fname,
                            f"{fname}[{index}]: {entry!r} is not a task -- a "
                            f"task is a mapping with an 'id', a 'text', and a "
                            f"'state' of open, done or dropped, as in "
                            f"{fname}: [{{id: T-thermal-model, text: Model "
                            f"worst-case copper temperature., state: open}}]",
                        )
                        continue
                    task_id = entry.get("id")
                    if task_id is not None and str(task_id) != "":
                        first = seen_task_ids.setdefault(str(task_id), index)
                        if first != index:
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}].id: {str(task_id)!r} is "
                                f"already used at {fname}[{first}] -- task "
                                f"ids must be unique within a list",
                            )
                    state = entry.get("state")
                    if state is None or str(state) == "":
                        continue
                    if state not in TASK_STATES:
                        close = difflib.get_close_matches(
                            str(state), TASK_STATES, n=1, cutoff=0.5
                        )
                        hint = (
                            f" Did you mean {close[0]!r}?" if close else ""
                        )
                        _field_error(
                            project, item, fname,
                            f"{fname}[{index}].state: {state!r} is not one "
                            f"of {', '.join(TASK_STATES)}.{hint}",
                        )
            elif fspec.type == "citations":
                if not isinstance(value, list):
                    _field_error(
                        project, item, fname,
                        f"{fname}: must be a list of citation entries",
                    )
                else:
                    for index, entry in enumerate(value):
                        if not isinstance(entry, dict):
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}]: each citation needs a 'path' or 'item'",
                            )
                            continue
                        if "url" in entry:
                            # Hard break (finding 25 Part 2): never let a stale
                            # `url:` fail as an anonymous unknown key -- name the
                            # rename and the way to have it done automatically.
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}]: citation field url: was "
                                f"renamed to path: -- rename it (refdes "
                                f"standard upgrade does this for hardware@2 "
                                f"-> @3 content)",
                            )
                            continue
                        if "vendor" in entry:
                            # Same hard break for the S1 rename (vocabulary-
                            # review.md): `vendor:` meant "keep a local copy",
                            # which a hardware engineer reads as the company.
                            # Silently ignoring it would drop the keep_copy flag and
                            # report the citation as hash-only -- success while
                            # doing nothing.
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}]: citation field vendor: was "
                                f"renamed to keep_copy: -- rename it (refdes "
                                f"standard upgrade does this for hardware@2 "
                                f"-> @3 content)",
                            )
                            continue
                        if "item" in entry:
                            target = entry["item"]
                            if not isinstance(target, str) or not target.strip():
                                _field_error(
                                    project, item, fname,
                                    f"{fname}[{index}]: item: must name an item id",
                                )
                            elif resolve_link_target(by_key, project, target) is None:
                                # `ID@key` and a bare key resolve here exactly
                                # as they do for every other target spelling
                                # (docs/design/keys.md §3); a display-id-only
                                # lookup reported a composite whose target was
                                # alive as "does not exist", which names neither
                                # the real cause nor a way out. Anything that
                                # *looks* like a key spelling now gets the shared
                                # key diagnostic instead, which explains that the
                                # key is what resolves and the label may be stale.
                                if "@" in target or _is_bare_key_token(target):
                                    _field_error(
                                        project, item, fname,
                                        _unknown_key_message(
                                            project, f"{fname}[{index}]: item:", target
                                        ),
                                    )
                                else:
                                    _field_error(
                                        project, item, fname,
                                        f"{fname}[{index}]: item: {target!r} does not exist",
                                    )
                        if not entry.get("path") and not entry.get("item"):
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}]: each citation needs a 'path' or 'item'",
                            )
                            continue
                        if not entry.get("path"):
                            continue  # item-only citations have no document to verify
                        try:
                            kind, _canon = citations_mod.classify(
                                project.root, str(entry["path"])
                            )
                        except citations_mod.CitationError as exc:
                            _field_error(project, item, fname, f"{fname}[{index}]: {exc}")
                            continue
                        if kind == "local" and entry.get("keep_copy"):
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}]: keep_copy: on local path "
                                f"{str(entry['path'])!r} is meaningless -- a "
                                f"local file is already local",
                            )
                            continue
                        if entry.get("page") is not None:
                            # A page is a positive integer or it is not a page
                            # the rendered `#page=` fragment can open, so this is
                            # a declaration error like `section:` above and not
                            # something to discover at build time. The grammar is
                            # the editor picker's own
                            # (`citations.page_number`, still
                            # `serve/sources._page_number`): `page: 0` used to
                            # publish `#page=0`, which most viewers read as page
                            # 1 and none of them as page 0. Whether the number is
                            # one this particular document has is a different
                            # question, asked against the page count in
                            # `citations._apply_page`.
                            page = entry["page"]
                            if not isinstance(page, (str, int)) or isinstance(
                                page, bool
                            ) or citations_mod.page_number(str(page)) is None:
                                _field_error(
                                    project, item, fname,
                                    f"{fname}[{index}]: page: {page!r} is not a "
                                    f"page number -- page: must be a positive "
                                    f"integer, counted from 1."
                                    f"{_page_remedy(page)}"
                                    f" See {docs_url_mod.CITATION_PAGE_DOCS}.",
                                )
                                continue
                        if "section" in entry:
                            section = entry["section"]
                            if not isinstance(section, str) or not section.strip():
                                _field_error(
                                    project, item, fname,
                                    f"{fname}[{index}]: section: must be a "
                                    f"non-empty string naming an outline entry",
                                )
                                continue
                            if kind == "remote" and not entry.get("keep_copy"):
                                # Resolving a title needs the bytes, and for a
                                # hash-only remote citation they are not
                                # guaranteed to be local -- resolution would
                                # depend on the network at fetch time and on
                                # luck afterwards.
                                _field_error(
                                    project, item, fname,
                                    f"{fname}[{index}]: section: on remote "
                                    f"path {str(entry['path'])!r} needs "
                                    f"keep_copy: true -- the bytes have to be "
                                    f"local for its outline to be read; keep a copy of "
                                    f"this citation or cite a local path",
                                )
                                continue
                        cite_id = entry.get("id")
                        if not cite_id:
                            continue
                        cite_id = str(cite_id)
                        if not CITATION_ID_RE.match(cite_id):
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}].id: {cite_id!r} is not a valid "
                                f"citation id (letters, digits, '-', '_' only)",
                            )
                            continue
                        existing = project.citation_ids.get(cite_id)
                        if existing is not None:
                            owner, owner_file, owner_line = existing
                            loc = f"{owner_file}:{owner_line}" if owner_line is not None else owner_file
                            project.error(
                                f"citation id {cite_id!r} is already used by {owner} ({loc}). "
                                f"Citation ids must be unique across the project.",
                                file=item.source_file, line=item.source_line, item_id=item.id,
                            )
                        else:
                            project.citation_ids[cite_id] = (item.id, item.source_file, item.source_line)
            elif fspec.type == "list":
                # A `list` field is a list of plain strings -- the shape the
                # editor's own completion is built from
                # (`schema_json._FIELD_TYPE_MAP`:
                # `"list": {"type": "array", "items": {"type": "string"}}`)
                # and the shape every consumer reads element by element:
                # `refdes ls --tag` substring-matches it, the item template
                # joins it, the search index indexes it. Run 6a's B6 was the
                # missing branch: a mapping element in `tags:` (what an author
                # writes when a list field gets the shape of the `options:`
                # block beside it) passed `check` with 0 errors, rendered on
                # the page as a Python dict repr, and `ls --tag x` matched the
                # mapping's *value*. Same posture as `options:` above: the
                # shape of an entry is diagnosed at the item, naming the field
                # and the index. A non-list `tags:` (scalar or mapping) is the
                # loader's error -- `_reject_scalar_collection` owns that
                # keystroke -- and an empty entry is the field's own business,
                # not this branch's.
                if not isinstance(value, list):
                    continue
                for index, entry in enumerate(value):
                    if isinstance(entry, str) or entry is None or entry == "":
                        continue
                    _field_error(
                        project, item, fname,
                        f"{fname}[{index}]: {entry!r} is not a string -- a "
                        f"{fname} entry is a plain string, one per line, as "
                        f"in {fname}: [first, second]",
                    )


def lint_own_tags(project: Project) -> None:
    """Finding 11, sequenced after finding 9 (`refdes ls --tag`): warn on an
    item with no `tags:` of its own -- opt-in, following `boards.lint_tokens()`'s
    own precedent for an advisory lint, since `tags:` is optional by design
    (`sets.provenance`, no `required:`) and plenty of projects will
    reasonably not want the noise.

    A bare presence check (warn when `tags:` is unset) would fire on
    essentially nothing: `tags:` is almost always declared once in a file's
    `defaults:` block, so every item in that file inherits a non-empty list
    automatically, satisfying a presence check while changing nothing about
    findability. `item.inherited_fields` (finding 6) is what makes the real
    signal checkable at all -- an item whose `tags:` is entirely inherited
    is exactly as hard to find as one with none, since a file-level tag set
    is identical across every item in the file and just re-encodes which
    file/board the item is already in.
    """
    if not project.lint_own_tags:
        return
    for item in project.local_items:
        spec = project.types[item.type]
        if "tags" not in spec.fields:
            continue
        if "tags" in item.inherited_fields:
            project.warn(
                "tags: are entirely inherited from this file's defaults: -- "
                "no tags of its own, which makes it as hard to find later as "
                "having none; add at least one item-specific tag",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
        elif not item.fields.get("tags"):
            project.warn(
                "no tags: at all, which makes it harder to find later; add "
                "at least one",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )


def validate_former_ids(project: Project) -> None:
    """Populate `project.former_ids` and flag one the linker can never reach.

    `BARE_REF_RE` requires an id to end in `-<digits>` -- deliberately: prose
    is full of hyphen-free, underscore-joined, all-caps tokens (`MAX_RETRY_3`,
    `GPIO_12`) that would false-positive as references if bare-word matching
    were loosened to catch them. Rather than widen that regex and trade
    autolink precision for former-id recall, an old id shaped like that is
    still fully linkable -- just only explicitly, as `[[old_id]]` -- and this
    warns so the gap is visible instead of a silent no-op.
    """
    ids_mod.collect_former_ids(project)
    for old_id, owner_id in project.former_ids.items():
        if BARE_REF_RE.fullmatch(old_id):
            continue
        owner = project.item_by_id(owner_id)
        project.warn(
            f"former_ids: {old_id!r} does not match the bare-reference shape "
            f"(PREFIX-NNN) and will never autolink in prose -- reference it "
            f"explicitly as [[{old_id}]]",
            file=owner.source_file, line=owner.source_line, item_id=owner_id,
        )


def _key_index(project: Project) -> dict[str, Item]:
    """Every item that has a surrogate key (docs/design/keys.md), keyed by
    that key. Built fresh on every call rather than cached on Project: it's
    cheap (one dict comprehension over items already parsed into memory),
    and a cached copy would need its own invalidation story every time an
    item's key changes (a reparse after `keys.mint_missing()` writes new
    ones, in particular).

    keys.validate() has already reported every duplicate before this runs,
    so a collision cannot make the build succeed even though this downstream
    index necessarily retains only one of the colliding items.
    """
    return {item.key: item for item in project.items.values() if item.key}


def _is_bare_key_token(target: str) -> bool:
    """Whether ``target`` has key-token shape rather than display-ID shape.

    Display IDs are conventionally hyphenated. A separator-free,
    11-character token is a key spelling, even when Layer 1 later finds it
    corrupt (uppercase and excluded alphabet characters included).
    """
    return len(target) == keys_mod.KEY_LEN and "@" not in target and "-" not in target


def _is_well_formed_bare_key(target: str) -> bool:
    return _is_bare_key_token(target) and keys_mod.malformed_key_message(target) is None


def resolve_link_target(by_key: dict[str, Item], project: Project, target: str) -> Item | None:
    """Resolve one structured link's target string to the item it names.

    Composite form `DISPLAY-ID@key` (docs/design/keys.md §3): resolution
    uses only the key, the part after `@` -- the display half is
    tool-maintained (refreshed when the target renames) and never consulted
    for resolution, not even as a fallback when the key doesn't resolve.
    That is deliberate, not an oversight: falling back to the display text
    would resurrect exactly the ambiguity keys exist to remove (two items
    momentarily sharing a stale display id after a rename, say). A bare,
    well-formed key resolves directly by key. Any other bare token remains a
    display-ID lookup, preserving the authoring path for unanchored links.

    No `former_ids:` fallback here: that is a prose-only mechanism
    (`validate_former_ids` / `_linkify`'s "(formerly X)" marker). A
    structured link (`satisfies:`, `refines:`, ...) must name a still-live
    id or key directly, same as always.

    Also used by compute_hashes (build.py's own _link_hash_token), so hashing
    stays correct regardless of whether a target is still a bare id or has
    already been expanded to a composite by links.expand_missing.
    """
    if "@" in target:
        _display, _, key = target.partition("@")
        return by_key.get(key)
    if _is_well_formed_bare_key(target):
        return by_key.get(target)
    return project.item_by_id(target)


def _unknown_key_message(project: Project, pointer: str, target_id: str) -> str:
    """Layer-3 diagnostic for a composite or bare key with no live target.

    Shared, not duplicated, between structured links (`resolve_links`) and
    `checks: against:` (`run_checks`) and cross-item calc references: all
    point at a target the same way,
    and `pointer` supplies only the verb phrase (for example, "refines
    points at" or "check against"). The remaining text deliberately never
    falls back to a display ID; for a composite its label may be stale, and
    for a bare key the key itself is the immutable identity.

    One condition, one wording (run-5 F8). This used to say the same thing
    three ways: a bare key and a stale label each got "check git history
    before restoring the original key or removing the reference", which sends
    the author to archaeology, while only the shape whose label happened to
    name a live item named `refdes keys restore` -- the command that fixes it
    without any. The explanation and the remedy below are now one text for
    every local target, and what varies is only what is true of the reference
    being reported: the extra sentence about a live item carrying this label,
    the argument of the restore command, and -- for a bare key, whose label is
    the very thing that is missing -- the words saying to substitute it. The
    imported-target ending stays different on purpose: `keys restore` writes to
    a file in this project, so it cannot reach a key that lives upstream
    (docs/troubleshooting.md).
    """
    label, separator, key = target_id.partition("@")
    if not separator:
        label, key = "", target_id
    message = f"{pointer} key {key!r}"
    if separator:
        message += f" (labelled {label})"
    message += ", which no item declares. "
    live = project.item_by_id(label) if separator else None
    if live is not None:
        declared = f"declares key {live.key!r}" if live.key else "declares no key"
        loss = "lost and regenerated" if live.key else "lost"
        message += (
            f"A live item labelled {label} {declared}. Its key may have been "
            f"{loss}, or the label may now name a different item. "
        )
    message += (
        "The target may have been deleted or its key lost or changed. A "
        "reference resolves by its key alone, so check git history to confirm "
        "identity. "
    )
    if live is not None and live.external:
        # The composite is the reason this author is confused: a writable load
        # of *their* project wrote it (docs/multi-board.md), so "no item
        # declares this key" reads like a claim about a file they never
        # touched. Say who wrote it before telling them where to fix it.
        return message + (
            "If it is the same item, restore its original key upstream. This "
            "composite reference was written into your file by refdes on a "
            f"load, not typed by hand — see {docs_url_mod.MULTI_BOARD_DOCS}."
        )
    # A bare key carries no label to put in front of the `@`, and nothing here
    # knows which item the key belonged to -- finding that is what the git
    # history above is for. So the command shows a placeholder for the label,
    # and says in words that it is one: a line an author pastes without
    # replacing it is worse than no command at all, and angle brackets would
    # only have made it fail in a different way. The shape is the argument
    # `keys restore --help` takes (`DISPLAY-ID@ORIGINAL-KEY`, verified by
    # running it) with this reference's own real key already substituted in.
    if separator:
        restore, substitution = f"{label}@{key}", ""
    else:
        restore = f"DISPLAY-ID@{key}"
        substitution = ", replacing DISPLAY-ID with the item's display id"
    return message + (
        f"If it is the same item, run `refdes keys restore {restore} "
        f"--dry-run`{substitution}, then repeat without --dry-run to restore "
        "the original key."
    )


def _dangling_bare_message(pointer: str, target_id: str, noun: str) -> str:
    """The bare-display-id half of "resolves to nothing" -- a structured link
    (`resolve_links`) or a `checks: against:` entry (`run_checks`).

    Shared, not duplicated, for the same reason as _unknown_key_message: both
    name a target the same way and resolve it through resolve_link_target, so
    the three ordinary explanations and the one remedy that apply are the
    same three and the same one. `noun` is what the caller calls the thing
    carrying the bare text -- "reference" for a structured link, "`against:`"
    for a `checks:` entry -- so the message reads about the right half of the
    file.

    Nothing here is computed from the project: the typo, deleted-item and
    renamed-while-bare cases share one text rather than the rename case being
    detected, because `project.former_ids` is empty at resolution time by
    design (validate_former_ids has not run) so a conditional version would
    need a new lookup -- a behaviour change, not a rewording. Kept to two
    sentences because this fires on every typo: the long form, which commands
    do *not* apply and why a hand rename is safe once a writable load has run,
    is troubleshooting.md's `## Links`, which is where the URL points.
    """
    return (
        f"{pointer} {target_id!r}, which does not exist -- a typo, a deleted "
        f"item, or an item renamed while this {noun} was still bare, and a "
        f"bare {noun} cannot follow a rename: write the item's new id here. "
        f"See {docs_url_mod.DANGLING_LINK_DOCS}."
    )


def _expand_subtypes(project: Project, names) -> set[str]:
    """`names` plus every type that extends one of them -- the ALLOW-side
    reading of a type-name list (docs/design/extends.md §3): a subtype stands
    wherever its parent is named."""
    sub = project.subtype_map
    expanded = set(names)
    for name in names:
        expanded.update(sub.get(name, ()))
    return expanded


def resolve_links(project: Project) -> None:
    by_key = _key_index(project)
    subtypes = project.subtype_map
    for item in project.items.values():
        spec = project.types.get(item.type)
        if spec is None:  # imported item of an undeclared type
            continue
        for link_name, targets in item.links.items():
            allowed = spec.links.get(link_name, [])
            for target_id in targets:
                bare_key = _is_bare_key_token(target_id)
                if "@" in target_id or bare_key:
                    label, _, key = target_id.partition("@")
                    if bare_key:
                        key = target_id
                    malformed = keys_mod.malformed_key_message(
                        key,
                        context=(
                            f" in {link_name} target (labelled {label})"
                            if "@" in target_id
                            else f" in {link_name} target"
                        ),
                    )
                    if malformed is not None:
                        project.error(
                            malformed,
                            file=item.source_file,
                            line=item.source_line,
                            item_id=item.id,
                        )
                        continue

                target = resolve_link_target(by_key, project, target_id)
                if target is None:
                    if "@" in target_id or bare_key:
                        message = _unknown_key_message(project, f"{link_name} points at", target_id)
                    else:
                        message = _dangling_bare_message(
                            f"{link_name} points at", target_id, "reference"
                        )
                    project.error(
                        message,
                        file=item.source_file,
                        line=item.source_line,
                        item_id=item.id,
                    )
                    continue
                inverse = project.inverse_of.get(link_name, f"{link_name}_by")
                source_ref = item.id or item.key
                target_ref = target.id or target.key
                if allowed and not any(
                    is_subtype(target.type, name, subtypes) for name in allowed
                ):
                    # `target_ref`, not the raw `target_id`: a link reached
                    # through a composite carries `DISPLAY-ID@key`, and the key
                    # is an implementation detail of the file, not something to
                    # read in a message meant for a human (model.py's
                    # resolved_links/links contract). It is also always current,
                    # so the stale-label hazard _unknown_key_message reports
                    # cannot arise here.
                    project.error(
                        f"{link_name} may point at {', '.join(allowed)}, but "
                        f"{target_ref} is a {target.type}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                    continue
                target.backlinks.setdefault(inverse, []).append(source_ref)
                item.resolved_links.setdefault(link_name, []).append(target_ref)


# Preserved exactly for the name-based coverable/verifier fallback below -- the
# behavior every project had before `coverable:`/verifies-link detection existed.
_FALLBACK_COVERABLE_TYPES = ("requirement", "constraint")


def _verifier_type_names(project: Project) -> set[str]:
    """Which types can verify something, derived from `links:`, not a type name.

    A type declaring `verifies` on itself is the verifier (the standard's own
    convention: test.links.verifies: [...]). A type declaring `verified_by`
    naming its own verifier target types (the legacy convention: a requirement
    declaring `verified_by: [test]`) makes each named target type a verifier
    instead. Either spelling of the pair is recognized, so this needs no new
    flag -- every project's link declarations already carry the information
    (docs/design/standard-library.md §2).
    """
    names: set[str] = set()
    for tname, spec in project.types.items():
        for lname, targets in spec.links.items():
            if lname == "verifies":
                names.add(tname)
            elif lname == "verified_by":
                names.update(targets)
    return _expand_subtypes(project, names)


def _resolve_coverable(
    spec: ItemType, project: Project, warned: set[str]
) -> tuple[bool, bool]:
    """(is_coverable, via_fallback). Emits the one-time fallback warning only for
    the two names the fallback has ever recognized -- see the compatibility
    hazard writeup in docs/design/standard-library.md §2."""
    if spec.coverable is not None:
        return spec.coverable, False
    # A subtype of one of the two conventional names stands in for it
    # (docs/design/extends.md §3); `spec.extends` is "" for every other type.
    is_fallback_coverable = (
        spec.name in _FALLBACK_COVERABLE_TYPES
        or spec.extends in _FALLBACK_COVERABLE_TYPES
    )
    if is_fallback_coverable and spec.name not in warned:
        project.warn(
            f"types.{spec.name} does not declare 'coverable:'; falling back to "
            "name-based detection (requirement/constraint are coverable by "
            "convention). Add 'coverable: true' explicitly -- this fallback is "
            "removed in refdes 1.0."
        )
        warned.add(spec.name)
    return is_fallback_coverable, True


def _excluded_by_status(item: Item, spec: ItemType) -> bool:
    """True if this item's current status keeps it out of coverage.

    `coverable_statuses` set: inclusion list -- coverable only when status is in
    it. Unset: falls back to excluding `status == "retired"` if a status field
    exists, and excluding nothing otherwise -- the exact pre-existing behavior.
    """
    if spec.coverable_statuses is not None:
        return item.fields.get("status") not in spec.coverable_statuses
    if "status" in spec.fields:
        return item.fields.get("status") == "retired"
    return False


def _group_type_names(project: Project) -> set[str]:
    """Which types are groups, derived from the schema rather than a type name.

    A group is whatever some type's `part_of:` may point at -- in the bundled
    hardware@3 standard that is exactly `group` (docs/design/backlog.md
    finding 14). Deriving it keeps this generic the way `_verifier_type_names`
    already is, and means a project with no `part_of:` declared anywhere has no
    group types, so any `conforms_to:` target is an error rather than a hit.
    """
    names: set[str] = set()
    for spec in project.types.values():
        names.update(spec.links.get("part_of", []))
    return _expand_subtypes(project, names)


def validate_conforms_to(project: Project) -> None:
    """Every `conforms_to:` target must name an existing group item.

    A typo here would silently discharge a whole board's obligations -- the
    same silent-and-optimistic failure an unregistered `board:` is a hard error
    for (boards.resolve), so this matches that posture exactly: name the fix,
    and do not let the build pass. Runs after resolve_links(), which is what
    populates the `contains` backlinks the per-board coverage below reads.
    """
    if not project.boards:
        return
    group_types = _group_type_names(project)
    for bname, spec in sorted(project.boards.items()):
        for target in spec.conforms_to:
            item = project.item_by_id(target)
            if item is None:
                project.error(
                    f"boards.{bname} conforms_to {target!r}, which does not "
                    f"exist -- a group item must be declared before a board can "
                    f"conform to it",
                    file="refdes-project.yaml",
                )
            elif item.type not in group_types:
                project.error(
                    f"boards.{bname} conforms_to {target!r}, which is a "
                    f"{item.type}, not a group -- conforms_to names group items",
                    file="refdes-project.yaml",
                )


def validate_includes(project: Project) -> None:
    """Every `includes:` target must name an existing group item.

    Mirrors `validate_conforms_to` exactly (finding 33): a typo here would
    silently leave a shared part off the board's pages -- the same absence
    this feature exists to fix -- so it is a hard error, not a quietly empty
    display set. Runs after resolve_links(), like its counterpart, though
    `includes:` itself only needs `item_by_id` to check the targets.
    """
    if not project.boards:
        return
    group_types = _group_type_names(project)
    for bname, spec in sorted(project.boards.items()):
        for target in spec.includes:
            item = project.item_by_id(target)
            if item is None:
                project.error(
                    f"boards.{bname} includes {target!r}, which does not "
                    f"exist -- a group item must be declared before a board "
                    f"can include it",
                    file="refdes-project.yaml",
                )
            elif item.type not in group_types:
                project.error(
                    f"boards.{bname} includes {target!r}, which is a "
                    f"{item.type}, not a group -- includes names group items",
                    file="refdes-project.yaml",
                )


def _board_gate(project: Project, board: str | None):
    """Filter for the satisfiers/verifiers that count toward `board`.

    `board is None` is the ordinary per-item coverage: everything counts, exactly
    as before. Otherwise only items actually on that board count -- and an item
    with no board counts for *no* board, so a satisfier sitting outside the
    registry can never quietly discharge a per-board obligation (finding 24).
    """
    def keep(ref: str) -> bool:
        if board is None:
            return True
        other = project.item_by_ref(ref)
        return other is not None and other.board == board

    return keep

def _coverage_status(project: Project, entry: Item | None, chain_graph) -> object | None:
    """Status coverage tests use an entry's declaration, then its thread.

    This applies identically to `satisfying_statuses` and
    `verifying_statuses`: a status inherited from a file `defaults:` block
    is not the entry declaring it. For a thread entry the current thread
    value is used instead; an unmerged fork resolves to None and cannot
    settle either kind of coverage. A non-thread item keeps its established
    effective-default behavior, preserving projects without `follows:`.
    """
    if entry is None:
        return None
    if "status" in entry.fields and "status" not in entry.inherited_fields:
        return entry.fields["status"]
    if not chains_mod.is_threaded(project, entry, graph=chain_graph):
        return entry.fields.get("status")
    return chains_mod.resolve_current(project, entry, "status", graph=chain_graph)


def _coverage_for(
    item: Item, project: Project, board: str | None = None, chain_graph=None
) -> Coverage:
    """One item's Coverage, optionally restricted to satisfiers on `board`.

    Same rules either way -- the only difference is which linked items count.
    """
    keep = _board_gate(project, board)
    cov = Coverage(item_id=item.id)
    cov.addressed_by = sorted(
        i
        for i in set(item.backlinks.get("addressed_by", []))
        | set(item.resolved_links.get("addresses", []))
        if keep(i)
    )

    settled: list[str] = []
    claimed: list[str] = []
    for satisfier_id in sorted(
        i
        for i in set(item.backlinks.get("satisfied_by", []))
        | set(item.resolved_links.get("satisfies", []))
        if keep(i)
    ):
        satisfier = project.item_by_ref(satisfier_id)
        satisfier_spec = project.types.get(satisfier.type) if satisfier else None
        allowed = satisfier_spec.satisfying_statuses if satisfier_spec else None
        # Unconfigured type: every link counts as settled, same as before
        # satisfying_statuses existed.
        status = _coverage_status(project, satisfier, chain_graph)
        if allowed is not None and status not in allowed:
            claimed.append(satisfier_id)
        else:
            settled.append(satisfier_id)
    cov.satisfied_by = settled
    cov.claimed_by = claimed

    verified: list[str] = []
    for verifier_id in sorted(
        i
        for i in set(item.backlinks.get("verified_by", []))
        | set(item.resolved_links.get("verified_by", []))
        if keep(i)
    ):
        verifier = project.item_by_ref(verifier_id)
        verifier_spec = project.types.get(verifier.type) if verifier else None
        allowed = verifier_spec.verifying_statuses if verifier_spec else None
        # Unconfigured: every link counts, mirroring satisfying_statuses.
        status = _coverage_status(project, verifier, chain_graph)
        if allowed is None or status in allowed:
            verified.append(verifier_id)
    cov.verified_by = verified
    return cov


def compute_board_coverage(project: Project, chain_graph=None) -> None:
    """Per-(item, board) coverage for the members of each board's `conforms_to:` groups.

    A platform-wide contract -- "every board with an ARM MCU uses the standard
    debug header" -- is one requirement item, so per-item coverage reports it
    satisfied the moment *any* board complies (docs/design/backlog.md finding
    24). This computes the same five stages again, once per (item, board) pair,
    counting only that board's own satisfiers, and warns on any pair still short
    of `satisfied`.

    Ordinary per-item coverage is untouched: this writes `project.board_coverage`
    only, and a project with no `conforms_to:` gets an empty dict and no warnings
    -- byte-identical output to before this existed.
    """
    if not project.boards:
        return
    warned_fallback_types: set[str] = set()
    for bname, spec in sorted(project.boards.items()):
        # A board with no items of its own gets no report pages at all, so its
        # warning must not point at a coverage page that will never be written.
        # nav.scope_reports is render's own condition for the page set -- it
        # decides emptiness from the board's items alone, so asking it here
        # before citations have been verified is still the same answer, and
        # this cannot drift from what actually lands in _site/.
        has_coverage_page = bool(
            spec.conforms_to and nav_mod.scope_reports(project, board=bname)
        )
        for group_id in spec.conforms_to:
            group = project.item_by_id(group_id)
            if group is None:
                continue  # validate_conforms_to() already errored on this
            for member_id in sorted(group.backlinks.get("contains", [])):
                member = project.item_by_ref(member_id)
                if member is None:
                    continue
                member_spec = project.types.get(member.type)
                if member_spec is None:
                    continue
                coverable, _via_fallback = _resolve_coverable(
                    member_spec, project, warned_fallback_types
                )
                if not coverable or _excluded_by_status(member, member_spec):
                    continue
                cov = _coverage_for(member, project, board=bname, chain_graph=chain_graph)
                project.board_coverage[(member.id, bname)] = cov
                if cov.stage in ("satisfied", "verified"):
                    continue
                pointer = f" — see coverage-{bname}.html" if has_coverage_page else ""
                project.warn(
                    f"{member.id} is not satisfied on board {bname!r} "
                    f"(board conforms to {group_id}) -- its "
                    f"{cov.stage} stage counts only {bname}'s own items{pointer}",
                    file=member.source_file,
                    line=member.source_line,
                    item_id=member.id,
                )


def compute_coverage(project: Project, chain_graph=None) -> None:
    """Distinct notions of done, which people routinely conflate.

    addressed  — somebody has worked on it and written it up in the design log
    claimed    — a decision or component says it meets it, but hasn't settled
                 (its status is not in the type's satisfying_statuses:, if declared)
    satisfied  — a settled decision or component claims to meet it
    verified   — a test proves it

    A requirement can be satisfied without being verified, and addressed without
    being satisfied. Collapsing those into one "done" flag is how open work goes
    missing.

    Two of these are individually uninteresting at scale, so they're counted
    rather than reported per item -- coverage.html carries the detail:

    - "nothing addresses, satisfies, or verifies this yet" -- every item starts
      here, so a project early in its life is mostly this.
    - "satisfied but not verified" -- routine noise when the project has not
      written a test plan yet, which is why it's suppressed entirely when no
      verifier items exist at all (the moment the first one is added, these
      become real findings again and start appearing).

    "Claimed but not verified" stays per item: it names an unsettled decision,
    which is the one class of coverage warning that is actually actionable.

    Participation is gated by `coverable:`/`coverable_statuses:` and which
    verifier links actually settle by `verifying_statuses:` -- schema-engine
    flags, not standard-specific plumbing (see model.ItemType and
    docs/design/standard-library.md §2). A type that never declares `coverable:`
    falls back to the old requirement/constraint-by-name convention, with a
    one-time warning; on that fallback path only, the requirement/constraint
    asymmetry in which types get the per-item warnings below is preserved
    exactly. Once a type explicitly declares `coverable: true`, it gets the
    same warnings as any other coverable type -- no further name restriction.
    """
    verifier_type_names = _verifier_type_names(project)
    has_verifiers = any(item.type in verifier_type_names for item in project.items.values())
    open_items: list[str] = []
    unverified_items: list[str] = []
    warned_fallback_types: set[str] = set()
    chains_by_claimer = blocked_mod.by_item(project)
    # One bucket per root blocker that accounts for >=1 claimed-but-unsettled
    # item with *exactly one* distinct root -- deliberately conservative,
    # see the aggregate line below.
    unsettled_by_root: dict[str, list[str]] = {}

    for item in project.local_items:
        spec = project.types[item.type]
        coverable, via_fallback = _resolve_coverable(spec, project, warned_fallback_types)
        if not coverable:
            continue
        if _excluded_by_status(item, spec):
            continue

        # Each edge may be declared from either end. resolved_links, not raw
        # links: the raw form can hold `DISPLAY@key` composite text, while the
        # derived form holds a display id or surrogate key reference that
        # `_coverage_for()` resolves through `Project.item_by_ref()`.
        cov = _coverage_for(item, project, chain_graph=chain_graph)
        claimed = cov.claimed_by
        project.coverage[item.id] = cov

        # On the fallback path, only items literally named "requirement" get the
        # two warnings below, matching pre-existing behavior exactly (constraint
        # was always coverable but never got these). Once a type explicitly opts
        # in with `coverable: true`, it gets the same treatment as any other
        # coverable type -- an opt-in improvement, not a compatibility break.
        warn_eligible = not via_fallback or "requirement" in (item.type, spec.extends)

        if cov.stage == "open":
            open_items.append(item.id)
        elif cov.stage == "claimed" and warn_eligible:
            # Every claimer's own blocked_by chain(s), if it has any -- no
            # ambiguity to resolve here, unlike the aggregate line below:
            # this is naming this one item's actual claimer(s) and their
            # actual chain(s), whatever that is.
            notes = []
            claimer_roots: set[str] = set()
            for claimer_id in claimed:
                claimer_chains = chains_by_claimer.get(claimer_id)
                if not claimer_chains:
                    continue
                claimer_roots.update(c.root_id for c in claimer_chains)
                chain_text = "; ".join(
                    f"blocked_by {' <- '.join(c.path[1:])}"
                    + (f" ({c.root_status})" if c.root_status else "")
                    for c in claimer_chains
                )
                notes.append(f"claimed by {claimer_id}, which is {chain_text}")
            message = "claimed but not verified (no test links to it)"
            if notes:
                message += "; " + "; ".join(notes)
            project.warn(
                message, file=item.source_file, line=item.source_line, item_id=item.id,
            )
            # Deliberately conservative: only when every blocked claimer
            # traces to the *same single* root is this item unambiguous
            # enough to fold into the aggregate line -- no chain at all, or
            # several claimers tracing to different roots, is left out and
            # simply keeps the per-item warning above.
            if len(claimer_roots) == 1:
                unsettled_by_root.setdefault(next(iter(claimer_roots)), []).append(item.id)
        elif cov.stage == "satisfied" and warn_eligible and has_verifiers:
            unverified_items.append(item.id)

    if open_items:
        project.warn(
            f"{len(open_items)} item(s) with no coverage — see coverage.html"
        )
    if unverified_items:
        project.warn(
            f"{len(unverified_items)} requirement(s) satisfied but not verified "
            f"— see coverage.html"
        )
    for root_id, items in sorted(unsettled_by_root.items()):
        root = project.item_by_id(root_id)
        status = root.fields.get("status") if root else None
        status_text = f" is {status}" if status else " is unsettled"
        project.warn(
            f"{len(items)} requirement(s) unsettled because {root_id}{status_text} "
            f"— see coverage.html"
        )


# ----------------------------------------------------------------------------- calc


def _calc_reference_targets(item) -> list[str]:
    """The target strings of every cross-item reference in this item -- calc
    blocks and inline calc spans -- fence lines first, then spans, each group
    in source order, deduped: the dependency edges the scheduler walks.
    Parsed with the same regexes `evaluate_block` uses (pipe unit stripped
    first; a span's whole right-hand side must be the reference, same
    `CROSS_REF_RE` as the evaluator), so a line is a dependency edge here
    exactly when it is a reference there -- run-12
    F12-5: an edge from a fence line only was the gap that let a span
    reference run before its target's calc."""
    targets: list[str] = []
    for block in calc.extract_blocks(item.body):
        for raw_line in block.splitlines():
            line = raw_line.partition("#")[0].rstrip()
            if not line.strip():
                continue
            pipe = calc.PIPE_UNIT_RE.match(line)
            if pipe:
                line = pipe.group("lhs").rstrip()
            match = calc.ASSIGN_RE.match(line)
            if not match:
                continue
            ref = calc.CROSS_REF_RE.match(match.group(2).strip())
            if ref and ref.group("target") not in targets:
                targets.append(ref.group("target"))
    for span in inline_calc.triggered_spans(item.body):
        ref = inline_calc.span_cross_ref(span)
        if ref and ref.group("target") not in targets:
            targets.append(ref.group("target"))
    return targets


def _calc_field_reference_targets(item) -> list[str]:
    """The target strings of every *field* reference (`TARGET.$field`, fence
    lines and inline spans) in this item, fence lines first, deduped. The
    scheduler deliberately never walks this list: a field reference reads the
    target item's saved fields, not its evaluated calc env, so it creates no
    dependency edge -- including the self-reference `ITEM.$field` in ITEM
    itself, which is why a field reference into one's own item is not a
    cycle (a bare self-reference keeps its edge, and its cycle). This list
    exists for the expansion plan (a field reference's target half gets the
    same `DISPLAY-ID@key` expansion as a bare reference) and for the content
    hash, where the target half is reduced to the same token while the field
    *value* never enters `calc_refs` (see `_calc_refs_hash_value`)."""
    targets: list[str] = []
    for block in calc.extract_blocks(item.body):
        for raw_line in block.splitlines():
            line = raw_line.partition("#")[0].rstrip()
            if not line.strip():
                continue
            pipe = calc.PIPE_UNIT_RE.match(line)
            if pipe:
                line = pipe.group("lhs").rstrip()
            match = calc.ASSIGN_RE.match(line)
            if not match:
                continue
            ref = calc.FIELD_REF_RE.match(match.group(2).strip())
            if ref and ref.group("target") not in targets:
                targets.append(ref.group("target"))
    for span in inline_calc.triggered_spans(item.body):
        ref = inline_calc.span_field_ref(span)
        if ref and ref.group("target") not in targets:
            targets.append(ref.group("target"))
    return targets


def _calc_fence_reference_targets(item) -> set[str]:
    """The target strings of this item's fenced cross-item references -- bare
    and field (`TARGET.$field`) forms alike -- only (the
    `calc.extract_blocks` loop of `_calc_reference_targets`, field lines
    included; feeds the expansion plan's span-only skip, and a field
    reference's rewrite is the same file-line edit)."""
    targets: set[str] = set()
    for block in calc.extract_blocks(item.body):
        for raw_line in block.splitlines():
            line = raw_line.partition("#")[0].rstrip()
            if not line.strip():
                continue
            pipe = calc.PIPE_UNIT_RE.match(line)
            if pipe:
                line = pipe.group("lhs").rstrip()
            match = calc.ASSIGN_RE.match(line)
            if not match:
                continue
            rhs = match.group(2).strip()
            ref = calc.CROSS_REF_RE.match(rhs) or calc.FIELD_REF_RE.match(rhs)
            if ref:
                targets.add(ref.group("target"))
    return targets


def _calc_span_reference_targets(item) -> set[str]:
    """The target strings of this item's inline-span cross-item references
    -- bare and field (`TARGET.$field`) forms alike -- only -- the subset of
    `_calc_reference_targets` whose rewrite is a span
    *content* replacement. The expansion plan drops these (and only these --
    a target a fenced reference also uses stays, its fence rewrite being a
    file-line edit) for an item whose body has no file position
    (`body_line is None`, e.g. an item body built from a YAML/list file):
    the span scan needs body geometry the file lines cannot supply, so the
    write-back can never apply them, and promising an expansion in the
    `--no-write` report that no write applies is worse than not counting it.
    The references still resolve, evaluate and hash -- only the composite
    expansion skips them."""
    return {
        ref.group("target")
        for span in inline_calc.triggered_spans(item.body)
        if (
            ref := (
                inline_calc.span_cross_ref(span) or inline_calc.span_field_ref(span)
            )
        )
        is not None
    }


def _calc_ref_display(target_str: str, target) -> str:
    """How a reference target is named in a diagnostic: the live item's current
    display id (never the raw composite text, per docs/design/keys.md §3),
    falling back to the authored text when nothing resolves."""
    if target is not None:
        return target.id or target.key
    return target_str.partition("@")[0] or target_str


def _make_calc_resolver(
    project: Project,
    by_key: dict[str, Item],
    warnings: list[str] | None = None,
    fields_overlay: tuple[Item, dict] | None = None,
):
    """The resolver a cross-item reference line calls, bound to the referring
    item's evaluation. Resolution is by key half only (`resolve_link_target`,
    docs/design/keys.md §3) -- the display half is refreshed by
    links.expand_missing_calc_refs and is never consulted here. Every failure
    raises CalcError with the message the referring line reports: file, line,
    and item id come from the caller's diagnostic, exactly like any other
    calc error. There is no silent default and no stale value on any path.

    A `$`-prefixed name half (`Rds = DEC-PWR-001.$rds_on`) reads the target's
    saved FIELD, not its calc env: no evaluation ordering is needed for a
    field (the scheduler creates no edge for it), so the read goes straight
    to `target.fields`, validated against the target's declared type --
    undeclared, empty, list-valued and non-quantity field values are all
    loud errors naming the field. With ``warnings``, a bare reference whose
    target has BOTH a calc value and a field of that name appends the
    collision warning here (the calc value is what resolves -- the field
    needs the explicit `$` spelling).

    ``fields_overlay`` is the live preview's draft bag (design §3.2/§3.4,
    item G1): an `(item, fields)` pair whose field reads, and ONLY its,
    resolve against `{**saved, **fields}` -- the item being edited, read as
    the author has typed it. Identity, not id-matching: a reference to a
    composite key of the same item resolves to the same object through
    `by_key` and is overlaid. Every other target reads saved."""

    def field_value(target, display: str, reference: str, field: str) -> calc.Value:
        spec = project.types.get(target.type)
        declared = sorted(spec.fields) if spec is not None else []
        listing = (
            "it declares: " + ", ".join(declared) if declared
            else "it declares no fields"
        )
        if field not in declared:
            raise calc.CalcError(
                f"cross-item reference {reference!r}: {display} has no field "
                f"{field!r} ({listing})"
            )
        if spec.fields[field].type in NON_SCALAR_FIELD_TYPES:
            raise calc.CalcError(
                f"cross-item reference {reference!r}: {display}'s field "
                f"{field!r} is a list-valued field; field references read a "
                "single quantity, and lists are out of scope"
            )
        fields = target.fields or {}
        if fields_overlay is not None and target is fields_overlay[0]:
            fields = {**fields, **fields_overlay[1]}
        value = fields.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise calc.CalcError(
                f"cross-item reference {reference!r}: {display}'s field "
                f"{field!r} is empty -- give it a quantity ({listing})"
            )
        try:
            return calc.parse_quantity(str(value))
        except calc.CalcError as exc:
            raise calc.CalcError(
                f"cross-item reference {reference!r}: {display}'s field "
                f"{field!r} is {str(value)!r}, not a quantity ({exc})"
            )

    def resolve(reference: str) -> calc.Value:
        target_str, _, name = reference.rpartition(".")
        target = resolve_link_target(by_key, project, target_str)
        if target is None:
            if "@" in target_str or _is_bare_key_token(target_str):
                raise calc.CalcError(
                    _unknown_key_message(project, f"calc reference {reference!r}", target_str)
                )
            raise calc.CalcError(
                f"no item {target_str!r} -- cross-item reference {reference!r} "
                "names an item that does not exist"
            )
        display = _calc_ref_display(target_str, target)
        if target.external:
            raise calc.CalcError(
                f"cross-item reference {reference!r} points at {display}, an "
                "imported item; references into imported items are not supported"
            )
        if name.startswith("$"):
            # A field reference reads the saved item, so the target's own
            # calc state is none of its business -- no `_calc_failed` gate
            # here, and none for the scheduler's benefit either (no edge).
            return field_value(target, display, reference, name[1:])
        if getattr(target, "_calc_failed", False):
            # One root error was already reported at the item that broke; a
            # dependent restates it in one line rather than a second confusing
            # "unknown name" cascade (the blocked.py one-root-many-notes shape).
            raise calc.CalcError(
                f"cannot resolve {reference!r}: {display}'s own calc failed"
            )
        # `not hasattr(target, "_env")` is unreachable here: the scheduler
        # walks `_calc_reference_targets`, which names every cross-item
        # reference of the item -- fence lines and inline spans alike -- so
        # a resolvable, non-external, non-failed target is always evaluated
        # (or cycle-marked, caught above) before this resolver runs. Run-12
        # F12-5's "has not been evaluated yet" message died with the gap.
        value = target._env.get(name)
        if value is None:
            defined = sorted(target._env)
            listing = (
                "it defines: " + ", ".join(defined) if defined
                else "it defines no calc values"
            )
            raise calc.CalcError(
                f"cross-item reference {reference!r}: {display} does not "
                f"define {name!r} ({listing})"
            )
        if warnings is not None:
            spec = project.types.get(target.type)
            if (
                spec is not None
                and name in spec.fields
                and name in (target.fields or {})
            ):
                # The decided policy warns whenever BOTH exist -- empty,
                # null and list-valued fields included. The `$` spelling is
                # only suggested where it can actually read the field.
                scalar = spec.fields[name].type not in NON_SCALAR_FIELD_TYPES
                hint = (
                    " -- write " + f"{display}.$" + f"{name} to read the field"
                    if scalar
                    else " -- this field is list-valued, so no reference reads it"
                )
                warnings.append(
                    f"{display} has both a calc value {name!r} and a field "
                    f"{name!r}; the reference reads the calc value{hint}"
                )
        return value

    return resolve


def _make_source_resolver(
    project: Project,
    item,
    records: dict,
    resolved: dict,
    uses: list,
):
    """The resolver a `source("path", "key")` line calls: authorization by the
    same-item citation rule, then the value the lockfile pinned. It never opens
    the cited file (docs/design/calc-sources.md §5) -- a file that changed
    since the pin is `citations.verify()`'s loud warning, and the value stays
    the reviewed one until `refdes fetch --update` accepts the change.

    `resolved` maps the authored (path, key) to (canonical path, locked text or
    None) for the row's provenance badge; `uses` accumulates every use for the
    content hash, `None` standing for a value that did not resolve. The span
    form is the same call with the same advice: `collect_source_uses` reads
    spans too (slice 2), so `refdes fetch` pins what a span names, and the
    run-12 F12-6 fence-form-only dead end is gone.
    """

    def resolve(path: str, key: str) -> str:
        canon, problem = citations_mod.authorize_source_path(project, item, path)
        if problem:
            uses.append((path, key, None))
            raise calc.CalcError(f"source({path!r}, {key!r}): {problem}")
        text = citations_mod.locked_source_value(records.get(canon), key)
        resolved[(path, key)] = (canon, text)
        uses.append((canon, key, text))
        if text is None:
            raise calc.CalcError(
                f"source({path!r}, {key!r}) has no locked value -- run "
                f"'refdes fetch --path {canon}' to extract and pin it"
            )
        return text

    return resolve


def _run_inline_span(project: Project, item, span, env, origins) -> bool:
    """Evaluate one triggered inline calc span and verify its stored result
    (docs/design/inline-calc.md slice 1). Returns True when the span
    reported an error.

    The RHS runs through the existing evaluator as the fence line
    `name = rhs | unit` -- same grammars, same restrictions, the same
    item-wide `env` and `origins`, which is what makes an inline `:=`
    assign into the fence scope and a duplicate name fire across the two
    spellings. The stored result is verified numerically against the
    evaluated value (section 2); a stale result is a warning, a missing
    one a parse error, and neither ever edits the source (D1)."""
    line_number = (
        item.body_line + span.line_offset
        if item.body_line is not None else item.source_line
    )
    label = span.name or span.raw.strip()

    def report_error(message: str) -> None:
        project.error(
            f"inline calc {label}: {message}",
            file=item.source_file, line=line_number, item_id=item.id,
        )

    if span.error:
        report_error(span.error)
        return True

    expression = f"{span.name} = {span.rhs}"
    if span.unit:
        expression += f" | {span.unit}"

    failed = False
    for outcome in calc.evaluate_block(
        expression, env, start_line=line_number, origins=origins
    ):
        if outcome.warning:
            project.warn(
                f"inline calc {label}: {outcome.warning}",
                file=item.source_file, line=line_number, item_id=item.id,
            )
        if outcome.error:
            report_error(outcome.error)
            failed = True
            continue
        if outcome.value is None:
            continue
        try:
            result = calc.format_value(outcome.value, project.sigfigs)
        except Exception as exc:  # noqa: BLE001 -- pint raises many types
            report_error(f"the value could not be formatted: {exc}")
            failed = True
            continue
        item.calc_values[outcome.name] = result
        try:
            stale = inline_calc.compare_stored(outcome.value, span, result)
        except calc.CalcError as exc:
            report_error(str(exc))
            failed = True
            continue
        if stale:
            project.warn(
                f"inline calc {label}: {stale}",
                file=item.source_file, line=line_number, item_id=item.id,
                code=INLINE_CALC_STALE,
            )
    return failed


def _run_item_calcs(project: Project, item, by_key: dict[str, Item]) -> None:
    """Evaluate one item's calc blocks -- the per-item half of run_calcs,
    extracted so the scheduler can call it in dependency order. `item._env`
    is populated here and cached; the scheduler guarantees every item this
    one references has already been evaluated (or failed) before it runs."""
    # The same pair the scheduler's entry writes: a memoised read's records
    # and its problem travel together, or a poisoned `{}` reads as "nothing
    # is pinned" (serve/sources.py `_lockfile`).
    records = getattr(project, "_source_lock", None)
    if records is None:
        records, problem = citations_mod.read_lockfile(project)
        project._source_lock = records
        project._lockfile_problem = problem
    source_resolved: dict[tuple[str, str], tuple[str, str | None]] = {}
    item._source_uses = []
    calc_warnings: list[str] = []

    def field_fields(target_str: str) -> list[str]:
        # The declared, identifier-style field names of a reference target --
        # what the non-identifier field-name error lists (calc.py
        # FIELD_FIELDS_KEY). Best effort: an unresolvable target lists nothing.
        target = resolve_link_target(by_key, project, target_str)
        spec = project.types.get(target.type) if target is not None else None
        if spec is None:
            return []
        return sorted(
            name
            for name in spec.fields
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        )

    env: dict[str, calc.Value] = {
        calc.RESOLVER_KEY: _make_calc_resolver(project, by_key, calc_warnings),
        calc.SOURCE_RESOLVER_KEY: _make_source_resolver(
            project, item, records, source_resolved, item._source_uses
        ),
        calc.CALC_WARNINGS_KEY: calc_warnings,
        calc.FIELD_FIELDS_KEY: field_fields,
    }
    # name -> line first assigned, threaded across every block of this item
    # exactly like `env` -- what lets evaluate_block catch a name reused in
    # a later block, not just within one block. The duplicate-name rule is
    # untouched by cross-item references: a reference binds a name exactly as
    # an assignment does, so `origins` fires if an item both references a
    # name and assigns it.
    origins: dict[str, int | None] = {}
    item_sealed: bool | None = None  # lazy: only retired lines ask the seal files
    failed = False
    # The fence info string is a grammar now, not a shrug (docs/design/
    # named-calc-blocks.md §3.4): every invalid fence is a build error at the
    # fence line's file:line, with the §7 message naming the fix.
    for fence_offset, fence_msg in calc.fence_errors(item.body):
        fence_line = (
            item.body_line + fence_offset
            if item.body_line is not None else item.source_line
        )
        project.error(
            fence_msg, file=item.source_file, line=fence_line, item_id=item.id
        )
        failed = True
    # An HTML comment suppresses the inline spans under it (run-12 F12-1),
    # so an unclosed `<!--` must not silently stop them being checked: warn
    # once at the opener's line, the shape of the unclosed-fence warning.
    comment_offset = inline_calc.unclosed_comment_offset(item.body)
    if comment_offset is not None:
        project.warn(
            inline_calc.UNCLOSED_COMMENT_WARNING,
            file=item.source_file,
            line=(
                item.body_line + comment_offset
                if item.body_line is not None else item.source_line
            ),
            item_id=item.id,
        )
    # Block names are unique per item, not per project (§11.2 decided):
    # the same shape as the value-name rule `origins` enforces below.
    named_fences: dict[str, int] = {}
    for _block, offset, block_id in calc.extract_blocks_with_lines(item.body):
        if block_id is None:
            continue
        fence_line = (
            item.body_line + offset - 1
            if item.body_line is not None else item.source_line
        )
        first = named_fences.get(block_id)
        if first is not None:
            project.error(
                f"calc block '{block_id}' is named twice in this item -- first "
                f"at line {first}, again at line {fence_line}. A block name can "
                "only be used once per item (values already share one item-wide "
                f"scope); rename one of them, e.g. '{block_id}' -> '{block_id}_2'.",
                file=item.source_file, line=fence_line, item_id=item.id,
            )
            failed = True
        else:
            named_fences[block_id] = fence_line
    # Inline calc spans and calc fences run as one source-ordered pass:
    # an inline `:=` assigns into the same item-wide env, so a later
    # fence sees the name and a later span sees a fence name, and the
    # `origins` registry catches a duplicate across the two spellings
    # (docs/design/inline-calc.md section 1). A span's line offset can
    # never collide with a fence's first-content offset: every line
    # between a fence's opener and its closer is fenced code, which the
    # span walk never reads.
    events = [
        (offset, (block, block_id))
        for block, offset, block_id in calc.extract_blocks_with_lines(item.body)
    ]
    events += [
        (span.line_offset, span)
        for span in inline_calc.triggered_spans(item.body)
    ]
    events.sort(key=lambda event: event[0])
    for _offset, event in events:
        if isinstance(event, inline_calc.InlineSpan):
            if _run_inline_span(project, item, event, env, origins):
                failed = True
            continue
        block, block_id = event
        start_line = item.body_line + _offset if item.body_line is not None else None
        for outcome in calc.evaluate_block(block, env, start_line=start_line, origins=origins):
            line = CalcLine(
                name=outcome.name,
                expression=outcome.expression,
                comment=outcome.comment,
                annotation=outcome.annotation,
                unit_style=outcome.unit_style,
                line=outcome.line,
                reference=outcome.reference,
                block=block_id or "",
            )
            if outcome.source is not None:
                canon, locked = source_resolved.get(outcome.source, ("", None))
                line.source_path = canon or outcome.source[0]
                line.source_key = outcome.source[1]
                line.source_locked = locked or ""
            diag_line = outcome.line if outcome.line is not None else item.source_line
            if outcome.warning:
                project.warn(
                    f"calc {outcome.name}: {outcome.warning}",
                    file=item.source_file, line=diag_line, item_id=item.id,
                )
            if outcome.error:
                if outcome.retired:
                    if item_sealed is None:
                        item_sealed = seal.is_sealed(project, item)
                    if item_sealed:
                        # A sealed append-only entry cannot be edited
                        # without resealing, and resealing is what Jared
                        # wants to avoid: the retired spelling inside one
                        # warns with the same text instead of failing the
                        # build, and stays working (evaluated above) until
                        # history-backed resealing lands.
                        project.warn(
                            f"calc {outcome.name}: {outcome.error}",
                            file=item.source_file, line=diag_line, item_id=item.id,
                        )
                    else:
                        line.error = outcome.error
                        failed = True
                        project.error(
                            f"calc {outcome.name or outcome.expression!r}: {outcome.error}",
                            file=item.source_file, line=diag_line, item_id=item.id,
                            code=RETIRED_UNIT_SPELLING,
                        )
                else:
                    line.error = outcome.error
                    failed = True
                    project.error(
                        f"calc {outcome.name or outcome.expression!r}: {outcome.error}",
                        file=item.source_file, line=diag_line, item_id=item.id,
                    )
            if outcome.value is not None:
                # Formatting runs on a value the evaluator already accepted, so
                # it sits outside the handler that turns an *evaluation* failure
                # into a line error -- and a formatter failure used to abort the
                # whole command with a traceback naming no file and no line (the
                # `sqrt(-1)` complex-magnitude bug). Whatever it raises is still
                # this line's problem, so it is reported like every other calc
                # error and the build continues to the next line.
                try:
                    result = calc.format_value(outcome.value, project.sigfigs)
                    bounds = calc.format_bounds(outcome.value, project.sigfigs)
                except Exception as exc:  # noqa: BLE001 -- pint raises many types
                    failed = True
                    message = f"the value could not be formatted: {exc}"
                    if not line.error:
                        line.error = message
                    project.error(
                        f"calc {outcome.name or outcome.expression!r}: {message}",
                        file=item.source_file, line=diag_line, item_id=item.id,
                    )
                else:
                    line.result = result
                    line.bounds = bounds
                    item.calc_values[outcome.name] = result
            item.calcs.append(line)
    del env[calc.RESOLVER_KEY]
    del env[calc.SOURCE_RESOLVER_KEY]
    del env[calc.CALC_WARNINGS_KEY]
    del env[calc.FIELD_FIELDS_KEY]
    item._env = env  # retained for check evaluation and cross-item references
    item._calc_failed = failed


PREVIEW_SPAN_LIMIT = 200
"""Max triggered spans one live-editor calc preview evaluates
(in-prog-logs/inline-calc-live-editor-design-20261020.md §3.3): the route stops
at the first 200 in source order and flags `truncated`; per-span cost is
~0.15-0.35 ms, so a request is bounded tens of ms regardless of body size."""


def preview_inline_spans(
    project: Project, item, body_text: str, *, fields: dict | None = None
) -> list[dict]:
    """Evaluate one item body's inline calc spans for the live editor's
    read-only preview route (`POST /api/item/<ref>/calc`,
    in-prog-logs/inline-calc-live-editor-design-20261020.md §3.4): a
    side-effect-free sibling of `_run_item_calcs` over `body_text` -- the
    author's unsaved draft.

    The pass mirrors `_run_item_calcs`'s shape (fences and spans as one
    source-ordered event list, the same resolvers), so a span may use a
    name a fence defines earlier in the same draft and the duplicate-name
    rule fires exactly as at build. What it must not touch is every
    mutation `_run_inline_span` makes: no `project.error`/`project.warn`
    (the verdict stays the build's), no `item.calc_values`, `item.calcs`,
    `item._source_uses`, `item._env`, no lockfile write, no disk. Locals
    own `env`, `origins`, and the source resolver's `resolved`/`uses`; the
    memoised `project._source_lock` is read, never re-read into the
    project. Cross-item references resolve against the snapshot's cached
    `_env`s, exactly as a build resolves them.

    `fields` is the editor's draft-field bag (§3.3): the item being edited
    is read with it overlaid on its saved fields -- a span of this item
    naming its own field (`DEC-001.$rds_on`) computes with the value the
    author typed, not the value on disk -- while every other item keeps
    reading saved (§3.2's limit: the bag describes THIS item). The overlay
    is a local merge inside the resolver; `item.fields` is never mutated,
    and the pass stays as side-effect-free as the rest of the preview.

    `line`/`start`/`end` are coordinates within `body_text` (the route's
    contract), not file lines. The one deliberate message divergence from
    the build: messages are the R12 vocabulary verbatim EXCEPT embedded
    line numbers -- the duplicate-name diagnostic's "first at line N,
    again at line M" -- which are body-relative here (`start_line`
    threaded into the evaluator is the 1-based line of `body_text`) and
    file-relative at the build (front matter offsets them by
    `item.body_line - 1`). Body-relative is the panel's coordinate space:
    the number must name a line of the text the author is looking at, and
    a frontmatter item's build numbers (file lines) are the ones that do
    not. At most the first `PREVIEW_SPAN_LIMIT` triggered spans are
    evaluated, in source order; the route reports the truncation (§3.3).
    """
    by_key = _key_index(project)
    # The collision warnings and the declared-fields listing ride the same
    # env hooks `_run_item_calcs` installs, so the resolver's vocabulary --
    # the hyphenated-field-name error's "the item type declares: ..." --
    # is the build's here too. Warnings are collected and dropped: the row
    # schema is three-status (§3.3), and the overlay never feeds the
    # collision check, which reads the target's SAVED fields (the check
    # pass warns on the same reference the same way).
    calc_warnings: list[str] = []

    def field_fields(target_str: str) -> list[str]:
        target = resolve_link_target(by_key, project, target_str)
        spec = project.types.get(target.type) if target is not None else None
        if spec is None:
            return []
        return sorted(
            name
            for name in spec.fields
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        )

    records = getattr(project, "_source_lock", None)
    if records is None:
        # An unbuilt project has no memo. Reading the lockfile is itself
        # read-only, so the preview asks for it; unlike a build it never
        # memoises onto the project.
        records, _problem = citations_mod.read_lockfile(project)
    env: dict[str, calc.Value] = {
        calc.RESOLVER_KEY: _make_calc_resolver(
            project, by_key, calc_warnings,
            fields_overlay=(item, fields) if fields else None,
        ),
        calc.SOURCE_RESOLVER_KEY: _make_source_resolver(project, item, records, {}, []),
        calc.CALC_WARNINGS_KEY: calc_warnings,
        calc.FIELD_FIELDS_KEY: field_fields,
    }
    origins: dict[str, int | None] = {}
    events: list[tuple[int, tuple]] = [
        (offset, ("fence", (block, offset)))
        for block, offset, _block_id in calc.extract_blocks_with_lines(body_text)
    ]
    events += [
        (line_offset, ("span", (start, end, content)))
        for line_offset, start, end, content in inline_calc.triggered_span_events(
            body_text.splitlines()
        )
    ]
    events.sort(key=lambda event: event[0])
    rows: list[dict] = []
    for _offset, (kind, payload) in events:
        if kind == "fence":
            # Evaluate the draft's fences to give their names to later
            # spans (the duplicate-name rule fires across the two
            # spellings exactly as at build); fence diagnostics are not
            # reported -- the save-time 422 owns fences (§3.3).
            calc.evaluate_block(payload[0], env, start_line=payload[1] + 1, origins=origins)
            continue
        if len(rows) >= PREVIEW_SPAN_LIMIT:
            break
        start, end, content = payload
        rows.append(
            _preview_inline_span(project, env, origins, _offset, start, end, content)
        )
    return rows


def _preview_inline_span(
    project: Project,
    env: dict,
    origins: dict,
    line_offset: int,
    start: int,
    end: int,
    content: str,
) -> dict:
    """One span's preview row
    (in-prog-logs/inline-calc-live-editor-design-20261020.md §3.3):
    status/message verbatim from the same parse/eval/compare calls the
    build makes -- the panel teaches `refdes check`'s vocabulary, not a
    second one -- with positions in `body_text` line coordinates. The one
    divergence: line numbers embedded in a message (the duplicate-name
    diagnostic) are body-relative, not the file-relative numbers the build
    reports for a frontmatter item, because the panel must name a line of
    the text the author is editing. `outcome.warning` (e.g. the
    unit-collision warning the build reports as an `inline calc` warning)
    is deliberately not surfaced: the row schema is three-status, and the
    save/build diagnostics own warnings. The result-slot range is absent
    when the span has no parseable result slot (B2's `result_col`);
    auto-fill and Fill are then unavailable for it."""
    span = inline_calc.parse_span(line_offset, content)
    label = span.name or span.raw.strip()

    row: dict = {"line": line_offset, "start": start, "end": end}
    if span.result_col is not None:
        pos = content.find(span.result, span.result_col)
        if pos >= 0:
            row["result_start"] = start + pos
            row["result_end"] = start + pos + len(span.result)
    row["name"] = label

    def finish(status: str, computed: str, message: str) -> dict:
        row["status"] = status
        row["computed"] = computed
        row["message"] = f"inline calc {label}: {message}" if message else ""
        return row

    if span.error:
        return finish("error", "", span.error)
    expression = f"{span.name} = {span.rhs}"
    if span.unit:
        expression += f" | {span.unit}"
    for outcome in calc.evaluate_block(
        expression, env, start_line=line_offset + 1, origins=origins
    ):
        if outcome.error:
            return finish("error", "", outcome.error)
        if outcome.value is None:
            continue
        try:
            computed = calc.format_value(outcome.value, project.sigfigs)
        except Exception as exc:  # noqa: BLE001 -- pint raises many types
            return finish("error", "", f"the value could not be formatted: {exc}")
        try:
            stale = inline_calc.compare_stored(outcome.value, span, computed)
        except calc.CalcError as exc:
            return finish("error", "", str(exc))
        return finish("stale" if stale else "ok", computed, stale or "")
    return finish("error", "", "the span produced no value")


def run_calcs(project: Project) -> None:
    """Evaluate every local item's calc blocks and inline calc spans in
    dependency order.

    A cross-item reference (`V_in = DEC-PWR-001.V_in`, finding 35) makes the
    per-item passes of the past a graph over items: the reference edges are
    walked first and each item is evaluated only after everything it reads
    from, so a target's `env` is ready when the resolver asks for it. The edges
    come from fence lines *and* inline span references
    (docs/design/inline-calc.md section 3), so a reference lives in whichever
    form an author chose. Each item's env is computed exactly once and cached
    on the item (`_env`), which is the whole state, so the scheduler is a
    memoised DFS post-order and `run_checks` keeps finding `_env` where it
    always did.

    A cycle is an error naming the full path (`a -> b -> a`), following the
    `blocked_by cycle:` (blocked.py) and `equation cycle:` (calc.py) shapes.
    Every item in a cycle is marked failed and never evaluated; a dependent
    outside the cycle gets one note naming the upstream failure rather than
    N restatements of it."""
    by_key = _key_index(project)
    # Records and problem are memoised as one pair, from one read: a memo
    # reader (the serve source picker) must never see one read's records
    # beside another read's problem -- a `{}` from a failed read trusted
    # alone claims every citation unpinned (serve/sources.py `_lockfile`).
    project._source_lock, project._lockfile_problem = citations_mod.read_lockfile(project)
    # Identity -> "visiting" (on the current DFS path) or "done" (env ready
    # or failed). Items are unhashable-by-value here, so id() is the key.
    state: dict[int, str] = {}
    reported_cycles: set[tuple[int, ...]] = set()

    def visit(item, path: list) -> None:
        mark = state.get(id(item))
        if mark == "done":
            return
        if mark == "visiting":
            cycle = [*path[path.index(item):], item]
            key = tuple(id(i) for i in cycle)
            if key not in reported_cycles:
                reported_cycles.add(key)
                closer = path[-1]  # the item whose reference closes the loop
                names = " -> ".join(i.id or i.key for i in cycle)
                project.error(
                    f"calc reference cycle: {names}",
                    file=closer.source_file, line=closer.source_line,
                    item_id=closer.id or closer.key,
                )
            for node in cycle:
                node._calc_failed = True
                node._env = {}
            return
        state[id(item)] = "visiting"
        for target_str in _calc_reference_targets(item):
            target = resolve_link_target(by_key, project, target_str)
            if target is None or target.external:
                # Reported at the reference line when the item itself runs;
                # not a schedulable edge.
                continue
            visit(target, [*path, item])
        state[id(item)] = "done"
        if getattr(item, "_calc_failed", False):
            # A cycle member: never evaluated, so its own references stay
            # unreported and its dependents get the one-line upstream note.
            return
        _run_item_calcs(project, item, by_key)

    for item in project.local_items:
        visit(item, [])


_CHECK_EMITTERS = {ERROR: Project.error, WARNING: Project.warn, INFO: Project.info}


def _severity_for(spec, item) -> str:
    """Resolve one item's `check_severity` (docs/design/candidate-parts.md §4.2).

    A scalar spec is that value, no other code path -- projects that never use
    the mapping form see byte-identical behaviour (§4.6). A mapping spec
    selects by the item's `status` field. Load-time validation guarantees the
    mapping covers every declared status or declares `default:`, so the
    fallback here only guards a status the schema cannot produce (a missing
    field value), where `error` is the safe reading."""
    severity = spec.check_severity if spec is not None else ERROR
    if isinstance(severity, dict):
        status = str((item.fields or {}).get("status", ""))
        return severity.get(status, severity.get("default", ERROR))
    return severity


def run_checks(project: Project) -> None:
    by_key = _key_index(project)
    for item in project.local_items:
        spec = project.types.get(item.type)
        check_severity = _severity_for(spec, item)
        # A failing check on a candidate item (check_severity: info) is the
        # finding, not a defect -- everything else about a `checks:` entry
        # (malformed shape, an unresolved target, a target with no limit) is a
        # real authoring mistake regardless of type, so those stay project.error.
        emit_violation = _CHECK_EMITTERS.get(check_severity, Project.error)

        entries = item.fields.get("checks") or []
        if not isinstance(entries, list):
            project.error(
                "checks: must be a list of {value, against} entries",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            continue

        env = getattr(item, "_env", {})
        for entry in entries:
            if not isinstance(entry, dict) or "value" not in entry or "against" not in entry:
                project.error(
                    "each checks: entry needs 'value' and 'against'",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue

            # An unknown key inside an entry is the item's own unknown-field
            # mistake one level down, and it is the same class of gap that let
            # a `options:` of bare strings pass `check` and crash `build`. The
            # schema this tool writes for the editor already refuses it --
            # `additionalProperties: false` on exactly this sub-mapping
            # (`schema_json.py`), which is what lights the key up in the editor
            # the moment it is typed -- so saying nothing here leaves the
            # published schema and the enforced one disagreeing.
            #
            # Two tiers, the ones `parse.py:965-992` implements for a field and
            # `docs/authoring.md:267-292` states: a confident near-miss is an
            # error, because that key's value is going nowhere and a warning is
            # not something a green build can be trusted to have caught; a key
            # with nothing close to it stays a warning whose value is kept --
            # forward-compatible metadata, a field a future version declares,
            # deliberate extra data, none of which has a typo to correct.
            #
            # Only an *extra* key reaches here. An entry that lost `value:` or
            # `against:` outright was refused by the shape error just above,
            # which `continue`s, so one keystroke is never reported twice.
            for key in sorted(entry, key=str):
                if key in ("value", "against"):
                    continue
                # `str()` because YAML keys are not necessarily strings: a
                # `true:` or `1:` line here is the bool/int, and handing that
                # to difflib (or sorting it beside the string keys) raises
                # where this should report. A non-string key is unknown by
                # definition -- the legal pair is spelled in letters.
                text = str(key)
                close = difflib.get_close_matches(
                    text, ["value", "against"], n=1, cutoff=0.6
                )
                if close:
                    message = (
                        f"unknown key {text!r} in a checks: entry -- did you "
                        f"mean the key {close[0]!r}? A misspelled key silently "
                        f"drops its value instead of erroring; an entry holds "
                        f"only 'value' and 'against'."
                    )
                    report = project.error
                else:
                    message = (
                        f"unknown key {text!r} in a checks: entry -- it holds "
                        f"only 'value' and 'against', and this one is ignored"
                    )
                    report = project.warn
                report(
                    message,
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )

            name, target_id = str(entry["value"]), str(entry["against"])

            # `against:` accepts a bare display id, a bare key, or a
            # `DISPLAY-ID@key` composite, resolved exactly as a structured
            # link target is (docs/design/keys.md §3) -- reusing
            # resolve_link_target and the same Layer 1/3 diagnostics rather
            # than re-implementing either. That includes the *gate*: the key
            # half of Layer 1/3 runs on a key-shaped token with no `@` too,
            # exactly as `resolve_links` and the calc resolver do. Gating on
            # `@` alone left a bare key reported as a plain dangling id --
            # a typo's remedy for a corrupt key, and `keys restore`'s
            # diagnostic replaced by a dead end for an unknown one, while
            # the same key in the item's own `links:` got the key text
            # (docs/design/keys.md's Layer 3: one diagnostic for all three
            # reference shapes).
            bare_key = _is_bare_key_token(target_id)
            if "@" in target_id or bare_key:
                label, _, key = target_id.partition("@")
                if bare_key:
                    key = target_id
                malformed = keys_mod.malformed_key_message(
                    key,
                    context=(
                        f" in check against target (labelled {label})"
                        if "@" in target_id
                        else " in check against target"
                    ),
                )
                if malformed is not None:
                    project.error(
                        malformed,
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                    item.checks.append(CheckResult(value_name=name, against=target_id))
                    continue

            target = resolve_link_target(by_key, project, target_id)
            # Diagnostics and rendering always show the target's current
            # display id, never the raw composite text (docs/design/keys.md
            # §3) -- a rename refreshes the stored label, not the result of
            # a single build's resolution.
            display_against = target.id if target is not None else target_id
            result = CheckResult(value_name=name, against=display_against)

            if target is None:
                if "@" in target_id or bare_key:
                    key = target_id if bare_key else target_id.partition("@")[2]
                    result.detail = f"key {key!r} does not resolve"
                    message = _unknown_key_message(project, "check against", target_id)
                else:
                    result.detail = f"{target_id} does not exist"
                    message = _dangling_bare_message(
                        "check against", target_id, "`against:`"
                    )
                project.error(
                    message,
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif name not in env:
                result.detail = f"no calc value named {name!r} in this item"
                project.error(
                    f"check refers to {name!r}, which no calc block defines",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif not target.fields.get("limit"):
                result.detail = f"{display_against} has no 'limit' to check against"
                project.error(
                    f"check against {display_against}, which declares no limit",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            else:
                try:
                    limit = calc.parse_limit(str(target.fields["limit"]))
                    ok, detail = limit.check(env[name], project.sigfigs)
                    result.ok, result.detail = ok, detail
                    result.actual = calc.format_value(env[name], project.sigfigs)
                    result.limit = limit.text
                    result.margin = limit.margin(env[name])
                    if not ok:
                        message = f"{name} violates {display_against}: {detail}"
                        if env[name].has_width and limit.kind in ("<=", "<", ">=", ">"):
                            message += f" (nominal {result.actual})"
                        emit_violation(
                            project, message,
                            file=item.source_file, line=item.source_line, item_id=item.id,
                            code=CHECK_VIOLATION,
                        )
                except calc.CalcError as exc:
                    result.detail = str(exc)
                    project.error(
                        f"check {name} against {display_against}: {exc}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )

            item.checks.append(result)


# ------------------------------------------------------------------- content hashing

# Bumped whenever what compute_hashes() feeds into the hash changes in a way
# that would churn every existing hash for a reason unrelated to content.
# Two bumps so far, both docs/design/keys.md §5:
#   2 -- link targets switched from display-id text to resolved keys.
#   3 (2026-09-14) -- `checks: against:` entries that resolve to a keyed
#      item are likewise reduced to that key; an unresolved or keyless
#      target keeps its raw text, same as a link target does.
#   4 (2026-09-21, finding 35) -- an item with cross-item calc references
#      (`V_in = DEC-PWR-001.V_in`) hashes each reference's resolved key and
#      the *value* it resolved to, and hashes its body with the reference's
#      target reduced to that key (docs/design/backlog.md, finding 35 §4).
#      An item with no such reference has the exact same payload as
#      format 3, so no existing item's hash moves. Finding 26's source()
#      values joined this same format number, not a fifth: an item with a
#      `source("path", "key")` calc line also hashes each (canonical path,
#      key, locked decimal text) it resolved (docs/design/calc-sources.md
#      section 9). An item with no source() line is unchanged.
#   5 (2026-09-25, docs/design/editor-image-upload.md §15.6 decided by Jared)
#      -- an item whose body references local images hashes each resolved
#      image's project-relative path and content digest (_image_inputs_hash_
#      value), so replacing the bytes behind a sealed entry's image moves the
#      seal's hash instead of silently changing what the sealed record shows.
#      An item with no image reference has the exact same payload as format 4,
#      so no existing item's hash moves. Image changes that happened *before*
#      an entry was stamped under format <= 4 stay silent -- those records
#      never recorded image digests, and reconstructing formats <= 4 ignores
#      images, which is what keeps the bump from making any existing item or
#      seal look edited (the keys.md §5(c) carry-forward rule).
#   6 (2026-10-19, docs/design/inline-calc.md section 3) -- inline calc spans
#      join the dependency scans and the hash: a span whose whole rhs is a
#      cross-item reference (`v := DEC-001.V_in`) is a real dependency, so the
#      scheduler orders the target first, the reference's resolved key and
#      resolved value enter the calc-reference hash, and the body reduces the
#      reference's target half to that key exactly as a fence line's does. (The
#      source-inputs hash is format 4's own input, counting every source()
#      call the evaluator resolves, so a resolvable span call has fed it since
#      slice 1 made spans evaluable -- the format 5 era; what is new here is
#      that `refdes fetch` *discovers and pins* it, not a hash input.)
#      The arithmetic of every triggered span (name, rhs, unit -- never the
#      author's stored result) joins the narrow arithmetic probe, so an
#      inline-only item finally gets a calc_hash. An item with no triggered
#      span has the exact same payload as format 5, so no existing item's
#      hash moves; spans with only literal arithmetic keep their old content
#      hash (they gain only a probe, which content hashing never sees).
#      Reconstruction of formats <= 5 excludes the span cross-item inputs
#      (span source() values ride `_source_uses` there exactly as they rode
#      the old code's hash), which is what keeps the bump from making any
#      existing baseline entry, seal, or audit look edited (the keys.md §5(c)
#      carry-forward rule -- and it is why the reconstruction also strips an
#      expanded span target back to its display half, restoring the
#      pre-expansion body text the recorded hash was computed from; an
#      author-written composite was hashed as written back then, so the
#      comparison side accepts both readings through keys.hashes_in_format).
# Recorded per baseline entry (lifecycle.py) so a partially-migrated baseline
# stays precisely describable; consulted by the migration in
# lifecycle.py/seal.py/keys.py, never by an ordinary build.
HASH_FORMAT = 6


def _hash_payload(
    item: Item,
    spec: ItemType,
    project: Project,
    link_values,
    checks_values=None,
    calc_refs=None,
    source_inputs=None,
    image_inputs=None,
    strip_inline_composite: bool = False,
    strip_display: dict[str, str] | None = None,
) -> dict[str, object]:
    """Everything compute_hashes() and hash_for_format() have in common: which
    fields/body enter the hash, and under what normalization. The two things
    that differ between hash-format definitions are how a link's *targets*
    turn into hashable values (`link_values`, called once per link name with
    that link's raw target list) and, from format 3 on, how a `checks:`
    entry's `against:` does (`checks_values`, called once with the raw
    `checks:` list; ``None`` leaves `checks:` hashed verbatim, as every
    format before 3 did) and, from format 4 on, how an item's cross-item
    calc references do (`calc_refs`, called once per item, returning
    ``(body_text, resolved_refs)`` or ``None`` for an item with no such
    reference -- which then hashes exactly as it did under format 3, so an
    item that never uses the feature can never churn because of it) and,
    also from format 4 on (finding 26 joined finding 35's bump rather than
    taking a fifth), how an item's `source()` values do (`source_inputs`,
    called once per item, returning a list or ``None`` for an item with no
    `source()` line -- hash-neutral for every item that has none) --
    everything else here is shared, so the hash
    definitions can never drift apart from each other by accident.
    """
    payload: dict[str, object] = {"type": item.type}

    for fname in sorted(item.fields):
        mode = item.on_change_for(fname, spec, project.default_on_change)
        if mode != INVALIDATE:
            continue
        if fname == "checks" and checks_values is not None:
            payload[fname] = checks_values(item.fields[fname])
        else:
            payload[fname] = item.fields[fname]

    for lname in sorted(item.links):
        payload[f"link:{lname}"] = link_values(item.links[lname])

    # Same precedence as fields: item field override > whole-item mode > schema.
    body_mode = item.on_change_for("body", spec, spec.body_on_change)
    if body_mode == INVALIDATE:
        body_text = item.body
        if calc_refs is not None:
            hashed = calc_refs(item)
            if hashed is not None:
                body_text, resolved = hashed
                # The resolved upstream values are arithmetic input -- content
                # of this item, exactly as finding 26 decided for source().
                payload["calc_refs"] = resolved
        if source_inputs is not None:
            inputs = source_inputs(item)
            if inputs is not None:
                # The locked scalar is arithmetic input, so content of this
                # item (docs/design/calc-sources.md section 9): the value the
                # calc used, not the source file's hash -- an unrelated edit to
                # the file must not invalidate this item, and an accepted
                # `fetch --update` that moves the value must.
                payload["source_values"] = inputs
        if image_inputs is not None:
            images = image_inputs(item)
            if images is not None:
                # The bytes behind this body's images are content too
                # (HASH_FORMAT 5, editor-image-upload.md §15.6): a swapped
                # image moves this hash with the text untouched. Absent
                # entirely for a body that references no image, so an
                # image-free item's format-5 payload is its format-4 payload.
                payload["images"] = images
        if strip_inline_composite:
            # Formats <= 5: a triggered span's cross-item reference was
            # invisible to the hash then, so the pre-slice-2 expansion of a
            # span target (`DISPLAY.V_in` -> `DISPLAY@key.V_in` on disk)
            # must not move a reconstruction: reduce it back to the display
            # half, restoring the body text the recorded hash was computed
            # from. The keys.md §5(c) carry-forward rule, third application
            # after links and `against:`. The strip is the inverse of the
            # slice-2 expansion: it is a faithful legacy reading only of a
            # composite whose key half belongs to the item its display half
            # names -- hash_for_format_variants() gates on exactly that,
            # and a key-half-only edit keeps only the as-written reading
            # (the text the format's own code hashed).
            from . import links as links_mod

            span_lines = body_text.splitlines()
            links_mod._calc_ref_rewrites(
                span_lines,
                0,
                len(span_lines),
                {},
                strip_inline_composite=True,
                strip_display=strip_display,
            )
            body_text = "\n".join(span_lines)
        normalized = re.sub(r"\s+", " ", body_text).strip()
        payload["body"] = normalized

    return payload


def _hash_blob(payload: dict[str, object]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _inline_span_calc_text(span: inline_calc.InlineSpan) -> str:
    """One triggered span's arithmetic as the calc_hash probe sees it: name,
    RHS and unit assertion, stored result excluded (docs/design/inline-calc.md
    section 3 -- a result-only edit must leave this probe fixed). A malformed
    span has no meaningful name/RHS/unit, so the probe is its raw text with
    the result portion removed (`inline_calc.resultless_raw`): the raw text
    verbatim would carry the stored result, and a result-only edit of a
    malformed span would move the probe (round-13 review); the build reports
    the span as an error at the line either way."""
    if span.error:
        return inline_calc.resultless_raw(span)
    text = f"{span.name} := {span.rhs}"
    if span.unit:
        text += f" | {span.unit}"
    return text


def calc_hash_for(item: Item) -> str | None:
    """A hash of just item's ```calc block(s) and inline calc spans -- the
    second, narrower probe docs/design/stale-arithmetic-signal.md needs
    alongside content_hash, so lifecycle.diff_against can tell "the calc
    block changed" apart from "the item changed" without storing the block's
    actual text anywhere.

    None (not a hash of an empty payload) when the item has no calc block and
    no inline span at all -- most items -- so lifecycle._items_map can omit
    the baseline field entirely rather than recording a hash that can never
    mean anything.

    Normalized the same way _hash_payload normalizes body text (collapse
    whitespace, strip), so reflowing a calc block's comments or indentation
    doesn't register as the arithmetic having changed. Deliberately reads
    item.body directly rather than item.calcs/calc_values: this hashes the
    block's *source* -- the expressions themselves -- not its evaluated
    results, which is what "the arithmetic" means for this signal. A result
    changing because an upstream value moved, with this item's own block
    untouched, is a different question this function doesn't answer.

    Inline spans enter as name/RHS/unit, in source order with the fences
    (docs/design/inline-calc.md section 3), so an inline-only item has a
    calc_hash and a stored-result edit leaves it fixed. An item with no
    inline spans hashes exactly as it did when the probe was blocks-only,
    so old baselines do not churn; an item whose old probe predates its own
    spans no longer matches, and _stale_arithmetic's verdict-change signal
    stays silent for it -- a false negative, never a false positive.
    """
    blocks = calc.extract_blocks_with_lines(item.body)
    spans = inline_calc.triggered_spans(item.body)
    if not blocks and not spans:
        return None
    events: list[tuple[int, str]] = [
        (offset, block) for block, offset, _block_id in blocks
    ]
    events += [(span.line_offset, _inline_span_calc_text(span)) for span in spans]
    events.sort(key=lambda event: event[0])
    normalized = [re.sub(r"\s+", " ", text).strip() for _offset, text in events]
    return _hash_blob({"calc_blocks": normalized})


def _link_hash_token(by_key: dict[str, Item], project: Project, target: str) -> str:
    """The value one link target contributes to its owner's content hash
    (docs/design/keys.md §5). Three cases, deliberately distinct so none of
    them can ever collide with each other or with a real key:

    - Resolves, and the target has a key: the key itself. This is the whole
      point -- renaming the target's display id changes nothing here, so
      renaming it changes nothing about *this* item's hash either.
    - Resolves, but the target has no key yet (§2: a keyless item stays
      fully usable, it just isn't durably referenced yet): a sentinel built
      from the target's *current* id, tagged so it can never be mistaken for
      a real key (no real key contains "!" or ":"). This is deliberately
      NOT rename-stable -- that instability is correct, not a bug: a link
      can't be rename-immune to a target that has no immutable identity to
      pin to yet. `refdes check`'s existing "N item(s) have no key yet" info
      line is what surfaces this state; it doesn't need a second diagnostic
      raised from inside hashing.
    - Doesn't resolve at all: a different tagged sentinel, built from the
      raw target text. `resolve_links()` already reports this exact case as
      a build error elsewhere in the same build (it runs first, see
      build()) -- this only needs to be deterministic and distinct from the
      other two cases, not to raise a second diagnostic for the same fault.
    """
    item = resolve_link_target(by_key, project, target)
    if item is None:
        return f"!unresolved:{target}"
    if item.key:
        return item.key
    return f"!nokey:{item.id}"


def _checks_display_only(entries) -> object:
    """The value `checks:` contributes to its owner's content hash under
    HASH_FORMAT 1 and 2 (before `against:` reduced to a resolved key):
    each entry's `against:` reduced to its display half only (everything
    before '@'), mirroring the format-1 link reconstruction
    (`t.split('@', 1)[0]` in hash_payload_builder).

    Before HASH_FORMAT 3, `checks:` composites did not exist -- `against:`
    was always bare, so a format-1 or format-2 hash was always computed
    from bare text. `links.expand_missing_checks` (docs/design/keys.md §3)
    can since have rewritten that same text to `DISPLAY@key` on disk, with
    no content change at all. Reconstructing formats 1/2 from *that* text
    verbatim would hash a string that never existed when those formats were
    actually in force, making an untouched item look edited. Stripping back
    to the display half undoes exactly that syntax upgrade, the same way
    the link path already does for format 1.
    """
    if not isinstance(entries, list):
        return entries
    reduced = []
    for entry in entries:
        if not isinstance(entry, dict) or "against" not in entry:
            reduced.append(entry)
            continue
        new_entry = dict(entry)
        new_entry["against"] = str(entry["against"]).split("@", 1)[0]
        reduced.append(new_entry)
    return reduced


def _checks_hash_value(by_key: dict[str, Item], project: Project, entries) -> object:
    """The value `checks:` contributes to its owner's content hash under
    HASH_FORMAT 3 (docs/design/keys.md §5, decided 2026-09-14): each entry's
    `against:` reduced to the target's resolved key, exactly as a link
    target is (_link_hash_token) -- renaming the checked-against item's
    display id then changes nothing about the checking item's hash.

    An entry that isn't a well-formed {value, against} mapping is left
    exactly as parsed -- run_checks() reports its own diagnostic for that
    shape and this only needs to not crash on it. A target that does not
    resolve, or resolves to a keyless item, keeps its *raw* `against:` text
    (the `!unresolved:`/`!nokey:` sentinels are how _link_hash_token signals
    those cases, and neither is stable across an edit -- unlike a real key,
    a bare id or a stale composite must still be able to invalidate).
    """
    if not isinstance(entries, list):
        return entries
    reduced = []
    for entry in entries:
        if not isinstance(entry, dict) or "against" not in entry:
            reduced.append(entry)
            continue
        token = _link_hash_token(by_key, project, str(entry["against"]))
        new_entry = dict(entry)
        if not token.startswith("!"):
            new_entry["against"] = token
        reduced.append(new_entry)
    return reduced


def _calc_reference_values(
    by_key: dict[str, Item], project: Project, item: Item, include_inline: bool = False
):
    """Every cross-item calc reference in ``item``'s blocks -- and, with
    ``include_inline``, its inline calc spans too -- as ``(target text, name,
    resolved target item or None, resolved Value or None)``, fence lines
    first in source order, then spans in source order. The one place a
    reference is resolved against the *evaluated* project, shared by the
    content hash (`_calc_refs_hash_value`, gated by hash format) and the
    baseline snapshot (`calc_reference_snapshot`, always current) so the two
    can never disagree about what a reference resolved to. Unresolvable
    pieces come back ``None``; the build has already reported them at the
    referring line."""
    out = []
    for block in calc.extract_blocks(item.body):
        for raw_line in block.splitlines():
            line = raw_line.partition("#")[0].rstrip()
            pipe = calc.PIPE_UNIT_RE.match(line)
            if pipe:
                line = pipe.group("lhs").rstrip()
            match = calc.ASSIGN_RE.match(line)
            ref = calc.CROSS_REF_RE.match(match.group(2).strip()) if match else None
            if not ref:
                continue
            target = resolve_link_target(by_key, project, ref.group("target"))
            value = None
            if target is not None and not target.external:
                value = getattr(target, "_env", {}).get(ref.group("name"))
            out.append((ref.group("target"), ref.group("name"), target, value))
    if include_inline:
        for span in inline_calc.triggered_spans(item.body):
            ref = inline_calc.span_cross_ref(span)
            if ref is None:
                continue
            target = resolve_link_target(by_key, project, ref.group("target"))
            value = None
            if target is not None and not target.external:
                value = getattr(target, "_env", {}).get(ref.group("name"))
            out.append((ref.group("target"), ref.group("name"), target, value))
    return out


def calc_reference_snapshot(project: Project, item: Item) -> dict[str, str]:
    """``{"<target key>.<name>": "<value as displayed>"}`` for every resolved
    cross-item reference of ``item`` -- what a baseline records so a later diff
    can say *which* upstream value moved and from what (finding 35 §4). Keyed
    on the target's key (its display id, when keyless), so an upstream rename
    does not look like a moved value; the text is the readable result and
    bounds, e.g. ``12 V (11.4 V … 12.6 V)``. Empty for an item with none.

    Inline spans enter the snapshot always: snapshots are stamped at the
    current format, and the current format hashes span references, so a
    stamped snapshot records exactly the references the stamp's own format
    hashes. There is no older-format snapshot to gate (round-14 review).
    """
    by_key = _key_index(project)
    snapshot: dict[str, str] = {}
    for _target_str, name, target, value in _calc_reference_values(
        # always current-format: reconstruction never calls this, so the
        # span inputs are always in scope (round-13 NIT: the old
        # `include_inline=HASH_FORMAT >= 6` was a gate that never closed)
        by_key, project, item, include_inline=True
    ):
        if target is None or value is None:
            continue
        text = calc.format_value(value, project.sigfigs)
        bounds = calc.format_bounds(value, project.sigfigs)
        snapshot[f"{target.key or target.id}.{name}"] = f"{text} ({bounds})" if bounds else text
    return snapshot


def _calc_refs_hash_value(
    by_key: dict[str, Item], project: Project, item: Item, include_inline: bool = False
):
    """What an item's cross-item calc references contribute to its content
    hash (HASH_FORMAT 4, finding 35 §4), or ``None`` when it has none. With
    ``include_inline`` (HASH_FORMAT 6, docs/design/inline-calc.md section 3),
    an inline span's whole-right-hand-side reference counts as one of those
    references, and its target half is reduced to the same token in the
    hashed body text.

    Returns ``(body_text, resolved)``. ``resolved`` lists, fence lines first
    then spans (each group in source order), each reference's
    ``[target token, name, value signature]``: the target
    reduced by `_link_hash_token` (its key -- so renaming the upstream
    *display id* changes nothing) and the value the reference resolved to
    (`calc.value_signature`, full precision and unit, independent of
    `sigfigs`) -- so a moved upstream value moves this hash while this
    item's own text is untouched. ``body_text`` is the body with each
    reference line's target replaced by the same token, so the on-disk
    bare -> `DISPLAY@key` expansion, and a later display-half refresh, are
    invisible to the hash exactly as they are for link targets. The legacy
    reconstruction (``include_inline=False``, formats <= 5) does not reduce
    span targets here at all -- the span's reference is invisible to a
    legacy hash, and the body-level strip of the expansion lives in
    `_hash_payload`, where the raw (no-references) body is hashed too.

    A reference that does not resolve (missing item, missing name, failed
    or imported target) contributes a ``None`` value; the build already
    reports that as an error at the referring line, this only has to be
    deterministic and distinct from any real value.

    A field reference (`TARGET.$field`) contributes NO entry to
    ``resolved`` -- the field's value never enters the content hash, so
    editing it moves the computed result and the release gate's stale-span
    report, not the hash (the rule is what keeps a field read out of the
    dependency-order story it shares with the scheduler's no-edge rule). Its
    target half IS reduced to the same token in ``body_text``, so the on-disk
    bare -> composite expansion of a field reference is hash-invisible like
    every other reference.
    """
    refs = _calc_reference_values(by_key, project, item, include_inline=include_inline)
    field_targets = [
        target_str
        for target_str in _calc_field_reference_targets(item)
        if target_str not in {t for t, *_ in refs}
    ]
    if not refs and not field_targets:
        return None
    tokens = {
        t: _link_hash_token(by_key, project, t)
        for t in [*[t for t, *_ in refs], *field_targets]
    }
    resolved = [
        [
            tokens[target_str],
            name,
            calc.value_signature(value) if value is not None else None,
        ]
        for target_str, name, _target, value in refs
    ]
    from . import links as links_mod

    body_lines = item.body.splitlines()
    links_mod._calc_ref_rewrites(
        body_lines, 0, len(body_lines), tokens, include_inline=include_inline
    )
    return "\n".join(body_lines), resolved


def _source_inputs_hash_value(item: Item):
    """What an item's `source()` lines contribute to its content hash (HASH_FORMAT
    4, finding 26), or ``None`` when it has none: the sorted, de-duplicated
    ``[canonical path, key, locked decimal text]`` triples the calc actually
    resolved -- and only those. No fetch timestamp, no file sha256, no
    unreferenced lock value, no reader version. A use that failed to resolve
    contributes ``None`` for its value: the build reports the error at the
    line, this only has to be deterministic and distinct from a real value."""
    uses = getattr(item, "_source_uses", None)
    if not uses:
        return None
    return sorted([canon, key, text] for canon, key, text in set(uses))


# One markdown-it parser per thread, not per item. Constructing a MarkdownIt
# costs ~0.09 ms and `_image_inputs_hash_value` ran it once per item: 1602
# constructions for a 1600-item corpus, measured at ~45% of model-build time.
# Sharing one instance is also what *enforces* the constraint that docstring
# states -- that the hash pass and `render_bodies` see the identical set of
# images. Three copies of the same literal are three chances to drift.
#
# Thread-local rather than a bare module global, because a MarkdownIt instance
# is mutable: `configure()`, `enable()`, `disable()` and `use()` all rewrite
# its rule chains, and `refdes serve` runs a poller thread
# (`serve/state.py` `Poller`) plus one thread per HTTP connection
# (`serve/server.py` `ThreadingHTTPServer`), with `loader.load_readonly` able
# to run concurrently. A shared instance would work today -- nothing in
# `src/` or `tests/` calls any of those four methods (grepped), and
# markdown-it's own `parse`/`render` build a fresh `StateCore` and a fresh
# `env` per call and never write to the instance -- but per-thread ownership
# keeps that a property of this module rather than a promise about
# markdown-it's internals that a future release could break. Cost is one
# parser per live thread instead of one per item.
_MD_LOCAL = threading.local()


def _markdown_parser() -> MarkdownIt:
    """This thread's markdown-it parser, built on first use.

    The configuration is load-bearing, not a preference: `gfm-like` for the
    tables and strikethrough a hardware document needs for pin maps and BOM
    excerpts; `linkify` off because bare IDs are our own concern; `html` off
    so a document can never inject markup -- which is also why an escaped raw
    `<img>` contributes no image to `_image_inputs_hash_value`. Every caller
    goes through here so the hash pass and the render pass cannot disagree.
    """
    md = getattr(_MD_LOCAL, "markdown_it", None)
    if md is None:
        md = MarkdownIt("gfm-like", {"html": False, "linkify": False})
        _MD_LOCAL.markdown_it = md
    return md


def _image_inputs_hash_value(project: Project, item: Item, digest_cache: dict):
    """What an item's referenced images contribute to its content hash
    (HASH_FORMAT 5, docs/design/editor-image-upload.md §15.6), or ``None``
    when its body references none: the sorted, de-duplicated
    ``[project-relative path, digest]`` pairs for every local image the body
    resolves -- ``digest`` being the same first-16-hex sha256 `_process_images`
    splices into the published asset leaf, so a hash contribution is directly
    comparable with the output filename. Resolution mirrors `_process_images`
    exactly: a frozen `/path` is project-root anchored; other sources resolve
    relative to the item's own source file first, then
    the bare-name `site.assets:` search (`_search_image_matches`, the shared
    pure half of `_search_image_src`, so the two resolutions can never drift).

    An unresolved, ambiguous, or unreadable src contributes ``[path, None]``:
    the render pass reports all three as build errors at the reference (the
    unreadable file recorded here under its resolved path -- IMAGE-ASSET-007),
    this only has to be deterministic and distinct from any real pair -- the
    posture of a ``None`` calc-ref value. URL-scheme srcs contribute nothing,
    same skip as `_process_images`. The src set comes from the same markdown-it
    configuration `render_bodies` uses, so the hash pass and the render pass
    see the identical set of images: code fences and escaped raw `<img>`
    (html is disabled) contribute none, link-wrapped images contribute theirs.
    The token src *is* the canonical spelling of `image_src_from_html`'s
    docstring -- the hash pass reads it straight, with no decode step, which
    is what keeps every existing content hash bit-identical; the render pass
    reaches the same string by decoding the attribute markdown-it escaped.
    """
    md = _markdown_parser()
    srcs = []
    for token in md.parse(item.body):
        for child in token.children or ():
            if child.type == "image":
                src = child.attrGet("src") or ""
                if src and not _URL_SCHEME_RE.match(src):
                    srcs.append(src)
    if not srcs:
        return None
    entries = set()
    for src in srcs:
        full_path = _local_image_path(project, src, item.source_file)
        if os.path.isfile(full_path):
            resolved = full_path
        elif "/" in src or "\\" in src:
            entries.add((src, None))
            continue
        else:
            matches = _search_image_matches(project, src)
            if len(matches) != 1:
                # Unresolved (0) or ambiguous (2+): both are build errors at
                # render; one deterministic sentinel covers both.
                entries.add((src, None))
                continue
            resolved = os.path.normpath(os.path.join(project.root, matches[0]))
        rel = os.path.relpath(resolved, project.root).replace("\\", "/")
        digest = digest_cache.get(rel)
        if digest is None:
            try:
                with open(resolved, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()[:16]
            except OSError:
                digest = None
        entries.add((rel, digest))
    # Sort on a key that never compares the ``None`` sentinel with a str
    # digest: a raw unresolved src's text can equal another src's resolved
    # project-relative path (IMAGE-ASSET-001), putting ``[path, None]`` and
    # ``[path, digest]`` in one set with the same first element. For a set
    # of all-str digests -- every ordinary project -- the key orders exactly
    # like the plain pair it replaces, so no ordinary project's hash moves.
    return sorted(
        ([path, digest] for path, digest in entries),
        key=lambda entry: (entry[0], entry[1] is not None, entry[1] or ""),
    )


def compute_hashes(project: Project) -> None:
    """Hash only the fields whose on_change mode is `invalidate`.

    This is what a link records at review time, so that a change to a `log` or
    `ignore` field (owner, tags) never marks downstream items suspect -- the two
    modes are indistinguishable here. `log` is reserved for a future history layer
    and currently behaves as `ignore`. Imported items keep the hash their own
    project computed.

    Link targets, and (from HASH_FORMAT 3) `checks: against:` targets that
    resolve to a keyed item, are hashed as their *resolved keys*
    (docs/design/keys.md §5), not as composite text and not as the display
    id -- see _link_hash_token for the three cases and why each is safe.
    This is the change §5 calls load-bearing: renaming a target's display id
    no longer touches the hash of anything that links to it or checks
    against it, whether the on-disk reference is still bare or has already
    been expanded to a `DISPLAY@key` composite.

    Two things stay deliberately absent from the payload, same as before
    keys existed: the display id (unchanged -- it was never hashed), and
    the item's *own* key. Hashing an item's own key would mean minting one
    -- an identity-only event with no content behind it -- rewrites that
    item's hash for no content reason, and the first time every item in a
    project adopts a key at once, that would be every item's hash in the
    project. Identity is what a hash's key-lookups point at from other
    items; it is not itself content to be hashed.
    """
    payload_for = hash_payload_builder(project, HASH_FORMAT)
    for item in project.local_items:
        spec = project.types[item.type]
        item.content_hash = _hash_blob(payload_for(item, spec))


def hash_payload_builder(
    project: Project,
    hash_format: int,
    strip_inline_composite: bool | None = None,
    strip_display: dict[str, str] | None = None,
):
    """A ``(item, spec) -> payload`` closure computing _hash_payload() under
    ``hash_format``'s definition, reused by compute_hashes() (current
    format) and hash_for_format() (any earlier one) so the two can never
    define "current" and "historical" hashing differently by accident.

    Format 1 (pre-keys): link targets hashed as bare display-id text,
    `checks: against:` hashed as its display half only (composites did not
    exist yet for checks: at this format, so this undoes any expansion
    links.expand_missing_checks has since done to the live source --
    _checks_display_only). Format 2 (docs/design/keys.md §5): link targets
    hashed as resolved keys, `checks: against:` still display-half-only for
    the same reason -- `against:` composites didn't exist under format 2
    either. Format 3 (§5, 2026-09-14): format 2, plus `checks: against:`
    entries reduced to a resolved key the same way a link target is
    (_checks_hash_value). Format 4 (finding 35, 2026-09-21): format 3, plus
    an item's cross-item calc references hash as resolved key + resolved
    value (_calc_refs_hash_value); an item with none is identical to format 3.
    Format 5 (editor-image-upload.md §15.6, 2026-09-25): format 4, plus an
    item's referenced images hash as resolved path + content digest
    (_image_inputs_hash_value); an item with none is identical to format 4.
    Format 6 (docs/design/inline-calc.md section 3, 2026-10-19): format 5,
    plus an inline calc span's cross-item reference counts as a calc
    reference (_calc_refs_hash_value with ``include_inline``); an item with
    no such span is identical to format 5.

    ``strip_inline_composite`` overrides the default reduction of expanded
    span targets to their display half (see _hash_payload); None derives it
    from the format -- stripped for every reconstruction the expansion
    post-dates, live for the current format. hash_for_format_variants()
    uses the override to offer the as-written legacy reading.
    """
    if strip_inline_composite is None:
        strip_inline_composite = hash_format < 6
    if hash_format <= 1:
        return lambda item, spec: _hash_payload(
            item, spec, project,
            link_values=lambda targets: sorted(t.split("@", 1)[0] for t in targets),
            checks_values=_checks_display_only,
            strip_inline_composite=strip_inline_composite,
            strip_display=strip_display,
        )
    by_key = _key_index(project)
    checks_values = (
        (lambda entries: _checks_hash_value(by_key, project, entries))
        if hash_format >= 3 else _checks_display_only
    )
    include_inline = hash_format >= 6
    calc_refs = (
        (lambda item: _calc_refs_hash_value(
            by_key, project, item, include_inline=include_inline
        ))
        if hash_format >= 4 else None
    )
    source_inputs = _source_inputs_hash_value if hash_format >= 4 else None
    image_digests: dict[str, str] = {}
    image_inputs = (
        (lambda item: _image_inputs_hash_value(project, item, image_digests))
        if hash_format >= 5 else None
    )
    return lambda item, spec: _hash_payload(
        item, spec, project,
        link_values=lambda targets: sorted(
            _link_hash_token(by_key, project, t) for t in targets
        ),
        checks_values=checks_values,
        calc_refs=calc_refs,
        source_inputs=source_inputs,
        image_inputs=image_inputs,
        strip_inline_composite=strip_inline_composite,
        strip_display=strip_display,
    )


def hash_for_format(item: Item, project: Project, hash_format: int) -> str:
    """The content hash this item would have under hash-format
    ``hash_format``, recomputed from its *current* parsed state.

    Deliberately not "whatever the target string looks like right now": if
    links.expand_missing has already rewritten a target to a `DISPLAY@key`
    composite, format 1's reconstruction only uses the display half
    (everything before '@'), because that is what the *original*,
    pre-adoption hash was computed from. Using the live composite text here
    would make an item that has not actually changed look changed, purely
    because its own link syntax was upgraded -- exactly the false positive
    the hash-format migration exists to avoid. `checks: against:` needs the
    identical treatment under formats 1 *and* 2 (_checks_display_only):
    `against:` composites did not exist at either format, so
    links.expand_missing_checks rewriting a bare target to a composite on
    the live source must not change either reconstruction either. Only
    format 3 reduces a resolving `against:` to its key instead of stripping
    it (_checks_hash_value); an unresolved or keyless target still keeps
    its raw text there too.

    Used only by the hash-format migration (lifecycle.migrate_hash_format,
    seal._matches_sealed_hash's carry-forward comparison, and
    keys.plan_surrogate_storage/`refdes keys adopt`, all through
    keys.hashes_in_format, which is this value plus the as-written span
    reading hash_for_format_variants() computes) to decide whether a stored
    old-format hash still matches current content. Never called during an
    ordinary build.
    """
    spec = project.types[item.type]
    payload = hash_payload_builder(project, hash_format)(item, spec)
    return _hash_blob(payload)


def _span_composite_targets(item: Item) -> list[tuple[str, str, str]]:
    """(target, display, key) for every composite cross-item target in
    this item's triggered inline spans, in source order. Shared by the
    faithfulness gate and the historical-display variants so they can
    never disagree about which targets they cover."""
    from . import inline_calc as inline_calc_mod

    found: list[tuple[str, str, str]] = []
    for _offset, _start, _end, content in inline_calc_mod.triggered_span_events(
        item.body.splitlines()
    ):
        ref = inline_calc_mod.span_cross_ref(inline_calc_mod.parse_span(0, content))
        if ref is None:
            continue
        display, sep, key = ref.group("target").partition("@")
        if not sep:
            continue
        found.append((ref.group("target"), display, key))
    return found


def _span_composites_are_faithful(item: Item, project: Project) -> bool:
    """True when every composite cross-item target in this item's triggered
    inline spans is a form slice-2's expansion (and its rename refresh)
    legitimately writes: the key half names a live item, and the display
    half is that item's current id OR one of its declared former ids.

    The format <= 5 strip (see _hash_payload) is the inverse of that
    expansion, so it is a faithful legacy reading of a composite *only*
    under this identity. A key-half-only edit (`DEC-001@K2`, the display
    half untouched -- now pointing at K2's item) strips back to the bare
    text a pre-edit baseline/seal recorded, and the stripped hash would
    certify an edited item as "content demonstrably unchanged" (round-7
    review). Failing this check fails closed: the stripped reading is
    withdrawn, the as-written reading stays -- which the format's own code
    hashed verbatim -- so the edit is reported, exactly as it was before
    the variant set existed. A bare target has no key half to fail on.
    The former-id half of the display test (round-10 review): an
    ordinary upstream display-id rename refreshes the composite label
    (`links._planned_target`), so a *stale* display half naming a former
    id of the key's owner is the signature of the rename, not an edit --
    the hashes_in_format variants below offer the stripped readings over
    those historical halves so pre-rename records keep matching. Build
    order precondition (round-14 NIT): `project.former_ids` is populated
    by `validate_former_ids`, which `build()` runs before any caller of
    this gate (seal verify, lifecycle) -- an unpopulated map only widens
    the fail-closed withdrawal.
    """
    by_key = {i.key: i for i in project.local_items if i.key}
    for _target, display, key in _span_composite_targets(item):
        owner = by_key.get(key)
        if owner is None:
            return False
        if display != owner.id and project.former_ids.get(display) != owner.id:
            return False
    return True


def hash_for_format_variants(item: Item, project: Project, hash_format: int) -> set[str] | None:
    """Every content hash ``hash_format`` can legitimately assign to this
    item's current content, or ``None`` for a format this build does not
    understand.

    The one thing hash_for_format() strips that the format's own code did
    not always strip: an inline calc span whose cross-item target is a
    composite (`DEC-001@key.V_in`). Slice 2's expansion writes composites
    into span targets that authors had written bare, so a format <= 5
    reconstruction strips them back (the display-half body is what the
    recorded hash saw). But `calc.CROSS_REF_RE` accepted an author-written
    composite all along, and the format's own code hashed *that* text
    verbatim -- resolving it by key exactly as a fence line's composite is
    resolved. For such a body there are two legitimate readings of "what
    this format hashes right now": the stripped body (target expanded by
    slice 2) and the as-written body (target authored as a composite).
    The stripped reading is offered only under a narrow identity gate --
    every composite target must be faithful, `DISPLAY@key` naming the
    item that owns ``key`` (see _span_composites_are_faithful) -- because
    a key-half-only edit strips back to the pre-edit bare text and the
    stripped reading would certify the edit as unchanged. The rules this
    leaves standing:

    - it is a *comparison-side* rule only. The current format is untouched
      (a set of one: ``item.content_hash``), and no hash is ever *recorded*
      from a variant -- baselines and seals keep stamping the single
      hash_for_format()/compute_hashes() value.
    - an edit to the body text moves the as-written reading, and a
      faithful composite that stops being faithful (a key-half edit)
      loses the stripped reading outright -- so every edit is reported
      changed/uncomparable, as before the variant set existed.
    - the as-written reading exists only for legacy formats (1 <= f <
      HASH_FORMAT); it is the identical payload with the span-strip pass
      disabled and every other format rule (link halves, `against:`,
      calc refs, source/image inputs) untouched, so it cannot smuggle in
      another format's definitions.

    A body with no composite span target hashes the same under both
    readings, so the set has one element there: this is invisible to every
    migration that predates inline spans.
    """
    spec = project.types[item.type]
    if hash_format == HASH_FORMAT:
        return {item.content_hash}
    if not 1 <= hash_format < HASH_FORMAT:
        return None
    live = _hash_blob(
        hash_payload_builder(project, hash_format, strip_inline_composite=False)(item, spec)
    )
    if not _span_composites_are_faithful(item, project):
        return {live}
    stripped = _hash_blob(hash_payload_builder(project, hash_format)(item, spec))
    variants = {stripped, live}
    # Historical display halves (round-10 review): an ordinary upstream
    # display-id rename refreshes a faithful composite's label, moving the
    # stripped body off the text a pre-rename record was computed over.
    # The key owner's declared former ids are legitimate historical
    # display halves -- offer the stripped readings over every combination
    # of (current id, former ids) per composite target, so a pre-rename
    # baseline/seal hash over the old label keeps matching. The
    # as-written-as-stripped combination is the `stripped` reading above.
    # A target whose key resolves to no live item fails the gate above,
    # so deletions never reach this code as a silent stripped pass.
    by_key = {i.key: i for i in project.local_items if i.key}
    formers: dict[str, list[str]] = {}
    for old, current in project.former_ids.items():
        formers.setdefault(current, []).append(old)
    options: list[tuple[str, list[str]]] = []
    authored_display: dict[str, str] = {}
    for target, display, key in _span_composite_targets(item):
        if target in authored_display:
            continue
        authored_display[target] = display
        owner = by_key[key]
        opts = [owner.id] + sorted(formers.get(owner.id, ()))
        options.append((target, opts))
    combinations = 1
    for _target, opts in options:
        combinations *= len(opts)
    # The sweep is exhaustive below a small bound and abandoned above it:
    # each extra display-half option doubles the reconstructions, and a
    # target with many former ids (plus several composites in one item)
    # would multiply out the comparison. Dropping the HISTORICAL readings
    # above the cap is the safe direction: the as-written and current-id
    # stripped readings stay in the set, so the loss is a false-positive
    # "modified since sealed" on a pre-rename record (the author reseals
    # or the record stays uncomparable), never a silent pass -- and the
    # round-7 gate withdrawal above still fails closed on key-half edits.
    # (Round-13 review; pinned by
    # test_former_id_readings_are_offered_up_to_the_cap_and_dropped_above.)
    if options and combinations <= 16:
        for combo in itertools.product(*(opts for _target, opts in options)):
            mapping = dict(zip(authored_display, combo))
            if mapping == authored_display:
                continue
            variants.add(
                _hash_blob(
                    hash_payload_builder(project, hash_format, strip_display=mapping)(item, spec)
                )
            )
    return variants


def legacy_hash_for(item: Item, project: Project) -> str:
    """hash_for_format(item, project, 1) -- kept as its own name because it
    predates hash_for_format and is still the common case callers reach for
    when they mean specifically "the pre-keys hash"."""
    return hash_for_format(item, project, 1)


# -------------------------------------------------------------------------- markdown


def _calc_table_html(lines: list[CalcLine], block: str = "") -> str:
    # A named block's table gains an anchor and a caption (§3.5, decided
    # §11.10); an unnamed block's HTML is byte-for-byte what it always was --
    # pinned by tests/test_calc_block_names.py, because most items have one
    # unnamed block and nothing about them should move.
    anchor = f' id="calc-{_esc(block)}"' if block else ""
    caption = f'<caption class="calc-caption">{_esc(block)}</caption>' if block else ""
    rows = []
    for line in lines:
        name_cell = _esc(line.name)
        if line.annotation:
            marker = "|" if line.unit_style == "|" else ":"
            name_cell += (
                f'<span class="calc-annotation">{marker} {_esc(line.annotation)}</span>'
            )
        # A cross-item reference renders as the dependency it is -- the
        # target's display id and the name, key half hidden (keys.md §3).
        expr_cell = _esc(line.display_expression)
        if line.source_path and not line.error:
            # Provenance sits beside the expression, never in hover-only UI
            # (docs/design/calc-sources.md section 6): which file, which key,
            # and the locked value the arithmetic actually used.
            expr_cell += (
                f'<span class="calc-source">source: {_esc(line.source_path)} '
                f'&middot; {_esc(line.source_key)} = {_esc(line.source_locked)}</span>'
            )
            if line.source_drift:
                expr_cell += (
                    f'<span class="calc-source-drift">&#9888; {_esc(line.source_drift)}</span>'
                )
        if line.error:
            rows.append(
                f'<tr class="calc-row calc-error">'
                f'<td class="calc-name">{name_cell}</td>'
                f'<td class="calc-expr">{expr_cell}</td>'
                f'<td class="calc-result" colspan="2">⚠ {_esc(line.error)}</td></tr>'
            )
            continue
        bounds = (
            f'<span class="calc-bounds">{_esc(line.bounds)}</span>' if line.bounds else ""
        )
        comment = (
            f'<td class="calc-comment">{_esc(line.comment)}</td>' if line.comment
            else "<td></td>"
        )
        rows.append(
            f'<tr class="calc-row">'
            f'<td class="calc-name">{name_cell}</td>'
            f'<td class="calc-expr">{expr_cell}</td>'
            f'<td class="calc-result">{_esc(line.result)} {bounds}</td>'
            f"{comment}</tr>"
        )
    return f'<table class="calc"{anchor}>' + caption + "".join(rows) + "</table>"


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _placeholder(index: int) -> str:
    """A token markdown will pass through untouched."""
    return f"xxrefdescalc{index}xx"


def _calc_line_count(block: str) -> int:
    """Rows a calc block contributes -- must match evaluate_block's line filtering."""
    return sum(
        1
        for raw in block.splitlines()
        if raw.strip() and not raw.strip().startswith("#")
    )


def _linkify(
    html: str,
    project: Project,
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> str:
    """Turn IDs into preview-bearing links, skipping code and pre regions."""

    def calc_anchor(item: Item, name: str, ref: str) -> str | None:
        """`#calc:<name>` checked against the target's own named calc blocks.

        Same posture as `field_anchor` below and for the same reason: None
        means the target has no such block, the miss is reported, and the
        caller must not emit an anchor for it. It is a *warning*, never an
        error (§11.9 decided): a broken prose link must not fail a build, the
        way an unresolved `[[...]]` never does.

        The names come from the target's fence lines, not from its evaluated
        rows, so a named block that produced no rows is still a name the item
        has -- the anchor Phase 1 puts on the table is what this resolves to.
        """
        fences = calc.extract_blocks_with_lines(item.body)
        names = [block_id for _, _, block_id in fences if block_id]
        if name in names:
            return f"#calc-{name}"
        if names:
            project.warn(
                f"{ref}: {item.id} has no calc block named {name!r} "
                f"(it names: {', '.join(names)}).",
                file=where_file, line=where_line, item_id=where_id,
            )
            return None
        if fences:
            project.warn(
                f'{ref}: {item.id} has calc blocks but none is named -- add '
                f'id="..." to its fence to make this link work.',
                file=where_file, line=where_line, item_id=where_id,
            )
            return None
        # Not one of §7's two shapes: the target computes nothing at all, so
        # neither "it names: ..." nor "none is named" is true of it. Same level,
        # same posture, and a fix that is true for this target.
        project.warn(
            f"{ref}: {item.id} has no calc blocks -- a #calc: fragment names a "
            f'```calc block given id="...", and this item computes nothing.',
            file=where_file, line=where_line, item_id=where_id,
        )
        return None

    def field_anchor(item: Item, field: str | None, ref: str) -> str | None:
        """A `#fragment` checked against the target, as an href suffix.

        `calc:<name>` resolves against the item's named calc blocks (§5.3);
        anything else is a field name, checked against the target's own type.

        None means the target has no such field or block -- reported, never
        swallowed, and the caller must not emit an anchor for it. A field that
        is declared but empty on this item still resolves: item.html.j2 keeps
        an anchor for every declared field, rendered or not.
        """
        if field is None:
            return ""
        if field.startswith(CALC_FRAGMENT_PREFIX):
            return calc_anchor(item, field[len(CALC_FRAGMENT_PREFIX) :], ref)
        if ":" in field:
            # `#blox:losses`: a namespace that does not exist. Before the
            # fragment group admitted a colon this reference simply did not
            # match, so it reached the page as literal text -- silent, which is
            # the failure this project keeps refusing. Now it is reported, and
            # names the only two fragment kinds there are.
            project.warn(
                f"{ref}: {item.id} has no {field!r} fragment -- a fragment is a "
                f"field name declared on {item.type!r}, or calc:<name> for a "
                f'named ```calc block.',
                file=where_file, line=where_line, item_id=where_id,
            )
            return None
        spec = project.types.get(item.type)
        if spec is not None and field in spec.fields:
            return f"#field-{field}"
        msg = (
            f"reference to {item.id!r} names field {field!r}, which type "
            f"{item.type!r} does not declare"
        )
        if field == CALC_FRAGMENT_PREFIX.rstrip(":"):
            # Run-9 F4: `[[ID#calc]]` is the calc anchor with the name left
            # off, and the bare field miss above does not hint the spelling
            # that works. Name it, and name the blocks the target has --
            # read off the same fence lines `calc_anchor` reads. An item
            # that computes nothing gets no hint: the anchor cannot resolve
            # there, and the plain field miss is the true sentence (§7's
            # third shape has the same posture).
            fences = calc.extract_blocks_with_lines(item.body)
            names = [block_id for _, _, block_id in fences if block_id]
            if names:
                msg += (
                    f" -- did you mean #{CALC_FRAGMENT_PREFIX}<name>? "
                    f"it names: {', '.join(names)}."
                )
            elif fences:
                msg += (
                    f" -- did you mean #{CALC_FRAGMENT_PREFIX}<name>? add "
                    f'id="..." to a calc fence to give a block a name.'
                )
        project.warn(
            msg,
            file=where_file, line=where_line, item_id=where_id,
        )
        return None

    def link(
        target_id: str,
        label: str | None,
        explicit: bool,
        field: str | None = None,
    ) -> str:
        # The reference as the author wrote it, for the fragment diagnostics
        # that need to quote it (§7 spells them `[[ID#calc:name]]: ...`).
        fragment_ref = f"[[{target_id}#{field}]]" if field else ""
        if explicit and field is not None and target_id.startswith("fig:"):
            # Figures are addressed by their own id, not by field; saying so
            # beats silently dropping the fragment.
            project.warn(
                f"reference to {target_id!r} has a #{field} fragment, which "
                "figure references do not have",
                file=where_file, line=where_line, item_id=where_id,
            )
            field = None
        if explicit and target_id.startswith("fig:"):
            # Deferred: existence (anywhere, and in this document) can't be
            # known until every item/page has run _apply_figure_attrs and the
            # whole document this reference lands in has been assembled --
            # see resolve_figures.
            fig_id = target_id[len("fig:") :]
            return (
                f'<span class="fig-ref-pending" data-fig="{_esc(fig_id)}" '
                f'data-label="{_esc(label) if label else ""}" '
                f'data-where-file="{_esc(where_file)}" '
                f'data-where-line="{where_line if where_line is not None else ""}" '
                f'data-where-id="{_esc(where_id) if where_id else ""}"></span>'
            )
        if explicit and field is not None and target_id.startswith("cite:"):
            # Citations are addressed by their own id, not by field, exactly
            # like figures.
            project.warn(
                f"reference to {target_id!r} has a #{field} fragment, which "
                "citation references do not have",
                file=where_file, line=where_line, item_id=where_id,
            )
            field = None
        if explicit and target_id.startswith("cite:"):
            # Not deferred, unlike fig: -- a citation belongs to exactly one
            # item and always links to a row on that item's own page, never
            # renumbered or reused across documents, so its existence and its
            # href are both fully known from project.citation_ids the moment
            # every item has been parsed and validated, well before any body
            # renders.
            cite_id = target_id[len("cite:") :]
            entry = project.citation_ids.get(cite_id)
            if entry is None:
                project.warn(
                    f"reference to citation {cite_id!r}, which does not exist",
                    file=where_file, line=where_line, item_id=where_id,
                )
                return f'<span class="ref ref-missing" title="unknown citation">{label or cite_id}</span>'
            owner_id, _owner_file, _owner_line = entry
            owner = project.item_by_id(owner_id)
            text = label or cite_id
            return (
                f'<a class="ref cite-ref" href="{owner.slug}.html#cite-{_esc(cite_id)}">{text}</a>'
            )
        target = project.item_by_id(target_id)
        if target is None:
            former_owner_id = project.former_ids.get(target_id)
            if former_owner_id is not None:
                # Resolves, but never silently -- a reader following an old id
                # must see it landed somewhere else, not be quietly redirected
                # (finding 12). So the visible text is the *current* id and the
                # marker names the former one: text = old id would render
                # "REQ-PWR-001 (formerly REQ-PWR-001)", a self-contradiction,
                # and would leave the reader with no statement anywhere of
                # where the old id went. An explicit `[[old|label]]` still
                # shows the author's label -- that text is theirs, not an id.
                owner = project.item_by_id(former_owner_id)
                anchor = field_anchor(owner, field, fragment_ref) or ""
                text = label or owner.id
                return (
                    f'<a class="ref ref-former" href="{owner.slug}.html{anchor}" '
                    f'data-ref="{owner.id}">{text}</a>'
                    f'<span class="ref-former-marker" '
                    f'title="{owner.id} was formerly {target_id}">(formerly {target_id})</span>'
                )
            if explicit:
                project.warn(
                    f"reference to {target_id!r}, which does not exist",
                    file=where_file, line=where_line, item_id=where_id,
                )
                return f'<span class="ref ref-missing" title="unknown item">{target_id}</span>'
            return target_id
        anchor = field_anchor(target, field, fragment_ref)
        if anchor is None:
            # A fragment miss renders the reference's own text, in red, exactly
            # like an unresolved item reference: the sentence stays readable and
            # says what did not resolve, and no anchor is emitted for a target
            # that has nothing to land on.
            kind = (
                "unknown calc block" if (field or "").startswith(CALC_FRAGMENT_PREFIX)
                else "unknown field"
            )
            return (
                f'<span class="ref ref-missing" title="{kind}">'
                f"{label or f'{target_id}#{field}'}"
                f"</span>"
            )
        text = label or (f"{target_id}#{field}" if field else target_id)
        return (
            f'<a class="ref" href="{target.slug}.html{anchor}" data-ref="{target.id}">{text}</a>'
        )

    def bare(segment: str) -> str:
        return BARE_REF_RE.sub(lambda m: link(m.group(1), None, False), segment)

    def process(segment: str) -> str:
        # Bare-ref scanning must only ever see the literal gaps between
        # explicit refs, never an explicit ref's own replacement HTML --
        # that HTML embeds the target id again (as link text, and now also in
        # a fig-ref-pending marker's data attributes), and a second sweep
        # over the whole already-substituted string would match that
        # embedded id and linkify it a second time, nesting <a> inside <a>.
        chunks: list[str] = []
        last = 0
        for m in EXPLICIT_REF_RE.finditer(segment):
            chunks.append(bare(segment[last : m.start()]))
            chunks.append(link(m.group(1), m.group(3), True, m.group(2)))
            last = m.end()
        chunks.append(bare(segment[last:]))
        return "".join(chunks)

    out: list[str] = []
    last = 0
    for match in PROTECTED_RE.finditer(html):
        out.append(process(html[last : match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(process(html[last:]))
    return "".join(out)


def _hashed_leaf(rel: str, digest: str) -> str:
    """`figures/curve.png` + digest -> `figures/curve.<digest>.png` -- source
    directory structure preserved, hash and extension appended to the leaf
    filename only (docs/design/index-blocks.md §10)."""
    directory, _, leaf = rel.rpartition("/")
    base, dot, ext = leaf.rpartition(".")
    hashed_leaf = f"{base}.{digest}.{ext}" if dot else f"{leaf}.{digest}"
    return f"{directory}/{hashed_leaf}" if directory else hashed_leaf


def _search_image_matches(project: Project, src: str) -> list[str]:
    """The pure half of `_search_image_src`: every project-relative match for
    a bare image leaf on the declared `site.assets:` directories, deduplicated
    in walk order, no diagnostics. Shared with the HASH_FORMAT 5 image inputs
    (`_image_inputs_hash_value`) so the hash pass and the render pass can
    never resolve a bare src differently; error reporting stays with the
    caller that renders."""
    matches: list[str] = []
    for _full_path, rel, contained in walk_site_assets(project):
        if not contained or rel.rpartition("/")[2] != src:
            continue
        if rel not in matches:
            matches.append(rel)
    return matches


def _search_image_src(
    project: Project,
    src: str,
    where_file: str,
    where_line: int | None,
    where_id: str | None,
) -> str | None:
    """Resolve a bare `<img src>` filename against the `site.assets:` directories.

    The fallback half of docs/design/backlog.md finding 36: `#include <foo.h>`
    semantics, where the declared list is `site.assets:` itself (the same
    directories `collect_static_assets` bulk-copies). Only a src that has
    already failed to resolve relative to the source file AND contains no path
    separator reaches here -- a multi-segment path was written as a specific
    location, and searching its leaf name would silently land an author's
    typo on an unrelated file somewhere else. Never a first-match pick: two
    files with the same leaf name on the search path is a build error naming
    every candidate, because "quietly resolved to a different `diagram.png`
    than the one meant" is this project's characteristic failure. Returns the
    resolved absolute path, or None after reporting the error.
    """
    matches = _search_image_matches(project, src)
    if len(matches) == 1:
        return os.path.normpath(os.path.join(project.root, matches[0]))
    if len(matches) > 1:
        project.error(
            f"image src {src!r} is ambiguous: it exists in more than one "
            f"site.assets directory ({', '.join(sorted(matches))}). Write the "
            f"path relative to {where_file} instead of the bare filename, or "
            f"rename one of them",
            file=where_file, line=where_line, item_id=where_id,
        )
        return None
    # The whole parenthetical is one clause in both branches: "searched ..." is
    # what the populated half needs, and the empty half has nothing that was
    # searched, so a bare "searched" in front of it read as a run-on.
    searched = (
        f"searched the site.assets directories: {', '.join(project.asset_dirs)}"
        if project.asset_dirs
        else "no site.assets directories are declared to search"
    )
    project.error(
        f"image src {src!r} does not exist ({searched})",
        file=where_file, line=where_line, item_id=where_id,
    )
    return None


def _local_image_path(project: Project, src: str, where_file: str) -> str:
    """A frozen /path is anchored at the project root; other paths are local."""
    if src.startswith("/") and not src.startswith("//"):
        return os.path.normpath(os.path.join(project.root, src.lstrip("/")))
    return os.path.normpath(
        os.path.join(project.root, os.path.dirname(where_file), src)
    )


def _process_images(
    html: str,
    project: Project,
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> str:
    """Resolve, validate, register, and rewrite local `<img src>` references.

    A frozen `/path` resolves from the project root. Other local sources resolve
    relative to the source file's own directory -- the
    same base a browser would use to open the rendered page next to its markdown
    source, and the rule that always wins: a src that resolves there is used
    whatever else shares its filename, so no document that works today changes
    behaviour. Only one that fails there *and* is a bare filename (no path
    separator) falls through to the `site.assets:` search
    (`_search_image_src`, docs/design/backlog.md finding 36). One that resolves
    is registered in `project.assets` (source path ->
    a content-hashed destination path, computed once per source and reused for
    every further reference to the same file) and rewritten to
    `assets/<hashed path>`, which is where `render_site` copies it. One that does
    not resolve is a build error, not a warning: unlike a dangling cross-reference,
    there is no sensible way to render a missing image, and now that a resolving
    src is actually made to work end to end, a broken one should stop the build.
    One that resolves to a file the build cannot read (mode 000, EACCES from
    any cause -- IMAGE-ASSET-007) is the same kind of build error at the same
    place, naming the src, the file, and the OS's reason: "does not exist"
    and "cannot be read" are kept as distinct sentences, and neither one
    escapes as a PermissionError traceback.

    The scanned attribute carries markdown-it's HTML-escaped spelling of the
    src; it is canonicalised with `image_src_from_html` before any resolution,
    so this pass and `_image_inputs_hash_value` act on the identical string
    (IMAGE-ASSET-002), and the rewrite goes out through `image_src_to_html`.
    """

    def record(ok: bool, src: str, rel: str | None = None, dest: str | None = None) -> None:
        # Thread workbench W2: remember what this pass already decided, per
        # item, so the preview decorator can show provenance and failure
        # markers without re-running the search. Pure bookkeeping on values
        # computed anyway; pages (where_id None) have no entry to key by.
        if where_id:
            project.image_results.setdefault(where_id, []).append(
                {"src": src, "ok": ok, "rel": rel, "dest": dest}
            )

    def refused(exc: OSError, src: str, rel: str, match: re.Match) -> str:
        # The resolution gate is `os.path.isfile`, and the open happens
        # after it. A file that changes in between -- a concurrent editor
        # write, the serve poller (see in-prog-logs/concurrent-editing-
        # serve.txt), a network mount going stale -- makes the open raise
        # FileNotFoundError, and claiming it "exists ... but cannot be
        # read" is self-contradictory with the wrong remediation. That race
        # re-unifies with the gate's own "does not exist" sentence;
        # everything the open can still refuse for (EACCES, EISDIR, EIO)
        # gets the unreadable refusal (IMAGE-ASSET-007).
        if isinstance(exc, FileNotFoundError):
            project.error(
                f"image src {src!r} does not exist",
                file=where_file, line=where_line, item_id=where_id,
            )
        else:
            project.error(
                f"image src {src!r} exists at {rel!r} but cannot be "
                f"read: {exc.strerror or exc}. Make the file readable, "
                f"or point the reference at a readable file",
                file=where_file, line=where_line, item_id=where_id,
            )
            project.unreadable_assets.add(rel)
        record(False, src)
        return match.group(0)

    def swap(match: re.Match) -> str:
        prefix, attr, suffix = match.group(1), match.group(2), match.group(3)
        # Canonicalise first: the attribute carries markdown-it's escaped
        # spelling, every resolver below (and the hash pass) speak the token
        # spelling -- see the block comment on `image_src_from_html`.
        src = image_src_from_html(attr)
        if not src or _URL_SCHEME_RE.match(src):
            return match.group(0)
        full_path = _local_image_path(project, src, where_file)
        if not os.path.isfile(full_path):
            if "/" in src or "\\" in src:
                project.error(
                    f"image src {src!r} does not exist",
                    file=where_file, line=where_line, item_id=where_id,
                )
                record(False, src)
                return match.group(0)
            found = _search_image_src(project, src, where_file, where_line, where_id)
            if found is None:
                record(False, src)
                return match.group(0)
            full_path = found
        rel = os.path.relpath(full_path, project.root).replace("\\", "/")
        dest = project.assets.get(rel)
        if dest is None:
            # Read once, on the path already being opened to confirm it
            # resolves -- not a second I/O pass. Cached by source path, so
            # the same image referenced from many items/pages hashes once.
            # A file that exists but will not open (IMAGE-ASSET-007: mode
            # 000, EACCES from any cause) used to escape here as an
            # unhandled PermissionError, crashing the whole render pass
            # before this reference -- or any other diagnostic -- could be
            # reported. It is a build error at the reference, same posture
            # as "does not exist": the hash pass recorded the same
            # `None`-digest sentinel the unresolved src contributes, and
            # the reference is left unrewritten.
            try:
                with open(full_path, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()[:16]
            except OSError as exc:
                return refused(exc, src, rel, match)
            dest = _hashed_leaf(rel, digest)
            project.assets[rel] = dest
            # The digest read *is* the readability probe for this file:
            # record it, so a later reference -- and the registration
            # check -- find the answer cached instead of opening again.
            project.readable_probe.add(rel)
        elif rel not in project.readable_probe:
            # A file registered by `collect_static_assets` (a `site.assets:`
            # directory) short-circuits the digest block above, so the
            # readability gate there never sees it: a referenced mode-000
            # asset recorded ok: True, `check` said 0 errors, and the
            # published page pointed at a copy publish then refused
            # (IMAGE-ASSET-007 review). Probe it here -- open and close,
            # no content read -- so the reference carries the same named
            # error as any other unreadable src; `readable_probe` keeps a
            # heavily-referenced asset directory at one open per file.
            # A successful open is the answer only for a *regular* file.
            # The resolution gate's `os.path.isfile` turns a FIFO away
            # with "does not exist" -- this branch sees a non-regular
            # file only through the gate->probe shape swap, a race
            # (round-7 review, F2, correcting this comment's first
            # draft) -- and the copy loop's `isfile` then skips the
            # file, so a probe that stopped at "opened" would record a
            # reference publish will dangle (round 6, F2). `fstat` on
            # the opened fd decides.
            # O_NONBLOCK: the blocking O_RDONLY open of a FIFO waits for
            # a writer, which hung the whole command on the very branch
            # added to gate references -- base attempted no open here at
            # all, so the guard is not optional (round 6, F1; the flag is
            # Unix-only, hence the `getattr`).
            try:
                fd = os.open(full_path,
                             os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        raise OSError(errno.ENOTSUP, "not a regular file",
                                      full_path)
                finally:
                    os.close(fd)
            except OSError as exc:
                return refused(exc, src, rel, match)
            project.readable_probe.add(rel)
        record(True, src, rel, dest)
        # Re-escape on the way out: the published page must carry the src in
        # the same spelling markdown-it's renderer emits, so a browser
        # decoding the attribute reaches the real asset filename -- `a&b.<h>.png`
        # on disk, `a&amp;b.<h>.png` in the tag. For an entity-free path --
        # every ordinary project -- this is the identity rewrite.
        return f"{prefix}{image_src_to_html(f'assets/{dest}')}{suffix}"

    return IMG_SRC_RE.sub(swap, html)


def _image_suffix_attrs(attrs_text: str) -> dict[str, str]:
    """Parse the inside of an image's `{...}` attribute suffix.

    markdown-it escapes '"' in plain text the same as '&', '<', '>', so the
    quoted-value delimiters in `attrs_text` are themselves `&quot;` by the time
    a regex ever sees them; unescape first to parse the attributes.
    """
    return {
        m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3)
        for m in FIGURE_ATTR_RE.finditer(html_entities.unescape(attrs_text))
    }


def _warn_unknown_image_attrs(
    project: Project,
    attrs: dict[str, str],
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> None:
    """One warning per attribute name refdes does not know.

    A typo like `widht=50%` otherwise does nothing at all, in silence, which is
    the failure mode this project treats most seriously. Shared by both image
    paths so a figure and an inline image report it in the same words. Never a
    build failure: an unrecognised name is no reason to stop rendering.
    """
    for name in attrs:
        if name not in IMAGE_ATTR_NAMES:
            project.warn(
                f"{name!r} is not an image attribute and is ignored",
                file=where_file, line=where_line, item_id=where_id,
            )


def _apply_inline_image_attrs(
    html: str,
    project: Project,
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> str:
    """Honour what a `{...}` suffix can mean on an image that is not alone in
    its paragraph, and never leave the suffix on the page as text.

    Runs after `FIGURE_RE`'s pass, so anything still carrying a suffix here is
    an inline image: `width=` becomes an inline `style` on the `<img>`, and
    `caption=`/`id=` -- which only mean something on a `<figure>`, and there is
    no `<figure>` inline -- are dropped with a warning naming file:line and
    item id, and saying how to get them instead. An unknown attribute name gets
    the same treatment: a warning, not silence, not a build failure.
    """

    def swap(match: re.Match) -> str:
        img_tag, attrs_text = match.group(1), match.group(2)
        if "=" not in attrs_text:
            # `{a, b}` after an image is a set in prose, not an attribute
            # suffix: leave the text exactly as the author wrote it.
            return match.group(0)
        attrs = _image_suffix_attrs(attrs_text)
        _warn_unknown_image_attrs(project, attrs, where_file, where_line, where_id)
        for name in ("caption", "id"):
            if name in attrs:
                want = "captioned figure" if name == "caption" else "numbered, referenceable figure"
                project.warn(
                    f"{name}= is ignored on an inline image; put the image in a "
                    f"paragraph of its own to get a {want}",
                    file=where_file, line=where_line, item_id=where_id,
                )
        width = attrs.get("width")
        if not width:
            return img_tag
        style = f' style="width: {_esc(width)}"'
        # markdown-it always closes an `<img>` with ` />`; keep that spacing.
        if img_tag.endswith("/>"):
            return f"{img_tag[:-2].rstrip()}{style} />"
        return f"{img_tag[:-1].rstrip()}{style}>"

    return INLINE_FIGURE_RE.sub(swap, html)


def _apply_figure_attrs(
    html: str,
    project: Project,
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> str:
    """Wrap `![alt](src){width=60% caption="..."}` in a real `<figure>`, and
    register an explicit `id=` in the project-wide figure registry
    (docs/design/index-blocks.md §9).


    A paragraph containing nothing but one image immediately followed by a
    `{...}` suffix becomes a real `<figure>`. An image with a suffix anywhere
    else -- inline with text, in a list item, in a table cell -- is handled by
    `_apply_inline_image_attrs`, which this function runs over the result.
    Either way an attribute name outside `IMAGE_ATTR_NAMES` warns: a typo like
    `widht=50%` must not silently do nothing.
    Matched the same way `_process_images` and `_linkify` scan rendered HTML
    with a regex rather than a markdown-it plugin.
    With no suffix the image passes through completely untouched. `alt` always
    stays on the `<img>`; `caption` falls back to it when not given. `id=` is
    optional exactly like `width=`/`caption=` already are -- a figure with no
    id renders exactly as it does today, numbered nowhere, referenced by
    nobody. A duplicate id is a build error naming both locations; the second
    figure keeps rendering, just without an id (which would be invalid HTML
    twice over) or a number.
    """

    def swap(match: re.Match) -> str:
        img_tag, attrs_text = match.group(1), match.group(2)
        # Parsed once unescaped, then re-escaped whatever ends up in the caption
        # before it goes back into the page as HTML text.
        attrs = _image_suffix_attrs(attrs_text)
        _warn_unknown_image_attrs(project, attrs, where_file, where_line, where_id)
        alt_match = IMG_ALT_RE.search(img_tag)
        alt = alt_match.group(1) if alt_match else ""  # already HTML-escaped text
        caption = _esc(attrs["caption"]) if "caption" in attrs else alt
        style = f' style="width: {_esc(attrs["width"])}"' if attrs.get("width") else ""

        id_attr = ""
        num_marker = ""
        fig_id = attrs.get("id")
        if fig_id:
            existing = project.figures.get(fig_id)
            if existing is not None:
                owner, owner_file, owner_line = existing
                loc = f"{owner_file}:{owner_line}" if owner_line is not None else owner_file
                project.error(
                    f"figure id {fig_id!r} is already used by {owner} ({loc}). "
                    f"Figure ids must be unique across the project.",
                    file=where_file, line=where_line, item_id=where_id,
                )
            else:
                project.figures[fig_id] = (where_id or where_file, where_file, where_line)
                id_attr = f' id="{_esc(fig_id)}"'
                num_marker = f'<span class="fig-num" data-fig="{_esc(fig_id)}"></span>'
                # Baked in now, not at resolution time: whether a caption
                # follows the number is static, only the number itself
                # depends on which document this figure ends up rendered in.
                if caption:
                    num_marker += " — "

        figcaption = f"<figcaption>{num_marker}{caption}</figcaption>" if (caption or num_marker) else ""
        return f'<figure class="md-figure"{id_attr}{style}>{img_tag}{figcaption}</figure>'

    html = FIGURE_RE.sub(swap, html)
    return _apply_inline_image_attrs(html, project, where_file, where_line, where_id)


def assign_figure_numbers(bodies: list[str]) -> dict[str, int]:
    """Number every `{id="..."}` figure across `bodies`, in the order given.

    Each rendered document computes its own figure numbers, fresh, in its own
    reading order (docs/design/index-blocks.md §9) -- `bodies` is that
    document's own sequence of rendered item/page bodies, e.g. one item's
    `body_html` for `item.html.j2`, or every section's items in
    `_document_sections`' order for `document.html`.
    """
    numbers: dict[str, int] = {}
    for html in bodies:
        for match in FIG_NUM_MARKER_RE.finditer(html):
            fig_id = match.group(1)
            if fig_id not in numbers:
                numbers[fig_id] = len(numbers) + 1
    return numbers


def validate_figure_refs(project: Project) -> None:
    """Eagerly catch a `[[fig:id]]` reference to an id that doesn't exist
    ANYWHERE in the project -- the one class of figure-reference mistake
    that's knowable without ever assembling a rendered document, so it's
    checked once here, right after every item/page body has been rendered,
    rather than only inside `resolve_figures` (which only ever runs from
    `render_site`, so `refdes check` -- which never renders -- would
    otherwise never catch a dangling `[[fig:...]]` the way it already
    catches a dangling `[[ITEM-ID]]`).

    The complementary "exists, but not in this specific rendered document"
    check is inherently document-shaped (the same body can render into up to
    three different documents, each with its own answer) and stays in
    `resolve_figures`, which is why this only handles the anywhere-or-not
    question and never re-warns what `resolve_figures` goes on to check.
    """
    bodies = [item.body_html for item in project.local_items] + [
        page.body_html for page in project.pages
    ]
    for html in bodies:
        for match in FIG_REF_PENDING_RE.finditer(html):
            fig_id, _label_raw, where_file, where_line_raw, where_id = match.groups()
            if fig_id in project.figures:
                continue
            where_line = int(where_line_raw) if where_line_raw else None
            project.warn(
                f"reference to figure {fig_id!r}, which does not exist. "
                f'Check the figure\'s {{id="..."}} attribute.',
                file=where_file, line=where_line, item_id=where_id or None,
            )


def resolve_figures(html: str, project: Project, numbers: dict[str, int]) -> str:
    """Fill in figure-number markers and `[[fig:id]]` cross-references in one
    piece of already-rendered HTML, using `numbers` (this document's own id ->
    Figure N map, from `assign_figure_numbers` run over the same document).

    A reference to a figure id that doesn't exist anywhere has already been
    warned about by `validate_figure_refs` (run once, at build() time) --
    this only warns about the complementary, document-scoped case: the id is
    real, just not present in *this* rendered document.
    """

    def num_marker(match: re.Match) -> str:
        return f"Figure {numbers[match.group(1)]}"

    def ref(match: re.Match) -> str:
        fig_id, label_raw, where_file, where_line_raw, where_id = match.groups()
        label = html_entities.unescape(label_raw) if label_raw else None
        where_line = int(where_line_raw) if where_line_raw else None
        item_id = where_id or None
        if fig_id not in project.figures:
            return f'<span class="ref ref-missing" title="unknown figure">{label or fig_id}</span>'
        if fig_id not in numbers:
            owner, _owner_file, _owner_line = project.figures[fig_id]
            project.warn(
                f"reference to figure {fig_id!r}, which exists on {owner} but is "
                f"not rendered on this page — figure references only resolve "
                f"within the same rendered document.",
                file=where_file, line=where_line, item_id=item_id,
            )
            return f'<span class="ref ref-missing" title="unknown figure">{label or fig_id}</span>'
        text = label or f"Figure {numbers[fig_id]}"
        return f'<a class="ref fig-ref" href="#{fig_id}">{text}</a>'

    html = FIG_NUM_MARKER_RE.sub(num_marker, html)
    return FIG_REF_PENDING_RE.sub(ref, html)


def _inline_value_replacer(project: Project, item: Item):
    """The `re.sub` callable that swaps `{{name}}` -- and `{{name | unit}}`
    -- for evaluated calc results in one item's body. A module-level factory
    rather than a closure over the render_bodies loop variable."""

    def replace_inline(match: re.Match) -> str:
        name, unit = match.group(1), (match.group(2) or "").strip()
        if name not in item.calc_values:
            project.warn(
                f"{{{{{name}}}}} does not name a calc value in this item",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            return match.group(0)
        if not unit:
            return f"`{item.calc_values[name]}`"
        # `{{P | mW}}`: convert the value itself, never the formatted
        # string -- and never silently fall back to the calc's own unit
        # when the dimension is wrong. The Value lives in the item's
        # calc environment, the same one `checks:` already reads.
        value = getattr(item, "_env", {}).get(name)
        if value is None:
            return f"`{item.calc_values[name]}`"
        try:
            converted = calc.convert_value(value, unit)
        except calc.CalcError as exc:
            project.error(
                f"{{{{{name} | {unit}}}}} — {exc}",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            return match.group(0)
        return f"`{calc.format_value(converted, project.sigfigs)}`"

    return replace_inline


def render_bodies(project: Project) -> None:
    md = _markdown_parser()

    for item in project.local_items:
        # Navis markers are *consumed* here (design §4: the published page
        # shows no marker bytes), on the render-local copy of the body --
        # never on item.body, which is hash input. strip_markers returns the
        # same string object when the body has no `navi:` prefix at all, so
        # a Navi-free project renders byte-identically.
        source = navis_mod.strip_markers(item.body)
        # Substitute inline calc values before markdown sees the text.
        source = INLINE_VALUE_RE.sub(_inline_value_replacer(project, item), source)

        # Swap calc blocks for placeholders, render, then inject the evaluated
        # tables. The placeholder has to be plain text -- an HTML comment would be
        # escaped, since we render markdown with html disabled on purpose.
        extracted = calc.extract_blocks_with_lines(source)
        blocks = [block for block, _, _ in extracted]
        block_names = [name or "" for _, _, name in extracted]
        for index in range(len(blocks)):
            source = calc.CALC_BLOCK_RE.sub(
                f"\n{_placeholder(index)}\n", source, count=1
            )

        html = md.render(source)

        cursor = 0
        for index in range(len(blocks)):
            count = _calc_line_count(blocks[index])
            chunk = item.calcs[cursor : cursor + count]
            cursor += count
            table = _calc_table_html(chunk, block=block_names[index])
            token = _placeholder(index)
            if f"<p>{token}</p>" in html:
                html = html.replace(f"<p>{token}</p>", table)
            else:
                html = html.replace(token, table)

        html = _process_images(html, project, item.source_file, item.source_line, item.id)
        html = _apply_figure_attrs(html, project, item.source_file, item.source_line, item.id)
        item.body_html = _linkify(
            html, project, item.source_file, item.source_line, item.id
        )


def render_pages(project: Project) -> None:
    """Render narrative pages: markdown, generated blocks, item cross-references,
    page-to-page links."""
    md = _markdown_parser()
    known = {page.slug for page in project.pages}

    for page in project.pages:
        # Generated blocks ({{index}}, {{cascade}}) extract from raw source
        # and placeholder-swap before md.render, then get their real HTML
        # back immediately after -- same two-step calc blocks already use.
        # This has to land before _linkify (next): an index/cascade table's
        # cells are item IDs, and injecting the table before _linkify runs
        # means _linkify's own pass over the whole page picks up every ID
        # for free, with the standard hover preview -- see blocks.py's
        # module docstring.
        source, block_htmls = blocks_mod.extract_blocks(
            project,
            page.body,
            page.source_file,
            page.front_matter_lines,
        )
        html = md.render(source)
        for index, block_html in enumerate(block_htmls):
            token = blocks_mod.placeholder(index)
            if f"<p>{token}</p>" in html:
                html = html.replace(f"<p>{token}</p>", block_html)
            else:
                html = html.replace(token, block_html)

        html = _process_images(html, project, page.source_file)
        html = _apply_figure_attrs(html, project, page.source_file)
        html = _linkify(html, project, page.source_file)
        page.body_html = pages_mod.rewrite_page_links(html, known)
        pages_mod.add_heading_anchors(page)


# --------------------------------------------------------------------- static assets


def walk_site_assets(project: Project) -> Iterator[tuple[str, str, bool]]:
    """Walk every declared `site.assets:` directory once: yields
    (absolute path, project-root-relative path with forward slashes,
    contained?) per file, in walk order.

    *Contained* means the file's real path -- what a symlink actually names,
    resolved at walk time, not at load -- is inside the project root. A
    symlinked file pointing outside is yielded as not contained, because
    `schema._confined_asset_dirs` can only judge the configuration at load
    while the tree keeps moving: the serve poller re-walks on a timer, and
    an author's own tree can swap a symlink under any of us. A *directory*
    whose real path leaves the root -- retargeted into a symlink after the
    load that accepted it, or pointing at the root itself -- is not entered
    at all: enumerating the outside tree to filter it afterwards is already
    reading information out of it, and `os.walk` never descends into nested
    symlinked directories to begin with. What remains is the race between
    one of these checks and the syscall that follows it; this layer shrinks
    the window from "however long since the config loaded" to one poll
    step, not to zero.

    Every asset reader walks through here -- the poller's revision inputs
    (`serve.state.asset_files`), this module's bulk registration and
    bare-name search -- so a file outside the root is never hashed,
    published, or resolved by one reader and missed by another
    (IMAGE-ASSET-006). Callers decide what a file outside the root means:
    silence for a watcher, a diagnostic for a build.
    """
    root = project.root
    root_real = os.path.realpath(root)
    for rel_dir in project.asset_dirs:
        full_dir = os.path.join(root, rel_dir)
        if not os.path.isdir(full_dir):
            continue
        if not os.path.realpath(full_dir).startswith(root_real + os.sep):
            continue
        for dirpath, _dirnames, filenames in os.walk(full_dir):
            for name in filenames:
                full_path = os.path.join(dirpath, name)
                contained = os.path.realpath(full_path).startswith(root_real + os.sep)
                rel = os.path.relpath(full_path, root).replace("\\", "/")
                yield full_path, rel, contained


def collect_static_assets(project: Project) -> None:
    """Register every file under a `site.assets:` directory, no reference needed.

    For a local file that is linked to (a PDF, a datasheet not managed as a
    citation) rather than embedded as an `<img>`, there is nothing in the
    rendered HTML to resolve automatically -- the author writes the `href`
    themselves, pointed at `assets/<path under the declared directory>`. This
    just makes sure the file is actually there to be linked to.

    Registered as an identity mapping (source path -> itself), never hashed --
    unlike `<img src>`, refdes doesn't own the `href` an author types by hand
    into a `site.assets:`-backed link, so hashing the destination would
    silently break it with no way for the tool to catch that at build time
    (docs/design/index-blocks.md §10's explicit scope line).

    A directory or file whose real path leaves the project root
    (IMAGE-ASSET-006) is refused rather than copied -- publishing it would
    ship bytes the repository does not contain -- with a warning naming the
    escaped entry, since silence would read as a working asset directory.

    An unreadable file (IMAGE-ASSET-007) is *not* filtered here: the
    registration is what a reference resolves through, and the readability
    refusal belongs to `check_registered_assets_readable` (after the render
    pass), which keeps a referenced file's single error at the reference.
    """
    root_real = os.path.realpath(project.root)
    for rel_dir in project.asset_dirs:
        full_dir = os.path.join(project.root, rel_dir)
        if not os.path.isdir(full_dir):
            project.warn(f"site.assets entry {rel_dir!r} is not a directory", file="refdes-project.yaml")
        elif not os.path.realpath(full_dir).startswith(root_real + os.sep):
            project.warn(
                f"site.assets entry {rel_dir!r} resolves outside the project "
                "root (via a symlink?) and nothing under it is published",
                file="refdes-project.yaml",
            )
    for _full_path, rel, contained in walk_site_assets(project):
        if not contained:
            project.warn(
                f"site.assets file {rel!r} resolves outside the project root "
                "(via a symlink?) and is not published",
                file="refdes-project.yaml",
            )
            continue
        project.assets[rel] = rel


def check_registered_assets_readable(project: Project) -> None:
    """Refuse every registered asset the build cannot read (IMAGE-ASSET-007).

    Runs after every render pass that resolves image references --
    `render_bodies` and `render_pages` -- and that order is the whole
    design: the render passes have already named the *referenced*
    unreadable files at their references (their single error, in the
    sentence that fits an author whose body links the file), and
    `readable_probe` / `unreadable_assets` record what they saw, so this
    pass adds a refusal only for the files no reference gates -- the
    `site.assets:` bulk-copy layout of the resweep probe, which `refdes
    check` renders and publishes nothing, so a copy-time-only refusal
    would leave `check` passing a
    project whose build cannot publish it. The probe is open-and-close, no
    content read. A file that vanished between the walk and here is dropped
    silently -- there is nothing to publish, and a reference to it already
    hit the reference gate's own "does not exist" sentence. The refused
    file stays registered; the copy loop skips it, so the site publishes
    the rest without it.
    """
    for rel in sorted(project.assets):
        if rel in project.readable_probe or rel in project.unreadable_assets:
            continue
        try:
            # O_NONBLOCK: the registration walk yields every entry
            # `os.walk` finds, FIFOs included, and a blocking O_RDONLY
            # open would hang the whole command until a writer appears
            # (IMAGE-ASSET-007 review round 2). Non-regular files answer
            # instantly and stay as base left them: registered, skipped
            # at publish by the copy loop's `isfile` check.
            os.close(os.open(os.path.join(project.root, *rel.split("/")),
                             os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)))
        except FileNotFoundError:
            continue
        except OSError as exc:
            project.unreadable_assets.add(rel)
            project.error(
                f"site.assets file {rel!r} cannot be read: {exc.strerror or exc}. "
                "Make it readable, or remove it from the site.assets: "
                "directory -- it is not published",
                file="refdes-project.yaml",
            )


# ------------------------------------------------------------------------ entry point


def _amends_may_point_at(project: Project, item_type: str) -> bool:
    """Whether the schema lets any declared type write an `amends` link onto
    an item of ``item_type`` -- the same target rule link validation uses
    (``accepts_type``: an empty target list is unrestricted, subtypes satisfy
    their parent's list). A project overlay that declares a type replaces its
    links wholesale, so this asks the project's resolved schema, not the
    bundled standard: an overlay's `log` without an `amends` verb gets no
    `amends:` advice, exactly because following it would be an unknown field.
    """
    return any(
        project.accepts_type(item_type, targets)
        for spec in project.types.values()
        for name, targets in spec.links.items()
        if name == "amends"
    )


def warn_edited_after_captured(project: Project) -> None:
    """Phase H3: "edited after captured" is a diagnostic and never a failure.

    One warning per captured item whose live semantic content differs from
    its snapshot, naming the item, the capture event, and the successor that
    captured it. Reported through ``project.warn`` only -- it can never move
    the exit code, and it reads `.refdes/history/` without writing it. A
    store that refuses to be read is reported the same way: the check
    declines, the build proceeds."""
    try:
        findings = history_mod.edited_after_captured(project)
    except history_mod.HistoryKeyError as exc:
        project.error(exc.message, file=exc.file)
        return
    except (history_mod.HistoryError, OSError) as exc:
        project.warn(
            f"edited-after-captured was not checked: the history store "
            f"could not be read ({exc})",
            file="refdes-project.yaml",
        )
        return
    by_key = {item.key: item for item in project.items.values() if item.key}
    for finding in findings:
        item = finding.item
        label = item.id or item.key
        successor_key = str(finding.event.get("successor_key") or "")
        successor = by_key.get(successor_key)
        succ_label = successor.id or successor.key if successor else successor_key
        captured_when = f"; captured when {succ_label} followed it" if succ_label else ""
        # Run-5 F4's remedy, scoped to where it is legal: `amends` is a verb
        # one type declares for correcting entries, so the advice applies
        # only where the project's own schema lets an `amends` link point at
        # this entry's type. An append-only type whose schema declares no
        # such verb, and an editable type -- which is most of what `history
        # capture` can take -- would both fail the build or warn unknown-field
        # if they followed it, so the warning says plainly that the snapshot
        # no longer matches and stops; an unknown type is not claimed to be
        # editable either, since the tool knows nothing about it.
        spec = project.types.get(item.type)
        if spec is None:
            correction = (
                "Nothing in this project's schema describes the entry's "
                "type, so the tool cannot say what a deliberate edit needs "
                "done about it; revert it if it was not deliberate."
            )
        elif spec.append_only and _amends_may_point_at(project, item.type):
            correction = (
                f"If the edit was a correction, revert it and append a new "
                f"entry with `amends: [{label}]` instead; otherwise there is "
                "nothing to do."
            )
        elif spec.append_only:
            correction = (
                "The entry's type is append-only, but this schema declares "
                "no `amends` link that may point at it, so a deliberate edit "
                "needs nothing done about it; revert it if it was not "
                "deliberate."
            )
        else:
            correction = (
                "The entry's type is editable, so a deliberate edit needs "
                "nothing done about it; revert it if it was not deliberate."
            )
        project.warn(
            f"{label}: edited after captured -- current semantic "
            f"content differs from the snapshot in {finding.event['kind']} "
            f"event {finding.event['id']}{captured_when}. {correction} "
            f"See {docs_url_mod.DESIGN_LOG_DOCS}.",
            file=item.source_file,
            line=item.source_line,
            item_id=item.id,
        )


def warn_uncaptured_edits(project: Project) -> None:
    """Run-5 finding B3: an edit to a history-backed entry that was never
    captured is an edit with no record of it, and that is said out loud.

    ``sealing: history`` drops the build-time lock, so the only thing that can
    still say "this entry used to say something else" is a capture. An entry
    with none -- every entry of a project that upgraded from the build-time
    seal, until someone captures it -- could be rewritten wholesale with
    ``check``, ``build`` and ``release`` all silent, and the next release would
    stamp the rewrite as the recorded truth. The legacy seal record still holds
    the hash it was sealed under, so the edit is detectable, and silence about a
    detectable one is the finding.

    One warning per entry, naming the entry, the record the prior hash came
    from, and the command that ends the blind spot. Reported through
    ``project.warn`` only -- it can never move the exit code, and it reads
    ``.refdes/`` without writing it. An entry with a capture is left to
    ``warn_edited_after_captured``, which says more about it; an entry nothing
    ever recorded stays silent, because there is genuinely nothing here to
    report an edit against. An unreadable history store is left unsaid here for
    the same reason: ``warn_edited_after_captured`` reads the same store one
    step earlier in this same build and is the diagnostic that names it, and a
    second copy of that sentence would only inflate the counts it reports."""
    try:
        findings = history_mod.uncaptured_edits(project)
    except (history_mod.HistoryError, OSError):
        return
    for finding in findings:
        item = finding.item
        label = item.id or item.key
        project.warn(
            f"{label}: edited while uncaptured -- the current content no longer "
            f"matches the hash {finding.recorded} recorded in "
            f"{finding.seal_file}, and nothing in .refdes/history/ holds a "
            "snapshot of this entry, so the edit leaves no trace. Run "
            f"`refdes history capture {label}` to record the current text; an "
            "edit after that is reported as edited after captured.",
            file=item.source_file,
            line=item.source_line,
            item_id=item.id,
        )


def build(
    project: Project,
    seal_write: bool = False,
    reseal: bool = False,
    accept_board_move: bool = False,
    require_citations: bool = False,
) -> Project:
    pages_mod.load_pages(project)
    collect_static_assets(project)
    calc.set_unit_aliases(project.unit_aliases)
    calc.set_preferred_units(project.preferred_units)
    imports.load_imports(project)
    workspaces_mod.resolve(project)
    boards_mod.resolve(project)
    pages_mod.validate_boards(project)
    pages_mod.validate_workspaces(project)
    validate_items(project)
    validate_former_ids(project)
    ids_mod.validate_prefixes(project)
    keys_mod.validate(project)
    resolve_links(project)
    chain_graph = chains_mod.build_graph(project)
    chains_mod.resolve(project, graph=chain_graph)
    validate_conforms_to(project)
    validate_includes(project)
    workspaces_mod.lint_cross_workspace_references(project)
    blocked_mod.resolve(project)
    status_links_mod.warn_conflicts(project)
    run_calcs(project)
    run_checks(project)
    compute_hashes(project)
    warn_edited_after_captured(project)
    warn_uncaptured_edits(project)
    seal.verify(project, write=seal_write, reseal=reseal)
    boards_mod.verify(project, write=seal_write, accept_move=accept_board_move)
    boards_mod.lint_tokens(project)
    lint_own_tags(project)
    compute_coverage(project, chain_graph=chain_graph)
    compute_board_coverage(project, chain_graph=chain_graph)
    citations_mod.verify(project, require=require_citations)
    # Navis (in-prog-logs/navis-design-20261025.md §7): the scan reads body
    # bytes and populates Item.navis -- it is deliberately *after*
    # compute_hashes/seal.verify, and it mutates neither body nor any hash
    # input, so a Navi-free project's hashes and a Navi'd project's hashes
    # are byte-identical to the same content scanned without it (§7.1).
    for d in navis_mod.scan(project):
        project.diagnostics.append(d)
    # Slice 3 (design §9): the archive store's own findings -- a record
    # this build cannot read, and a record whose marker is gone. Like the
    # scan, this reads and reports only; it writes nothing.
    for d in navis_mod.archive_diagnostics(project):
        project.diagnostics.append(d)
    render_bodies(project)
    render_pages(project)
    # After EVERY render pass that can reference an asset (bodies and
    # pages): the passes have named the referenced unreadable files at
    # their references, so this adds a refusal only for files no
    # reference gates (IMAGE-ASSET-007 review round 8 -- running it
    # between the two passes double-reported page references).
    check_registered_assets_readable(project)
    validate_figure_refs(project)
    return project
