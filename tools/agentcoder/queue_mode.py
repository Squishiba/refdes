"""Opt-in, single-job AgentCoder supervision primitives.

This module intentionally does not change the legacy run/resume path. Queue
state is cooperative same-user state, not a security boundary.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows imports the driver and uses msvcrt below.
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

POLL_SECONDS = 5
BACKOFF_SECONDS = (15, 30, 60, 120, 300)
MAX_INCIDENT_RETRIES = 5
MAX_JOB_RETRIES = 10
MAX_NUDGES = 2
MAX_PERMISSION_PROMPTS = 100
MAX_PERMISSION_CHAIN_SECONDS = 900
MAX_ACTIVE_SECONDS = 14400
TRANSIENT_GRACE_SECONDS = 120
LOOP_WINDOW_SECONDS = 600
DENIAL = ("Queue policy denied this request: {reason}. Use only scoped relative paths and "
          "approved commands in your worktree; do not retry the denied operation.")
REFERENCE_RISKY = re.compile(
    r"\b(?:delete|remove|unlink|git push|push (?:to|the branch)|"
    r"(?<!direction )merge(?! diffs?)|force|sudo|chmod|chown|curl|wget|ssh|"
    r"install|reset|checkout\s+main|kill|systemctl)\b|\brm\s|"
    r"\bbranch\s+-D\b|"
    r"/tmp|~/|\.paseo|\.ssh|\.config|/etc/|"
    r"/home/jorb/work/(paseo-pr-review-plugin|refdes)(?!-dev)\b", re.I)
REFERENCE_SAFE = re.compile(
    r"\.scratch|\bscratch probes?\b|\bindependent [a-z ]*probes?\b|"
    r"(re)?runn?ing[a-z ,-]* probes?|requested foreground checks|existing probes|"
    r"isolated fixture|(edit|write|update|fix)[a-z ]* the report|"
    r"untracked REVIEW-[A-Z]+\.md|untracked probes|read-only probes|own worktree|"
    r"review artifacts|foreground (tests|test)", re.I)

CAPTURED_STATUSES = {"running", "idle", "closed", "permission"}
CAPTURED_AGENT_FIELDS = {"id", "shortId", "name", "provider", "thinking", "status",
                         "cwd", "created"}
CAPTURED_WORKSPACE_FIELDS = {"workspaceId", "project", "name", "isolation", "cwd"}
TERMINAL = {"landed", "parked", "failed"}


class QueueError(Exception):
    pass


def _fsync_dir(path):
    # Windows does not support opening directories through os.open. Directory
    # fsync is also unavailable on some POSIX filesystems, so keep it best effort.
    if sys.platform == "win32":
        return
    fd = None
    try:
        fd = os.open(str(path), os.O_RDONLY)
        os.fsync(fd)
    except OSError:
        return
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


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
        backend = _lock_backend()
        if backend == "posix":
            if fcntl is None:
                raise QueueError("queue state locking is unavailable on this platform")
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return
        if msvcrt is None:
            raise QueueError("queue state locking requires the Windows msvcrt backend")
        stream.seek(0)
        if not stream.read(1):
            stream.seek(0)
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        while True:
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                break
            except OSError:
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _lock_backend():
    return "windows" if os.name == "nt" else "posix"


def read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        raise QueueError(f"corrupt or unreadable state {path}: {exc}") from exc


def load_state(jobdir):
    """Load queue state after checking its durable schema.

    `owned_agents` is always an object keyed by full agent ID; operations and
    maintenance agent records are also objects, while attempts and outbox are
    arrays. Missing collections are accepted for older opt-in state files.
    """
    jobdir = Path(jobdir)
    state = read_json(jobdir / "state.json")
    if not isinstance(state, dict):
        raise QueueError("invalid queue state schema: root must be an object")
    for key in ("owned_agents", "operations", "replacements"):
        if key in state and not isinstance(state[key], dict):
            raise QueueError(f"invalid queue state schema: {key} must be an object keyed by ID")
    for key in ("attempts", "outbox", "permit_decisions", "hook_results"):
        if key in state and not isinstance(state[key], list):
            raise QueueError(f"invalid queue state schema: {key} must be an array")
    if "maintenance" in state and state["maintenance"] is not None \
            and not isinstance(state["maintenance"], dict):
        raise QueueError("invalid queue state schema: maintenance must be an object or null")
    if isinstance(state.get("maintenance"), dict) \
            and "agents" in state["maintenance"] \
            and not isinstance(state["maintenance"]["agents"], dict):
        raise QueueError("invalid queue state schema: maintenance.agents must be an object keyed by ID")
    if "permission_prompts" in state and (isinstance(state["permission_prompts"], bool)
            or not isinstance(state["permission_prompts"], int)
            or state["permission_prompts"] < 0):
        raise QueueError("invalid queue state schema: permission_prompts must be a non-negative integer")
    if "permission_started_at" in state and state["permission_started_at"] is not None \
            and (isinstance(state["permission_started_at"], bool)
                 or not isinstance(state["permission_started_at"], (int, float))):
        raise QueueError("invalid queue state schema: permission_started_at must be a number or null")
    return state


def _event(state, kind, outcome):
    seq = int(state.get("event_seq", 0)) + 1
    event_id = f"{state['task_id']}:{seq}"
    event = {"event_id": event_id, "task_id": state["task_id"],
             "kind": kind, "status": state["status"], "outcome": outcome,
             "report": state.get("report"),
             "counts": {state["status"]: 1}, "created": time.time()}
    state["event_seq"] = seq
    state.setdefault("outbox", []).append(event)
    return event


def save_terminal(jobdir, state, status, outcome):
    """Commit terminal status and its numbered event in one locked replacement."""
    jobdir = Path(jobdir)
    with locked(jobdir / "job.lock"):
        current = read_json(jobdir / "state.json") if (jobdir / "state.json").exists() else state
        if current.get("status") in ("landed", "parked", "failed"):
            events = current.get("outbox", [])
            if events:
                return events[-1]
            current["status"] = "paused"  # repair an interrupted terminal commit
        current.update(status=status, outcome=outcome, updated=time.time())
        event = _event(current, "terminal", outcome)
        atomic_json(jobdir / "state.json", current)
    notify_terminal(jobdir, event)
    return event


def notify_terminal(jobdir, event, invoke=None):
    """Best-effort trusted argv hook; durable event is committed before attempts."""
    jobdir = Path(jobdir)
    state = load_state(jobdir)
    command = state.get("notification_command")
    if command is None:
        return
    if not isinstance(command, list) or not command or not all(
            isinstance(arg, str) and arg for arg in command):
        result = {"event_id": event["event_id"], "status": "invalid-command"}
        with locked(jobdir / "job.lock"):
            current = load_state(jobdir)
            current.setdefault("hook_results", []).append(result)
            atomic_json(jobdir / "state.json", current)
        return
    if invoke is None:
        def invoke(argv):
            return subprocess.run(argv, input=json.dumps(event), capture_output=True, text=True,
                                  cwd=jobdir, env={"PATH": os.environ.get("PATH", ""),
                                                   "LANG": "C.UTF-8"}, timeout=10)
    attempts = []
    for number in range(2):
        try:
            proc = invoke(command)
            attempts.append({"attempt": number + 1, "rc": proc.returncode,
                             "evidence": bounded_raw(proc.stdout + proc.stderr, 1000)})
            if proc.returncode == 0:
                break
        except (OSError, subprocess.TimeoutExpired) as exc:
            attempts.append({"attempt": number + 1, "error": str(exc)[:500]})
    result = {"event_id": event["event_id"], "attempts": attempts,
              "status": "delivered" if attempts and attempts[-1].get("rc") == 0 else "failed"}
    with locked(jobdir / "job.lock"):
        current = load_state(jobdir)
        current.setdefault("hook_results", []).append(result)
        atomic_json(jobdir / "state.json", current)


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


def verified_job_completion(job):
    """Require the driver's saved executor gate, never child prose/exit alone."""
    if not isinstance(job, dict) or job.get("phase") != "done" \
            or job.get("status") != "ready-for-human-gate":
        return False
    if not all(job.get(k) for k in ("base_sha", "test_sha", "coder_sha")):
        return False
    if not isinstance(job.get("controls"), int) or not isinstance(job.get("intended_reds"), int):
        return False
    results = job.get("candidate_results")
    return isinstance(results, list) and any(
        isinstance(row, dict) and row.get("rc") == 0 and row.get("failed") == []
        for row in results)


