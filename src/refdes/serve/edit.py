"""The editor's one write path: `apply_edit(project_root, request)`.

docs/design/browser-editor.md, "Permissions are out of scope for v1 -- with one
seam": one entry point applies every mutation, every operation carries who
asked, and a refusal is a first-class result. This module is that entry point.
It has no HTTP and no UI: the server slice wraps these results in status codes,
and a refusal here is a value the caller renders, never an exception it catches.

An outcome is one of four dataclasses -- `Applied`, `Conflict`, `Refused`,
`Invalid` -- each carrying `ok` and a human-readable `message`, so a caller can
branch on type and still log any result uniformly.

What each save does, in order (the design's transaction model, journal
included -- see step 7):

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
7. journal the write and write atomically: before the replace, the target
   file's exact current bytes are recorded in `.refdes/editor-transaction/`
   (`editor_journal.begin`, design step "write the journal before the
   replacements"), the temp file is written in the same directory -- flush,
   fsync, `os.replace` -- re-read, and confirmed to hold the planned bytes,
   and the journal is cleared once the save lands
   (`editor_journal.complete`). Step 3's revision check is the swap's last
   word: `expected_revision` is threaded into the write and compared against
   the bytes the replace itself reads, so a file a writer outside the lock
   moved during step 6's gate is the same `Conflict`, with nothing written.
   A kill between arming the journal and clearing it leaves the journal
   visible: every project-loading command then refuses until
   `refdes recover` restores the journaled files to the bytes recorded there
   (docs/design/browser-editor.md, acceptance).

One save writes two files. A `set_body` carrying `pin` (docs/design/
editor-source-picker.md §4 -- the editor's source-value picker accepting a
value) writes `.refdes/citations.yaml` as well as the item, because a body with
a `source()` line whose key is not pinned is an item that does not build and a
pinned key no body names is dead state in a tracked file. The pair lands in the
save's final section, one section under the project's cross-process write lock,
after the revision check: the lockfile bytes are staged in memory (the loader's
lockfile overlay), judged by the delta gate, and landed in the same section as
the body that names them -- no cooperating writer lands between the pin and
the body, and a file a cooperating writer moved during the gate is re-staged
from, not restored over (§4). Both lockfile sections -- the read-compute that
stages and the write-then-restore of the final section -- each run as one
section under the same `project_write_lock` `cli.main` wraps its commands in
(`serve`, `init`, `new` and `schema` exempt, as are read-only runs); the delta
gate between the two sections deliberately does not hold the lock, and a
cooperating writer that lands inside that window is met by re-reading the file
at landing, not by a promise that no writer lands there. It is still one
apply-operation call and still one mutation entry point; what widened is the
request, not the number of writers.

`apply_edit` addresses an existing field, body, or link; `create_item` is
Slice 3's entry point, which does mint a key, reserve an id, and write a new
item -- inside the same lock, with the same refuse-as-a-value posture, and
with the ledger reservation and the file write committed or rolled back
together. An append through `create_item` is planned against the destination
bytes read under that lock and re-read once, immediately before the replace,
so a destination a writer outside the lock touched in the meantime is
re-planned from a fresh load rather than silently replaced -- and a create
whose last check passes can still lose to a writer that lands between that
check and the `os.replace` itself, which no check-and-replace on a plain
file can prevent; see `create_item`'s docstring for what is and is not
promised.
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
from .. import dates, editor_journal, ids, keys, links, loader, patcher, scaffold, seal, textio
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
from . import resolution, security
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
    # whose bytes are staged in memory and land together in one section of
    # the project's cross-process lock (§4). Empty for every edit that is not
    # an accept.
    pins: tuple = ()


# -------------------------------------------------------------------- results


@dataclass(frozen=True)
class Applied:
    """The edit is on disk. `revision` is the target file's new content revision.

    `item_id` and `handle` are the item's CURRENT display id and live handle
    (key, else display id) -- which is what the caller posted as `ref` only
    when `ref` was already current. A write that arrived under a retired id
    lands on the item and reports the live spelling back, so the browser can
    correct its ref (the same contract `GET /api/item/<retired>` gives)."""

    who: str
    ref: str
    path: str
    revision: str
    plan: PatchPlan
    diagnostics: tuple = ()
    # What an accept pinned, as `{path, key, reader, value}` -- the value the
    # reader read. Empty for an ordinary save, and never a value the client sent.
    pinned: tuple = ()
    item_id: str = ""
    handle: str = ""
    # Set when the save landed and the journal survived `complete()`: the
    # message says so, because the next project load will refuse until
    # `refdes recover` clears it (by rolling this save back).
    journal_warning: str = ""
    ok: bool = True

    @property
    def message(self) -> str:
        text = f"applied: {self.plan.describe()}"
        if self.journal_warning:
            text += f" -- {self.journal_warning}"
        return text


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
    and replacement across server processes.

    LOCK ORDER, and it is not negotiable: `write_lock_for` is always taken
    first and `_disk_write_lock` (i.e. `project_write_lock`) only ever inside
    it. Every holder here honours it -- `apply_edit` and `create_item` take
    this lock then that one, `serve/upload.py:669` takes this one alone, and
    nothing in the package acquires `project_write_lock` and then reaches for
    `write_lock_for`. The rule exists because these are two different locks
    with no ordering of their own: two threads in this process that took them
    in opposite orders would deadlock outright (one holds the project lock and
    waits for this one, the other holds this one and waits for the project
    lock, and nothing can time out), and a `refdes fetch` in another process
    holds the project lock for its whole command, so an editor section must
    expect to wait for it and never the reverse."""
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
    """Use the same project lock as CLI writers.

    Re-entrant per thread (`write_lock.project_write_lock`), so a save that
    takes it inside a section it already holds does not deadlock itself. A
    read-only root raises `LockUnavailable`, an `OSError`, which every caller
    here already turns into a refusal.
    """
    from ..write_lock import project_write_lock

    with project_write_lock(root):
        yield


