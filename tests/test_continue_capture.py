"""W5b.5: the continuation save writes the PREDECESSOR's `followed` capture
event in the SAME locked operation that appends the continuation entry.

docs/design/thread-workbench-w5b-plan.md §4 W5b.5 (the capture moment, plan
lines 340-361), §6 Q2's ratified sub-question (a) (plan lines 464-482: "W5b.5
writes both from the one locked operation"), Q7 = none (plan lines 566-583),
Q10(a) = NO CLI in W5b (plan lines 632-633, so no CLI test, no new endpoint,
no pane change). The capture rules live at docs/design/living-notes.md:185-215:
entry + event in one transaction (rule 1, :190-193), the capture is ANNOUNCED
once, never silent (:209-212), idempotence per (predecessor, successor) pair
(:226), and the `followed-corrected` case (:222). This file is the TEST AUTHOR
slice (W5b.5-tests): it pins the contract the implementer must build in
`src/refdes/serve/edit.py`'s `continue_thread` / `_continue_locked` and in the
`POST /api/item/<ref>/continue` route (api.py `_continue_item` /
`_write_outcome`); it does NOT touch src/ or any existing test.

What today does NOT do (the red these tests show): after the entry is written
and its id reserved, `_continue_locked` returns `Applied` writing NO event and
carrying NO announcement. `history.capture_followed` (history.py:645) is the
one function the capture call site adds -- idempotent (re-capturing returns a
FollowCapture with created False, announces nothing), needs `predecessor.key`
and `successor.key`, save_object + append_event. It is what
`links._capture_followed_edges` (links.py:775) calls from a writable load and
what prints `captured LOG-A-011: LOG-A-012 now follows it` (living-notes.md:210
and the builder inside `capture_followed`, history.py:732-735). The save reuses
that builder's wording; the announcement is the exact string that
`FollowCapture.announcement` carries -- no second wording is invented here.

The contract this file pins (assumptions stated, conservative where the brief
is silent):

* `Applied.announcements` is a tuple of the capture announcement strings the
  save produced -- empty for every save that captured nothing. The smallest
  honest shape (brief): a tuple, the same strings the writable-load path prints.
* Every other result value (Conflict / Refused / Invalid) carries the same
  `announcements` field, empty -- the "announces nothing" refusals become a
  positive, testable claim (a refusal prints no capture line). This is the
  smallest shape that makes "announced exactly once per save" fully pinned;
  it is stated as an assumption in in-prog-logs/w5b5-tests.md.
* The HTTP JSON for a successful continue gains `"announcements"`: a list of
  those same strings (ADD, do not rename -- the existing keys
  kind/ok/message/path/revision/describe/id/handle/diagnostics stay, api.py
  :1185-1202). Refusal statuses are unchanged.
* The event: exactly ONE new `followed` event per save, `item_key` = the
  predecessor (tip) key, `successor_key` = the new entry's key, holding the
  predecessor's snapshot (its semantic digest as the object).
* Entry + event are atomic: a capture that raises (HistoryError / OSError)
  rolls the entry back exactly as the id-ledger failure path does (file bytes
  restored, id not reserved, Refused with a plain reason), and NO event file
  survives. A pre-existing event for the same edge (idempotence) is NOT a
  failure.

The fixtures and the `continue_thread`/HTTP helpers mirror
tests/test_serve_continue.py and tests/test_serve_continue_http.py so the
red/green is at the same level those files pin.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes import chains, history, keys, parse
from refdes.schema import load_project
from refdes.serve import edit as edit_mod
from refdes.serve.edit import Applied, Conflict, Refused
from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Continue capture test"
date_format: DD/MM/YYYY
id:
  width: 3
link_types:
  follows: { inverse: followed_by, label: Follows, trace: false }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      date: { type: date }
      summary: { type: text, required: true }
      tasks: { type: tasks, on_change: timeline }
    links:
      follows: [log]
"""

LOG = """\
defaults:
  type: log
  prefix: LOG-SYS

items:
  - id: LOG-SYS-001
    summary: Rail work opens.
    date: 30/08/2026
  - id: LOG-SYS-002
    summary: Rail work continues.
    date: 01/09/2026
    follows: [LOG-SYS-001]
    tasks:
      - {id: T-rail, text: Settle the rail budget., state: open}
      - {id: T-probe, text: Probe the SWD pins., state: open}
"""


# ----------------------------------------------------------------- fixtures


