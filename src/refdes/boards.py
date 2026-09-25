"""Board scoping: which board an item belongs to, and drift between builds.

Opt-in. A board is one path segment under `items/`, matched against the
`boards:` registry in refdes-project.yaml -- the first segment under `item_layout:
flat` (today's `items/<board>/`), the second under `item_layout: workspace`
(`items/<workspace>/<board>/`, see workspaces.py). With no registry, every
function here is a no-op and every item's `board` stays "" -- an existing
project with no `boards:` block must build byte-identical to one from before
this module existed, and that includes staying on `item_layout: flat`.

Board membership is expected to be mostly stable, but a file does sometimes move.
`.refdes/boards.yaml` records which board -- and, once `workspaces:` is in use,
which workspace -- each item was on the last time the project was built, modeled
on `seal.py`'s append-only manifest, except a move is always a warning, never a
build error: unlike editing sealed history, moving a board or workspace is an
ordinary thing to do deliberately.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import yaml

from . import keys as keys_mod
from . import textio
from .ids import split_id
from .model import Item, Project
from .parse import yaml_safe_load

MANIFEST_FILE = ".refdes/boards.yaml"


# --------------------------------------------------------------------- resolution


def _path_index(project: Project) -> dict[str, str]:
    """items/ path segment -> board key, including any `path:` aliases."""
    return {spec.path_segment: name for name, spec in project.boards.items()}


def path_segments(item: Item) -> list[str]:
    """Every items/ path segment `item` lives under, filename excluded.

    `["board-a"]` for `items/board-a/r.yaml`, `["ws-a", "board-a"]` for
    `items/ws-a/board-a/r.yaml`, `[]` for a file directly in `items/`. Shared
    with workspaces.py, which reads the first element the same way this module
    reads whichever element `item_layout` says is the board's own.
    """
    rel = item.source_file.replace("\\", "/")
    prefix = "items/"
    if not rel.startswith(prefix):
        return []
    remainder = rel[len(prefix) :]
    parts = remainder.split("/")
    return parts[:-1]  # drop the filename


def _board_segment(project: Project, item: Item) -> str:
    """Which path segment names the board, depending on `item_layout`."""
    parts = path_segments(item)
    if project.item_layout == "workspace":
        return parts[1] if len(parts) >= 2 else ""
    return parts[0] if parts else ""


def _derive(project: Project, item: Item) -> str:
    segment = _board_segment(project, item)
    return _path_index(project).get(segment, "") if segment else ""


def resolve(project: Project) -> None:
    """Assign `item.board` for every local item: item override > file defaults > path.

    The override precedence between an item's own `board:` and its file's
    `defaults:` is already resolved by the time `item.board_hint` is set --
    parse.py merges `defaults:` under each item before the item-level value can
    win, the same way it already does for `prefix:`. This only adds the path
    fallback for items that set neither.
    """
    if not project.boards:
        return
    for item in project.local_items:
        if item.board_hint:
            if item.board_hint not in project.boards:
                project.error(
                    f"board: {item.board_hint!r} is not declared in refdes-project.yaml's "
                    f"boards: registry",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            item.board = item.board_hint
        else:
            item.board = _derive(project, item)
            if not item.board:
                segment = _board_segment(project, item)
                if segment:
                    reason = f"{segment!r} is not in the boards: registry"
                elif project.item_layout == "workspace":
                    reason = (
                        "it has no second items/ path segment to read a board "
                        "from under item_layout: workspace"
                    )
                else:
                    reason = "it sits directly in items/, outside any board folder"
                project.warn(
                    f"no board: {reason} and no board: key was set. Add "
                    f"`board: <name>` to the file's defaults:, or move the file "
                    f"to items/<registered-board>/.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )


def included_map(project: Project, board: str | None) -> dict[str, str]:
    """The display half of finding 33: `{member id: group id}` for the members
    of the groups named in `board`'s `includes:`.

    These items appear on the board's scoped pages -- labelled "shared, via
    GRP-..." -- but are counted by nothing: summary tallies, coverage, the
    release gate, the seals, the drift manifest and `items.json` all keep
    reading `item.board` alone. This map is the ONLY place inclusion is
    resolved; display sites consult it instead of writing their own checks.

    Membership is the group's `contains` backlinks -- the same walk
    `compute_board_coverage` does for `conforms_to:` -- so the group never
    lists its members. Empty for `board is None`, an unknown board, or a
    board with no `includes:`, which is what keeps every project that never
    used the key byte-identical.
    """
    if board is None or not project.boards:
        return {}
    spec = project.boards.get(board)
    if spec is None or not spec.includes:
        return {}
    out: dict[str, str] = {}
    for group_id in spec.includes:
        group = project.item_by_id(group_id)
        if group is None:
            continue  # validate_includes() already errored on this
        for ref in group.backlinks.get("contains", []):
            member = project.item_by_ref(ref)
            if member is not None:
                out.setdefault(member.id, group_id)
    return out


def displays(item: Item, board: str | None, included: Mapping[str, str]) -> bool:
    """The one display predicate: does `item` appear on `board`'s pages?

    Owned (`item.board == board`) or included (a member of one of the board's
    `includes:` groups). Never use this where a number is produced -- tallies,
    coverage and gates keep using `item.board` alone.
    """
    if board is None:
        return True
    return item.board == board or item.id in included


def shared_via(
    item: Item, board: str | None, included: Mapping[str, str]
) -> str:
    """The group id an item is shared onto `board` by, or "" when it is owned."""
    if board is None or item.board == board:
        return ""
    return included.get(item.id, "")


def lint_tokens(project: Project) -> None:
    """Warn when an item's id prefix does not contain its board's declared token.

    Only checked for boards that declare a `token:` -- ID prefixes stay
    independent of boards otherwise, so this is advisory, never automatic.
    """
    if not project.boards:
        return
    for item in project.local_items:
        if not item.board or not item.id:
            continue
        spec = project.boards.get(item.board)
        if not spec or not spec.token:
            continue
        parsed = split_id(item.id)
        prefix = parsed[0] if parsed else item.id
        if spec.token not in prefix.split("-"):
            project.warn(
                f"item is on board {item.board!r} (token {spec.token!r}), but its "
                f"id prefix {prefix!r} does not contain that token",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )


# ------------------------------------------------------------------------- drift


def manifest_path(project: Project) -> str:
    return os.path.join(project.root, MANIFEST_FILE)


MembershipValue = str | dict[str, object]
Memberships = dict[str, MembershipValue]
Manifest = dict[str, Memberships]

_HEADER = (
    "# Refdes membership drift manifest. Records which board -- and, once\n"
    "# workspaces: is in use, which workspace -- each item was on the last\n"
    "# time the project was built, so a file moving either -- usually a move\n"
    "# to the wrong folder -- is a warning instead of a silent surprise.\n"
    "# Legacy projects key entries by display id. Adopted projects key entries\n"
    "# by surrogate key and carry the current display id inside for readability.\n"
)


def _load_memberships(data: object) -> Memberships:
    if not isinstance(data, Mapping):
        return {}
    return {
        str(record_id): dict(value) if isinstance(value, Mapping) else str(value)
        for record_id, value in data.items()
    }


def load_manifest(project: Project) -> Manifest:
    """Load legacy display-id scalars and adopted surrogate-keyed entries.

    One file, two independent sections -- loaded and saved together so neither
    verify() pass can clobber the other's half when only one of `boards:` /
    `workspaces:` is actually in use for this project.
    """
    path = manifest_path(project)
    if not os.path.isfile(path):
        return {"boards": {}, "workspaces": {}}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml_safe_load(fh) or {}
    return {
        "boards": _load_memberships(data.get("boards")),
        "workspaces": _load_memberships(data.get("workspaces")),
    }


def format_manifest(project: Project, manifest: Manifest) -> str:
    """Serialize the manifest identically for adoption and persistence."""
    payload: dict[str, Memberships] = {"boards": manifest.get("boards", {})}
    # Omitted entirely for a project that has never used workspaces:, so a
    # boards-only project's manifest stays exactly the shape it always was.
    if project.workspaces or manifest.get("workspaces"):
        payload["workspaces"] = manifest.get("workspaces", {})
    return _HEADER + yaml.safe_dump(payload, sort_keys=True, default_flow_style=False)


def save_manifest(project: Project, manifest: Manifest) -> None:
    path = manifest_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    textio.write_text(path, format_manifest(project, manifest))


def _membership_parts(
    record_id: str, value: MembershipValue, kind: str
) -> tuple[str | None, str, str]:
    """Return surrogate key, recorded display id, and membership for either shape."""
    if isinstance(value, Mapping):
        entry = dict(value)
        display_id = entry.get("id")
        if isinstance(display_id, str) and display_id:
            return record_id, display_id, str(entry.get(kind, ""))
    return None, record_id, str(value)


def _find_membership(
    memberships: Memberships,
    item: Item,
    kind: str,
    live_keys: set[str],
) -> tuple[str, MembershipValue, str] | None:
    """Find an entry by surrogate, recorded display id, then legacy id.

    A recorded display id on a keyed entry is only a fallback when no live
    local item owns that entry's key. Otherwise it remains the old readable
    label of its actual owner and must not claim a new item reusing that id.
    """
    if item.key:
        keyed = memberships.get(item.key)
        if keyed is not None:
            key, _display_id, recorded = _membership_parts(item.key, keyed, kind)
            if key == item.key:
                return item.key, keyed, recorded
    for record_id, value in memberships.items():
        key, display_id, recorded = _membership_parts(record_id, value, kind)
        if key is not None and key not in live_keys and display_id == item.id:
            return record_id, value, recorded
    legacy = memberships.get(item.id)
    if legacy is None:
        return None
    key, _display_id, recorded = _membership_parts(item.id, legacy, kind)
    if key is not None:
        return None
    return item.id, legacy, recorded


def _store_membership(
    adopted: bool,
    memberships: Memberships,
    item: Item,
    kind: str,
    value: str,
    previous_record_id: str | None = None,
) -> bool:
    if adopted and item.key:
        record_id = item.key
        stored: MembershipValue = {"id": item.id, kind: value}
    else:
        record_id = item.id
        stored = value

    changed = False
    if previous_record_id is not None and previous_record_id != record_id:
        del memberships[previous_record_id]
        changed = True
    if memberships.get(record_id) != stored:
        memberships[record_id] = stored
        changed = True
    return changed


def _membership_is_live(
    record_id: str,
    value: MembershipValue,
    kind: str,
    live_ids: set[str],
    live_keys: set[str],
) -> bool:
    key, display_id, _recorded = _membership_parts(record_id, value, kind)
    return key in live_keys if key is not None else display_id in live_ids


def _deleted_key_evidence(project: Project) -> dict[str, str]:
    """display id -> recorded key, for items whose key was deleted by hand.

    A key-keyed membership entry for such an item is the *only* record of the
    key in a project with no baselines, so the writers below must not prune or
    rewrite it (§6, decision 2026-09-15).
    """
    return {r.item.id: r.key for r in keys_mod.deleted_key_records(project)}


def _prune_stale(
    project: Project,
    memberships: Memberships,
    kind: str,
    evidence: dict[str, str] | None = None,
) -> bool:
    """Drop memberships whose immutable or legacy identity is no longer local."""
    evidence = evidence or {}
    live_ids = {item.id for item in project.local_items}
    live_ids |= set(project.former_ids)
    live_keys = {item.key for item in project.local_items if item.key}
    stale = [
        record_id
        for record_id, value in memberships.items()
        if not _membership_is_live(
            record_id, value, kind, live_ids, live_keys
        )
        and evidence.get(_membership_parts(record_id, value, kind)[1])
        != record_id
    ]
    for record_id in stale:
        del memberships[record_id]
    return bool(stale)


@dataclass
class ManifestStoragePlan:
    """Write-free conversion of both membership sections for key adoption."""

    manifest: Manifest = field(
        default_factory=lambda: {"boards": {}, "workspaces": {}}
    )
    carried: int = 0
    total: int = 0
    unidentified: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


def plan_surrogate_storage(project: Project, manifest: Manifest) -> ManifestStoragePlan:
    """Convert live, identifiable memberships and drop stale drift state."""
    plan = ManifestStoragePlan()
    by_display_id = {item.id: item for item in project.local_items}
    by_former_id = {
        old_id: by_display_id[current_id]
        for old_id, current_id in project.former_ids.items()
        if current_id in by_display_id
    }
    live_ids = set(by_display_id) | set(by_former_id)
    live_keys = {item.key for item in project.local_items if item.key}

    for section, kind in (("boards", "board"), ("workspaces", "workspace")):
        original = manifest.get(section, {})
        plan.total += len(original)
        converted: Memberships = {}

        # Preserve live, already-adopted entries first. Exact current display
        # ids then take priority over former ids when an old additive manifest
        # contains both identities.
        for record_id, value in original.items():
            key, _display_id, _membership = _membership_parts(record_id, value, kind)
            if key is None:
                continue
            if not _membership_is_live(
                record_id, value, kind, live_ids, live_keys
            ):
                plan.stale.append(f"{section}: {record_id}")
                continue
            converted[record_id] = dict(value)
            plan.carried += 1

        legacy_ids = [
            record_id
            for record_id, value in original.items()
            if _membership_parts(record_id, value, kind)[0] is None
        ]
        ordered_ids = [record_id for record_id in legacy_ids if record_id in by_display_id]
        ordered_ids += [
            record_id
            for record_id in legacy_ids
            if record_id not in by_display_id and record_id in by_former_id
        ]
        ordered_ids += [
            record_id
            for record_id in legacy_ids
            if record_id not in by_display_id and record_id not in by_former_id
        ]
        for record_id in ordered_ids:
            value = original[record_id]
            _key, _display_id, membership = _membership_parts(record_id, value, kind)
            item = by_display_id.get(record_id) or by_former_id.get(record_id)
            if item is None:
                plan.stale.append(f"{section}: {record_id}")
                continue
            if item.key:
                keyed: MembershipValue = {"id": item.id, kind: membership}
                existing = converted.get(item.key)
                if existing is None:
                    converted[item.key] = keyed
                    plan.carried += 1
                    continue
                _existing_key, _existing_id, existing_membership = _membership_parts(
                    item.key, existing, kind
                )
                if existing_membership == membership:
                    plan.carried += 1
                    continue
            converted[record_id] = value
            plan.unidentified.append(f"{section}: {record_id}")

        plan.manifest[section] = dict(sorted(converted.items()))

    plan.stale.sort()
    plan.unidentified.sort()
    return plan


def _verify_membership(
    project: Project,
    manifest: Memberships,
    moves: list[tuple[str, str, str]],
    current: Callable[[Item], str],
    kind: str,
    write: bool,
    accept_move: bool,
    adopted: bool,
    evidence: dict[str, str],
) -> bool:
    """One kind's worth of drift checking (`"board"` or `"workspace"`).

    Both legacy display-id scalars and surrogate-keyed entries follow the same
    rule: compare resolved membership with the last recorded value, warn
    (never error) on a change, and record it in ``moves``. The shared
    ``--accept-board-move`` flag accepts either kind because both live in this
    manifest and share the same deliberate-move posture.
    """
    changed = False
    live_keys = {item.key for item in project.local_items if item.key}
    for item in sorted(project.local_items, key=lambda i: i.id):
        value = current(item)
        found = _find_membership(manifest, item, kind, live_keys)
        if not value and found is None:
            continue  # never assigned -- resolve()'s own diagnostic covers this

        if found is None:
            if write:
                changed = _store_membership(
                    adopted, manifest, item, kind, value
                ) or changed
            continue

        record_id, _stored, recorded = found
        if evidence.get(item.id) == record_id:
            # This entry records the key the item just lost: rewriting it in
            # the item's (keyless) shape would delete the last record of it.
            continue
        if recorded == value:
            if write:
                changed = _store_membership(
                    adopted, manifest, item, kind, value, record_id
                ) or changed
            continue

        moves.append((item.id, recorded, value))
        if value:
            accepted = f"was on {kind} {recorded!r}, now on {value!r}"
            warning = (
                f"{item.id} moved from {kind} {recorded!r} to {value!r} since "
                f"the last build. Run 'refdes build --accept-board-move' if "
                f"this is deliberate, or move the file back."
            )
        else:
            accepted = f"was on {kind} {recorded!r}, now resolves to no {kind}"
            warning = (
                f"{item.id} was on {kind} {recorded!r} and now resolves to no "
                f"{kind}. Run 'refdes build --accept-board-move' if this is "
                f"deliberate, or restore the {kind}."
            )
        if accept_move:
            project.warn(
                f"{kind} move accepted: {item.id} {accepted}",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            changed = _store_membership(
                adopted, manifest, item, kind, value, record_id
            ) or changed
        else:
            project.warn(
                warning,
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
    return changed


def verify(project: Project, write: bool = False, accept_move: bool = False) -> None:
    """Compare each item's resolved board and workspace against the manifest."""
    if not project.boards and not project.workspaces:
        return

    manifest = load_manifest(project)
    adopted = keys_mod.is_adopted(project) if write else False
    evidence = _deleted_key_evidence(project) if write else {}
    changed = False
    if write:
        changed = _prune_stale(
            project, manifest["boards"], "board", evidence
        ) or changed
        changed = (
            _prune_stale(
                project, manifest["workspaces"], "workspace", evidence
            )
            or changed
        )

    if project.boards:
        changed = _verify_membership(
            project, manifest["boards"], project.board_moves,
            lambda item: item.board, "board", write, accept_move, adopted,
            evidence,
        ) or changed

    if project.workspaces:
        changed = _verify_membership(
            project, manifest["workspaces"], project.workspace_moves,
            lambda item: item.workspace, "workspace", write, accept_move,
            adopted, evidence,
        ) or changed

    if write and changed:
        save_manifest(project, manifest)
