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
   (`loader.load_readonly`), which is also where the before-diagnostics come
   from;
3. compare the file's current content revision with the `expected_revision`
   the client saw. A mismatch is a `Conflict`: the current span text and a
   unified diff of the draft against disk come back, and **nothing is merged**
   -- the design's "draft, refuse, diff -- never merge";
4. refuse a sealed item under the lock (the mutation endpoint repeats the
   check the UI cannot be trusted to make);
5. plan the edit with `patcher`, whose own fidelity proof means a `Refusal`
   here is the patcher saying "I cannot bound this edit" -- also a result;
6. run the **delta** diagnostic gate: load the whole project again with the
   candidate text as a source overlay and compare error sets. Only a *newly
   introduced* error blocks, or a pre-existing error attributed to the field
   or body being edited and still present. An unrelated pre-existing error on
   an already-broken item never blocks the repair that is the reason the
   editor exists;
7. write atomically -- temp file in the same directory, flush, fsync,
   `os.replace` -- then re-read and confirm the bytes are the planned bytes.

Nothing here writes into `.refdes/`, mints a key, or creates an item: the
loads are `load_readonly`, and only an existing field or body is addressed.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import threading
from dataclasses import dataclass
from typing import Any

from .. import links, loader, patcher, seal
from ..model import CHECK_VIOLATION, Diagnostic, ERROR, Item, Project
from ..patcher import AddLink, PatchPlan, Refusal, RemoveLink, SetBody, SetField

CONFIG_NAME = "refdes-project.yaml"


# ------------------------------------------------------------------- requests


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
    interleaving saves; cross-process protection is the content revision, and
    the crash journal is a later slice."""
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


def _apply_locked(config: str, request: EditRequest):
    who, ref = request.who, request.ref
    try:
        before = loader.load_readonly(config)
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

    try:
        after = loader.load_readonly(config, overlay={path: new_text})
    except Exception as exc:  # noqa: BLE001 - a candidate that will not load is a result
        return Refused(
            who, ref, f"the edited project did not load: {type(exc).__name__}: {exc}", path=path
        )

    blocking = _blocking_diagnostics(before, after, item, request.op)
    if blocking:
        return Invalid(who, ref, tuple(blocking), path=path)

    failure = _atomic_replace(path, new_text.encode("utf-8"))
    if failure is not None:
        return Refused(who, ref, failure, path=path)

    return Applied(
        who=who,
        ref=ref,
        path=path,
        revision=file_revision(path),
        plan=plan,
        diagnostics=tuple(after.diagnostics),
    )


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
    tmp = os.path.join(directory, f".{os.path.basename(path)}.refdes-tmp")
    try:
        with open(path, "rb") as fh:
            original = fh.read()
    except OSError as exc:
        return f"could not read {path} before writing: {exc}"

    fd = None
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, os.stat(path).st_mode & 0o777)
        with os.fdopen(fd, "wb") as fh:
            fd = None  # fdopen owns it from here
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
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
