"""Append-only enforcement for design log entries.

An engineering notebook is only worth anything if yesterday's page still says what
it said yesterday. Entries are sealed the first time they are built; after that,
changing one is a build error. Corrections are made by appending a new entry that
`amends` the old one — the same convention as a paper notebook, where you strike
through and initial rather than erase.

Nothing here can *prevent* an edit; it detects one. That is the honest limit of a
file-based tool, and detection is what actually matters.
"""

from __future__ import annotations

import os

import yaml

from .model import Project

SEAL_FILE = ".refdes/log-seal.yaml"


def seal_path(project: Project) -> str:
    return os.path.join(project.root, SEAL_FILE)


def load_seals(project: Project) -> dict[str, str]:
    path = seal_path(project)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return dict(data.get("sealed") or {})


def save_seals(project: Project, seals: dict[str, str]) -> None:
    path = seal_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# Refdes append-only seals. Each entry records the content hash of a log\n"
        "# entry at the time it was first built. Editing a sealed entry fails the\n"
        "# build; append a new entry that `amends` it instead.\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump({"sealed": seals}, fh, sort_keys=True, default_flow_style=False)


def append_only_items(project: Project) -> list:
    return [
        item
        for item in project.local_items
        if project.types.get(item.type) and project.types[item.type].append_only
    ]


def verify(project: Project, write: bool = False, reseal: bool = False) -> None:
    """Check sealed entries, and seal any new ones when `write` is set."""
    entries = append_only_items(project)
    if not entries:
        return

    seals = load_seals(project)
    changed = False

    for item in sorted(entries, key=lambda i: i.id):
        recorded = seals.get(item.id)
        if recorded is None:
            if write:
                seals[item.id] = item.content_hash
                changed = True
            continue
        if recorded == item.content_hash:
            continue

        if reseal:
            project.warn(
                f"resealed after an edit to a sealed entry (was {recorded}, "
                f"now {item.content_hash}). This is recorded in the audit output.",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            seals[item.id] = item.content_hash
            changed = True
        else:
            project.seal_violations.append(item.id)
            project.error(
                f"{item.id} is append-only and has been modified since it was "
                f"sealed. Append a new entry with `amends: [{item.id}]` instead, "
                f"or run with --reseal if the edit is deliberate.",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )

    if write and changed:
        save_seals(project, seals)


def resealed_ids(project: Project) -> list[str]:
    """Entries whose seal no longer matches their first-built hash."""
    seals = load_seals(project)
    return [
        item.id
        for item in append_only_items(project)
        if item.id in seals and seals[item.id] != item.content_hash
    ]
