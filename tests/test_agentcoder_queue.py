"""Offline tests for supervised recovery using captured Paseo payload fixtures."""
import importlib.util
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
QPATH = Path(os.environ.get("AGENTCODER_QUEUE_MODE_PATH",
                            str(ROOT / "tools" / "agentcoder" / "queue_mode.py")))
FIXTURES = ROOT / "tests" / "fixtures" / "agentcoder_queue"
spec = importlib.util.spec_from_file_location("queue_mode", QPATH)
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


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
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_windows_lock_fallback_is_exclusive_on_posix(tmp_path, monkeypatch):
    if importlib.util.find_spec("fcntl") is None:
        return  # The Windows runner exercises the real msvcrt backend instead.
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
            release.wait(2)

    def second():
        entered.wait(2)
        with queue.locked(tmp_path / "queue.lock"):
            second_entered.set()

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    two.start()
    assert entered.wait(2)
    assert not second_entered.wait(0.1)
    release.set()
    one.join(2)
    two.join(2)
    assert second_entered.is_set()


def create_state(path, **updates):
    path.mkdir(parents=True, exist_ok=True)
    state = {"task_id": "queue-test", "status": "running", "event_seq": 0,
             "outbox": [], "nudges": 0, "retries": 0, "owned_agents": {},
             "operations": {}, "attempts": []}
    state.update(updates)
    queue.atomic_json(path / "state.json", state)
    return state


def permit_row(name, description, short="agent-l", rid="req-1",
               agent_id="agent-live-running"):
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
            lambda argv: (calls.append(argv) or fake_result(out="[]")),
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
            stale = (FIXTURES / "permit-allow-stale.stderr.txt").read_text()
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


def test_stale_deny_race_is_benign(tmp_path):
    jobdir = tmp_path / "job"
    create_state(jobdir)
    listing = fixture("ls-g.json")
    calls = []

    def invoke(argv):
        calls.append(argv)
        if argv[:2] == ["permit", "deny"]:
            stale = (FIXTURES / "permit-allow-stale.stderr.txt").read_text()
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
        lambda argv: (calls.append(argv) or fake_result(out="[]")),
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
        lambda argv: (calls.append(argv) or fake_result(out="[]")),
        trust_owned_agents=True)
    assert allowed == "CLEAR"
    assert calls[0][:4] == ["permit", "allow", listing[0]["id"], row["id"]]
    risky = dict(row, name="CodexBash curl", description="-")
    denied, _ = queue.process_permits(
        jobdir, [listing[0]["id"]], listing, [risky],
        lambda argv: (calls.append(argv) or fake_result(out="[]")),
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
    queue.note_permission_prompt(state, 3, 5, now=14)
    try:
        queue.note_permission_prompt(state, 3, 5, now=16)
    except queue.QueueError as exc:
        assert "no-progress timer" in str(exc)
    else:
        raise AssertionError("permission chain must stop at its no-progress deadline")


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
        (fixture("wait-idle.json"), "agent-live-running",
         {"agentId", "status", "message"}),
        (fixture("run-permission.json"), None,
         {"agentId", "status", "provider", "cwd", "title"}),
        (fixture("send-permission.json"), "agent-live-running",
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
        unknown, "agent-live-running", {"agentId", "status", "message"})[0] == "unknown"


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

    def child_run(_cmd, **_kwargs):
        job = {"queue_supervised": True, "jobdir": str(jobdir),
               "task_id": spec["task_id"], "spec": spec}
        driver.record_turn(job, "coder", 0, json.dumps(run), "workspace banner")
        raise TypeError("simulated post-spawn supervisor fault")

    monkeypatch.setattr(queue.subprocess, "run", child_run)
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
    assert queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py") == 2
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
                                      "agent-live-completed")[0]
    assert queue.validate_wait_result(fixture("wait-idle.json"), "agent-live-running")[0]
    assert queue.validate_wait_result(fixture("wait-permission.json"), "agent-permission-001")[0]
    assert queue.validate_stop_result(fixture("stop-running.json"), "agent-live-running")[0]
    assert queue.validate_stop_result(fixture("stop-idle.json"), "agent-live-running")[0]
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
    monkeypatch.setattr(driver, "agent_cwd", lambda _job, _id: "/workspace/probe")
    monkeypatch.setattr(driver, "save_job", lambda _job: None)
    stdout = json.dumps(fixture("run-completed.json"))
    stderr = (FIXTURES / "run-blocking.stderr.txt").read_text()
    driver.record_turn(job, "coder", 0, stdout, stderr)
    assert job["coder_agent"] == "agent-live-completed"
    assert queue.read_json(tmp_path / "state.json")["owned_agents"]["agent-live-completed"]


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
    agent_id = "agent-live-completed"
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
                "coder_agent": "agent-live-running"}
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
    state, action, reason = queue.bounded_recovery({}, {"kind": "uncertain_send"}, 0)
    assert action == "park" and "refusing duplicate" in reason
    assert queue.resolve_send_acceptance(True) == "ADOPT"
    assert queue.resolve_send_acceptance(False) == "RETRY_SAFE"


def test_maintenance_stop_intent_survives_restart(tmp_path):
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
    assert queue.read_json(jobdir / "state.json")["maintenance"]["intent"] == "maintenance"
    assert queue.supervise(spec_path, jobdir, ROOT / "tools/agentcoder/agentcoder.py",
                           sleep_fn=lambda _seconds: None) == 1
    assert queue.read_json(jobdir / "state.json")["maintenance"]["intent"] == "maintenance"


def test_wait_completion_before_registration(tmp_path):
    state = create_state(tmp_path)
    queue.save_terminal(tmp_path, state, "parked", "human needed")
    event, code = queue.wait_for_event(tmp_path, after="0", timeout=0)
    assert event["status"] == "parked" and code == 2


def test_wait_lost_hint_rechecks_durable_state(tmp_path):
    state = create_state(tmp_path)
    queue.save_terminal(tmp_path, state, "landed", "ready")
    event, code = queue.wait_for_event(tmp_path, after="0", timeout=0)
    assert event["status"] == "landed" and code == 0


def test_wait_survives_supervisor_restart(tmp_path):
    state = create_state(tmp_path)
    queue.save_terminal(tmp_path, state, "parked", "retained")
    event, _ = queue.wait_for_event(tmp_path, after="0", timeout=0)
    assert event["event_id"] == "queue-test:1"


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
                            cwd=ROOT, capture_output=True, text=True, timeout=15)
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
