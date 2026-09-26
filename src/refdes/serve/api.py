"""JSON API handlers for `refdes serve`, kept free of HTTP details.

`handle()` is given an already-authenticated request (see `server`) and
returns `(status, payload)`. Reads answer from the *built* project snapshot,
never from a file scan.
"""

from __future__ import annotations

import os
import urllib.parse

from ..model import CHECK_VIOLATION, Diagnostic, Item, Project
from ..patcher import PROTECTED_FIELDS, AddLink, RemoveLink, SetBody, SetField
from ..seal import is_sealed
from . import edit as edit_mod
from . import filters as filters_mod
from . import sources as sources_mod
from . import state as state_mod
from .filters import FilterError, check_state, item_tags


def item_pages(project: Project) -> dict[str, str]:
    """`project.items` dict key (surrogate key or provisional handle) ->
    the rendered page filename `render_site` writes for that item."""
    return {key: f"{item.slug}.html" for key, item in project.items.items()}


# Three source-read routes are dispatched below through `_SOURCE_ROUTES`, which
# is declared with their handlers further down this file. They are all GET: a
# non-GET on one is a 405 here, the same as any other `/api/item/` route.
def handle(app, method: str, path: str, query: dict[str, list[str]], body) -> tuple[int, dict]:
    if path == "/api/revision" and method in ("GET", "HEAD"):
        return 200, app.state.revision_info()
    if path == "/api/items" and method in ("GET", "HEAD"):
        return _items(app, query)
    if path.startswith("/api/item/") and path.endswith("/edit"):
        ref = urllib.parse.unquote(path[len("/api/item/"):-len("/edit")])
        if method == "POST":
            return _apply_edit(app, ref, body)
        return 405, {"error": "method not allowed"}
    if path == "/api/create/schema" and method in ("GET", "HEAD"):
        return _create_schema(app)
    if path == "/api/create/preview" and method in ("GET", "HEAD"):
        return _create_preview(app, query)
    if path == "/api/images" and method in ("GET", "HEAD"):
        return _images(app, (query.get("item") or [""])[0])
    if path == "/api/items/create" and method == "POST":
        return _create_item(app, body)
    if path.startswith("/api/item/"):
        for suffix, handler in _SOURCE_ROUTES:
            if not path.endswith(suffix):
                continue
            if method not in ("GET", "HEAD"):
                return 405, {"error": "method not allowed"}
            ref = urllib.parse.unquote(path[len("/api/item/"):-len(suffix)])
            return handler(app, ref, query)
    if path.startswith("/api/item/") and method in ("GET", "HEAD"):
        ref = urllib.parse.unquote(path[len("/api/item/"):])
        return _item_view(app, ref)
    if path in ("/api/items", "/api/images", "/api/items/create") or path.startswith("/api/item/"):
        return 405, {"error": "method not allowed"}
    return 404, {"error": "not found"}


def _items(app, query: dict[str, list[str]]) -> tuple[int, dict]:
    project = app.state.snapshot.project
    try:
        filters = filters_mod.parse_filters(project, query)
        limit = filters_mod.parse_limit(query)
    except FilterError as exc:
        return exc.status, {"error": str(exc)}
    return 200, filters_mod.items_payload(project, filters, limit)


def _find_item(project: Project, ref: str) -> tuple[Item | None, str | None]:
    """Resolve an item-view reference. Accepted spellings, in order: the
    `project.items` dict key (surrogate key, or the provisional handle of a
    keyless item — what `/api/items` rows carry as `handle`), then display id,
    then surrogate key via `item_by_ref`. A provisional handle is never a
    linkable identity, so it is deliberately looked up only here, only by
    exact dict hit, and echoed back so the UI can address the item again."""
    if not ref:
        return None, None
    item = project.items.get(ref)
    if item is not None:
        return item, ref
    item = project.item_by_ref(ref)
    if item is not None:
        return item, item.key or ref
    return None, None


def _diagnostics_for(project: Project, item: Item, handle: str) -> list[dict]:
    refs = {r for r in (item.id, item.key, handle) if r}
    out = []
    for d in project.diagnostics:
        if d.item_id and d.item_id in refs:
            out.append(
                {
                    "level": d.level,
                    "message": d.message,
                    "file": d.file,
                    "line": d.line,
                    "code": d.code,
                }
            )
    return out


