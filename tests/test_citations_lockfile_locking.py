"""Every writer of `.refdes/citations.yaml` holds the project's cross-process
write lock for its own read-modify-write.

`docs/design/editor-source-picker.md` §4 makes the editor a second writer of
that file, and PR #182's rollback documented, in `serve/edit.py`, that its
read-compare-restore was not atomic: "the window is microseconds ... so it is
accepted, not closed; closing it properly means a real lock, which is a
separate decision." This is that decision, so these tests are the proof that
the window is closed rather than a description of it:

* the accept lands its pair -- lockfile then body -- in one section under
  the project lock, and when the body's replace fails the lockfile's restore
  runs in that same section: a writer that tries to replace the lockfile
  **between** the write and its restore is serialised out of that section --
  it lands after, and the file ends up as the last writer wrote it
  (`test_no_writer_lands_between...`);
* a writer that lands **during the gate** is never clobbered, because the
  pair lands in one section behind the revision check: the late check
  refuses the accept and its lockfile never moves
  (`test_a_write_that_landed_during_the_gate...`);
* the accept's own pin write happens inside the lock
  (`test_the_accepts_lockfile_write...`);
* `refdes fetch` -- the CLI writer -- writes while holding the lock, and a
  second holder keeps it out of the file until that holder leaves
  (`test_refdes_fetch_holds...`, `test_a_second_holder_keeps_fetch...`).

The interleavings are built with threads and an event, and by monkeypatching a
hook at the exact point in the landing section, not with sleeps: the bounded
wait in
the interleaving test asserts that a writer *cannot* have landed, and every
final assertion below is a fact about bytes, so nothing here passes by being
lucky about timing.
"""

from __future__ import annotations

import contextlib
import os
import threading

import pytest
from helpers import _build_at
from test_serve_sources import fetch, lock, lock_bytes, make_root

from refdes import cli as cli_mod
from refdes import citations as citations_mod
from refdes.patcher import SetBody
from refdes.serve import edit as edit_mod
from refdes.serve.edit import Applied, Conflict, EditRequest, Refused
from refdes.write_lock import project_write_lock

CSV_PATH = "analysis/budget.csv"
RAIL = 'P = source("analysis/budget.csv", "rail_load") | W'
EFF = 'eff = source("analysis/budget.csv", "eff") | 1'
OTHER = 'o = source("analysis/budget.csv", "other") | 1'
ITEM = "items/decisions.yaml"


def calc_body(*lines) -> str:
    return "```calc\n" + "".join(line + "\n" for line in lines) + "```\n"


def accept(root, *, text=calc_body(RAIL, EFF), key="eff"):
    """The editor's accept, called the way the HTTP route calls it."""
    return edit_mod.apply_edit(
        str(root),
        EditRequest(
            who="local-author",
            ref="DEC-001",
            op=SetBody(text),
            expected_revision=edit_mod.file_revision(str(root / ITEM)),
            pins=(edit_mod.SourcePin(path=CSV_PATH, key=key, unit="1", name=key),),
        ),
    )


def another_pin(root) -> bytes:
    """A whole lockfile holding one pin more than this project's fetch wrote --
    what a cooperating writer's replace looks like from the outside."""
    records = citations_mod.load_lockfile(_build_at(root))
    records[CSV_PATH].setdefault("values", {})["other"] = {"reader": "csv", "value": "7"}
    return citations_mod.lockfile_text(records).encode("utf-8")


def lock_is_held(root) -> bool:
    """Whether the project's cross-process write lock is held right now.

    `write_lock.project_write_lock` locks one stable file, and a lock request
    made through a *different* open file description is refused while another
    holds it -- even from the same process -- so this asks the same lock the
    writers ask, spelled with the same calls `write_lock` itself uses. It is a
    probe of the real thing, not of a flag anyone has to remember to set.
    """
    path = os.path.join(os.path.abspath(str(root)), ".refdes-write.lock")
    try:
        with open(path, "a+b") as fh:
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    return True
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                return False
            import fcntl

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            return False
    except OSError:
        return False


