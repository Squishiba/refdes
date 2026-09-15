"""Import items from another Refdes project.

We import the built `items.json` artifact rather than the source tree, on purpose.
A shared interface spec is a dependency with a version: you qualify a board against
rev C, and you upgrade to rev D deliberately. Reading a live source folder gives you
a spec that shifts under you between builds, which is how boards end up qualified
against something that no longer exists.

Imported items are read-only. You may link to them and render reference pages for
them; you may not edit, renumber, or revalidate them.
"""

from __future__ import annotations

import json
import os

from . import keys as keys_mod
from .model import Item, Project, provisional_handle


def load_imports(project: Project) -> None:
    """Absorb each pinned artifact once into this parsed project."""
    if project.imports_loaded:
        return
    project.imports_loaded = True

    for spec in project.imports:
        path = spec.items_path
        if not os.path.isabs(path):
            path = os.path.normpath(os.path.join(project.root, path))

        if not os.path.isfile(path):
            project.error(
                f"import {spec.name!r}: no artifact at {path}. Build the upstream "
                f"project first, or fix the path.",
                file="refdes-project.yaml",
            )
            continue

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            project.error(f"import {spec.name!r}: could not read {path}: {exc}")
            continue

        upstream_version = str(data.get("version") or "")
        if spec.version and upstream_version != spec.version:
            project.error(
                f"import {spec.name!r} is pinned to version {spec.version!r} but the "
                f"artifact declares {upstream_version or '<none>'!r}. Rebuild the "
                f"upstream project or update the pin deliberately.",
                file="refdes-project.yaml",
            )
            continue

        _absorb(project, spec.name, upstream_version, data)


def _absorb(project: Project, origin: str, version: str, data: dict) -> None:
    for raw in data.get("items", []):
        item_id = str(raw.get("id") or "")
        raw_key = raw.get("key")
        key = str(raw_key) if raw_key is not None else ""
        if key:
            malformed = keys_mod.malformed_key_message(key)
            if malformed is not None:
                project.error(
                    f"import {origin!r}: {malformed}",
                    file="refdes-project.yaml",
                )
                key = ""

        if not item_id:
            continue

        existing = project.item_by_id(item_id)
        if existing is not None:
            where = (
                f"import {existing.origin!r}"
                if existing.external
                else f"{existing.source_file}:{existing.source_line}"
            )
            project.error(
                f"import {origin!r} defines {item_id!r}, which already exists "
                f"({where}). IDs must be unique across every imported project — "
                f"give each project its own prefix.",
                file="refdes-project.yaml",
            )
            continue

        item = Item(
            id=item_id,
            type=str(raw.get("type") or ""),
            key=key,
            fields=dict(raw.get("fields") or {}),
            links=dict(raw.get("links") or {}),
            source_file=f"<import:{origin}>",
            source_line=1,
            external=True,
            origin=origin,
            # Keep the upstream hash verbatim; recomputing it locally would be
            # meaningless, and it is what a suspect-link check compares against.
            content_hash=str(raw.get("content_hash") or ""),
        )
        if version:
            item.fields.setdefault("_version", version)

        if item.type not in project.types:
            project.warn(
                f"import {origin!r}: {item_id} has type {item.type!r}, which this "
                f"project's schema does not declare. It will render, but its fields "
                f"are not validated.",
                file="refdes-project.yaml",
            )

        # Older artifacts have no `key` field. Keep their temporary handle,
        # but store a keyed import under its durable identity so every local
        # graph and link resolver sees the same cross-project key scope.
        handle = project.add_item(item, item.key or provisional_handle(item))
        project.items_by_id[item_id] = handle