# ---------------------------------------------------------------- the entry point


def apply_edit(project_root: str, request: EditRequest, config_path: str | None = None):
    """Apply one edit request to the project at `project_root`.

    `config_path` is the project's settings file when the server was
    launched with `-c/--config` at a path that is not the default marker
    name; every load below reads the file the model was built from, so a
    save against a custom-configured project loads -- and refuses on -- the
    same file, not a `refdes-project.yaml` that was never there. Omitted,
    the default marker beside the root is the config, exactly as before.

    Returns `Applied` | `Conflict` | `Refused` | `Invalid`. Authoring outcomes
    are values; only a genuinely unexpected internal fault raises, and the
    write path itself restores the original bytes if a replacement half-fails.

    The save's last revision check is the replace's own read: the expected
    revision is threaded into the atomic swap and compared against the bytes
    the swap reads, so a file a writer OUTSIDE the project lock moved between
    the gate and the swap is refused as the same `Conflict`, with nothing
    written. The irreducible gap between the swap's own read and its
    `os.replace` stays open -- the same residual `create_item`'s docstring
    names, and no check-and-replace on a plain file closes it.
    """
    root = os.path.abspath(project_root)
    config = os.path.abspath(config_path) if config_path else os.path.join(root, CONFIG_NAME)
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
    needs one at all. The accept keeps it eager because `sources.accept_plan`
    re-validates the picks against the item's evaluated calc lines, which only
    a built snapshot has.

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

    resolved = resolution.resolve_ref(before, ref)
    if resolved.claimed_by:
        owners = ", ".join(f"'{owner}'" for owner in resolved.claimed_by)
        return Refused(
            who,
            ref,
            f"former id {ref!r} is recorded in the former_ids of {owners}: a retired id "
            "must resolve to exactly one item, and this write refuses to pick one",
        )
    item = resolved.item
    if item is None:
        return Refused(who, ref, f"no item {ref!r} in this project")
    # What the patcher matches in the file is the item's CURRENT spelling --
    # a retired id is not in the file, and a keyless item's provisional
    # `~<relpath>:<line>` dict key (what `/api/items` hands the browser as
    # the row handle) is a view address, not a spelling the file holds. The
    # patcher matches `id:`/`key:` values, so the save is planned against
    # them: the key when the item carries one (the spelling the list route
    # hands out), else the display id. The handle's relpath:line is not
    # dropped unvalidated -- it was just proven by the resolution above,
    # which accepted this handle only by exact dict-key hit against the tree
    # loaded from disk under this lock: a stale line, or a line in a file
    # the item does not live in, resolves to nothing and is refused there.
    patch_ref = item.key or item.id or resolved.handle
    if item.external:
        return Refused(who, ref, f"{ref} is an imported item; imports are read-only here")

    path = _item_path(before, item)
    if path is None:
        return Refused(who, ref, f"{ref} resolves outside the project; nothing was written")

    current_revision = file_revision(path)
    if current_revision != request.expected_revision:
        return _conflict(who, ref, path, before, request, current_revision, patch_ref)

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

    plan = patcher.plan_patch(text, patch_ref, op, path=path)
    if isinstance(plan, Refusal):
        return Refused(who, ref, plan.reason, path=path)
    new_text = patcher.apply_patch(text, plan)

    # An accept: the body op plus the keys to pin. One operation over two
    # files (docs/design/editor-source-picker.md §4), and the only one here
    # that is. The pins are staged in memory, not written: the candidate is
    # built against the staged lockfile through the loader's lockfile
    # overlay, and the pair lands in the final section below, one section
    # under the project's cross-process write lock, after the revision
    # check. Nothing lands on disk ahead of the pair, so no cooperating
    # writer has a window between a pin and the body that names it -- the
    # gate's window is read-only, and a file a cooperating writer moved
    # during it is re-staged from, not restored over (§4).
    new_body = op.text if isinstance(op, SetBody) else None
    accept, reason = _accept_pins(before, item, request.pins, new_body)
    if reason is not None:
        return Refused(who, ref, reason, path=path)

    # The staged lockfile, as text, for the candidate load. `None` for an
    # ordinary save: it judges the project exactly as it stands.
    staged_lockfile = (
        None
        if accept is None or accept.lock is None
        else accept.lock.staged.decode("utf-8")
    )

    try:
        after = loader.load_readonly(
            config, overlay={path: new_text}, lockfile_overlay=staged_lockfile
        )
    except Exception as exc:  # noqa: BLE001 - a candidate that will not load is a result
        # The window §4's old shape left: the pin on disk, the body not
        # landing. There is no disk to put back here -- the accept's bytes
        # are staged, and the refusal lands nothing.
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
        return Invalid(who, ref, tuple(blocking), path=path)

    # The candidate gate can take seconds. Another server may have saved since
    # the first check, so check again under the cross-process write lock. The
    # check's last word is the replace's own read: `expected_revision` is
    # threaded into `_atomic_replace` below, so a file a writer OUTSIDE the
    # lock moved between the fast check and the replace's read is this same
    # `Conflict`, with nothing written -- the replace consumes the bytes its
    # own check names (see `create_item` for the residual gap that remains).
    #
    # The pair lands in this one section: the pins (if this is an accept)
    # first, then the body, with nothing between them and no lock release
    # between the two replaces -- a cooperating writer (another server's
    # accept, `refdes fetch`) is serialised outside the whole pair. The
    # section re-reads the lockfile under the lock and re-stages this
    # accept's keys from what it finds when the bytes moved during the gate,
    # so a cooperating writer's pins are input to the bytes that land, never
    # a reason to skip this pair (§4). If the body's replace fails the
    # section restores what its own lockfile replace replaced -- under the
    # same lock, seconds after the write, not seconds later in a window.
    # The journal (design step 6): armed with the file's exact bytes before
    # the replace runs, cleared after it lands (step 9). A kill between
    # arming and clearing leaves `.refdes/editor-transaction/` visible, and
    # every project-loading command refuses until `refdes recover` restores
    # it. A journal that cannot be armed stops the save before it starts:
    # an unarmed write is exactly the kill-with-no-recovery this ends.
    journal_rel = _journal_relpath(before.root, path)
    journal_warning = None
    payload = new_text.encode("utf-8")
    try:
        with _disk_write_lock(before.root):
            current_revision = file_revision(path)
            if current_revision != request.expected_revision:
                return _conflict(who, ref, path, before, request, current_revision, patch_ref)
            if accept is not None:
                reason = _land_lockfile(before, accept)
                if reason is not None:
                    return Refused(who, ref, reason, path=path)
            if journal_rel is not None:
                reason = _journal_arm(
                    before.root, journal_rel, text.encode("utf-8"), payload
                )
                if reason is not None:
                    _restore_lockfile(accept)
                    return Refused(who, ref, reason, path=path)
            try:
                failure = _atomic_replace(path, payload, request.expected_revision)
            except _Moved as moved:
                # The file moved after the fast check above, before the
                # replace read it: the same Conflict the check spells, named
                # from the bytes this replace saw. The pins -- if this was an
                # accept -- landed a moment ago under this lock and must go
                # back with the body that never lands. The journal armed for
                # this replace describes a save that lands nowhere: clear it
                # with the save (a survival is reported by the next load).
                _restore_lockfile(accept)
                _journal_clear(before.root)
                return _conflict(who, ref, path, before, request, moved.current, patch_ref)
            if failure is not None:
                _restore_lockfile(accept)
                warning = _journal_clear(before.root)
                return Refused(
                    who,
                    ref,
                    failure if warning is None else f"{failure}; {warning}",
                    path=path,
                )
            journal_warning = _journal_clear(before.root)
    except OSError as exc:
        return Refused(who, ref, f"could not lock {path} for writing: {exc}", path=path)

    return Applied(
        who=who,
        ref=ref,
        path=path,
        revision=file_revision(path),
        plan=plan,
        diagnostics=tuple(after.diagnostics),
        pinned=() if accept is None else accept.pinned,
        item_id=item.id,
        handle=resolved.handle,
        journal_warning=journal_warning,
    )