# --------------------------------------------------- the landing section's window


def test_no_writer_lands_between_the_lockfiles_write_and_its_restore(
    tmp_path, monkeypatch
):
    # The landing section's window. The accept lands the lockfile, then the
    # body's replace fails and the section restores the bytes its own write
    # replaced -- all of it inside one section under the project's
    # cross-process write lock. A second writer -- here a thread, because the
    # lock it wants is the one that serialises processes too -- tries to
    # replace the file at exactly that moment.
    root = make_root(tmp_path)
    fetch(root)
    lock_file = root / ".refdes" / "citations.yaml"
    before = lock_file.read_bytes()
    landed = another_pin(root)
    assert landed != before

    started = threading.Event()
    finished = threading.Event()
    saw = {}
    threads = []
    real_replace = edit_mod._atomic_replace

    def a_writer_replaces_the_lockfile():
        started.set()
        with project_write_lock(str(root)):
            # Only reachable once the landing section has left: that is the
            # whole of what this test reads.
            saw["bytes_when_it_got_the_lock"] = lock_file.read_bytes()
            lock_file.write_bytes(landed)
        finished.set()

    def replace(path, payload):
        if os.path.basename(path) != "decisions.yaml":
            return real_replace(path, payload)
        # The lockfile landed a moment ago, under this lock, and this replace
        # is about to fail. Start the writer and assert the negative: while
        # this thread holds the project lock -- which it does, from the
        # lockfile's write through the restore that follows this failure --
        # the writer cannot be in the file. If the lock is ever dropped from
        # this section again, it lands here and this fails.
        thread = threading.Thread(target=a_writer_replaces_the_lockfile, daemon=True)
        thread.start()
        threads.append(thread)
        assert started.wait(10)
        # Bounded: the writer blocks on the lock, so this is a wait for a
        # block, not a race.
        assert not finished.wait(0.5), (
            "a cooperating writer replaced the lockfile between its landing "
            "and the restore of the body's failed replace -- the window is "
            "open again"
        )
        return "simulated write failure"

    monkeypatch.setattr(edit_mod, "_atomic_replace", replace)
    result = accept(root)
    assert isinstance(result, Refused), result
    assert len(threads) == 1
    threads[0].join(60)
    assert not threads[0].is_alive(), "the second writer never got the lock back"
    # It serialised *after*: the bytes it read were the restored ones, so it
    # wrote over a file it had just read, and the last whole writer wins.
    assert saw["bytes_when_it_got_the_lock"] == before
    assert lock_file.read_bytes() == landed
    assert "other" in lock(root)["citations"][CSV_PATH]["values"]
    # And the accept landed nothing of itself: the body never moved, and the
    # key its restore put back is unpinned again.
    assert EFF not in (root / ITEM).read_text("utf-8")


def test_a_write_that_landed_during_the_gate_is_not_clobbered_by_the_refusal(
    tmp_path, monkeypatch
):
    # The gate's window from the writer's side: a whole accept that lands
    # during the slow candidate gate -- which runs without the project lock,
    # on purpose -- is caught by the landing section's revision check, so
    # this accept's pair never lands and the writer's file survives whole.
    # This is the property the old rollback's compare provided from inside a
    # window; the pair landing behind the revision check makes the window --
    # and the compare with it -- unnecessary.
    root = make_root(tmp_path)
    fetch(root)
    lock_file = root / ".refdes" / "citations.yaml"
    item_file = root / ITEM
    landed = another_pin(root)
    original_gate = edit_mod._blocking_diagnostics

    def a_whole_accept_lands_during_the_gate(before, after, item, op):
        with project_write_lock(str(root)):
            lock_file.write_bytes(landed)
        text = item_file.read_text("utf-8")
        item_file.write_text(
            text.replace("      " + RAIL + "\n", "      " + RAIL + "\n      " + OTHER + "\n", 1),
            "utf-8",
        )
        return original_gate(before, after, item, op)

    monkeypatch.setattr(edit_mod, "_blocking_diagnostics", a_whole_accept_lands_during_the_gate)
    result = accept(root)
    assert isinstance(result, Conflict), result  # the late revision check is what says no
    assert lock_file.read_bytes() == landed, "the refused accept destroyed a save that had landed"
    assert "other" in lock(root)["citations"][CSV_PATH]["values"]


