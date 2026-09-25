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
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

from .. import dates, ids, keys, links, loader, patcher, scaffold, seal, textio
from ..model import CHECK_VIOLATION, Diagnostic, ERROR, Item, Project
from ..parse import yaml_safe_load
from ..patcher import AddLink, PatchPlan, Refusal, RemoveLink, SetBody, SetField
from . import security

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
# form enforces, one constant shared with the API).
NON_SCALAR_FIELD_TYPES = frozenset({"list", "checks", "citations", "options"})


@dataclass(frozen=True)
class CreateRequest:
    """One creation intent. `fields` maps declared field names (plus
    `board`/`workspace`) to scalar values; `id` is an optional explicit
    override -- omitted means "next free"; `destination` is a
    project-relative path under `items/`, omitted means "suggested";
    `amends` names a sealed log entry this new entry corrects -- the sealed
    entry itself is never touched, the correction is pure creation with an
    `amends:` composite (docs/design/living-notes.md, "corrections are new
    entries"). `who` is the same permissions seam as `EditRequest`."""

    who: str
    type: str
    fields: dict
    id: str | None = None
    destination: str | None = None
    amends: str | None = None


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
        return _create_locked(config, request)


def _create_locked(config: str, request: CreateRequest):
    who = request.who
    try:
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

    new_id, reason = ids.plan_new_id(before, request.type, explicit_id=request.id)
    if reason is not None:
        return Refused(who, "", reason)
    key = _fresh_key(before)

    link_lines = []
    if request.amends:
        line, reason = _amends_line(before, spec, request.amends)
        if reason is not None:
            return Refused(who, new_id, reason)
        link_lines.append(line)

    body, reason = _item_lines(spec, fields, link_lines)
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
    a reason."""
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
    if ext == ".md":
        return rel, {"kind": "append-md"}, None

    # An existing YAML list file: it must be a mapping with a block-style
    # `items:` list, and that list must be the last block in the file --
    # anything else means a safe append (every existing byte untouched)
    # cannot be promised, which is a refusal, not a guess.
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        data = yaml_safe_load(text)
    except (OSError, UnicodeDecodeError) as exc:
        return None, None, f"could not read {rel}: {exc}"
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
    file_type = defaults.get("type") if isinstance(defaults, dict) else None
    return rel, {"kind": "append-yaml", "indent": indent or "  ", "type": file_type}, None


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


def _item_lines(spec, fields: dict, link_lines: list[str]):
    """The new item's YAML lines after id/key: board/workspace, then the
    initial field set -- scaffold.initial_field_values, the same resolution
    `refdes new` scaffolds -- emitted through the patcher's round-trip-verified
    scalar emitter, then any link lines."""
    lines: list[str] = []
    for name in ("board", "workspace"):
        if name in fields:
            text, _note = patcher._emit_scalar(
                fields[name], style=None, indent=0, eol="\n", allow_block=False, original=""
            )
            if text is None:
                return None, f"the value for {name!r} cannot be emitted as YAML"
            lines.append(f"{name}: {text}")
    for fname, value in scaffold.initial_field_values(spec, fields).items():
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
    new_id, reason = ids.plan_new_id(project, type_name, explicit_id=explicit_id)
    dest = (destination or "").strip().replace("\\", "/") or suggest_destination(
        project, type_name, board=board
    )
    exists = os.path.exists(os.path.join(project.root, dest.replace("/", os.sep)))
    return {"id": new_id, "reason": reason, "destination": dest, "destination_exists": exists}