def bounded_recovery(state, signal, now):
    """Pure bounded recovery policy; returned state can be persisted verbatim."""
    state = json.loads(json.dumps(state))
    kind = signal.get("kind") if isinstance(signal, dict) else None
    evidence = bounded_raw(signal)
    if not isinstance(signal, dict) or not kind:
        state.update(status="parked", parked_reason="unknown recovery signal: " + evidence,
                     retry_at=None)
        return state, "park", state["parked_reason"]

    def park(reason):
        state.update(status="parked", parked_reason=reason, retry_at=None)
        return state, "park", reason

    if kind == "maintenance_stop":
        state["status"] = "paused"
        state.setdefault("maintenance", {"intent": "stop", "requested_at": now})
        return state, "maintenance", "deliberate maintenance stop"
    if kind == "uncertain_send":
        return park("send acceptance is uncertain; refusing duplicate delivery")
    if kind == "daemon_unreachable":
        attempt, total = int(state.get("incident_retries", 0)), int(state.get("retries", 0))
        if attempt >= MAX_INCIDENT_RETRIES or total >= MAX_JOB_RETRIES:
            return park("daemon retry budget exhausted: " + evidence)
        delay = BACKOFF_SECONDS[attempt]
        state.update(status="paused", incident_retries=attempt + 1, retries=total + 1,
                     retry_at=now + delay, recovery_kind=kind, recovery_evidence=evidence)
        return state, "backoff", f"daemon unreachable; retry in {delay}s"
    if kind == "transient_error":
        first = state.setdefault("transient_error_since", now)
        if signal.get("recovered") is True:
            state.pop("transient_error_since", None)
            state["status"] = "running"
            return state, "adopt", "transient error recovered without nudge"
        if now - first < TRANSIENT_GRACE_SECONDS:
            state.update(status="paused", retry_at=first + TRANSIENT_GRACE_SECONDS)
            return state, "observe", "observing transient error; no send before 120s"
        if signal.get("verified_signature") is not True:
            return park("unverified transient-error signature: " + evidence)
        role = signal.get("role")
        if role not in {"coder", "designer", "reviewer"}:
            return park("persistent error has no verified role identity")
        replacements = state.setdefault("replacements", {})
        if replacements.get(role, 0) >= 1:
            return park("persistent error after the one allowed replacement")
        replacements[role] = replacements.get(role, 0) + 1
        state.update(status="paused", retry_at=now, recovery_kind=kind)
        return state, "replace_same_workspace", "persistent verified error; retain workspace"
    if kind in {"idle", "turn_limit", "loop", "garbled_finish"}:
        if kind == "loop":
            since = state.setdefault("loop_signature_since", now)
            if signal.get("signature_changed") is True or signal.get("artifact_progress") is True:
                state.pop("loop_signature_since", None)
                state["status"] = "running"
                return state, "adopt", "artifact progress resets loop observation"
            if now - since < LOOP_WINDOW_SECONDS:
                state.update(status="paused", retry_at=since + LOOP_WINDOW_SECONDS)
                return state, "observe", "loop signature unchanged; observe to 600s"
            windows = int(state.get("no_progress_windows", 0)) + 1
            state["no_progress_windows"] = windows
            if windows > 1:
                return park("two no-progress windows with the same failure signature")
        if kind == "garbled_finish" and signal.get("operation_reconciled") is not True:
            return park("garbled completion with unreconciled operation identity: " + evidence)
        if kind == "garbled_finish" and state.get("verdict_repair_used"):
            return park("review verdict remained malformed after one repair")
        if kind == "garbled_finish":
            state["verdict_repair_used"] = True
        used, maximum = int(state.get("nudges", 0)), state.get("max_nudges", MAX_NUDGES)
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
            return park("invalid persisted nudge budget")
        if used >= min(maximum, MAX_NUDGES):
            return park("shared nudge budget exhausted: " + evidence)
        state.update(status="paused", nudges=used + 1, retry_at=now, recovery_kind=kind,
                     recovery_evidence=evidence)
        return state, "continue_same_workspace", f"bounded {kind} continuation"
    return park("unrecognized recovery kind: " + evidence)


def wall_elapsed(state, now):
    elapsed = float(state.get("active_seconds", 0))
    started = state.get("active_started_at")
    if started is not None:
        elapsed += max(0, now - float(started))
    return elapsed


def start_active_clock(state, now):
    if state.get("active_started_at") is None:
        state["active_started_at"] = now
    return state


def stop_active_clock(state, now):
    state["active_seconds"] = wall_elapsed(state, now)
    state["active_started_at"] = None
    return state


def pause_active_for_backoff(state, now):
    """Do not charge a deliberate daemon-recovery sleep to the active budget."""
    return stop_active_clock(state, now)


