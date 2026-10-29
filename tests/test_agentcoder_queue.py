"""Offline tests for supervised recovery using captured Paseo payload fixtures."""
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
QPATH = Path(os.environ.get("AGENTCODER_QUEUE_MODE_PATH",
                            str(ROOT / "tools" / "agentcoder" / "queue_mode.py")))
FIXTURES = ROOT / "tests" / "fixtures" / "agentcoder_queue"
spec = importlib.util.spec_from_file_location("queue_mode", QPATH)
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


def shadow_os(monkeypatch, **overrides):
    """Give queue_mode a private os namespace so patched calls stay local."""
    namespace = vars(os).copy()
    namespace.update(overrides)
    monkeypatch.setattr(queue, "os", SimpleNamespace(**namespace))


def shadow_time(monkeypatch, **overrides):
    """Give queue_mode a private time namespace for deterministic clocks."""
    namespace = vars(time).copy()
    namespace.update(overrides)
    shadow = SimpleNamespace(**namespace)
    monkeypatch.setattr(queue, "time", shadow)
    return shadow


def shadow_subprocess(monkeypatch, **overrides):
    """Give queue_mode a private subprocess namespace for child fakes."""
    namespace = vars(subprocess).copy()
    namespace.update(overrides)
    monkeypatch.setattr(queue, "subprocess", SimpleNamespace(**namespace))


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_atomic_json_windows_skips_unavailable_directory_open(tmp_path, monkeypatch):
    jobdir = tmp_path / "job"
    jobdir.mkdir()
    target = jobdir / "state.json"
    target.write_text('{"old": true}\n', encoding="utf-8")
    calls = []
    monkeypatch.setattr(queue, "sys", SimpleNamespace(platform="win32"))

    def unavailable_directory_open(path, flags):
        calls.append((path, flags))
        raise PermissionError(13, "directory handles are unavailable")

    shadow_os(monkeypatch, open=unavailable_directory_open)
    queue.atomic_json(target, {"new": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}
    assert not list(jobdir.glob("*.tmp"))
    assert calls == []


def test_atomic_json_fsyncs_directory_on_posix(tmp_path, monkeypatch):
    jobdir = tmp_path / "job"
    jobdir.mkdir()
    calls = []
    monkeypatch.setattr(queue, "sys", SimpleNamespace(platform="linux"))
    shadow_os(monkeypatch,
              open=lambda path, flags: calls.append(("open", path, flags)) or 47,
              fsync=lambda fd: calls.append(("fsync", fd)),
              close=lambda fd: calls.append(("close", fd)))

    target = jobdir / "state.json"
    queue.atomic_json(target, {"durable": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"durable": True}
    assert calls.count(("open", str(jobdir), os.O_RDONLY)) == 1
    assert ("fsync", 47) in calls and ("close", 47) in calls


def test_atomic_json_tolerates_directory_fsync_oserror(tmp_path, monkeypatch):
    jobdir = tmp_path / "job"
    jobdir.mkdir()
    monkeypatch.setattr(queue, "sys", SimpleNamespace(platform="linux"))
    def fake_open(_path, _flags):
        return 47

    def fsync(fd):
        if fd == 47:
            raise OSError(22, "unsupported")

    shadow_os(monkeypatch, open=fake_open, fsync=fsync, close=lambda _fd: None)

    target = jobdir / "state.json"
    queue.atomic_json(target, {"durable": "file fsync remains"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"durable": "file fsync remains"}


def test_queue_imports_when_posix_lock_module_is_unavailable():
    script = r'''
import builtins, importlib.util, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "fcntl":
        raise ModuleNotFoundError("simulated Windows: no fcntl")
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
spec = importlib.util.spec_from_file_location("queue_mode_windows_import", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
'''
    proc = subprocess.run([sys.executable, "-c", script, str(QPATH)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_windows_lock_fallback_is_exclusive_on_posix(tmp_path, monkeypatch):
    if importlib.util.find_spec("fcntl") is None:
        pytest.skip("POSIX flock shim requires fcntl; Windows runner tests msvcrt")
    import fcntl as posix_fcntl

    class MsvcrtShim:
        LK_LOCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(fd, operation, _length):
            posix_fcntl.flock(fd, posix_fcntl.LOCK_EX if operation == 1
                              else posix_fcntl.LOCK_UN)

    monkeypatch.setattr(queue, "_lock_backend", lambda: "windows")
    monkeypatch.setattr(queue, "msvcrt", MsvcrtShim)
    entered = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()

    def first():
        with queue.locked(tmp_path / "queue.lock"):
            entered.set()
            release.wait(10)

    def second():
        entered.wait(10)
        with queue.locked(tmp_path / "queue.lock"):
            second_entered.set()

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    two.start()
    assert entered.wait(10)
    assert not second_entered.wait(0.5)
    release.set()
    one.join(10)
    two.join(10)
    assert second_entered.is_set()


def create_state(path, **updates):
    path.mkdir(parents=True, exist_ok=True)
    state = {"task_id": "queue-test", "status": "running", "event_seq": 0,
             "outbox": [], "nudges": 0, "retries": 0, "owned_agents": {},
             "operations": {}, "attempts": []}
    state.update(updates)
    queue.atomic_json(path / "state.json", state)
    return state


def load_driver(name):
    driver_spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    return driver


def test_supervised_running_waits_back_off_before_retry(tmp_path, monkeypatch):
    driver = load_driver("agentcoder_running_wait_backoff")
    monkeypatch.setitem(sys.modules, "queue_mode", queue)
    create_state(tmp_path)
    running = {"agentId": "agent-1", "status": "running", "message": "working"}
    idle = {"agentId": "agent-1", "status": "idle", "message": "done"}
    responses = [running, running, running, idle]
    sleeps = []

    def guarded(argv, **_kwargs):
        assert argv[1] == "wait"
        return 0, json.dumps(responses.pop(0)), ""

    monkeypatch.setattr(driver, "run_guarded", guarded)
    monkeypatch.setattr(driver, "check_permits", lambda _job: None)
    job = {"queue_supervised": True, "jobdir": str(tmp_path), "coder_agent": "agent-1",
           "spec": {"agent_timeout": 30}}
    driver.wait_for_agent(job, "coder", sleep_fn=sleeps.append)
    assert sleeps == [1, 1, 1]
    assert not responses


@pytest.mark.parametrize(("agent_remaining", "wall_remaining", "permission_remaining", "expected"), [
    (2, 7, 8, 2),
    (10, 3, 8, 3),
    (10, 25, 3, 3),
])
def test_supervised_wait_is_capped_by_all_active_deadlines(
        tmp_path, monkeypatch, agent_remaining, wall_remaining,
        permission_remaining, expected):
    driver = load_driver("agentcoder_wait_budget_caps")
    monkeypatch.setitem(sys.modules, "queue_mode", queue)
    wall_now, monotonic_start = 1000.0, 100.0
    state = create_state(tmp_path, active_seconds=0,
                         active_started_at=wall_now - (30 - wall_remaining),
                         job_wall_timeout=30,
                         permission_started_at=wall_now - (10 - permission_remaining))
    queue.atomic_json(tmp_path / "state.json", state)
    queue_time = shadow_time(monkeypatch, time=lambda: wall_now)
    monkeypatch.setattr(queue, "record_permission_progress", lambda _jobdir: None)
    monotonic_calls = 0

    def monotonic():
        nonlocal monotonic_calls
        monotonic_calls += 1
        return monotonic_start if monotonic_calls == 1 else monotonic_start + 10 - agent_remaining

    time_namespace = vars(time).copy()
    time_namespace["time"] = queue_time.time
    time_namespace["monotonic"] = monotonic
    monkeypatch.setattr(driver, "time", SimpleNamespace(**time_namespace))
    monkeypatch.setattr(driver, "check_permits", lambda _job: None)
    requested, transport_timeouts = [], []

    def guarded(argv, **kwargs):
        requested.append(float(argv[-1]))
        transport_timeouts.append(kwargs["timeout"])
        return 0, json.dumps({"agentId": "agent-budget", "status": "idle",
                              "message": "done"}), ""

    monkeypatch.setattr(driver, "run_guarded", guarded)
    job = {"queue_supervised": True, "jobdir": str(tmp_path),
           "coder_agent": "agent-budget",
           "spec": {"agent_timeout": 10, "queue": {
               "permission_no_progress_seconds": 10}}}
    driver.wait_for_agent(job, "coder")
    assert requested == [pytest.approx(expected)]
    assert transport_timeouts == [pytest.approx(expected)]


def test_queue_wall_timeout_cannot_exceed_child_hard_cap():
    with pytest.raises(queue.QueueError, match="must not exceed"):
        queue._queue_limits({"queue": {
            "job_wall_timeout": queue.MAX_ACTIVE_SECONDS + 1}})


def test_supervise_usage_error_is_json(capsys):
    assert queue.cli(["supervise"], ROOT / "tools/agentcoder/agentcoder.py") == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_supervisor_reads_spec_once(tmp_path, monkeypatch):
    spec_path, jobdir = tmp_path / "spec.json", tmp_path / "job"
    spec_path.write_text(json.dumps({"task_id": "read-once"}), encoding="utf-8")
    reads = []
    original_read_json = queue.read_json

    def counted_read(path):
        if Path(path) == spec_path:
            reads.append(path)
        return original_read_json(path)

    monkeypatch.setattr(queue, "read_json", counted_read)
    shadow_subprocess(monkeypatch,
                      run=lambda *_args, **_kwargs: fake_result(rc=2, out="human needed"))
    assert queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                           sleep_fn=lambda _seconds: None) == 2
    assert len(reads) == 1


def test_notify_terminal_reads_state_under_job_lock(tmp_path, monkeypatch):
    jobdir = tmp_path / "job"
    create_state(jobdir, notification_command=["notify"])
    real_locked, real_load_state = queue.locked, queue.load_state
    depth = [0]

    @contextmanager
    def tracked_lock(path):
        with real_locked(path):
            depth[0] += 1
            try:
                yield
            finally:
                depth[0] -= 1

    def locked_load(path):
        assert depth[0] > 0
        return real_load_state(path)

    monkeypatch.setattr(queue, "locked", tracked_lock)
    monkeypatch.setattr(queue, "load_state", locked_load)
    queue.notify_terminal(jobdir, {"event_id": "queue-test:1"},
                          lambda _argv: fake_result())


def test_in_loop_daemon_recovery_keeps_reconciled_owned_agents_and_operations(
        tmp_path, monkeypatch, capsys):
    spec_path, jobdir = tmp_path / "spec.json", tmp_path / "job"
    spec_path.write_text(json.dumps({"task_id": "recover-mid-turn",
                                     "queue": {"job_wall_timeout": 600}}),
                         encoding="utf-8")
    state = create_state(jobdir)
    state.update(spec_path=str(spec_path), job_wall_timeout=600, active_seconds=0,
                 active_started_at=None)
    queue.atomic_json(jobdir / "state.json", state)
    queue.atomic_json(jobdir / "job.json", {})
    agent = fixture("ls-g.json")[0]
    listing_calls = []

    def listing():
        listing_calls.append(True)
        return ([], None) if len(listing_calls) == 1 else ([agent], None)

    child_calls = []

    def child(*_args, **_kwargs):
        child_calls.append(True)
        if len(child_calls) == 1:
            current = queue.load_state(jobdir)
            current["owned_agents"][agent["id"]] = {"role": "coder", "status": "recorded"}
            current["operations"]["run-op"] = {
                "operation_id": "run-op", "kind": "run", "role": "coder",
                "request_hash": "hash", "status": "intent"}
            queue.atomic_json(jobdir / "state.json", current)
            queue.atomic_json(jobdir / "job.json", {"coder_agent": agent["id"]})
            return fake_result(rc=1, err="DAEMON_NOT_RUNNING")
        return fake_result(rc=2, out="human needed")

    monkeypatch.setattr(queue, "_listing_from_cli", listing)
    shadow_subprocess(monkeypatch, run=child)
    assert queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                           sleep_fn=lambda _seconds: None) == 2
    saved = queue.load_state(jobdir)
    assert saved["owned_agents"][agent["id"]]["status"] == "active"
    assert saved["operations"]["run-op"]["status"] == "adopted"
    assert saved["reconciliation"]["adopted"][agent["id"]] == "active"


def test_supervised_land_refreshes_report_when_publish_is_disabled(tmp_path, monkeypatch):
    driver = load_driver("agentcoder_land_report")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    report = tmp_path / "report.md"
    report.write_text("stale PR: -\n", encoding="utf-8")
    sha = "a" * 40

    def fake_git(_repo, *args, **_kwargs):
        if args[:2] == ("rev-parse", "HEAD"):
            return sha
        return ""

    monkeypatch.setattr(driver, "git", fake_git)
    monkeypatch.setattr(driver, "save_job", lambda _job: None)
    job = {"queue_supervised": True, "jobdir": str(tmp_path), "task_id": "land-report",
           "phase": "land", "status": "ready-for-human-gate", "coder_sha": sha,
           "base_sha": "b" * 40, "coder_cwd": str(worktree), "test_sha": "c" * 40,
           "test_paths": [], "spec": {"publish": False}}
    driver.do_land(job)
    content = report.read_text(encoding="utf-8")
    assert "- status: **ready-for-human-gate**" in content
    assert "- PR: -" in content
    assert "stale" not in content


def test_supervised_send_timeout_marks_operation_uncertain(tmp_path, monkeypatch):
    driver = load_driver("agentcoder_send_timeout_operation")
    monkeypatch.setitem(sys.modules, "queue_mode", queue)
    create_state(tmp_path)

    def timeout(*_args, **_kwargs):
        raise driver.Pause("paseo send timed out")

    monkeypatch.setattr(driver, "run_guarded", timeout)
    job = {"queue_supervised": True, "jobdir": str(tmp_path), "coder_agent": "agent-1",
           "spec": {"agent_timeout": 3}}
    with pytest.raises(driver.Pause, match="timed out"):
        driver.send_to(job, "coder_agent", "continue")
    operation = next(iter(queue.load_state(tmp_path)["operations"].values()))
    assert operation["status"] == "uncertain"
    assert "timed out" in operation["evidence"]


def permit_row(name, description, short="agent-r", rid="req-1",
               agent_id="agent-running-001"):
    return {"agentShortId": short, "agentId": agent_id, "id": rid,
            "name": name, "description": description}


def fake_result(rc=0, out="[]", err=""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def test_outage_backoff_bounded():
    state = create_state_dict = {"status": "running", "incident_retries": 0, "retries": 0}
    waits = []
    for wait in queue.BACKOFF_SECONDS:
        state, action, _ = queue.bounded_recovery(
            state, {"kind": "daemon_unreachable", "evidence": "DAEMON_NOT_RUNNING"}, 100)
        waits.append(state["retry_at"] - 100)
        assert action == "backoff"
    assert waits == [15, 30, 60, 120, 300]
    state, action, reason = queue.bounded_recovery(
        state, {"kind": "daemon_unreachable", "evidence": "still unavailable"}, 500)
    assert action == "park" and "budget exhausted" in reason
    assert create_state_dict["incident_retries"] == 0  # policy copies before mutation
    state, action, _ = queue.bounded_recovery(
        {"incident_retries": 0, "retries": queue.MAX_JOB_RETRIES},
        {"kind": "daemon_unreachable"}, 900)
    assert action == "park" and state["retries"] == queue.MAX_JOB_RETRIES


def test_transient_error_recovers_without_nudge():
    state = {"nudges": 0}
    state, action, _ = queue.bounded_recovery(
        state, {"kind": "transient_error", "recovered": False}, 10)
    assert action == "observe" and state["nudges"] == 0 and state["retry_at"] == 130
    state, action, reason = queue.bounded_recovery(
        state, {"kind": "transient_error", "recovered": True}, 40)
    assert action == "adopt" and "without nudge" in reason and state["nudges"] == 0
    persistent = {"nudges": 0}
    persistent, action, _ = queue.bounded_recovery(
        persistent, {"kind": "transient_error", "recovered": False}, 100)
    persistent, action, _ = queue.bounded_recovery(
        persistent, {"kind": "transient_error", "verified_signature": True,
                     "role": "coder"}, 220)
    assert action == "replace_same_workspace" and persistent["replacements"]["coder"] == 1
    persistent, action, reason = queue.bounded_recovery(
        persistent, {"kind": "transient_error", "verified_signature": True,
                     "role": "coder"}, 221)
    assert action == "park" and "replacement" in reason


def test_idle_turn_limit_loop_share_budget():
    state = {"nudges": 0, "max_nudges": 2}
    state, action, _ = queue.bounded_recovery(state, {"kind": "idle"}, 0)
    assert action == "continue_same_workspace" and state["nudges"] == 1
    state, action, _ = queue.bounded_recovery(state, {"kind": "turn_limit"}, 1)
    assert action == "continue_same_workspace" and state["nudges"] == 2
    state, action, reason = queue.bounded_recovery(state, {"kind": "idle"}, 2)
    assert action == "park" and "nudge budget" in reason
    loop = {"nudges": 0}
    loop, action, _ = queue.bounded_recovery(loop, {"kind": "loop"}, 100)
    assert action == "observe" and loop["retry_at"] == 700
    loop, action, _ = queue.bounded_recovery(loop, {"kind": "loop"}, 700)
    assert action == "continue_same_workspace" and loop["no_progress_windows"] == 1
    loop, action, reason = queue.bounded_recovery(loop, {"kind": "loop"}, 1300)
    assert action == "park" and "two no-progress windows" in reason


def test_unknown_permit_parks(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g.json")
    calls = []
    rows = [permit_row("CodexBash", "run read-only probes in my own worktree")]

    def invoke(argv):
        calls.append(argv)
        return fake_result(out="[]")

    result, reason = queue.process_permits(jobdir, [listing[0]["id"]], listing, rows, invoke)
    assert result == "PARK" and "unclassifiable" in reason
    assert calls == []
    decision = queue.read_json(jobdir / "state.json")["permit_decisions"][0]
    assert decision["decision"] == "UNKNOWN" and decision["request_hash"]


def test_risky_or_outside_permit_denied(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g.json")
    for row in (permit_row("external_directory", "browse project"),
                permit_row("CodexBash", "write output outside this workspace"),
                permit_row("CodexBash", "git push the branch")):
        calls = []
        result, _ = queue.process_permits(
            jobdir, [listing[0]["id"]], listing, [row],
            lambda argv, calls=calls: (calls.append(argv) or fake_result(out="[]")),
            trusted_agent_ids=[listing[0]["id"]])
        assert result == "PARK" and calls and calls[0][1] == "deny"


def test_trusted_agent_allow_and_stale_race(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g.json")
    calls = []

    def invoke(argv):
        calls.append(argv)
        if argv[:2] == ["permit", "allow"]:
            stale = (FIXTURES / "permit-allow-stale.json").read_text()
            return fake_result(rc=1, err=stale)
        return fake_result(out="[]")

    result, _ = queue.process_permits(
        jobdir, [listing[0]["id"]], listing,
        [permit_row("CodexBash", "May I run the exact command?")], invoke,
        trusted_agent_ids=[listing[0]["id"]])
    assert result == "CLEAR"
    assert calls[0][:4] == ["permit", "allow", listing[0]["id"], "req-1"]
    assert calls[1] == ["permit", "ls", "--json"]
    assert queue.read_json(jobdir / "state.json")["permit_decisions"][0]["decision"] == "ALLOW"


def test_permit_action_transport_failures_park_with_evidence(tmp_path):
    listing = fixture("ls-g.json")
    rows = (permit_row("CodexFileChange", "-", short=listing[0]["shortId"],
                       agent_id=listing[0]["id"]),
            permit_row("CodexBash", "write outside this workspace",
                       short=listing[0]["shortId"], agent_id=listing[0]["id"]))
    case = 0
    for row in rows:
        for fail_call in (1, 2):
            case += 1
            jobdir = tmp_path / f"job-{case}"
            create_state(jobdir)
            calls = []

            def invoke(argv, calls=calls, fail_call=fail_call):
                calls.append(argv)
                if len(calls) == fail_call:
                    raise OSError("paseo unavailable")
                return fake_result(out="[]")

            decision, reason = queue.process_permits(
                jobdir, [listing[0]["id"]], listing, [row], invoke,
                trust_owned_agents=True)
            assert decision == "PARK" and "uncertain" in reason
            assert "paseo unavailable" in json.dumps(
                queue.load_state(jobdir)["permit_decisions"])


def test_check_permits_recognizes_owned_reviewer_agent(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_reviewer_permit", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    monkeypatch.setitem(sys.modules, "queue_mode", queue)
    listing = fixture("ls-g.json")
    reviewer = listing[1]
    row = permit_row("CodexFileChange", "-", short=reviewer["shortId"],
                     agent_id=reviewer["id"])
    payloads = [json.dumps([row]), json.dumps(listing)]

    def guarded(_argv, **_kwargs):
        return 0, payloads.pop(0), ""

    permit_calls = []

    def paseo(argv, **_kwargs):
        permit_calls.append(argv)
        return fake_result(out="[]")

    monkeypatch.setattr(driver, "run_guarded", guarded)
    shadow_subprocess(monkeypatch, run=paseo)
    jobdir = tmp_path / "job"
    create_state(jobdir)
    job = {"queue_supervised": True, "jobdir": str(jobdir),
           "reviewer_agent": reviewer["id"],
           "spec": {"queue": {"trust_owned_agents": True}}}
    driver.check_permits(job)
    assert permit_calls[0][:4] == ["paseo", "permit", "allow", reviewer["id"]]


def test_stale_deny_race_is_benign(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g.json")
    calls = []

    def invoke(argv):
        calls.append(argv)
        if argv[:2] == ["permit", "deny"]:
            stale = (FIXTURES / "permit-allow-stale.json").read_text()
            return fake_result(rc=1, err=stale)
        return fake_result(out="[]")

    result, _ = queue.process_permits(
        jobdir, [listing[0]["id"]], listing,
        [permit_row("CodexBash", "write output outside this workspace")], invoke)
    assert result == "CLEAR" and len(calls) == 2


def test_trusted_agent_does_not_bypass_unverified_schema(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g.json")
    row = permit_row("CodexBash", "May I run a command?")
    row["input"] = {"command": "unknown"}
    calls = []
    result, reason = queue.process_permits(
        jobdir, [listing[0]["id"]], listing, [row],
        lambda argv: (calls.append(argv) or fake_result()),
        trusted_agent_ids=[listing[0]["id"]])
    assert result == "PARK" and "unverified schema" in reason and calls == []


def test_owned_agent_trust_allows_captured_in_workspace_write(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g-permission.json")
    row = fixture("permit-owned-write.json")
    assert queue.classify_permit_record(row[0])[0] == "UNKNOWN"
    calls = []
    no_opt_in, _ = queue.process_permits(
        jobdir, [listing[0]["id"]], listing, row,
        lambda argv: (calls.append(argv) or fake_result(out="[]")))
    assert no_opt_in == "PARK" and calls == []
    allowed, _ = queue.process_permits(
        jobdir, [listing[0]["id"]], listing, row,
        lambda argv, calls=calls: (calls.append(argv) or fake_result(out="[]")),
        trust_owned_agents=True)
    assert allowed == "CLEAR"
    assert calls[0][:4] == ["permit", "allow", listing[0]["id"], row[0]["id"]]


def test_no_evidence_file_change_permit_requires_owned_trust(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g-permission.json")
    row = fixture("permit-no-description.json")
    row["agentId"] = listing[0]["id"]
    row["agentShortId"] = listing[0]["shortId"]
    calls = []
    parked, reason = queue.process_permits(
        jobdir, [listing[0]["id"]], listing, [row],
        lambda argv: (calls.append(argv) or fake_result(out="[]")))
    assert parked == "PARK" and "unclassifiable" in reason and calls == []
    decision = queue.load_state(jobdir)["permit_decisions"][-1]
    assert decision["raw"] and '"description": "-"' in decision["raw"]
    empty = dict(row, description="")
    allowed, _ = queue.process_permits(
        jobdir, [listing[0]["id"]], listing, [empty],
        lambda argv, calls=calls: (calls.append(argv) or fake_result(out="[]")),
        trust_owned_agents=True)
    assert allowed == "CLEAR"
    assert calls[0][:4] == ["permit", "allow", listing[0]["id"], row["id"]]
    risky = dict(row, name="CodexBash curl", description="-")
    denied, _ = queue.process_permits(
        jobdir, [listing[0]["id"]], listing, [risky],
        lambda argv, calls=calls: (calls.append(argv) or fake_result(out="[]")),
        trust_owned_agents=True)
    assert denied == "PARK" and calls[-2][1] == "deny"


def test_sequential_permission_waits_have_separate_bounded_budget(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_permission_wait_loop", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    create_state(tmp_path)
    prompt = fixture("wait-permission.json")
    idle = dict(fixture("wait-idle.json"), agentId=prompt["agentId"])
    responses = [prompt, prompt, prompt, prompt, idle]
    permits = []

    def guarded(argv, **_kwargs):
        assert argv[1] == "wait"
        return 0, json.dumps(responses.pop(0)), ""

    monkeypatch.setattr(driver, "run_guarded", guarded)
    monkeypatch.setattr(driver, "check_permits", lambda _job: permits.append("check"))
    job = {"queue_supervised": True, "jobdir": str(tmp_path),
           "coder_agent": prompt["agentId"], "spec": {"agent_timeout": 30,
               "queue": {"max_permission_prompts": 5}}}
    driver.wait_for_agent(job, "coder")
    state = queue.load_state(tmp_path)
    assert len(permits) == 5 and not responses
    assert state["permission_prompts"] == 4 and state["permission_started_at"] is None
    assert state["nudges"] == 0


def test_permission_wait_runaway_budget_and_no_progress_timer(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_permission_runaway", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    create_state(tmp_path)
    prompt = fixture("wait-permission.json")
    calls = []
    monkeypatch.setattr(driver, "run_guarded", lambda *_args, **_kwargs:
                        (calls.append("wait") or (0, json.dumps(prompt), "")))
    monkeypatch.setattr(driver, "check_permits", lambda _job: None)
    job = {"queue_supervised": True, "jobdir": str(tmp_path),
           "coder_agent": prompt["agentId"], "spec": {"agent_timeout": 30,
               "queue": {"max_permission_prompts": 2}}}
    try:
        driver.wait_for_agent(job, "coder")
    except driver.Pause as exc:
        assert "permission prompt budget" in str(exc)
    else:
        raise AssertionError("runaway permission sequence must park")
    assert calls == ["wait"] * 3 and queue.load_state(tmp_path)["nudges"] == 0

    state = {"permission_prompts": 0, "permission_started_at": None}
    queue.note_permission_prompt(state, 3, 5, now=10)
    queue.refresh_permission_progress(state, now=14)
    queue.check_permission_progress(state, 5, now=18)
    try:
        queue.check_permission_progress(state, 5, now=19)
    except queue.QueueError as exc:
        assert "no-progress timer" in str(exc)
    else:
        raise AssertionError("stuck permission handling must stop at its deadline")


def test_long_turn_after_permission_grant_refreshes_no_progress_timer(tmp_path, monkeypatch):
    driver = load_driver("agentcoder_long_turn_permission_progress")
    monkeypatch.setitem(sys.modules, "queue_mode", queue)
    create_state(tmp_path)
    permission = fixture("wait-permission.json")
    running = dict(permission, status="running", message="agent is working")
    idle = dict(fixture("wait-idle.json"), agentId=permission["agentId"])
    responses = [permission, running, running, running, running, idle]
    now = [100.0]

    def wall_time():
        value = now[0]
        now[0] += 10
        return value

    shadow_time(monkeypatch, time=wall_time)
    monkeypatch.setattr(driver, "time", SimpleNamespace(**vars(queue.time)))

    def guarded(_argv, **_kwargs):
        return 0, json.dumps(responses.pop(0)), ""

    monkeypatch.setattr(driver, "run_guarded", guarded)
    monkeypatch.setattr(driver, "check_permits", lambda _job: None)
    job = {"queue_supervised": True, "jobdir": str(tmp_path),
           "coder_agent": permission["agentId"], "spec": {"agent_timeout": 1000,
               "queue": {"permission_no_progress_seconds": 30}}}
    driver.wait_for_agent(job, "coder")
    state = queue.load_state(tmp_path)
    assert state["permission_prompts"] == 1 and now[0] - 100 > 30
    assert state["permission_started_at"] is None


def test_owned_trust_still_denies_outside_and_risky_descriptions():
    rows = [
        dict(fixture("permit-owned-write.json")[0],
             description="May I write pkg/mathx.py outside this workspace?"),
        dict(fixture("permit-owned-write.json")[0], description="May I run curl https://x?"),
        dict(fixture("permit-owned-write.json")[0], description="May I git push this branch?"),
        dict(fixture("permit-owned-write.json")[0], description="May I rm -rf a generated file?"),
    ]
    for row in rows:
        decision, _, _ = queue.classify_permit_record(row)
        assert decision == "DENY"


def test_permit_classifier_uses_job_roots_and_cross_platform_absolute_paths(tmp_path):
    repo = "C:\\Users\\Example\\work\\repo"
    row = permit_row("CodexFileChange", "Write C:\\Users\\AnotherUser\\secrets\\x.py")
    assert queue.classify_permit_record(row, trusted_roots=[repo])[0] == "DENY"
    in_repo = permit_row("CodexFileChange", "Write C:\\Users\\Example\\work\\repo\\pkg\\x.py")
    assert queue.classify_permit_record(in_repo, trusted_roots=[repo])[0] == "UNKNOWN"


def test_supervisor_migrates_missing_attempts_collection(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"task_id": "legacy", "publish": False}), encoding="utf-8")
    jobdir = tmp_path / "job"
    state = create_state(jobdir)
    state.pop("attempts")
    state["spec_path"] = str(spec_path)
    queue.atomic_json(jobdir / "state.json", state)

    def child(*_args, **_kwargs):
        return fake_result(rc=2, out="human needed")

    shadow_subprocess(monkeypatch, run=child)
    assert queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                           sleep_fn=lambda _seconds: None) == 2
    saved = queue.load_state(jobdir)
    assert len(saved["attempts"]) == 1 and saved["status"] == "parked"
    assert "KeyError" not in capsys.readouterr().out


def test_queue_stop_missing_job_fails_without_creating_anything(tmp_path, capsys):
    jobdir = tmp_path / "missing-job"
    assert queue.cli(["queue", "stop", str(jobdir)], ROOT / "tools/agentcoder/agentcoder.py") == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error" and "does not exist" in output["reason"]
    assert not jobdir.exists()


def test_supervise_terminal_resume_reemits_terminal_event(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"task_id": "queue-test"}), encoding="utf-8")
    jobdir = tmp_path / "job"
    state = create_state(jobdir)
    event = queue.save_terminal(jobdir, state, "parked", "already done")
    shadow_subprocess(monkeypatch,
                      run=lambda *_a, **_k: pytest.fail("driver child spawned"))
    assert queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                           sleep_fn=lambda _seconds: None) == 2
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["event_id"] == event["event_id"] and emitted["status"] == "parked"


def test_supervised_send_and_wait_use_shared_queue_validators(tmp_path, monkeypatch):
    driver = load_driver("agentcoder_shared_queue_response_validators")
    monkeypatch.setitem(sys.modules, "queue_mode", queue)
    create_state(tmp_path)
    called = {"send": 0, "wait": 0}
    original_send = queue.validate_send_result
    original_wait = queue.validate_wait_result

    def send_validator(*args, **kwargs):
        called["send"] += 1
        return original_send(*args, **kwargs)

    def wait_validator(*args, **kwargs):
        called["wait"] += 1
        return original_wait(*args, **kwargs)

    monkeypatch.setattr(queue, "validate_send_result", send_validator)
    monkeypatch.setattr(queue, "validate_wait_result", wait_validator)
    responses = [fixture("send-permission.json"), fixture("wait-idle.json")]

    def guarded(argv, **_kwargs):
        return 0, json.dumps(responses.pop(0)), ""

    monkeypatch.setattr(driver, "run_guarded", guarded)
    monkeypatch.setattr(driver, "check_permits", lambda _job: None)
    job = {"queue_supervised": True, "jobdir": str(tmp_path),
           "coder_agent": "agent-running-001", "spec": {"agent_timeout": 30}}
    driver.send_to(job, "coder_agent", "continue")
    assert called == {"send": 1, "wait": 1}


def test_completed_send_is_not_replayed_when_same_phase_resumes(tmp_path, monkeypatch):
    driver = load_driver("agentcoder_completed_send_resume")
    monkeypatch.setitem(sys.modules, "queue_mode", queue)
    create_state(tmp_path)
    sends = []

    def guarded(argv, **_kwargs):
        sends.append(argv)
        return 0, json.dumps(fixture("send-completed.json")), ""

    monkeypatch.setattr(driver, "run_guarded", guarded)
    monkeypatch.setattr(driver, "check_permits", lambda _job: None)
    job = {"queue_supervised": True, "jobdir": str(tmp_path),
           "coder_agent": "agent-completed-001", "phase": "coder",
           "spec": {"agent_timeout": 30}}
    driver.send_to(job, "coder_agent", "same phase instruction")
    driver.send_to(job, "coder_agent", "same phase instruction")
    assert len(sends) == 1


def test_task_qualified_wait_reads_single_job_layout_and_tolerates_registration(tmp_path):
    state = create_state(tmp_path, task_id="single-task")
    queue.save_terminal(tmp_path, state, "parked", "needs human")
    event, code = queue.wait_for_event(tmp_path, task_id="single-task", after="0", timeout=0)
    assert event["task_id"] == "single-task" and code == 2
    missing, code = queue.wait_for_event(tmp_path / "not-registered", task_id="later",
                                         after="0", timeout=0)
    assert missing["status"] == "timeout" and code == 124


def test_permission_run_records_agent_then_processes_and_waits(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_permission_run_fixture", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    create_state(tmp_path)
    permission_run = fixture("run-permission.json")
    calls = []
    monkeypatch.setattr(driver, "ensure_workspace", lambda *_args: "wks_fixture")
    def run_guarded(argv, **_kwargs):
        if argv[1] == "wait":
            calls.append("wait-idle")
            idle = dict(fixture("wait-idle.json"), agentId=permission_run["agentId"])
            return 0, json.dumps(idle), ""
        return 0, json.dumps(permission_run), (FIXTURES / "run-blocking.stderr.txt").read_text()

    monkeypatch.setattr(driver, "run_guarded", run_guarded)
    monkeypatch.setattr(driver, "agent_cwd", lambda _job, _id: permission_run["cwd"])
    monkeypatch.setattr(driver, "save_job", lambda _job: None)
    monkeypatch.setattr(driver, "check_permits", lambda _job: calls.append("permissions"))
    job = {"queue_supervised": True, "jobdir": str(tmp_path), "task_id": "t",
           "spec": {"repo": str(tmp_path), "agent_timeout": 10}}
    driver.spawn_agent(job, "coder", "codex/gpt-6-luna", "base", "prompt")
    assert calls == ["permissions", "wait-idle"]
    assert job["coder_agent"] == permission_run["agentId"]
    operation = next(iter(queue.read_json(tmp_path / "state.json")["operations"].values()))
    assert operation["status"] == "adopted"


def test_run_send_wait_share_permission_response_classification():
    cases = [
        (fixture("run-completed.json"), None,
         {"agentId", "status", "provider", "cwd", "title"}),
        (fixture("wait-idle.json"), "agent-running-001",
         {"agentId", "status", "message"}),
        (fixture("run-permission.json"), None,
         {"agentId", "status", "provider", "cwd", "title"}),
        (fixture("send-permission.json"), "agent-running-001",
         {"agentId", "status", "message"}),
        (fixture("run-running.json"), None,
         {"agentId", "status", "provider", "cwd", "title"}),
        (fixture("wait-permission.json"), "agent-permission-001",
         {"agentId", "status", "message"}),
    ]
    assert [queue.classify_agent_response(payload, aid, fields)[0]
            for payload, aid, fields in cases] == [
                "completed", "idle", "permission", "permission", "running", "permission"]
    unknown = dict(fixture("send-permission.json"), status="mystery")
    assert queue.classify_agent_response(
        unknown, "agent-running-001", {"agentId", "status", "message"})[0] == "unknown"


def test_send_permission_is_accepted_once_then_waits_for_idle(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_send_permission_fixture", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    create_state(tmp_path)
    listing = fixture("ls-g-permission.json")
    send_permission = dict(fixture("send-permission.json"), agentId=listing[0]["id"])
    wait_idle = dict(fixture("wait-idle.json"), agentId=send_permission["agentId"])
    row = dict(fixture("permit-no-description.json"), agentId=listing[0]["id"],
               agentShortId=listing[0]["shortId"])
    calls, events, responses = [], [], [send_permission, wait_idle]

    def guarded(argv, **_kwargs):
        calls.append(argv)
        if argv[1] == "send":
            events.append("send")
        elif argv[1] == "wait":
            events.append("wait")
        return 0, json.dumps(responses.pop(0)), ""

    def permit_check(_job):
        decision, _ = queue.process_permits(
            tmp_path, [listing[0]["id"]], listing, [row],
            lambda argv: (events.append("allow" if argv[1] == "allow" else "permit-list")
                          or fake_result(out="[]")),
            trust_owned_agents=True)
        assert decision == "CLEAR"

    monkeypatch.setattr(driver, "run_guarded", guarded)
    monkeypatch.setattr(driver, "check_permits", permit_check)
    job = {"queue_supervised": True, "jobdir": str(tmp_path), "task_id": "send-permission",
           "coder_agent": send_permission["agentId"], "spec": {"agent_timeout": 30,
               "queue": {"trust_owned_agents": True}}}
    driver.send_to(job, "coder_agent", "continue working")
    assert sum(argv and argv[0:2] == ["paseo", "send"] for argv in calls) == 1
    assert calls[0][:2] == ["paseo", "send"]
    assert calls[-1][0:2] == ["paseo", "wait"]
    assert events == ["send", "allow", "permit-list", "wait"]
    operation = next(iter(queue.load_state(tmp_path)["operations"].values()))
    assert operation["status"] == "adopted" and operation["agent_id"] == send_permission["agentId"]


def test_supervise_initial_state_records_first_spawn_and_parks_crash(tmp_path, monkeypatch):
    """Exercise supervise's actual initializer before the first supervised turn."""
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_first_spawn_fixture", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    spec_path, jobdir = tmp_path / "spec.json", tmp_path / "job"
    spec = {"task_id": "first-spawn", "queue": {"enabled": True}}
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    run = fixture("run-permission.json")
    monkeypatch.setattr(driver, "agent_cwd", lambda _job, _agent_id: run["cwd"])

    def child_run(cmd, **kwargs):
        assert "--queue-supervised" in cmd
        job = {"queue_supervised": True, "jobdir": str(jobdir),
               "task_id": spec["task_id"], "spec": spec}
        driver.record_turn(job, "coder", 0, json.dumps(run), "workspace banner")
        raise TypeError("simulated post-spawn supervisor fault")

    shadow_subprocess(monkeypatch, run=child_run)
    result = queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                             sleep_fn=lambda _seconds: None)
    assert result == 2
    state = queue.load_state(jobdir)
    assert run["agentId"] in state["owned_agents"]
    assert state["status"] == "parked"
    assert "Traceback" not in state["outcome"]
    attempts = list((jobdir / "attempts").glob("attempt-*"))
    assert attempts and "Traceback" in (attempts[0] / "stderr.txt").read_text()


def test_state_loader_rejects_wrong_owned_agent_shape(tmp_path):
    create_state(tmp_path, owned_agents=[])
    try:
        queue.load_state(tmp_path)
    except queue.QueueError as exc:
        assert "owned_agents" in str(exc) and "object" in str(exc)
    else:
        raise AssertionError("list-shaped owned_agents must be rejected clearly")


def test_state_loader_rejects_wrong_nested_collection_shapes(tmp_path):
    create_state(tmp_path, maintenance={"agents": []})
    try:
        queue.load_state(tmp_path)
    except queue.QueueError as exc:
        assert "maintenance.agents" in str(exc)
    else:
        raise AssertionError("list-shaped maintenance agent rows must be rejected clearly")


def test_unexpected_supervisor_exception_is_a_short_durable_park(tmp_path, monkeypatch):
    jobdir, spec_path = tmp_path / "job", tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"task_id": "supervisor-fault"}), encoding="utf-8")
    jobdir.mkdir()
    create_state(jobdir)
    (jobdir / "job.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(queue, "_listing_from_cli", lambda: (_ for _ in ()).throw(
        TypeError("simulated inventory failure")))
    shadow_subprocess(monkeypatch,
                      run=lambda *_a, **_k: pytest.fail("driver child spawned"))
    assert queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                           sleep_fn=lambda _seconds: None) == 2
    state = queue.load_state(jobdir)
    assert state["status"] == "parked"
    assert "TypeError" in state["outcome"] and "Traceback" not in state["outcome"]
    attempt = Path(state["attempts"][-1]["path"])
    assert "Traceback" in (attempt / "stderr.txt").read_text(encoding="utf-8")


def test_record_turn_writes_agent_ownership_before_job_save(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_write_ahead_fixture", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    create_state(tmp_path, owned_agents={})
    run = fixture("run-permission.json")
    monkeypatch.setattr(driver, "agent_cwd", lambda _job, _agent_id: run["cwd"])

    def crash_save(_job):
        assert run["agentId"] in queue.load_state(tmp_path)["owned_agents"]
        raise OSError("simulated job journal failure")

    monkeypatch.setattr(driver, "save_job", crash_save)
    job = {"queue_supervised": True, "jobdir": str(tmp_path), "task_id": "t",
           "spec": {}}
    try:
        driver.record_turn(job, "coder", 0, json.dumps(run), "")
    except OSError:
        pass
    else:
        raise AssertionError("simulated crash should propagate to supervisor boundary")
    assert run["agentId"] in queue.load_state(tmp_path)["owned_agents"]
    listing = [dict(fixture("ls-g.json")[0], id=run["agentId"],
                    shortId=run["agentId"][:7], status="running")]
    after = [dict(listing[0], status="idle")]
    listings = [listing, after]
    calls = []
    status, _ = queue.maintenance_stop(
        tmp_path,
        lambda argv: (calls.append(argv) or fake_result(out=json.dumps(
            {"stoppedCount": 1, "agentIds": [run["agentId"]]}))),
        lambda: (listings.pop(0), None))
    assert status == "PAUSED" and calls == [["stop", run["agentId"], "--json"]]


def test_run_unknown_status_still_parks():
    run = dict(fixture("run-permission.json"), status="mystery")
    assert not queue.validate_run_result(run)[0]
    assert queue.validate_run_result(fixture("run-permission.json"))[0]


def test_captured_daemon_payload_validators():
    run = fixture("run-completed.json")
    assert queue.validate_run_result(run)[0]
    assert queue.validate_run_result(fixture("run-running.json"))[0]
    assert not queue.validate_run_result(dict(run, extra="unverified"))[0]
    assert queue.validate_send_result(fixture("send-completed.json"),
                                      "agent-completed-001")[0]
    assert queue.validate_wait_result(fixture("wait-idle.json"), "agent-running-001")[0]
    assert queue.validate_wait_result(fixture("wait-permission.json"), "agent-permission-001")[0]
    assert queue.validate_stop_result(fixture("stop-running.json"), "agent-running-001")[0]
    assert queue.validate_stop_result(fixture("stop-idle.json"), "agent-running-001")[0]
    permit = fixture("permit-pending.json")[0]
    assert set(permit) == {"id", "agentId", "agentShortId", "name", "description"}
    assert queue.classify_permit_record(permit)[0] == "DENY"


def test_supervised_run_uses_stdout_json_and_ignores_stderr_banner(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_run_fixture", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    create_state(tmp_path)
    job = {"queue_supervised": True, "jobdir": str(tmp_path), "spec": {}}
    monkeypatch.setattr(driver, "paseo_ls", lambda: fixture("ls-g.json"))
    monkeypatch.setattr(driver, "save_job", lambda _job: None)
    stdout = json.dumps(fixture("run-completed.json"))
    stderr = (FIXTURES / "run-blocking.stderr.txt").read_text()
    driver.record_turn(job, "coder", 0, stdout, stderr)
    assert job["coder_agent"] == "agent-completed-001"
    assert queue.read_json(tmp_path / "state.json")["owned_agents"]["agent-completed-001"]


def test_supervised_workspace_create_uses_captured_json(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_create_fixture", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    calls = []
    monkeypatch.setattr(driver, "run_guarded", lambda argv, **kwargs: (
        calls.append(argv) or (0, json.dumps(fixture("workspace-create.json")),
                               "Using workspace wks_fixture\n")))
    monkeypatch.setattr(driver, "save_job", lambda _job: None)
    job = {"queue_supervised": True, "task_id": "t", "spec": {"repo": str(tmp_path)}}
    assert driver.ensure_workspace(job, "coder", "base", "branch") == \
        fixture("workspace-create.json")["workspaceId"]
    assert calls and calls[0][-1] == "--json"


def test_supervised_send_and_idle_wait_use_captured_json(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_send_wait_fixture", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    create_state(tmp_path)
    agent_id = "agent-completed-001"
    job = {"queue_supervised": True, "jobdir": str(tmp_path), "spec": {},
           "coder_agent": agent_id}
    send = dict(fixture("send-completed.json"), agentId=agent_id)
    monkeypatch.setattr(driver, "run_guarded", lambda *_args, **_kwargs:
                        (0, json.dumps(send), ""))
    monkeypatch.setattr(driver, "check_permits", lambda _job: None)
    driver.send_to(job, "coder_agent", "continue")
    state = queue.read_json(tmp_path / "state.json")
    assert next(iter(state["operations"].values()))["status"] == "completed"
    wait_job = {"queue_supervised": True, "jobdir": str(tmp_path), "spec": {},
                "coder_agent": "agent-running-001"}
    monkeypatch.setattr(driver, "run_guarded", lambda *_args, **_kwargs:
                        (0, json.dumps(fixture("wait-idle.json")), ""))
    driver.wait_for_agent(wait_job, "coder")


def test_foreign_permit_untouched(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g.json")
    calls = []
    result, _ = queue.process_permits(
        jobdir, [listing[1]["id"]], listing,
        [permit_row("external_directory", "/tmp", short=listing[0]["shortId"])],
        lambda argv: (calls.append(argv) or fake_result()), trust_owned_agents=True)
    assert result == "CLEAR" and calls == []
    assert "permit_decisions" not in queue.read_json(jobdir / "state.json")


def test_owned_agent_resume_adopts_exact_ids(tmp_path):
    rows = fixture("ls-g.json")
    owned = [rows[0]["id"], rows[1]["id"]]
    adopted, uncertain = queue.reconcile_owned_agents(owned, rows)
    assert adopted == {owned[0]: "active", owned[1]: "idle"} and uncertain == {}
    changed = [dict(rows[0], shortId="f39938x"), rows[1]]
    adopted, uncertain = queue.reconcile_owned_agents([owned[0]], changed)
    assert not adopted and owned[0] in uncertain
    adopted, uncertain = queue.reconcile_owned_agents(["missing-full-agent-id"], rows)
    assert not adopted and "do not relaunch" in uncertain["missing-full-agent-id"]
    permission_listing = fixture("ls-g-permission.json")
    adopted, uncertain = queue.reconcile_owned_agents(
        [permission_listing[0]["id"]], permission_listing)
    assert adopted == {permission_listing[0]["id"]: "active"} and uncertain == {}
    wait = fixture("wait-idle.json")
    assert queue.validate_wait_result(wait, wait["agentId"])[0]
    assert not queue.validate_wait_result(wait, "different-full-id")[0]
    assert not queue.validate_wait_result(dict(wait, status="error"), wait["agentId"])[0]


def test_reconcile_job_agents_keeps_state_owned_ids(tmp_path):
    listing = fixture("ls-g.json")
    agent_id = listing[0]["id"]
    create_state(tmp_path, owned_agents={agent_id: {"role": "reviewer"}})
    queue.atomic_json(tmp_path / "job.json", {})
    adopted, uncertain = queue.reconcile_job_agents(tmp_path, listing)
    assert adopted == {agent_id: "active"} and uncertain == {}
    assert agent_id in queue.load_state(tmp_path)["owned_agents"]


def test_unverified_listing_shape_parks_with_evidence():
    adopted, uncertain = queue.reconcile_owned_agents([fixture("ls-g.json")[0]["id"]],
                                                       {"error": {"code": "UNKNOWN"}})
    assert not adopted and "not an array" in next(iter(uncertain.values()))


def test_verdict_garbage_not_green():
    state, action, reason = queue.bounded_recovery(
        {}, {"kind": "garbled_finish", "operation_reconciled": False,
             "raw": "all looks good"}, 20)
    assert action == "park" and "unreconciled" in reason
    state, action, _ = queue.bounded_recovery(
        {}, {"kind": "garbled_finish", "operation_reconciled": True}, 20)
    assert action == "continue_same_workspace" and state["verdict_repair_used"]
    state, action, _ = queue.bounded_recovery(
        state, {"kind": "garbled_finish", "operation_reconciled": True}, 21)
    assert action == "park"
    assert not queue.verified_job_completion({"phase": "done", "status": "ready-for-human-gate"})


def test_recovery_preserves_workspace_and_edits(tmp_path, monkeypatch):
    path = tmp_path / "role"
    path.mkdir()
    (path / "edit.txt").write_text("retained uncommitted edit")
    module_spec = importlib.util.spec_from_file_location(
        "agentcoder_for_queue_test", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(driver)
    job = {"queue_supervised": True, "task_id": "t", "spec": {},
           "coder_workspace": "wks-existing", "coder_workspace_ready": True}
    monkeypatch.setattr(driver, "workspace_cwd", lambda _job, _wid: str(path))
    monkeypatch.setattr(driver, "prepare_tree", lambda *args: (_ for _ in ()).throw(
        AssertionError("recovery must not reset the role tree")))
    assert driver.ensure_workspace(job, "coder", "base", "branch") == "wks-existing"
    assert (path / "edit.txt").read_text() == "retained uncommitted edit"


def test_workspace_listing_uses_captured_fields(tmp_path, monkeypatch):
    driver_spec = importlib.util.spec_from_file_location(
        "agentcoder_workspace_fixture", ROOT / "tools" / "agentcoder" / "agentcoder.py")
    driver = importlib.util.module_from_spec(driver_spec)
    driver_spec.loader.exec_module(driver)
    rows = fixture("workspace-ls.json")
    job = {"queue_supervised": True}
    monkeypatch.setattr(driver, "workspace_ls", lambda: rows)
    assert driver.workspace_cwd(job, rows[1]["workspaceId"]) == rows[1]["cwd"]
    monkeypatch.setattr(driver, "workspace_ls", lambda: [dict(rows[1], uncaptured="x")])
    try:
        driver.workspace_cwd(job, rows[1]["workspaceId"])
    except driver.Pause as exc:
        assert "unknown workspace row shape" in str(exc)
    else:
        raise AssertionError("uncaptured workspace fields must fail closed")


def test_uncertain_send_parks():
    assert queue.resolve_send_acceptance(None) == "PARK"
    _state, action, reason = queue.bounded_recovery({}, {"kind": "uncertain_send"}, 0)
    assert action == "park" and "refusing duplicate" in reason
    assert queue.resolve_send_acceptance(True) == "ADOPT"
    assert queue.resolve_send_acceptance(False) == "RETRY_SAFE"


def test_maintenance_stop_intent_survives_restart(tmp_path, monkeypatch):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    agent_id = fixture("ls-g.json")[0]["id"]
    queue.atomic_json(jobdir / "job.json", {"coder_agent": agent_id})
    listings = [fixture("ls-g.json"), [dict(fixture("ls-g.json")[0], status="idle")]]
    calls = []

    def listing_fn():
        return listings.pop(0), None

    status, _ = queue.maintenance_stop(
        jobdir, lambda argv: (calls.append(argv) or fake_result(
            out=json.dumps(fixture("stop-running.json")))), listing_fn)
    assert status == "PAUSED" and calls == [["stop", agent_id, "--json"]]
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"task_id": "queue-test"}))
    state = queue.read_json(jobdir / "state.json")
    state["spec_path"] = str(spec_path)
    queue.atomic_json(jobdir / "state.json", state)
    # Restarting the supervisor observes and preserves, rather than clears, intent.
    shadow_subprocess(monkeypatch,
                      run=lambda *_a, **_k: pytest.fail("driver child spawned"))
    assert queue.read_json(jobdir / "state.json")["maintenance"]["intent"] == "maintenance"
    assert queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                           sleep_fn=lambda _seconds: None) == 1
    assert queue.read_json(jobdir / "state.json")["maintenance"]["intent"] == "maintenance"


def test_corrupt_state_fails_closed_without_overwrite(tmp_path, monkeypatch, capsys):
    jobdir = tmp_path / "job"
    jobdir.mkdir()
    state_path = jobdir / "state.json"
    original = b'{"status": broken\n'
    state_path.write_bytes(original)
    assert queue.cli(["queue", "wait", str(jobdir), "--after", "0"],
                     ROOT / "tools/agentcoder/agentcoder.py") == 1
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["status"] == "error"
    assert state_path.read_bytes() == original

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"task_id": "corrupt"}), encoding="utf-8")
    shadow_subprocess(monkeypatch,
                      run=lambda *_a, **_k: pytest.fail("driver child spawned"))
    queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                    sleep_fn=lambda _seconds: None)
    # Unlike queue wait, supervise currently catches the corruption and parks by
    # replacing state.json with a short durable supervisor-failure record.
    assert state_path.read_bytes() != original
    assert queue.load_state(jobdir)["status"] == "parked"


def test_wait_completion_before_registration(tmp_path):
    """Finds a terminal event already durable before the waiter starts; no hint race is simulated."""
    state = create_state(tmp_path)
    queue.save_terminal(tmp_path, state, "parked", "human needed")
    event, code = queue.wait_for_event(tmp_path, after="0", timeout=0)
    assert event["status"] == "parked" and code == 2


def test_wait_lost_hint_rechecks_durable_state(tmp_path):
    """Finds durable state after a lost hint; the hint transport itself is not exercised."""
    state = create_state(tmp_path)
    queue.save_terminal(tmp_path, state, "landed", "ready")
    event, code = queue.wait_for_event(tmp_path, after="0", timeout=0)
    assert event["status"] == "landed" and code == 0


def test_wait_survives_supervisor_restart(tmp_path):
    """Reads persisted event state without a live supervisor; no process restart is launched."""
    state = create_state(tmp_path)
    queue.save_terminal(tmp_path, state, "parked", "retained")
    event, _ = queue.wait_for_event(tmp_path, after="0", timeout=0)
    assert event["event_id"] == "queue-test:1"


def test_wait_after_cursor_honors_task_id(tmp_path):
    qdir = tmp_path / "batch"
    for task_id in ("a", "b"):
        jobdir = qdir / "jobs" / task_id
        state = create_state(jobdir, task_id=task_id)
        queue.save_terminal(jobdir, state, "parked", "needs human")
    event, code = queue.wait_for_event(qdir, after="a:1", timeout=0)
    assert code == 2 and event["task_id"] == "b" and event["event_id"] == "b:1"


def test_terminal_hook_failure_still_wakes_parent(tmp_path):
    state = create_state(tmp_path)
    event = queue.save_terminal(tmp_path, state, "landed", "ready")
    saved = queue.read_json(tmp_path / "state.json")
    saved["notification_command"] = ["notify"]
    queue.atomic_json(tmp_path / "state.json", saved)
    queue.notify_terminal(tmp_path, event, lambda _argv: fake_result(rc=1, out="hook down"))
    replayed, code = queue.wait_for_event(tmp_path, after="0", timeout=0)
    assert replayed["event_id"] == event["event_id"] and code == 0
    saved = queue.read_json(tmp_path / "state.json")
    assert saved["hook_results"][0]["status"] == "failed"


def _run_mutant(tmp_path, mutant, probe):
    scratch = ROOT / ".scratch" / ("agentcoder-mutation-" + uuid.uuid4().hex)
    scratch.mkdir(parents=True)
    module_path = scratch / "queue_mode.py"
    module_path.write_text(mutant, encoding="utf-8")
    probe_path = scratch / "probe.py"
    probe_path.write_text(probe, encoding="utf-8")
    result = subprocess.run([sys.executable, str(probe_path), str(module_path)],
                            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    (scratch / "mutation-result.txt").write_text(
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
        encoding="utf-8")
    return result


def test_classifier_mutation_is_caught_in_disposable_copy(tmp_path):
    source = QPATH.read_text(encoding="utf-8")
    old = 'if REFERENCE_RISKY.search(name + "\\n" + description):'
    assert old in source
    mutant = source.replace(old, 'if False and REFERENCE_RISKY.search(name + "\\n" + description):', 1)
    probe = """import importlib.util, sys
spec=importlib.util.spec_from_file_location('mutant',sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
row={'agentShortId':'f399385','agentId':'f3993852-557c-4a4e-989b-6490584ef5c8','id':'r1','name':'CodexBash','description':'git push the branch'}
assert m.classify_permit_record(row)[0] == 'DENY'
"""
    result = _run_mutant(tmp_path, mutant, probe)
    assert result.returncode != 0, "risky-operation classifier mutation escaped the check"


def test_retry_bounds_mutation_is_caught_in_disposable_copy(tmp_path):
    source = QPATH.read_text(encoding="utf-8")
    old = "if used >= min(maximum, MAX_NUDGES):"
    assert old in source
    mutant = source.replace(old, "if used > min(maximum, MAX_NUDGES):", 1)
    probe = """import importlib.util, sys
spec=importlib.util.spec_from_file_location('mutant',sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s={'nudges':0,'max_nudges':2}
for i in range(3): s,action,_=m.bounded_recovery(s,{'kind':'idle'},i)
assert action == 'park'
"""
    result = _run_mutant(tmp_path, mutant, probe)
    assert result.returncode != 0, "nudge-bound mutation escaped the check"


def test_wall_clock_pauses_only_for_deliberate_maintenance():
    state = {"active_seconds": 4, "active_started_at": 10}
    assert queue.wall_elapsed(state, 15) == 9
    queue.stop_active_clock(state, 15)
    assert state["active_seconds"] == 9 and state["active_started_at"] is None
    queue.start_active_clock(state, 100)
    assert queue.wall_elapsed(state, 103) == 12


def test_daemon_recovery_backoff_is_excluded_from_active_budget():
    state = {"active_seconds": 4, "active_started_at": 10}
    queue.pause_active_for_backoff(state, 15)
    assert queue.wall_elapsed(state, 115) == 9
    queue.start_active_clock(state, 115)
    assert queue.wall_elapsed(state, 118) == 12


def test_wait_durable_recheck_mutation_is_caught_in_disposable_copy(tmp_path):
    source = QPATH.read_text(encoding="utf-8")
    old = "        for path in paths:"
    assert old in source
    mutant = source.replace(old, "        for path in []:", 1)
    probe = """import importlib.util, sys, tempfile, json
from pathlib import Path
spec=importlib.util.spec_from_file_location('mutant',sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as d:
 p=Path(d); p.mkdir(exist_ok=True)
 m.atomic_json(p/'state.json', {'task_id':'probe','status':'landed','event_seq':1,'outbox':[{'event_id':'probe:1','task_id':'probe','status':'landed'}]})
 event,code=m.wait_for_event(p,after='0',timeout=0)
 assert event['status']=='landed' and code==0
"""
    result = _run_mutant(tmp_path, mutant, probe)
    assert result.returncode != 0, "durable-state recheck mutation escaped the bounded timeout probe"