def _write(root, name, text):
    with open(os.path.join(str(root), name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _write_bytes(root, name, data: bytes):
    with open(os.path.join(str(root), name), "wb") as fh:
        fh.write(data)


def _read_bytes(root, rel) -> bytes:
    with open(os.path.join(str(root), rel), "rb") as fh:
        return fh.read()


def _ledger(root):
    """The id ledger's bytes, or None when it has not been created yet (a
    project with a minted-key thread has no ledger until a save reserves an
    id -- tests/test_serve_continue.py reads it only after a save)."""
    path = os.path.join(str(root), ".refdes", "ids.yaml")
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def mint_keys(root):
    project = load_project(config_path=os.path.join(str(root), "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project, write=True)


def mint_and_seal(root):
    mint_keys(root)
    from refdes import build as build_mod

    project = load_project(config_path=os.path.join(str(root), "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=True, reseal=False)


def _load(root):
    project = load_project(config_path=os.path.join(str(root), "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    return project


def _setup(root, *, text=LOG, seal=False, mint=True):
    """Write the project. `text` is the thread file as str (LF) or bytes (e.g.
    CRLF, written verbatim so the bytes are the same on every platform)."""
    write_project_config(root, SCHEMA)
    os.makedirs(os.path.join(str(root), "items"), exist_ok=True)
    if isinstance(text, bytes):
        _write_bytes(root, "items/log.yaml", text)
    else:
        _write(root, "items/log.yaml", text)
    if mint:
        mint_keys(root)
    if seal:
        mint_and_seal(root)
    return root


# ------------------------------------------------------------------ helpers


def continue_thread(root, ref, ticks, expected_revision, *, who="local-author", read_only=False):
    request = edit_mod.ContinueRequest(
        who=who, ref=ref, ticks=tuple(ticks), expected_revision=expected_revision
    )
    return edit_mod.continue_thread(str(root), request, read_only=read_only)


def rev(root, rel="items/log.yaml") -> str:
    return edit_mod.file_revision(os.path.join(str(root), rel))


def events(root):
    return history.load_events(str(root))


def event_files(root):
    directory = history.events_dir(str(root))
    if not os.path.isdir(directory):
        return []
    return sorted(name for name in os.listdir(directory) if name.endswith(".yaml"))


# ====================================================== the core W5b.5 red


def test_one_save_writes_the_predecessors_followed_event_holding_the_tip_snapshot(tmp_path):
    """The one locked operation writes entry + event (Q2 sub-question (a), plan
    lines 464-482; living-notes.md:190-193). One save of the tip appends the
    continuation AND writes exactly ONE `followed` event: item_key = the tip's
    key, successor_key = the new entry's key, holding the tip's snapshot. The
    tip's bytes stay a pure suffix (R2): the capture writes only under
    .refdes/history/, never into the thread file. Today: the entry is written,
    ZERO events -> the expected red."""
    _setup(tmp_path)
    tip_key = _load(tmp_path).item_by_id("LOG-SYS-002").key
    before = _read_bytes(tmp_path, "items/log.yaml")
    assert event_files(tmp_path) == []  # a thread file alone has no history dir yet

    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path))
    assert isinstance(result, Applied), result.message

    after = _read_bytes(tmp_path, "items/log.yaml")
    assert after.startswith(before)  # R2: the tip's bytes are untouched
    evs = events(tmp_path)
    assert len(evs) == 1, [e["kind"] for e in evs]  # today this is 0 -> red
    event = evs[0]
    assert event["kind"] == "followed"
    assert event["item_key"] == tip_key  # the predecessor (the tip the save copied)
    assert event["successor_key"] == result.handle  # the new entry's key
    snapshot = history.load_object(str(tmp_path), event["object"])
    assert snapshot["id"] == "LOG-SYS-002"  # the snapshot is the predecessor's
    assert snapshot["fields"]["summary"] == "Rail work continues."


def test_the_applied_result_carries_the_capture_announcement(tmp_path):
    """The capture is ANNOUNCED, never silent (living-notes.md:209-212): the
    Applied result carries the announcement the writable-load path prints, built
    by the SAME builder (the string capture_followed returns, history.py:732).
    Pin the exact wording -- reuse, do not invent (brief). Today: Applied has no
    `announcements` attribute -> the expected red."""
    _setup(tmp_path)
    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path))
    assert isinstance(result, Applied), result.message

    expected = f"captured LOG-SYS-002: {result.item_id} now follows it"
    assert result.announcements == (expected,)  # today: no such attribute -> red
    assert result.announcements[0] == "captured LOG-SYS-002: LOG-SYS-003 now follows it"


def test_the_continue_endpoint_adds_the_announcements_list_to_the_json(tmp_path):
    """The endpoint's 200 body (api.py `_write_outcome`/`_continue_item`) gains
    `announcements` -- the same list under the same name, ADD not rename (brief;
    tests/test_serve_continue_http.py:42-48 lists the current keys, all of which
    must stay). Today: the key is absent from the JSON -> the expected red."""
    _setup(tmp_path)
    app = EditorApp(os.path.join(str(tmp_path), "refdes-project.yaml"), poll_interval=60)
    app.start()
    try:
        client = Client(app)
        status, payload = client.api_post(
            "/api/item/LOG-SYS-002/continue",
            {"ticks": [["T-rail", "done"]], "expected_revision": rev(tmp_path)},
        )
        assert status == 200, payload
        # the existing keys stay (ADD, do not rename)
        assert payload["kind"] == "applied" and payload["ok"] is True
        assert payload["id"] == "LOG-SYS-003"
        assert "path" in payload and "revision" in payload and "describe" in payload
        # the added key, the same strings the Applied carries
        assert payload["announcements"] == [
            "captured LOG-SYS-002: LOG-SYS-003 now follows it"
        ]  # today: KeyError -> red
    finally:
        app.stop()


def test_the_announcement_appears_exactly_once_a_second_writable_load_is_silent(
    tmp_path, capsys
):
    """Idempotence + "announced once, never silent" (living-notes.md:204-207,
    :226): after the save captures the edge, a second writable load (the very
    path the composite `follows:` the save wrote came through) captures the
    save's edge nothing new and announces the save's edge nothing -- the tree
    under .refdes/history is byte-for-byte unchanged. Today: the save writes
    ZERO events, so the "one event, then silent reload" contract cannot hold ->
    the expected red at the count."""
    _setup(tmp_path)
    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path))
    assert isinstance(result, Applied), result.message
    assert len(events(tmp_path)) == 1  # today 0 -> red
    assert len(result.announcements) == 1  # today no attribute -> red

    config = os.path.join(str(tmp_path), "refdes-project.yaml")
    succ_key = _load(tmp_path).item_by_id("LOG-SYS-003").key
    save_edge = [e for e in events(tmp_path) if e.get("successor_key") == succ_key]
    assert len(save_edge) == 1  # the save's edge, exactly one event
    capsys.readouterr()
    from refdes import loader

    loader.load_tree(config, write=True)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    # The save's edge (its successor key is unique) must not be re-captured or
    # re-announced. A writable load re-announces the fixture's pre-existing,
    # un-captured LOG-SYS-001 -> LOG-SYS-002 edge -- that is not the save's.
    assert "LOG-SYS-003" not in out
    save_edge_after = [e for e in events(tmp_path) if e.get("successor_key") == succ_key]
    assert save_edge_after == save_edge  # the save's event is not duplicated


# ---------------------------------------------------- the transaction's "no"


def _boom_history(exc):
    def boom(root, predecessor, successor, **kwargs):
        raise exc

    return boom


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(history.HistoryError("the store refused"), id="HistoryError"),
        pytest.param(OSError("the disk refused"), id="OSError"),
    ],
)
def test_a_capture_failure_rolls_the_entry_back_and_reserves_no_id(tmp_path, monkeypatch, exc):
    """Entry + event or NEITHER (living-notes.md:190-193; brief): if the capture
    raises, the entry write is rolled back exactly as the id-ledger failure path
    already does -- the file's bytes restored, the id NOT reserved (the next
    save reuses the number), a Refused with a plain reason -- and NO event file
    survives. Today: `continue_thread` never reaches the capture, so the save
    SUCCEEDS (Applied, entry written, id reserved) -> the expected red."""
    _setup(tmp_path)
    monkeypatch.setattr(history, "capture_followed", _boom_history(exc))
    before_bytes = _read_bytes(tmp_path, "items/log.yaml")
    before_ledger = _ledger(tmp_path)
    revision = rev(tmp_path)

    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], revision)

    assert isinstance(result, Refused), f"capture failure must roll back, got {result!r}"
    assert not result.ok
    assert result.reason  # a plain reason (the implementer's wording)
    assert result.announcements == ()  # a rollback announces nothing
    assert _read_bytes(tmp_path, "items/log.yaml") == before_bytes  # bytes restored
    assert _ledger(tmp_path) == before_ledger  # id not reserved
    assert "LOG-SYS-003" not in _read_bytes(tmp_path, "items/log.yaml").decode("utf-8")
    assert event_files(tmp_path) == []  # no event file survives

    monkeypatch.undo()
    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path))
    assert isinstance(result, Applied), result.message
    assert result.item_id == "LOG-SYS-003"  # the number the failure did not burn