def _queue_limits(spec):
    policy = spec.get("queue", {})
    if not isinstance(policy, dict):
        raise QueueError("queue must be a JSON object")
    max_nudges = policy.get("max_nudges", MAX_NUDGES)
    wall_timeout = policy.get("job_wall_timeout", MAX_ACTIVE_SECONDS)
    trusted = policy.get("trusted_agents", [])
    if not isinstance(trusted, list) or any(not isinstance(agent_id, str) or not agent_id
                                            for agent_id in trusted) \
            or len(set(trusted)) != len(trusted):
        raise QueueError("queue.trusted_agents must be a list of unique exact full agent IDs")
    trust_owned = policy.get("trust_owned_agents", False)
    if not isinstance(trust_owned, bool):
        raise QueueError("queue.trust_owned_agents must be a JSON boolean")
    if isinstance(max_nudges, bool) or not isinstance(max_nudges, int) or not 0 <= max_nudges <= 10:
        raise QueueError("queue.max_nudges must be an integer from 0 through 10")
    if isinstance(wall_timeout, bool) or not isinstance(wall_timeout, int) or wall_timeout < 1:
        raise QueueError("queue.job_wall_timeout must be a positive integer")
    return max_nudges, wall_timeout


def reconcile_owned_agents(owned_ids, listing):
    """Adopt exact captured full IDs; unknown rows never authorize a relaunch."""
    if not isinstance(listing, list):
        return {}, {str(a): "listing is not an array" for a in owned_ids}
    rows, malformed = {}, []
    for row in listing:
        if not isinstance(row, dict) or not all(
                isinstance(row.get(k), str) and row[k] for k in CAPTURED_AGENT_FIELDS) \
                or set(row) != CAPTURED_AGENT_FIELDS:
            malformed.append(bounded_raw(row, 1000))
            continue
        if row["id"] in rows:
            malformed.append("duplicate id " + row["id"])
        rows[row["id"]] = row
    result, uncertain = {}, {}
    for agent_id in owned_ids:
        row = rows.get(agent_id)
        if row is None:
            uncertain[agent_id] = "owned full ID absent from fresh listing; do not relaunch"
        elif row["shortId"] != agent_id[:7]:
            uncertain[agent_id] = "listing shortId does not match captured full-ID mapping"
        elif row["status"] in {"running", "permission"}:
            result[agent_id] = "active"
        elif row["status"] == "idle":
            result[agent_id] = "idle"
        elif row["status"] == "closed":
            result[agent_id] = "closed"
        else:
            uncertain[agent_id] = "unverified listing status " + repr(row["status"])
    if malformed:
        uncertain["_listing"] = "malformed rows: " + bounded_raw(malformed, 3000)
    return result, uncertain


def classify_agent_response(payload, expected_agent_id=None, fields=None,
                            required_nonempty=()):
    """Classify a captured blocking Paseo response using one status vocabulary."""
    if not isinstance(payload, dict) or (fields is not None and set(payload) != fields):
        return "unknown", "unverified Paseo response shape: " + bounded_raw(payload)
    if not all(isinstance(value, str) for value in payload.values()):
        return "unknown", "Paseo response fields must be text: " + bounded_raw(payload)
    if any(not payload.get(key) for key in required_nonempty):
        return "unknown", "Paseo response has an empty required field: " + bounded_raw(payload)
    if expected_agent_id is not None and payload.get("agentId") != expected_agent_id:
        return "unknown", "Paseo response agentId does not match exact owned ID: " \
            + bounded_raw(payload)
    status = payload.get("status")
    if status not in {"completed", "idle", "permission", "running"}:
        return "unknown", "unrecognized Paseo response status: " + bounded_raw(payload)
    return status, "captured Paseo " + status + " response"


def validate_wait_result(payload, expected_agent_id):
    """Accept captured in-flight and idle wait envelopes for the exact full ID."""
    status, reason = classify_agent_response(
        payload, expected_agent_id, {"agentId", "status", "message"}, {"agentId"})
    if status in {"idle", "permission", "running"}:
        return True, reason
    return False, reason


def permission_limits(spec):
    policy = spec.get("queue", {})
    if not isinstance(policy, dict):
        raise QueueError("queue must be a JSON object")
    maximum = policy.get("max_permission_prompts", MAX_PERMISSION_PROMPTS)
    seconds = policy.get("permission_no_progress_seconds", MAX_PERMISSION_CHAIN_SECONDS)
    if isinstance(maximum, bool) or not isinstance(maximum, int) \
            or not 1 <= maximum <= 1000:
        raise QueueError("queue.max_permission_prompts must be an integer from 1 through 1000")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 86400:
        raise QueueError("queue.permission_no_progress_seconds must be an integer from 1 through 86400")
    return maximum, seconds


def note_permission_prompt(state, maximum=MAX_PERMISSION_PROMPTS,
                           no_progress_seconds=MAX_PERMISSION_CHAIN_SECONDS, now=None):
    """Record one permission wait without consuming the stall/nudge budget."""
    now = time.time() if now is None else now
    count = int(state.get("permission_prompts", 0)) + 1
    started = state.get("permission_started_at")
    if started is None:
        started = now
    state.update(permission_prompts=count, permission_started_at=started)
    if count > maximum:
        raise QueueError(f"permission prompt budget exhausted ({maximum} per job)")
    if now - float(started) >= no_progress_seconds:
        raise QueueError("permission sequence exceeded its no-progress timer")
    return count


def record_permission_prompt(jobdir, maximum, no_progress_seconds):
    with locked(Path(jobdir) / "job.lock"):
        state = load_state(jobdir)
        try:
            count = note_permission_prompt(state, maximum, no_progress_seconds)
        except QueueError:
            atomic_json(Path(jobdir) / "state.json", state)
            raise
        atomic_json(Path(jobdir) / "state.json", state)
        return count


def clear_permission_wait(jobdir):
    with locked(Path(jobdir) / "job.lock"):
        state = load_state(jobdir)
        state["permission_started_at"] = None
        atomic_json(Path(jobdir) / "state.json", state)


def validate_run_result(payload, expected_agent_id=None):
    fields = {"agentId", "status", "provider", "cwd", "title"}
    status, reason = classify_agent_response(payload, expected_agent_id, fields, fields)
    if status in {"completed", "running", "permission"}:
        return True, reason
    return False, reason


def validate_send_result(payload, expected_agent_id):
    status, reason = classify_agent_response(
        payload, expected_agent_id, {"agentId", "status", "message"}, {"agentId"})
    if status in {"completed", "running", "permission"}:
        return True, reason
    return False, reason


def validate_stop_result(payload, requested_agent_id):
    fields = {"stoppedCount", "agentIds"}
    if not isinstance(payload, dict) or set(payload) != fields:
        return False, "unverified paseo stop payload shape: " + bounded_raw(payload)
    ids = payload.get("agentIds")
    count = payload.get("stoppedCount")
    if not isinstance(count, int) or count < 0 or not isinstance(ids, list) \
            or any(not isinstance(agent_id, str) for agent_id in ids) \
            or count != len(ids) or any(agent_id != requested_agent_id for agent_id in ids):
        return False, "paseo stop result does not match exact requested ID: " + bounded_raw(payload)
    return True, "captured stop response"


