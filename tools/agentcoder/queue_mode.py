"""Opt-in, single-job AgentCoder supervision primitives.

This module intentionally does not change the legacy run/resume path. Queue
state is cooperative same-user state, not a security boundary.
"""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

POLL_SECONDS = 5
BACKOFF_SECONDS = (15, 30, 60, 120, 300)
MAX_INCIDENT_RETRIES = 5
MAX_JOB_RETRIES = 10
MAX_NUDGES = 2
MAX_ACTIVE_SECONDS = 14400
DENIAL = ("Queue policy denied this request: {reason}. Use only scoped relative paths and "
          "approved commands in your worktree; do not retry the denied operation.")


class QueueError(Exception):
    pass


def _fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with open(tmp, "x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


@contextmanager
def locked(lock_path):
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        raise QueueError(f"corrupt or unreadable state {path}: {exc}") from exc


def _event(state, kind, outcome):
    seq = int(state.get("event_seq", 0)) + 1
    event_id = f"{state['task_id']}:{seq}"
    event = {"event_id": event_id, "task_id": state["task_id"],
             "kind": kind, "status": state["status"], "outcome": outcome,
             "report": state.get("report"), "created": time.time()}
    state["event_seq"] = seq
    state.setdefault("outbox", []).append(event)
    return event


def save_terminal(jobdir, state, status, outcome):
    """Commit terminal status and its numbered event in one locked replacement."""
    jobdir = Path(jobdir)
    with locked(jobdir / "job.lock"):
        current = read_json(jobdir / "state.json") if (jobdir / "state.json").exists() else state
        if current.get("status") in ("landed", "parked", "failed"):
            return current.get("outbox", [])[-1]
        current.update(status=status, outcome=outcome, updated=time.time())
        event = _event(current, "terminal", outcome)
        atomic_json(jobdir / "state.json", current)
        return event


def bounded_raw(value, limit=8192):
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = repr(value)
    return raw[:limit]


def resolve_send_acceptance(accepted):
    """Never replay a send whose remote acceptance is ambiguous."""
    if accepted is True:
        return "ADOPT"
    if accepted is False:
        return "RETRY_SAFE"
    return "PARK"


def classify_permission(request, role_root, allowed_paths=()):
    """Return (decision, reason, hash); schema uncertainty is never permissive.

    The supported structured schema is deliberately narrow and must be extended
    only from a real recorded Paseo permit payload.
    """
    digest = hashlib.sha256(bounded_raw(request, 65536).encode()).hexdigest()
    if not isinstance(request, dict):
        return "UNKNOWN", "request is not an object", digest
    tool = request.get("tool")
    cwd = request.get("cwd")
    args = request.get("input")
    if tool not in {"read_file", "write_file", "edit_file"}:
        return "UNKNOWN", "unrecognized or opaque tool request", digest
    if not isinstance(cwd, str) or not os.path.isabs(cwd) or not isinstance(args, dict):
        return "UNKNOWN", "missing verified cwd or structured tool input", digest
    root = Path(role_root).resolve(strict=True)
    work = Path(cwd).resolve(strict=True)
    if work != root and root not in work.parents:
        return "DENY", "working directory is outside the role worktree", digest
    target_value = args.get("path")
    if not isinstance(target_value, str) or not target_value or os.path.isabs(target_value):
        return "UNKNOWN", "target path is missing or not relative", digest
    candidate = work / target_value
    # Resolve the nearest existing ancestor; nonexistent tails cannot conceal an
    # existing symlink escape.
    parent = candidate
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    resolved_parent = parent.resolve(strict=True)
    if resolved_parent != root and root not in resolved_parent.parents:
        return "DENY", "resolved target escapes the role worktree", digest
    target = candidate.resolve(strict=False)
    if target != root and root not in target.parents:
        return "DENY", "resolved target escapes the role worktree", digest
    rel = target.relative_to(root).as_posix()
    if rel == ".scratch" or rel.startswith(".scratch/"):
        return "ALLOW", "private role scratch path", digest
    import fnmatch
    if tool in {"write_file", "edit_file"} and not any(fnmatch.fnmatchcase(rel, p)
                                                       for p in allowed_paths):
        return "DENY", "write is outside declared role scope", digest
    return "ALLOW", "recognized structured local file operation", digest


def record_permit(jobdir, owned_ids, row):
    """Record exact owned permit decisions; foreign requests are untouched."""
    agent_id = row.get("agentId") if isinstance(row, dict) else None
    request_id = row.get("requestId") if isinstance(row, dict) else None
    if not isinstance(agent_id, str) or agent_id not in set(owned_ids):
        return "FOREIGN"
    if not isinstance(request_id, str) or not request_id:
        return "UNKNOWN"
    decision, reason, digest = classify_permission(row, row.get("cwd", "/"))
    with locked(Path(jobdir) / "job.lock"):
        state = read_json(Path(jobdir) / "state.json")
        record = {"agent_id": agent_id, "request_id": request_id,
                  "decision": decision, "reason": reason, "request_hash": digest,
                  "raw": bounded_raw(row)}
        state.setdefault("permits", []).append(record)
        atomic_json(Path(jobdir) / "state.json", state)
    return decision


def mark_stop_intent(jobdir, agent_ids, reason="maintenance"):
    jobdir = Path(jobdir)
    with locked(jobdir / "job.lock"):
        state = read_json(jobdir / "state.json")
        state["maintenance"] = {"intent": reason, "requested": time.time(),
                                "agents": {aid: "pending" for aid in agent_ids}}
        state["status"] = "paused"
        atomic_json(jobdir / "state.json", state)


def _parse_event(event):
    return int(event.get("event_id", "").rsplit(":", 1)[1])


def wait_for_event(qdir, task_id=None, after="0", timeout=None):
    """Durable-state-first wait. One-second polling makes hints optional."""
    qdir = Path(qdir)
    try:
        cursor = int(after.rsplit(":", 1)[-1])
    except (ValueError, AttributeError):
        raise QueueError("--after must be a numeric event ID or task:ID")
    started = time.monotonic()
    while True:
        paths = sorted((qdir / "jobs").glob("*/state.json"))
        if (qdir / "state.json").is_file():
            paths = [qdir / "state.json"]
        if task_id:
            paths = [qdir / "jobs" / task_id / "state.json"]
        events = []
        for path in paths:
            state = read_json(path)
            events.extend(e for e in state.get("outbox", [])
                          if _parse_event(e) > cursor and
                          e.get("status") in ("landed", "parked", "failed"))
        if events:
            event = min(events, key=_parse_event)
            event["batch_id"] = qdir.name
            return event, (0 if event["status"] == "landed" else 2)
        if timeout is not None and time.monotonic() - started >= timeout:
            return {"event_id": None, "batch_id": qdir.name, "task_id": task_id,
                    "status": "timeout", "outcome": None}, 124
        time.sleep(1)


def supervise(spec_path, jobdir, driver_path):
    """Run one legacy job as a child, retaining every invocation transcript.

    Recovery is deliberately conservative: daemon failures are backoff bounded;
    ambiguous child outcomes park. The child owns the existing acceptance gates.
    """
    spec_path, jobdir = Path(spec_path).resolve(), Path(jobdir).resolve()
    jobdir.mkdir(parents=True, exist_ok=True)
    state_path = jobdir / "state.json"
    with locked(jobdir / "job.lock"):
        if state_path.exists():
            state = read_json(state_path)
            if state.get("status") in ("landed", "parked", "failed"):
                return 0 if state["status"] == "landed" else 2
        else:
            spec = read_json(spec_path)
            state = {"task_id": spec.get("task_id", jobdir.name), "status": "queued",
                     "event_seq": 0, "outbox": [], "nudges": 0, "retries": 0,
                     "attempts": [], "owned_agents": [], "report": str(jobdir / "report.md")}
        state.update(status="running", started=time.time(), maintenance=None)
        atomic_json(state_path, state)
    attempt_root = jobdir / "attempts"
    attempt_root.mkdir(exist_ok=True)
    backoff_index = 0
    while True:
        attempt = attempt_root / f"attempt-{len(state['attempts']) + 1:03d}"
        attempt.mkdir()
        out_path, err_path = attempt / "stdout.txt", attempt / "stderr.txt"
        command = "resume" if (jobdir / "job.json").exists() else "run"
        cmd = [sys.executable, str(driver_path), command,
               str(jobdir) if command == "resume" else str(spec_path)]
        if command == "run":
            cmd.append(str(jobdir))
        started = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=MAX_ACTIVE_SECONDS)
            out_path.write_text(proc.stdout, encoding="utf-8")
            err_path.write_text(proc.stderr, encoding="utf-8")
            rc = proc.returncode
        except subprocess.TimeoutExpired as exc:
            out_path.write_text((exc.stdout or "") if isinstance(exc.stdout, str) else "",
                                encoding="utf-8")
            err_path.write_text("supervised child timed out", encoding="utf-8")
            rc = 124
        state["attempts"].append({"path": str(attempt), "rc": rc,
                                  "duration": time.monotonic() - started})
        state["retries"] += 1
        state["status"] = "running"
        with locked(jobdir / "job.lock"):
            atomic_json(state_path, state)
        if rc == 0:
            event = save_terminal(jobdir, state, "landed", "ready-for-human-gate")
            print(json.dumps(event))
            return 0
        # Legacy job.json provides typed pause/escalation; don't turn arbitrary
        # failures into repeated worker turns.
        try:
            job = read_json(jobdir / "job.json")
        except QueueError:
            job = {}
        reason = str(job.get("reason") or "supervised child failed")
        if rc == 2:
            event = save_terminal(jobdir, state, "parked", reason)
            print(json.dumps(event))
            return 2
        if "DAEMON_NOT_RUNNING" in reason or "cannot launch paseo" in reason.lower():
            if state["retries"] >= MAX_JOB_RETRIES or backoff_index >= len(BACKOFF_SECONDS):
                event = save_terminal(jobdir, state, "parked", reason)
                print(json.dumps(event))
                return 2
            delay = BACKOFF_SECONDS[backoff_index]
            backoff_index += 1
            state["retry_at"] = time.time() + delay
            with locked(jobdir / "job.lock"):
                atomic_json(state_path, state)
            time.sleep(delay)
            # Queue-owned resumes, rather than resubmitting a run that may have
            # created workers, require a reconciled live inventory. Fail closed
            # when no durable owned IDs can be proven.
            state["status"] = "parked"
            message = reason + "; daemon recovery requires reconciliation"
            event = save_terminal(jobdir, state, "parked", message)
            print(json.dumps(event))
            return 2
        event = save_terminal(jobdir, state, "parked", reason)
        print(json.dumps(event))
        return 2


def cli(argv, driver_path):
    if not argv:
        return None
    if argv[0] == "supervise":
        if len(argv) != 3:
            print("usage: agentcoder.py supervise SPEC.json JOBDIR")
            return 1
        try:
            return supervise(argv[1], argv[2], driver_path)
        except (QueueError, OSError) as exc:
            print(json.dumps({"status": "parked", "reason": str(exc)}))
            return 2
    if argv[:2] == ["queue", "wait"]:
        import argparse
        parser = argparse.ArgumentParser(prog="agentcoder.py queue wait")
        parser.add_argument("qdir")
        parser.add_argument("task_id", nargs="?")
        parser.add_argument("--after", required=True)
        parser.add_argument("--timeout", type=float)
        try:
            args = parser.parse_args(argv[2:])
            event, code = wait_for_event(args.qdir, args.task_id, args.after, args.timeout)
            print(json.dumps(event, sort_keys=True), flush=True)
            return code
        except (QueueError, OSError) as exc:
            print(json.dumps({"status": "error", "reason": str(exc)}), flush=True)
            return 1
    return None
