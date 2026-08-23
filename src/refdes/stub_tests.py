"""`refdes stub-tests`: a starter test item per coverable item with no
verifying test yet -- turning a wall of coverage warnings into a checklist.

Refdes does not own test items after this. One test routinely verifies
several requirements (a thermal soak covers five thermal requirements) and
one requirement often needs several tests at different corners, so a
generated one-per-requirement structure is only ever a starting point, not
a shape the tool goes on maintaining -- restructure freely afterward.

Deduplication is by declared links, not text: a candidate is skipped the
moment something already declares it verified, so deleting a generated
stub (or the whole file) makes its requirement eligible again automatically,
and re-running never doubles up.
"""

from __future__ import annotations

import os

from .model import Item, Project, SchemaError


def _verifier_types(project: Project) -> list[str]:
    """Types whose own `links:` declare `verifies` -- the modern convention
    (`test.links.verifies: [requirement, constraint]`) this command
    generates against. The legacy verified_by-declared-on-the-target
    spelling would mean editing the requirement file instead of writing a
    new test, and isn't what this command does.
    """
    return sorted(tname for tname, spec in project.types.items() if "verifies" in spec.links)


def _already_covered(project: Project, verifier_types: set[str]) -> set[str]:
    """Every item id that already has a verifying test, by either spelling
    of the link, from *either* `project.items` or `project.pending`.

    Pending matters: a just-generated stub has no id yet (the ordinary
    two-phase author-then-allocate flow, same as anything `refdes new`
    scaffolds), so `resolve_links()` never sees its `verifies:` edge and
    the target's `backlinks` stay empty until `refdes id` runs. Reading
    `verifies:`/`verified_by:` directly off every pending item -- rather
    than through resolve_links()'s output -- is what keeps two `stub-tests`
    runs in a row, with no `refdes id` in between, from generating a
    duplicate for the same requirement.

    Two loops, not one over `list(project.items.values()) + project.pending`,
    because they need to read a *different* field. An already-idd item's
    `verifies:`/`verified_by:` may be `DISPLAY@key` composite text by now
    (docs/design/keys.md §3, links.expand_missing) -- resolved_links (this
    item's own resolve_links() output, already resolved to plain display
    ids) is what's comparable against the plain ids `covered` is checked
    against elsewhere in this module. A pending item, having no id, was
    never reached by resolve_links() (it only walks project.items) or by
    links.expand_missing() (which only walks project.local_items, for the
    same reason) -- its `verifies:`/`verified_by:` is guaranteed to still be
    bare text, so `links` is read directly; there is nothing to resolve a
    composite out of yet.
    """
    covered: set[str] = set()
    for item in project.items.values():
        if item.type in verifier_types:
            covered.update(item.resolved_links.get("verifies", []))
        if item.resolved_links.get("verified_by"):
            covered.add(item.id)
    for item in project.pending:
        if item.type in verifier_types:
            covered.update(item.links.get("verifies", []))
        if item.links.get("verified_by"):
            covered.add(item.id)
    return covered


def _item_block(lines: list[str]) -> str:
    return "---\n" + "\n".join(lines) + "\n"


def generate(
    project: Project, verifier_type: str | None = None, dry_run: bool = False
) -> list[tuple[str, list[str]]]:
    """Write one multi-item markdown file per (workspace, board) pair,
    each holding one stub `verifier_type` item per still-uncovered local
    item in that scope -- `verifies:` already pointing at it, its schema's
    own default `status:` (`planned` in the bundled standard, which is
    deliberately not one of `verifying_statuses:`, so a stub never
    retroactively marks its target verified), and an empty `method:` if the
    type declares one.

    Returns `[(path, [item_id, ...]), ...]`, one entry per file actually
    written (or that would be, under `dry_run`) -- empty if every coverable
    item already has a verifying test.

    Appends to an existing file at the target path rather than overwriting
    it: a prior run's stubs are the author's the moment they're written, so
    a later run must never touch them, only add newly-eligible ones after
    them in the same file.
    """
    verifier_types = _verifier_types(project)
    if not verifier_types:
        raise SchemaError(
            "no type declares a 'verifies' link -- nothing to generate stubs as"
        )
    if verifier_type is None:
        if len(verifier_types) > 1:
            raise SchemaError(
                f"multiple types declare 'verifies' ({', '.join(verifier_types)}) "
                "-- pass --type to choose one"
            )
        verifier_type = verifier_types[0]
    elif verifier_type not in verifier_types:
        raise SchemaError(
            f"{verifier_type!r} does not declare a 'verifies' link "
            f"(types that do: {', '.join(verifier_types)})"
        )

    spec = project.types[verifier_type]
    status_field = spec.fields.get("status")
    status_value = status_field.default if status_field is not None else None
    has_method = "method" in spec.fields

    covered = _already_covered(project, set(verifier_types))

    groups: dict[tuple[str, str], list[Item]] = {}
    for item_id in sorted(project.coverage):
        if item_id in covered:
            continue
        item = project.items.get(item_id)
        if item is None or item.external:
            continue
        groups.setdefault((item.workspace, item.board), []).append(item)

    written: list[tuple[str, list[str]]] = []
    for (workspace, board), items in sorted(groups.items()):
        parts = ["items"]
        if workspace:
            wspec = project.workspaces.get(workspace)
            parts.append(wspec.path_segment if wspec else workspace)
        if board:
            bspec = project.boards.get(board)
            parts.append(bspec.path_segment if bspec else board)
        target = os.path.join(project.root, *parts, "stub-tests.md")

        blocks = []
        for item in items:
            lines = [f"type: {verifier_type}", f"title: Verify {item.id}"]
            if status_value is not None:
                lines.append(f"status: {status_value}")
            if has_method:
                lines.append('method: ""')
            lines.append(f"verifies: [{item.id}]")
            blocks.append(_item_block(lines))
        text = "".join(blocks) + "---\n"

        if not dry_run:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            prefix = ""
            if os.path.isfile(target) and os.path.getsize(target) > 0:
                with open(target, "rb") as fh:
                    fh.seek(-1, os.SEEK_END)
                    if fh.read(1) != b"\n":
                        prefix = "\n"
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(prefix + text)

        rel = os.path.relpath(target, project.root).replace("\\", "/")
        written.append((rel, [i.id for i in items]))

    return written
