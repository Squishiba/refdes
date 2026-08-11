"""Render the resolved project to a static HTML site plus items.json."""

from __future__ import annotations

import json
import os
import re
import shutil

from jinja2 import Environment, FileSystemLoader, select_autoescape

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


def _document_sections(
    project: Project, board: str | None = None
) -> list[tuple[str, list[Item]]]:
    """Items grouped for linear reading: schema order, log entries by date.

    `board`, when given, scopes this to one board's own local items -- imported
    items carry no board, so a per-board document has no "Imported references"
    section.
    """
    sections: list[tuple[str, list[Item]]] = []
    for type_name, spec in project.types.items():
        items = [
            i
            for i in project.items.values()
            if i.type == type_name and not i.external and (board is None or i.board == board)
        ]
        if type_name == "log":
            items.sort(key=lambda i: (str(i.fields.get("date", "")), i.id))
        else:
            items.sort(key=lambda i: i.id)
        sections.append((spec.plural, items))

    if board is None:
        imported = sorted(
            (i for i in project.items.values() if i.external), key=lambda i: i.id
        )
        if imported:
            sections.append(("Imported references", imported))
    return sections


def _coverage_rows(project: Project, board: str | None = None) -> list[tuple[Item, object]]:
    stage_order = {"open": 0, "addressed": 1, "claimed": 2, "satisfied": 3, "verified": 4}
    rows = [
        (project.items[item_id], cov)
        for item_id, cov in project.coverage.items()
        if item_id in project.items
        and (board is None or project.items[item_id].board == board)
    ]
    rows.sort(key=lambda row: (stage_order.get(row[1].stage, 9), row[0].id))
    return rows


def _log_entries(project: Project, board: str | None = None) -> list[Item]:
    return sorted(
        (
            i
            for i in project.local_items
            if i.type == "log" and (board is None or i.board == board)
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


def summary_payload(project: Project, board: str | None = None) -> dict:
    """Everything the at-a-glance view needs, computed once.

    The per-type pages answer "what does this item say". This answers the questions
    you actually ask at a design review: what is closest to breaking, what numbers
    does the design depend on, and what is not traced to anything.

    `board`, when given, scopes every table on the page to that board's own items.
    """
    local = [
        i
        for i in project.items.values()
        if not i.external and (board is None or i.board == board)
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
        entry.update({
            "fields": item.fields,
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
    env.globals["has_log"] = any(i.type == "log" for i in project.local_items)

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
    # board adds its own scoped set of the same four reports.
    reserved = {
        "coverage",
        "log",
        "document",
        "summary",
        dashboard_name[: -len(".html")],
    }
    for board_key in project.boards:
        reserved.update(
            f"{name}-{board_key}" for name in ("coverage", "log", "document", "summary")
        )
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

    page_tpl = env.get_template("page.html.j2")
    for page in project.pages:
        written.add(f"{page.slug}.html")
        with open(
            os.path.join(out_dir, f"{page.slug}.html"), "w", encoding="utf-8"
        ) as fh:
            fh.write(
                page_tpl.render(
                    project=project, page=page, previews_json=previews_json
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
                )
            )

    known_slugs = {item.slug for item in project.items.values()}
    document_tpl = env.get_template("document.html.j2")
    written.add("document.html")
    with open(os.path.join(out_dir, "document.html"), "w", encoding="utf-8") as fh:
        fh.write(
            document_tpl.render(
                project=project,
                sections=_document_sections(project),
                anchored=lambda html: _anchorize(html, known_slugs),
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

    with open(os.path.join(out_dir, "items.json"), "w", encoding="utf-8") as fh:
        json.dump(items_json(project), fh, indent=2, ensure_ascii=False, default=str)

    asset_out = os.path.join(out_dir, "assets")
    if os.path.isdir(ASSET_DIR):
        shutil.copytree(ASSET_DIR, asset_out, dirs_exist_ok=True)
        written.update(_asset_file_list(ASSET_DIR))

    _prune_stale_output(out_dir, written)
    return out_dir
