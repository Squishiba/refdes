"""Load refdes.yaml into a Project."""

from __future__ import annotations

import os
from typing import Any

import yaml

from .model import (
    ON_CHANGE_MODES,
    BoardSpec,
    FieldSpec,
    ImportSpec,
    ItemType,
    LinkType,
    Project,
)

CONFIG_NAME = "refdes.yaml"


class SchemaError(Exception):
    pass


def find_config(start: str = ".") -> str:
    """Walk up from `start` looking for refdes.yaml."""
    here = os.path.abspath(start)
    while True:
        candidate = os.path.join(here, CONFIG_NAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            raise SchemaError(
                f"no {CONFIG_NAME} found in {os.path.abspath(start)} or any parent directory"
            )
        here = parent


def load_project(config_path: str | None = None, start: str = ".") -> Project:
    path = config_path or find_config(start)
    with open(path, "r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    root = os.path.dirname(os.path.abspath(path))

    site = raw.get("site") or {}
    id_cfg = raw.get("id") or {}
    history = raw.get("history") or {}
    units = raw.get("units") or {}

    default_on_change = history.get("default", "invalidate")
    if default_on_change not in ON_CHANGE_MODES:
        raise SchemaError(
            f"history.default must be one of {list(ON_CHANGE_MODES)}, got {default_on_change!r}"
        )

    link_types: dict[str, LinkType] = {}
    inverse_of: dict[str, str] = {}
    for name, spec in (raw.get("link_types") or {}).items():
        spec = spec or {}
        inverse = spec.get("inverse", f"{name}_by")
        link_types[name] = LinkType(name=name, inverse=inverse, label=spec.get("label", name))
        inverse_of[name] = inverse

    # A link may be declared from either end -- a requirement's `verified_by` and a
    # test's `verifies` are the same edge -- so the map has to resolve both ways.
    for name, inverse in list(inverse_of.items()):
        inverse_of.setdefault(inverse, name)

    types: dict[str, ItemType] = {}
    for tname, tspec in (raw.get("types") or {}).items():
        tspec = tspec or {}
        fields: dict[str, FieldSpec] = {}
        for fname, fspec in (tspec.get("fields") or {}).items():
            fspec = fspec or {}
            on_change = fspec.get("on_change", default_on_change)
            if on_change not in ON_CHANGE_MODES:
                raise SchemaError(
                    f"types.{tname}.fields.{fname}.on_change must be one of "
                    f"{list(ON_CHANGE_MODES)}, got {on_change!r}"
                )
            fields[fname] = FieldSpec(
                name=fname,
                type=fspec.get("type", "text"),
                on_change=on_change,
                required=bool(fspec.get("required", False)),
                choices=fspec.get("choices"),
                default=fspec.get("default"),
            )

        links: dict[str, list[str]] = {}
        for lname, targets in (tspec.get("links") or {}).items():
            if lname not in link_types and lname not in inverse_of.values():
                raise SchemaError(
                    f"types.{tname}.links.{lname} is not a declared link_type"
                )
            links[lname] = list(targets or [])

        body_cfg = tspec.get("body") or {}
        body_on_change = body_cfg.get("on_change", default_on_change)
        if body_on_change not in ON_CHANGE_MODES:
            raise SchemaError(
                f"types.{tname}.body.on_change must be one of {list(ON_CHANGE_MODES)}"
            )

        satisfying_statuses = tspec.get("satisfying_statuses")
        if satisfying_statuses is not None:
            if "status" not in fields:
                raise SchemaError(
                    f"types.{tname}.satisfying_statuses requires a 'status' field "
                    f"on {tname}"
                )
            satisfying_statuses = [str(s) for s in satisfying_statuses]

        types[tname] = ItemType(
            name=tname,
            prefix=tspec.get("prefix", tname[:3].upper()),
            label=tspec.get("label", tname.title()),
            plural=tspec.get("plural", "") or f"{tspec.get('label', tname.title())}s",
            fields=fields,
            links=links,
            preview=list(tspec.get("preview") or []),
            body_on_change=body_on_change,
            append_only=bool(tspec.get("append_only", False)),
            satisfying_statuses=satisfying_statuses,
        )

    if not types:
        raise SchemaError(f"{path} declares no item types")

    import_specs: list[ImportSpec] = []
    for entry in raw.get("imports") or []:
        entry = entry or {}
        if not entry.get("name") or not entry.get("items"):
            raise SchemaError("each imports: entry needs 'name' and 'items'")
        import_specs.append(
            ImportSpec(
                name=str(entry["name"]),
                items_path=str(entry["items"]),
                version=str(entry["version"]) if entry.get("version") else None,
            )
        )

    boards: dict[str, BoardSpec] = {}
    path_owner: dict[str, str] = {}
    for bname, bspec in (raw.get("boards") or {}).items():
        bspec = bspec or {}
        spec = BoardSpec(
            name=bname,
            label=bspec.get("label", bname),
            token=str(bspec.get("token") or ""),
            path=str(bspec.get("path") or ""),
        )
        segment = spec.path_segment
        if segment in path_owner:
            raise SchemaError(
                f"boards.{bname} and boards.{path_owner[segment]} both map to "
                f"items/{segment}/ — path segments must be unique"
            )
        path_owner[segment] = bname
        boards[bname] = spec

    return Project(
        title=site.get("title", "Design Reference"),
        out_dir=site.get("out", "_site"),
        version=str(site.get("version") or ""),
        pages_dir=str(site.get("pages") or "pages"),
        nav_order=[str(s) for s in (site.get("nav") or [])],
        asset_dirs=[str(s) for s in (site.get("assets") or [])],
        imports=import_specs,
        types=types,
        link_types=link_types,
        inverse_of=inverse_of,
        default_on_change=default_on_change,
        id_width=int(id_cfg.get("width", 3)),
        id_ledger=id_cfg.get("ledger", ".refdes/ids.yaml"),
        preferred_units=list(units.get("preferred") or []),
        unit_aliases=dict(units.get("aliases") or {}),
        root=root,
        boards=boards,
    )
