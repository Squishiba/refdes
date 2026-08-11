"""Turn parsed items into a resolved, evaluated, validated project."""

from __future__ import annotations

import hashlib
import html as html_entities
import json
import os
import re

from markdown_it import MarkdownIt

from . import boards as boards_mod
from . import calc, imports, pages as pages_mod, seal
from .model import INVALIDATE, CalcLine, CheckResult, Coverage, Item, Project

# Explicit reference: [[REQ-PWR-002]] or [[REQ-PWR-002|the input range]]
EXPLICIT_REF_RE = re.compile(r"\[\[\s*([A-Za-z0-9\-_]+)\s*(?:\|\s*([^\]]+?)\s*)?\]\]")
# Bare reference: REQ-PWR-002 appearing in prose.
BARE_REF_RE = re.compile(r"(?<![\w\-/])([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{1,6})(?![\w\-])")
# Inline calc value: {{P_diss}}
INLINE_VALUE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
# Regions of rendered HTML where references must not be linkified.
PROTECTED_RE = re.compile(r"<pre\b[\s\S]*?</pre>|<code\b[\s\S]*?</code>", re.IGNORECASE)
# `<img src="...">` as markdown-it emits it -- html is off, so this only ever comes
# from `![alt](src)`, never from a literal tag the author typed. Three groups so a
# rewrite can replace just the URL and leave the rest of the tag untouched.
IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.IGNORECASE)
# A URL (has a scheme) or protocol-relative reference: not ours to validate.
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:|^//")
# A whole paragraph that is nothing but one image immediately followed by a
# Quarto-style attribute suffix: `![alt](src){width=60% caption="..."}`. Anything
# else -- no suffix, other text in the paragraph -- is left completely alone.
FIGURE_RE = re.compile(
    r'<p>\s*(<img\b[^>]*?>)\s*\{([^{}]*)\}\s*</p>', re.IGNORECASE
)
FIGURE_ATTR_RE = re.compile(r'([A-Za-z_][\w-]*)\s*=\s*(?:"([^"]*)"|(\S+))')
IMG_ALT_RE = re.compile(r'\balt="([^"]*)"', re.IGNORECASE)


# ----------------------------------------------------------------------- validation