def diag_dict(d: Diagnostic) -> dict:
    return {
        "level": d.level,
        "message": d.message,
        "file": d.file,
        "line": d.line,
        "code": d.code,
    }


# ------------------------------------------------------------- edit affordances

# Field types whose values are collections: the patcher replaces scalar spans
# only, so these are read-only in the form (docs/design/browser-editor.md,
# "Editing fields" -- links have their own picker, a later slice). The create
# path enforces the same rule from the one constant in serve.edit.
NON_SCALAR_FIELD_TYPES = edit_mod.NON_SCALAR_FIELD_TYPES


def _value_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return "string"


def edit_state(app, project: Project, item: Item) -> dict:
    """What the browser may change on this item, and the proof it must send
    back to change it: the content revision of the item's own source file (the
    same spelling `serve.edit.apply_edit` compares), so the form holds a
    revision per item rather than one for the whole project.

    Read-only reasons are spelled out, not implied: a sealed entry, an imported
    item, an identity field, a collection. The UI renders what is here instead
    of reimplementing the rules."""
    rel = (item.source_file or "").replace("\\", "/")
    revision = app.state.snapshot.hashes.get(rel)
    if revision is None:
        revision = edit_mod.file_revision(os.path.join(project.root, rel))

    blocked = None
    if item.external:
        blocked = "imported items are read-only in the editor"
    elif is_sealed(project, item):
        blocked = "a sealed entry is append-only: a correction is a new entry, not this edit"

    spec = project.types.get(item.type)
    fields = {}
    for name in ("id", "key", "type"):
        fields[name] = {
            "editable": False,
            "reason": "identity: id, key and type are not editable in v1",
        }
    for name, value in item.fields.items():
        if name in fields:
            continue
        if blocked:
            fields[name] = {"editable": False, "reason": blocked}
            continue
        fspec = spec.fields.get(name) if spec else None
        ftype = fspec.type if fspec else None
        if name in PROTECTED_FIELDS:
            fields[name] = {
                "editable": False,
                "reason": "identity: id and key are not editable in v1",
            }
        elif ftype in NON_SCALAR_FIELD_TYPES or isinstance(value, (list, dict)):
            fields[name] = {"editable": False, "reason": "not a scalar value: collections are not editable here"}
        else:
            control = "select" if ftype == "enum" and fspec.choices else "text"
            fields[name] = {
                "editable": True,
                "control": control,
                "choices": list(fspec.choices) if control == "select" else None,
                "required": bool(fspec.required) if fspec else False,
                "value_type": _value_type(value),
            }
    # Slice 2's link pickers: one entry per verb the item's type declares,
    # with the target types the schema allows (the UI feeds these to the
    # /api/items filter) and the targets currently written on the item, so
    # the picker can mark them and offer removal without a second request.
    link_verbs = {}
    for verb, allowed in sorted((spec.links if spec else {}).items()):
        if blocked:
            link_verbs[verb] = {"editable": False, "reason": blocked}
            continue
        link_verbs[verb] = {
            "editable": True,
            "target_types": list(allowed),
            "targets": sorted(item.links.get(verb) or []),
        }
    return {
        "file_revision": revision,
        "editable": blocked is None,
        "reason": blocked,
        "fields": fields,
        "links": link_verbs,
        "body": {"editable": blocked is None, "reason": blocked},
    }


def _item_view(app, ref: str) -> tuple[int, dict]:
    project = app.state.snapshot.project
    item, handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    cov = project.coverage.get(item.id) if item.id else None
    spec = project.types.get(item.type)
    return 200, {
        "revision": app.state.snapshot.revision,
        "handle": handle,
        "page": f"{item.slug}.html",
        "key": item.key,
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "board": item.board,
        "workspace": item.workspace,
        "tags": item_tags(item),
        "source_file": item.source_file.replace("\\", "/"),
        "source_line": item.source_line,
        "body": item.body,
        "fields": item.fields,
        "inherited_fields": sorted(item.inherited_fields),
        "external": item.external,
        "origin": item.origin,
        "append_only": bool(spec.append_only) if spec else False,
        "sealed": is_sealed(project, item),
        "links": {
            "outgoing": {v: list(t) for v, t in sorted(item.resolved_links.items())},
            "incoming": {v: list(t) for v, t in sorted(item.backlinks.items())},
        },
        "coverage": (
            None
            if cov is None
            else {
                "stage": cov.stage,
                "addressed_by": list(cov.addressed_by),
                "claimed_by": list(cov.claimed_by),
                "satisfied_by": list(cov.satisfied_by),
                "verified_by": list(cov.verified_by),
            }
        ),
        "edit": edit_state(app, project, item),
        "check": check_state(item),
        "checks": [
            {
                "value_name": c.value_name,
                "against": c.against,
                "ok": c.ok,
                "detail": c.detail,
                "actual": c.actual,
            }
            for c in item.checks
        ],
        "diagnostics": _diagnostics_for(project, item, handle),
    }


