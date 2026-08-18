"""Render the resolved project to a static HTML site plus items.json."""

from __future__ import annotations

import json
import os
import re
import shutil

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import blocked as blocked_mod
from . import build as build_mod
from . import citations as citations_mod
from . import nav as nav_mod
from .model import Item, Project

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
ASSET_DIR = os.path.join(TEMPLATE_DIR, "assets")


PAGE_HREF_RE = re.compile(r'href="([a-z0-9][a-z0-9\-_.]*)\.html"')


def _anchorize(html: str, known_slugs: set[str]) -> str:
    """Rewrite per-page links into in-document anchors.

    The multi-page site links `href="con-thm-001.html"`. In the single-document
    render every item is a section on one page, so the same reference has to become
    `href="#con-thm-001"` or it dangles — which is exactly what breaks when you
    print a page-per-item site.
    """

    def swap(match: re.Match) -> str:
        slug = match.group(1)
        if slug in known_slugs:
            return f'href="#{slug}"'
        return match.group(0)

    return PAGE_HREF_RE.sub(swap, html)


def _figured(project: Project, bodies: list[str]):
    """A `figured(html)` closure for one rendered document: numbers every
    `{id="..."}` figure across `bodies` in that document's own reading order,
    then returns a function that resolves figure-number markers and
    `[[fig:id]]` references against that one document's numbering
    (docs/design/index-blocks.md §9) -- the same per-document posture
    `_anchorize` already takes with cross-item hrefs."""
    numbers = build_mod.assign_figure_numbers(bodies)
    return lambda html: build_mod.resolve_figures(html, project, numbers)


def _in_scope(item: Item, board: str | None, workspace: str | None) -> bool:
    """The one filter every per-board/per-workspace report shares. Callers pass
    at most one of `board`/`workspace` -- both `None` means unscoped."""
    if board is not None and item.board != board:
        return False
    if workspace is not None and item.workspace != workspace:
        return False
    return True


def _document_sections(
    project: Project, board: str | None = None, workspace: str | None = None
) -> list[tuple[str, list[Item]]]:
    """Items grouped for linear reading: schema order, log entries by date.

    `board`/`workspace`, when given, scope this to that board's or
    workspace's own local items -- imported items carry neither, so a scoped
    document has no "Imported references" section.
    """
    sections: list[tuple[str, list[Item]]] = []
    for type_name, spec in project.types.items():
        items = [
            i
            for i in project.items.values()
            if i.type == type_name and not i.external and _in_scope(i, board, workspace)
        ]
        if type_name == "log":
            items.sort(key=lambda i: (str(i.fields.get("date", "")), i.id))
        else:
            items.sort(key=lambda i: i.id)
        sections.append((spec.plural, items))

    if board is None and workspace is None:
        imported = sorted(
            (i for i in project.items.values() if i.external), key=lambda i: i.id
        )
        if imported:
            sections.append(("Imported references", imported))
    return sections


def _coverage_rows(
    project: Project, board: str | None = None, workspace: str | None = None
) -> list[tuple[Item, object]]:
    stage_order = {"open": 0, "addressed": 1, "claimed": 2, "satisfied": 3, "verified": 4}
    rows = [
        (project.items[item_id], cov)
        for item_id, cov in project.coverage.items()
        if item_id in project.items and _in_scope(project.items[item_id], board, workspace)
    ]
    rows.sort(key=lambda row: (stage_order.get(row[1].stage, 9), row[0].id))
    return rows


def _log_entries(
    project: Project, board: str | None = None, workspace: str | None = None
) -> list[Item]:
    return sorted(
        (
            i
            for i in project.local_items
            if i.type == "log" and _in_scope(i, board, workspace)
        ),
        key=lambda i: (str(i.fields.get("date", "")), i.id),
    )


def _check_state(item: Item) -> str:
    if not item.checks:
        return "none"
    if any(c.ok is False for c in item.checks):
        return "fail"
    if any(c.ok is None for c in item.checks):
        return "unknown"
    return "pass"