# ------------------------------------------------------------------- accepting
#
# docs/design/editor-source-picker.md §4. A picked source value is two writes --
# a line in an item's body and a pin in `.refdes/citations.yaml` -- that are
# meaningful only together, so they are one operation: neither lands without the
# other, and a refusal anywhere leaves both files exactly as they were.


@dataclass
class _LockfileStage:
    """One lockfile write decided in memory, with what the final section did.

    `previous` is the whole-file bytes the stage replaces, None when the
    project had no lockfile at all -- an accept of an unpinned citation into a
    project nobody has ever fetched creates the file, and undoing the final
    section's own write means removing it, not leaving an empty `citations: {}`
    where no file was.

    `landed` and `restore_to` are the final section's bookkeeping: `landed`
    says its replace ran, `restore_to` holds the bytes that replace replaced,
    which is all the restore is ever asked to put back. Nothing outside the
    final section reads them -- there is no rollback window to read them
    from.

    `root` is the project root: the stage's read and the final section's write
    are sections of a read-modify-write of a file other processes write, so
    both take the same cross-process lock every other writer of this file
    takes.
    """

    path: str
    root: str
    previous: bytes | None
    staged: bytes
    landed: bool = False
    restore_to: bytes | None = None


@dataclass
class _Acceptance:
    """What an accept decided, before the pair it belongs to has landed.

    `lock` is the staged lockfile (its bytes, the bytes it replaces) and
    `pinned` is what the reader read, which is the only thing about the pick
    worth telling the caller back. `plans`, `anchors` and `digests` are the
    accept's own keys, carried so the final section can re-stage them from
    the records on disk if a cooperating writer moved the file during the
    gate. The composed line is deliberately not carried: the author already
    has it -- it is the text in the body being saved -- and a second copy of
    it here would be a second thing to keep in agreement.
    """

    lock: _LockfileStage | None
    pinned: tuple = ()
    plans: tuple = ()
    anchors: dict = field(default_factory=dict)
    digests: dict = field(default_factory=dict)