def classify_permit_record(row):
    """Reference deny/risky semantics; prose alone can never prove ALLOW."""
    digest = hashlib.sha256(bounded_raw(row, 65536).encode()).hexdigest()
    if not isinstance(row, dict):
        return "UNKNOWN", "permit is not an object", digest
    required = ("agentShortId", "agentId", "id", "name")
    captured = set(required) | {"description"}
    if any(not isinstance(row.get(k), str) or not row[k] for k in required) \
            or not isinstance(row.get("description"), str):
        return "UNKNOWN", "permit schema is incomplete", digest
    if set(row) != captured:
        return "UNKNOWN", "permit has uncaptured fields", digest
    name, description = row["name"], row["description"]
    outside = re.search(r"/tmp|~/|\.\./|/(?:etc|home|root|var|usr)/|"
                        r"\boutside (?:(?:the|this|my) )?(?:worktree|workspace|repo|project)\b",
                        description, re.I)
    if "external_directory" in name.lower() or outside:
        return "DENY", "request targets an outside directory", digest
    if REFERENCE_RISKY.search(name + "\n" + description):
        return "DENY", "request matches the risky-operation policy", digest
    if not description.strip() or description.strip() == "-":
        return "UNKNOWN", "permit description contains no evidence", digest
    if REFERENCE_SAFE.search(description):
        return "UNKNOWN", "safe-scope prose lacks structured tool input and cwd", digest
    return "UNKNOWN", "request effect cannot be proven from name and description", digest


def record_decision(jobdir, record):
    with locked(Path(jobdir) / "job.lock"):
        state = load_state(jobdir)
        state.setdefault("permit_decisions", []).append(record)
        atomic_json(Path(jobdir) / "state.json", state)


def note_agent(jobdir, agent_id, role):
    with locked(Path(jobdir) / "job.lock"):
        state = load_state(jobdir)
        rows = state.setdefault("owned_agents", {})
        rows[agent_id] = {"role": role, "status": "recorded"}
        atomic_json(Path(jobdir) / "state.json", state)


def begin_operation(jobdir, kind, role, details):
    jobdir = Path(jobdir)
    digest = hashlib.sha256(bounded_raw(details, 65536).encode()).hexdigest()
    with locked(jobdir / "job.lock"):
        state = load_state(jobdir)
        operations = state.setdefault("operations", {})
        for operation in operations.values():
            if operation.get("kind") == kind and operation.get("role") == role \
                    and operation.get("status") in {"intent", "uncertain"}:
                raise QueueError(f"unresolved {kind} operation for {role}; refusing replay")
        op_id = uuid.uuid4().hex
        operations[op_id] = {"operation_id": op_id, "kind": kind, "role": role,
                             "request_hash": digest, "details": bounded_raw(details),
                             "status": "intent", "created": time.time()}
        atomic_json(jobdir / "state.json", state)
    return op_id


def finish_operation(jobdir, op_id, status, evidence, agent_id=None):
    with locked(Path(jobdir) / "job.lock"):
        state = load_state(jobdir)
        operation = state.setdefault("operations", {}).get(op_id)
        if operation is None:
            raise QueueError(f"operation {op_id} disappeared from durable state")
        operation.update(status=status, evidence=bounded_raw(evidence), finished=time.time())
        if agent_id:
            operation["agent_id"] = agent_id
        atomic_json(Path(jobdir) / "state.json", state)


def unresolved_operations(state):
    return [op for op in state.get("operations", {}).values()
            if op.get("status") in {"intent", "uncertain"}]


