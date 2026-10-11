"""Append-only enforcement for design log entries.

An engineering notebook is only worth anything if yesterday's page still says what
it said yesterday. Entries are sealed the first time they are built; after that,
changing one is a build error. Corrections are made by appending a new entry that
`amends` the old one — the same convention as a paper notebook, where you strike
through and initial rather than erase.

Nothing here can *prevent* an edit; it detects one. That is the honest limit of a
file-based tool, and detection is what actually matters.

Seals are stored per board -- "no one works on everything at once", so accepting
an edit on one board's entries (`--reseal <board>`) must never touch another's.
`.refdes/log-seal.yaml` is the base file: it holds seals for items that resolve
to no board (unchanged from before boards existed, and the *only* file used by a
project with no `boards:` registry at all), plus, transitionally, any entry an
older, single-file build sealed for an item that has since come to live on a
board it hasn't been physically migrated out to yet -- see `verify()`.

All of the above is the *build* policy, every append-only type's default. A
type that declares `sealing: history` (living-notes plan §H5, Q1) is backed by
captured history instead: it is never sealed, an edit to one of its entries is
the history store's "edited after captured" warning rather than a build error,
and `--reseal` has nothing to do for it. Seal files that already mention its
entries are still read -- never rewritten, never deleted -- as legacy-seal
markers: a recorded hash only, whose original content was not captured. The
word "sealed" stays with the build-time lock and those markers alone
(vocabulary review P5); the history-backed state is "captured".
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone

import yaml

from . import keys as keys_mod
from . import model
from .model import SEALING_BUILD, SEALING_HISTORY, Item, Project
from .parse import yaml_safe_load

SEAL_FILE = ".refdes/log-seal.yaml"
RESEAL_ALL = "*"  # sentinel: --reseal with no board name means "every board"

_HEADER = (
    "# Refdes append-only seals. Each entry records the content hash of a log\n"
    "# entry at its first build or latest accepted reseal. Editing it fails the\n"
    "# build; append a new entry that `amends` it instead.\n"
    "# reseals records deliberate edits/removals; preserve every past event.\n"
)


def seal_path(project: Project, board: str = "") -> str:
    """`.refdes/log-seal.yaml` for board `""`; `.refdes/log-seal-<board>.yaml`
    otherwise -- the same `-<board>` suffix convention every other per-board
    report file already uses.
    """
    name = f"log-seal-{board}.yaml" if board else "log-seal.yaml"
    return os.path.join(project.root, ".refdes", name)


def _reseal_hint(board: str) -> str:
    """The command to run when a sealed-entry violation was deliberate.

    Spells out `refdes build` because both verify() callers print the same
    error and only one of them -- `refdes build` -- has `--reseal`. Under
    `refdes check`, a bare `--reseal` is not advice, it is a usage dump and
    an exit code 2: the command being suggested is one the printing command
    does not accept.
    """
    return f"refdes build --reseal {board}" if board else "refdes build --reseal"


SealValue = str | dict[str, object]
Seals = dict[str, SealValue]


def _seal_parts(
    record_id: str, value: SealValue
) -> tuple[str | None, str, str, int | None]:
    """Return key, recorded display id, hash, and format for either shape."""
    if isinstance(value, Mapping):
        entry = dict(value)
        display_id = entry.get("id")
        if isinstance(display_id, str) and display_id:
            key = record_id
        else:
            key = None
            display_id = record_id
        recorded = str(entry.get("hash", ""))
        raw_format = entry.get("hash_format")
        try:
            hash_format = int(raw_format) if raw_format is not None else None
        except (TypeError, ValueError):
            hash_format = -1
        return key, display_id, recorded, hash_format
    return None, record_id, str(value), None


def _find_seal(
    seals: Seals, item: Item, live_keys: set[str]
) -> tuple[str, SealValue, str, int | None] | None:
    """Find an item's seal by surrogate, recorded display id, then legacy id.

    The recorded-id pass is corruption-sensitive: if the live item's key was
    changed, the old key-keyed seal still belongs to this display id. It may
    claim that item only when no live local item owns the recorded key; a live
    owner means the seal belongs to that owner and its recorded id is merely
    the pre-rename label. This prevents both laundering and rename-then-reuse
    false positives.
    """
    if item.key:
        keyed = seals.get(item.key)
        if keyed is not None:
            key, _display_id, recorded, hash_format = _seal_parts(item.key, keyed)
            if key == item.key:
                return item.key, keyed, recorded, hash_format
    for record_id, value in seals.items():
        key, display_id, recorded, hash_format = _seal_parts(record_id, value)
        if key is not None and key not in live_keys and display_id == item.id:
            return record_id, value, recorded, hash_format
    legacy = seals.get(item.id)
    if legacy is None:
        return None
    key, _display_id, recorded, hash_format = _seal_parts(item.id, legacy)
    if key is not None:
        return None
    return item.id, legacy, recorded, hash_format


def _seal_key_mismatch(record_id: str, value: SealValue, item: Item) -> str | None:
    recorded_key, _display_id, _hash, _format = _seal_parts(record_id, value)
    if recorded_key is not None and recorded_key != item.key:
        return recorded_key
    return None


def _with_seal_hash(value: SealValue, new_hash: str, hash_format: int) -> SealValue:
    if not isinstance(value, Mapping):
        return new_hash
    entry = dict(value)
    entry["hash"] = new_hash
    entry["hash_format"] = hash_format
    return entry


def _load_seal_data(project: Project, board: str = "") -> dict:
    path = seal_path(project, board)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml_safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: seal file must be a mapping")
    for record_id, value in (data.get("sealed") or {}).items():
        if isinstance(value, Mapping) and value.get("id"):
            keys_mod.report_storage_key(project, record_id, path)
    for event in data.get("reseals", []):
        if isinstance(event, dict) and event.get("key"):
            keys_mod.report_storage_key(project, event["key"], path)
    events = data.get("reseals", [])
    if not isinstance(events, list) or any(
        not isinstance(event, dict)
        or not {"id", "action", "old_hash", "new_hash", "occurred_at"} <= event.keys()
        or event["action"] not in ("edit", "remove")
        or any(
            not isinstance(event[field], str) or not event[field]
            for field in ("id", "old_hash", "occurred_at")
        )
        or (
            event["action"] == "edit"
            and (not isinstance(event["new_hash"], str) or not event["new_hash"])
        )
        or (event["action"] == "remove" and event["new_hash"] is not None)
        for event in events
    ):
        raise ValueError(f"{path}: malformed reseal history; refusing to discard it")
    return data


def load_seals(project: Project, board: str = "") -> Seals:
    data = _load_seal_data(project, board)
    return {
        str(record_id): dict(value) if isinstance(value, Mapping) else str(value)
        for record_id, value in (data.get("sealed") or {}).items()
    }


def load_reseals(project: Project, board: str = "") -> list[dict]:
    """Accepted reseal events, in append order, independent of live items."""
    return _load_seal_data(project, board).get("reseals", [])


def reseal_history(project: Project) -> list[tuple[str, dict]]:
    """All durable events, including files for boards no longer declared."""
    directory = os.path.dirname(seal_path(project))
    boards = {""} | set(project.boards)
    if os.path.isdir(directory):
        for name in os.listdir(directory):
            if name.startswith("log-seal-") and name.endswith(".yaml"):
                boards.add(name[len("log-seal-") : -len(".yaml")])
    return [(board, event) for board in sorted(boards) for event in load_reseals(project, board)]


def format_seals(seals: Seals, reseals: list[dict] | None = None) -> str:
    """Serialize seals identically for adoption planning and persistence."""
    data = {"sealed": seals}
    if reseals:
        data["reseals"] = reseals
    return _HEADER + yaml.safe_dump(data, sort_keys=True, default_flow_style=False)


def save_seals(
    project: Project, seals: Seals, board: str = "", *, events: list[dict] | None = None
) -> bool:
    """Replace active seals and append events together; never erase history.

    Returns whether the seals landed. A read-only tree -- a frozen CI
    checkout, a read-only bind mount -- is a condition of the filesystem and
    not of the project, so the refusal is recorded as a diagnostic naming the
    file rather than raised, and the *caller* decides what it means:

    - `build` (via `verify`) goes on and exits non-zero on the error, because
      a site render is still owed to the user and the entries being unsealed
      is a finding about the project, not an aborted command.
    - An explicit write the user asked for -- `refdes revise`, which carries
      a renamed entry's seal hash forward -- must NOT go on. That hash is the
      only record that the rename was not an edit to a sealed entry, so
      losing it makes the next `build` report a deliberate rename as an
      append-only violation. `revise._carry_forward_seals` checks this
      return value and refuses, naming the file.
    """
    path = seal_path(project, board)
    history = load_reseals(project, board) + (events or [])
    payload = format_seals(seals, history)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # A failed write must leave both the old hash and its history intact.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=os.path.dirname(path),
                prefix=".log-seal-", suffix=".tmp", delete=False,
            ) as fh:
                temporary = fh.name
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            if os.path.exists(path):
                os.chmod(temporary, os.stat(path).st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
    except OSError:
        return _record_seal_write(project, path)
    return True


def _record_seal_write(project: Project, path: str) -> bool:
    """One seal file the filesystem would not accept. Always False.

    `build` is the command that seals, so this is an *error*, not the
    load-time warning `schema_json`/`revise` use for a file it merely
    refreshed: an entry that is not sealed has no append-only protection at
    all (`refdes check --help` says so outright, and docs/design-log.md §
    Append-only is where that promise lives), and a build that reported
    success over it would be claiming the protection it did not write. The
    site render still happens and still says what it rendered -- it does not
    read the seal file -- so the diagnostic, not an abort, is what carries
    the failure; `_report()` turns the error into exit 1.
    """
    rel = os.path.relpath(path, project.root).replace("\\", "/")
    project.load_writes.blocked.append(rel)
    project.error(
        model.read_only_refusal(
            "the entries in it are NOT sealed, so they have no append-only "
            "protection until a build can write this file"
        ),
        file=rel,
    )
    return False


def _reseal_event(
    display_id: str, key: str | None, recorded: str, new_hash: str | None,
    hash_format: int | None,
) -> dict:
    from . import build as build_mod

    event = {
        "action": "edit" if new_hash is not None else "remove",
        "id": display_id,
        "old_hash": recorded,
        "new_hash": new_hash,
        "old_hash_format": hash_format,
        "new_hash_format": build_mod.HASH_FORMAT if new_hash is not None else None,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    if key:
        event["key"] = key
    return event


def _matches_sealed_hash(
    recorded: str, item: Item, project: Project, hash_format: int | None = None
) -> tuple[bool, str]:
    """Compare a stored seal hash against `item`'s current one, folding in
    the hash-format migration (docs/design/keys.md §5) so a seal written
    under an earlier hash definition does not read as tampered purely
    because the definition changed underneath it.

    Returns ``(matches, hash_to_store)``. Two outcomes:

    - ``hash_format`` known (a key-keyed entry's own recorded format): the
      recorded hash must match ``keys.hash_in_format(item, project,
      hash_format)`` -- the one shared reconstruction every hash-format
      migration site uses, not a copy of it.
    - ``hash_format`` unknown (a legacy scalar seal, with no field for a
      format marker of its own): try the newest definition first, then each
      older one in turn (docs/design/keys.md §5(c)) -- the first that
      matches identifies an unchanged entry, and a successful write upgrades
      the scalar to the current hash.

    Neither permitted definition matching is a real edit; the original hash
    is returned with ``matches=False``.

    The deferred ``build`` import avoids a cycle: ``build.py`` imports this
    module for ``verify()``, while this comparison needs ``build.HASH_FORMAT``.
    By call time build has finished importing and Python caches the module.
    """
    from . import build as build_mod

    formats = (hash_format,) if hash_format is not None else tuple(range(build_mod.HASH_FORMAT, 0, -1))
    for fmt in formats:
        expected = keys_mod.hash_in_format(item, project, fmt)
        if expected is not None and recorded == expected:
            return True, item.content_hash
    return False, recorded


def history_backed(project: Project, type_name: str) -> bool:
    """Whether ``type_name`` is an append-only type backed by captured history
    (``sealing: history``) rather than the build-time lock."""
    spec = project.types.get(type_name)
    return bool(spec and spec.append_only and spec.sealing == SEALING_HISTORY)


def append_only_items(
    project: Project, board: str | None = None, sealing: str | None = None
) -> list[Item]:
    """Local append-only items, optionally narrowed to one board's own ("" included)
    and to one ``sealing`` policy (``None``: every append-only type)."""
    items = [
        item
        for item in project.local_items
        if project.types.get(item.type) and project.types[item.type].append_only
    ]
    if sealing is not None:
        items = [i for i in items if project.types[i.type].sealing == sealing]
    if board is not None:
        items = [i for i in items if i.board == board]
    return items


def is_sealed(project: Project, item: Item) -> bool:
    """Whether ``item`` already has an append-only seal in any board file.

    Follows freezing happens before board resolution in the normal load path,
    so it must inspect every declared board rather than relying on
    ``item.board``. A legacy base-file seal remains authoritative until a
    writable build migrates it to its board-specific file.

    Always False for a history-backed type (``sealing: history``): a seal
    record that mentions one of its entries is a legacy-seal marker, not a
    lock, so nothing that refuses an edit to a sealed entry -- the bare
    ``follows:`` freeze, the editor, an upload, a calc rewrite -- refuses it.
    """
    spec = project.types.get(item.type)
    if spec is None or not spec.append_only or spec.sealing != SEALING_BUILD:
        return False
    live_keys = {candidate.key for candidate in project.local_items if candidate.key}
    for board in sorted({""} | set(project.boards)):
        if _find_seal(load_seals(project, board), item, live_keys) is not None:
            return True
    return False


def _boards_in_play(project: Project, sealing: str | None = None) -> list[str]:
    """Every board key ("" included) at least one append-only item resolves to."""
    return sorted({item.board for item in append_only_items(project, sealing=sealing)})


def verify(project: Project, write: bool = False, reseal: str | None = None) -> None:
    """Check sealed entries per board, and seal any new ones when requested.

    A new entry with an ERROR diagnostic attributed to it in this build is
    not sealed -- it is reported once and seals on the first later build
    where it is error-free, so fixing what the build complained about never
    collides with a seal made over the broken text.

    ``reseal`` is ``None``/falsy (verify only), ``RESEAL_ALL`` (accept edits
    on every board), or one registered board key (accept edits only for that
    board). A changed surrogate key is corruption, not an ordinary edit, and
    is never accepted by resealing.

    Both legacy display-id-keyed scalars and §5 surrogate-keyed dictionaries
    are accepted, including mixtures in one file. New seals use the keyed
    shape after the project records explicit adoption.

    Pre-board history is migrated lazily and lookback-only: when an item now
    resolves onto a board but its seal remains in the base file, verification
    still checks that old entry rather than treating the item as new. Only a
    write-enabled build moves it into the board file and prunes the base copy;
    read-only ``check`` therefore never mutates seal storage while retaining
    the same tamper detection.

    Everything above applies to build-sealed types only. History-backed types
    (``sealing: history``) are never sealed, never hash-checked, and never
    resealed here: their seal records are left exactly as they are on disk
    (see ``_verify_history_backed``).
    """
    from . import build as build_mod

    base = load_seals(project, board="")
    base_changed = False
    base_events: list[dict] = []
    live_keys = {item.key for item in project.local_items if item.key}
    # An entry this very build flagged with an ERROR is never sealed: the
    # author is told to fix it, and sealing it now would turn that fix into
    # "modified since it was sealed" -- following the error's own instruction
    # would punish them. Per-entry, not per-build: an error elsewhere does
    # not freeze healthy entries out of sealing. Only attributed errors
    # count; project-level diagnostics belong to no entry.
    errored_items = {d.item_id for d in project.errors if d.item_id}

    for board in _boards_in_play(project, sealing=SEALING_BUILD):
        entries = append_only_items(project, board=board, sealing=SEALING_BUILD)
        changed = False
        events: list[dict] = [] if board else base_events
        if board:
            seals = load_seals(project, board)
            for item in entries:
                if _find_seal(seals, item, live_keys) is not None:
                    continue
                inherited = _find_seal(base, item, live_keys)
                if inherited is None:
                    continue
                record_id, value, _recorded, _hash_format = inherited
                seals[record_id] = value
                changed = True
        else:
            seals = base

        reseal_here = reseal == RESEAL_ALL or reseal == board
        for item in sorted(entries, key=lambda i: i.id):
            found = _find_seal(seals, item, live_keys)
            if found is None:
                if write:
                    if item.id in errored_items:
                        project.warn(
                            f"{item.id} was not sealed because it has errors; "
                            "it will be sealed on the first clean build",
                            file=item.source_file, line=item.source_line,
                            item_id=item.id,
                        )
                    elif keys_mod.is_adopted(project) and item.key:
                        seals[item.key] = {
                            "id": item.id,
                            "hash": item.content_hash,
                            "hash_format": build_mod.HASH_FORMAT,
                        }
                    else:
                        seals[item.id] = item.content_hash
                    changed = True
                continue
            record_id, value, recorded, hash_format = found
            recorded_key = _seal_key_mismatch(record_id, value, item)
            if recorded_key is not None:
                project.seal_violations.append(item.id)
                if not item.key:
                    # The key was deleted, not changed: the deleted-key report
                    # (§6, 2026-09-15) owns this item and says so with the
                    # remedies. Never re-seal over it either.
                    continue
                project.error(
                    f"{item.id} is append-only and its key changed since it was "
                    f"sealed: was {recorded_key!r}, now {item.key!r}. A key never "
                    "changes legitimately; restore the sealed key from history.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            ok, upgraded = _matches_sealed_hash(recorded, item, project, hash_format)
            if ok:
                if upgraded != recorded and write:
                    seals[record_id] = _with_seal_hash(
                        value, upgraded, hash_format=build_mod.HASH_FORMAT
                    )
                    changed = True
                continue

            if reseal_here:
                message = (
                    "resealed after an edit to a sealed entry"
                    if write else "would reseal after an edit to a sealed entry"
                )
                record_notice = (
                    "This is recorded in the audit output."
                    if write else "No seal or audit record was written."
                )
                project.warn(
                    f"{message} (was {recorded}, now {item.content_hash}). {record_notice}",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                seals[record_id] = _with_seal_hash(
                    value, item.content_hash, hash_format=build_mod.HASH_FORMAT
                )
                changed = True
                if write:
                    events.append(_reseal_event(
                        item.id, item.key, recorded, item.content_hash, hash_format
                    ))
            else:
                project.seal_violations.append(item.id)
                project.error(
                    f"{item.id} is append-only and has been modified since it was "
                    f"sealed. Append a new entry with `amends: [{item.id}]` instead, "
                    f"or run with {_reseal_hint(board)} if the edit is deliberate.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )

        if board:
            if write and changed:
                save_seals(project, seals, board, events=events)
            if write:
                for item in entries:
                    inherited = _find_seal(base, item, live_keys)
                    if inherited is not None:
                        del base[inherited[0]]
                        base_changed = True
        elif changed:
            base_changed = True

    _verify_history_backed(project, base, reseal=reseal)

    if _report_deleted(project, base, write=write, reseal=reseal, base_events=base_events):
        base_changed = True

    if write and base_changed:
        save_seals(project, base, board="", events=base_events)


def _seal_file_label(project: Project, board: str) -> str:
    return os.path.relpath(seal_path(project, board), project.root).replace("\\", "/")


def _verify_history_backed(project: Project, base: Seals, reseal: str | None) -> None:
    """The ``sealing: history`` half of ``verify()``. Read-only: it never writes,
    upgrades, migrates or prunes a seal record.

    An entry of a history-backed type is not hash-checked here at all -- an
    edit to it is ``build.warn_edited_after_captured``'s warning, never a build
    error. Two things still apply to it:

    - A legacy seal record that names the entry under a *different* surrogate
      key is key corruption, not an edit, and stays the error it is for a
      build-sealed entry: a key never changes legitimately, whatever backs the
      entry's content. (A deleted key is the deleted-key report's, as above.)
    - ``--reseal`` is accepted and says it has nothing to do (plan Q2) -- it
      captures nothing, and the legacy seal records stay byte-for-byte as
      they are. A silent no-op would leave a documented habit looking like it
      had worked (plan R7).
    """
    if reseal:
        for tname in sorted(t for t in project.types if history_backed(project, t)):
            project.warn(
                f"--reseal: sealing no longer applies to the {tname!r} type; "
                "nothing was rewritten. Its legacy seal records are kept as they "
                "are, and an edit to a captured entry is reported as edited "
                "after captured instead."
            )

    entries = append_only_items(project, sealing=SEALING_HISTORY)
    if not entries:
        return
    seal_files = [("", base)] + [
        (board, load_seals(project, board)) for board in sorted(project.boards)
    ]
    live_keys = {item.key for item in project.local_items if item.key}
    for item in sorted(entries, key=lambda i: i.id):
        if not item.key:
            continue
        for board, seals in seal_files:
            found = _find_seal(seals, item, live_keys)
            if found is None:
                continue
            recorded_key = _seal_key_mismatch(found[0], found[1], item)
            if recorded_key is not None:
                project.seal_violations.append(item.id)
                project.error(
                    f"{item.id}'s key changed since its legacy seal record in "
                    f"{_seal_file_label(project, board)} was written: was "
                    f"{recorded_key!r}, now {item.key!r}. A key never changes "
                    "legitimately; restore the recorded key from history.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            break


def _orphan_is_history_backed(project: Project, display_id: str) -> bool:
    """Whether an orphaned seal record belonged to a history-backed type.

    A seal record carries no type, so the declared prefix opening the record's
    display id narrows the append-only types it could have come from; with no
    prefix match, every append-only type is a candidate. Prefixes may
    themselves contain hyphens (``REQ-TMP``), so the match runs to a prefix
    boundary -- the longest declared prefix the display id starts with --
    rather than cutting at the first hyphen. A type's ``legacy_prefixes``
    open its own ids just as ``prefix`` does (ids.validate_prefixes treats a
    legacy-prefixed id of the right type as legitimate, not a mismatch), so
    they claim an orphan the same way. Only when *every* candidate is
    history-backed is the orphan one -- any doubt keeps today's error, because
    reading a build-sealed deletion as a mere warning would remove the
    deletion lock from the type that still has it.
    """
    append_only = [spec for spec in project.types.values() if spec.append_only]
    claimed = [
        (spec, prefix)
        for spec in append_only
        for prefix in (spec.prefix, *spec.legacy_prefixes)
        if display_id.startswith(f"{prefix}-")
    ]
    if claimed:
        longest = max(len(prefix) for _spec, prefix in claimed)
        candidates = [spec for spec, prefix in claimed if len(prefix) == longest]
    else:
        candidates = append_only
    return bool(candidates) and all(spec.sealing == SEALING_HISTORY for spec in candidates)


def _report_deleted(
    project: Project, base: Seals, write: bool, reseal: str | None,
    base_events: list[dict],
) -> bool:
    """Report every sealed entry whose identity is no longer in the project.

    Editing a sealed entry was already an error; without this pass, deleting
    one outright produced a clean build and left only an orphaned hash. That
    is the louder half of the same tamper-evidence rule and uses the same
    board-scoped reseal escape hatch.

    "No longer anywhere" is deliberately generous. A legacy display id still
    counts when it is live on another board or claimed through ``former_ids``.
    A surrogate-keyed entry first belongs to any live owner of its immutable
    key, regardless of whether its recorded id was later reused. Only when no
    live item owns that key may the recorded display id identify key
    corruption; that case is reported once by ``verify()``, not again and
    misleadingly as a deleted item here. Read-only checks report but never
    remove entries.

    This pass iterates seal *files*, not append-only items, so the sealing
    policy has to be applied to each orphan explicitly: otherwise a type that
    stopped locking edits would keep erroring on deletion. A record that
    belonged to a history-backed type (``_orphan_is_history_backed``) is a
    legacy-seal marker, and its entry going missing is a warning naming the
    record and the seal file -- the same class of diagnostic as an edit, never
    an error -- and ``--reseal`` never drops it.
    """
    live_ids = {item.id for item in project.local_items}
    live_ids |= set(project.former_ids)
    live_keys = {item.key for item in project.local_items if item.key}

    base_changed = False
    for board in sorted({""} | set(project.boards)):
        seals = base if board == "" else load_seals(project, board)
        orphans = []
        events: list[dict] = [] if board else base_events
        for record_id, value in seals.items():
            key, display_id, _recorded, _hash_format = _seal_parts(record_id, value)
            if key is None:
                is_live = display_id in live_ids
            elif key in live_keys:
                is_live = True
            else:
                is_live = display_id in live_ids
            if is_live:
                continue
            orphans.append((record_id, display_id))
        if not orphans:
            continue
        reseal_here = bool(reseal) and (reseal == RESEAL_ALL or reseal == board)
        hint = _reseal_hint(board)
        dropped = False
        for record_id, display_id in sorted(orphans, key=lambda pair: pair[1]):
            if _orphan_is_history_backed(project, display_id):
                key, _id, recorded, _hash_format = _seal_parts(record_id, seals[record_id])
                project.warn(
                    f"{display_id} has a legacy seal record in "
                    f"{_seal_file_label(project, board)}"
                    + (f" (key {key})" if key else "")
                    + " but is no longer in the project. The record holds a hash "
                    f"only ({recorded}); the original content was not captured, so "
                    "it cannot be restored from history -- restore it from version "
                    "control if the removal was not deliberate. The record is kept "
                    "as it is.",
                    item_id=display_id,
                )
                continue
            if reseal_here:
                acceptance = (
                    "accepting the removal and dropping its seal; recorded in audit."
                    if write else "would accept the removal; no seal or audit record was written."
                )
                project.warn(
                    f"{display_id} was sealed as append-only and is no longer in "
                    f"the project -- {acceptance}",
                    item_id=display_id,
                )
                if write:
                    key, _id, recorded, hash_format = _seal_parts(record_id, seals[record_id])
                    events.append(_reseal_event(display_id, key, recorded, None, hash_format))
                    del seals[record_id]
                    dropped = True
            else:
                project.error(
                    f"{display_id} is append-only and was sealed, but no item with "
                    "that id is in the project any more. An append-only entry "
                    "is corrected by appending one that `amends` it, never by "
                    f"deleting it -- restore it, or run with {hint} if the removal "
                    "is deliberate.",
                    item_id=display_id,
                )
        # Only a dropped record rewrites the file: a history-backed orphan is
        # kept, so a board whose orphans are all legacy-seal markers is left
        # byte-for-byte untouched even under --reseal.
        if reseal_here and write and dropped:
            if board:
                save_seals(project, seals, board, events=events)
            else:
                base_changed = True
    return base_changed


def resealed_ids(project: Project) -> list[str]:
    """Return sealed entries whose current content no longer matches.

    Audit is read-only, so it cannot rely on ``verify(write=True)`` having
    upgraded legacy hashes first. It therefore uses the same format-aware
    comparison as verification; otherwise the first audit after adopting keys
    would call every unchanged legacy seal "resealed". A key mismatch is also
    returned as drift even when the content hash itself still matches.
    """
    base = load_seals(project, board="")
    live_keys = {item.key for item in project.local_items if item.key}
    out: list[str] = []
    for board in _boards_in_play(project):
        seals = load_seals(project, board) if board else base
        for item in append_only_items(project, board=board):
            found = _find_seal(seals, item, live_keys)
            if found is None and board:
                found = _find_seal(base, item, live_keys)
            if found is None:
                continue
            _record_id, _value, recorded, hash_format = found
            if _seal_key_mismatch(_record_id, _value, item) is not None:
                out.append(item.id)
                continue
            ok, _upgraded = _matches_sealed_hash(recorded, item, project, hash_format)
            if not ok:
                out.append(item.id)
    return out
