"""Explicit restoration of an item's original surrogate identity.

Unlike adoption, this transaction only edits supplied items' key fields. A
display label cannot prove continuity: the caller supplies the original key
after checking history. Full validation must succeed with that identity.

Where a stamped baseline remembers the key, it also says what the key
belonged to, and that record outranks the label: restoring a key onto an item
the record does not describe is refused (`_baseline_content_conflict`) rather
than accepted, because the move silently re-points every reference that names
the key while leaving a clean build. `--force` is the override.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import adopt, boards, history, keys, lifecycle, loader, patcher, revise, schema, seal, textio
from . import build as build_mod
from .model import Item, Project, SchemaError


@dataclass
class RestorationResult:
    ok: bool
    changes: list[tuple[str, str, str]] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _recorded_current_key(project: Project, item: Item) -> str | None:
    """Do not orphan history written under a replacement key, even old history."""
    if not item.key:
        return None
    for baseline in lifecycle.list_baselines(project):
        for record_id, entry in baseline.items.items():
            identity = keys.baseline_identity(record_id, entry)
            if identity is not None and identity[0] == item.key:
                return f"baseline {baseline.name!r}"
    for rel, board, _path in adopt._seal_files(project):
        if item.key in seal.load_seals(project, board):
            return rel
    manifest = boards.load_manifest(project)
    for section in ("boards", "workspaces"):
        if item.key in manifest.get(section, {}):
            return boards.MANIFEST_FILE
    for event in history.load_events(project.root):
        if item.key in (event.get("item_key"), event.get("successor_key")):
            return f"captured-history event {event['id']!r}"
    return None


def _baseline_recording(project: Project, key: str) -> tuple[str, str, dict] | None:
    """(baseline name, display id recorded under, entry) for the most recent
    baseline that filed ``key``, or None when no baseline remembers it.

    A pre-keys entry carries no identity evidence at all (`baseline_identity`
    returns None for it), so a key only stamped before surrogate keys existed
    is not found here -- and a project with no baselines is not either. Both
    leave nothing to compare a restore against, which is why the caller falls
    back to today's behaviour rather than refusing on no evidence.

    Both baseline shapes are read through the one shared `baseline_identity`,
    so the legacy display-id-keyed entry (surrogate in `key`) and the adopted
    key-keyed entry (display id in `id`) are found the same way.
    """
    found: list[tuple[str, str, str, dict]] = []
    for baseline in lifecycle.list_baselines(project):
        for record_id, entry in baseline.items.items():
            identity = keys.baseline_identity(record_id, entry)
            if identity is not None and identity[0] == key:
                found.append((baseline.stamped_at, baseline.name, identity[1], entry))
    if not found:
        return None
    _, name, display_id, entry = max(found, key=lambda row: (row[0], row[1]))
    return name, display_id, entry


def _baseline_content_conflict(project: Project, item: Item, key: str) -> str | None:
    """Refuse moving a recorded key onto an item its record does not describe.

    A matching display id proves nothing (docs/design/keys.md §3, §8): after a
    deletion the same id can name a different item, and the restore is then the
    thing that hands the old item's identity -- and every reference that names
    it -- to that new item, with a clean build afterwards. A baseline that
    filed this key also filed the title and content hash the key belonged to,
    so it can answer exactly the question the display id cannot.

    Both recorded signals are compared, and either one disagreeing refuses:
    the title is what a human reads, the hash is what proves. The hash is
    compared with `keys.hash_in_format`, the single shared reconstruction of
    "what this item's hash was under the recorded format", so a genuine
    restore of the same item matches whatever format stamped the record
    (an item's own key and display id are not in its content hash -- see
    `build.compute_hashes`). A record that carries neither signal, or a hash
    whose recorded format this build cannot reconstruct, leaves the remaining
    signal to decide on its own; no comparable signal at all is not a
    disagreement.
    """
    recording = _baseline_recording(project, key)
    if recording is None:
        return None
    baseline_name, recorded_id, entry = recording

    differences = []
    recorded_title = entry.get("title")
    if isinstance(recorded_title, str) and recorded_title and item.title != recorded_title:
        differences.append(f"title: baseline {recorded_title!r}, now {item.title!r}")
    recorded_hash = entry.get("hash")
    if isinstance(recorded_hash, str) and recorded_hash:
        try:
            recorded_format = int(entry.get("hash_format", 1))
        except (TypeError, ValueError):
            recorded_format = -1
        current_hash = keys.hash_in_format(item, project, recorded_format)
        if current_hash and current_hash != recorded_hash:
            differences.append(
                f"content hash: baseline {recorded_hash!r}, now {current_hash!r}"
            )
    if not differences:
        return None

    return (
        f"refusing to move key {key!r} onto {item.id}: baseline {baseline_name!r} "
        f"records that key under {recorded_id!r} with different content -- "
        + "; ".join(differences)
        + ". Restoring it would re-point every reference that names the key at "
        "this item and leave a passing build. If this really is the item that "
        "key belonged to -- the same item, edited since that baseline was "
        "stamped -- pass --force. If it is not, give the item a new display id "
        "so it is not mistaken for the old one; a fresh key is minted for it "
        "then."
    )


def apply(
    project_root: str,
    targets: list[str],
    dry_run: bool = False,
    force: bool = False,
) -> RestorationResult:
    config_path = os.path.join(project_root, schema.PROJECT_SETTINGS_NAME)
    try:
        project = loader.load_readonly(config_path)
        # `keys.hash_in_format` compares a stored baseline hash against
        # `item.content_hash` for the current format, and `load_readonly` does
        # not compute hashes. `keys adopt` does the same before it compares
        # stored hashes.
        build_mod.compute_hashes(project)
        selected = []
        seen_ids: set[str] = set()
        seen_keys: set[str] = set()
        for target in targets:
            display, separator, key = target.partition("@")
            if not display or not separator:
                raise ValueError(f"{target!r}: expected DISPLAY-ID@ORIGINAL-KEY")
            malformed = keys.malformed_key_message(key)
            if malformed:
                raise ValueError(malformed)
            if display in seen_ids or key in seen_keys:
                raise ValueError("each display id and original key must be supplied only once")
            seen_ids.add(display)
            seen_keys.add(key)
            matches = [i for i in project.items.values() if i.id == display]
            if len(matches) != 1 or matches[0].external:
                raise ValueError(f"{display!r} must name exactly one local item")
            item = matches[0]
            owners = [i for i in project.items.values() if i.key == key and i is not item]
            owners += [i for i in project.pending if i.key == key]
            if owners:
                raise ValueError(
                    f"key {key!r} is already declared by {owners[0].id or 'a pending item'}"
                )
            if item.key != key:
                record = _recorded_current_key(project, item)
                if record:
                    raise ValueError(
                        f"{display}'s current key {item.key!r} is recorded in {record}; "
                        "restoring another key would orphan that history"
                    )
                if not force:
                    conflict = _baseline_content_conflict(project, item, key)
                    if conflict:
                        raise ValueError(conflict)
            selected.append((item, key))

        originals: dict[str, str] = {}
        overlay: dict[str, str] = {}
        changes = []
        for item, key in selected:
            if item.key == key:
                continue
            path = os.path.join(project.root, item.source_file)
            if path not in originals:
                originals[path] = textio.read_text(path)
            before = overlay.get(path, originals[path])
            plan = patcher.plan_key_restore(before, item.id, key, path=item.source_file)
            if isinstance(plan, patcher.Refusal):
                raise ValueError(str(plan))
            overlay[path] = patcher.apply_patch(before, plan)
            changes.append((item.id, item.key, key))

        candidate = loader.load_readonly(config_path, overlay=overlay)
        blocking = revise._blocking_errors(candidate)
        if blocking:
            return RestorationResult(
                ok=False,
                errors=[
                    "restored project would still have build errors -- fix them or "
                    "supply all lost keys in one command"
                ]
                + [str(d) for d in blocking],
            )
        rewrites = [
            revise.FileRewrite(
                path=path,
                rel=os.path.relpath(path, project.root).replace(os.sep, "/"),
                before=originals[path],
                after=after,
            )
            for path, after in overlay.items()
        ]
    except (SchemaError, ValueError, OSError, history.HistoryError) as exc:
        return RestorationResult(ok=False, errors=[str(exc)])

    result = RestorationResult(ok=True, changes=changes, changed_files=[r.rel for r in rewrites])
    if dry_run or not rewrites:
        return result

    # Check every original before writing; do not overwrite an intervening edit.
    try:
        if any(textio.read_text(r.path) != r.before for r in rewrites):
            return RestorationResult(ok=False, errors=["item source changed while planning; retry"])
    except OSError as exc:
        return RestorationResult(ok=False, errors=[str(exc)])
    try:
        revise.write_rewrites(rewrites)
        validated = loader.load_readonly(config_path)
        for item, key in selected:
            restored = validated.item_by_id(item.id)
            if restored is None or restored.key != key:
                raise RuntimeError(f"{item.id} did not reload with original key {key!r}")
        blocking = revise._blocking_errors(validated)
        if blocking:
            raise RuntimeError("; ".join(str(d) for d in blocking))
    except Exception as exc:  # noqa: BLE001
        try:
            revise.restore_rewrites(rewrites)
        except Exception as rollback_exc:  # noqa: BLE001
            return RestorationResult(
                ok=False,
                errors=[f"restoration failed: {exc}", f"rollback also failed: {rollback_exc}"],
            )
        return RestorationResult(ok=False, errors=[f"restoration failed; rolled back: {exc}"])
    return result
