"""The published site's read-only Navis panel (design §11, §13 item 4).

The panel is a projection of a projection: `navis.projection` is the one
service for Navi facts (design §11 -- "no second implementation"), and
this module only *presents* those rows for the template. It reads nothing
and writes nothing -- the published site is read-only (PR #396 provisional
decision 4; archive and restore live in CLI/serve), which is why every
restore control the template renders is disabled and names the CLI
command that actually acts.

Placement (§11): a second fixed panel stacked above the task pane in the
z-index order (toggle 63 / pane 62 in `templates/taskpane/taskpane.css`,
Navis above at 65), opened by a `<details>` toggle, so it needs no
JavaScript and no fetch -- the panel data rides the page server-side.
"""

from __future__ import annotations

from .model import Project

#: How many leading key characters a row is labelled with -- the CLI's
#: short-key spelling (design §7: "CLI and panel show the 6-char prefix,
#: full key in `show`"), so a panel row and a `refdes navis` command agree.
KEY_PREFIX = 6

#: The §9 row-4 note, shown next to an archived row whose live marker text
#: differs from the record's snapshot. The snapshot is never re-stamped
#: (§9: the panel shows the record, not a re-snapshot).
CHANGED_NOTE = "marker text has changed since archived"


def panel_model(project: Project, rows: list[dict]) -> dict | None:
    """Present one render's `navis.projection` rows for `base.html.j2`.

    Returns None for a Navi-free project -- the panel, its asset and its
    `<link>` all hinge on this being non-None, so a project without Navis
    publishes exactly the bytes it published before the panel existed (the
    `taskpane_assets` gate posture, `render.py:1035-1059`).

    Each row carries: `key6` (the §7 short key), `text` (an archived row's
    snapshot text, §9), `item` + `href` (the §10 link to the source item's
    page -- None when unresolvable, §9 row 3: an orphan whose stored item
    key names no live item has a dead link by design),
    `archived`, `changed` (§9 row 4) and `orphan` (§9 row 3, labelled
    "marker not found"). Rows keep the projection's order, active first.
    """
    if not rows:
        return None
    by_id = {item.id: item for item in project.local_items}
    by_key = {item.key: item for item in project.local_items if item.key}
    model = []
    for row in rows:
        source = row["source"]
        # §10: a scanned row carries the CURRENT display id of the item the
        # marker was scanned out of (`source.item`), so the panel link is a
        # display link (§9 row 2: "the panel link with no record write").
        # An orphan row has no scan; its record stores an item KEY (§10:
        # stored identity is by key), resolved to the item's current page.
        item = by_id.get(source["item"]) if source.get("item") else by_key.get(
            source.get("key")
        )
        archived = bool(row["archived"])
        # §9: an archived row shows the record's snapshot, never the live
        # marker text -- that is the whole point of the note in `changed`
        # rows (the live text has moved; the panel shows what was archived).
        text = row["snapshot"]["text"] if archived and row["snapshot"] else row["text"]
        model.append(
            {
                "key6": (row["key"] or "")[:KEY_PREFIX],
                "text": text,
                "item": item.id if item else None,
                "href": f"{item.slug}.html" if item else None,
                "file": source["file"],
                "line": source["line"],
                "archived": bool(row["archived"]),
                "changed": bool(row["text_changed"]),
                "orphan": source.get("marker_found") is False,
            }
        )
    active = [row for row in model if not row["archived"]]
    return {
        "rows": model,
        "active": active,
        "archived": [row for row in model if row["archived"]],
        "count": len(model),
        "changed_note": CHANGED_NOTE,
    }
