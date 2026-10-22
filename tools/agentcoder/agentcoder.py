#!/usr/bin/env python3
"""agentcoder — a small driver: coder agent + blind test designer + executor.

No Paseo event hooks and no journal: a blocking ``paseo run`` / ``paseo send``
call IS the completion signal.  All state lives in ``JOBDIR/job.json``,
rewritten atomically after every phase transition, so ``resume JOBDIR``
continues from the recorded phase.  See tools/agentcoder/README.md.
"""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXIT_OK, EXIT_ERROR, EXIT_ESCALATED = 0, 1, 2
DEFAULT_MODEL = "opencode/qwenlocal/Qwen3.8-Flash-Next"
DEFAULT_TC = ["python", "-m", "pytest", "-q", "{tests}"]
PHASES = ["spawn", "test_review", "execute", "candidate", "land", "report", "done"]
PROMPT_CAP = 150
PASEO_TIMEOUT = 60
LIM = ["prlimit", "--cpu=60", "--as=3221225472", "--fsize=268435456", "--nproc=256"]
TASK_ID_RE = re.compile(r"[A-Za-z0-9._-]+\Z")


class Pause(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class Escalate(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def tool_path(name):
    if name == "paseo":
        return os.environ.get("AGENTCODER_PASEO", "paseo")
    if name == "gh":
        return os.environ.get("AGENTCODER_GH", "gh")
    return name


def resolve(argv):
    return [tool_path(argv[0])] + list(argv[1:])


def run_cmd(argv, cwd=None, env=None, timeout=None):
    """The one subprocess helper.  Fake it via AGENTCODER_PASEO / AGENTCODER_GH."""
    proc = subprocess.run(resolve(argv), cwd=cwd, env=env, timeout=timeout,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def run_guarded(argv, cwd=None, timeout=PASEO_TIMEOUT):
    """Every blocking tool call goes through here: a hung tool is a Pause."""
    try:
        return run_cmd(argv, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Pause(f"{' '.join(map(str, argv[:3]))} timed out after {timeout}s")


def tail_text(text, limit=PROMPT_CAP):
    lines = text.splitlines()
    return "\n".join(lines[-limit:])


def json_of(text, what):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise Pause(f"unparseable {what}: {exc}: {text[:200]!r}")


def git(repo, *args, check=True, timeout=120):
    try:
        rc, out, err = run_cmd(["git", "-C", str(repo)] + [str(a) for a in args],
                               env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
                               timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Pause(f"git {' '.join(map(str, args))} in {repo}: timed out after {timeout}s")
    if check and rc != 0:
        raise Pause(f"git {' '.join(map(str, args))} in {repo}: rc={rc} {err.strip()[:200]}")
    return out.strip()


def save_job(job):
    path = Path(job["jobdir"]) / "job.json"
    tmp = Path(job["jobdir"]) / "job.json.tmp"
    with open(tmp, "w") as fh:
        json.dump(job, fh, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_job(jobdir):
    path = Path(jobdir) / "job.json"
    if not path.is_file():
        raise Pause(f"no job.json in {jobdir}")
    return json_of(path.read_text(), "job.json")


def validate_spec(spec):
    problems = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    tid = str(spec.get("task_id", ""))
    if not TASK_ID_RE.match(tid):
        problems.append(f"task_id must match [A-Za-z0-9._-]+, got {tid!r}")
    else:
        for role in ("coder", "designer", "review-r0"):
            rc, _, _ = run_guarded(["git", "check-ref-format", "--branch",
                                    f"ac/{tid}/{role}"])
            if rc != 0:
                problems.append(f"task_id {tid!r} cannot form git branch "
                                f"ac/{tid}/{role}")
                break
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        problems.append("title must be a non-empty string")
    repo = str(spec.get("repo", ""))
    repo_root = os.path.realpath(os.path.expanduser(repo)) if repo else ""
    if not repo_root:
        problems.append(f"repo is not a git repository: {repo!r}")
    else:
        rc, out, _ = run_guarded(["git", "-C", repo_root, "rev-parse",
                                  "--is-inside-work-tree"])
        if rc != 0 or out.strip() != "true":
            problems.append(f"repo is not a git repository: {repo!r}")

    def rel_path(value, what, must_exist):
        if not isinstance(value, str) or not value:
            problems.append(f"{what} must be a non-empty path")
            return
        target = os.path.realpath(os.path.join(repo_root, value))
        if not (target == repo_root or target.startswith(repo_root + os.sep)):
            problems.append(f"{what} must stay inside repo: {value!r}")
        if must_exist and not os.path.isfile(target):
            problems.append(f"{what} is not a file: {value!r}")

    rel_path(spec.get("contract_file"), "contract_file", True)
    if not str(spec.get("base", "")):
        problems.append("base (git ref) is required")

    def check_globs(key):
        globs = spec.get(key)
        if not isinstance(globs, list) or not globs:
            problems.append(f"{key} must be a non-empty list of globs")
            return
        for g in globs:
            if not isinstance(g, str) or not g or os.path.isabs(g) \
                    or g.split("/")[0] in ("", "..", "."):
                problems.append(f"{key} entry must be a relative glob: {g!r}")

    check_globs("allowed_code_paths")
    check_globs("allowed_test_paths")
    cases_file = spec.get("cases_file", f"tests/{tid}.cases.json")
    if not isinstance(cases_file, str) or os.path.isabs(cases_file) \
            or any(ch in cases_file for ch in "*?[") \
            or not any(path_matches(cases_file, g)
                       for g in spec.get("allowed_test_paths") or []):
        problems.append(f"cases_file must be a plain path inside "
                        f"allowed_test_paths: {cases_file!r}")
    tc = spec.get("test_command", DEFAULT_TC)
    if not isinstance(tc, list) or not all(isinstance(x, str) and x for x in tc) \
            or "{tests}" not in tc:
        problems.append(f"test_command must be a fixed argv list containing '{{tests}}': {tc!r}")
    for key, lo in (("max_rounds", 1), ("qwen_cap", 1), ("reserve", 0)):
        value = spec.get(key, {"max_rounds": 2, "qwen_cap": 8, "reserve": 1}[key])
        if not isinstance(value, int) or isinstance(value, bool) or value < lo:
            problems.append(f"{key} must be an int >= {lo}, got {value!r}")
    return problems


def preflight(job):
    spec = job["spec"]
    if job.get("base_sha") is None:  # pinned at first resolution; never re-moved
        job["base_sha"] = git(spec["repo"], "rev-parse", "--verify",
                              str(spec["base"]) + "^{commit}")
    if not shutil.which("prlimit") and not spec.get("allow_no_prlimit"):
        raise Pause("prlimit is not on PATH: tests would run WITHOUT CPU/address-space "
                    "limits; install prlimit, or set \"allow_no_prlimit\": true to accept")
    rc, out, err = run_guarded(["paseo", "ls", "-g", "--json"])
    if rc != 0:
        raise Pause(f"cannot list agents (paseo ls -g): {tail_text(err, 5) or rc}")
    data = json_of(out, "paseo ls output")
    agents = data.get("agents", []) if isinstance(data, dict) else data
    running = [a for a in agents if a.get("status") == "running"
               and "qwen" in str(a.get("model", "")).lower()]
    room = int(spec["qwen_cap"]) - int(spec["reserve"])
    if len(running) >= room:
        raise Pause(f"refusing to start: {len(running)} Qwen agents running, "
                    f"cap({spec['qwen_cap']}) - reserve({spec['reserve']}) = {room}")
    job["preflight_ok"] = True


def ensure_preflight(job):
    """Re-runs the safety gates on every resume until they have fully passed
    (preflight_ok is only set once ALL checks pass, so a pause mid-preflight
    cannot leave base_sha set and let resume skip the prlimit/capacity gates).
    Returns an exit code to use, or None to continue."""
    if job.get("preflight_ok"):
        return None
    try:
        preflight(job)
    except Pause as exc:
        job["status"], job["reason"] = "paused", exc.reason
        save_job(job)
        write_report(job)
        return EXIT_ERROR
    save_job(job)
    return None


def contract_text(job):
    try:
        return Path(job["spec"]["repo"], job["spec"]["contract_file"]).read_text()
    except OSError as exc:  # report.md must never crash the exit path
        return f"(contract unreadable: {exc})"


def branch_name(job, role):
    return f"ac/{job['task_id']}/{role}"


def designer_prompt(job):
    cf = job["spec"].get("cases_file", f"tests/{job['task_id']}.cases.json")
    return (
        f"You are the BLIND test designer for task {job['task_id']}. Write no product code.\n"
        f"Contract:\n{contract_text(job)}\n"
        f"Rules:\n"
        f"- Write tests ONLY under: {', '.join(job['spec']['allowed_test_paths'])}. "
        f"Never edit anything else.\n"
        f"- Never look at other branches, other worktrees, or their history "
        f"(no `git log --all`). You are blind to the implementation.\n"
        f"- Commit your work on the current branch.\n"
        f"- Write {cf} mapping each pytest node id to "
        f'{{"expected_on_base": "pass"|"fail", "requirement": "one line"}}. '
        f'"pass" = a control that must already pass on the OLD code; '
        f'"fail" = new behavior the change must bring.'
    )


def coder_prompt(job):
    return (
        f"You are the coder for task {job['task_id']}. Implement the contract below.\n"
        f"Contract:\n{contract_text(job)}\n"
        f"Rules:\n"
        f"- Touch ONLY files matching: {', '.join(job['spec']['allowed_code_paths'])}.\n"
        f"- Do NOT write the acceptance tests; a separate designer owns them.\n"
        f"- Run your own quick checks, then commit on the current branch."
    )


def review_prompt(job):
    return (
        f"Review the tests in this worktree against the contract (author: a blind designer).\n"
        f"Contract:\n{contract_text(job)}\n"
        f"Checklist: assertions match the CONTRACT and real CLI behavior; every declared "
        f"control really passes on the base commit; every intended red fails for the right "
        f"reason; the tests do not accidentally target another change.\n"
        f'End your reply with exactly one line: "VERDICT: APPROVE" or '
        f'"VERDICT: CHANGES REQUESTED", findings below it.'
    )


def base_env(job):
    return {"PATH": os.environ.get("PATH", ""), "HOME": job["jobdir"], "LANG": "C.UTF-8"}


def agent_cwd(job, agent_id):
    rc, out, err = run_guarded(["paseo", "ls", "-g", "--json"])
    if rc != 0:
        raise Pause(f"cannot list agents (paseo ls -g): {tail_text(err, 5) or rc}")
    data = json_of(out, "paseo ls output")
    agents = data.get("agents", []) if isinstance(data, dict) else data
    for a in agents:
        if a.get("agentId") == agent_id and a.get("cwd"):
            return a["cwd"]
    raise Pause(f"agent {agent_id} reports no worktree path (cwd) in paseo ls output")


def check_permits(job):
    rc, out, err = run_guarded(["paseo", "permit", "ls", "--json"])
    if rc != 0:
        raise Pause(f"cannot list pending permits (paseo permit ls rc={rc}): "
                    f"{tail_text(err, 3)}")
    data = json_of(out, "paseo permit ls output")
    entries = data.get("permits", []) if isinstance(data, dict) else data
    ids = {job.get("coder_agent"), job.get("designer_agent"),
           *(job.get("reviewers") or {}).values()}
    hit = [e for e in entries if e.get("agentId") in ids]
    if hit:
        raise Pause(f"permission prompt pending for job agents: "
                    f"{sorted(e.get('agentId') for e in hit)}")


def record_turn(job, role, rc, out, err):
    if rc != 0:
        raise Pause(f"{role} agent turn failed (rc={rc}, quota/usage?): {tail_text(err, 5)}")
    data = json_of(out, f"{role} run result")
    status = data.get("status")
    if status != "completed":
        raise Pause(f"{role} agent turn ended with status {status!r}: {tail_text(out, 5)}")
    agent_id = data.get("agentId")
    if not agent_id:
        raise Pause(f"{role} agent turn reported no agentId: {tail_text(out, 3)}")
    job[f"{role}_agent"] = agent_id
    job[f"{role}_cwd"] = agent_cwd(job, agent_id)
    save_job(job)  # ids survive a hard crash mid-loop, so resume adopts them


def send_to(job, agent_key, message):
    agent_id = job.get(agent_key)
    if not agent_id:
        raise Pause(f"no recorded agent for {agent_key}; refusing to guess")
    rc, out, err = run_guarded(["paseo", "send", agent_id, "--json", message],
                                timeout=int(job["spec"].get("agent_timeout", 1800)))
    if rc != 0:
        raise Pause(f"send to {agent_key} failed (rc={rc}): {tail_text(err, 5)}")
    status = json_of(out, "send result").get("status")
    if status != "completed":
        raise Pause(f"send to {agent_key} ended with status {status!r}")
    check_permits(job)


def spawn_agent(job, role, model, base, prompt):
    argv = ["paseo", "run", "--new-workspace", "worktree", "--worktree-mode", "branch-off",
            "--new-branch", branch_name(job, role), "--base", base, "--model", model,
            "--title", f"AgentCoder {job['task_id']} {role}", "--json", prompt]
    try:
        rc, out, err = run_guarded(argv, cwd=job["spec"]["repo"],
                                   timeout=int(job["spec"].get("agent_timeout", 1800)))
    except Pause as exc:
        raise Pause(f"{role} spawn: {exc}")
    key = "reviewer" if role.startswith("review") else role
    record_turn(job, key, rc, out, err)
    return job[f"{key}_cwd"]


def _kill_all(procs):
    for proc in procs.values():
        proc.kill()
    for proc in procs.values():
        proc.wait()


def do_spawn(job):
    spec = job["spec"]
    need = [r for r in ("coder", "designer") if not job.get(f"{r}_agent")]
    if need:
        prompts = {"coder": coder_prompt(job), "designer": designer_prompt(job)}
        procs = {}
        for role in need:
            model = spec.get(f"{role}_model") or DEFAULT_MODEL
            argv = resolve(["paseo", "run", "--new-workspace", "worktree",
                            "--worktree-mode", "branch-off",
                            "--new-branch", branch_name(job, role),
                            "--base", job["base_sha"], "--model", model,
                            "--title", f"AgentCoder {job['task_id']} {role}",
                            "--json", prompts[role]])
            procs[role] = subprocess.Popen(argv, cwd=spec["repo"],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True)
        for role, proc in procs.items():
            try:
                out, err = proc.communicate(timeout=int(spec.get("agent_timeout", 1800)))
            except subprocess.TimeoutExpired:
                _kill_all(procs)
                raise Pause(f"{role} agent turn timed out")
            try:
                record_turn(job, role, proc.returncode, out, err)
            except Pause:
                _kill_all(procs)
                raise
        check_permits(job)
    else:
        for role in ("coder", "designer"):
            run_guarded(["paseo", "wait", job[f"{role}_agent"], "--timeout", "60"])
        check_permits(job)


def path_matches(p, g):
    g = g.rstrip("/")
    if not any(ch in g for ch in "*?[") and (p == g or p.startswith(g + "/")):
        return True
    return fnmatch.fnmatch(p, g)


def scope_check(job, sha, globs, who):
    changed = [p for p in git(job["spec"]["repo"], "diff", "--name-only",
                              job["base_sha"], sha).splitlines() if p]
    bad = sorted(p for p in changed if not any(path_matches(p, g) for g in globs))
    if bad:
        raise Escalate(f"{who} touched paths outside its allowed globs: {bad}")
    return changed


def freeze_tests(job):
    return git(job["designer_cwd"], "rev-parse", "HEAD")


def do_test_review(job):
    spec = job["spec"]
    if not spec.get("test_reviewer_model"):
        job["test_review"] = "skipped (no test_reviewer_model in spec)"
        return
    rnd = int(job.get("review_round", 0))
    reviewers = job.setdefault("reviewers", {})
    while True:
        if rnd >= int(spec["max_rounds"]):
            raise Escalate(f"test review unresolved after {rnd} round(s): reviewer kept "
                           f"requesting changes")
        test_sha = job.get("test_sha") or freeze_tests(job)
        job["test_sha"] = test_sha
        key = f"{rnd}@{test_sha[:8]}"  # sha-scoped: re-reviews get a fresh reviewer
        if not reviewers.get(key):
            spawn_agent(job, f"review-r{rnd}-{test_sha[:6]}", spec["test_reviewer_model"],
                        test_sha, review_prompt(job))
            reviewers[key] = job.pop("reviewer_agent")
            job.pop("reviewer_cwd", None)
            save_job(job)
        rc, out, err = run_guarded(["paseo", "logs", reviewers[key], "--tail", "60"])
        if rc != 0:
            raise Pause(f"paseo logs for reviewer {reviewers[key]} failed (rc={rc})")
        verdicts = re.findall(r"VERDICT:\s*(APPROVE|CHANGES REQUESTED)", out)
        if not verdicts:
            raise Pause(f"reviewer round {rnd} produced no VERDICT line; refusing to guess")
        check_permits(job)
        if verdicts[-1] == "APPROVE":
            job["test_review"] = "APPROVE"
            job["review_round"] = rnd
            job["reviewed_test_sha"] = test_sha
            return
        job["test_review"] = f"CHANGES REQUESTED (round {rnd})"
        send_to(job, "designer_agent",
                f"Test review round {rnd} requested changes; the reviewer said:\n"
                f"{tail_text(out)}\nFix the tests on your branch, keep them blind, commit.")
        rnd += 1
        job["review_round"] = rnd
        job["test_sha"] = None
        save_job(job)


OUTCOME_RE = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)[ \t]+"
                        r"(?:\[\d+\][ \t]+)?(\S+)", re.MULTILINE)


def run_tests(job, wt):
    argv = []
    for part in job["spec"].get("test_command", DEFAULT_TC):
        argv.extend(job["spec"]["allowed_test_paths"] if part == "{tests}" else [part])
    if any("pytest" in part for part in argv) and "-rA" not in argv:
        argv.append("-rA")
    cmd = (["prlimit"] + LIM[1:]) if shutil.which("prlimit") else []
    cmd += argv
    tmo = int(job["spec"].get("test_timeout", 120))
    try:
        rc, out, err = run_cmd(cmd, cwd=wt, env=base_env(job), timeout=tmo)
    except subprocess.TimeoutExpired:
        raise Pause(f"test command timed out after {tmo}s; nothing was judged "
                    f"and no agent was fed this output")
    outcomes = {node.rstrip(":"): status
                for status, node in OUTCOME_RE.findall(out + err)}
    if rc not in (0, 1, 5) and not outcomes:
        raise Pause(f"test command exited {rc} with no per-test outcomes: "
                    f"{tail_text(out + err, 8)}")
    return rc, out + err, outcomes


def load_cases(job, test_sha):
    cf = job["spec"].get("cases_file", f"tests/{job['task_id']}.cases.json")
    raw = git(job["spec"]["repo"], "show", f"{test_sha}:{cf}", check=False)
    cases = json_of(raw, "cases.json") if raw else None
    if not isinstance(cases, dict) or not cases:
        raise Escalate(f"no usable {cf} in frozen test commit {test_sha}; "
                       f"designer must declare every test id")
    for test_id, decl in cases.items():
        want = decl if isinstance(decl, str) else decl.get("expected_on_base")
        if want not in ("pass", "fail"):
            raise Escalate(f"cases.json entry {test_id!r} has expected_on_base={want!r}, "
                           f"must be 'pass' or 'fail'")
    return cases


def compare_cases(cases, outcomes):
    problems = []
    for test_id, decl in sorted(cases.items()):
        want = decl if isinstance(decl, str) else decl.get("expected_on_base")
        got = outcomes.get(test_id, "NOT-COLLECTED")
        if want == "pass" and got != "PASSED":
            problems.append(f"{test_id}: control declared 'pass' but on base it is {got}")
        if want == "fail" and got != "FAILED":
            problems.append(f"{test_id}: declared 'fail' (new behavior) but on base it is "
                            f"{got} — it must FAIL on base to pin the change")
    return problems


def gate_failures(cases, outcomes):
    """Every declared id must have been collected and PASSED; SKIPPED/XFAIL/
    XPASS/ERROR/FAILED/missing are all red, each with the observed outcome."""
    return [f"{t} ({outcomes.get(t, 'NOT-COLLECTED')})"
            for t in sorted(cases) if outcomes.get(t, "NOT-COLLECTED") != "PASSED"]


def ensure_worktree(job, name, sha):
    wt = str(Path(job["jobdir"]) / name)
    if Path(wt).exists():
        git(wt, "checkout", "--force", "--detach", sha)
        git(wt, "clean", "-fdq")
    else:
        git(job["spec"]["repo"], "worktree", "add", "--detach", wt, sha)
    return wt


def drop_worktree(job, wt):
    git(job["spec"]["repo"], "worktree", "remove", "--force", wt, check=False)


def do_execute(job):
    spec = job["spec"]
    rnd = int(job.get("execute_round", 0))
    while True:
        head = freeze_tests(job)
        test_sha = job["test_sha"] = head
        if spec.get("test_reviewer_model") and head != job.get("reviewed_test_sha"):
            return "test_review"  # designer committed new tests: re-gate via review
        test_paths = scope_check(job, test_sha, spec["allowed_test_paths"], "test designer")
        test_paths = [p for p in test_paths
                      if any(path_matches(p, g) for g in spec["allowed_test_paths"])
                      and not p.endswith(".cases.json")]
        if not test_paths:
            raise Escalate(f"test designer commit {test_sha[:9]} adds no files "
                           f"under {spec['allowed_test_paths']}")
        cases = load_cases(job, test_sha)
        wt = ensure_worktree(job, "base-wt", job["base_sha"])
        try:
            git(wt, "checkout", "-f", test_sha, "--", *test_paths)
            rc, out, outcomes = run_tests(job, wt)
        finally:
            drop_worktree(job, wt)
        problems = compare_cases(cases, outcomes)
        job["execute_last"] = {"round": rnd, "rc": rc, "problems": problems,
                               "tail": tail_text(out, 30)}
        if not problems:
            job["test_paths"] = test_paths
            job["controls"] = sum(1 for d in cases.values()
                                  if (d if isinstance(d, str) else d.get("expected_on_base")) == "pass")
            job["intended_reds"] = len(cases) - job["controls"]
            job["execute_round"] = rnd
            return
        if rnd >= int(spec["max_rounds"]):
            raise Escalate(f"tests still mismatch cases.json after {rnd} round(s): "
                           f"{'; '.join(problems[:6])}")
        send_to(job, "designer_agent",
                "Executor ran the frozen tests against the BASE commit and the outcomes "
                "contradict " + spec["cases_file"] + ":\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\nOutput tail:\n" + tail_text(out)
                + "\nFix the tests (a control that fails on base, a 'fail' case that "
                  "passes on base = TEST bug). Never edit the implementation.")
        rnd += 1
        job["execute_round"] = rnd
        job["test_sha"] = None
        save_job(job)


def do_candidate(job):
    spec = job["spec"]
    rnd = int(job.get("candidate_round", 0))
    cases = load_cases(job, job["test_sha"])
    while True:
        coder_sha = git(job["coder_cwd"], "rev-parse", "HEAD")
        scope_check(job, coder_sha, spec["allowed_code_paths"], "coder")
        wt = ensure_worktree(job, f"cand-wt-{rnd}", coder_sha)
        try:
            git(wt, "checkout", "-f", job["test_sha"], "--", *job["test_paths"])
            rc, out, outcomes = run_tests(job, wt)
        finally:
            drop_worktree(job, wt)
        failed = gate_failures(cases, outcomes)
        if rc == 5:
            failed = failed or ["no tests were collected (exit 5)"]
        if rc == 0 and not failed:
            job["coder_sha"] = coder_sha
            job.setdefault("candidate_results", []).append(
                {"round": rnd, "rc": rc, "failed": []})
            job["candidate_round"] = rnd
            return
        job.setdefault("candidate_results", []).append(
            {"round": rnd, "rc": rc, "failed": failed})
        if rnd >= int(spec["max_rounds"]):
            raise Escalate(f"candidate red after {rnd} round(s); last failures: "
                           f"{failed[:10] or tail_text(out, 8)}")
        send_to(job, "coder_agent",
                "The executor ran the fixed acceptance tests against your branch and it "
                f"is RED (round {rnd}).\nFailing tests: {', '.join(failed[:30])}\n"
                f"Output (last {PROMPT_CAP} lines):\n{tail_text(out)}\n"
                "Make the change; NEVER weaken, skip, or edit the tests.")
        rnd += 1
        job["candidate_round"] = rnd
        save_job(job)


def co_trailer(job):
    model = str(job["spec"].get("coder_model") or DEFAULT_MODEL)
    return f"Co-authored-by: {model.rsplit('/', 1)[-1]} <noreply@refdes.local>"


def do_land(job):
    wt = job["coder_cwd"]
    head = git(wt, "rev-parse", "HEAD")
    if head != job["coder_sha"] and head != job.get("test_landed_sha"):
        return "candidate"  # coder moved: re-gate the new head, land gates only
    dirty = git(wt, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise Escalate("coder worktree has uncommitted/staged changes; refusing to "
                       f"sweep them into the test commit:\n{tail_text(dirty, 15)}")
    git(wt, "checkout", job["test_sha"], "--", *job["test_paths"])
    if git(wt, "diff", "--cached", "--name-only", check=False):
        git(wt, "-c", "user.name=agentcoder", "-c", "user.email=noreply@refdes.local",
            "commit", "--author", "agentcoder <noreply@refdes.local>",
            "-m", f"test: acceptance tests for {job['task_id']} (agentcoder)",
            "-m", co_trailer(job))
        # driver-recorded sha (job.json is not agent-writable): identifies the
        # driver's own test commit as landable on resume, without string matching
        job["test_landed_sha"] = git(wt, "rev-parse", "HEAD")
        save_job(job)
    git(wt, "push", "-u", "origin", branch_name(job, "coder"), timeout=300)
    job["pushed_sha"] = git(wt, "rev-parse", "HEAD")
    save_job(job)
    if job.get("pr_number") is None:
        rc, out, _ = run_guarded(["gh", "pr", "list", "--head",
                                  branch_name(job, "coder"), "--json",
                                  "number,state,headRefOid", "--state", "all"], cwd=wt)
        if rc != 0:
            raise Pause("gh pr list failed; refusing to run gh pr create blind "
                        "(a duplicate PR could result)")
        existing = json_of(out, "gh pr list output")
        hit = next((p for p in existing if p.get("state") == "OPEN"
                    or (p.get("state") == "MERGED" and p.get("headRefOid") == job.get("pushed_sha"))), None)
        if hit is None and existing:
            raise Escalate(f"PR(s) {[(p.get('number'), p.get('state')) for p in existing]}"
                           f" exist for {branch_name(job, 'coder')} and none is "
                           f"adoptable; resolve them manually before landing")
        if hit:
            job["pr_number"] = int(hit["number"])
            save_job(job)
            print(f"PR: {job['pr_number']} (adopted existing)")
        else:
            body = Path(job["jobdir"], "report.md")
            write_report(job, landing=True)
            rc, out, err = run_guarded(
                ["gh", "pr", "create", "--title", str(job["spec"]["title"]),
                 "--base", str(job["spec"]["base"]),
                 "--head", branch_name(job, "coder"),
                 "--body-file", str(body)], cwd=wt)
            if rc != 0:
                raise Pause(f"gh pr create failed (rc={rc}): {tail_text(err, 5)}")
            found = re.search(r"/pull/(\d+)", out)
            if not found:
                raise Pause(f"gh pr create printed no PR URL: {tail_text(out, 3)}")
            job["pr_number"] = int(found.group(1))
            save_job(job)
            print(f"PR: {job['pr_number']}")
        write_report(job)


def write_report(job, landing=False):
    rows = "\n".join(
        f"| {r['round']} | {r['rc']} | {', '.join(r['failed']) or '-'} |"
        for r in job.get("candidate_results", []))
    lines = [
        f"# agentcoder report — {job['task_id']}",
        "",
        f"- status: **{job.get('status', 'running')}**"
        + (f" — {job['reason']}" if job.get("reason") else ""),
        f"- base SHA: `{job.get('base_sha')}`",
        f"- frozen test SHA: `{job.get('test_sha')}`",
        f"- coder SHA: `{job.get('coder_sha')}`",
        f"- controls green: {job.get('controls')}, intended reds: {job.get('intended_reds')}",
        f"- test review: {job.get('test_review', 'not reached')}",
        f"- PR: {job.get('pr_number') or '-'}",
        "",
        "## Contract (summary)",
        "",
        tail_text(contract_text(job), 20) if job.get("spec", {}).get("contract_file") else "-",
        "",
        "## Candidate results per round",
        "",
        "| round | exit | failing tests |",
        "| --- | --- | --- |",
        rows or "| - | - | not reached |",
    ]
    Path(job["jobdir"], "report.md").write_text("\n".join(lines) + "\n")
    if landing:
        return
    summary = {
        "job": job["jobdir"], "task_id": job["task_id"], "status": job.get("status"),
        "reason": job.get("reason"), "base_sha": job.get("base_sha"),
        "test_sha": job.get("test_sha"), "code_sha": job.get("coder_sha"),
        "controls_green": job.get("controls"), "intended_reds": job.get("intended_reds"),
        "candidate_results": job.get("candidate_results", []),
        "test_review": job.get("test_review"), "pr_number": job.get("pr_number"),
    }
    print(json.dumps(summary, indent=1, sort_keys=True))


def do_report(job):
    job["status"] = "ready-for-human-gate"
    job["reason"] = None


HANDLERS = {"spawn": do_spawn, "test_review": do_test_review, "execute": do_execute,
            "candidate": do_candidate, "land": do_land, "report": do_report}


def run_loop(job):
    while job["phase"] != "done":
        try:
            job["phase"] = HANDLERS[job["phase"]](job) \
                or PHASES[PHASES.index(job["phase"]) + 1]
            save_job(job)
        except Escalate as exc:
            job["status"], job["reason"] = "escalated", exc.reason
            save_job(job)
            write_report(job)
            return EXIT_ESCALATED
        except Pause as exc:
            job["status"], job["reason"] = "paused", exc.reason
            save_job(job)
            write_report(job)
            return EXIT_ERROR
    write_report(job)
    return EXIT_OK


def exit_json(status, reason):
    print(json.dumps({"status": status, "reason": reason}, sort_keys=True))


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[0])
        print("usage: agentcoder.py run SPEC.json [JOBDIR] | resume JOBDIR | status JOBDIR")
        return EXIT_ERROR
    cmd, arg = argv[0], argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "run":
            try:
                raw = Path(arg).read_text()
            except OSError as exc:
                exit_json("error", f"spec unreadable: {exc}")
                return EXIT_ERROR
            spec = json_of(raw, "spec file")
            problems = validate_spec(spec)
            if problems:
                exit_json("invalid-spec", "; ".join(problems))
                return EXIT_ERROR
            spec.setdefault("test_command", DEFAULT_TC)
            spec.setdefault("coder_model", DEFAULT_MODEL)
            spec.setdefault("designer_model", DEFAULT_MODEL)
            spec.setdefault("max_rounds", 2)
            spec.setdefault("qwen_cap", 8)
            spec.setdefault("reserve", 1)
            spec.setdefault("cases_file", f"tests/{spec['task_id']}.cases.json")
            jobdir = Path(argv[2] if len(argv) > 2
                          else Path(spec["repo"]) / ".scratch" / "agentcoder"
                          / spec["task_id"]).resolve()
            jobdir.mkdir(parents=True, exist_ok=True)
            if (jobdir / "job.json").exists():
                exit_json("error", f"a job already lives in {jobdir}; use resume")
                return EXIT_ERROR
            job = {"jobdir": str(jobdir), "task_id": spec["task_id"], "spec": spec,
                   "phase": "spawn", "status": "running", "reason": None}
            save_job(job)
            rc = ensure_preflight(job)
            if rc is not None:
                return rc
        elif cmd in ("resume", "status"):
            job = load_job(arg)
            job["jobdir"] = str(Path(arg).resolve())
            if cmd == "status":
                keep = ("task_id", "phase", "status", "reason", "base_sha", "test_sha",
                        "coder_sha", "pr_number", "test_review", "execute_round",
                        "candidate_round", "review_round")
                print(json.dumps({k: job.get(k) for k in keep}, indent=1, sort_keys=True))
                return EXIT_OK
            job["status"], job["reason"] = "running", None
            rc = ensure_preflight(job)
            if rc is not None:
                return rc
        else:
            exit_json("error", f"unknown command: {cmd}")
            return EXIT_ERROR
        return run_loop(job)
    except Pause as exc:
        exit_json("paused", exc.reason)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
