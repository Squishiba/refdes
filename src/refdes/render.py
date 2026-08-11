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


def _document_sections(project: Project) -> list[tuple[str, list[Item]]]:
    """Items grouped for linear reading: schema order, log entries by date."""
    sections: list[tuple[str, list[Item]]] = []
    for type_name, spec in project.types.items():
        items = [
            i for i in project.items.values() if i.type == type_name and not i.external
        ]
        if type_name == "log":
            items.sort(key=lambda i: (str(i.fields.get("date", "")), i.id))
        else:
            items.sort(key=lambda i: i.id)
        sections.append((spec.plural, items))

    imported = sorted(
        (i for i in project.items.values() if i.external), key=lambda i: i.id
    )
    if imported:
        sections.append(("Imported references", imported))
    return sections


def _check_state(item: Item) -> str:
    if not item.checks:
        return "none"
    if any(c.ok is False for c in item.checks):
        return "fail"
    if any(c.ok is None for c in item.checks):
        return "unknown"
    return "pass"


def summary_payload(project: Project) -> dict:
    """Everything the at-a-glance view needs, computed once.

    The per-type pages answer "what does this item say". This answers the questions
    you actually ask at a design review: what is closest to breaking, what numbers
    does the design depend on, and what is not traced to anything.
    """
    local = [i for i in project.items.values() if not i.external]

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

    stage_counts = {"open": 0, "addressed": 0, "satisfied": 0, "verified": 0}
    for cov in project.coverage.values():
        stage_counts[cov.stage] = stage_counts.get(cov.stage, 0) + 1
    total_covered = sum(stage_counts.values())

    evaluated = [c for _i, c in margin_rows]
    with_margin = [c.margin for c in evaluated if c.margin is not None]

    return {
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
    """The machine-readable export. Anything downstream should read this, not HTML."""
    return {
        "title": project.title,
        "version": project.version,
        "coverage": {
            item_id: {
                "stage": cov.stage,
                "addressed_by": cov.addressed_by,
                "satisfied_by": cov.satisfied_by,
                "verified_by": cov.verified_by,
            }
            for item_id, cov in sorted(project.coverage.items())
        },
        "types": {
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
        },
        "items": [
            {
                "id": item.id,
                "type": item.type,
                "title": item.title,
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
            }
            for item in sorted(project.items.values(), key=lambda i: i.id)
        ],
        "diagnostics": [
            {
                "level": d.level,
                "message": d.message,
                "file": d.file,
                "line": d.line,
                "item": d.item_id,
            }
            for d in project.diagnostics
        ],
    }


def render_site(project: Project) -> str:
    out_dir = os.path.join(project.root, project.out_dir)
    os.makedirs(out_dir, exist_ok=True)

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
    stage_order = {"open": 0, "addressed": 1, "satisfied": 2, "verified": 3}
    coverage_rows = sorted(
        (
            (project.items[item_id], cov)
            for item_id, cov in project.coverage.items()
            if item_id in project.items
        ),
        key=lambda row: (stage_order.get(row[1].stage, 9), row[0].id),
    )
    outstanding = [row for row in coverage_rows if row[1].stage != "verified"]

    log_entries = sorted(
        (i for i in project.local_items if i.type == "log"),
        key=lambda i: (str(i.fields.get("date", "")), i.id),
    )

    # Generated reports own these filenames. A page of the same name would be
    # silently clobbered by whichever is written last, so say so instead.
    reserved = {
        "coverage",
        "log",
        "document",
        "summary",
        dashboard_name[: -len(".html")],
    }
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
        return out_dir

    summary_tpl = env.get_template("summary.html.j2")
    with open(os.path.join(out_dir, "summary.html"), "w", encoding="utf-8") as fh:
        fh.write(
            summary_tpl.render(
                project=project,
                previews_json=previews_json,
                **summary_payload(project),
            )
        )

    coverage_tpl = env.get_template("coverage.html.j2")
    with open(os.path.join(out_dir, "coverage.html"), "w", encoding="utf-8") as fh:
        fh.write(
            coverage_tpl.render(
                project=project,
                coverage_rows=coverage_rows,
                previews_json=previews_json,
            )
        )

    log_tpl = env.get_template("log.html.j2")
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
    with open(os.path.join(out_dir, "document.html"), "w", encoding="utf-8") as fh:
        fh.write(
            document_tpl.render(
                project=project,
                sections=_document_sections(project),
                anchored=lambda html: _anchorize(html, known_slugs),
                previews_json=previews_json,
            )
        )

    with open(os.path.join(out_dir, "items.json"), "w", encoding="utf-8") as fh:
        json.dump(items_json(project), fh, indent=2, ensure_ascii=False, default=str)

    asset_out = os.path.join(out_dir, "assets")
    if os.path.isdir(ASSET_DIR):
        shutil.copytree(ASSET_DIR, asset_out, dirs_exist_ok=True)

    return out_dir