# ------------------------------------------------------- "does not change"

# Each of these asserts the capture-surface claim (the result carries an
# `announcements` tuple, empty; the history dir gains nothing). The result
# classes gain `announcements` in W5b.5, so referencing it is the red today;
# the "no event / bytes identical" part is the invariant the save must keep.


def test_a_stale_revision_is_a_conflict_that_captures_nothing_and_announces_nothing(tmp_path):
    """A Conflict writes no event and announces nothing (brief). The revision
    compare (Q3(a)) refuses before the write, so there is no capture."""
    _setup(tmp_path)
    stale = rev(tmp_path)
    applied = edit_mod.apply_edit(
        str(tmp_path),
        edit_mod.EditRequest(
            who="other",
            ref="LOG-SYS-002",
            op=edit_mod.SetField("summary", "Rail work, re-scoped."),
            expected_revision=stale,
        ),
    )
    assert isinstance(applied, Applied), applied.message

    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], stale)
    assert isinstance(result, Conflict), result.message
    assert result.announcements == ()  # today no attribute on Conflict -> red
    assert event_files(tmp_path) == []
    assert "LOG-SYS-003" not in _read_bytes(tmp_path, "items/log.yaml").decode("utf-8")


def test_a_read_only_call_captures_nothing_and_announces_nothing(tmp_path):
    """`--no-write` writes nothing (brief; living-notes.md:224): the save is
    refused before the entry, so no event and no announcement."""
    _setup(tmp_path)
    result = continue_thread(
        tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path), read_only=True
    )
    assert isinstance(result, Refused), result.message
    assert "--no-write" in result.reason
    assert result.announcements == ()  # today no attribute on Refused -> red
    assert event_files(tmp_path) == []
    assert not os.path.isdir(os.path.join(str(tmp_path), ".refdes", "history"))


