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


def _value_pattern(old_value: str | None) -> str:
    """Regex fragment matching `old_value` as it may appear in raw source
    text -- optionally wrapped in the quotes YAML parsing already stripped
    (`id: "042"` and `id: 042` both resolve to the same string by the time
    `old_value` reaches here, but only one of them still has quotes on the
    line). Empty (matches only a truly bare key) when `old_value` is None.
    """
    if old_value is None:
        return ""
    return rf"[\"']?{re.escape(old_value)}[\"']?"


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


def orphaned_allocations(project: Project) -> list[str]:
    """`ledger["allocated"]` entries with no live item and no `former_ids:`
    explaining where they went -- informational only (issue #6, finding 10
    part 2's narrower half). Surfaced by `refdes audit`, never `check`/
    `build`: an id going missing from the ledger's perspective is the
    *ordinary*, expected shape of deleting an item, not a defect, so this is
    not a warning or an error anywhere else -- only worth a look.

    This is NOT a fix for the finding's own reuse bug and must never be
    presented as one: it only catches the moment between an item's deletion
    and any later re-typing of the *same* id, and only if `refdes audit`
    happens to run during that window. Finding 10's own repro deletes and
    retypes in one edit, then runs `check` once at the end -- by then the
    entry is no longer orphaned (the new item's id, being the identical
    string, re-explains it), and nothing here or anywhere else can tell that
    a swap happened. Two different histories -- "this item, never touched"
    and "a different item, hand-typed with the exact former id" -- produce
    byte-identical project state once both edits have already landed; see
    docs/design/keys.md's "Why this is the root fix" for why closing that
    fully needs identity that survives an id being retyped, not a sharper
    check against what's on disk now.
    """
    ledger = load_ledger(project)
    allocated = {str(entry) for entry in (ledger.get("allocated") or [])}
    live = set(project.items)
    former: set[str] = set()
    for item in project.local_items:
        former.update(item.former_ids)
    return sorted(allocated - live - former)


def prefix_for(project: Project, item: Item) -> str:
    if item.prefix_hint:
        return item.prefix_hint
    spec = project.types.get(item.type)
    return spec.prefix if spec else item.type[:3].upper()


def validate_prefixes(project: Project) -> None:
    """Finding 8 Parts 1/2: an already-id'd item's own prefix -- the id
    scheme's "type segment" -- must match what `prefix_for()` would derive
    for it. `prefix_for()` was previously read only inside `allocate()`, for
    a *pending* item choosing its id for the first time; this reaches the
    opposite population, an item that already has a hand-typed id, doing
    nothing but a static comparison of two already-known strings -- no
    resolution, no ambient state.

    A mismatch is a loud, blocking error, never a silent rewrite: fixing it
    automatically would change the one string every link, backlink, and
    ledger entry is keyed on -- the same class of harm Part 0's write-back
    bug caused by accident, self-inflicted here instead.

    Checked as "starts with", not "equals": Part 2's free-form category
    segment (`IO-AI`, `EXP-PCIE`) is typed straight into the id with no
    scheme change and no matching `prefix:` of its own, so `id: CON-IO-004`
    against a bare `prefix: CON` is exactly right, not a mismatch --
    `split_id`'s own greedy match would otherwise read `CON-IO` as one
    inseparable prefix and flag every categorized id in the project.
    """
    for item in project.local_items:
        if not item.id:
            continue  # pending -- nothing to compare yet
        if split_id(item.id) is None:
            continue  # not shaped like PREFIX-NNN at all -- a different diagnostic's job
        expected = prefix_for(project, item)
        if item.id.startswith(f"{expected}-"):
            continue
        source = "from defaults:" if item.prefix_hint else f"the {item.type!r} type's default"
        project.error(
            f"id {item.id!r} does not match this item's prefix {expected!r} "
            f"({source})",
            file=item.source_file, line=item.source_line, item_id=item.id,
        )


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


def insert_into_markdown(
    lines: list[str], line_no: int, new_line: str, old_value: str | None = None
) -> list[str]:
    """Insert `new_line` as the first front-matter key (line_no is the first key line).

    Generic over what the key/value text is -- allocate() inserts `id: X`;
    former_ids.confirm() reuses this to insert `former_ids: [X]` the same way.

    If the target line already *is* that same key, replace it in place
    instead of inserting a second occurrence above it. A duplicate key isn't
    cosmetic: YAML resolves a mapping with a repeated key to the *last* one,
    so leaving the original in place means the item still parses as if
    nothing were ever written -- looking unallocated again on the very next
    parse, and burning another id if `refdes id` runs again on it.

    `old_value`, when given, is the exact text currently on that line (e.g.
    a bare-numeric `id:` hint being expanded -- finding 8 Part 1) and is
    matched literally; otherwise only a *bare* key (a scaffolded placeholder
    with no value at all) is replaced, matching the original, narrower fix.
    """
    index = max(0, line_no - 1)
    key = new_line.split(":", 1)[0].strip()
    value_pattern = _value_pattern(old_value)
    if index < len(lines) and re.match(rf"^{re.escape(key)}:\s*{value_pattern}\s*$", lines[index]):
        return lines[:index] + [new_line] + lines[index + 1 :]
    return lines[:index] + [new_line] + lines[index:]


