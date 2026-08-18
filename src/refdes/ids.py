"""ID allocation.

IDs are allocated once, written back into the source file, and never reused.
Nothing is ever numbered by position: inserting a requirement at the top of a list
must not shift the IDs below it, because that would silently repoint every link and
orphan every item's history.

An ID is provisional until it appears in a baseline. After that it is frozen.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

import yaml

from .model import Item, Project

ID_RE = re.compile(r"^([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)-(\d+)$")
LIST_ENTRY_RE = re.compile(r"^(\s*)-(\s+)(\S.*)$")
FLOW_ENTRY_RE = re.compile(r"^\{(.*)\}\s*$")


def split_id(item_id: str) -> tuple[str, int] | None:
    match = ID_RE.match(item_id.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


# ------------------------------------------------------------------------- ledger


def ledger_path(project: Project) -> str:
    return os.path.join(project.root, project.id_ledger)


def load_ledger(project: Project) -> dict:
    path = ledger_path(project)
    if not os.path.isfile(path):
        return {"burned": {}, "allocated": []}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("burned", {})
    data.setdefault("allocated", [])
    return data


def save_ledger(project: Project, ledger: dict) -> None:
    path = ledger_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# Refdes ID ledger — allocated IDs are never reused, even after an item\n"
        "# is deleted. Do not hand-edit unless you know why you are doing it.\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(ledger, fh, sort_keys=True, default_flow_style=False)


def high_water(project: Project, ledger: dict) -> dict[str, int]:
    """Highest number seen per prefix, across live items, their `former_ids:`
    (finding 12: a migration renumbering must not let a later item reuse the
    old number just because it fell out of the ledger), and the ledger."""
    marks: dict[str, int] = defaultdict(int)
    for prefix, number in (ledger.get("burned") or {}).items():
        marks[prefix] = max(marks[prefix], int(number))
    for item_id in ledger.get("allocated") or []:
        parsed = split_id(str(item_id))
        if parsed:
            marks[parsed[0]] = max(marks[parsed[0]], parsed[1])
    for item in project.items.values():
        parsed = split_id(item.id)
        if parsed:
            marks[parsed[0]] = max(marks[parsed[0]], parsed[1])
        for old_id in item.former_ids:
            parsed = split_id(old_id)
            if parsed:
                marks[parsed[0]] = max(marks[parsed[0]], parsed[1])
    return marks


def prefix_for(project: Project, item: Item) -> str:
    if item.prefix_hint:
        return item.prefix_hint
    spec = project.types.get(item.type)
    return spec.prefix if spec else item.type[:3].upper()


# --------------------------------------------------------------- former ids


def collect_former_ids(project: Project) -> None:
    """Populate `project.former_ids` (old id -> current item id) and validate.

    A migration renumbers an item and there was previously nowhere to record
    the mapping: external references (schematics, review notes, commit
    messages) citing the old id had no path to the replacement, and nothing
    stopped a future item being minted with that old id (finding 12).

    Two ways an entry can be unsafe, both hard errors:

    - It names a still-live id -- either a different item's (a real
      collision: which one wins?) or its own (self-reference makes no
      sense). Either way `former_ids:` must name only retired ids.
    - Two different items declare the same former id. `[[old_id]]` has to
      resolve to exactly one item, so this can't be allowed to pick one
      arbitrarily and stay silent about the other.

    A former id that collides is never added to `project.former_ids`, so a
    reference to it falls through to the ordinary "unknown item" handling
    rather than resolving ambiguously.
    """
    for item in project.local_items:
        for old_id in item.former_ids:
            live = project.items.get(old_id)
            if live is not None:
                whose = "this item's own current id" if live is item else "still a live item id"
                project.error(
                    f"former_ids: {old_id!r} is {whose} -- former_ids must name "
                    "only retired ids, never one still in use",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            claimed_by = project.former_ids.get(old_id)
            if claimed_by is not None and claimed_by != item.id:
                project.error(
                    f"former_ids: {old_id!r} is declared by both {claimed_by} "
                    f"and {item.id} -- a former id must resolve to exactly one "
                    "item",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            project.former_ids[old_id] = item.id


# -------------------------------------------------------------------- write-back


def _insert_into_markdown(lines: list[str], line_no: int, new_id: str) -> list[str]:
    """Insert `id:` as the first front-matter key (line_no is the first key line)."""
    index = max(0, line_no - 1)
    return lines[:index] + [f"id: {new_id}"] + lines[index:]


def _insert_into_list(lines: list[str], line_no: int, new_id: str) -> list[str] | None:
    """Rewrite `- text: ...` as `- id: X` / `  text: ...`, preserving indentation.

    A flow-style entry (`- {text: ...}`) cannot be split across two lines like a
    block mapping without breaking the braces, so the id is injected inside them
    instead. An entry whose flow mapping does not close on the same line is
    refused rather than guessed at, so it fails loudly instead of corrupting the
    file.
    """
    index = line_no - 1
    if not (0 <= index < len(lines)):
        return None
    match = LIST_ENTRY_RE.match(lines[index])
    if not match:
        return None
    indent, sep, rest = match.groups()
    if rest.startswith("{"):
        flow_match = FLOW_ENTRY_RE.match(rest)
        if not flow_match:
            return None
        inner = flow_match.group(1).strip()
        new_inner = f"id: {new_id}" if not inner else f"id: {new_id}, {inner}"
        return lines[:index] + [f"{indent}-{sep}{{{new_inner}}}"] + lines[index + 1 :]
    replacement = [f"{indent}- id: {new_id}", f"{indent}  {rest}"]
    return lines[:index] + replacement + lines[index + 1 :]


def allocate(project: Project, dry_run: bool = False) -> list[tuple[Item, str]]:
    """Allocate IDs for every pending item and write them into the source files."""
    if not project.pending:
        return []

    ledger = load_ledger(project)
    marks = high_water(project, ledger)

    assignments: list[tuple[Item, str]] = []
    for item in project.pending:
        prefix = prefix_for(project, item)
        marks[prefix] = marks.get(prefix, 0) + 1
        new_id = f"{prefix}-{marks[prefix]:0{project.id_width}d}"
        assignments.append((item, new_id))

    if dry_run:
        return assignments

    # Rewrite bottom-up so earlier line numbers stay valid as we insert.
    by_file: dict[str, list[tuple[Item, str]]] = defaultdict(list)
    for item, new_id in assignments:
        by_file[item.source_file].append((item, new_id))

    for rel, entries in by_file.items():
        path = os.path.join(project.root, rel)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()

        for item, new_id in sorted(entries, key=lambda e: e[0].source_line, reverse=True):
            if rel.endswith(".md"):
                lines = _insert_into_markdown(lines, item.source_line, new_id)
            else:
                updated = _insert_into_list(lines, item.source_line, new_id)
                if updated is None:
                    project.error(
                        f"could not write id {new_id} back into the source",
                        file=rel, line=item.source_line,
                    )
                    continue
                lines = updated

        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(newline.join(lines) + newline)

    ledger.setdefault("allocated", [])
    for _item, new_id in assignments:
        if new_id not in ledger["allocated"]:
            ledger["allocated"].append(new_id)
    burned = ledger.setdefault("burned", {})
    for prefix, number in marks.items():
        burned[prefix] = max(int(burned.get(prefix, 0)), int(number))
    save_ledger(project, ledger)

    for item, new_id in assignments:
        item.id = new_id
        project.items[new_id] = item
    project.pending.clear()

    return assignments