def test_a_sealed_tip_is_refused_with_no_event_and_no_announcement(tmp_path):
    """A sealed tip stays refused (plan line 243; brief: sealed tip refused with
    no event). The refusal is before the write, so no capture."""
    _setup(tmp_path, seal=True)
    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path))
    assert isinstance(result, Refused), result.message
    assert "sealed" in result.reason
    assert result.announcements == ()  # today no attribute on Refused -> red
    assert event_files(tmp_path) == []
    assert not os.path.isdir(os.path.join(str(tmp_path), ".refdes", "history"))


def test_a_keyless_tip_is_refused_and_captures_nothing(tmp_path):
    """A keyless predecessor cannot be saved (brief: "already Refused today --
    confirm it still is and that no event exists"). With keys never minted, the
    tip carries no key, so no composite and no save; a refusal writes no event.
    The result carries the (empty) `announcements` tuple -- the red today."""
    _setup(tmp_path, mint=False)  # keys never minted
    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path))
    assert isinstance(result, Refused), result.message
    assert "no artifact key" in result.reason
    assert result.announcements == ()  # today no attribute on Refused -> red
    assert event_files(tmp_path) == []
    assert not os.path.isdir(os.path.join(str(tmp_path), ".refdes", "history"))


def test_an_id_less_tip_is_refused_and_captures_nothing(tmp_path):
    """Edge case (brief: id-less / keyed-only thread entries). The continue
    operation names the tip with a DISPLAY-ID@key composite, which an id-less
    tip cannot supply (links.composite_for returns None with no id), so it is
    Refused -- no event, no announcement. (A keyed-only tip is addressed by key
    for capture, living-notes.md:207, but the composite the save writes needs an
    id; the refusal is the honest posture today, pinned here.)"""
    _setup(tmp_path)
    tip_key = _load(tmp_path).item_by_id("LOG-SYS-002").key
    idless = (
        "defaults:\n  type: log\n  prefix: LOG-SYS\n\n"
        "items:\n"
        "  - id: LOG-SYS-001\n    summary: Rail work opens.\n    date: 30/08/2026\n"
        f"  - key: {tip_key}\n    summary: Rail work continues.\n    date: 01/09/2026\n"
        "    follows: [LOG-SYS-001]\n"
        "    tasks:\n      - {id: T-rail, text: Settle the rail budget., state: open}\n"
    )
    _write(tmp_path, "items/log.yaml", idless)

    result = continue_thread(tmp_path, tip_key, [("T-rail", "done")], rev(tmp_path))
    assert isinstance(result, Refused), result.message
    assert "composite" in result.reason
    assert result.announcements == ()  # today no attribute on Refused -> red
    assert event_files(tmp_path) == []