def _land_lockfile(before: Project, accept: _Acceptance) -> str | None:
    """Land this accept's staged lockfile bytes; the project lock is held.

    Called by the final section of `_apply_locked` under the same lock, after
    the body's revision check, immediately before the body lands: §4's pair
    lands together. Returns a refusal reason (the lockfile lands nowhere, the
    body lands nowhere), or None.

    Three states of the file, read fresh under this lock:

    * the bytes this accept staged -- the pair is pinned (a cooperating
      accept of these same keys landed these exact bytes; its own write was
      the no-op this staging is); the write is skipped, the body lands, and
      the pair is together;
    * the bytes this accept staged its decision from -- nobody moved the
      file; the staged bytes land;
    * anything else -- a cooperating writer's read-modify-write landed
      during the gate. The file is input, not an obstacle. If its records
      already pin every pair this accept brings AT THE VALUES this accept
      read them (its bytes differ from ours only in pins we do not carry),
      the file stands: writing this accept's staged bytes -- computed
      before the writer landed, and therefore missing the writer's pins --
      would erase them from under the bodies that name them, which is this
      PR's own clobber class. A pair the file pins at a DIFFERENT value is
      a refusal: the gate judged the body against the value this accept
      staged, and landing the body over the writer's pin would let a
      `source()` line evaluate at a value the gate never judged; the
      deliberate repair is a fresh accept against the current lockfile,
      and overwriting the writer's file is not on the table. Otherwise
      this accept's keys are re-staged over the records as they now are,
      under fetch's own non-update policy, and the merged bytes land, so
      the writer's pins survive in the file and the pair lands with the
      body. A record the keys no longer describe (a changed source file)
      is a refusal, not a clobber, and so is a re-extraction that reads a
      value other than the one the gate was judged on.

    A refusal after this function returned None can only be the body's
    replace failing, and the section restores what its own write replaced --
    `landed`/`restore_to` are what that restore reads.
    """
    lock = accept.lock
    if lock is None:
        return None
    try:
        with open(lock.path, "rb") as fh:
            current = fh.read()
    except OSError:
        current = None
    # The replace's check consumes the read above: `expected_sha` names
    # these exact bytes, so a writer OUTSIDE the lock that lands on the
    # file between this read and the replace's own read is a refusal, not
    # a clobber -- the pair lands nowhere and the outside bytes stand. The
    # replace's read-to-swap gap is the module-wide residual (see
    # `create_item`). Named apart from `expected` below, the pin-value map
    # -- the check consumes the bytes, not the pins.
    expected_sha = None if current is None else hashlib.sha256(current).hexdigest()
    if current == lock.staged:
        return None
    if current != lock.previous:
        # The file moved. A source file's bytes cannot be re-digested for a
        # pin already on disk, and a pair the records already pin is a pair
        # that landed with its own body -- the revision check above says no
        # body of ours replaced it -- so the file stands and only the body
        # lands.
        try:
            records = citations_mod.load_lockfile(before)
        except citations_mod.LockfileError as exc:
            return str(exc)
        pairs = [(plan["path"], plan["key"]) for plan in accept.plans]
        expected = {
            (entry["path"], entry["key"]): str(entry["value"])
            for entry in accept.pinned
        }
        pinned_on_disk = {
            (canon, key): citations_mod.locked_source_value(records.get(canon), key)
            for canon, key in pairs
        }
        if all(
            pinned_on_disk[pair] == expected[pair] for pair in pinned_on_disk
        ):
            return None
        drifted = [
            f"{canon}: key {key!r} is pinned to {on_disk!r}, not the "
            f"{expected[(canon, key)]!r} this accept read"
            for (canon, key), on_disk in pinned_on_disk.items()
            if on_disk is not None and on_disk != expected[(canon, key)]
        ]
        if drifted:
            return "; ".join(drifted) + "; re-accept against the current lockfile"
        errors, pinned = citations_mod.stage_source_pins(
            before, records, pairs,
            anchors=accept.anchors, digests=accept.digests,
        )
        if errors:
            return "; ".join(errors)
        drifted = [
            f"{entry['path']}: key {entry['key']!r} now reads {str(entry['value'])!r}, "
            f"not the {expected[(entry['path'], entry['key'])]!r} the gate was judged on"
            for entry in pinned
            if str(entry["value"]) != expected[(entry["path"], entry["key"])]
        ]
        if drifted:
            return "; ".join(drifted) + "; re-accept against the current lockfile"
        lock.staged = citations_mod.lockfile_text(records).encode("utf-8")
        # The response reports the values this section's bytes pin, which
        # is the same extraction under the same policy -- the reader's
        # answer, not a second copy of anything.
        accept.pinned = tuple(pinned)
    try:
        failure = (
            _atomic_replace(lock.path, lock.staged, expected_sha)
            if current is not None
            else _atomic_create(lock.path, lock.staged)
        )
    except _Moved:
        return (
            f"{lock.path} changed on disk while this accept was landing; "
            "the pair landed nowhere -- re-accept against the current lockfile"
        )
    if failure is not None:
        return failure
    lock.landed = True
    lock.restore_to = current
    return None


def _restore_lockfile(accept: _Acceptance | None) -> None:
    """Undo the final section's own lockfile write after the body's replace
    failed; the project lock is held.

    Bytes restored from memory, not a transaction journal -- the design says
    so out loud rather than papering over it: the window is one `os.replace`
    wide, and the failure mode if the process dies inside it is a lockfile
    pinning a key no item names, which is inert, visible in `git status`, and
    cleaned by the next `refdes fetch`. What the window does not admit is
    another writer: the restore runs in the same lock section as the write it
    undoes, and the pair it lands with is the body that fails one `os.replace`
    later. A restore that cannot write is swallowed, as `_rollback` has always
    swallowed it -- the residue is the inert pin the crash window already
    names.
    """
    if accept is None or accept.lock is None or not accept.lock.landed:
        return
    _rollback(accept.lock.path, accept.lock.restore_to)


