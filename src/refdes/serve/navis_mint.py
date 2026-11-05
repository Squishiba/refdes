"""HTTP face of `POST /api/navis/mint`.

Every mint rule -- exact provenance or refuse, keys unique against the
project's declared keys, the ``<!--navi:`` -> ``<!--navi:KEY `` splice that
never changes line counts, idempotence -- lives in `refdes.navis.mint_keys`
(the CLI renders the same call in `cli`); this module is a renderer of that
call into a status and JSON, the same posture as `navis_write` is to
`navis_ops` and `api._apply_edit` is to `serve.edit`. The route plans against
the served snapshot's project: `mint_keys` writes through
`revise.write_rewrites_verified`, whose parse guard and line-exact splice
refuse a marker per marker when the file changed under the parse -- the
user's bytes win, never a clobber -- while an untouched file still mints in
the same call.

`still_keyless` counts the call's `NAVI_MINT_REFUSED` warnings on the
project (the delta across the call, which is the total: a read-only build
emits none). Refusals are mint rules `mint_keys` itself reports, so the
route decides nothing; the alternative -- counting keyless rows of the
rebuilt projection -- would also count markers `mint_keys` never touched (a
malformed marker is the corruption lint's report, not a mint refusal), and
measure the project where the response promises this call.

The write takes the editor's per-project write lock (`write_lock_for`)
around the whole plan-and-write, honouring the lock order documented in
`serve.edit.write_lock_for`: that lock first, `project_write_lock` only ever
inside it. Checked at implementation: `mint_keys` takes no lock of its own
-- `revise.write_rewrites_verified` writes files directly through
`textio.atomic_write_text` (no `project_write_lock` anywhere in
`revise.py`) -- so this route is the only lock holder on the mint path, and
it takes the first lock of the order. A successful mint is followed by
`app.state.refresh(force=True)` -- the save path's rebuild, forced because
the second request must plan against the committed state, and so the panel
and the preview are current when the response lands (design §11). Nothing
here touches `.refdes/navis/`: the mint writes marker bytes in item files
and nothing else.
"""

from __future__ import annotations

from .. import navis as navis_mod
from ..navis import NAVI_MINT_REFUSED_CODE
from .edit import write_lock_for

_NO_WRITE_MESSAGE = (
    "this server was started with --no-write: navis mint is disabled"
)


def handle(app, body) -> tuple[int, dict]:
    """`body` is the parsed JSON body. The body carries no parameters -- the
    mint is project-wide, `navis.mint_keys`' posture (per-marker mint is
    out of scope, design §5) -- so extra keys are ignored and anything that
    is not a JSON object is a 400. The route's own `read_only` flag is
    consulted FIRST, before any body validation: the sibling write routes'
    gate-first posture (design §13 slice 5's unqualified "403 under
    `--no-write`"), so a client probing writability with an incomplete
    payload gets the refusal, not a 400 that leaks the body rules of a
    server that cannot write."""
    if getattr(app, "read_only", False):
        return 403, {"kind": "refused", "error": _NO_WRITE_MESSAGE}
    if not isinstance(body, dict):
        return 400, {"kind": "bad_request", "error": "expected a JSON object"}

    root = str(app.state.snapshot.project.root)
    with write_lock_for(root):
        # The snapshot is read inside the lock: the request that loses a
        # concurrent pair plans against the state the winner committed (and
        # refresh installed), not against the project it arrived to.
        project = app.state.snapshot.project
        refused_before = _refusal_count(project)
        try:
            landed = navis_mod.mint_keys(project, write=True)
        except OSError as exc:
            # The sibling routes' `navis_ops.apply` posture: a write that
            # the filesystem refused mid-call is a JSON 500 naming it,
            # never a traceback that dies in the handler thread.
            return 500, {"kind": "error", "error": str(exc)}
        still_keyless = _refusal_count(project) - refused_before
        if landed:
            # The §11 save-then-rebuild, forced through the same path the
            # editor save uses, so the response lands on a current model.
            app.state.refresh(force=True)
    return 200, {
        "kind": "ok",
        "changed": bool(landed),
        "minted": [
            {
                "key": key,
                "key6": key[:6],
                "item": item.id,
                "file": item.source_file,
            }
            for item, key in landed
        ],
        "still_keyless": still_keyless,
    }


def _refusal_count(project) -> int:
    return sum(1 for d in project.diagnostics if d.code == NAVI_MINT_REFUSED_CODE)