def _listing_from_cli():
    executable = os.environ.get("AGENTCODER_PASEO", "paseo")
    try:
        proc = subprocess.run([executable, "ls", "-g", "--json"], capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"global listing failed: {exc}"
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        return None, f"global listing is not JSON: {exc}; raw={bounded_raw(proc.stdout)}"
    if proc.returncode or not isinstance(data, list):
        return None, f"global listing unavailable: rc={proc.returncode}; raw={bounded_raw(data)}"
    return data, None


def _job_agent_ids(job):
    ids = {job.get(k) for k in ("coder_agent", "designer_agent", "reviewer_agent")}
    ids.update((job.get("reviewers") or {}).values())
    return sorted(i for i in ids if isinstance(i, str) and i)


def _durable_agent_ids(jobdir, job):
    return sorted(set(_job_agent_ids(job)) | set(load_state(jobdir).get("owned_agents", {})))


def reconcile_job_agents(jobdir, listing=None):
    """Recover recorded role IDs from the legacy job record and fresh inventory."""
    jobdir = Path(jobdir)
    job = read_json(jobdir / "job.json")
    owned = _durable_agent_ids(jobdir, job)
    if listing is None:
        listing, error = _listing_from_cli()
        if error:
            return {}, {"_listing": error}
    adopted, uncertain = reconcile_owned_agents(owned, listing)
    with locked(jobdir / "job.lock"):
        state = load_state(jobdir)
        state["owned_agents"] = {aid: {"role": next(
            (r for r in ("coder", "designer", "reviewer")
             if job.get(f"{r}_agent") == aid), "reviewer"),
            "status": adopted.get(aid, "unknown")} for aid in owned}
        state["reconciliation"] = {"adopted": adopted, "uncertain": uncertain,
                                    "observed_at": time.time()}
        for op_id, operation in state.get("operations", {}).items():
            if operation.get("kind") == "run" and operation.get("status") == "intent":
                role = operation.get("role")
                agent_id = job.get(f"{role}_agent") if role else None
                if isinstance(agent_id, str) and agent_id in adopted:
                    operation.update(status="adopted", agent_id=agent_id,
                                     evidence="reconciled from exact saved job.json agent ID")
                    uncertain.pop(agent_id, None)
        state["reconciliation"]["uncertain"] = uncertain
        atomic_json(jobdir / "state.json", state)
    return adopted, uncertain


def process_permits(jobdir, owned_ids, listing, rows, invoke=None, trusted_agent_ids=(),
                    trust_owned_agents=False):
    """Process only exact owned short IDs; unknown/risky evidence parks the job."""
    if not isinstance(rows, list):
        reason = "permit listing is not the captured array shape: " + bounded_raw(rows)
        record_decision(jobdir, {"decision": "UNKNOWN", "reason": reason,
                                "raw": bounded_raw(rows)})
        return "PARK", reason
    if invoke is None:
        def invoke(argv):
            executable = os.environ.get("AGENTCODER_PASEO", "paseo")
            return subprocess.run([executable] + argv, capture_output=True, text=True, timeout=60)
    identity = {}
    if isinstance(listing, list):
        for row in listing:
            if not isinstance(row, dict) or set(row) != CAPTURED_AGENT_FIELDS or any(
                    not isinstance(row.get(k), str) or not row[k]
                    for k in CAPTURED_AGENT_FIELDS) or row.get("status") not in CAPTURED_STATUSES:
                reason = "global listing contains an uncaptured row/status: " + bounded_raw(row)
                record_decision(jobdir, {"decision": "UNKNOWN", "reason": reason,
                                         "raw": bounded_raw(row)})
                return "PARK", reason
            identity.setdefault(row["shortId"], []).append(row["id"])
    else:
        reason = "global listing is not the captured array shape: " + bounded_raw(listing)
        record_decision(jobdir, {"decision": "UNKNOWN", "reason": reason,
                                 "raw": bounded_raw(listing)})
        return "PARK", reason
    owned_ids = set(owned_ids)
    for row in rows:
        if not isinstance(row, dict):
            record_decision(jobdir, {"decision": "UNKNOWN", "reason": "malformed permit row",
                                    "raw": bounded_raw(row)})
            return "PARK", "malformed permit row"
        short = row.get("agentShortId")
        request_id = row.get("id")
        full_from_record = row.get("agentId")
        if not isinstance(short, str) or not short or not isinstance(request_id, str) \
                or not request_id or not isinstance(full_from_record, str) or not full_from_record:
            reason = "permit lacks exact agentShortId or request id; attribution unknown"
            record_decision(jobdir, {"decision": "UNKNOWN", "reason": reason,
                                    "raw": bounded_raw(row)})
            return "PARK", reason
        matches = identity.get(short, [])
        if not matches:
            reason = "permit agentShortId is absent from fresh listing; attribution unknown"
            record_decision(jobdir, {"decision": "UNKNOWN", "reason": reason,
                                    "raw": bounded_raw(row)})
            return "PARK", reason
        if len(matches) > 1:
            reason = "permit agentShortId maps to multiple full IDs; attribution ambiguous"
            record_decision(jobdir, {"decision": "UNKNOWN", "reason": reason,
                                    "raw": bounded_raw(row)})
            return "PARK", reason
        if matches[0] != full_from_record:
            reason = "permit full agentId disagrees with exact shortId mapping"
            record_decision(jobdir, {"decision": "UNKNOWN", "reason": reason,
                                    "raw": bounded_raw(row)})
            return "PARK", reason
        if matches[0] not in owned_ids:
            continue  # foreign request: do not allow, deny, or rewrite it
        decision, reason, digest = classify_permit_record(row)
        # The exact captured shortId maps to one full ID; prefix matching is
        # deliberately forbidden. Ambiguous/foreign rows are never touched.
        full_id = matches[0]
        trusted = full_id in set(trusted_agent_ids) or (
            trust_owned_agents is True and full_id in owned_ids)
        unverified_schema = decision == "UNKNOWN" and (
                set(row) != {"agentShortId", "agentId", "id", "name", "description"}
                or reason in {"permit schema is incomplete", "permit has uncaptured fields"})
        if unverified_schema:
            record_decision(jobdir, {"agent_id": full_id, "agent_short_id": short,
                                     "request_id": request_id, "decision": "UNKNOWN",
                                     "reason": reason, "request_hash": digest,
                                     "raw": bounded_raw(row)})
            return "PARK", f"owned permit {request_id} has unverified schema; evidence retained"
        action = "allow" if decision == "UNKNOWN" and trusted else "deny"
        if action == "allow":
            reason = "operator-listed cooperative trusted agent; " + reason
            decision = "ALLOW"
        record = {"agent_id": full_id, "agent_short_id": short, "request_id": request_id,
                  "decision": decision, "reason": reason, "request_hash": digest,
                  "raw": bounded_raw(row)}
        record_decision(jobdir, record)  # durable before any external side effect
        if decision == "UNKNOWN" and not trusted:
            return "PARK", f"owned permit {request_id} is unclassifiable; evidence retained: {reason}"
        deny_message = DENIAL.format(reason=reason)
        stale = False
        remains = True
        result = None
        try:
            argv = ["permit", action, full_id, request_id, "--json"]
            if action == "deny":
                argv[-1:-1] = ["--message", deny_message]
            result = invoke(argv)
            stale = False
            if result.returncode != 0:
                for stream in (result.stdout, result.stderr):
                    try:
                        error = json.loads(stream).get("error", {})
                    except (ValueError, AttributeError):
                        continue
                    if error.get("code") == "NO_PENDING_PERMISSIONS":
                        stale = True
                        break
            if result.returncode != 0 and not stale:
                record_decision(jobdir, {**record, "decision": "STOP_PENDING",
                                         "reason": f"{action} response failed; " + reason,
                                         "raw_response": bounded_raw(result.stdout + result.stderr)})
            reread = invoke(["permit", "ls", "--json"])
            try:
                pending = json.loads(reread.stdout) if reread.returncode == 0 else None
            except ValueError:
                pending = None
            remains = None
            if not isinstance(pending, list):
                record_decision(jobdir, {**record, "decision": "STOP_PENDING",
                                         "reason": "permit resolution could not be verified",
                                         "raw_response": bounded_raw(reread.stdout + reread.stderr)})
                remains = True
            else:
                remains = any(isinstance(p, dict) and p.get("agentShortId") == short
                              and p.get("id") == request_id for p in pending)
            if remains:
                record_decision(jobdir, {**record, "decision": "STOP_PENDING",
                                         "reason": f"exact permit remains pending after {action}",
                                         "raw_response": bounded_raw(reread.stdout)})
        except (OSError, subprocess.TimeoutExpired) as exc:
            record_decision(jobdir, {**record, "decision": "STOP_PENDING",
                                     "reason": f"permit {action} outcome uncertain: {exc}"})
            return "PARK", f"owned permit {request_id} resolution is uncertain: {exc}; evidence retained"
        if action == "deny" and stale and not remains:
            continue  # NO_PENDING_PERMISSIONS is a benign list/action race
        if action == "deny":
            return "PARK", f"owned permit {request_id} denied/parked: {reason}"
        if result.returncode != 0 and not stale:
            return "PARK", f"trusted permit allow failed; evidence retained: {reason}"
        if remains:
            return "PARK", f"trusted permit allow is unresolved: {reason}"
    return "CLEAR", "no exact owned pending permits"


def mark_stop_intent(jobdir, agent_ids, reason="maintenance"):
    jobdir = Path(jobdir)
    with locked(jobdir / "job.lock"):
        state = load_state(jobdir)
        now = time.time()
        stop_active_clock(state, now)
        state["maintenance"] = {"intent": reason, "requested": now,
                                "agents": {aid: "pending" for aid in agent_ids}}
        state["status"] = "paused"
        atomic_json(jobdir / "state.json", state)


def maintenance_stop(jobdir, invoke=None, listing_fn=None, reason="maintenance"):
    """Persist exact stop intents before stopping, then confirm via fresh listing."""
    jobdir = Path(jobdir)
    if invoke is None:
        def invoke(argv):
            executable = os.environ.get("AGENTCODER_PASEO", "paseo")
            return subprocess.run([executable] + argv, capture_output=True, text=True, timeout=60)
    if listing_fn is None:
        listing_fn = _listing_from_cli
    job_path = jobdir / "job.json"
    job = read_json(job_path) if job_path.exists() else {}
    ids = _durable_agent_ids(jobdir, job)
    mark_stop_intent(jobdir, ids, reason)
    before, error = listing_fn()
    if error:
        with locked(jobdir / "job.lock"):
            state = load_state(jobdir)
            state["stop_pending"] = True
            state["maintenance"]["evidence"] = error
            atomic_json(jobdir / "state.json", state)
        return "STOP_PENDING", error
    states, uncertain = reconcile_owned_agents(ids, before)
    for aid, status in states.items():
        if status in {"idle", "closed"}:
            continue
        if status != "active":
            uncertain[aid] = "unverified pre-stop status"
            continue
        try:
            result = invoke(["stop", aid, "--json"])
            try:
                payload = json.loads(result.stdout)
            except ValueError:
                payload = None
            valid, stop_reason = validate_stop_result(payload, aid)
            if result.returncode != 0 or not valid:
                uncertain[aid] = "stop command failed: " + bounded_raw(
                    {"reason": stop_reason, "stdout": result.stdout,
                     "stderr": result.stderr}, 1000)
        except (OSError, subprocess.TimeoutExpired) as exc:
            uncertain[aid] = f"stop outcome unknown: {exc}"
    after, after_error = listing_fn()
    confirmed = {}
    if after_error:
        uncertain["_listing"] = after_error
    else:
        confirmed, unresolved = reconcile_owned_agents(ids, after)
        for aid in ids:
            if confirmed.get(aid) in {"idle", "closed"}:
                uncertain.pop(aid, None)
            else:
                uncertain[aid] = unresolved.get(aid, "agent remains active or status unknown")
    with locked(jobdir / "job.lock"):
        state = load_state(jobdir)
        state["stop_pending"] = bool(uncertain)
        state["maintenance"]["agents"] = {
            aid: ("confirmed-inactive" if not uncertain.get(aid) and
                  (not after_error and confirmed.get(aid) in {"idle", "closed"}) else "pending")
            for aid in ids}
        state["maintenance"]["evidence"] = bounded_raw(uncertain) if uncertain else None
        atomic_json(jobdir / "state.json", state)
    return ("STOP_PENDING", bounded_raw(uncertain)) if uncertain else ("PAUSED", "all owned agents inactive")


def authorize_resume(jobdir, listing=None):
    """Explicitly authorize parked/maintenance work after fresh reconciliation."""
    jobdir = Path(jobdir)
    state = load_state(jobdir)
    if state.get("status") not in {"parked", "paused"}:
        return False, "job is not parked or paused"
    if state.get("outcome") == "acceptance checks complete; publication disabled for this job":
        return False, "publication after a completed no-publish run requires a new explicit job"
    job_path = jobdir / "job.json"
    if not job_path.exists():
        return False, "legacy job record is missing"
    job = read_json(job_path)
    ids = _durable_agent_ids(jobdir, job)
    if listing is None:
        listing, error = _listing_from_cli()
        if error:
            return False, "fresh daemon inventory required: " + error
    adopted, uncertain = reconcile_owned_agents(ids, listing)
    if uncertain:
        return False, "owned-agent reconciliation is uncertain: " + bounded_raw(uncertain)
    if state.get("stop_pending") or state.get("maintenance"):
        if any(status not in {"idle", "closed"} for status in adopted.values()):
            return False, "maintenance stop is not confirmed for every owned agent"
    with locked(jobdir / "job.lock"):
        current = load_state(jobdir)
        current.update(status="paused", explicit_resume=True, resumed_at=time.time(),
                       maintenance=None, stop_pending=False, parked_reason=None)
        start_active_clock(current, time.time())
        current["reconciliation"] = {"adopted": adopted, "uncertain": {},
                                      "observed_at": time.time()}
        atomic_json(jobdir / "state.json", current)
    return True, "resume authorized after fresh inventory"


def _parse_event(event):
    try:
        return int(event.get("event_id", "").rsplit(":", 1)[1])
    except (AttributeError, IndexError, ValueError) as exc:
        raise QueueError("corrupt terminal event ID") from exc


def wait_for_event(qdir, task_id=None, after="0", timeout=None):
    """Durable-state-first wait. One-second polling makes hints optional."""
    qdir = Path(qdir)
    cursor_task = None
    try:
        if not isinstance(after, str):
            raise ValueError
        if ":" in after:
            cursor_task, cursor_text = after.rsplit(":", 1)
            if not cursor_task:
                raise ValueError
        else:
            cursor_text = after
        cursor = int(cursor_text)
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
            state = load_state(path.parent)
            for event in state.get("outbox", []):
                if cursor_task is None:
                    is_after_cursor = _parse_event(event) > cursor
                elif event.get("task_id") == cursor_task:
                    is_after_cursor = _parse_event(event) > cursor
                else:
                    is_after_cursor = True
                if is_after_cursor and event.get("status") in ("landed", "parked", "failed"):
                    events.append(event)
        if events:
            event = min(events, key=_parse_event)
            event["batch_id"] = qdir.name
            return event, (0 if event["status"] == "landed" else 2)
        if timeout is not None and time.monotonic() - started >= timeout:
            return {"event_id": None, "batch_id": qdir.name, "task_id": task_id,
                    "status": "timeout", "outcome": None}, 124
        time.sleep(min(1, POLL_SECONDS))


def _supervise(spec_path, jobdir, driver_path, sleep_fn=None):
    """Run one legacy job as a child, retaining every invocation transcript.

    Recovery is deliberately conservative: daemon failures are backoff bounded;
    ambiguous child outcomes park. The child owns the existing acceptance gates.
    """
    spec_path, jobdir = Path(spec_path).resolve(), Path(jobdir).resolve()
    sleep_fn = sleep_fn or time.sleep
    spec = read_json(spec_path)
    max_nudges, wall_timeout = _queue_limits(spec)
    if "publish" in spec and not isinstance(spec["publish"], bool):
        raise QueueError("publish must be a JSON boolean")
    queue_config = spec.get("queue", {})
    hook = spec.get("notification_command")
    if hook is None and isinstance(queue_config, dict):
        hook = queue_config.get("notification_command")
    if hook is not None and (not isinstance(hook, list) or not hook or not all(
            isinstance(arg, str) and arg for arg in hook)):
        raise QueueError("notification_command must be a fixed non-empty argv list")
    jobdir.mkdir(parents=True, exist_ok=True)
    state_path = jobdir / "state.json"
    with locked(jobdir / "job.lock"):
        if state_path.exists():
            state = load_state(jobdir)
            if state.get("status") in ("landed", "parked", "failed"):
                return 0 if state["status"] == "landed" else 2
        else:
            spec = read_json(spec_path)
            state = {"task_id": spec.get("task_id", jobdir.name), "status": "queued",
                     "event_seq": 0, "outbox": [], "nudges": 0, "retries": 0,
                     "attempts": [], "owned_agents": {}, "report": str(jobdir / "report.md"),
                     "spec_path": str(spec_path), "notification_command": hook,
                     "max_nudges": max_nudges, "job_wall_timeout": wall_timeout,
                     "active_seconds": 0, "active_started_at": None}
        if not state.get("maintenance"):
            state.update(status="running", started=state.get("started", time.time()))
        state.setdefault("max_nudges", max_nudges)
        state.setdefault("job_wall_timeout", wall_timeout)
        state.setdefault("active_seconds", 0)
        state.setdefault("active_started_at", None)
        state.setdefault("spec_path", str(spec_path))
        state.setdefault("notification_command", hook)
        atomic_json(state_path, state)
    if state.get("maintenance"):
        print(json.dumps({"status": "paused", "reason": "maintenance intent remains set"}))
        return 1
    if (jobdir / "job.json").exists():
        old_state = load_state(jobdir)
        owned = _durable_agent_ids(jobdir, read_json(jobdir / "job.json"))
        listing, error = _listing_from_cli()
        while error:
            state, action, reason = bounded_recovery(
                old_state, {"kind": "daemon_unreachable", "evidence": error}, time.time())
            pause_active_for_backoff(state, time.time())
            with locked(jobdir / "job.lock"):
                atomic_json(state_path, state)
            if action == "park":
                event = save_terminal(jobdir, state, "parked", reason)
                print(json.dumps(event))
                return 2
            sleep_fn(max(0, state["retry_at"] - time.time()))
            old_state = state
            start_active_clock(old_state, time.time())
            listing, error = _listing_from_cli()
        if owned:
            adopted, uncertain = reconcile_job_agents(jobdir, listing)
            if uncertain:
                state = load_state(jobdir)
                state.update(status="parked", parked_reason="owned-agent reconciliation uncertain",
                             recovery_evidence=bounded_raw(uncertain))
                with locked(jobdir / "job.lock"):
                    atomic_json(state_path, state)
                event = save_terminal(jobdir, state, "parked", state["parked_reason"])
                print(json.dumps(event))
                return 2
    current_state = load_state(jobdir)
    state = current_state
    pending_ops = unresolved_operations(current_state)
    if pending_ops:
        evidence = bounded_raw(pending_ops, 4000)
        current_state.update(status="parked", parked_reason="unresolved external operation",
                             recovery_evidence=evidence)
        with locked(jobdir / "job.lock"):
            atomic_json(state_path, current_state)
        event = save_terminal(jobdir, current_state, "parked",
                              "unresolved external operation; refusing duplicate side effect")
        print(json.dumps(event))
        return 2


    attempt_root = jobdir / "attempts"
    attempt_root.mkdir(exist_ok=True)
    while True:
        now = time.time()
        if wall_elapsed(state, now) >= state.get("job_wall_timeout", wall_timeout):
            stop_status, stop_reason = maintenance_stop(jobdir, reason="wall-timeout")
            if stop_status == "STOP_PENDING":
                print(json.dumps({"status": "STOP_PENDING", "reason": stop_reason}))
                return 2
            state = load_state(jobdir)
            state["maintenance"] = None
            state["stop_pending"] = False
            state["status"] = "running"
            with locked(jobdir / "job.lock"):
                atomic_json(state_path, state)
            event = save_terminal(jobdir, state, "parked", "active job wall-time budget exhausted")
            print(json.dumps(event))
            return 2
        start_active_clock(state, now)
        with locked(jobdir / "job.lock"):
            atomic_json(state_path, state)
        attempt = attempt_root / f"attempt-{uuid.uuid4().hex}"
        attempt.mkdir()
        out_path, err_path = attempt / "stdout.txt", attempt / "stderr.txt"
        command = "resume" if (jobdir / "job.json").exists() else "run"
        cmd = [sys.executable, str(driver_path), command,
               str(jobdir) if command == "resume" else str(spec_path)]
        if command == "run":
            cmd.append(str(jobdir))
        started = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=MAX_ACTIVE_SECONDS,
                                  env=dict(os.environ, AGENTCODER_SUPERVISED="1"))
            out_path.write_text(proc.stdout, encoding="utf-8")
            err_path.write_text(proc.stderr, encoding="utf-8")
            rc = proc.returncode
        except subprocess.TimeoutExpired as exc:
            out_path.write_text((exc.stdout or "") if isinstance(exc.stdout, str) else "",
                                encoding="utf-8")
            err_path.write_text("supervised child timed out", encoding="utf-8")
            rc = 124
        except Exception:
            err_path.write_text(traceback.format_exc(), encoding="utf-8")
            rc = 70
        # The driver records newly spawned IDs write-ahead while this child is
        # running. Merge the attempt result into that latest durable snapshot.
        state = load_state(jobdir)
        state["attempts"].append({"path": str(attempt), "rc": rc,
                                  "duration": time.monotonic() - started})
        state["status"] = "running"
        with locked(jobdir / "job.lock"):
            atomic_json(state_path, state)
        if rc == 0:
            try:
                completed_job = read_json(jobdir / "job.json")
            except QueueError:
                completed_job = {}
            if not verified_job_completion(completed_job):
                event = save_terminal(jobdir, state, "parked",
                                      "child exit did not have a verified terminal job record")
                print(json.dumps(event))
                return 2
            if spec.get("publish") is True:
                terminal_status, outcome, code = "landed", "ready-for-human-gate", 0
            else:
                terminal_status, code = "parked", 2
                outcome = "acceptance checks complete; publication disabled for this job"
            stop_active_clock(state, time.time())
            with locked(jobdir / "job.lock"):
                atomic_json(state_path, state)
            event = save_terminal(jobdir, state, terminal_status, outcome)
            print(json.dumps(event))
            return code
        # Legacy job.json provides typed pause/escalation; don't turn arbitrary
        # failures into repeated worker turns.
        try:
            job = read_json(jobdir / "job.json")
        except QueueError:
            job = {}
        child_evidence = ""
        try:
            child_evidence = "\n".join((out_path.read_text(encoding="utf-8", errors="replace")
                                         + "\n" + err_path.read_text(
                                             encoding="utf-8", errors="replace")).splitlines()[-30:])
        except OSError:
            pass
        if rc == 70:
            reason = _short_traceback(err_path.read_text(encoding="utf-8", errors="replace"))
        else:
            reason = str(job.get("reason") or child_evidence or "supervised child failed")
        if rc == 2:
            stop_active_clock(state, time.time())
            with locked(jobdir / "job.lock"):
                atomic_json(state_path, state)
            event = save_terminal(jobdir, state, "parked", reason)
            print(json.dumps(event))
            return 2
        if "DAEMON_NOT_RUNNING" in reason or "cannot launch paseo" in reason.lower():
            if state.get("incident_retries", 0) >= MAX_INCIDENT_RETRIES \
                    or state.get("retries", 0) >= MAX_JOB_RETRIES:
                event = save_terminal(jobdir, state, "parked", reason)
                print(json.dumps(event))
                return 2
            state, action, reason = bounded_recovery(
                state, {"kind": "daemon_unreachable", "evidence": reason}, time.time())
            if action == "park":
                stop_active_clock(state, time.time())
                with locked(jobdir / "job.lock"):
                    atomic_json(state_path, state)
                event = save_terminal(jobdir, state, "parked", reason)
                print(json.dumps(event))
                return 2
            delay = state["retry_at"] - time.time()
            pause_active_for_backoff(state, time.time())
            with locked(jobdir / "job.lock"):
                atomic_json(state_path, state)
            sleep_fn(max(0, delay))
            start_active_clock(state, time.time())
            # Queue-owned resumes, rather than resubmitting a run that may have
            # created workers, require a reconciled live inventory. Fail closed
            # when no durable owned IDs can be proven.
            listing, error = _listing_from_cli()
            if error:
                state, action, message = bounded_recovery(
                    state, {"kind": "daemon_unreachable", "evidence": error}, time.time())
                pause_active_for_backoff(state, time.time())
                with locked(jobdir / "job.lock"):
                    atomic_json(state_path, state)
                if action == "park":
                    stop_active_clock(state, time.time())
                    with locked(jobdir / "job.lock"):
                        atomic_json(state_path, state)
                    event = save_terminal(jobdir, state, "parked", message)
                    print(json.dumps(event))
                    return 2
                sleep_fn(max(0, state["retry_at"] - time.time()))
                continue
            if (jobdir / "job.json").exists():
                adopted, uncertain = reconcile_job_agents(jobdir, listing)
                if uncertain:
                    message = "daemon recovered but owned-agent reconciliation is uncertain: " \
                        + bounded_raw(uncertain)
                    event = save_terminal(jobdir, state, "parked", message)
                    print(json.dumps(event))
                    return 2
            state["incident_retries"] = 0
            state["status"] = "running"
            with locked(jobdir / "job.lock"):
                atomic_json(state_path, state)
            continue
        event = save_terminal(jobdir, state, "parked", reason)
        print(json.dumps(event))
        return 2


