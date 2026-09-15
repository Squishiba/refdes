"""Explicit, transactional surrogate-key adoption (docs/design/keys.md §7)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import boards as boards_mod
from . import build as build_mod
from . import keys as keys_mod
from . import lifecycle, revise
from . import links as links_mod
from . import schema as schema_mod
from . import seal as seal_mod
from .model import SchemaError

_MARKER_TEXT = """\
# Refdes surrogate-key adoption state.
# Commit this file: future stamps, seals, and membership manifests use key-keyed storage.
# Written by `refdes keys adopt`; do not edit it by hand.
adopted: true
format: 1
"""


@dataclass
class BaselineAdoption:
    name: str
    carried: int
    total: int
    uncomparable: list[str] = field(default_factory=list)


@dataclass
class SealAdoption:
    file: str
    carried: int
    total: int
    uncomparable: list[str] = field(default_factory=list)


@dataclass
class MembershipAdoption:
    file: str
    carried: int
    total: int
    unidentified: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


@dataclass
class AdoptionResult:
    ok: bool
    minted: int = 0
    expanded: int = 0
    checks_expanded: int = 0
    baselines: list[BaselineAdoption] = field(default_factory=list)
    seals: list[SealAdoption] = field(default_factory=list)
    memberships: list[MembershipAdoption] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False
    already_adopted: bool = False
    frozen_follows: int = 0


def _baseline_data(baseline: lifecycle.Baseline, items: dict[str, dict]) -> dict:
    data = {
        "kind": baseline.kind,
        "name": baseline.name,
        "stamped_at": baseline.stamped_at,
        "stamped_by": baseline.stamped_by,
        "refdes_version": baseline.refdes_version,
    }
    if baseline.standard is not None:
        data["standard"] = baseline.standard
    if baseline.gate is not None:
        data["gate"] = baseline.gate
    data["items"] = items
    return data


def _seal_files(project) -> list[tuple[str, str, str]]:
    """Return ``(relative path, board, absolute path)`` for every seal file."""
    directory = os.path.join(project.root, ".refdes")
    if not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory)):
        if name == "log-seal.yaml":
            board = ""
        elif name.startswith("log-seal-") and name.endswith(".yaml"):
            board = name[len("log-seal-") : -len(".yaml")]
        else:
            continue
        found.append((f".refdes/{name}", board, os.path.join(directory, name)))
    return found


def _chain_rewrites(
    *rewrite_lists: list[revise.FileRewrite],
) -> list[revise.FileRewrite]:
    """Merge sequentially-computed FileRewrite lists -- each stage computed
    using the previous stage's output as its own ``source_texts`` -- into
    one rewrite per file: the earliest ``before`` seen and the latest
    ``after``. A no-op stage for a given file (it read but didn't change it)
    contributes nothing, so the merge still finds that file's true original
    text in whichever stage did touch it.
    """
    before_by_rel: dict[str, str] = {}
    after_by_rel: dict[str, str] = {}
    path_by_rel: dict[str, str] = {}
    order: list[str] = []
    for rewrites in rewrite_lists:
        for rewrite in rewrites:
            if rewrite.rel not in before_by_rel:
                before_by_rel[rewrite.rel] = rewrite.before
                order.append(rewrite.rel)
            after_by_rel[rewrite.rel] = rewrite.after
            path_by_rel[rewrite.rel] = rewrite.path
    return [
        revise.FileRewrite(
            path=path_by_rel[rel], rel=rel,
            before=before_by_rel[rel], after=after_by_rel[rel],
        )
        for rel in order
        if before_by_rel[rel] != after_by_rel[rel]
    ]


def _compose_item_rewrites(project, assignments) -> tuple[list[revise.FileRewrite], object]:
    """Compose source-preserving item edits before key insertion.

    Each stage reads the preceding stage's output through ``source_texts``:
    all use source lines from the original parse, while a preceding rewrite
    may have changed the exact text the next stage must preserve. The fixed
    order is links -> checks -> follows -> keys. Links/checks/follows touch
    disjoint fields, but follows must run after assignments give every target
    an in-memory key and before key insertion shifts source lines.
    """
    for item, new_key in assignments:
        item.key = new_key

    link_plan = links_mod.plan_expansion(project)
    link_texts = {rewrite.rel: rewrite.after for rewrite in link_plan.files}

    check_plan = links_mod.plan_check_expansion(project, source_texts=link_texts)
    check_texts = dict(link_texts)
    check_texts.update({rewrite.rel: rewrite.after for rewrite in check_plan.files})

    follows_plan = links_mod.plan_follows_freeze(project, source_texts=check_texts)
    follows_texts = dict(check_texts)
    follows_texts.update({rewrite.rel: rewrite.after for rewrite in follows_plan.files})

    mint_plan = keys_mod.plan_missing(
        project, source_texts=follows_texts, assignments=assignments
    )

    composed = _chain_rewrites(
        link_plan.files, check_plan.files, follows_plan.files, mint_plan.rewrites
    )
    return composed, (mint_plan, link_plan, check_plan, follows_plan)


def apply(project_root: str, dry_run: bool = False) -> AdoptionResult:
    """Plan, validate, and atomically apply explicit surrogate-key adoption."""
    config_path = os.path.join(project_root, schema_mod.PROJECT_SETTINGS_NAME)
    try:
        project = revise._load_and_validate(config_path)
    except SchemaError as exc:
        return AdoptionResult(ok=False, errors=[f"project does not load: {exc}"], dry_run=dry_run)

    # Checked before the generic build-error gate: adoption mints keys, and a
    # hand-deleted key is exactly the item adoption must not mint for.
    deleted = keys_mod.deleted_key_records(project)
    if deleted:
        return AdoptionResult(
            ok=False,
            errors=[keys_mod.deleted_key_message(record) for record in deleted],
            dry_run=dry_run,
        )

    blocking = revise._blocking_errors(project)
    if blocking:
        return AdoptionResult(
            ok=False,
            errors=["project has existing build errors -- fix those first"]
            + [str(diagnostic) for diagnostic in blocking],
            dry_run=dry_run,
        )

    assignments = keys_mod.missing_assignments(project)
    item_rewrites, plans = _compose_item_rewrites(project, assignments)
    mint_plan, link_plan, check_plan, follows_plan = plans
    if (
        mint_plan.remaining
        or link_plan.remaining
        or check_plan.remaining
        or follows_plan.remaining
    ):
        errors = []
        if mint_plan.remaining:
            errors.append(f"could not write back {mint_plan.remaining} key(s)")
        if link_plan.remaining:
            errors.append(
                f"could not expand {link_plan.remaining} local link reference(s)"
            )
        if check_plan.remaining:
            errors.append(
                f"could not expand {check_plan.remaining} local check reference(s)"
            )
        if follows_plan.remaining:
            errors.append(
                f"could not freeze {follows_plan.remaining} local follows reference(s)"
            )
        return AdoptionResult(ok=False, errors=errors, dry_run=dry_run)

    build_mod.compute_hashes(project)
    rewrites = list(item_rewrites)
    baselines = []
    for baseline in lifecycle.list_baselines(project):
        storage = keys_mod.plan_surrogate_storage(project, baseline.items, {})
        items = dict(sorted(storage.baseline_items.items()))
        path = lifecycle.baseline_path(project, baseline.name)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            before = fh.read()
        after = lifecycle.format_baseline(_baseline_data(baseline, items))
        if after != before:
            rewrites.append(
                revise.FileRewrite(
                    path=path,
                    rel=os.path.relpath(path, project.root).replace("\\", "/"),
                    before=before,
                    after=after,
                )
            )
        baselines.append(
            BaselineAdoption(
                name=baseline.name,
                carried=len(baseline.items) - len(storage.baseline_uncomparable),
                total=len(baseline.items),
                uncomparable=storage.baseline_uncomparable,
            )
        )

    seals = []
    for rel, board, path in _seal_files(project):
        original = seal_mod.load_seals(project, board)
        if not original:
            continue
        storage = keys_mod.plan_surrogate_storage(project, {}, original)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            before = fh.read()
        after = seal_mod.format_seals(storage.seals)
        if after != before:
            rewrites.append(
                revise.FileRewrite(path=path, rel=rel, before=before, after=after)
            )
        seals.append(
            SealAdoption(
                file=rel,
                carried=len(original) - len(storage.seal_uncomparable),
                total=len(original),
                uncomparable=storage.seal_uncomparable,
            )
        )

    memberships = []
    membership_path = boards_mod.manifest_path(project)
    if os.path.isfile(membership_path):
        original = boards_mod.load_manifest(project)
        storage = boards_mod.plan_surrogate_storage(project, original)
        with open(membership_path, "r", encoding="utf-8", newline="") as fh:
            before = fh.read()
        after = boards_mod.format_manifest(project, storage.manifest)
        if after != before:
            rewrites.append(
                revise.FileRewrite(
                    path=membership_path,
                    rel=boards_mod.MANIFEST_FILE,
                    before=before,
                    after=after,
                )
            )
        if storage.total:
            memberships.append(
                MembershipAdoption(
                    file=boards_mod.MANIFEST_FILE,
                    carried=storage.carried,
                    total=storage.total,
                    unidentified=storage.unidentified,
                    stale=storage.stale,
                )
            )


    marker_path = keys_mod.adoption_marker_path(project)
    marker_existed = os.path.isfile(marker_path)
    marker_was_adopted = keys_mod.is_adopted(project)
    marker_before = ""
    if marker_existed:
        with open(marker_path, "r", encoding="utf-8", newline="") as fh:
            marker_before = fh.read()
    if not marker_was_adopted:
        rewrites.append(
            revise.FileRewrite(
                path=marker_path,
                rel=keys_mod.ADOPTION_MARKER,
                before=marker_before,
                after=_MARKER_TEXT,
                existed=marker_existed,
            )
        )

    changed_files = [rewrite.rel for rewrite in rewrites]
    result = AdoptionResult(
        ok=True,
        minted=len(mint_plan.assignments),
        expanded=link_plan.expansion_count - link_plan.remaining,
        checks_expanded=check_plan.expansion_count - check_plan.remaining,
        baselines=baselines,
        seals=seals,
        memberships=memberships,
        frozen_follows=len(follows_plan.rewrites),
        changed_files=changed_files,
        dry_run=dry_run,
        already_adopted=marker_was_adopted and not changed_files,
    )
    if dry_run or not rewrites:
        return result

    try:
        revise.write_rewrites(rewrites)
        validated = revise._load_and_validate(config_path)
        after_blocking = revise._blocking_errors(validated)
        if after_blocking:
            raise RuntimeError(
                "adopted project has build errors: "
                + "; ".join(str(diagnostic) for diagnostic in after_blocking)
            )
    except Exception as exc:  # noqa: BLE001
        try:
            revise.restore_rewrites(rewrites)
        except Exception as rollback_exc:  # noqa: BLE001
            return AdoptionResult(
                ok=False,
                errors=[
                    f"adoption failed: {exc}",
                    f"rollback also failed: {rollback_exc}",
                ],
            )
        return AdoptionResult(ok=False, errors=[f"adoption failed; rolled back: {exc}"])

    return result
