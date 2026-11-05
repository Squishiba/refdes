"""HTTP face of `POST /api/navis/archive` and `POST /api/navis/restore`.

Every rule -- the no-write refusal, the keyless marker, the orphan, the
ambiguous prefix, the journal gate, the store errors -- lives in
`refdes.navis_ops` (the CLI renders the same `Outcome` in
`cli._navis_write_verb`); this module is a renderer of that Outcome into
statuses and JSON, the same posture as `api._apply_edit` is to
`serve.edit`. Rows for the selector come from `navis.projection`, so the
routes and `refdes navis all` can never disagree about a Navi's number,
key, text, source, or archive state (design §11's one-projection rule).

The write itself takes the editor's per-project write lock (`write_lock_for`)
around the whole decide-and-write, honouring the lock order documented in
`serve.edit.write_lock_for`: that lock first, `project_write_lock` (which
`navis_archive` takes internally) only ever inside it. A successful write is
followed by `app.state.refresh(force=True)` -- the save path's rebuild
mechanism, forced because the archive store is not a hashed build input --
so the preview is current when the response lands (design §11).
"""

from __future__ import annotations

from .. import navis as navis_mod
from .. import navis_ops
from .edit import write_lock_for

_NO_WRITE_MESSAGE = (
    "this server was started with --no-write: navis archive and restore are disabled"
)

_CONFLICT_MESSAGES = {
    "keyless": (
        "this Navi has no key -- keys are minted by the next writable "
        "command, and this marker's body is one refdes will not mint into, "
        "so it cannot be archived"
    ),
    "not_archived": "this Navi is not archived -- nothing to restore",
    "orphan": (
        "navis.archived_orphan: the Navi is archived with its marker not "
        "found -- restore refuses (there is no marker to reactivate; "
        "writing one would edit a body, design §9). Hand-restore the "
        "marker and the pair re-links by key."
    ),
}


def handle(app, verb: str, body) -> tuple[int, dict]:
    """`verb` is "archive" or "restore"; `body` is the parsed JSON body.

    The route's own `read_only` flag is the `allow_write` answer `navis_ops`
    refuses on (the same gate the CLI's `--no-write` reaches), consulted
    FIRST -- before any body validation, the sibling write routes' gate-first
    posture (design §13 slice 5: "403 under --no-write", unqualified), so a
    client probing writability with an incomplete payload gets the refusal;
    the `allow_write=` pass-through stays as defense in depth (one message
    source: `_NO_WRITE_MESSAGE`)."""
    if getattr(app, "read_only", False):
        return 403, {"kind": "refused", "error": _NO_WRITE_MESSAGE}
    if not isinstance(body, dict):
        return 400, {"kind": "bad_request", "error": "expected a JSON object"}
    selector, error = _selector(body.get("navi"))
    if error:
        return 400, {"kind": "bad_request", "error": error}

    project = app.state.snapshot.project
    root = str(project.root)
    with write_lock_for(root):
        rows = navis_mod.projection(project)
        result = navis_ops.apply(
            root,
            verb,
            rows,
            selector,
            allow_write=not getattr(app, "read_only", False),
        )
        if result.changed:
            # The §11 save-then-rebuild: force the synchronous rebuild (the
            # store write is invisible to the signature gate `refresh()`
            # normally checks), so the next preview GET is current.
            app.state.refresh(force=True)
    return _render(verb, selector, len(rows), result)


def _selector(value) -> tuple[str, str]:
    """The body's `navi` selector as the string `navis_ops.select` takes.
    A JSON int is an ordinal; a bool, float, container, null, or blank
    string is not a selector at all -- a request that cannot name a Navi
    is a 400, one that names nothing is the selector's own 404."""
    if isinstance(value, bool) or value is None:
        return "", _SELECTOR_HELP
    if isinstance(value, int):
        return str(value), ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "", _SELECTOR_HELP
        return text, ""
    return "", _SELECTOR_HELP


_SELECTOR_HELP = (
    "navi is required: the Navi's full key, a unique key prefix, or its "
    "`refdes navis all` ordinal (a JSON string or number)"
)


def _render(verb: str, selector: str, total: int, result) -> tuple[int, dict]:
    kind = result.kind
    if kind in ("ok", "noop"):
        return 200, {
            "kind": "ok",
            "verb": verb,
            "key": result.row["key"],
            "changed": result.changed,
        }
    if kind == "refused_no_write":
        return 403, {"kind": "refused", "error": _NO_WRITE_MESSAGE}
    if kind == "not_found":
        return 404, {
            "kind": "not_found",
            "error": (
                f"no Navi {selector!r}: `refdes navis all` numbers them "
                f"1..{total}; a selector is a number, a full key, or a key "
                "prefix"
            ),
        }
    if kind == "ambiguous":
        return 409, {
            "kind": "ambiguous",
            "error": f"navi key prefix {selector!r} is ambiguous: name one of its candidates",
            "candidates": [
                {
                    "key": cand["key"],
                    "text": cand["text"],
                    "file": cand["source"]["file"],
                    "line": cand["source"]["line"],
                }
                for cand in result.candidates
            ],
        }
    if kind == "error":
        return 500, {"kind": "error", "error": result.detail}
    # The 409 conflicts: keyless, not_archived, orphan, journal_pending.
    # journal_pending carries the store's own refusal text in `detail`.
    if kind in _CONFLICT_MESSAGES or kind == "journal_pending":
        return 409, {
            "kind": "conflict",
            "reason": kind,
            "error": result.detail if kind == "journal_pending" else _CONFLICT_MESSAGES[kind],
        }
    # A kind this renderer has never seen (a future `navis_ops` addition):
    # a JSON 500 naming it, never a KeyError that dies in the handler thread
    # and drops the connection.
    return 500, {
        "kind": "error",
        "error": f"navis {verb}: navis_ops reported an outcome kind this "
        f"server does not know how to render ({kind!r})",
    }
