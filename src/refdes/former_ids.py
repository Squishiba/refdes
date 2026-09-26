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
from . import keys as keys_mod
from . import lifecycle
from . import textio
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
    # True when the pairing comes from surrogate-key identity, not from a
    # similarity score: a keyed baseline records each item's immutable key,
    # so an old display id matching a new one through the same key is exact
    # provenance, not inference (docs/design/keys.md §4).
    exact: bool = False


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


def _baseline_carries_keys(baseline) -> bool:
    """Whether any baseline record carries surrogate-key identity (either
    §5 shape: key-keyed, or a legacy record with a `key:` field)."""
    return any(
        keys_mod.baseline_identity(record_id, entry) is not None
        for record_id, entry in baseline.items.items()
    )


def _entry_for_relabel(baseline, old_id: str, key: str) -> dict:
    """The stamped record for a relabelled pair, in either §5 storage shape.

    A baseline that is *not* adopted is keyed by display id and carries the
    surrogate inside a `key:` field, so indexing the map by the surrogate --
    which is what `diff.relabelled` hands back -- finds nothing and every
    `old_title` came back empty. An adopted baseline *is* keyed by surrogate,
    so the same lookup works there. Resolve both, by key first (that is the
    identity the rename was proven by) and by display id second, so a mixed
    baseline left by an uncomparable historical entry still resolves.
    """
    entry = baseline.items.get(key)
    if entry is not None:
        return entry
    for record_id, candidate in baseline.items.items():
        identity = keys_mod.baseline_identity(record_id, candidate)
        if identity is None:
            continue
        if identity[0] == key or identity[1] == old_id:
            return candidate
    return {}


def propose(
    project: Project, baseline_name: str | None = None, write: bool = True
) -> list[Candidate]:
    """Best-match candidates, one per still-unresolved removed id, greedily
    assigned by descending confidence so no added item is proposed twice.

    A baseline that carries surrogate keys needs no inference for a display
    rename: `diff.relabelled` already pairs old id, new id, and the key that
    proves they are the same item, so those candidates come back exact
    (confidence 1.0, `exact=True`) and similarity scoring never runs on
    them. Similarity scoring remains the path for legacy keyless baselines
    -- the pre-keys world this command was written for.

    `write` threads through to `lifecycle.diff_against`'s hash-format
    migration -- `--no-write` must not rewrite a baseline file just to
    propose candidates (docs/design/keys.md §2).
    """
    baseline = _resolve_baseline(project, baseline_name)
    diff = lifecycle.diff_against(project, baseline, write=write)

    if _baseline_carries_keys(baseline):
        out: list[Candidate] = []
        for old_id, new_id, _key in diff.relabelled:
            if old_id in project.former_ids:  # already resolved
                continue
            new_item = project.item_by_id(new_id)
            if new_item is None or new_item.former_ids:
                continue
            entry = _entry_for_relabel(baseline, old_id, _key)
            out.append(
                Candidate(
                    old_id=old_id,
                    old_type=str(entry.get("type", new_item.type)),
                    old_title=str(entry.get("title", "")),
                    new_id=new_id,
                    new_title=new_item.title,
                    confidence=1.0,
                    exact=True,
                )
            )
        return out

    removed = [
        (old_id, old_type, old_title)
        for old_id, old_type, old_title in diff.removed
        if old_id not in project.former_ids  # already resolved -- nothing to propose
    ]

    added_by_type: dict[str, list[str]] = defaultdict(list)
    for item_id in diff.added:
        item = project.item_by_id(item_id)
        # Already carries its own former_ids -- not a candidate; confirm()
        # only ever adds a fresh entry, never merges into an existing one.
        if item is not None and not item.former_ids:
            added_by_type[item.type].append(item_id)

    scored: list[Candidate] = []
    for old_id, old_type, old_title in removed:
        for new_id in added_by_type.get(old_type, []):
            new_item = project.item_by_id(new_id)
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
        by_file[project.item_by_id(c.new_id).source_file].append(c)

    for rel, entries in by_file.items():
        path = os.path.join(project.root, rel)
        # This read was in text mode, which is the whole bug: universal
        # newlines had already folded every CRLF to LF before the style check
        # below could run, so a CRLF file left `--confirm` entirely LF and an LF
        # file was handed to the platform's newline translation on the way out.
        source = textio.SourceText.of(path)
        lines = source.lines

        # Rewrite bottom-up so earlier line numbers stay valid as we insert --
        # same discipline ids.allocate() uses for the same reason.
        for c in sorted(entries, key=lambda c: project.item_by_id(c.new_id).source_line, reverse=True):
            item = project.item_by_id(c.new_id)
            if rel.endswith(".md"):
                updated = ids_mod.insert_into_markdown(
                    lines, item.source_line, f"former_ids: [{c.old_id}]"
                )
                if updated is None:
                    project.error(
                        "could not write former_ids back into the source",
                        file=rel, line=item.source_line, item_id=c.new_id,
                    )
                    continue
                lines = updated
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

        textio.write_text(path, source.render(lines))

    for c in confirmed:
        project.item_by_id(c.new_id).former_ids.append(c.old_id)
        project.former_ids[c.old_id] = c.new_id

    return confirmed