def insert_into_list(
    lines: list[str], line_no: int, key: str, value: str, old_value: str | None = None
) -> list[str] | None:
    """Rewrite `- text: ...` as `- {key}: {value}` / `  text: ...`, preserving indentation.

    Generic over `key`/`value` for the same reason as insert_into_markdown()
    above. A flow-style entry (`- {text: ...}`) cannot be split across two
    lines like a block mapping without breaking the braces, so the new pair is
    injected inside them instead. An entry whose flow mapping does not close
    on the same line is refused rather than guessed at, so it fails loudly
    instead of corrupting the file.

    If the target line already *is* `{key}:` -- bare, or already holding
    `old_value` when given (a bare-numeric `id:` hint being expanded,
    finding 8 Part 1) -- its value is replaced in place rather than
    inserting a second `{key}:` above it, in both block and flow style; see
    insert_into_markdown()'s docstring for why a duplicate key is a
    correctness bug, not a cosmetic one.
    """
    index = line_no - 1
    if not (0 <= index < len(lines)):
        return None
    match = LIST_ENTRY_RE.match(lines[index])
    if not match:
        return None
    indent, sep, rest = match.groups()
    value_pattern = _value_pattern(old_value)
    if rest.startswith("{"):
        flow_match = FLOW_ENTRY_RE.match(rest)
        if not flow_match:
            return None
        inner = flow_match.group(1).strip()
        existing_re = re.compile(rf"(^|,)(\s*){re.escape(key)}:\s*{value_pattern}\s*(?=,|$)")
        if existing_re.search(inner):
            new_inner = existing_re.sub(
                lambda m: f"{m.group(1)}{m.group(2)}{key}: {value}", inner, count=1
            )
        else:
            new_inner = f"{key}: {value}" if not inner else f"{key}: {value}, {inner}"
        return lines[:index] + [f"{indent}-{sep}{{{new_inner}}}"] + lines[index + 1 :]
    if re.match(rf"^{re.escape(key)}:\s*{value_pattern}\s*$", rest):
        return lines[:index] + [f"{indent}- {key}: {value}"] + lines[index + 1 :]
    replacement = [f"{indent}- {key}: {value}", f"{indent}  {rest}"]
    return lines[:index] + replacement + lines[index + 1 :]


def allocate(project: Project, dry_run: bool = False) -> list[tuple[Item, str]]:
    """Allocate IDs for every pending item and write them into the source files.

    Two passes, in this order, both against the same `marks` high-water dict:

    1. Numeric-hint items (finding 8 Part 1: `id: 042`) freeze the *specific*
       number the author typed, verbatim -- `marks[prefix]` is raised to at
       least that number, never incremented past it. A number at or below
       the current high water is a collision (already live, or burned by a
       since-deleted item) and is refused with an error rather than silently
       renumbered -- the same "yell, don't rewrite" posture as everything
       else that touches id identity.
    2. Truly-pending items (no `id:` at all) get the next free number per
       prefix, exactly as before -- run second so a numeric hint's reserved
       number is never handed out from under it, regardless of which order
       the items happen to appear in the file.
    """
    if not project.pending:
        return []

    ledger = load_ledger(project)
    marks = high_water(project, ledger)

    assignments: list[tuple[Item, str]] = []
    for item in project.pending:
        if not item.numeric_id_hint:
            continue
        prefix = prefix_for(project, item)
        number = int(item.numeric_id_hint)
        new_id = f"{prefix}-{item.numeric_id_hint}"
        if number <= marks.get(prefix, 0):
            project.error(
                f"id: {item.numeric_id_hint} would expand to {new_id!r}, but "
                f"that number is already used or was burned by an earlier "
                f"item under prefix {prefix!r} -- pick a number higher than "
                f"{marks.get(prefix, 0)}, or leave id: blank to let 'refdes "
                f"id' assign the next one",
                file=item.source_file, line=item.source_line,
            )
            continue
        marks[prefix] = number
        assignments.append((item, new_id))

    for item in project.pending:
        if item.numeric_id_hint:
            continue
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

    # An id whose write-back was refused is *not* allocated. The refusal
    # happens before anything is written (insert_into_list returns None
    # having touched nothing), so no file, and nothing anywhere else, can be
    # referring to that id -- reporting it as allocated, recording it in the
    # ledger, and burning its number would all be claims about a write that
    # never happened. The error stands on its own; the number stays free for
    # the next run, once the entry is in a shape that can be written to.
    failed: set[int] = set()

    for rel, entries in by_file.items():
        path = os.path.join(project.root, rel)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()

        for item, new_id in sorted(entries, key=lambda e: e[0].source_line, reverse=True):
            old_value = item.numeric_id_hint or None
            if rel.endswith(".md"):
                lines = insert_into_markdown(
                    lines, item.source_line, f"id: {new_id}", old_value=old_value
                )
            else:
                updated = insert_into_list(
                    lines, item.source_line, "id", new_id, old_value=old_value
                )
                if updated is None:
                    project.error(
                        f"could not write id {new_id} back into the source",
                        file=rel, line=item.source_line,
                    )
                    failed.add(id(item))
                    continue
                lines = updated

        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(newline.join(lines) + newline)

    written = [(item, new_id) for item, new_id in assignments if id(item) not in failed]

    ledger.setdefault("allocated", [])
    for _item, new_id in written:
        if new_id not in ledger["allocated"]:
            ledger["allocated"].append(new_id)
    burned = ledger.setdefault("burned", {})
    # High water over what was already burned plus what this run actually
    # wrote -- never over `marks`, which was advanced during assignment and
    # so still counts the refusals above.
    for prefix, number in high_water(project, ledger).items():
        burned[prefix] = max(int(burned.get(prefix, 0)), int(number))
    for _item, new_id in written:
        parsed = split_id(new_id)
        if parsed:
            burned[parsed[0]] = max(int(burned.get(parsed[0], 0)), parsed[1])
    save_ledger(project, ledger)

    for item, new_id in written:
        item.id = new_id
        project.items[new_id] = item
    project.pending = [item for item in project.pending if id(item) in failed]

    return written