def validate_items(project: Project) -> None:
    for item in project.local_items:
        spec = project.types[item.type]

        for fname, fspec in spec.fields.items():
            value = item.fields.get(fname)
            if fspec.required and (value is None or str(value).strip() == ""):
                project.error(
                    f"missing required field {fname!r}",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            if value is None:
                continue
            if fspec.type == "enum" and fspec.choices and value not in fspec.choices:
                import difflib

                close = difflib.get_close_matches(str(value), fspec.choices, n=1, cutoff=0.5)
                hint = f" Did you mean {close[0]!r}?" if close else ""
                project.error(
                    f"{fname}: {value!r} is not one of {fspec.choices}.{hint}",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif fspec.type == "limit":
                try:
                    calc.parse_limit(str(value))
                except calc.CalcError as exc:
                    project.error(
                        f"{fname}: {exc}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )


def resolve_links(project: Project) -> None:
    for item in project.items.values():
        spec = project.types.get(item.type)
        if spec is None:  # imported item of an undeclared type
            continue
        for link_name, targets in item.links.items():
            allowed = spec.links.get(link_name, [])
            for target_id in targets:
                target = project.items.get(target_id)
                if target is None:
                    project.error(
                        f"{link_name} points at {target_id!r}, which does not exist",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                    continue
                if allowed and target.type not in allowed:
                    project.error(
                        f"{link_name} may point at {allowed}, but {target_id} is a "
                        f"{target.type}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                    continue
                inverse = project.inverse_of.get(link_name, f"{link_name}_by")
                target.backlinks.setdefault(inverse, []).append(item.id)


COVERABLE = ("requirement", "constraint")


def compute_coverage(project: Project) -> None:
    """Distinct notions of done, which people routinely conflate.

    addressed  — somebody has worked on it and written it up in the design log
    claimed    — a decision or component says it meets it, but hasn't settled
                 (its status is not in the type's satisfying_statuses:, if declared)
    satisfied  — a settled decision or component claims to meet it
    verified   — a test proves it

    A requirement can be satisfied without being verified, and addressed without
    being satisfied. Collapsing those into one "done" flag is how open work goes
    missing.
    """
    for item in project.local_items:
        if item.type not in COVERABLE:
            continue
        if item.fields.get("status") == "retired":
            continue

        cov = Coverage(item_id=item.id)
        # Each edge may be declared from either end.
        cov.addressed_by = sorted(
            set(item.backlinks.get("addressed_by", []))
            | set(item.links.get("addresses", []))
        )

        satisfying_ids = sorted(
            set(item.backlinks.get("satisfied_by", []))
            | set(item.links.get("satisfies", []))
        )
        settled: list[str] = []
        claimed: list[str] = []
        for satisfier_id in satisfying_ids:
            satisfier = project.items.get(satisfier_id)
            spec = project.types.get(satisfier.type) if satisfier else None
            allowed = spec.satisfying_statuses if spec else None
            # Unconfigured type: every link counts as settled, same as before
            # satisfying_statuses existed.
            if allowed is not None and satisfier.fields.get("status") not in allowed:
                claimed.append(satisfier_id)
            else:
                settled.append(satisfier_id)
        cov.satisfied_by = settled
        cov.claimed_by = claimed

        cov.verified_by = sorted(
            set(item.backlinks.get("verified_by", []))
            | set(item.links.get("verified_by", []))
        )
        project.coverage[item.id] = cov

        if cov.stage == "open":
            project.warn(
                "nothing addresses, satisfies, or verifies this yet",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
        elif not cov.verified_by and item.type == "requirement":
            project.warn(
                f"{cov.stage} but not verified (no test links to it)",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )


# ----------------------------------------------------------------------------- calc


def run_calcs(project: Project) -> None:
    for item in project.local_items:
        env: dict[str, calc.Value] = {}
        for block in calc.extract_blocks(item.body):
            for outcome in calc.evaluate_block(block, env):
                line = CalcLine(
                    name=outcome.name,
                    expression=outcome.expression,
                    comment=outcome.comment,
                    annotation=outcome.annotation,
                )
                if outcome.warning:
                    project.warn(
                        f"calc {outcome.name}: {outcome.warning}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                if outcome.error:
                    line.error = outcome.error
                    project.error(
                        f"calc {outcome.name or outcome.expression!r}: {outcome.error}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                else:
                    line.result = calc.format_value(outcome.value)
                    line.bounds = calc.format_bounds(outcome.value)
                    item.calc_values[outcome.name] = line.result
                item.calcs.append(line)
        item._env = env  # retained for check evaluation


def run_checks(project: Project) -> None:
    for item in project.local_items:
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

            name, target_id = str(entry["value"]), str(entry["against"])
            result = CheckResult(value_name=name, against=target_id)

            target = project.items.get(target_id)
            if target is None:
                result.detail = f"{target_id} does not exist"
                project.error(
                    f"check against {target_id!r}, which does not exist",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif name not in env:
                result.detail = f"no calc value named {name!r} in this item"
                project.error(
                    f"check refers to {name!r}, which no calc block defines",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif not target.fields.get("limit"):
                result.detail = f"{target_id} has no 'limit' to check against"
                project.error(
                    f"check against {target_id}, which declares no limit",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            else:
                try:
                    limit = calc.parse_limit(str(target.fields["limit"]))
                    ok, detail = limit.check(env[name])
                    result.ok, result.detail = ok, detail
                    result.actual = calc.format_value(env[name])
                    result.limit = limit.text
                    result.margin = limit.margin(env[name])
                    if not ok:
                        project.error(
                            f"{name} = {result.actual} violates {target_id} "
                            f"({limit.text})",
                            file=item.source_file, line=item.source_line, item_id=item.id,
                        )
                except calc.CalcError as exc:
                    result.detail = str(exc)
                    project.error(
                        f"check {name} against {target_id}: {exc}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )

            item.checks.append(result)


# ------------------------------------------------------------------- content hashing


def compute_hashes(project: Project) -> None:
    """Hash only the fields whose on_change mode is `invalidate`.

    This is what a link records at review time, so that a change to a `log` field
    (owner, tags) never marks downstream items suspect. Imported items keep the hash
    their own project computed.
    """
    for item in project.local_items:
        spec = project.types[item.type]
        payload: dict[str, object] = {"type": item.type}

        for fname in sorted(item.fields):
            mode = item.on_change_for(fname, spec, project.default_on_change)
            if mode == INVALIDATE:
                payload[fname] = item.fields[fname]

        for lname in sorted(item.links):
            payload[f"link:{lname}"] = sorted(item.links[lname])

        # Same precedence as fields: item field override > whole-item mode > schema.
        body_mode = item.on_change_for("body", spec, spec.body_on_change)
        if body_mode == INVALIDATE:
            normalized = re.sub(r"\s+", " ", item.body).strip()
            payload["body"] = normalized

        blob = json.dumps(payload, sort_keys=True, default=str)
        item.content_hash = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# -------------------------------------------------------------------------- markdown


def _calc_table_html(lines: list[CalcLine]) -> str:
    rows = []
    for line in lines:
        name_cell = _esc(line.name)
        if line.annotation:
            name_cell += f'<span class="calc-annotation">: {_esc(line.annotation)}</span>'
        if line.error:
            rows.append(
                f'<tr class="calc-row calc-error">'
                f'<td class="calc-name">{name_cell}</td>'
                f'<td class="calc-expr">{_esc(line.expression)}</td>'
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
            f'<td class="calc-expr">{_esc(line.expression)}</td>'
            f'<td class="calc-result">{_esc(line.result)} {bounds}</td>'
            f"{comment}</tr>"
        )
    return '<table class="calc">' + "".join(rows) + "</table>"


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
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

    def link(target_id: str, label: str | None, explicit: bool) -> str:
        target = project.items.get(target_id)
        if target is None:
            if explicit:
                project.warn(
                    f"reference to {target_id!r}, which does not exist",
                    file=where_file, line=where_line, item_id=where_id,
                )
                return f'<span class="ref ref-missing" title="unknown item">{target_id}</span>'
            return target_id
        text = label or target_id
        return (
            f'<a class="ref" href="{target.slug}.html" data-ref="{target.id}">{text}</a>'
        )

    def process(segment: str) -> str:
        segment = EXPLICIT_REF_RE.sub(
            lambda m: link(m.group(1), m.group(2), True), segment
        )
        return BARE_REF_RE.sub(lambda m: link(m.group(1), None, False), segment)

    out: list[str] = []
    last = 0
    for match in PROTECTED_RE.finditer(html):
        out.append(process(html[last : match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(process(html[last:]))
    return "".join(out)


def _process_images(
    html: str,
    project: Project,
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> str:
    """Resolve, validate, register, and rewrite local `<img src>` references.

    A local src is resolved relative to the source file's own directory -- the
    same base a browser would use to open the rendered page next to its markdown
    source. One that resolves is registered in `project.assets` under its
    project-root-relative path and rewritten to `assets/<that path>`, which is
    where `render_site` copies it, mirroring the source layout. One that does not
    resolve is a build error, not a warning: unlike a dangling cross-reference,
    there is no sensible way to render a missing image, and now that a resolving
    src is actually made to work end to end, a broken one should stop the build.
    """

    def swap(match: re.Match) -> str:
        prefix, src, suffix = match.group(1), match.group(2), match.group(3)
        if not src or _URL_SCHEME_RE.match(src):
            return match.group(0)
        full_path = os.path.normpath(
            os.path.join(project.root, os.path.dirname(where_file), src)
        )
        if not os.path.isfile(full_path):
            project.error(
                f"image src {src!r} does not exist",
                file=where_file, line=where_line, item_id=where_id,
            )
            return match.group(0)
        rel = os.path.relpath(full_path, project.root).replace("\\", "/")
        project.assets.add(rel)
        return f"{prefix}assets/{rel}{suffix}"

    return IMG_SRC_RE.sub(swap, html)


def _apply_figure_attrs(html: str) -> str:
    """Wrap `![alt](src){width=60% caption="..."}` in a real `<figure>`.

    Only a paragraph containing nothing but one image immediately followed by a
    `{...}` suffix is touched -- matched the same way `_process_images` and
    `_linkify` scan rendered HTML with a regex rather than a markdown-it plugin.
    With no suffix the image passes through completely untouched. `alt` always
    stays on the `<img>`; `caption` falls back to it when not given.
    """

    def swap(match: re.Match) -> str:
        img_tag, attrs_text = match.group(1), match.group(2)
        # markdown-it escapes '"' in plain text the same as '&', '<', '>', so the
        # quoted-value delimiters in `attrs_text` are themselves `&quot;` by the
        # time this regex ever sees them. Unescape first to parse the attributes,
        # then re-escape whatever ends up in the caption before it goes back into
        # the page as HTML text.
        attrs = {
            m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3)
            for m in FIGURE_ATTR_RE.finditer(html_entities.unescape(attrs_text))
        }
        alt_match = IMG_ALT_RE.search(img_tag)
        alt = alt_match.group(1) if alt_match else ""  # already HTML-escaped text
        caption = _esc(attrs["caption"]) if "caption" in attrs else alt
        style = f' style="width: {_esc(attrs["width"])}"' if attrs.get("width") else ""
        figcaption = f"<figcaption>{caption}</figcaption>" if caption else ""
        return f'<figure class="md-figure"{style}>{img_tag}{figcaption}</figure>'

    return FIGURE_RE.sub(swap, html)


def render_bodies(project: Project) -> None:
    # gfm-like adds tables and strikethrough, which a hardware document needs for
    # pin maps and BOM excerpts. linkify stays off: bare IDs are our own concern,
    # and raw HTML stays off so a document can never inject markup.
    md = MarkdownIt("gfm-like", {"html": False, "linkify": False})

    for item in project.local_items:
        # Substitute inline calc values before markdown sees the text.
        def replace_inline(match: re.Match) -> str:
            name = match.group(1)
            if name in item.calc_values:
                return f"`{item.calc_values[name]}`"
            project.warn(
                f"{{{{{name}}}}} does not name a calc value in this item",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            return match.group(0)

        source = INLINE_VALUE_RE.sub(replace_inline, item.body)

        # Swap calc blocks for placeholders, render, then inject the evaluated
        # tables. The placeholder has to be plain text -- an HTML comment would be
        # escaped, since we render markdown with html disabled on purpose.
        blocks = calc.extract_blocks(source)
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
            table = _calc_table_html(chunk)
            token = _placeholder(index)
            if f"<p>{token}</p>" in html:
                html = html.replace(f"<p>{token}</p>", table)
            else:
                html = html.replace(token, table)

        html = _process_images(html, project, item.source_file, item.source_line, item.id)
        html = _apply_figure_attrs(html)
        item.body_html = _linkify(
            html, project, item.source_file, item.source_line, item.id
        )


def render_pages(project: Project) -> None:
    """Render narrative pages: markdown, item cross-references, page-to-page links."""
    md = MarkdownIt("gfm-like", {"html": False, "linkify": False})
    known = {page.slug for page in project.pages}

    for page in project.pages:
        html = md.render(page.body)
        html = _process_images(html, project, page.source_file)
        html = _apply_figure_attrs(html)
        html = _linkify(html, project, page.source_file)
        page.body_html = pages_mod.rewrite_page_links(html, known)
        pages_mod.add_heading_anchors(page)


# --------------------------------------------------------------------- static assets


def collect_static_assets(project: Project) -> None:
    """Register every file under a `site.assets:` directory, no reference needed.

    For a local file that is linked to (a PDF, a datasheet not managed as a
    citation) rather than embedded as an `<img>`, there is nothing in the
    rendered HTML to resolve automatically -- the author writes the `href`
    themselves, pointed at `assets/<path under the declared directory>`. This
    just makes sure the file is actually there to be linked to.
    """
    for rel_dir in project.asset_dirs:
        full_dir = os.path.join(project.root, rel_dir)
        if not os.path.isdir(full_dir):
            project.warn(f"site.assets entry {rel_dir!r} is not a directory", file="refdes.yaml")
            continue
        for dirpath, _dirnames, filenames in os.walk(full_dir):
            for name in filenames:
                full_path = os.path.join(dirpath, name)
                rel = os.path.relpath(full_path, project.root).replace("\\", "/")
                project.assets.add(rel)


# ------------------------------------------------------------------------ entry point


def build(
    project: Project,
    seal_write: bool = False,
    reseal: bool = False,
    accept_board_move: bool = False,
) -> Project:
    pages_mod.load_pages(project)
    collect_static_assets(project)
    calc.set_unit_aliases(project.unit_aliases)
    calc.set_preferred_units(project.preferred_units)
    imports.load_imports(project)
    boards_mod.resolve(project)
    validate_items(project)
    resolve_links(project)
    run_calcs(project)
    run_checks(project)
    compute_hashes(project)
    seal.verify(project, write=seal_write, reseal=reseal)
    boards_mod.verify(project, write=seal_write, accept_move=accept_board_move)
    boards_mod.lint_tokens(project)
    compute_coverage(project)
    render_bodies(project)
    render_pages(project)
    return project
