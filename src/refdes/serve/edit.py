"""The editor's one write path: `apply_edit(project_root, request)`.

docs/design/browser-editor.md, "Permissions are out of scope for v1 -- with one
seam": one entry point applies every mutation, every operation carries who
asked, and a refusal is a first-class result. This module is that entry point.
It has no HTTP and no UI: the server slice wraps these results in status codes,
and a refusal here is a value the caller renders, never an exception it catches.

An outcome is one of four dataclasses -- `Applied`, `Conflict`, `Refused`,
`Invalid` -- each carrying `ok` and a human-readable `message`, so a caller can
branch on type and still log any result uniformly.

What each save does, in order (the design's transaction model, minus the
journal, which is a later slice):

1. take the per-project write lock, so two applies in one process cannot
   interleave;
2. resolve the item and its file through the side-effect-free load
   (`loader.load_tree`, read-only), which is also where the before-diagnostics
   come from -- its `build()` deferred, because the only thing that reads the
   before snapshot's build output is step 6's gate, and only when the candidate
   has an error to compare (`_load_before`);
3. compare the file's current content revision with the `expected_revision`
   the client saw. A mismatch is a `Conflict`: the current span text and a
   unified diff of the draft against disk come back, and **nothing is merged**
   -- the design's "draft, refuse, diff -- never merge";
4. refuse a sealed item under the lock (the mutation endpoint repeats the
   check the UI cannot be trusted to make);
5. plan the edit with `patcher`, whose own fidelity proof means a `Refusal`
   here is the patcher saying "I cannot bound this edit" -- also a result;
6. run the **delta** diagnostic gate: load the whole project again with the
   candidate text as a source overlay and compare error sets -- building the
   before snapshot now, and only now, if the candidate has an error at all. Only a *newly
   introduced* error blocks, or a pre-existing error attributed to the field
   or body being edited and still present. An unrelated pre-existing error on
   an already-broken item never blocks the repair that is the reason the
   editor exists;
7. write atomically -- temp file in the same directory, flush, fsync,
   `os.replace` -- then re-read and confirm the bytes are the planned bytes.

One save writes two files. A `set_body` carrying `pin` (docs/design/
editor-source-picker.md §4 -- the editor's source-value picker accepting a
value) writes `.refdes/citations.yaml` as well as the item, because a body with
a `source()` line whose key is not pinned is an item that does not build and a
pinned key no body names is dead state in a tracked file. The lockfile lands
first, so the delta gate judges the candidate the save actually produces, and
every refusal after it restores the previous lockfile bytes. It is still one
apply-operation call and still one mutation entry point; what widened is the
request, not the number of writers.

`apply_edit` addresses an existing field, body, or link; `create_item` is
Slice 3's entry point, which does mint a key, reserve an id, and write a new
item -- inside the same lock, with the same refuse-as-a-value posture, and
with the ledger reservation and the file write committed or rolled back
together.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import tempfile
import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .. import build as build_mod
from .. import citations as citations_mod
from .. import dates, ids, keys, links, loader, patcher, scaffold, seal, textio
from ..model import (
    CHECK_VIOLATION,
    ERROR,
    NON_SCALAR_FIELD_TYPES,
    Diagnostic,
    Item,
    Project,
)
from ..parse import front_matter_defaults_block, md_front_matter_blocks, yaml_safe_load
from ..patcher import AddLink, PatchPlan, Refusal, RemoveLink, SetBody, SetField
from ..sources import PdfAnchor
from . import security
from . import sources as sources_mod

CONFIG_NAME = "refdes-project.yaml"


# ------------------------------------------------------------------- requests


@dataclass(frozen=True)
class SourcePin:
    """One source value the request asks to pin, as the client named it
    (docs/design/editor-source-picker.md §4).

    A path, a key, and the unit and name of the calc line that must be in the
    body this request saves. **No value**: the number comes from the reader
    inside the accept operation and from nowhere else (§5 -- a browser-side
    parser would be a second authority on what a CSV says, and the disagreement
    between two of them is the silent-wrong-value class this project keeps
    finding). A `value` key in the request is ignored, not trusted.

    It travels with a `set_body` op and is never an op of its own: the body and
    the pin are one fact -- a line naming an unpinned key is an item that will
    not build, and a pinned key no line names is dead state in a tracked file --
    so they commit together or not at all.
    """

    path: str
    key: str
    unit: str = ""
    name: str = ""
    # PDF session coordinates, re-read to derive durable quoted-row provenance.
    page: str = ""
    row: str = ""
    token: str = ""
    sha256: str = ""


@dataclass(frozen=True)
class EditRequest:
    """One authoring intent, as the client presents it.

    `who` is the permissions seam: today every caller is the same local author
    and nothing reads it, but the field exists before the feature does, so a
    later identity check is one more line in one place rather than an audit of
    callers that might have forgotten to pass it.
    """

    who: str
    ref: str
    op: Any  # patcher.SetField | patcher.SetBody | patcher.AddLink | patcher.RemoveLink
    expected_revision: str  # content revision of the target FILE, as the client saw it
    # Source values to pin alongside this edit (`SourcePin`). Only a `set_body`
    # may carry them, because only a body can name them; the write is then a
    # transaction over two files -- the item and `.refdes/citations.yaml` --
    # inside this one lock. Empty for every edit that is not an accept.
    pins: tuple = ()


# -------------------------------------------------------------------- results


@dataclass(frozen=True)
class Applied:
    """The edit is on disk. `revision` is the target file's new content revision."""

    who: str
    ref: str
    path: str
    revision: str
    plan: PatchPlan
    diagnostics: tuple = ()
    # What an accept pinned, as `{path, key, reader, value}` -- the value the
    # reader read. Empty for an ordinary save, and never a value the client sent.
    pinned: tuple = ()
    ok: bool = True

    @property
    def message(self) -> str:
        return f"applied: {self.plan.describe()}"


@dataclass(frozen=True)
class Conflict:
    """Disk moved since the client read it. Never merged, never written.

    `current_text` is the text the item span holds on disk right now, and
    `diff` is a unified diff of the client's draft against that text -- the
    two halves the design's conflict screen shows side by side.
    """

    who: str
    ref: str
    path: str
    expected_revision: str
    current_revision: str
    current_text: str | None
    diff: str
    ok: bool = False
    kind: str = "conflict"

    @property
    def message(self) -> str:
        return (
            f"conflict: {self.path} changed since this edit was planned "
            f"(expected {self.expected_revision[:12]}, found {self.current_revision[:12]})"
        )


@dataclass(frozen=True)
class Refused:
    """The operation is not permitted or cannot be made faithfully. Nothing changed."""

    who: str
    ref: str
    reason: str
    path: str | None = None
    ok: bool = False
    kind: str = "refused"

    @property
    def message(self) -> str:
        return f"refused: {self.reason}"