_PART_ANCHOR_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _part_anchor(part_number: str) -> str:
    """HTML id for a part number's row on parts.html -- the exact string,
    sanitized to characters an id/URL fragment can hold safely. Used both to
    write the anchor on parts.html and to link to it from a component page,
    so the two always agree."""
    return "part-" + _PART_ANCHOR_RE.sub("-", part_number).strip("-").lower()


def _trace_view(item: Item, project: Project) -> dict:
    """Split an item's links/backlinks into three buckets for the
    Traceability section: `outgoing` (this item's own declarations, minus
    self-inverse verbs), `incoming` (computed backlinks, same exclusion),
    and `self_inverse` -- every link type where `LinkType.inverse ==
    LinkType.name` (`equivalent`/`alternate` today, any future one
    automatically), merged from both `links` and `backlinks` into one
    de-duplicated list per verb.

    docs/design/standard-library.md §11: for a self-inverse verb,
    `links["equivalent"]` and `backlinks["equivalent"]` are the identical
    fact, not two different ones the way "Satisfies"/"Satisfied by" are --
    rendering them as separate Outgoing/Incoming entries would show a reader
    the same claim twice, differing only in which of the two items happened
    to type the YAML.
    """
    self_inverse: dict[str, list[str]] = {}
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {}
    for name, targets in item.links.items():
        ltype = project.link_types.get(name)
        if ltype is not None and ltype.inverse == name:
            self_inverse.setdefault(name, []).extend(targets)
        else:
            outgoing[name] = targets
    for name, sources in item.backlinks.items():
        ltype = project.link_types.get(name)
        if ltype is not None and ltype.inverse == name:
            self_inverse.setdefault(name, []).extend(sources)
        else:
            incoming[name] = sources
    return {
        "outgoing": outgoing,
        "incoming": incoming,
        "self_inverse": {name: sorted(set(ids)) for name, ids in self_inverse.items()},
    }


def summary_payload(
    project: Project, board: str | None = None, workspace: str | None = None
) -> dict:
    """Everything the at-a-glance view needs, computed once.

    The per-type pages answer "what does this item say". This answers the questions
    you actually ask at a design review: what is closest to breaking, what numbers
    does the design depend on, and what is not traced to anything.

    `board`/`workspace`, when given, scope every table on the page to that
    board's or workspace's own items.
    """
    local = [
        i
        for i in project.items.values()
        if not i.external and _in_scope(i, board, workspace)
    ]

    # Every evaluated check, tightest margin first. A pass at 2% and a pass at 200%
    # are not the same engineering situation, and sorting by margin is what surfaces
    # the difference without anyone having to hunt.
    margin_rows = [
        (item, check)
        for item in local
        for check in item.checks
        if check.ok is not None
    ]
    margin_rows.sort(
        key=lambda row: (row[1].margin is None, row[1].margin if row[1].margin is not None else 0.0)
    )

    # Every number the design computes, in one table.
    calc_rows = [
        (item, line)
        for item in sorted(local, key=lambda i: i.id)
        for line in item.calcs
    ]

    # Items connected to nothing in any direction. Not an error -- a component can
    # legitimately stand alone -- but it is where traceability silently stops.
    #
    # A `checks:` entry is a real dependency that is not a link: a constraint an
    # expression is checked against is traced, even with no edges pointing at it.
    # Counting only links would list such a constraint as untraced, directly
    # contradicting the margins table above.
    checked_against = {
        check.against for i in local for check in i.checks if check.against
    }
    orphans = sorted(
        (
            i
            for i in local
            if not any(i.links.values())
            and not any(i.backlinks.values())
            and i.id not in checked_against
        ),
        key=lambda i: i.id,
    )

    log_entries = sorted(
        (i for i in local if i.type == "log"),
        key=lambda i: (str(i.fields.get("date", "")), i.id),
        reverse=True,
    )

    type_rows = []
    for type_name, spec in project.types.items():
        items = [i for i in local if i.type == type_name]
        if not items:
            continue
        covered = [project.coverage[i.id] for i in items if i.id in project.coverage]
        type_rows.append(
            {
                "name": type_name,
                "plural": spec.plural,
                "count": len(items),
                "verified": sum(1 for c in covered if c.stage == "verified"),
                "coverable": len(covered),
            }
        )

    local_ids = {i.id for i in local}
    stage_counts = {"open": 0, "addressed": 0, "claimed": 0, "satisfied": 0, "verified": 0}
    for item_id, cov in project.coverage.items():
        if item_id in local_ids:
            stage_counts[cov.stage] = stage_counts.get(cov.stage, 0) + 1
    total_covered = sum(stage_counts.values())

    evaluated = [c for _i, c in margin_rows]
    with_margin = [c.margin for c in evaluated if c.margin is not None]

    return {
        "item_count": len(local),
        "margin_rows": margin_rows,
        "calc_rows": calc_rows,
        "orphans": orphans,
        "log_entries": log_entries[:10],
        "log_total": len(log_entries),
        "type_rows": type_rows,
        "stage_counts": stage_counts,
        "total_covered": total_covered,
        "checks_total": len(evaluated),
        "checks_failing": sum(1 for c in evaluated if c.ok is False),
        "tightest": min(with_margin) if with_margin else None,
        "calc_errors": sum(1 for _i, line in calc_rows if line.error),
    }


