"""Explicit restoration of an item's original surrogate identity.

Unlike adoption, this transaction only edits supplied items' key fields. A
display label cannot prove continuity: the caller supplies the original key
after checking history. Full validation must succeed with that identity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import adopt, boards, history, keys, lifecycle, loader, patcher, revise, schema, seal, textio
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


def apply(project_root: str, targets: list[str], dry_run: bool = False) -> RestorationResult:
    config_path = os.path.join(project_root, schema.PROJECT_SETTINGS_NAME)
    try:
        project = loader.load_readonly(config_path)
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