def _accept_pins(
    before: Project, item: Item, pins: tuple, new_body: str | None
) -> tuple[_Acceptance | None, str | None]:
    """Re-validate the picks, extract their values, and stage the lockfile.

    Returns `(acceptance, None)` or `(None, reason)`; a reason means nothing
    was decided anywhere -- no bytes, no disk. The acceptance carries the
    whole-file bytes of the staged lockfile; nothing is written here. The
    delta gate judges them through the loader's lockfile overlay, and the
    final section of `_apply_locked` lands them with the body (§4).

    Called under the write lock, after the body patch is planned and before
    the candidate project is loaded. The order is the design's, and each step
    is the same code another command already runs:

    1. `sources.accept_plan` -- Slice A's `propose_payload` again, against the
       server's copy of the item, so authorization, the key still existing and
       still selectable, the name, the unit and the composed line are one rule
       with one spelling rather than a second copy of them; plus the check only
       an accept can make, that the body being saved names the pair.
    2. `citations.stage_source_pins` -- the extraction and the record, under
       fetch's non-`--update` policy, in the shape fetch writes.
    3. the staged bytes, exactly what `save_lockfile` would have produced.

    Step 2 reads the lockfile, so it is one section of the project's
    cross-process write lock: the file is the state, and a pin written by a
    fetch since the snapshot was built belongs in what this accept stages
    over. Step 1, which only reads the item and the source file, is not part
    of that section. Any failure of the lock -- a read-only root's
    `LockUnavailable` or any other `OSError` the filesystem can raise on its
    way in -- becomes this function's ordinary refusal like every other
    reason it returns: the whole `with` section is caught as an `OSError`,
    spelled the same way the landing section in `_apply_locked` spells it.
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

    lock_path = citations_mod.lockfile_path(before)
    try:
        with _disk_write_lock(before.root):
            # Fresh from disk, not the snapshot's copy: under this lock, the
            # file is the state, and a pin written by a fetch since the
            # snapshot was built belongs in what this accept stages over.
            #
            # Strictly `load_lockfile`, and a LockfileError becomes this
            # function's ordinary refusal reason rather than an exception:
            # the final section writes this file whole from the records it
            # read. Records it could not read would come back with one
            # record -- the key being accepted -- and every other pin in the
            # project silently gone. Refusing leaves both files untouched.
            try:
                records = citations_mod.load_lockfile(before)
            except citations_mod.LockfileError as exc:
                return None, str(exc)
            errors, pinned = citations_mod.stage_source_pins(
                before, records, [(p["path"], p["key"]) for p in plans],
                anchors=anchors, digests=digests,
            )
            if errors:
                return None, "; ".join(errors)
            try:
                with open(lock_path, "rb") as fh:
                    previous = fh.read()
            except OSError:
                previous = None
            staged = citations_mod.lockfile_text(records).encode("utf-8")
            lock = _LockfileStage(
                path=lock_path, root=before.root, previous=previous, staged=staged
            )
    except OSError as exc:
        return None, f"could not lock {before.root} for writing: {exc}"
    return (
        _Acceptance(
            lock=lock,
            pinned=tuple(pinned),
            plans=tuple(plans),
            anchors=anchors,
            digests=digests,
        ),
        None,
    )


# ------------------------------------------------------------------ resolution


def _find_item(project: Project, ref: str) -> Item | None:
    """The same spellings the read API accepts: the `project.items` dict key
    (a surrogate key, or a keyless item's provisional handle), then the
    display id, then the key via `item_by_ref`, then a retired id some item
    still records in `former_ids:`.

    This is the shared `serve.resolution.resolve_ref`, not a copy of it: the
    read route resolves the identical spelling list, and the two routes
    handing the browser different answers for the same ref is exactly the
    EDIT-03 bug. An ambiguous retired id resolves to nothing here -- the
    link-target callers refuse it as "no item ... to link to"; the write
    route's own entry (`_apply_locked`) asks the resolver directly and names
    the claimants in its refusal."""
    return resolution.resolve_ref(project, ref).item


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


def _conflict(who, ref, path, before, request, current_revision, patch_ref=None) -> Conflict:
    """The disk moved. Show the author their draft against the current file;
    offer nothing that merges.

    The server holds no draft text -- drafts live in the page (design,
    "Drafts: what the editor holds before it saves") -- so the draft shown is
    the current file with the requested operation applied: exactly what the
    save would have written, expressed against what is there now. When the
    current text cannot even be planned against (the item is gone, its span
    is now ambiguous), the conflict says so instead of inventing a diff.

    `patch_ref` is the item's current file spelling -- the key when it
    carries one, else the display id -- not the request's raw ref, and not
    a keyless row's provisional `~<relpath>:<line>` handle (the resolver's
    live handle for that ref is the `~` dict key, a view address the file
    does not hold). For a retired-id edit the retired spelling is not in
    the file, and planning against it would refuse and strip the conflict
    screen of its diff. The conflict still names the ref the author asked
    with.
    """
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return Conflict(who, ref, path, request.expected_revision, current_revision, None, "")

    plan = patcher.plan_patch(text, patch_ref or ref, request.op, path=path)
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


class _Moved(Exception):
    """Private signal from `_atomic_replace`: the file on disk at the moment
    the replace read it is not the bytes the caller planned against, so
    nothing was written. Raised, not returned: the return of
    `_atomic_replace` stays the reason string its callers already treat, and
    only a caller that passes `expected` can ever see this. It carries the
    sha256 of the bytes that read took in, so the revision a conflict names
    is the one the replace itself saw; the conflict's diff and draft come
    from a later read of the file by `_conflict`, which may see the file
    moved again -- the save is refused either way, so no bytes ride on the
    two agreeing."""

    def __init__(self, current: str) -> None:
        super().__init__(current)
        self.current = current


def _atomic_replace(
    path: str, payload: bytes, expected: str | None = None
) -> str | None:
    """Write `payload` to `path` atomically; return None on success, a reason
    on failure. A failed replacement leaves the original bytes in place: the
    temp file is discarded, and if the destination was somehow replaced and
    the re-read disagrees, the original bytes are put back -- when the
    restore itself lands. When it does not, the file is left as it was
    found (the bytes on disk are not this process's to name) and the reason
    says so.

    With `expected` (the sha256 of the bytes the caller planned against --
    the revision an apply's client saw, what a create read before it
    planned its append), the destination is checked against it on the read
    below, before a byte is written: a destination that moved since the
    caller's plan raises `_Moved` and writes nothing. The check consumes the
    exact bytes this function will replace and protect, which is the
    narrowest window a plain file allows -- the gap between this read and
    `os.replace` (the temp write and fsync in between) is the irreducible
    part, and no check-and-replace on a plain file closes it."""
    directory = os.path.dirname(path)
    tmp = None
    try:
        with open(path, "rb") as fh:
            original = fh.read()
    except OSError as exc:
        return f"could not read {path} before writing: {exc}"
    if expected is not None:
        current = hashlib.sha256(original).hexdigest()
        if current != expected:
            raise _Moved(current)

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
        if _restore(path, original):
            return f"could not re-read {path} after the write: {exc}; the original bytes were restored"
        # Both failures are named: the reread, and the restore that did
        # not land. What is ON the file is not claimed -- a failed
        # restore left it as the restore found it, and a writer that
        # bypasses the lock may have moved it since the write.
        return (
            f"could not re-read {path} after the write: {exc}, the original bytes "
            f"could not be restored, and {path} was left as it was found"
        )
    if written != payload:
        if _restore(path, original):
            return f"the bytes on disk after the write are not the bytes planned; {path} was restored"
        # What is known and nothing more: a mismatch was observed, the
        # restore did not land, and it left the file as it found it.
        # What is ON the file is not known -- this branch is reached
        # precisely because the bytes on disk are not this process's to
        # describe, and a re-read here would only be a fresh guess.
        return (
            f"the bytes on disk after the write are not the bytes planned, the "
            f"original bytes could not be restored, and {path} was left as it was found"
        )
    return None


def _discard_tmp(tmp: str) -> None:
    try:
        os.unlink(tmp)
    except OSError:
        pass


def _restore(path: str, original: bytes) -> bool:
    """Put `original` back at `path`, atomically: the bytes are staged in a
    temp file in the destination's own directory and swapped in, so a
    restore that fails partway leaves the destination exactly as it found
    it -- never truncated to zero bytes by the restore itself, the way an
    in-place `"wb"` open would leave it. Returns True when the swap landed
    and False when it did not; a caller that REPORTS the undo in a message
    must ask, not assume -- the apply path's `_restore_lockfile` reports
    nothing, so it reads no bool, by that helper's own design. The swap
    preserves the destination's
    mode, copied from the file itself -- which also narrows the old
    in-place write: a destination DELETED before the restore is not
    recreated -- the mode stat fails, the temp is discarded, the restore
    reports failure, and the file stays deleted. That shape is reachable
    wherever a destination can vanish between the caller's write and the
    restore: the reread-failure branch of `_atomic_replace` (a vanished
    file is one way the reread fails), and, per the same
    lock-bypassing-writer model the failure messages state, any writer
    outside the lock."""
    directory = os.path.dirname(path)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.refdes-tmp-", dir=directory)
        with os.fdopen(fd, "wb") as fh:
            mode = os.stat(path).st_mode & 0o777
            fh.write(original)
            fh.flush()
            os.fsync(fh.fileno())
            # the destination's (often world-readable) mode is applied only
            # once the contents are fully written: a crashed or partial
            # temp keeps mkstemp's 0600, so the file's PREVIOUS contents
            # are never left permissive in the directory mid-restore
            # (the PERM-OWNER-001 discipline; _atomic_replace and
            # _atomic_create keep their chmod-before-write ordering --
            # out of scope here, and the justification is narrower than
            # it looks: apply_edit and the create-append shapes stage
            # the WHOLE rewritten file, previous contents included, so
            # their crash windows predate this change)
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        tmp = None  # the swap consumed the temp file
    except OSError:  # the destination is untouched; the caller reports the failure
        if tmp is not None:
            _discard_tmp(tmp)
        return False
    return True


# ================================================================== creation
#
# docs/design/browser-editor.md, "Slice 3 -- creation". Identity comes from
# the modules that own it and nowhere else: the id is planned by
# `ids.plan_new_id` (pure) and reserved by `ids.reserve_id`, the key is
# minted by `keys.mint`, and every link is spelled by `links.composite_for`.
# The ledger reservation runs only after the file write succeeded, and any
# failure after the write rolls the file back -- a failed creation burns
# nothing. An append checks its destination against the bytes it planned
# onto on the very read its replace performs: bytes a writer outside the
# lock landed in the meantime re-plan the creation onto the current file or
# end it as a refusal, never a silent replacement reported as success --
# and a writer landing in the replace's own read-to-swap gap remains the
# limit no plain file can promise against (see `create_item`). Destinations
# are suggested but always overridable (Decisions,
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
    journal_warning: str = ""
    ok: bool = True

    @property
    def message(self) -> str:
        text = f"created: {self.item_id} ({self.type}) in {self.path}"
        if self.journal_warning:
            text += f" -- {self.journal_warning}"
        return text


# How many times one `create_item` call plans and attempts its append. A
# destination that another process wrote between this create's read of it and
# its replace is re-planned from a fresh load while attempts remain, then
# refused -- never silently replaced. Two attempts: enough for the ordinary
# one-shot concurrent append, bounded so a destination under steady outside
# writing ends in a refusal instead of an unbounded spin under the lock.
CREATE_DESTINATION_ATTEMPTS = 2


@dataclass(frozen=True)
class _DestinationMoved:
    """Private signal, never returned by `create_item`: the destination file
    holds different bytes now than the ones this creation read and planned
    its append onto. Carried instead of raised because a result value is how
    this module says "no"; `create_item` retries the whole plan while
    attempts remain and then spells the refusal. It is not one of the four
    public outcomes and must not leave this module."""

    who: str
    new_id: str
    rel: str
    path: str


def create_item(project_root: str, request: CreateRequest, config_path: str | None = None):
    """Create one item in the project at `project_root`, under the same
    per-project write lock every edit takes: two creates in flight cannot
    claim the same id, because the second plans against the state the first
    committed. `config_path` is threaded exactly as in `apply_edit`: the
    configured settings file when the launch used `-c/--config`, the default
    marker beside the root otherwise. Returns `Created` | `Refused` | `Invalid`.

    An append to an existing destination checks that file on the very read
    its replace performs (see `_create_locked` and `_atomic_replace`'s
    `expected` argument); a destination that moved between this create's
    plan and that read is re-planned from a fresh load up to
    `CREATE_DESTINATION_ATTEMPTS` times, and a destination still moving
    after that is refused with nothing written and no id reserved. What a
    standard `os.replace` cannot offer -- and this does not claim -- is a
    check and its replacement as one atomic step: between the replace's own
    read of the destination and its `os.replace` (the temp write's syscalls
    in between) a writer that does not take the project's write lock can
    still land, and its bytes are lost. The check shrinks a create's
    exposure from the whole candidate gate (two project loads, easily
    seconds) to that irreducible gap; it shares `apply_edit`'s posture (the
    apply threads its `expected_revision` into its replace too), and it is
    not a conflict guarantee against uncooperating writers. A destination
    planned as a new file needs none
    of this: `_atomic_create` links rather than replaces, so a file that
    appeared underneath is already a refusal."""
    root = os.path.abspath(project_root)
    config = os.path.abspath(config_path) if config_path else os.path.join(root, CONFIG_NAME)
    with write_lock_for(root):
        # A lock the filesystem will not host -- a read-only root's
        # `LockUnavailable`, or any other `OSError` on the way in -- is a
        # `Refused` here like on every other writing route in this module
        # (`_apply_locked`'s re-check section spells it the same way), not an
        # exception past the entry point that the caller's docstring says
        # returns only values.
        try:
            with _disk_write_lock(root):
                attempts = max(1, CREATE_DESTINATION_ATTEMPTS)
                for attempt in range(attempts):
                    result = _create_locked(config, request)
                    if not isinstance(result, _DestinationMoved):
                        return result
                    if attempt + 1 == attempts:
                        return Refused(
                            result.who,
                            result.new_id,
                            f"{result.rel} kept changing while this creation was "
                            f"being planned ({attempts} attempts); nothing was "
                            "written and no id was reserved -- retry the creation",
                            path=result.path,
                        )
        except OSError as exc:
            return Refused(
                request.who, "", f"could not lock {root} for writing: {exc}"
            )


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
                raw = fh.read()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return Refused(who, new_id, f"could not read {rel}: {exc}")
        # The rollback payload is the RAW bytes, never the decoded text:
        # `_restore` writes its payload to a binary file, so handing it a
        # `str` raised `TypeError` past the `except OSError`, out of a
        # function documented to return a result -- and an in-place write
        # of that failed payload left the destination truncated. The
        # decoded text is only what the append plans onto; the bytes are
        # what a failed creation restores.
        original = raw
        # The revision of exactly the bytes this append was planned against,
        # computed from the read itself rather than a second read of the
        # path: what this check can promise is that the bytes being replaced
        # are the bytes that were appended to, and it can only promise that
        # about the bytes it actually has. The check that consumes it is the
        # replace's own read, inside `_atomic_replace`, below.
        planned_revision = hashlib.sha256(raw).hexdigest()
        # The ending of the line the new block is being appended *after*, not
        # "CRLF if the file mentions CRLF anywhere": appending to a file whose
        # tail is LF used to hand the new item CRLF endings, because an
        # unrelated line higher up was CRLF. The block joins the end, so it
        # takes the end's style.
        eol = textio.append_ending(text)
        if dest["kind"] == "append-md":
            block = ["---", f"id: {new_id}", f"key: {key}", f"type: {request.type}", *body, "---", ""]
        else:
            ind = dest["indent"]
            block = [f"{ind}- id: {new_id}", f"{ind}  key: {key}"]
            if dest["type"] != request.type:
                block.append(f"{ind}  type: {request.type}")
            block.extend(f"{ind}  {ln}" for ln in body)
        head = "" if text.endswith("\n") else eol
        # Pure append: every existing byte of the file stays exactly where
        # it was -- the fidelity contract, trivially satisfied.
        new_text = text + head + eol.join(block) + eol

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

    # The journal, armed with the destination's exact bytes (None for a new
    # file) before the write runs, cleared after the id is reserved -- the
    # same step 6/9 pair `apply_edit`'s final section runs.
    journal_rel = _journal_relpath(before.root, path)
    journal_warning = None
    payload = new_text.encode("utf-8")
    if journal_rel is not None:
        reason = _journal_arm(before.root, journal_rel, original, payload)
        if reason is not None:
            return Refused(who, new_id, reason, path=path)

    if dest["kind"] == "new-md":
        failure = _atomic_create(path, payload)
    else:
        # The gate above cannot see writes to the destination's own bytes;
        # the check consumes the replace's own read (see `_atomic_replace`),
        # so a destination that moved since this append was planned writes
        # nothing, reserves nothing, and re-plans from a fresh load. The
        # read-to-swap gap that remains is irreducible on a plain file --
        # see `create_item`'s docstring.
        try:
            failure = _atomic_replace(path, payload, planned_revision)
        except _Moved:
            # The journal describes a write that lands nowhere; clear it
            # with the attempt, so the retry's own arm does not find it
            # pending.
            _journal_clear(before.root)
            return _DestinationMoved(who, new_id, rel, path)
    if failure is not None:
        warning = _journal_clear(before.root)
        return Refused(
            who,
            new_id,
            failure if warning is None else f"{failure}; {warning}",
            path=path,
        )

    # The reservation is the last step, so nothing is burned unless the
    # item is on disk; a failed reservation rolls the file back so the id
    # stays as unburned as it was.
    try:
        ids.reserve_id(before, new_id)
    except OSError as exc:
        if _rollback(path, original):
            warning = _journal_clear(before.root)
            reason = (
                f"the id ledger could not be written ({exc}); {rel} was rolled back "
                f"and {new_id} was not reserved"
            )
            return Refused(
                who, new_id, reason if warning is None else f"{reason}; {warning}", path=path
            )
        # The journal armed for this write is the whole recovery story of a
        # rollback that could not run: the file stands with the create's
        # bytes and the journal holds the originals. Say so -- the next
        # load will refuse until `refdes recover` restores them.
        kept = (
            "; the editor transaction journal is kept: run 'refdes recover' "
            f"to restore {rel}"
        )
        # Known facts only, in the shape the rollback actually took. For
        # the append shapes the rollback is a restore: a failed restore
        # touches nothing, so the file was left as the restore found it.
        # For the new-md shape the rollback is an unlink: a failed unlink
        # touched nothing, so the created file stands. What is ON the file
        # is not asserted in either shape: the create's write landed, but
        # a writer outside the lock can have moved the destination since,
        # and the rollback never re-reads to know.
        if original is None:
            return Refused(
                who,
                new_id,
                f"the id ledger could not be written ({exc}); {new_id} was not "
                f"reserved, and {rel} was not removed: the file the create "
                f"wrote stands, the failed rollback touched nothing{kept}",
                path=path,
            )
        return Refused(
            who,
            new_id,
            f"the id ledger could not be written ({exc}); {new_id} was not "
            f"reserved, and {rel} could not be restored: the creation's bytes "
            f"were not rolled back, and the file was left as it was found{kept}",
            path=path,
        )

    journal_warning = _journal_clear(before.root)

    return Created(
        who=who,
        item_id=new_id,
        key=key,
        type=request.type,
        path=path,
        revision=file_revision(path),
        diagnostics=tuple(after.diagnostics),
        journal_warning=journal_warning,
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


def suggest_destination(
    project: Project,
    type_name: str,
    board: str | None = None,
    workspace: str | None = None,
) -> str:
    """Suggest, never decide: prefer a file of this type in the selected
    board/workspace. Under the workspace layout, an empty selected workspace
    gets a new Markdown file inside its own directory instead of borrowing
    another workspace's file and file-level defaults. The explicit override
    always wins (Decisions, "Creation destination: suggest plus override")."""
    files = [
        item.source_file.replace("\\", "/")
        for item in project.local_items
        if item.type == type_name and item.source_file
    ]
    if board or workspace:
        same_scope = [
            item.source_file.replace("\\", "/")
            for item in project.local_items
            if item.type == type_name
            and item.source_file
            and (not board or item.board == board)
            and (not workspace or item.workspace == workspace)
        ]
        if same_scope:
            files = same_scope
        elif workspace and project.item_layout == "workspace" and workspace in project.workspaces:
            # The scope is empty, so no existing file can donate its defaults
            # or prefix. Keep the workspace's registered path even when the
            # caller did not choose a board; a board choice adds its own path.
            scope = f"items/{project.workspaces[workspace].path_segment}"
            if board and board in project.boards:
                scope += f"/{project.boards[board].path_segment}"
            return f"{scope}/{type_name}s.md"
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
        fields = request.fields or {}
        dest = suggest_destination(
            project,
            request.type,
            board=fields.get("board"),
            workspace=fields.get("workspace"),
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
        # `_fence_warnings` is the loader's to report; the server only edits
        # files of the project it loaded, which split and announced them.
        blocks, _errors, _duplicates, _fence_warnings = md_front_matter_blocks(text.split("\n"))
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


def _journal_relpath(root: str, path: str) -> str | None:
    """The journal's spelling of `path`: project-relative, or None for a
    target outside the root (a symlinked item), which is not journaled."""
    rel = os.path.relpath(path, root).replace("\\", "/")
    return None if rel == "." or rel.startswith("..") else rel


def _journal_arm(root: str, rel: str, original: bytes | None, replacement: bytes) -> str | None:
    """Arm the transaction journal for one file's write (design step 6:
    journal before replacing). Returns a refusal reason -- the write lands
    nowhere when the journal cannot be armed, because an unarmed write is
    the kill-with-no-recovery the journal exists to end. `None` means the
    journal is armed and the write may proceed.

    `rel` is a destination this module resolved under the project root
    (never the `.refdes` control namespace -- `begin` refuses those, and
    the lockfile/ledger writes have their own documented recovery story).
    """
    try:
        editor_journal.begin(root, [editor_journal.Entry(rel, original, replacement)])
    except editor_journal.JournalPending as exc:
        return str(exc)
    except OSError as exc:
        return (
            f"the save journal could not be written: {exc}; the write landed "
            "nowhere. A leftover .refdes/editor-transaction/ from an earlier "
            "interrupted save is restored by 'refdes recover'"
        )
    return None


def _journal_clear(root: str) -> str | None:
    """Disarm and remove the journal after a save landed (design step 9).
    Returns a warning on failure: the journal surviving a landed save is
    the design's visible condition -- every project-loading command
    refuses until `refdes recover` clears it (by rolling the save back).
    """
    try:
        editor_journal.complete(root)
    except OSError as exc:
        return (
            "the save landed, but the editor transaction journal could not "
            f"be cleared: {exc}. Run 'refdes recover' to clear it -- it "
            "restores the journaled files to their pre-save state"
        )
    return None


def _rollback(path: str, original: bytes | None) -> bool:
    """Undo a completed write when a later step failed: restore the previous
    bytes, or remove the file that did not exist before. Returns True when
    the undo is known to have landed; False means the destination is not
    what it was. A caller that reports the undo in a message must say so
    rather than claim a rollback that did not happen; the apply path's
    `_restore_lockfile` deliberately does not report it -- it swallows the
    bool for the inert-pin residue its own docstring names."""
    if original is None:
        try:
            os.unlink(path)
        except OSError:
            return False
        return True
    return _restore(path, original)


def preview_creation(
    project: Project,
    type_name: str,
    *,
    explicit_id: str | None = None,
    board: str | None = None,
    workspace: str | None = None,
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
        project, type_name, board=board, workspace=workspace
    )
    # Resolved exactly as `create_item` will resolve it, so a destination
    # file's own `defaults.prefix` reaches the previewed id too -- this form
    # promises that the id shown before saving is the id the item gets, and a
    # prefix the preview cannot see is one more way that promise breaks.
    # A destination the create would refuse still previews its bare type
    # prefix; the refusal is the save's to report, not the preview's to hide.
    preview_fields = {}
    if board is not None:
        preview_fields["board"] = board
    if workspace is not None:
        preview_fields["workspace"] = workspace
    _rel, resolved, _why = _resolve_destination(
        project,
        CreateRequest(
            who="preview",
            type=type_name,
            fields=preview_fields,
            destination=dest,
        ),
    )
    prefix_hint = str((resolved or {}).get("defaults", {}).get("prefix") or "")
    new_id, reason = ids.plan_new_id(
        project, type_name, explicit_id=explicit_id, prefix_hint=prefix_hint
    )
    exists = os.path.exists(os.path.join(project.root, dest.replace("/", os.sep)))
    return {"id": new_id, "reason": reason, "destination": dest, "destination_exists": exists}