# ----------------------------------------------------------- reading source files
#
# docs/design/editor-source-picker.md §2, §5, §6, §7 -- Slice A, "the service
# reads": three GET routes, no writes. Each names one item, and the service
# authorizes the path with `citations.authorize_source_path` -- the same call
# `refdes fetch` and the source resolver make -- so the picker can never be
# authorized for a file the fetcher would refuse. They are added as routes here
# and nowhere else, which is what makes them inherit the launch-token, Host and
# Origin checks every other `/api/` request already passes: no new surface, no
# new security posture, just a new path into the same one.
#
# There is no seal or external-item gate here, and that is deliberate rather
# than forgotten (§9 Q6, recommended A): these are reads, seeing where a value
# came from is review, and the refusal that belongs to a sealed or imported
# item is Accept's -- a body write, already refused by the edit route with the
# existing reason.


def _item_sources(app, ref: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    """`GET /api/item/<ref>/sources` -- the item's own cited files a reader can
    read, each with its pin state and the values already pinned for it."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    return 200, sources_mod.files_payload(project, item)


def _source_entries(app, ref: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    """`GET /api/item/<ref>/sources/entries?path=&q=` -- the rows of one cited
    file, read live, each labelled with the value the lockfile pins beside it."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    path = (query.get("path") or [""])[0]
    if not path:
        return 400, {"error": "path is required: ?path=<a citation path this item declares>"}
    try:
        return 200, sources_mod.entries_payload(
            project, item, path, (query.get("q") or [""])[0]
        )
    except sources_mod.SourceRefusal as exc:
        return _refused(exc)


def _source_propose(app, ref: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    """`GET /api/item/<ref>/sources/propose?path=&key=&unit=&name=` -- the calc
    line this `(path, key, unit, name)` composes to, composed and checked here
    so the browser never assembles the text and never learns the grammar."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    for name in ("path", "key"):
        if not (query.get(name) or [""])[0]:
            what = "a citation path this item declares" if name == "path" else (
                "a key from the file's key column"
            )
            return 400, {"error": f"{name} is required: ?{name}=<{what}>"}
    try:
        return 200, sources_mod.propose_payload(
            project, item,
            path=(query.get("path") or [""])[0],
            key=(query.get("key") or [""])[0],
            unit=(query.get("unit") or [""])[0],
            name=(query.get("name") or [""])[0],
        )
    except sources_mod.SourceRefusal as exc:
        return _refused(exc)


def _refused(exc: sources_mod.SourceRefusal) -> tuple[int, dict]:
    """A read the authorizer, the registry or the row itself refused. 422 with
    the reason verbatim, in the edit route's `refused` vocabulary, because that
    is the shape the browser already knows how to read off an authoring
    outcome -- the request was well-formed; what it asked for is not this
    item's to read."""
    return 422, {"kind": "refused", "ok": False, "error": str(exc), "reason": str(exc)}


# Longest suffix first: `/sources` is a suffix of the other two, and a plain
# `endswith("/sources")` would swallow both.
_SOURCE_ROUTES = (
    ("/sources/entries", _source_entries),
    ("/sources/propose", _source_propose),
    ("/sources", _item_sources),
)


# ------------------------------------------------------------------ the write


def _apply_edit(app, ref: str, body) -> tuple[int, dict]:
    """`POST /api/item/<ref>/edit` -- the HTTP face of `serve.edit.apply_edit`.

    The service decides everything (revision check, seal check, patcher, delta
    gate, atomic write); this only turns its four results into status codes:
    Applied 200, Conflict 409 (with the current span text and the diff),
    Refused 422 (a reason), Invalid 422 (the blocking diagnostics). A malformed
    request -- not an authoring outcome -- is a 400. `who` is `local`: today
    every caller is the same local author, and the seam lives in the service."""
    if getattr(app, "read_only", False):
        return 403, {"kind": "refused", "error": "this server was started with --no-write: edits are disabled"}
    if not isinstance(body, dict):
        return 400, {"error": "expected a JSON object"}

    expected = body.get("expected_revision")
    if not isinstance(expected, str) or not expected:
        return 400, {"error": "expected_revision is required: the file_revision from GET /api/item/<ref>"}

    op_name = body.get("op")
    if op_name == "set_field":
        field = body.get("field")
        value = body.get("value")
        if not isinstance(field, str) or not field:
            return 400, {"error": "set_field needs a field name"}
        if value is None or isinstance(value, (dict, list)):
            return 400, {"error": "set_field takes a scalar value: collections and null are not editable"}
        op = SetField(field, value)
    elif op_name == "set_body":
        text = body.get("text")
        if not isinstance(text, str):
            return 400, {"error": "set_body needs a text string"}
        op = SetBody(text)
    elif op_name in ("add_link", "remove_link"):
        verb = body.get("verb")
        target = body.get("target")
        if not isinstance(verb, str) or not verb:
            return 400, {"error": f"{op_name} needs a verb"}
        if not isinstance(target, str) or not target:
            return 400, {"error": f"{op_name} needs a target: an item handle, display id or key"}
        op = AddLink(verb, target) if op_name == "add_link" else RemoveLink(verb, target)
    else:
        return 400, {"error": "op must be 'set_field', 'set_body', 'add_link' or 'remove_link'"}

    project = app.state.snapshot.project
    result = edit_mod.apply_edit(
        project.root,
        edit_mod.EditRequest(who="local", ref=ref, op=op, expected_revision=expected),
    )

    def shown(path):
        """Project-relative when possible: the browser has no use for a server
        filesystem root, and a path it cannot read is a path it cannot leak."""
        if not path:
            return None
        text = os.path.relpath(path, project.root).replace("\\", "/")
        return path.replace("\\", "/") if text.startswith("..") else text

    if isinstance(result, edit_mod.Applied):
        # The design's "full rebuild after save": the model and the preview
        # come back from the same refresh the file watcher uses, so the next
        # GET and the rendered site both show the saved bytes.
        app.state.refresh()
        return 200, {
            "kind": "applied",
            "ok": True,
            "message": result.message,
            "path": shown(result.path),
            "revision": result.revision,
            "describe": result.plan.describe(),
            "diagnostics": [diag_dict(d) for d in result.diagnostics if d.level != CHECK_VIOLATION],
        }
    if isinstance(result, edit_mod.Conflict):
        return 409, {
            "kind": "conflict",
            "ok": False,
            "message": result.message,
            "path": shown(result.path),
            "expected_revision": result.expected_revision,
            "current_revision": result.current_revision,
            "current_text": result.current_text,
            "diff": result.diff,
        }
    if isinstance(result, edit_mod.Invalid):
        return 422, {
            "kind": "invalid",
            "ok": False,
            "message": result.message,
            "reason": result.message,
            "path": shown(result.path),
            "diagnostics": [diag_dict(d) for d in result.diagnostics],
        }
    return 422, {
        "kind": "refused",
        "ok": False,
        "message": result.message,
        "reason": result.reason,
        "path": shown(result.path),
    }


# ---------------------------------------------------------------- creation


def _create_schema(app) -> tuple[int, dict]:
    """What a New Item form needs, answered from the resolved schema: every
    declared type with its prefix, whether it is append-only (the amend
    flow), whether it declares `amends`, its fields with control-relevant
    metadata, and the project's boards/workspaces/date_format. The client
    interprets nothing it is not told here."""
    project = app.state.snapshot.project
    types = []
    for name, spec in sorted(project.types.items()):
        fields = {}
        for fname, fspec in spec.fields.items():
            fields[fname] = {
                "type": fspec.type,
                "required": bool(fspec.required),
                "choices": list(fspec.choices) if fspec.type == "enum" else None,
                "default": fspec.default,
                "creatable": fspec.type not in NON_SCALAR_FIELD_TYPES,
            }
        types.append(
            {
                "name": name,
                "prefix": spec.prefix,
                "label": spec.label,
                "append_only": bool(spec.append_only),
                "amends": "amends" in spec.links,
                "fields": fields,
            }
        )
    return 200, {
        "types": types,
        "boards": list(project.boards),
        "workspaces": list(project.workspaces),
        "date_format": project.date_format,
    }


def _create_preview(app, query: dict[str, list[str]]) -> tuple[int, dict]:
    """The id that WOULD be minted and the destination that WOULD be used,
    planned purely (serve.edit.preview_creation) -- nothing is reserved."""
    type_name = (query.get("type") or [""])[0]
    if not type_name:
        return 400, {"error": "type is required: ?type=<declared type>"}
    board = (query.get("board") or [""])[0] or None
    explicit = (query.get("id") or [""])[0] or None
    destination = (query.get("destination") or [""])[0] or None
    return 200, edit_mod.preview_creation(
        app.state.snapshot.project,
        type_name,
        explicit_id=explicit,
        board=board,
        destination=destination,
    )


def _create_item(app, body) -> tuple[int, dict]:
    """`POST /api/items/create` -- the HTTP face of `serve.edit.create_item`.
    Same result-to-status mapping as the edit route: Created 200, Refused and
    Invalid 422, malformed request 400."""
    if getattr(app, "read_only", False):
        return 403, {
            "kind": "refused",
            "error": "this server was started with --no-write: creation is disabled",
        }
    if not isinstance(body, dict):
        return 400, {"error": "expected a JSON object"}
    type_name = body.get("type")
    if not isinstance(type_name, str) or not type_name:
        return 400, {"error": "type is required: a declared item type"}
    fields = body.get("fields", {})
    if not isinstance(fields, dict):
        return 400, {"error": "fields must be an object"}
    for key_name in ("id", "destination", "amends"):
        value = body.get(key_name)
        if value is not None and not isinstance(value, str):
            return 400, {"error": f"{key_name} must be a string when given"}

    project = app.state.snapshot.project
    result = edit_mod.create_item(
        project.root,
        edit_mod.CreateRequest(
            who="local",
            type=type_name,
            fields=fields,
            id=body.get("id"),
            destination=body.get("destination"),
            amends=body.get("amends"),
        ),
    )

    def shown(path):
        if not path:
            return None
        text = os.path.relpath(path, project.root).replace("\\", "/")
        return path.replace("\\", "/") if text.startswith("..") else text

    if isinstance(result, edit_mod.Created):
        app.state.refresh()
        return 200, {
            "kind": "created",
            "ok": True,
            "message": result.message,
            "id": result.item_id,
            "key": result.key,
            "type": result.type,
            "path": shown(result.path),
            "revision": result.revision,
        }
    if isinstance(result, edit_mod.Invalid):
        return 422, {
            "kind": "invalid",
            "ok": False,
            "message": result.message,
            "reason": result.message,
            "path": shown(result.path),
            "diagnostics": [diag_dict(d) for d in result.diagnostics],
        }
    return 422, {
        "kind": "refused",
        "ok": False,
        "message": result.message,
        "reason": result.reason,
        "path": shown(result.path),
    }


# ---------------------------------------------------------------- image picker
#
# docs/design/editor-image-upload.md §17, Phase 0: list the images the project
# already has so the author can reference one, and nothing else. Read-only --
# no upload, no write endpoint, no bytes accepted -- and the reference the
# author picks travels out through the ordinary `set_body` save like any other
# body edit (the client inserts it into the draft; design §7).
#
# What the list can name is decided by the build, not here. `state.asset_files`
# is the walk `project_inputs` already watches and `build.collect_static_assets`
# already publishes: every file under a declared `site.assets:` directory, with
# no reference needed, because a bare `<img src>` is resolved by searching those
# directories (`build._search_image_src`). So a file this endpoint can offer is a
# file the build can already resolve, and one it cannot offer was never
# reachable by a reference in the first place.
#
# The bytes come from the preview surface rather than a new read endpoint: a
# file under a declared asset directory is identity-mapped in `project.assets`
# (`collect_static_assets`), so the build's own answer for it is `assets/<rel>`
# in the current generation, and the existing `/preview/` route serves that with
# `PreviewManager.open_file`'s real-path containment, the session cookie,
# `nosniff`, and `PREVIEW_CSP` (docs/design/browser-editor.md, Security: no
# generic file-read endpoint; design §16.10, whose "unnecessary: the preview
# generation already serves the asset" holds here too). The client names no
# path, so there is no client path to confine.

# The image file types the picker offers. This is a *display* filter on the walk
# above, not a resolution rule: the build resolves a src by exact filename with
# no extension test at all (`build._process_images`), so a file outside this set
# is still perfectly valid to reference by hand -- the picker just does not
# volunteer it. SVG is listed, not refused, for the same reason: refusing it is
# an upload-side policy decision (design §6, about bytes arriving from a
# browser), and this endpoint accepts no bytes and reads none.
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff", ".avif", ".ico"}
)


def image_alt(name: str) -> str:
    """Default alt text for a picked image: the filename's stem, never empty
    (design §7 -- an empty `alt` is a silent accessibility failure). Brackets
    are escaped because the stem lands inside `![...]`."""
    stem = name.rsplit(".", 1)[0] if "." in name.lstrip(".") else name
    return (stem or name).replace("[", "\\[").replace("]", "\\]").replace("\n", " ").strip() or name


def image_markdown(src: str, alt: str) -> str:
    """The exact `![alt](src)` line the client inserts, composed here so the
    browser never builds a path spelling of its own. A destination containing a
    space or a parenthesis takes markdown's `<...>` form, which is what makes a
    file called `thermal curve.png` insertable at all."""
    target = f"<{src}>" if any(ch in src for ch in " ()<>") else src
    return f"![{alt}]({target})"


def referenceable(src: str) -> bool:
    """Whether the build could resolve `src` exactly as written.

    Markdown's renderer percent-encodes a destination it does not consider
    URL-safe, and the build resolves the *rendered* `src` against the
    filesystem without decoding it (`build._process_images` walks the HTML), so
    a file whose name carries a space or a non-ASCII character cannot be
    referenced by any spelling: `![a](<figures/thermal curve.png>)` renders a
    src of `figures/thermal%20curve.png` and the lookup misses. Rather than
    hand the author a reference the save would refuse, the picker reports the
    file and says why it is not offerable.

    `quote(src) == src` is the conservative direction: the renderer's encoder
    is narrower than `quote`, so a name refused here can still work when typed
    by hand (`a(b).png`, `a#b.png`), while a name accepted here is one no
    encoder rewrites."""
    return urllib.parse.quote(src, safe="/") == src


def _image_row(project: Project, item: Item, full_path: str) -> dict | None:
    """One row of `GET /api/images`, or None when the file is not an image the
    picker offers. `rel` is the build's own project-relative spelling and `src`
    is that path as this item's source file must spell it -- the relative lookup
    that runs first and always wins (docs/markdown.md), so the inserted text
    resolves to this exact file whatever else shares the leaf name."""
    rel = os.path.relpath(full_path, project.root).replace("\\", "/")
    name = rel.rpartition("/")[2]
    if os.path.splitext(name)[1].lower() not in IMAGE_SUFFIXES:
        return None
    source_dir = os.path.join(project.root, os.path.dirname(item.source_file.replace("\\", "/")))
    src = os.path.relpath(os.path.join(project.root, rel), source_dir).replace("\\", "/")
    try:
        size = os.path.getsize(full_path)
    except OSError:
        size = 0
    alt = image_alt(name)
    row = {
        "rel": rel,
        "name": name,
        "alt": alt,
        "bytes": size,
        "src": src,
        "insertable": referenceable(src),
    }
    if row["insertable"]:
        row["markdown"] = image_markdown(src, alt)
    else:
        row["note"] = (
            "this filename cannot be referenced as written: markdown "
            "percent-encodes it and the build resolves the encoded form. It "
            "needs renaming before any body can point at it."
        )
    dest = project.assets.get(rel)
    if dest:
        # The build's own answer, not a guess: a declared asset-directory file
        # is identity-mapped, so this is the file the preview already serves.
        row["thumb"] = "/preview/assets/" + urllib.parse.quote(dest)
    return row


def _images(app, ref: str) -> tuple[int, dict]:
    """`GET /api/images?item=<handle>` -- the picker's list.

    Item-scoped because the answer depends on the item: a src is relative to
    *that* item's source file, and only the item's own draft can receive the
    insertion. An unknown item 404s like `_item_view`; an item with no source
    file has no base to be relative to and says so rather than guessing a root."""
    project = app.state.snapshot.project
    item, _handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    if not item.source_file:
        return 400, {"error": "this item has no source file, so no relative path to offer"}
    rows = [
        row
        for row in (_image_row(project, item, path) for path in state_mod.asset_files(project))
        if row is not None
    ]
    rows.sort(key=lambda row: row["rel"])
    return 200, {
        "item": item.id or ref,
        "source_file": item.source_file.replace("\\", "/"),
        "asset_dirs": list(project.asset_dirs),
        "images": rows,
        "total": len(rows),
    }
