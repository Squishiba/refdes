"""`GET /api/navis` -- the editor's read of the Navis panel (design §11, N5a).

The editor is a *client* of the panel's projection, not a second
implementation (design §11): rows are `navis_panel.panel_model` over
`navis.projection(project)`, exactly the pair the published-site panel
renders, so the two surfaces cannot drift. The row set carries the full
`key` (panel_model), which the site template never renders.

The projection merges the `.refdes/navis/` archive store at request time
(it is not a `state.project_inputs` entry, so the poller never rebuilds on
an archive), which is what makes an on-disk archive visible on the next
GET. The GET itself reads and writes nothing.
"""

from __future__ import annotations

from .. import navis as navis_mod
from .. import navis_panel as panel_mod


def navis_payload(app) -> tuple[int, dict]:
    """(200, {"navis": rows, "counts": {"active", "archived"}}) for the
    current snapshot. One projection per request; a Navi-free project is
    the same shape with empty rows and zero counts."""
    project = app.state.snapshot.project
    model = panel_mod.panel_model(project, navis_mod.projection(project))
    rows = model["rows"] if model else []
    return 200, {
        "navis": rows,
        "counts": {
            "active": sum(1 for row in rows if not row["archived"]),
            "archived": sum(1 for row in rows if row["archived"]),
        },
    }