def test_two_saves_in_a_row_add_a_second_event_leaving_the_first_untouched(tmp_path):
    """Edge case (brief: a thread whose tip already has an incoming `followed`
    event from an earlier save). Save #1 captures tip-002 -> entry-003. Save #2
    continues the thread (now tipped at 003) -> a SECOND event for the new edge
    003 -> 004, the first event's bytes untouched (append-only, never rewritten).
    Today: zero events -> the expected red."""
    _setup(tmp_path)
    first = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path))
    assert isinstance(first, Applied), first.message
    assert len(events(tmp_path)) == 1  # today 0 -> red
    tip3_key = _load(tmp_path).item_by_id("LOG-SYS-003").key

    second = continue_thread(tmp_path, "LOG-SYS-002", [("T-probe", "done")], rev(tmp_path))
    assert isinstance(second, Applied), second.message

    evs = events(tmp_path)
    assert len(evs) == 2, [e["kind"] for e in evs]
    by_succ = {e["successor_key"]: e for e in evs}
    assert set(by_succ) == {first.handle, second.handle}
    assert by_succ[second.handle]["item_key"] == tip3_key  # 003 -> 004
    assert by_succ[first.handle]["item_key"] == _load(tmp_path).item_by_id("LOG-SYS-002").key


def test_two_saves_racing_land_exactly_one_event_for_the_winning_edge(tmp_path):
    """Edge case (brief): two saves racing the same tip -> exactly one Applied,
    one Conflict, exactly ONE event, and it names the WINNING edge (the loser's
    revision check refuses it before the write, so it never captures). Today:
    zero events -> the expected red."""
    import threading

    _setup(tmp_path)
    tip_key = _load(tmp_path).item_by_id("LOG-SYS-002").key
    revision = rev(tmp_path)
    results: list = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait(timeout=30)
        results.append(continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], revision))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    applied = [r for r in results if isinstance(r, Applied)]
    conflicted = [r for r in results if isinstance(r, Conflict)]
    assert len(applied) == 1, [type(r).__name__ for r in results]
    assert len(conflicted) == 1, [type(r).__name__ for r in results]

    evs = events(tmp_path)
    assert len(evs) == 1, [e["kind"] for e in evs]  # today 0 -> red
    assert evs[0]["item_key"] == tip_key
    assert evs[0]["successor_key"] == applied[0].handle  # the winner's edge only
    assert all(r.announcements == () for r in conflicted)


# ------------------------------------------------- cross-platform edge cases


def test_a_crlf_thread_file_still_captures_and_the_object_is_line_ending_independent(tmp_path):
    """Edge case (brief): a file with CRLF line endings still captures, and the
    event content is not line-ending dependent. The thread file is CRLF; the
    capture writes its object with `textio.write_text` (newline='', history.py),
    so the object/event bytes carry LF only -- the digest is of the payload, not
    the file's line endings. Today: zero events -> the expected red."""
    crlf = LOG.replace("\n", "\r\n").encode("utf-8")
    _setup(tmp_path, text=crlf)
    assert b"\r\n" in _read_bytes(tmp_path, "items/log.yaml")  # authored CRLF
    tip_key = _load(tmp_path).item_by_id("LOG-SYS-002").key

    result = continue_thread(tmp_path, "LOG-SYS-002", [("T-rail", "done")], rev(tmp_path))
    assert isinstance(result, Applied), result.message

    evs = events(tmp_path)
    assert len(evs) == 1  # today 0 -> red
    assert evs[0]["item_key"] == tip_key
    object_path = history.object_path(str(tmp_path), evs[0]["object"])
    with open(object_path, "rb") as fh:
        object_bytes = fh.read()
    assert b"\r\n" not in object_bytes  # the store writes LF, not the file's CRLF
    assert b"\n" in object_bytes


def test_a_non_ascii_project_path_still_captures(tmp_path):
    """Edge case (brief: a non-ASCII project path). The whole project sits under
    a directory with non-ASCII names; the save writes the entry and the capture
    event the same as anywhere else. Today: zero events -> the expected red."""
    root = tmp_path / "café-Ω-rail"
    os.makedirs(str(root))
    _setup(root)

    result = continue_thread(root, "LOG-SYS-002", [("T-rail", "done")], rev(root))
    assert isinstance(result, Applied), result.message

    evs = events(root)
    assert len(evs) == 1  # today 0 -> red
    assert evs[0]["successor_key"] == result.handle
    # the entry landed too (the thread is a line, fold reports the new tip)
    project = _load(root)
    fold = chains.fold_tasks(project, project.item_by_id(result.item_id))[0]
    assert fold.tip.id == result.item_id