@dataclass(frozen=True)
class Invalid:
    """The candidate project would carry an error the gate blocks. Nothing changed."""

    who: str
    ref: str
    diagnostics: tuple
    path: str | None = None
    ok: bool = False
    kind: str = "invalid"

    @property
    def message(self) -> str:
        first = self.diagnostics[0].message if self.diagnostics else "no diagnostic"
        return f"blocked: the edit would leave {len(self.diagnostics)} error(s): {first}"


# --------------------------------------------------------- per-project locking

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def write_lock_for(project_root: str) -> threading.Lock:
    """The one write lock for one project root, shared by every apply in this
    process. The design's posture is that the lock stops *this* server from
    interleaving saves; `_disk_write_lock` serialises the final revision check
    and replacement across server processes."""
    key = os.path.normcase(os.path.abspath(project_root))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def file_revision(path: str) -> str:
    """A file's content revision: sha256 of its bytes, "" when it does not
    exist -- the same spelling `serve.state.content_hashes` uses, so a client
    can hold either and compare."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


@contextmanager
def _disk_write_lock(root: str):
    """Use the same project lock as CLI writers."""
    from ..write_lock import project_write_lock

    with project_write_lock(root):
        yield


# ---------------------------------------------------------------- the entry point


def apply_edit(project_root: str, request: EditRequest):
    """Apply one edit request to the project at `project_root`.

    Returns `Applied` | `Conflict` | `Refused` | `Invalid`. Authoring outcomes
    are values; only a genuinely unexpected internal fault raises, and the
    write path itself restores the original bytes if a replacement half-fails.
    """
    root = os.path.abspath(project_root)
    config = os.path.join(root, CONFIG_NAME)
    with write_lock_for(root):
        return _apply_locked(config, request)


def _load_before(config: str, *, full: bool) -> tuple[Project, bool]:
    """The project as it stands on disk, with `build()` deferred.

    `loader.load_readonly` is `load_tree` + `build`, and everything the before
    snapshot is read for *before* the candidate is loaded -- resolving the item,
    its file and its revision, the imported and sealed refusals, the link-target
    resolution -- is config, parse and import state, which `load_tree`
    produces in full. (`seal.is_sealed` is the instructive one: it walks every
    declared board precisely because board resolution has not happened yet in
    the load path it was written for.) Build output is read off the before
    snapshot in two places only: the accept's re-validation, which reads the
    item's evaluated calc lines, and the delta gate's error set.

    So `full` -- an accept -- keeps the eager `load_readonly`, and an ordinary
    save takes the unbuilt snapshot and gets its build at the gate, if the gate
    needs one at all. The accept keeps it eager for a second reason too:
    `_accept_pins` writes `.refdes/citations.yaml`, which a build reads, so a
    build of `before` deferred past that write would not be the same build.

    `create_item` does not use this at all -- see the note in `_create_locked`
    on the board it suggests a destination from.

    Returns `(project, built)`; `built` says whether the build already ran.
    A build that this defers still has to be able to fail the same way it did
    inside `load_readonly` -- see `_build_before`.
    """
    if full:
        return loader.load_readonly(config), True
    project, _stale = loader.load_tree(config, require_ids=False, write=False)
    return project, False


def _build_before(project: Project) -> str | None:
    """Run the before snapshot's deferred build; return None, or the reason.

    `loader.load_readonly` built the snapshot it was handed, and the call that
    used it sat in a `try/except Exception` that turned any failure into
    `Refused("the project did not load: ...")`. Deferring the build past that
    handler would let a project that parses but will not build -- a half-written
    `.refdes/citations.yaml`, a history event that is not YAML, an image file
    the renderer cannot open -- raise out of `apply_edit` instead, and the HTTP
    face has no catch-all: the connection would close with no response at all.
    Authoring outcomes are values, so it comes back as the same refusal, in the
    same words.
    """
    try:
        build_mod.build(project, seal_write=False, reseal=False)
    except Exception as exc:  # noqa: BLE001 - same posture as the load above
        return f"the project did not load: {type(exc).__name__}: {exc}"
    return None


def _apply_locked(config: str, request: EditRequest):
    who, ref = request.who, request.ref
    try:
        before, before_built = _load_before(config, full=bool(request.pins))
    except Exception as exc:  # noqa: BLE001 - a project that will not load is a result
        return Refused(who, ref, f"the project did not load: {type(exc).__name__}: {exc}")

    item = _find_item(before, ref)
    if item is None:
        return Refused(who, ref, f"no item {ref!r} in this project")
    if item.external:
        return Refused(who, ref, f"{ref} is an imported item; imports are read-only here")

    path = _item_path(before, item)
    if path is None:
        return Refused(who, ref, f"{ref} resolves outside the project; nothing was written")

    current_revision = file_revision(path)
    if current_revision != request.expected_revision:
        return _conflict(who, ref, path, before, request, current_revision)

    if seal.is_sealed(before, item):
        return Refused(
            who,
            ref,
            f"{ref} is a sealed append-only entry: an edit means appending a new entry "
            "with `amends:`, not rewriting this one",
            path=path,
        )

    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except OSError as exc:
        return Refused(who, ref, f"could not read {path}: {exc}", path=path)
    except UnicodeDecodeError:
        return Refused(who, ref, f"{path} is not UTF-8 text", path=path)

    op = request.op
    if isinstance(op, (AddLink, RemoveLink)):
        # Resolve the target under the write lock, against the same snapshot
        # the patch will be planned against: the composite is decided here,
        # never by the browser, and a target that cannot be named faithfully
        # is a refusal before a single byte is planned (Slice 2).
        op, reason = _resolve_link_op(before, item, op)
        if reason is not None:
            return Refused(who, ref, reason, path=path)

    plan = patcher.plan_patch(text, ref, op, path=path)
    if isinstance(plan, Refusal):
        return Refused(who, ref, plan.reason, path=path)
    new_text = patcher.apply_patch(text, plan)

    # An accept: the body op plus the keys to pin. One operation over two files
    # (docs/design/editor-source-picker.md §4), and the only one here that is.
    # It runs before the candidate load rather than after it because the
    # candidate has to resolve the new `source()` line against the lockfile that
    # is about to exist -- the loader's overlay covers item source files and
    # nothing else, so the pin is real on disk by then and every later failure
    # below has to put it back.
    new_body = op.text if isinstance(op, SetBody) else None
    accept, reason = _accept_pins(before, item, request.pins, new_body)
    if reason is not None:
        return Refused(who, ref, reason, path=path)

    try:
        after = loader.load_readonly(config, overlay={path: new_text})
    except Exception as exc:  # noqa: BLE001 - a candidate that will not load is a result
        _undo_accept(accept)
        # The before snapshot's build is deferred to below this point, so a
        # project that will not build at all now fails here first -- and what it
        # fails on has nothing to do with the edit. Ask the unedited tree
        # whether it builds, and if it does not, say that instead: one extra
        # build, on a path that is already refusing.
        if not before_built:
            failure = _build_before(before)
            if failure is not None:
                return Refused(who, ref, failure)
        return Refused(
            who, ref, f"the edited project did not load: {type(exc).__name__}: {exc}", path=path
        )

    # The gate compares the candidate's error set against the before snapshot's,
    # and only ever reads that set off `before`. With nothing to compare it
    # reads `len(before.local_items)` and nothing else, so the before build --
    # the other half of what a `load_readonly` costs -- runs here rather than
    # at the top of the function, and not at all on a clean candidate.
    if not before_built and _has_gate_errors(after):
        failure = _build_before(before)
        if failure is not None:
            return Refused(who, ref, failure)

    blocking = _blocking_diagnostics(before, after, item, request.op)
    if blocking:
        _undo_accept(accept)
        return Invalid(who, ref, tuple(blocking), path=path)

    # The candidate gate can take seconds. Another server may have saved since
    # the first check, so check again under the cross-process write lock.
    try:
        with _disk_write_lock(before.root):
            current_revision = file_revision(path)
            if current_revision != request.expected_revision:
                _undo_accept(accept)
                return _conflict(who, ref, path, before, request, current_revision)
            failure = _atomic_replace(path, new_text.encode("utf-8"))
    except OSError as exc:
        _undo_accept(accept)
        return Refused(who, ref, f"could not lock {path} for writing: {exc}", path=path)
    if failure is not None:
        _undo_accept(accept)
        return Refused(who, ref, failure, path=path)

    return Applied(
        who=who,
        ref=ref,
        path=path,
        revision=file_revision(path),
        plan=plan,
        diagnostics=tuple(after.diagnostics),
        pinned=() if accept is None else accept.pinned,
    )


# ------------------------------------------------------------------- accepting
#
# docs/design/editor-source-picker.md §4. A picked source value is two writes --
# a line in an item's body and a pin in `.refdes/citations.yaml` -- that are
# meaningful only together, so they are one operation: neither lands without the
# other, and a refusal anywhere leaves both files exactly as they were.


@dataclass
class _LockfileWrite:
    """One lockfile write, with what it replaced.

    `previous` is None when the project had no lockfile at all, which is a
    different rollback from a restore: an accept of an unpinned citation into a
    project nobody has ever fetched creates the file, and a refusal has to leave
    a project with no lockfile rather than one holding an empty `citations: {}`.
    """

    path: str
    previous: bytes | None
    staged: bytes
    written: bool = False

    def rollback(self) -> None:
        if not self.written:
            return
        self.written = False
        # Compare before restoring: the accept's whole-file write is not inside
        # the cross-process lock's check-and-replace section (the candidate
        # gate it precedes can take seconds), so a cooperating writer may have
        # replaced this file between our write and this rollback. Our `previous`
        # is then stale -- restoring it would delete a save that already
        # landed, whose body names a pin that would no longer exist. Leaving
        # our pin in the file another writer replaced is the failure mode the
        # design names as inert (docs/design/editor-source-picker.md §4);
        # destroying a landed writer's state is not.
        try:
            with open(self.path, "rb") as fh:
                current = fh.read()
        except OSError:
            current = None
        if current != self.staged:
            return
        _rollback(self.path, self.previous)


@dataclass
class _Acceptance:
    """What an accept decided, before the body it belongs to has landed.

    `lock` is what to put back if anything past here fails; `pinned` is what the
    reader read, which is the only thing about the pick worth telling the caller
    back. The composed line is deliberately not carried: the author already has
    it -- it is the text in the body being saved -- and a second copy of it here
    would be a second thing to keep in agreement.
    """

    lock: _LockfileWrite | None
    pinned: tuple = ()


def _undo_accept(accept: _Acceptance | None) -> None:
    """§4's step 6: the lockfile goes back before the refusal is returned.

    Bytes restored from memory, not a transaction journal -- the design says so
    out loud rather than papering over it: the window is one `os.replace` wide,
    and the failure mode if the process dies inside it is a lockfile pinning a
    key no item names, which is inert, visible in `git status`, and cleaned by
    the next `refdes fetch`.
    """
    if accept is not None:
        accept.lock.rollback()


def _accept_pins(
    before: Project, item: Item, pins: tuple, new_body: str | None
) -> tuple[_Acceptance | None, str | None]:
    """Re-validate the picks, extract their values, and write the lockfile.

    Returns `(acceptance, None)` or `(None, reason)`; a reason means nothing was
    written anywhere. Called under the write lock, after the body patch is
    planned and before the candidate project is loaded.

    The order is the design's, and each step is the same code another command
    already runs:

    1. `sources.accept_plan` -- Slice A's `propose_payload` again, against the
       server's copy of the item, so authorization, the key still existing and
       still selectable, the name, the unit and the composed line are one rule
       with one spelling rather than a second copy of them; plus the check only
       an accept can make, that the body being saved names the pair.
    2. `citations.stage_source_pins` -- the extraction and the record, under
       fetch's non-`--update` policy, in the shape fetch writes.
    3. the write, atomic and whole-file, in the same bytes `save_lockfile`
       would have produced.
    """
    if not pins:
        return None, None
    if new_body is None:
        return None, (
            "a source value is pinned by the body that names it: pin is only "
            "accepted on a set_body edit"
        )
    try:
        plans = [
            sources_mod.accept_plan(
                before, item, path=p.path, key=p.key, unit=p.unit, name=p.name,
                body=new_body, page=p.page, row=p.row, token=p.token, sha256=p.sha256,
            )
            for p in pins
        ]
    except sources_mod.SourceRefusal as exc:
        return None, str(exc)

    # Fresh from disk, not the snapshot's copy: under this lock, the file is the
    # state, and a pin written by a fetch since the snapshot was built belongs
    # in what we write back.
    #
    # Strictly `load_lockfile`, and a LockfileError becomes this function's
    # ordinary refusal reason rather than an exception: this is the second
    # writer of the lockfile (step 3 of the sequence below), and it writes the
    # file whole from the records it read. A lockfile it could not read would
    # come back with one record -- the key being accepted -- and every other
    # pin in the project silently gone. Refusing leaves both files untouched.
    try:
        records = citations_mod.load_lockfile(before)
    except citations_mod.LockfileError as exc:
        return None, str(exc)
    anchors = {}
    digests = {}
    for plan in plans:
        if plan.get("reader") != "pdf":
            continue
        entry = plan["entry"]
        pair = (plan["path"], plan["key"])
        anchor = PdfAnchor(
            entry["page"], entry["quoted"], entry["numeric_index"],
        )
        if pair in anchors and anchors[pair] != anchor:
            return None, f"{pair[0]}: key {pair[1]!r} names conflicting PDF candidates"
        anchors[pair] = anchor
        digests[plan["path"]] = plan["sha256"]
    errors, pinned = citations_mod.stage_source_pins(
        before, records, [(p["path"], p["key"]) for p in plans],
        anchors=anchors, digests=digests,
    )
    if errors:
        return None, "; ".join(errors)

    lock_path = citations_mod.lockfile_path(before)
    try:
        with open(lock_path, "rb") as fh:
            previous = fh.read()
    except OSError:
        previous = None
    staged = citations_mod.lockfile_text(records).encode("utf-8")
    lock = _LockfileWrite(path=lock_path, previous=previous, staged=staged)
    # Nothing changed -- re-accepting a key that is already pinned from these
    # same bytes -- then nothing is written: a save that pins nothing new leaves
    # the lockfile's mtime alone, and has no rollback to perform.
    if staged != previous:
        failure = (
            _atomic_replace(lock_path, staged)
            if previous is not None
            else _atomic_create(lock_path, staged)
        )
        if failure is not None:
            return None, failure
        lock.written = True
    return _Acceptance(lock=lock, pinned=tuple(pinned)), None


# ------------------------------------------------------------------ resolution


def _find_item(project: Project, ref: str) -> Item | None:
    """The same three spellings the read API accepts: the `project.items` dict
    key (a surrogate key, or a keyless item's provisional handle), then the
    display id, then the key via `item_by_ref`."""
    if not ref:
        return None
    item = project.items.get(ref)
    if item is not None:
        return item
    return project.item_by_ref(ref)


def _item_path(project: Project, item: Item) -> str | None:
    """The item's source file, or None when it escapes the project root.

    `item.source_file` is already root-relative, so an escape means something
    corrupted -- which is exactly why the check runs on every save rather than
    trusting the parse (the design's path-escape invariant)."""
    if not item.source_file:
        return None
    root = os.path.abspath(project.root)
    path = os.path.normpath(os.path.join(root, item.source_file.replace("/", os.sep)))
    if path != root and not path.startswith(root + os.sep):
        return None
    return path


# ------------------------------------------------------------------- conflict


def _resolve_link_op(project: Project, item: Item, op):
    """Turn a browser-side link intent into a patcher op that is safe to write.

    The verb must be declared by the item's type, and for an add the target
    must exist, be of a type the verb accepts, and carry a key: the written
    text is always the `DISPLAY-ID@key` composite `links.composite_for`
    spells, so a target with a null artifact key -- an imported item, or one
    whose key was never minted -- is refused rather than written as a bare
    id (docs/design/browser-editor.md, Slice 2). Removal needs no identity:
    the patcher matches whatever spelling is on disk by its display or key
    half, which is exactly how a dangling target should be removable.
    """
    spec = project.types.get(item.type)
    if spec is None or op.verb not in spec.links:
        declared = sorted(spec.links) if spec else []
        where = f"; {item.type} declares {', '.join(declared)}" if declared else ""
        return None, f"{item.type} does not declare the link '{op.verb}'{where}"
    if isinstance(op, RemoveLink):
        return RemoveLink(op.verb, op.target), None
    allowed = spec.links[op.verb]
    target = _find_item(project, op.target)
    if target is None:
        return None, f"no item {op.target!r} in this project to link to"
    if not project.accepts_type(target.type, allowed):
        wants = "any declared type" if not allowed else "targets of type " + ", ".join(allowed)
        return None, f"'{op.verb}' accepts {wants}; {target.id} is a {target.type}"
    composite = links.composite_for(target)
    if composite is None:
        return None, (
            f"{target.id} carries no artifact key, so no DISPLAY-ID@key composite can be "
            "written for it; linking it as a bare id would drop the identity the link is "
            "for, which the editor refuses rather than guesses"
        )
    return AddLink(op.verb, composite), None


def _conflict(who, ref, path, before, request, current_revision) -> Conflict:
    """The disk moved. Show the author their draft against the current file;
    offer nothing that merges.

    The server holds no draft text -- drafts live in the page (design,
    "Drafts: what the editor holds before it saves") -- so the draft shown is
    the current file with the requested operation applied: exactly what the
    save would have written, expressed against what is there now. When the
    current text cannot even be planned against (the item is gone, its span
    is now ambiguous), the conflict says so instead of inventing a diff.
    """
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return Conflict(who, ref, path, request.expected_revision, current_revision, None, "")

    plan = patcher.plan_patch(text, ref, request.op, path=path)
    if isinstance(plan, Refusal):
        return Conflict(who, ref, path, request.expected_revision, current_revision, None, "")
    draft = patcher.apply_patch(text, plan)
    rel = os.path.relpath(path, before.root).replace("\\", "/")
    diff = "\n".join(
        difflib.unified_diff(
            text.splitlines(),
            draft.splitlines(),
            fromfile=f"{rel} (on disk)",
            tofile=f"{rel} (your edit)",
            lineterm="",
        )
    )
    return Conflict(
        who, ref, path, request.expected_revision, current_revision, plan.original, diff
    )


# -------------------------------------------------------------- delta gate


def _diag_key(d) -> tuple:
    """A diagnostic's stable structured identity. Line numbers are excluded
    on purpose: an edit that adds a line moves every diagnostic below it, and
    a moved line is not a new error. Field-path attribution is not in the
    diagnostic model yet (the design names enriching it as a prerequisite), so
    attribution below works from the message text instead."""
    return (d.level, d.code or "", d.item_id or "", d.file or "", d.message)


def _errors(project: Project) -> dict[tuple, Any]:
    out: dict[tuple, Any] = {}
    for d in project.diagnostics:
        if d.level != "error":
            continue
        # A failing engineering check is a check failure, not source
        # corruption: shown, never a gate (design, "Diagnostic gate").
        if d.code == CHECK_VIOLATION:
            continue
        out.setdefault(_diag_key(d), d)
    return out


def _has_gate_errors(project: Project) -> bool:
    """Whether `project` carries an error the delta gate would compare --
    `_errors`' own filter as a predicate, including its exclusion of failing
    engineering checks. The gate iterates the candidate's error set and looks
    each one up in the before snapshot's, so a candidate with no such error
    never reads the before snapshot's diagnostics, and the before snapshot
    needs no build to answer for it."""
    return any(
        d.level == "error" and d.code != CHECK_VIOLATION for d in project.diagnostics
    )


def _attributed(d, item: Item, op: Any) -> bool:
    """Whether a pre-existing error on the edited item belongs to the field or
    body this edit touches."""
    refs = {r for r in (item.id, item.key) if r}
    if not d.item_id or d.item_id not in refs:
        return False
    if isinstance(op, (AddLink, RemoveLink)):
        return d.message.startswith(f"{op.verb}:") or f"'{op.verb}'" in d.message
    if isinstance(op, SetField):
        name = op.name
        return d.message.startswith(f"{name}:") or f"'{name}'" in d.message
    if isinstance(op, SetBody):
        if "body" in d.message.lower():
            return True
        # A calc/body diagnostic carries the body's own source line.
        return bool(d.line and item.body_line and d.line >= item.body_line)
    return False


def _blocking_diagnostics(before: Project, after: Project, item: Item, op: Any) -> list:
    before_errors = _errors(before)
    after_errors = _errors(after)

    # Structural invariant first, independent of any diagnostic diff: an edit
    # to one existing item must not change how many items the project has.
    before_count = len(before.local_items)
    after_count = len(after.local_items)
    if before_count != after_count:
        return [
            d
            for d in after.diagnostics
            if d.level == "error"
        ] or [
            _synthetic_error(
                item,
                f"the edit changed the number of items from {before_count} to {after_count}",
            )
        ]

    blocking = [d for key, d in after_errors.items() if key not in before_errors]
    blocking += [
        d for key, d in after_errors.items() if key in before_errors and _attributed(d, item, op)
    ]
    return blocking


def _synthetic_error(item: Item, message: str) -> Diagnostic:
    return Diagnostic(
        ERROR, message, file=item.source_file, line=item.source_line, item_id=item.id
    )


# ---------------------------------------------------------------- atomic write


def _atomic_replace(path: str, payload: bytes) -> str | None:
    """Write `payload` to `path` atomically; return None on success, a reason
    on failure. A failed replacement leaves the original bytes in place: the
    temp file is discarded, and if the destination was somehow replaced and
    the re-read disagrees, the original bytes are put back."""
    directory = os.path.dirname(path)
    tmp = None
    try:
        with open(path, "rb") as fh:
            original = fh.read()
    except OSError as exc:
        return f"could not read {path} before writing: {exc}"

    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.refdes-tmp-", dir=directory)
        with os.fdopen(fd, "wb") as fh:
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        if tmp is not None:
            _discard_tmp(tmp)
        return f"the write failed ({exc}); {path} still holds its original bytes"

    try:
        with open(path, "rb") as fh:
            written = fh.read()
    except OSError as exc:
        _restore(path, original)
        return f"could not re-read {path} after the write: {exc}"
    if written != payload:
        _restore(path, original)
        return f"the bytes on disk after the write are not the bytes planned; {path} was restored"
    return None


def _discard_tmp(tmp: str) -> None:
    try:
        os.unlink(tmp)
    except OSError:
        pass


def _restore(path: str, original: bytes) -> None:
    try:
        with open(path, "wb") as fh:
            fh.write(original)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:  # nothing further to do; the next load reports what it sees
        pass


# ================================================================== creation
#
# docs/design/browser-editor.md, "Slice 3 -- creation". Identity comes from
# the modules that own it and nowhere else: the id is planned by
# `ids.plan_new_id` (pure) and reserved by `ids.reserve_id`, the key is
# minted by `keys.mint`, and every link is spelled by `links.composite_for`.
# The ledger reservation runs only after the file write succeeded, and any
# failure after the write rolls the file back -- a failed creation burns
# nothing. Destinations are suggested but always overridable (Decisions,
# "Creation destination: suggest plus override"); the three supported shapes
# are append to an existing YAML list file, append to an existing
# multi-item Markdown file, and create a new single-item Markdown file.

# Field types whose values are collections: creation writes scalar fields
# only; a collection is edited after the item exists (same rule the edit
# form enforces). The set itself lives in model.py, because the loader
# refuses the same scalar on the way in and the two must not drift.
# `NON_SCALAR_FIELD_TYPES` above is imported, not defined here, so
# `edit.NON_SCALAR_FIELD_TYPES` still resolves for anything that has always
# read it from this module.


@dataclass(frozen=True)
class CreateRequest:
    """One creation intent. `fields` maps declared field names (plus
    `board`/`workspace`) to scalar values; `id` is an optional explicit
    override -- omitted means "next free"; `destination` is a
    project-relative path under `items/`, omitted means "suggested";
    `amends` names a sealed log entry this new entry corrects -- the sealed
    entry itself is never touched, the correction is pure creation with an
    `amends:` composite (docs/design/living-notes.md, "corrections are new
    entries"). `links` maps a declared link verb to the one or more targets
    it should carry at creation -- the generalisation of `amends`, which is
    the same mechanism with the verb spelled for it (Slice 2's link adds,
    applied while the item does not exist yet). Targets are refs as the
    client knows them: display id, surrogate key, or a `DISPLAY@key`
    composite; the composite that lands on disk is re-derived server-side
    under the write lock, never taken from the request. `who` is the same
    permissions seam as `EditRequest`."""

    who: str
    type: str
    fields: dict
    id: str | None = None
    destination: str | None = None
    amends: str | None = None
    links: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Created:
    """The item is on disk with a reserved id and a minted key."""

    who: str
    item_id: str
    key: str
    type: str
    path: str
    revision: str
    diagnostics: tuple = ()
    ok: bool = True

    @property
    def message(self) -> str:
        return f"created: {self.item_id} ({self.type}) in {self.path}"


def create_item(project_root: str, request: CreateRequest):
    """Create one item in the project at `project_root`, under the same
    per-project write lock every edit takes: two creates in flight cannot
    claim the same id, because the second plans against the state the first
    committed. Returns `Created` | `Refused` | `Invalid`."""
    root = os.path.abspath(project_root)
    config = os.path.join(root, CONFIG_NAME)
    with write_lock_for(root):
        with _disk_write_lock(root):
            return _create_locked(config, request)


def _create_locked(config: str, request: CreateRequest):
    who = request.who
    try:
        # Eager, unlike `apply_edit`'s before snapshot: `_resolve_destination`
        # suggests a destination by `item.board`, and `item.board` is assigned by
        # `boards.resolve()`, which is a build step -- an unbuilt snapshot has
        # every item on no board, and a creation with a `board:` field would be
        # offered a different file. `_load_before`'s deferral is only sound where
        # nothing reads build output off the snapshot.
        before = loader.load_readonly(config)
    except Exception as exc:  # noqa: BLE001 - a project that will not load is a result
        return Refused(who, "", f"the project did not load: {type(exc).__name__}: {exc}")

    spec = before.types.get(request.type)
    if spec is None:
        declared = ", ".join(sorted(before.types)) or "no types at all"
        return Refused(who, "", f"no item type {request.type!r}; this project declares {declared}")

    fields, reason = _creation_fields(spec, request.fields)
    if reason is not None:
        return Refused(who, "", reason)

    # A declared date field the author left empty is today, spelled the
    # project's way (dates.format_date, never a hand-rolled strftime).
    fspec = spec.fields.get("date")
    if fspec is not None and fspec.type == "date" and "date" not in fields:
        fields["date"] = dates.format_date(date.today(), before.date_format)

    rel, dest, reason = _resolve_destination(before, request)
    if reason is not None:
        return Refused(who, "", reason)

    # The destination's own `defaults.prefix` is the series this item is
    # about to be numbered under -- the same override every item already in
    # that file carries, and the same one `refdes id` honours for the same
    # file. Planning from the bare type prefix instead minted ids the file's
    # prefix did not cover (`REQ-001` in a file of `REQ-SYS-*`), which only
    # `refdes check` noticed, as a warning, after the id was already written
    # and burned.
    dest_defaults = dest.get("defaults") or {}
    new_id, reason = ids.plan_new_id(
        before,
        request.type,
        explicit_id=request.id,
        prefix_hint=str(dest_defaults.get("prefix") or ""),
    )
    if reason is not None:
        return Refused(who, "", reason)
    key = _fresh_key(before)

    link_lines = []
    if request.amends:
        line, reason = _amends_line(before, spec, request.amends)
        if reason is not None:
            return Refused(who, new_id, reason)
        link_lines.append(line)

    # Every other verb the type declares, resolved the same way and in the
    # same locked breath: nothing is written unless all of it resolves, so an
    # item never lands with half the links its creation asked for.
    extra_links, reason = _link_lines(before, spec, request.links)
    if reason is not None:
        return Refused(who, new_id, reason)
    if request.amends and "amends" in (request.links or {}):
        return Refused(
            who,
            new_id,
            "'amends' was requested twice -- once as `amends:` and once in "
            "`links:`; one creation writes each verb once",
        )
    link_lines.extend(extra_links)

    body, reason = _item_lines(spec, fields, link_lines, inherited=frozenset(dest_defaults))
    if reason is not None:
        return Refused(who, new_id, reason)

    path = os.path.join(before.root, rel.replace("/", os.sep))
    original: bytes | None = None
    if dest["kind"] == "new-md":
        block = ["---", f"id: {new_id}", f"key: {key}", f"type: {request.type}", *body, "---", ""]
        new_text = "\n".join(block) + "\n"
    else:
        try:
            with open(path, "rb") as fh:
                original = fh.read().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return Refused(who, new_id, f"could not read {rel}: {exc}")
        # The ending of the line the new block is being appended *after*, not
        # "CRLF if the file mentions CRLF anywhere": appending to a file whose
        # tail is LF used to hand the new item CRLF endings, because an
        # unrelated line higher up was CRLF. The block joins the end, so it
        # takes the end's style.
        eol = textio.append_ending(original)
        if dest["kind"] == "append-md":
            block = ["---", f"id: {new_id}", f"key: {key}", f"type: {request.type}", *body, "---", ""]
        else:
            ind = dest["indent"]
            block = [f"{ind}- id: {new_id}", f"{ind}  key: {key}"]
            if dest["type"] != request.type:
                block.append(f"{ind}  type: {request.type}")
            block.extend(f"{ind}  {ln}" for ln in body)
        head = "" if original.endswith("\n") else eol
        # Pure append: every existing byte of the file stays exactly where
        # it was -- the fidelity contract, trivially satisfied.
        new_text = original + head + eol.join(block) + eol

    # Validate the candidate before a byte changes, the same overlay gate
    # apply_edit runs: exactly one more item, no newly introduced error, and
    # the new id resolves with the key it was minted (PyYAML-authoritative
    # post-condition).
    try:
        after = loader.load_readonly(config, overlay={path: new_text})
    except Exception as exc:  # noqa: BLE001 - a candidate that will not load is a result
        return Refused(
            who, new_id, f"the project did not load with the new item: {type(exc).__name__}: {exc}"
        )
    blocking = _creation_blocking(before, after, new_id, key)
    if blocking:
        return Invalid(who, new_id, tuple(blocking), path=path)

    if dest["kind"] == "new-md":
        failure = _atomic_create(path, new_text.encode("utf-8"))
    else:
        failure = _atomic_replace(path, new_text.encode("utf-8"))
    if failure is not None:
        return Refused(who, new_id, failure, path=path)

    # The reservation is the last step, so nothing is burned unless the
    # item is on disk; a failed reservation rolls the file back so the id
    # stays as unburned as it was.
    try:
        ids.reserve_id(before, new_id)
    except OSError as exc:
        _rollback(path, original)
        return Refused(
            who,
            new_id,
            f"the id ledger could not be written ({exc}); {rel} was rolled back "
            f"and {new_id} was not reserved",
            path=path,
        )

    return Created(
        who=who,
        item_id=new_id,
        key=key,
        type=request.type,
        path=path,
        revision=file_revision(path),
        diagnostics=tuple(after.diagnostics),
    )


# ------------------------------------------------------------------ creation parts


def _creation_fields(spec, fields):
    """Structural field checks only -- unknown names, collections, non-scalars.
    Value correctness (a bad enum choice, a malformed date, a missing
    required field) is the delta gate's job, judged by the schema itself on
    the candidate load, exactly like an ordinary field edit."""
    if not isinstance(fields, dict):
        return None, "fields must be an object mapping field names to scalar values"
    out: dict = {}
    for name, value in fields.items():
        if name in ("board", "workspace"):
            if not isinstance(value, str) or not value:
                return None, f"{name} needs a non-empty string"
            out[name] = value
            continue
        fspec = spec.fields.get(name)
        if fspec is None:
            declared = ", ".join(sorted(spec.fields)) or "none"
            return None, f"{spec.name} does not declare a field {name!r}; it declares {declared}"
        if fspec.type in NON_SCALAR_FIELD_TYPES:
            return None, (
                f"field {name!r} is a {fspec.type} field: collections are not "
                "created here -- create the item and edit the collection after"
            )
        if value is None or isinstance(value, (list, dict)):
            return None, f"field {name!r} needs a scalar value"
        out[name] = value
    return out, None


def suggest_destination(project: Project, type_name: str, board: str | None = None) -> str:
    """Suggest, never decide: the file where items of this type already live
    (preferring the same board when one is given), falling back to a new
    single-item Markdown file named for the type. The explicit override
    always wins (Decisions, "Creation destination: suggest plus override")."""
    files = [
        item.source_file.replace("\\", "/")
        for item in project.local_items
        if item.type == type_name and item.source_file
    ]
    if board:
        same_board = [
            item.source_file.replace("\\", "/")
            for item in project.local_items
            if item.type == type_name and item.source_file and item.board == board
        ]
        if same_board:
            files = same_board
    if files:
        return Counter(files).most_common(1)[0][0]
    return f"items/{type_name}s.md"


def _resolve_destination(project: Project, request: CreateRequest):
    """-> (rel, dest, reason). dest is None|{'kind': ..., 'indent'/'type'...}
    for the three shapes: append-yaml (an existing list file), append-md (an
    existing multi-item Markdown file), new-md (a new single-item Markdown
    file). Everything else -- path escapes, a non-source extension, a new
    YAML file, a list file whose `items:` block cannot be safely grown -- is
    a reason.

    For the two append shapes, `dest['defaults']` is the destination file's
    own file-wide `defaults:` mapping -- the one the loader merges under
    every item in that file. An item appended there inherits it like any
    other, so the id series it numbers under and the field values it starts
    with are that file's to decide, not the type's. new-md has no
    `defaults:` key at all: a file that does not exist yet cannot declare
    any, which is exactly the state `refdes id` would find it in.
    """
    dest = (request.destination or "").strip().replace("\\", "/")
    if not dest:
        dest = suggest_destination(
            project, request.type, board=(request.fields or {}).get("board")
        )
    parts = security.safe_relative_parts("/" + dest)
    if not parts:
        return None, None, f"{dest!r} is not a safe relative path"
    if parts[0] != "items":
        return None, None, "a destination must live under items/, where the project's sources are"
    ext = os.path.splitext(parts[-1])[1].lower()
    if ext not in (".md", ".yaml", ".yml"):
        return None, None, "a destination must be a .md, .yaml, or .yml item source file"
    root = os.path.abspath(project.root)
    path = os.path.normpath(os.path.join(root, *parts))
    if path != root and not path.startswith(root + os.sep):
        return None, None, "the destination resolves outside the project"
    rel = "/".join(parts)

    if not os.path.exists(path):
        if ext != ".md":
            return None, None, (
                f"{rel} does not exist, and creating a new YAML list file is not a v1 "
                "destination -- start one with `refdes new --list`, or choose a new .md file"
            )
        return rel, {"kind": "new-md"}, None
    if os.path.isdir(path):
        return None, None, f"{rel} is a directory"

    # Both existing-file shapes are read here, once, because the item about
    # to be appended inherits the destination file's own `defaults:` exactly
    # as the loader hands it to every item already in that file -- and the
    # prefix and status that implies have to be known *before* an id is
    # planned and the item's lines are emitted. A file that does not exist
    # yet (new-md) has no defaults to inherit, so it plans from the type.
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return None, None, f"could not read {rel}: {exc}"
    if ext == ".md":
        blocks, _errors, _duplicates = md_front_matter_blocks(text.split("\n"))
        return rel, {
            "kind": "append-md",
            "defaults": front_matter_defaults_block(blocks) or {},
        }, None

    # An existing YAML list file: it must be a mapping with a block-style
    # `items:` list, and that list must be the last block in the file --
    # anything else means a safe append (every existing byte untouched)
    # cannot be promised, which is a refusal, not a guess.
    try:
        data = yaml_safe_load(text)
    except Exception as exc:  # noqa: BLE001 - a YAML error here is a refusal reason
        return None, None, f"{rel} does not parse: {type(exc).__name__}"
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None, None, f"{rel} is not a list file (a mapping with an items: list)"
    lines = text.splitlines()
    items_at = None
    for i, line in enumerate(lines):
        if re.match(r"^items\s*:", line):
            items_at = i
            break
    if items_at is None:
        return None, None, f"{rel} has no items: block at the top level"
    rest = lines[items_at].split(":", 1)[1].strip()
    if rest and not rest.startswith("#"):
        return None, None, (
            f"{rel}: its items: list is written inline (flow style), which cannot be "
            "appended to without rewriting it"
        )
    indent = None
    for line in lines[items_at + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace():
            return None, None, (
                f"{rel}: the items: list is not the last block in the file, so a new "
                "entry cannot be appended without moving what follows it"
            )
        entry = ids.LIST_ENTRY_RE.match(line)
        if indent is None and entry:
            indent = entry.group(1)
    defaults = data.get("defaults")
    defaults = defaults if isinstance(defaults, dict) else {}
    return rel, {
        "kind": "append-yaml",
        "indent": indent or "  ",
        "type": defaults.get("type"),
        "defaults": defaults,
    }, None


def _fresh_key(project: Project) -> str:
    """A key this project does not already carry. 50-bit keys make a
    collision absurd; the check is free, so take it."""
    taken = {item.key for item in project.items.values() if item.key}
    for _ in range(8):
        key = keys.mint()
        if key not in taken:
            return key
    return keys.mint()


def _amends_line(project: Project, spec, ref: str):
    """The `amends:` line for a correcting entry, resolved under the lock
    exactly like Slice 2's link adds: the verb must be declared, the target
    must exist and be of an allowed type, and the written text is always
    `links.composite_for`'s DISPLAY-ID@key -- never a bare id."""
    if "amends" not in spec.links:
        return None, (
            f"type {spec.name!r} does not declare an amends link; a correction "
            "is a new entry with amends only where the schema allows one"
        )
    allowed = spec.links["amends"]
    target = _find_item(project, ref)
    if target is None:
        return None, f"no item {ref!r} in this project to amend"
    if not project.accepts_type(target.type, allowed):
        wants = "any declared type" if not allowed else "targets of type " + ", ".join(allowed)
        return None, f"'amends' accepts {wants}; {target.id} is a {target.type}"
    composite = links.composite_for(target)
    if composite is None:
        return None, (
            f"{target.id} carries no artifact key, so no DISPLAY-ID@key composite "
            "can be written for it; amending it with a bare id would drop the "
            "identity the link is for"
        )
    return f"amends: [{composite}]", None


def _link_target(project: Project, verb: str, ref: str, allowed: list[str]):
    """One creation link target -> the composite to write, or a reason.

    The spellings accepted are the ones `_resolve_link_op` accepts for an
    ordinary link add -- the `project.items` handle, the display id, the key
    -- plus a `DISPLAY@key` composite a client already resolved as far as it
    could: the key half is what resolves (docs/design/keys.md §3), the label
    half is only a label. Either way the text returned is
    `links.composite_for`'s own output, so a composite the client got wrong
    (or stale) cannot reach the disk."""
    target = _find_item(project, ref)
    if target is None and "@" in ref:
        target = project.items.get(ref.partition("@")[2])
    if target is None:
        return None, f"no item {ref!r} in this project to link to with '{verb}'"
    if not project.accepts_type(target.type, allowed):
        wants = "any declared type" if not allowed else "targets of type " + ", ".join(allowed)
        return None, f"'{verb}' accepts {wants}; {target.id} is a {target.type}"
    composite = links.composite_for(target)
    if composite is None:
        return None, (
            f"{target.id} carries no artifact key, so no DISPLAY-ID@key composite "
            "can be written for it; linking it with a bare id would drop the "
            "identity the link is for"
        )
    return composite, None


def _link_lines(project: Project, spec, links_map):
    """The link lines for a new item, for any verb the type declares --
    `_amends_line` generalised, and resolved by the same rules the edit
    route's `AddLink` uses (`_resolve_link_op`): the verb must be declared,
    every target must exist and be of a type the verb accepts, and what is
    written is always the `DISPLAY-ID@key` composite. Anything that does not
    resolve is a reason, which refuses the whole creation -- the same
    posture `_amends_line` has, and the reason this runs before a byte is
    planned rather than as a follow-up edit.

    One line per verb, in the flow-sequence spelling the standard's own items
    write (`addresses: [REQ-PWR-001@…, REQ-PWR-002@…]`), so one target and
    five targets are spelled the same way `amends:` already spells one."""
    if not links_map:
        return [], None
    if not isinstance(links_map, dict):
        return None, "links must be an object mapping link verbs to lists of target refs"
    lines: list[str] = []
    for verb, targets in links_map.items():
        if not isinstance(verb, str) or not verb.strip():
            return None, "every links: key must be a link verb name"
        if not isinstance(targets, list) or not targets:
            return None, (
                f"links {verb!r} needs a non-empty list of target refs "
                "(a display id, surrogate key, or DISPLAY@key composite each)"
            )
        if verb not in spec.links:
            declared = ", ".join(sorted(spec.links)) or "no links at all"
            return None, f"{spec.name} does not declare the link {verb!r}; it declares {declared}"
        allowed = spec.links[verb]
        composites: list[str] = []
        for ref in targets:
            if not isinstance(ref, str) or not ref.strip():
                return None, f"links {verb!r} needs non-empty target refs"
            composite, reason = _link_target(project, verb, ref.strip(), allowed)
            if reason is not None:
                return None, reason
            # Compared on the resolved composite, not the spelling sent, so
            # `REQ-001`, its bare key and the composite are one target asked
            # for twice -- which is what the edit route already refuses with
            # "item X already links Y" (`patcher.py`). A new item is the one
            # place there is no existing line to refuse against, so the
            # request itself is where the duplicate has to be caught.
            if composite in composites:
                return None, (
                    f"links {verb!r} names {composite.partition('@')[0]} twice; "
                    "one creation links each target once"
                )
            composites.append(composite)
        lines.append(f"{verb}: [{', '.join(composites)}]")
    return lines, None


def _item_lines(spec, fields: dict, link_lines: list[str], inherited: frozenset = frozenset()):
    """The new item's YAML lines after id/key: board/workspace, then the
    initial field set -- scaffold.initial_field_values, the same resolution
    `refdes new` scaffolds -- emitted through the patcher's round-trip-verified
    scalar emitter, then any link lines.

    A field named in `inherited` (the destination file's `defaults:`) is
    left off when its value is only the type's declared fallback. The item
    would inherit the file's value anyway, and writing the fallback made it
    *override* that value instead: a file whose `defaults:` said
    `status: active` collected items stamped `status: draft`, one line per
    item, and the file's own setting was quietly dead. A value the author
    supplied is written even then -- overriding the file is what supplying
    one means.
    """
    lines: list[str] = []
    for name in ("board", "workspace"):
        if name in fields:
            text, _note = patcher._emit_scalar(
                fields[name], style=None, indent=0, eol="\n", allow_block=False, original=""
            )
            if text is None:
                return None, f"the value for {name!r} cannot be emitted as YAML"
            lines.append(f"{name}: {text}")
    initial = scaffold.initial_field_values(spec, fields)
    for fname, value in initial.items():
        if fname in inherited and fname not in fields:
            continue
        text, _note = patcher._emit_scalar(
            value, style=None, indent=0, eol="\n", allow_block=False, original=""
        )
        if text is None:
            return None, f"the value for field {fname!r} cannot be emitted as YAML"
        lines.append(f"{fname}: {text}")
    lines.extend(link_lines)
    return lines, None


def _creation_blocking(before: Project, after: Project, new_id: str, key: str) -> list:
    """The creation gate: exactly one more item than before, the new id
    resolving with the minted key, and no newly introduced error. A
    pre-existing unrelated error never blocks, same posture as the edit
    gate."""
    before_count = len(before.local_items)
    after_count = len(after.local_items)
    if after_count != before_count + 1:
        return [d for d in after.diagnostics if d.level == "error"] or [
            Diagnostic(
                ERROR,
                f"creating {new_id} changed the number of items from "
                f"{before_count} to {after_count}",
            )
        ]
    new_item = after.item_by_id(new_id)
    if new_item is None or new_item.key != key:
        return [
            Diagnostic(
                ERROR,
                f"the new item {new_id} does not resolve with the key it was minted",
            )
        ]
    before_errors = _errors(before)
    after_errors = _errors(after)
    return [d for k, d in after_errors.items() if k not in before_errors]


def _atomic_create(path: str, payload: bytes) -> str | None:
    """Create a file that must not exist yet, atomically: temp write in the
    destination directory, fsync, then a hard link -- which fails rather
    than replace -- and unlink of the temp. Returns None on success, a
    reason on failure."""
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        return f"could not create {directory}: {exc}"
    tmp = os.path.join(directory, f".{os.path.basename(path)}.refdes-tmp")
    fd = None
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        with os.fdopen(fd, "wb") as fh:
            fd = None
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(tmp, path)
    except OSError as exc:
        _discard_tmp(tmp)
        return f"could not create {path}: {exc}"
    _discard_tmp(tmp)
    try:
        with open(path, "rb") as fh:
            written = fh.read()
    except OSError as exc:
        return f"could not re-read {path} after the write: {exc}"
    if written != payload:
        return f"the bytes on disk after the write are not the bytes planned for {path}"
    return None


def _rollback(path: str, original: bytes | None) -> None:
    """Undo a completed write when a later step failed: restore the previous
    bytes, or remove the file that did not exist before."""
    if original is None:
        try:
            os.unlink(path)
        except OSError:
            pass
        return
    _restore(path, original)


def preview_creation(
    project: Project,
    type_name: str,
    *,
    explicit_id: str | None = None,
    board: str | None = None,
    destination: str | None = None,
) -> dict:
    """The id an item WOULD get and the destination it WOULD land in --
    purely, with no lock and no reservation. This is why planning was split
    out of `ids.allocate()`: the form can show the author the next id and
    the suggested file without burning anything. A concurrent create that
    moves the number between preview and save is caught by the save itself,
    which re-plans under the lock."""
    spec = project.types.get(type_name)
    if spec is None:
        declared = ", ".join(sorted(project.types)) or "no types at all"
        return {
            "id": None,
            "reason": f"no item type {type_name!r}; this project declares {declared}",
            "destination": None,
            "destination_exists": False,
        }
    dest = (destination or "").strip().replace("\\", "/") or suggest_destination(
        project, type_name, board=board
    )
    # Resolved exactly as `create_item` will resolve it, so a destination
    # file's own `defaults.prefix` reaches the previewed id too -- this form
    # promises that the id shown before saving is the id the item gets, and a
    # prefix the preview cannot see is one more way that promise breaks.
    # A destination the create would refuse still previews its bare type
    # prefix; the refusal is the save's to report, not the preview's to hide.
    _rel, resolved, _why = _resolve_destination(
        project,
        CreateRequest(
            who="preview",
            type=type_name,
            fields={} if board is None else {"board": board},
            destination=dest,
        ),
    )
    prefix_hint = str((resolved or {}).get("defaults", {}).get("prefix") or "")
    new_id, reason = ids.plan_new_id(
        project, type_name, explicit_id=explicit_id, prefix_hint=prefix_hint
    )
    exists = os.path.exists(os.path.join(project.root, dest.replace("/", os.sep)))
    return {"id": new_id, "reason": reason, "destination": dest, "destination_exists": exists}
