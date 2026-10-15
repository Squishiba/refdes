"""The redaction rollback: a removal undone must not be a removal half-done.

Sabotage-style, like the rest of the history tests: the redaction's own
event write is faulted after files are already removed, and the rollback's
own writes are faulted (the ENOSPC shape PR #244's review injected). The
invariants under test: the rollback restores bytes it holds in memory through
one ``os.replace`` per file — never an in-place truncating ``open(path,
"wb")``, which left a 0-byte event where the store had a valid one; a restore
that faults is disclosed together with the failure that triggered it, the
original preserved as the ``__cause__``, never silently replaced; and a
restore that succeeds leaves the store byte-identical to before the attempt.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import history

LOG_SCHEMA = """\
site: { title: Redact Rollback, out: site_out_redact_rb }
id: { width: 3, ledger: .refdes/ids.yaml }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

TWO_LOGS = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: Secret note.\n"
    "  - id: LOG-002\n    summary: Second note.\n"
)

ORIGINAL_FAILURE = "injected: the redaction event write failed"


def _setup(tmp_path):
    write_project_config(tmp_path, LOG_SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(TWO_LOGS, encoding="utf-8")
    config = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    return config


def _captured(root):
    events = history.load_events(root)
    return [e for e in events if e["kind"] == "captured"][0]


def _tree(root):
    """relpath -> sha256 for every file under `root` (dot-files included, so
    a temp residue is visible to the comparison)."""
    files = {}
    for dirpath, _dirnames, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace("\\", "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


class _EnospcWriter:
    """File wrapper whose write() faults with ENOSPC — the full-disk shape
    PR #244's review injected into the rollback's write."""

    def __init__(self, fh):
        self._fh = fh

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fh.close()
        return False

    def write(self, data):
        raise OSError(28, "No space left on device")

    def flush(self):
        pass


def _fault_event_write(monkeypatch):
    """The redaction event write — the step after the removals — fails."""

    def _boom(*args, **kwargs):
        raise RuntimeError(ORIGINAL_FAILURE)

    monkeypatch.setattr(history, "append_event", _boom)


def _fault_all_writes(monkeypatch):
    """Every write of a rollback temp faults: the disk is full at exactly the
    worst moment."""
    real_fdopen = os.fdopen

    def _faulty_fdopen(fd, mode="r", *args, **kwargs):
        fh = real_fdopen(fd, mode, *args, **kwargs)
        if "w" in mode:
            return _EnospcWriter(fh)
        return fh

    monkeypatch.setattr(os, "fdopen", _faulty_fdopen)


def _assert_no_temp_residue(root):
    store = os.path.join(root, ".refdes", "history")
    for dirpath, _dirnames, names in os.walk(store):
        assert not [n for n in names if "refdes-tmp" in n], names


def test_a_rolled_back_redaction_leaves_the_store_byte_identical(tmp_path, monkeypatch):
    """A redaction that fails after its removals, with a working rollback,
    re-raises the original failure unchanged and changes nothing on disk."""
    _setup(tmp_path)
    root = str(tmp_path)
    event = _captured(root)
    before = _tree(root)

    _fault_event_write(monkeypatch)
    with pytest.raises(RuntimeError) as excinfo:
        history.redact(root, item_key=str(event["item_key"]))

    assert str(excinfo.value) == ORIGINAL_FAILURE
    assert _tree(root) == before, "the rollback changed bytes it should have restored"
    _assert_no_temp_residue(root)


def test_a_faulted_restore_never_truncates_the_removed_event(tmp_path, monkeypatch):
    """The defect this replaces: the rollback restored with
    ``open(path, "wb")``, which truncates at open — a write that faulted left
    a 0-byte event file in a store that had a valid one. The atomic restore
    creates the target only with the full bytes, so a faulted restore leaves
    the file exactly where the removal left it: absent."""
    _setup(tmp_path)
    root = str(tmp_path)
    event = _captured(root)
    event_path = os.path.join(history.events_dir(root), f"{event['id']}.yaml")
    with open(event_path, "rb") as fh:
        assert len(fh.read()) > 0

    _fault_event_write(monkeypatch)
    _fault_all_writes(monkeypatch)
    with pytest.raises(history.HistoryError):
        history.redact(root, item_key=str(event["item_key"]))

    assert not os.path.exists(event_path), (
        "the rollback left a file at the event's path — it truncated the target "
        "it was restoring, the exact defect this change removes"
    )
    _assert_no_temp_residue(root)
    # The rest of the store is still loadable: no 0-byte record to poison it.
    history.load_events(root)


def test_a_faulted_restore_reports_both_failures(tmp_path, monkeypatch):
    """A restore that faults is disclosed with the failure that triggered it,
    not in place of it: the original exception is the ``__cause__``, the
    message names the original, the restore fault, and which files are gone."""
    _setup(tmp_path)
    root = str(tmp_path)
    event = _captured(root)

    _fault_event_write(monkeypatch)
    _fault_all_writes(monkeypatch)
    with pytest.raises(history.HistoryError) as excinfo:
        history.redact(root, item_key=str(event["item_key"]))

    err = excinfo.value
    assert ORIGINAL_FAILURE in str(err)
    assert "No space left on device" in str(err)
    assert "restored 0 of 2 removed file(s)" in str(err)
    assert isinstance(err.__cause__, RuntimeError)
    assert str(err.__cause__) == ORIGINAL_FAILURE


def test_a_partly_faulted_restore_reports_exactly_what_is_gone(tmp_path, monkeypatch):
    """The arithmetic is truthful file by file: with the event's directory
    refusing renames and the object's directory accepting them, the message
    counts 1 of 2 restored and names only the event."""

    real_replace = os.replace

    def _faulty_replace(src, dst, *args, **kwargs):
        if os.path.dirname(str(src)) == history.events_dir(str(tmp_path)):
            raise OSError(28, "No space left on device")
        return real_replace(src, dst, *args, **kwargs)

    _setup(tmp_path)
    root = str(tmp_path)
    event = _captured(root)

    _fault_event_write(monkeypatch)
    monkeypatch.setattr(os, "replace", _faulty_replace)
    with pytest.raises(history.HistoryError) as excinfo:
        history.redact(root, item_key=str(event["item_key"]))

    err = excinfo.value
    assert "restored 1 of 2 removed file(s)" in str(err)
    assert f"events/{event['id']}.yaml" in str(err).replace("\\", "/")
    assert f"objects/{event['object']}.yaml" not in str(err).replace("\\", "/")
    # The restored object is whole; the event that could not land is absent.
    with open(history.object_path(root, str(event["object"])), "rb") as fh:
        assert len(fh.read()) > 0
    assert not os.path.exists(os.path.join(history.events_dir(root), f"{event['id']}.yaml"))
    _assert_no_temp_residue(root)
