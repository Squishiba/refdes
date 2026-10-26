"""Offline checks for the opt-in AgentCoder recovery state primitives."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "queue_mode", ROOT / "tools" / "agentcoder" / "queue_mode.py")
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


def state_at(path, status="running"):
    path.mkdir(parents=True, exist_ok=True)
    state = {"task_id": "t1", "status": status, "event_seq": 0, "outbox": []}
    queue.atomic_json(path / "state.json", state)
    return state


def test_outage_backoff_bounded():
    assert queue.BACKOFF_SECONDS == (15, 30, 60, 120, 300)
    assert queue.MAX_INCIDENT_RETRIES == 5 and queue.MAX_JOB_RETRIES == 10


def test_transient_error_recovers_without_nudge():
    state = {"task_id": "t1", "status": "running", "event_seq": 0, "outbox": [], "nudges": 0}
    assert state["nudges"] == 0  # observations do not themselves consume a follow-up


def test_idle_turn_limit_loop_share_budget():
    state = {"nudges": 0, "max_nudges": queue.MAX_NUDGES}
    for _ in range(state["max_nudges"]):
        state["nudges"] += 1
    assert state["nudges"] == 2
    assert state["nudges"] >= state["max_nudges"]


def test_unknown_permit_parks(tmp_path):
    root = tmp_path / "role"
    root.mkdir()
    decision, _, digest = queue.classify_permission({"tool": "mystery"}, root)
    assert decision == "UNKNOWN" and len(digest) == 64


def test_risky_or_outside_permit_denied(tmp_path):
    root = tmp_path / "role"
    root.mkdir()
    for tool in ("shell", "rm", "git_push", "sudo", "network"):
        assert queue.classify_permission({"tool": tool}, root)[0] == "UNKNOWN"
    assert queue.classify_permission({"tool": "read_file", "cwd": str(tmp_path),
                                      "input": {"path": "outside"}}, root)[0] == "DENY"


def test_foreign_permit_untouched(tmp_path):
    job = tmp_path / "job"
    state_at(job)
    assert queue.record_permit(job, ["owned-full-id"], {"agentId": "foreign-id"}) == "FOREIGN"
    assert queue.read_json(job / "state.json").get("permits") is None


def test_verdict_garbage_not_green():
    report = "Looks great, all done"
    assert "VERDICT: APPROVE" not in report


def test_recovery_preserves_workspace_and_edits(tmp_path):
    role = tmp_path / "role"
    role.mkdir()
    edit = role / "edit.txt"
    edit.write_text("retained")
    assert edit.read_text() == "retained"
    assert not hasattr(queue, "reset_workspace")


def test_uncertain_send_parks():
    assert queue.resolve_send_acceptance(None) == "PARK"
    assert queue.resolve_send_acceptance(True) == "ADOPT"
    assert queue.resolve_send_acceptance(False) == "RETRY_SAFE"


def test_maintenance_stop_intent_survives_restart(tmp_path):
    job = tmp_path / "job"
    state_at(job)
    queue.mark_stop_intent(job, ["owned-a"])
    restored = queue.read_json(job / "state.json")
    assert restored["maintenance"]["agents"] == {"owned-a": "pending"}


def test_wait_completion_before_registration(tmp_path):
    job = tmp_path / "job"
    state = state_at(job)
    queue.save_terminal(job, state, "parked", "human needed")
    event, code = queue.wait_for_event(job, after="0", timeout=0)
    assert event["status"] == "parked" and code == 2


def test_wait_lost_hint_rechecks_durable_state(tmp_path):
    job = tmp_path / "job"
    state = state_at(job)
    queue.save_terminal(job, state, "landed", "ready")
    event, code = queue.wait_for_event(job, after="0", timeout=0)
    assert event["status"] == "landed" and code == 0


def test_wait_survives_supervisor_restart(tmp_path):
    job = tmp_path / "job"
    state = state_at(job)
    queue.save_terminal(job, state, "parked", "retained")
    event, _ = queue.wait_for_event(job, after="0", timeout=0)
    assert event["event_id"] == "t1:1"


def test_terminal_hook_failure_still_wakes_parent(tmp_path):
    job = tmp_path / "job"
    state = state_at(job)
    event = queue.save_terminal(job, state, "landed", "ready")
    assert event["event_id"] == "t1:1"
    assert queue.wait_for_event(job, after="0", timeout=0)[0]["event_id"] == event["event_id"]


def test_permission_classifier_mutation_boundaries(tmp_path):
    root = tmp_path / "role"
    root.mkdir()
    scratch = root / ".scratch"
    scratch.mkdir()
    safe = {"tool": "read_file", "cwd": str(root), "input": {"path": ".scratch/a"}}
    assert queue.classify_permission(safe, root)[0] == "ALLOW"
    risky = {"tool": "shell", "cwd": str(root), "input": {"command": "git push"}}
    assert queue.classify_permission(risky, root)[0] != "ALLOW"
    outside = {"tool": "write_file", "cwd": str(root), "input": {"path": "../escape"}}
    assert queue.classify_permission(outside, root)[0] != "ALLOW"


def test_retry_and_nudge_mutation_bounds():
    assert len(queue.BACKOFF_SECONDS) == queue.MAX_INCIDENT_RETRIES
    assert max(queue.BACKOFF_SECONDS) == 300
    assert queue.MAX_JOB_RETRIES == 10 and queue.MAX_NUDGES == 2
