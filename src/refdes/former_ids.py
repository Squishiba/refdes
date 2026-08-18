"""`refdes former-ids propose`: infer old-to-new id mappings, on request only.

Writing `former_ids:` by hand for every item a renumbering touches has a real
cost, which is exactly why it tends to not get done -- and why finding 12
exists in the first place. This module doesn't close that gap by guessing at
build time: it compares the most recent baseline snapshot (`.refdes/
baselines/<name>.yaml`, already recording each local item's id, type, and
title -- see lifecycle.py) against the live project, matches an item that
disappeared against one that appeared of the same type by title similarity,
and shows each candidate with its confidence.

Nothing is written until the caller names specific old ids to accept via
--confirm. This is deliberate, not a missing --yes flag: a wrong link in a
traceability tool is worse than a missing one, so inference only ever drafts
a suggestion -- confirmation decides, and the `former_ids:` entry it writes
is the source of truth build ever reads, never a fuzzy match recomputed on
the fly.
"""

from __future__ import annotations

import difflib
import os
from collections import defaultdict
from dataclasses import dataclass

from . import ids as ids_mod
from . import lifecycle
from .model import Project, SchemaError

# Below this, two titles are not meaningfully alike -- shown only as a
# candidate worth a human's judgement, never silently acted on regardless of
# score (that's the whole point of requiring --confirm).
MIN_CONFIDENCE = 0.35


class ProposeError(SchemaError):
    pass


@dataclass
class Candidate:
    old_id: str
    old_type: str
    old_title: str
    new_id: str
    new_title: str
    confidence: float


def _resolve_baseline(project: Project, baseline_name: str | None):
    if baseline_name is not None:
        baseline = lifecycle.load_baseline(project, baseline_name)
        if baseline is None:
            raise ProposeError(f"no baseline named {baseline_name!r}")
        return baseline
    baseline = lifecycle.latest(lifecycle.list_baselines(project))
    if baseline is None:
        raise ProposeError(
            "no baseline stamped yet -- nothing to compare against. Run "
            "'refdes revision <name>' first."
        )
    return baseline


def propose(project: Project, baseline_name: str | None = None) -> list[Candidate]:
    """Best-match candidates, one per still-unresolved removed id, greedily
    assigned by descending confidence so no added item is proposed twice."""
    baseline = _resolve_baseline(project, baseline_name)
    diff = lifecycle.diff_against(project, baseline)

    removed = [
        (old_id, old_type, old_title)
        for old_id, old_type, old_title in diff.removed
        if old_id not in project.former_ids  # already resolved -- nothing to propose
    ]

    added_by_type: dict[str, list[str]] = defaultdict(list)
    for item_id in diff.added:
        item = project.items.get(item_id)
        # Already carries its own former_ids -- not a candidate; confirm()
        # only ever adds a fresh entry, never merges into an existing one.
        if item is not None and not item.former_ids:
            added_by_type[item.type].append(item_id)

    scored: list[Candidate] = []
    for old_id, old_type, old_title in removed:
        for new_id in added_by_type.get(old_type, []):
            new_item = project.items[new_id]
            confidence = difflib.SequenceMatcher(None, old_title, new_item.title).ratio()
            if confidence >= MIN_CONFIDENCE:
                scored.append(
                    Candidate(old_id, old_type, old_title, new_id, new_item.title, confidence)
                )

    scored.sort(key=lambda c: c.confidence, reverse=True)
    claimed_old: set[str] = set()
    claimed_new: set[str] = set()
    out: list[Candidate] = []
    for c in scored:
        if c.old_id in claimed_old or c.new_id in claimed_new:
            continue
        claimed_old.add(c.old_id)
        claimed_new.add(c.new_id)
        out.append(c)
    return out


def confirm(project: Project, candidates: list[Candidate], old_ids: list[str]) -> list[Candidate]:
    """Write `former_ids: [old_id]` into each named candidate's new item.

    `old_ids` must all be present in `candidates` -- a name confirmed against
    a stale proposal (the project changed since `propose()` ran) is refused
    rather than silently matched against whatever the id happens to mean now.
    """
    by_old_id = {c.old_id: c for c in candidates}
    unknown = [old_id for old_id in old_ids if old_id not in by_old_id]
    if unknown:
        raise ProposeError(
            f"not a currently proposed candidate: {', '.join(unknown)} -- "
            "run 'refdes former-ids propose' again to see current candidates"
        )

    confirmed = [by_old_id[old_id] for old_id in old_ids]
    by_file: dict[str, list[Candidate]] = defaultdict(list)
    for c in confirmed:
        by_file[project.items[c.new_id].source_file].append(c)

    for rel, entries in by_file.items():
        path = os.path.join(project.root, rel)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()

        # Rewrite bottom-up so earlier line numbers stay valid as we insert --
        # same discipline ids.allocate() uses for the same reason.
        for c in sorted(entries, key=lambda c: project.items[c.new_id].source_line, reverse=True):
            item = project.items[c.new_id]
            if rel.endswith(".md"):
                lines = ids_mod.insert_into_markdown(
                    lines, item.source_line, f"former_ids: [{c.old_id}]"
                )
            else:
                updated = ids_mod.insert_into_list(
                    lines, item.source_line, "former_ids", f"[{c.old_id}]"
                )
                if updated is None:
                    project.error(
                        "could not write former_ids back into the source",
                        file=rel, line=item.source_line, item_id=c.new_id,
                    )
                    continue
                lines = updated

        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(newline.join(lines) + newline)

    for c in confirmed:
        project.items[c.new_id].former_ids.append(c.old_id)
        project.former_ids[c.old_id] = c.new_id

    return confirmed