def _short_traceback(text):
    """Return a compact class/message summary; full traceback stays in attempt."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        match = re.match(r"([A-Za-z_][\w.]*?(?:Error|Exception|Exit)):\s*(.*)", line)
        if match:
            message = re.sub(r"\s+", " ", match.group(2))[:140]
            return f"supervised worker exception ({match.group(1)}): {message}"
    return "supervised worker exited after an unclassified exception"


def _park_supervisor_exception(jobdir, exc, trace):
    """Persist an unexpected supervisor failure without exposing its traceback."""
    jobdir = Path(jobdir).resolve()
    jobdir.mkdir(parents=True, exist_ok=True)
    attempts = jobdir / "attempts"
    attempts.mkdir(exist_ok=True)
    attempt = attempts / f"attempt-{uuid.uuid4().hex}"
    attempt.mkdir()
    (attempt / "stdout.txt").write_text("", encoding="utf-8")
    (attempt / "stderr.txt").write_text(trace, encoding="utf-8")
    try:
        state = load_state(jobdir)
    except QueueError:
        try:
            state = read_json(jobdir / "state.json")
        except QueueError:
            state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("task_id", jobdir.name)
    state.setdefault("event_seq", 0)
    if not isinstance(state.get("outbox"), list):
        state["outbox"] = []
    if not isinstance(state.get("attempts"), list):
        state["attempts"] = []
    if not isinstance(state.get("owned_agents"), dict):
        state["owned_agents"] = {}
        try:
            job = read_json(jobdir / "job.json")
        except QueueError:
            job = {}
        for agent_id in _job_agent_ids(job):
            role = next((name for name in ("coder", "designer", "reviewer")
                         if job.get(f"{name}_agent") == agent_id), "reviewer")
            state["owned_agents"][agent_id] = {"role": role, "status": "needs-reconciliation"}
    state.setdefault("report", str(jobdir / "report.md"))
    state["attempts"].append({"path": str(attempt), "rc": 70, "duration": 0})
    short = f"supervisor exception ({type(exc).__name__}): {str(exc).splitlines()[0][:140]}"
    with locked(jobdir / "job.lock"):
        atomic_json(jobdir / "state.json", state)
    return save_terminal(jobdir, state, "parked", short)


def supervise(spec_path, jobdir, driver_path, sleep_fn=None):
    """Supervise one job and convert unexpected faults into durable parked events."""
    try:
        return _supervise(spec_path, jobdir, driver_path, sleep_fn=sleep_fn)
    except Exception as exc:
        event = _park_supervisor_exception(jobdir, exc, traceback.format_exc())
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
    if argv[:2] == ["queue", "stop"]:
        if len(argv) != 3:
            print("usage: agentcoder.py queue stop JOBDIR")
            return 1
        try:
            status, reason = maintenance_stop(argv[2])
            print(json.dumps({"status": status, "reason": reason}, sort_keys=True))
            return 0 if status == "PAUSED" else 2
        except (QueueError, OSError) as exc:
            print(json.dumps({"status": "STOP_PENDING", "reason": str(exc)}))
            return 2
    if argv[:2] == ["queue", "resume"]:
        if len(argv) != 3:
            print("usage: agentcoder.py queue resume JOBDIR")
            return 1
        try:
            ok, reason = authorize_resume(argv[2])
            if not ok:
                print(json.dumps({"status": "parked", "reason": reason}, sort_keys=True))
                return 2
            state = load_state(argv[2])
            return supervise(state["spec_path"], argv[2], driver_path)
        except (QueueError, OSError, KeyError) as exc:
            print(json.dumps({"status": "parked", "reason": str(exc)}, sort_keys=True))
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