# ------------------------------------------------------------ the other writers


def test_the_accepts_lockfile_write_happens_inside_the_project_write_lock(tmp_path, monkeypatch):
    # The accept reads the lockfile, decides the new whole-file contents from
    # what it read, and replaces it -- a read-modify-write like any other, so
    # it holds the lock while it does it. The probe asks the lock itself at the
    # moment of the replace, so this fails the day the write moves back out.
    root = make_root(tmp_path)
    fetch(root)
    held = {}
    real_replace = edit_mod._atomic_replace

    def spy(path, payload):
        held[os.path.basename(path)] = lock_is_held(root)
        return real_replace(path, payload)

    monkeypatch.setattr(edit_mod, "_atomic_replace", spy)
    result = accept(root)
    assert isinstance(result, Applied), result.message
    assert held == {"citations.yaml": True, "decisions.yaml": True}, held
    assert "eff" in lock(root)["citations"][CSV_PATH]["values"]


def test_refdes_fetch_holds_the_project_lock_while_it_writes_the_lockfile(tmp_path, monkeypatch):
    # `fetch` is the lockfile's other writer, and the one that rewrites the
    # whole file from the records it read. Its read-modify-write is inside the
    # lock `cli.main` takes around a writing command (its
    # `with project_write_lock(...)` around `args.func(args)`); this says
    # so about the write itself rather than trusting where the `with` sits.
    root = make_root(tmp_path)
    assert not (root / ".refdes" / "citations.yaml").exists()
    held = {}
    real_save = citations_mod.save_lockfile

    def spy(project, records):
        held["during_save"] = lock_is_held(root)
        return real_save(project, records)

    monkeypatch.setattr(citations_mod, "save_lockfile", spy)
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "fetch"]) == 0
    assert held == {"during_save": True}
    assert lock(root)["citations"][CSV_PATH]["sha256"]


def test_a_second_holder_keeps_fetch_out_of_the_lockfile(tmp_path):
    # Same fact from the other side: with the lock held elsewhere, `fetch`
    # waits, and the file it would have written does not exist yet. Bounded
    # both ways -- the wait for the block and the wait for the release both
    # fail the test rather than hang it.
    root = make_root(tmp_path)
    outcome = {}

    def run_fetch():
        outcome["rc"] = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "fetch"])

    thread = threading.Thread(target=run_fetch, daemon=True)
    with project_write_lock(str(root)):
        thread.start()
        thread.join(0.5)
        assert thread.is_alive(), "refdes fetch wrote the lockfile without the project lock"
        assert not (root / ".refdes" / "citations.yaml").exists()
    thread.join(120)
    assert not thread.is_alive()
    assert outcome.get("rc") == 0
    assert lock(root)["citations"][CSV_PATH]["sha256"]


# ---------------------------------------------------------------- read-only roots


@pytest.mark.skipif(os.name == "nt", reason="chmod-based: advisory mode bits on Windows")
def test_an_accept_on_a_root_that_cannot_host_the_lock_refuses_like_every_other_writer(tmp_path):
    # `project_write_lock` raises `LockUnavailable` for a read-only root with a
    # writable child (write_lock.py:42-50). A writer that cannot lock does not
    # write, and an authoring outcome is a value: the accept comes back as a
    # refusal, and the lockfile it read is untouched.
    root = make_root(tmp_path)
    fetch(root)
    lock_file = root / ".refdes" / "citations.yaml"
    before = lock_file.read_bytes()
    root.chmod(0o555)
    try:
        result = accept(root)
    finally:
        root.chmod(0o755)
    assert isinstance(result, Refused), result
    assert "could not lock" in result.reason
    assert lock_file.read_bytes() == before
    assert lock_bytes(root) == before


