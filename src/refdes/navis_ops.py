"""The Navis archive/restore decisions, as a service.

Design §11's rule -- "the panel is a client of the same projection, never
a second implementation" (in-prog-logs/navis-design-20261025.md) -- means
the coming serve API and the CLI must share one copy of the rules, not
transcribe them. This module is that copy: `select` resolves a selector
the way every Navis verb does, and `apply` runs the archive/restore
decision -- performing the store write when the rules allow it -- and
returns the outcome as data.

It prints nothing, parses no argparse object, and returns no exit code:
rendering and exit codes belong to the caller, so a caller with no
stdout (a server) gets the same decisions as one with a terminal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import keys as keys_mod
from . import navis_archive as navis_archive_mod


@dataclass(frozen=True)
class Outcome:
    """The result of one archive/restore attempt, as data.

    ``kind`` names the outcome: one of ``ok``, ``noop``,
    ``refused_no_write``, ``ambiguous``, ``not_found``, ``keyless``,
    ``not_archived``, ``orphan``, ``journal_pending``, ``error``.
    ``row`` is the selected Show-all row, None while nothing was selected.
    ``candidates`` is populated only for ``ambiguous``. ``changed``
    says a record was written or removed (only ever true for ``ok``).
    ``detail`` carries the failure text for ``journal_pending`` and
    ``error`` -- the text the CLI prints after its ``error: `` prefix --
    and is empty for every other kind.
    """

    kind: str
    row: dict | None = None
    candidates: tuple = ()
    changed: bool = False
    detail: str = ""


def select(rows: list[dict], selector: str) -> tuple[dict | None, list[dict]]:
    """The selector every Navis verb shares (slice 2's `show` selector,
    design §5): the full 11-character key first -- every digit is in the
    key alphabet, so an 11-character all-digit string is legal key
    grammar and a full-key selector must not be read as an out-of-range
    ordinal number -- then a 6-to-10-character key *prefix* (the short
    key the CLI and panel display; a unique match selects, an ambiguous
    one names its candidates, §5's short-key resolution), then the
    ls/Show-all ordinal. Returns ``(row, ambiguous)``; at most one side
    is populated.

    Slice 3: `archive` and `restore` share this selector verbatim --
    one way to name a Navi, for every verb that needs to name one."""
    row = next((r for r in rows if r["key"] == selector), None)
    if (
        row is None
        and 6 <= len(selector) < keys_mod.KEY_LEN
        and all(ch in keys_mod.ALPHABET for ch in selector)
    ):
        candidates = [
            r for r in rows if r["key"] and r["key"].startswith(selector)
        ]
        if len(candidates) == 1:
            row = candidates[0]
        elif candidates:
            return None, candidates
    # ASCII digits only, and no more of them than the largest ordinal
    # has: a longer digit string is out of range by length alone, and
    # int() of a 4300-digit string raises (CPython's integer-string
    # limit) -- a selector that names nothing is a naming error, exit 2,
    # never a traceback.
    if (
        row is None
        and len(selector) <= len(str(len(rows)))
        and re.fullmatch(r"[0-9]+", selector)
    ):
        index = int(selector) - 1
        if 0 <= index < len(rows):
            row = rows[index]
    return row, []


def apply(
    project_root: str,
    verb: str,
    rows: list[dict],
    selector: str,
    *,
    allow_write: bool,
) -> Outcome:
    """Decide and (when allowed) perform one archive/restore, design §6,
    §9, §12, §13. The only writes are the Navi's gzip record under
    `.refdes/navis/` and its removal -- that is the §7.3 invariant, and
    it is why there is no other write here: the item's body keeps the
    marker (the pointer), the record is the snapshot, and a Navi's text
    is edited by editing the marker, never by the archive. The store
    writer checks the journal for callers that are not this CLI (§12).

    ``project_root`` is the project directory, ``verb`` is "archive" or
    "restore", ``rows`` are the Show-all projection rows, ``selector``
    names one of them, and ``allow_write`` is the caller's --no-write
    answer. The caller renders the outcome (and exits); this decides."""
    if not allow_write:
        return Outcome("refused_no_write")
    row, ambiguous = select(rows, selector)
    if ambiguous:
        return Outcome("ambiguous", candidates=tuple(ambiguous))
    if row is None:
        return Outcome("not_found")
    key = row["key"]
    if not key:
        # §5/§7.2: a keyless marker (a --no-write run, or a body refdes
        # will not mint into) has no identity to archive under.
        return Outcome("keyless", row=row)
    src = row["source"]
    try:
        if verb == "archive":
            if row["archived"]:
                return Outcome("noop", row=row)
            created, _record = navis_archive_mod.archive_record(
                project_root,
                navi_key=key,
                item_key=src.get("key") or "",
                source={"file": src["file"], "line": src["line"]},
                text=row["text"],
            )
            return Outcome("ok", row=row, changed=created)
        # restore
        if not row["archived"]:
            return Outcome("not_archived", row=row)
        if src.get("marker_found") is False:
            # §9 row 3: restore reactivates a *marker*; writing a marker
            # back would edit a body, which §2.3 forbids. The record
            # stays, Show-all keeps revealing it, and hand-restoring the
            # marker re-pairs the two by key.
            return Outcome("orphan", row=row)
        removed = navis_archive_mod.restore_record(project_root, key)
        return Outcome("ok", row=row, changed=removed)
    except navis_archive_mod.JournalPending as exc:
        return Outcome("journal_pending", row=row, detail=str(exc))
    except navis_archive_mod.NavisArchiveError as exc:
        return Outcome("error", row=row, detail=str(exc))
    except OSError as exc:
        # The record is the archive: a failed write says so and writes
        # nothing half -- the temp is unlinked by the store writer, the
        # marker is untouched. Never a traceback.
        return Outcome(
            "error",
            row=row,
            detail=f"navis {verb} could not write the archive store: {exc}",
        )
