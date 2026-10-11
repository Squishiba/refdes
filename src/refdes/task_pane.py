"""The task pane's model (docs/design/thread-workbench.md §7a, phase W5a).

The floating task pane over an item's preview page (serve) and its published
page (site) is a *client* of `threads.threads_projection` — the same object
the index payload carries under `threads` — exactly like `refdes thread`:
it computes no fold, no tip resolution, no derived row, and reads no clock
(§7a's architecture constraint, living-notes §6). This module turns one
projection entry plus the entry the page shows into the pane's render model:
pure read, pure data, nothing rendered here — the template renders these
strings, and nothing writes.

Shape (per §7a's six sub-decisions):

* **tip list on an older entry (1):** one tab per open tip; a tab whose tip
  is not the entry the page shows carries the note
  `viewing LOG-007 · tasks as of tip LOG-012`;
* **forks get tabs, never a union (3):** a forked thread is one tab per
  open tip (the projection's per-branch `tasks`), and there is no code path
  that merges them — the fork rule lives in the fold, this module just
  refuses to undo it;
* **derived rows in a second, collapsed section (4):** grouped under the
  owner's per-kind headings in the ONE shared kind order
  (`threads.DERIVED_GROUP_ORDER` / `DERIVED_GROUP_HEADINGS`, aligned with
  `refdes work`, #194), the rows the projection already produced;
* a task row shows the same facts as `refdes thread` prints: the checkbox
  glyph *as text* (the pane is read-only — it emits no input that writes),
  the task id, its text, and `open since LOG-X, <date>` — absolute only,
  the CLI's `--as-of` relative spans belong to the CLI;
* the verdict line is `refdes thread`'s own line (§5 rule 4's "never alone"
  wording via `threads.verdict_open_suffix`), and a fold that refused shows
  as *conflicting*, never as "nothing concluded".

Page-side: an item page shows exactly one thread entry, so the pane's
"thread in view" is simply the page's item's thread — `panes_by_entry` keys
one pane per thread member, which is also the mechanism a hypothetical
multi-thread page would switch over.
"""

from __future__ import annotations

from . import threads as threads_mod
from .model import Item, Project


def thread_views(project: Project, *, graph=None, captures=None) -> list[dict]:
    """The projection, once per render (§7a: the pane is a client of it).

    Same call `refdes thread` and the index `threads` key make; `graph`
    reuses render's one build-wide follows graph and `captures` its one
    capture-store read, so a whole-site render parses the history event
    store once, not once per consumer (PR #197 review E1, the same
    `captures=` pass-through `work_projection` takes). A project with no
    `follows:` edge anywhere gets the empty list, which is what keeps its
    published pages byte-identical (no panes, no pane assets).
    """
    return threads_mod.threads_projection(project, graph=graph, captures=captures)


def label(item: Item) -> str:
    """How the projection names an entry (display id, or key when it has
    none) — the pane looks its thread up by the same label."""
    return threads_mod._label(item)


def panes_by_entry(views: list[dict]) -> dict[str, dict]:
    """`{entry label: pane model}` for every entry of every thread.

    One pane model per thread (shared object across that thread's entries
    would be wrong: the `viewing` note names the entry the page shows), so
    a member's pane differs from its tip's only in that note.
    """
    panes: dict[str, dict] = {}
    for view in views:
        for entry in view["entries"]:
            panes[entry] = pane_for(view, entry)
    return panes


def pane_for(view: dict, viewing: str) -> dict:
    """One thread's pane, as the page of `viewing` shows it."""
    return {
        "ref": view["ref"],
        "viewing": viewing,
        "forked": view["forked"],
        "tabs": [_tab(branch, viewing) for branch in view["branches"]],
        "derived": _derived_groups(view["derived"]),
        "derived_heading": threads_mod.DERIVED_HEADING,
    }


def _tab(branch: dict, viewing: str) -> dict:
    tip = branch["tip"]
    tasks = branch["tasks"]
    rows = tasks["rows"]
    open_rows = [row for row in (rows or []) if row.get("state") == "open"]
    return {
        "tip": tip,
        "date": branch["date"],
        "summary": branch["summary"],
        # §7a sub-decision 1: the tip's list on any entry, with the note
        # naming what the pane is looking at. On the tip's own page the
        # list is simply current, and `refdes thread` says nothing extra
        # there either — no note.
        "note": None if tip == viewing else f"viewing {viewing} · tasks as of tip {tip}",
        "verdict": _verdict_line(branch["verdict"], len(open_rows)),
        "tasks": _task_block(tasks),
    }