def preview_payload(project: Project) -> dict:
    out = {}
    for item in project.items.values():
        spec = project.types[item.type]
        fields = []
        for name in spec.preview:
            value = item.fields.get(name)
            if value in (None, "", []):
                continue
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            text = str(value)
            fields.append(
                {"name": name, "value": text if len(text) <= 160 else text[:157] + "…"}
            )
        out[item.id] = {
            "id": item.id,
            "type": spec.label,
            "title": item.title,
            "href": f"{item.slug}.html",
            "fields": fields,
            "check": _check_state(item),
        }
    return out


def _citations_json(item: Item) -> dict:
    """Resolved provenance for `item.citations`, grouped by field and ordered by index.

    Deliberately kept separate from `fields` -- `fields[fname][i]` is authored
    intent (url, rev, vendor:), this is what it resolved to (sha256, vendored,
    pinned). Every entry always carries the same keys, `state` included, so
    "unpinned" and "pinned but not vendored" are each a distinct, explicit
    `state` value rather than something a consumer infers from an absent key.
    """
    out: dict[str, list[dict]] = {}
    for status in sorted(item.citations, key=lambda s: (s.spec.field, s.spec.index)):
        out.setdefault(status.spec.field, []).append(
            {
                "url": status.spec.url,
                "state": status.state,
                "pinned": status.state != "unpinned",
                "vendored": status.vendored,
                "sha256": status.sha256,
                "fetched": status.fetched,
                "local_path": status.local_path,
                "detail": status.detail,
            }
        )
    return out


def items_json(project: Project) -> dict:
    """The machine-readable export. Anything downstream should read this, not HTML.

    The `boards` key and each item's `board` are only present when a project has
    actually declared a `boards:` registry -- so a project that has not adopted
    boards gets byte-identical output to before this feature existed.
    """
    payload: dict = {
        "title": project.title,
        "version": project.version,
    }
    if project.boards:
        payload["boards"] = {
            name: {"label": spec.label, "token": spec.token, "path": spec.path}
            for name, spec in sorted(project.boards.items())
        }
    if project.workspaces:
        payload["workspaces"] = {
            name: {"label": spec.label, "shared": spec.shared, "path": spec.path}
            for name, spec in sorted(project.workspaces.items())
        }

    payload["coverage"] = {
        item_id: {
            "stage": cov.stage,
            "addressed_by": cov.addressed_by,
            "claimed_by": cov.claimed_by,
            "satisfied_by": cov.satisfied_by,
            "verified_by": cov.verified_by,
        }
        for item_id, cov in sorted(project.coverage.items())
    }
    payload["types"] = {
        name: {
            "label": spec.label,
            "plural": spec.plural,
            "prefix": spec.prefix,
            "append_only": spec.append_only,
            "fields": {
                f.name: {
                    "type": f.type,
                    "on_change": f.on_change,
                    "required": f.required,
                    "choices": f.choices,
                }
                for f in spec.fields.values()
            },
            "links": spec.links,
        }
        for name, spec in project.types.items()
    }

    items_out = []
    for item in sorted(project.items.values(), key=lambda i: i.id):
        entry = {
            "id": item.id,
            "type": item.type,
            "title": item.title,
        }
        if project.boards:
            entry["board"] = item.board
        if project.workspaces:
            entry["workspace"] = item.workspace
        entry.update({
            "fields": item.fields,
            "former_ids": item.former_ids,
            "citations": _citations_json(item),
            "links": item.links,
            "backlinks": item.backlinks,
            "content_hash": item.content_hash,
            "external": item.external,
            "origin": item.origin,
            "source": {"file": item.source_file, "line": item.source_line},
            "calcs": [
                {
                    "name": c.name,
                    "expression": c.expression,
                    "result": c.result,
                    "bounds": c.bounds,
                    "error": c.error,
                }
                for c in item.calcs
            ],
            "checks": [
                {
                    "value": c.value_name,
                    "against": c.against,
                    "ok": c.ok,
                    "actual": c.actual,
                    "limit": c.limit,
                    "detail": c.detail,
                    "margin": c.margin,
                }
                for c in item.checks
            ],
        })
        items_out.append(entry)
    payload["items"] = items_out

    payload["diagnostics"] = [
        {
            "level": d.level,
            "message": d.message,
            "file": d.file,
            "line": d.line,
            "item": d.item_id,
        }
        for d in project.diagnostics
    ]
    return payload