def test_an_accept_where_the_lock_raises_a_bare_oserror_refuses_like_a_lock_miss(
    tmp_path, monkeypatch
):
    # `_disk_write_lock`'s docstring promises an `OSError` becomes a refusal,
    # and the re-check-and-replace section in `_apply_locked` catches the whole
    # `OSError`; the accept's own lock section used to catch only
    # `LockUnavailable`, so any *other* OSError the lock can raise on its way
    # in -- an unwrapped `os.stat` in `project_write_lock`, say -- escaped as a
    # raised exception past an entry point whose contract is values-only. Here
    # the lock raises the bare `OSError` directly, and the accept must refuse
    # the same way it does for a read-only root, leaving the lockfile alone.
    root = make_root(tmp_path)
    fetch(root)
    lock_file = root / ".refdes" / "citations.yaml"
    before = lock_file.read_bytes()

    @contextlib.contextmanager
    def lock_raises_oserror(_root):
        raise OSError(5, "Input/output error")
        yield  # pragma: no cover - never reached

    monkeypatch.setattr(edit_mod, "_disk_write_lock", lock_raises_oserror)
    result = accept(root)
    assert isinstance(result, Refused), result
    assert "could not lock" in result.reason
    assert lock_file.read_bytes() == before
    assert lock_bytes(root) == before


def test_a_create_where_the_lock_raises_a_bare_oserror_refuses_like_a_lock_miss(
    tmp_path, monkeypatch
):
    # The other route PR #195 made a lockfile writer: `create_item` takes the
    # disk lock around its whole write and returns `Created | Refused | Invalid`
    # per its own docstring, yet the lock call sat unwrapped, so a raised
    # `OSError` -- any `OSError`, `LockUnavailable` included -- flew past the
    # entry point instead of coming back as a value.
    root = make_root(tmp_path)
    fetch(root)

    @contextlib.contextmanager
    def lock_raises_oserror(_root):
        raise OSError(5, "Input/output error")
        yield  # pragma: no cover - never reached

    monkeypatch.setattr(edit_mod, "_disk_write_lock", lock_raises_oserror)
    result = edit_mod.create_item(
        str(root),
        edit_mod.CreateRequest(who="local-author", type="decision", fields={"title": "x"}),
    )
    assert isinstance(result, Refused), result
    assert "could not lock" in result.reason


@pytest.mark.skipif(os.name == "nt", reason="chmod-based: advisory mode bits on Windows")
def test_a_create_on_a_root_that_cannot_host_the_lock_refuses_like_every_other_writer(
    tmp_path
):
    # The same fact the accept's read-only-root test above establishes, for the
    # create route: `create_item` is a writing route too, and a root that cannot
    # host the lock is a refusal, not a traceback.
    root = make_root(tmp_path)
    fetch(root)
    root.chmod(0o555)
    try:
        result = edit_mod.create_item(
            str(root),
            edit_mod.CreateRequest(who="local-author", type="decision", fields={"title": "x"}),
        )
    finally:
        root.chmod(0o755)
    assert isinstance(result, Refused), result
    assert "could not lock" in result.reason


# --------------------------------------------------------- the header's writer claim


def test_the_lockfile_header_names_both_of_the_files_writers():
    # The header is comment bytes inside users' committed lockfiles, so what
    # it says about who writes the file is a claim that has to stay true: the
    # two are `refdes fetch` and the editor's accept (docs/design/
    # editor-source-picker.md §4 -- `serve/edit.py`'s `_accept_pins` writes
    # the whole file through `lockfile_text`, and `save_lockfile`'s docstring
    # says so too), and the header used to read "Written only by
    # `refdes fetch`." Nothing else pinned the header text, so this pins it.
    header = citations_mod.lockfile_text({})
    assert "Written only by" not in header
    assert "`refdes fetch`" in header
    assert "`refdes serve`" in header