def _verdict_line(verdict: dict | None, open_count: int) -> str | None:
    """`refdes thread`'s Verdict line, in the owner's wording — including
    the conflicting posture (§5 rule 3 for `status`, said as itself)."""
    if verdict is None:
        return None
    if verdict["state"] == threads_mod.VERDICT_CONFLICTING:
        return threads_mod.verdict_conflicting_line(verdict["state"])
    on = f", {verdict['declared_on']}" if verdict["declared_on"] else ""
    suffix = threads_mod.verdict_open_suffix(verdict, open_count)
    return f"Verdict: {verdict['status']} ({verdict['declared_by']}{on}){suffix}"


def _task_block(tasks: dict) -> dict:
    """The authored list under the CLI's own heading (`Tasks at tip:` /
    `Tasks at <tip>:`), with the fold's distinct postures kept distinct —
    the same four lines `cmd_thread` prints, in `threads`' shared strings.

    The malformed count is its own field, never the note that stands where
    the rows go: `refdes thread` prints the count on the heading AND the
    valid rows under it, and a pane that let the count hide the rows made
    a partly-broken list look like an empty one (PR #197 review B1)."""
    if tasks["state"] == "ambiguous":
        return {
            "state": "ambiguous",
            "posture": threads_mod.TASK_POSTURE_AMBIGUOUS,
            "malformed_note": "",
            "rows": [],
        }
    if tasks["state"] == "undeclared":
        return {
            "state": "undeclared",
            "posture": threads_mod.TASK_POSTURE_UNDECLARED,
            "malformed_note": "",
            "rows": [],
        }
    if tasks["state"] == "cleared":
        return {
            "state": "cleared",
            "posture": threads_mod.task_posture_cleared(tasks["declared_by"]),
            "malformed_note": "",
            "rows": [],
        }
    malformed = tasks.get("malformed")
    rows = [
        {
            "glyph": threads_mod.TASK_GLYPHS.get(row.get("state"), threads_mod.TASK_GLYPH_UNKNOWN),
            "id": row.get("id", "?"),
            "text": row.get("text", ""),
            "since": _age(row),
        }
        for row in (tasks["rows"] or [])
    ]
    return {
        "state": "declared",
        "posture": "",
        "malformed_note": (
            threads_mod.task_malformed_note(malformed) if malformed else ""
        ),
        "rows": rows,
    }


def _age(row: dict) -> str:
    """§5 rule 3's age line, absolute — `open since LOG-001, 2026-08-30`.
    No relative span: that is what the CLI's `--as-of` adds, and a static
    page has no as-of (and no clock)."""
    since = row.get("open_since") or {}
    entry, declared = since.get("entry"), since.get("date")
    if not entry:
        return ""
    return f"(open since {entry}, {declared})" if declared else f"(open since {entry})"


def _derived_groups(rows: list[dict]) -> list[dict]:
    """The derived rows in their two structurally separate-group clothing
    (§5 rule 1): grouped by kind, kinds in the ONE shared order, each with
    the owner's group heading. The projection already ordered the rows; the
    grouping preserves that within-kind order and nothing here adds or
    removes a row — fix the gap, re-render, the row is gone (rule 2)."""
    groups = []
    unknown = sorted({row["kind"] for row in rows} - set(threads_mod.DERIVED_GROUP_ORDER))
    if unknown:
        # A kind the projection can emit but the table cannot group must
        # fail loudly, not drop its rows from the pane in silence (PR #197
        # review S3): add it to `threads.DERIVED_GROUP_HEADINGS`, which IS
        # the order now, and both surfaces pick it up.
        raise ValueError(
            f"derived kind(s) {unknown} missing from "
            "threads.DERIVED_GROUP_HEADINGS (the one group table)"
        )
    for kind in threads_mod.DERIVED_GROUP_ORDER:
        kind_rows = [row for row in rows if row["kind"] == kind]
        if kind_rows:
            groups.append(
                {
                    "kind": kind,
                    "heading": threads_mod.DERIVED_GROUP_HEADINGS[kind],
                    "rows": [_derived_row(row) for row in kind_rows],
                }
            )
    return groups


def _derived_row(row: dict) -> str:
    """One derived row in `refdes thread`'s detail wording, minus the kind
    column the group heading now names."""
    if row["kind"] == "check":
        detail = f"{row['value']} violates {row['against']}"
    elif row["kind"] == "blocked":
        stale = " (stale)" if row["stale"] else ""
        detail = f"by {row['root']} ({row['root_status']}){stale}"
    else:
        detail = row["problem"]
    return f"{row['ref']}  {detail}"