MANIFEST_NAME = ".refdes-manifest.json"


def _load_manifest(out_dir: str) -> set[str]:
    path = os.path.join(out_dir, MANIFEST_NAME)
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return set()
    return set(data) if isinstance(data, list) else set()


def _asset_file_list(asset_dir: str) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(asset_dir):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), asset_dir).replace("\\", "/")
            out.append(f"assets/{rel}")
    return out


def _copy_project_assets(project: Project, out_dir: str, written: set[str]) -> None:
    """Copy `project.assets` into `_site/assets/`: source path -> destination
    path (relative to assets/), the latter content-hashed for a resolved
    `<img src>` and identity-mapped for a `site.assets:` directory file (see
    `project.assets`'s own docstring in model.py).

    Runs after the template's own `assets/` copytree, so a project asset whose
    path collides with a name the template itself owns (`style.css`, `app.js`) is
    refused with a build error instead of silently overwriting it -- the same
    guard `render_site` already applies to a page whose slug collides with a
    generated report.
    """
    reserved = set(os.listdir(ASSET_DIR)) if os.path.isdir(ASSET_DIR) else set()
    asset_out = os.path.join(out_dir, "assets")
    for rel, dest_rel in sorted(project.assets.items()):
        top = dest_rel.split("/", 1)[0]
        if top in reserved:
            project.error(
                f"asset {rel!r} would be written to assets/{top}, which the site "
                f"template itself uses. Rename the source file or its enclosing "
                f"directory."
            )
            continue
        src = os.path.join(project.root, *rel.split("/"))
        if not os.path.isfile(src):
            continue  # already reported as a build error when the reference was resolved
        dest = os.path.join(asset_out, *dest_rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        written.add(f"assets/{dest_rel}")


def _copy_datasheet_assets(project: Project, out_dir: str, written: set[str]) -> None:
    """Copy `project.datasheet_assets` into `_site/assets/`, flattened.

    Populated only when `publish_datasheets` is on (citations.py) -- source and
    destination differ (`.refdes/vendor/<sha256><ext>` -> flattened
    `assets/datasheets/<sha256><ext>`), so this can't reuse
    `_copy_project_assets`'s mirroring copy.
    """
    asset_out = os.path.join(out_dir, "assets")
    for rel, src in sorted(project.datasheet_assets.items()):
        target = f"assets/{rel}"
        if target in written:
            project.error(
                f"published datasheet {rel!r} collides with an existing "
                f"{target}, most likely a site.assets: directory of the same "
                f"name -- rename one of them."
            )
            continue
        if not os.path.isfile(src):
            continue  # already reported as cache_missing when the citation was resolved
        dest = os.path.join(asset_out, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        written.add(target)


def _prune_stale_output(out_dir: str, written: set[str]) -> None:
    """Delete output from a previous build that this build no longer produces.

    A deleted or renamed item must not leave a live, still-linkable page behind.
    Only ever removes files this tool itself wrote and tracked in the manifest --
    never anything else that happens to live in out_dir.
    """
    previous = _load_manifest(out_dir)
    for rel in previous - written:
        path = os.path.join(out_dir, *rel.split("/"))
        if os.path.isfile(path):
            os.remove(path)
    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8") as fh:
        json.dump(sorted(written), fh, indent=2)


def render_site(project: Project) -> str:
    out_dir = os.path.join(project.root, project.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    written: set[str] = set()

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["check_state"] = _check_state
    env.globals["coverage_of"] = project.coverage.get
    env.globals["blocked_chains_for"] = blocked_mod.by_item(project).get
    env.globals["trace_view"] = lambda item: _trace_view(item, project)
    env.globals["part_anchor"] = _part_anchor
    citations_by_url = citations_mod.by_url(project)
    parts_by_number = citations_mod.by_part_number(project)
    env.globals["parts_usage"] = parts_by_number.get

    # A page called `index` owns index.html; otherwise the item dashboard does. This
    # is what lets a docs-only project render as an ordinary website.
    page_slugs = {page.slug for page in project.pages}
    dashboard_name = "items.html" if "index" in page_slugs else "index.html"
    env.globals["home_href"] = "index.html"
    env.globals["dashboard_href"] = dashboard_name

    previews = preview_payload(project)
    previews_json = json.dumps(previews, ensure_ascii=False)

    by_type: dict[str, list[Item]] = {}
    for item in sorted(project.items.values(), key=lambda i: i.id):
        by_type.setdefault(item.type, []).append(item)

    failing = [
        (item, check)
        for item in project.items.values()
        for check in item.checks
        if check.ok is False
    ]
    # Coverage, ordered so the work that still needs doing floats to the top.
    coverage_rows = _coverage_rows(project)
    outstanding = [row for row in coverage_rows if row[1].stage != "verified"]

    log_entries = _log_entries(project)

    # Generated reports own these filenames. A page of the same name would be
    # silently clobbered by whichever is written last, so say so instead. Each
    # board and each workspace adds its own scoped set of the same six
    # reports -- schema.py's load-time check already guarantees a board key
    # and a workspace key never collide, so these two updates never fight.
    report_names = ("coverage", "log", "document", "summary", "references", "parts")
    reserved = {*report_names, dashboard_name[: -len(".html")]}
    for board_key in project.boards:
        reserved.update(f"{name}-{board_key}" for name in report_names)
    for workspace_key in project.workspaces:
        reserved.update(f"{name}-{workspace_key}" for name in report_names)
    if project.items:
        keep = []
        for page in project.pages:
            if page.slug in reserved:
                project.error(
                    f"page '{page.slug}.md' would be written to {page.slug}.html, "
                    f"which is a generated report. Rename the page.",
                    file=page.source_file,
                )
            else:
                keep.append(page)
        # Drop it entirely rather than half-including it: leaving it in would put a
        # nav link on every page pointing at the report instead of the page.
        project.pages = keep

    env.globals["nav_tree"] = nav_mod.build_nav(project, dashboard_href=dashboard_name)

    page_tpl = env.get_template("page.html.j2")
    for page in project.pages:
        written.add(f"{page.slug}.html")
        with open(
            os.path.join(out_dir, f"{page.slug}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                page_tpl.render(
                    project=project, page=page, previews_json=previews_json,
                    figured=_figured(project, [page.body_html]),
                )
            )

    if project.items:
        index_tpl = env.get_template("index.html.j2")
        written.add(dashboard_name)
        with open(os.path.join(out_dir, dashboard_name), "w", encoding="utf-8") as fh:
            fh.write(
                index_tpl.render(
                    project=project,
                    by_type=by_type,
                    failing=failing,
                    outstanding=outstanding,
                    previews_json=previews_json,
                )
            )
    elif not project.pages:
        project.warn("nothing to render: no items and no pages")

    if not project.items:
        if os.path.isdir(ASSET_DIR):
            shutil.copytree(ASSET_DIR, os.path.join(out_dir, "assets"), dirs_exist_ok=True)
            written.update(_asset_file_list(ASSET_DIR))
        _copy_project_assets(project, out_dir, written)
        _copy_datasheet_assets(project, out_dir, written)
        _prune_stale_output(out_dir, written)
        return out_dir

    summary_tpl = env.get_template("summary.html.j2")
    written.add("summary.html")
    with open(os.path.join(out_dir, "summary.html"), "w", encoding="utf-8") as fh:
        fh.write(
            summary_tpl.render(
                project=project,
                previews_json=previews_json,
                **summary_payload(project),
            )
        )

    coverage_tpl = env.get_template("coverage.html.j2")
    written.add("coverage.html")
    with open(os.path.join(out_dir, "coverage.html"), "w", encoding="utf-8") as fh:
        fh.write(
            coverage_tpl.render(
                project=project,
                coverage_rows=coverage_rows,
                previews_json=previews_json,
            )
        )

    log_tpl = env.get_template("log.html.j2")
    written.add("log.html")
    with open(os.path.join(out_dir, "log.html"), "w", encoding="utf-8") as fh:
        fh.write(
            log_tpl.render(
                project=project,
                entries=log_entries,
                previews_json=previews_json,
            )
        )

    references_tpl = env.get_template("references.html.j2")
    written.add("references.html")
    with open(os.path.join(out_dir, "references.html"), "w", encoding="utf-8") as fh:
        fh.write(
            references_tpl.render(
                project=project,
                grouped=citations_by_url,
                previews_json=previews_json,
            )
        )

    parts_tpl = env.get_template("parts.html.j2")
    written.add("parts.html")
    with open(os.path.join(out_dir, "parts.html"), "w", encoding="utf-8") as fh:
        fh.write(
            parts_tpl.render(
                project=project,
                parts=parts_by_number,
                previews_json=previews_json,
            )
        )

    item_tpl = env.get_template("item.html.j2")
    for item in project.items.values():
        spec = project.types.get(item.type)
        if spec is None:  # imported item of a type this schema does not declare
            continue
        written.add(f"{item.slug}.html")
        with open(
            os.path.join(out_dir, f"{item.slug}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                item_tpl.render(
                    project=project,
                    item=item,
                    spec=spec,
                    previews_json=previews_json,
                    figured=_figured(project, [item.body_html]),
                )
            )

    known_slugs = {item.slug for item in project.items.values()}
    document_tpl = env.get_template("document.html.j2")
    doc_sections = _document_sections(project)
    written.add("document.html")
    with open(os.path.join(out_dir, "document.html"), "w", encoding="utf-8") as fh:
        fh.write(
            document_tpl.render(
                project=project,
                sections=doc_sections,
                anchored=lambda html: _anchorize(html, known_slugs),
                figured=_figured(
                    project, [item.body_html for _label, items in doc_sections for item in items]
                ),
                previews_json=previews_json,
            )
        )

    written.add("items.json")

    # One document/coverage/log/summary set per registered board, scoped to that
    # board's own items -- the unscoped pages above are unaffected either way.
    for board_key, board_spec in project.boards.items():
        board_sections = _document_sections(project, board=board_key)
        board_known_slugs = {
            item.slug for _label, items in board_sections for item in items
        }
        written.add(f"document-{board_key}.html")
        with open(
            os.path.join(out_dir, f"document-{board_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                document_tpl.render(
                    project=project,
                    board=board_spec,
                    sections=board_sections,
                    anchored=lambda html, slugs=board_known_slugs: _anchorize(html, slugs),
                    figured=_figured(
                        project, [item.body_html for _label, items in board_sections for item in items]
                    ),
                    previews_json=previews_json,
                )
            )

        written.add(f"coverage-{board_key}.html")
        with open(
            os.path.join(out_dir, f"coverage-{board_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                coverage_tpl.render(
                    project=project,
                    board=board_spec,
                    coverage_rows=_coverage_rows(project, board=board_key),
                    previews_json=previews_json,
                )
            )

        written.add(f"log-{board_key}.html")
        with open(
            os.path.join(out_dir, f"log-{board_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                log_tpl.render(
                    project=project,
                    board=board_spec,
                    entries=_log_entries(project, board=board_key),
                    previews_json=previews_json,
                )
            )

        written.add(f"references-{board_key}.html")
        with open(
            os.path.join(out_dir, f"references-{board_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                references_tpl.render(
                    project=project,
                    board=board_spec,
                    grouped=citations_mod.by_url(project, board=board_key),
                    previews_json=previews_json,
                )
            )

        written.add(f"parts-{board_key}.html")
        with open(
            os.path.join(out_dir, f"parts-{board_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                parts_tpl.render(
                    project=project,
                    board=board_spec,
                    parts=citations_mod.by_part_number(project, board=board_key),
                    previews_json=previews_json,
                )
            )

        written.add(f"summary-{board_key}.html")
        with open(
            os.path.join(out_dir, f"summary-{board_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                summary_tpl.render(
                    project=project,
                    board=board_spec,
                    previews_json=previews_json,
                    **summary_payload(project, board=board_key),
                )
            )

    # Same five reports, one set per registered workspace, scoped to that
    # workspace's own items -- mirrors the per-board loop above exactly.
    for workspace_key, workspace_spec in project.workspaces.items():
        ws_sections = _document_sections(project, workspace=workspace_key)
        ws_known_slugs = {
            item.slug for _label, items in ws_sections for item in items
        }
        written.add(f"document-{workspace_key}.html")
        with open(
            os.path.join(out_dir, f"document-{workspace_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                document_tpl.render(
                    project=project,
                    workspace=workspace_spec,
                    sections=ws_sections,
                    anchored=lambda html, slugs=ws_known_slugs: _anchorize(html, slugs),
                    figured=_figured(
                        project, [item.body_html for _label, items in ws_sections for item in items]
                    ),
                    previews_json=previews_json,
                )
            )

        written.add(f"coverage-{workspace_key}.html")
        with open(
            os.path.join(out_dir, f"coverage-{workspace_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                coverage_tpl.render(
                    project=project,
                    workspace=workspace_spec,
                    coverage_rows=_coverage_rows(project, workspace=workspace_key),
                    previews_json=previews_json,
                )
            )

        written.add(f"log-{workspace_key}.html")
        with open(
            os.path.join(out_dir, f"log-{workspace_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                log_tpl.render(
                    project=project,
                    workspace=workspace_spec,
                    entries=_log_entries(project, workspace=workspace_key),
                    previews_json=previews_json,
                )
            )

        written.add(f"references-{workspace_key}.html")
        with open(
            os.path.join(out_dir, f"references-{workspace_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                references_tpl.render(
                    project=project,
                    workspace=workspace_spec,
                    grouped=citations_mod.by_url(project, workspace=workspace_key),
                    previews_json=previews_json,
                )
            )

        written.add(f"parts-{workspace_key}.html")
        with open(
            os.path.join(out_dir, f"parts-{workspace_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                parts_tpl.render(
                    project=project,
                    workspace=workspace_spec,
                    parts=citations_mod.by_part_number(project, workspace=workspace_key),
                    previews_json=previews_json,
                )
            )

        written.add(f"summary-{workspace_key}.html")
        with open(
            os.path.join(out_dir, f"summary-{workspace_key}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                summary_tpl.render(
                    project=project,
                    workspace=workspace_spec,
                    previews_json=previews_json,
                    **summary_payload(project, workspace=workspace_key),
                )
            )

    with open(os.path.join(out_dir, "items.json"), "w", encoding="utf-8") as fh:
        json.dump(items_json(project), fh, indent=2, ensure_ascii=False, default=str)

    asset_out = os.path.join(out_dir, "assets")
    if os.path.isdir(ASSET_DIR):
        shutil.copytree(ASSET_DIR, asset_out, dirs_exist_ok=True)
        written.update(_asset_file_list(ASSET_DIR))
    _copy_project_assets(project, out_dir, written)
    _copy_datasheet_assets(project, out_dir, written)

    _prune_stale_output(out_dir, written)
    return out_dir
