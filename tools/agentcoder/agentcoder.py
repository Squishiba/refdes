#!/usr/bin/env python3
"""agentcoder — a small driver: coder agent + blind test designer + executor.

No Paseo event hooks and no journal: a blocking ``paseo run`` / ``paseo send``
call IS the completion signal.  All state lives in ``JOBDIR/job.json``,
rewritten atomically after every phase transition, so ``resume JOBDIR``
continues from the recorded phase.  See tools/agentcoder/README.md.
"""
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

EXIT_OK, EXIT_ERROR, EXIT_ESCALATED = 0, 1, 2
DEFAULT_MODEL = "opencode/qwenlocal/Qwen3.8-Flash-Next"
DEFAULT_TC = ["python", "-m", "pytest", "-q", "{tests}"]
PHASES = ["spawn", "test_review", "execute", "candidate", "land", "report", "done"]
PROMPT_CAP = 150
PASEO_TIMEOUT = 60
LIM = ["prlimit", "--cpu=60", "--as=3221225472", "--fsize=268435456", "--nproc=256"]
TASK_ID_RE = re.compile(r"[A-Za-z0-9._-]+\Z")


class JobExit(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class Pause(JobExit):
    pass


class Escalate(JobExit):
    pass


class OutOfScope(Escalate):
    def __init__(self, who, paths):
        super().__init__(f"{who} touched paths outside its allowed globs: {sorted(paths)}")
        self.paths = sorted(paths)


def tool_path(name):
    return os.environ.get(f"AGENTCODER_{name.upper()}", name) if name in ("paseo", "gh") else name


def resolve(argv):
    return [tool_path(argv[0])] + list(argv[1:])


def run_cmd(argv, cwd=None, env=None, timeout=None):
    # the one subprocess helper; fake it via AGENTCODER_PASEO / AGENTCODER_GH
    try:
        proc = subprocess.run([tool_path(argv[0])] + list(argv[1:]), cwd=cwd, env=env,
                              timeout=timeout, capture_output=True, text=True,
                              errors="replace")  # agents/tests can emit undecodable bytes
    except OSError as exc:  # missing/not-executable paseo/gh/git/prlimit: Pause, not crash
        raise Pause(f"cannot launch {argv[0]}: {exc}")
    return proc.returncode, proc.stdout, proc.stderr


def run_guarded(argv, cwd=None, timeout=PASEO_TIMEOUT):
    # every blocking tool call goes through here: a hung tool is a Pause
    try:
        return run_cmd(argv, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Pause(f"{' '.join(map(str, argv[:3]))} timed out after {timeout}s")


def tail_text(text, limit=PROMPT_CAP):
    return "\n".join(text.splitlines()[-limit:])


def json_of(text, what):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise Pause(f"unparseable {what}: {exc}: {text[:200]!r}")


def last_json_of(text, what):
    try:
        return json.loads(text)
    except ValueError:
        pass
    dec, docs, i = json.JSONDecoder(), [], 0
    while (j := text.find("{", i)) >= 0:
        try:
            doc, end = dec.raw_decode(text, j)
            docs.append(doc)
            i = end
        except ValueError:
            i = j + 1
    if not docs:
        raise Pause(f"unparseable {what}: {text[:200]!r}")
    return docs[-1]


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
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(job, fh, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_job(jobdir):
    path = Path(jobdir) / "job.json"
    if not path.is_file():
        raise Pause(f"no job.json in {jobdir}")
    return json_of(path.read_text(encoding="utf-8", errors="replace"), "job.json")


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
        if len(tid) > 32:  # spawn titles stay within the ~60-char ls name truncation
            problems.append(f"task_id {tid!r} too long: AgentCoder titles would be cut")
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
        else:
            spec["repo"] = repo_root  # normalize once: all later paths use this

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
            return False
        ok = True
        for g in globs:
            parts = g.split("/") if isinstance(g, str) else []
            if not isinstance(g, str) or not g or os.path.isabs(g) \
                    or parts[0] in ("", ".") or ".." in parts:
                problems.append(f"{key} entry must be a relative glob with no '..' "
                                f"component: {g!r}")
                ok = False
        return ok

    if "allow_no_prlimit" in spec and not isinstance(spec["allow_no_prlimit"], bool):
        problems.append(f"allow_no_prlimit must be a real JSON bool, not {spec['allow_no_prlimit']!r}")
    check_globs("allowed_code_paths")
    test_globs_ok = check_globs("allowed_test_paths")
    cases_file = spec.get("cases_file", f"tests/{tid}.cases.json")
    if not isinstance(cases_file, str) or os.path.isabs(cases_file) \
            or any(ch in cases_file for ch in "*?["):
        problems.append(f"cases_file must be a plain path inside "
                        f"allowed_test_paths: {cases_file!r}")
    elif test_globs_ok and not any(
            path_matches(cases_file, g) for g in spec["allowed_test_paths"]):
        problems.append(f"cases_file must be a plain path inside "
                        f"allowed_test_paths: {cases_file!r}")
    tc = spec.get("test_command", DEFAULT_TC)
    if not isinstance(tc, list) or not all(isinstance(x, str) and x for x in tc) \
            or "{tests}" not in tc:
        problems.append(f"test_command must be a fixed argv list containing '{{tests}}': {tc!r}")
    elif not any("pytest" in x for x in tc):
        problems.append(f"test_command must invoke pytest: outcomes are judged from pytest's "
                        f"--junitxml only, so {tc!r} can never reach the gate")
    for key, lo in (("max_rounds", 1), ("qwen_cap", 1), ("reserve", 0),
                    ("agent_timeout", 1), ("test_timeout", 1)):
        value = spec.get(key, {"max_rounds": 2, "qwen_cap": 8, "reserve": 1,
                               "agent_timeout": 1800, "test_timeout": 120}[key])
        if not isinstance(value, int) or isinstance(value, bool) or value < lo:
            problems.append(f"{key} must be an int >= {lo}, got {value!r}")
    cap, res = spec.get("qwen_cap", 8), spec.get("reserve", 1)
    if all(isinstance(v, int) and not isinstance(v, bool) for v in (cap, res)) \
            and res >= cap:
        problems.append(f"reserve ({res}) must be < qwen_cap ({cap}): with no headroom "
                        "the preflight pool check can never pass")
    for key in ("coder_model", "designer_model", "test_reviewer_model"):
        if key in spec and spec[key] is not None \
                and (not isinstance(spec[key], str) or not spec[key].strip()):
            problems.append(f"{key} must be a non-empty string, got {spec[key]!r}")
    return problems


def paseo_ls():
    rc, out, err = run_guarded(["paseo", "ls", "-g", "--json"])
    if rc != 0:
        raise Pause(f"cannot list agents (paseo ls -g): {tail_text(err, 5) or rc}")
    data = json_of(out, "paseo ls output")
    return data.get("agents", []) if isinstance(data, dict) else data


def preflight(job):
    spec = job["spec"]
    if job.get("base_sha") is None:  # pinned at first resolution; never re-moved
        job["base_sha"] = git(spec["repo"], "rev-parse", "--verify",
                              str(spec["base"]) + "^{commit}")
    if job.get("contract") is None:  # pinned once; later reads never touch the checkout
        try:
            # NULs cannot ride argv: the pinned text goes into every spawn prompt
            job["contract"] = Path(spec["repo"], spec["contract_file"]).read_text(
                encoding="utf-8", errors="replace").replace("\x00", "")
        except OSError as exc:
            raise Pause(f"contract file {spec['contract_file']} is unreadable: {exc}")
    if not shutil.which("prlimit") and not spec.get("allow_no_prlimit"):
        raise Pause("prlimit is not on PATH: tests would run WITHOUT CPU/address-space "
                    "limits; install prlimit, or set \"allow_no_prlimit\": true to accept")
    # real `paseo ls -g --json` keys (verified): id/shortId/name/provider/status/cwd
    running = [a for a in paseo_ls() if a.get("status") == "running" and "qwen" in str(a.get("provider", "")).lower()]
    room = int(spec["qwen_cap"]) - int(spec["reserve"])
    if len(running) >= room:
        raise Pause(f"refusing to start: {len(running)} Qwen agents running, "
                    f"cap({spec['qwen_cap']}) - reserve({spec['reserve']}) = {room}")
    job["preflight_ok"] = True


def ensure_preflight(job):
    # re-runs the safety gates on every resume until preflight_ok is set;
    # returns an exit code, or None to continue
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
    # pinned into job.json at preflight: the contract file is usually untracked
    # scratch, so it is read from the checkout ONCE, never from the base commit
    return str(job.get("contract", "(contract not pinned)"))


def branch_name(job, role):
    return f"ac/{job['task_id']}/{role}"


def designer_prompt(job):
    cf = job["spec"].get("cases_file", f"tests/{job['task_id']}.cases.json")
    return (
        f"You are the BLIND test designer for task {job['task_id']}. Write no product "
        f"code.\nContract:\n{contract_text(job)}\nRules:\n"
        f"- Write tests ONLY under: {', '.join(job['spec']['allowed_test_paths'])}. "
        f"Never edit anything else (one exception: your progress log, below).\n- Never "
        f"look at other branches, other worktrees, or their history (no `git log --all`). "
        f"You are blind to the implementation.\n- Your shell already starts in your own "
        f"worktree. Use RELATIVE paths only. Never cd to an absolute path and never touch "
        f"other worktrees.\n- Write your short progress log under in-prog-logs/"
        f"{job['task_id']}-designer.md; that path is allowed for you.\n- Commit your work "
        f"on the current branch.\n- Write {cf} mapping each pytest "
        f'node id to {{"expected_on_base": "pass"|"fail", "requirement": "one line"}}. '
        f'"pass" = a control that must already pass on the OLD code; "fail" = new '
        f'behavior the change must bring.')


def coder_prompt(job):
    return (
        f"You are the coder for task {job['task_id']}. Implement the contract below.\n"
        f"Contract:\n{contract_text(job)}\nRules:\n- Touch ONLY files matching: "
        f"{', '.join(job['spec']['allowed_code_paths'])}.\n- Do NOT write the acceptance "
        f"tests; a separate designer owns them.\n- Your shell already starts in your own "
        f"worktree. Use RELATIVE paths only. Never cd to an absolute path and never touch "
        f"other worktrees.\n- Write your short progress log under in-prog-logs/"
        f"{job['task_id']}-coder.md; that path is allowed for you.\n- Run your own quick "
        f"checks, then commit on the current branch.")


def review_prompt(job):
    return (
        f"Review the tests in this worktree against the contract (author: a blind "
        f"designer).\nContract:\n{contract_text(job)}\nChecklist: assertions match the "
        f"CONTRACT and real CLI behavior; every declared control really passes on the "
        f"base commit; every intended red fails for the right reason; the tests do not "
        f"accidentally target another change.\nWrite your findings first, then END your "
        f'reply with exactly one line: "VERDICT: APPROVE" or "VERDICT: CHANGES REQUESTED".')


def base_env(job):
    return {"PATH": os.environ.get("PATH", ""), "HOME": job["jobdir"], "LANG": "C.UTF-8"}


def agent_cwd(job, agent_id):
    for a in paseo_ls():
        if a.get("id") == agent_id and a.get("cwd"):
            return os.path.expanduser(a["cwd"])  # real cwd can start with ~
    raise Pause(f"agent {agent_id} reports no worktree path (cwd) in paseo ls output")


def check_permits(job):
    rc, out, err = run_guarded(["paseo", "permit", "ls", "--json"])
    if rc != 0:
        raise Pause(f"cannot list pending permits (paseo permit ls rc={rc}): "
                    f"{tail_text(err, 3)}")
    data = json_of(out, "paseo permit ls output")
    entries = data
    if isinstance(entries, dict):
        entries = entries.get("permits", [])
    if isinstance(entries, dict):
        entries = list(entries.values())
    if not isinstance(entries, list):
        return  # malformed payload: never crash, never pause on it
    ids = {str(i) for i in (job.get("coder_agent"), job.get("designer_agent"),
                            *(job.get("reviewers") or {}).values()) if i}

    def relates(e):  # permit entry keys UNVERIFIED upstream: id-ish fields
        vals = {str(e[k]) for k in ("id", "agentId", "agent", "shortId") if e.get(k)}
        # one-way tolerance: the permit id may EXTEND a job id (daemon-suffixed),
        # or match on a 7+ char short id; never attribute a SHORTER foreign id
        return any(v == i or v.startswith(i)
                   or (len(v) >= 7 and len(i) >= 7 and v[:7] == i[:7])
                   for v in vals for i in ids)
    hit = sorted(str(e.get("id") or e.get("agentId") or e.get("agent") or e)
                 for e in entries if isinstance(e, dict) and relates(e))
    if hit:
        raise Pause(f"permission prompt pending for job agents: {hit}")


def record_turn(job, role, rc, out, err):
    if rc != 0:
        raise Pause(f"{role} agent turn failed (rc={rc}, quota/usage?): {tail_text(err, 5)}")
    data = last_json_of(out, f"{role} run result")  # real run --json: running doc, then final
    status = data.get("status")
    if status == "permission":
        raise Pause(f"{role} agent is waiting on a permission prompt; approve/deny it with "
                    "`paseo permit`, then `resume`")
    if status != "completed":
        raise Pause(f"{role} agent turn ended with status {status!r}: {tail_text(out, 5)}")
    agent_id = data.get("agentId")
    if not agent_id:
        raise Pause(f"{role} agent turn reported no agentId: {tail_text(out, 3)}")
    cwd = agent_cwd(job, agent_id)  # derive BEFORE mutating: a Pause leaves the job untouched
    job[f"{role}_agent"] = agent_id
    job[f"{role}_cwd"] = cwd
    save_job(job)  # ids survive a hard crash mid-loop, so resume adopts them


def send_to(job, agent_key, message):
    agent_id = job.get(agent_key)
    if not agent_id:
        raise Pause(f"no recorded agent for {agent_key}; refusing to guess")
    rc, out, err = run_guarded(["paseo", "send", agent_id, "--json", message],
                                timeout=int(job["spec"].get("agent_timeout", 1800)))
    if rc != 0:
        raise Pause(f"send to {agent_key} failed (rc={rc}): {tail_text(err, 5)}")
    status = last_json_of(out, "send result").get("status")  # send streams like run
    if status != "completed":
        raise Pause(f"send to {agent_key} ended with status {status!r}")
    check_permits(job)


def spawn_agent(job, role, model, base, prompt):
    argv = ["paseo", "run", "--new-workspace", "worktree", "--worktree-mode", "branch-off",
            "--new-branch", branch_name(job, role), "--base", base, "--provider", model,
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


def wait_for_agent(job, role):
    # rc=0 proves NOTHING: real `paseo wait` exits 0 printing status "error"
    # ("Agent not found") as readily as "idle" -- the JSON status is the signal
    tmo = int(job["spec"].get("agent_timeout", 1800))
    rc, out, err = run_guarded(["paseo", "wait", job[f"{role}_agent"], "--json",
                                "--timeout", str(tmo)], timeout=tmo + 30)  # outlive the CLI
    data = last_json_of(out, f"{role} wait result")
    if data.get("status") != "idle":
        aid = job[f"{role}_agent"]
        raise Pause(f"{role} agent {aid} is not idle: paseo wait reports "
                    f"{data.get('status')!r} {tail_text(str(data.get('message', '')), 3)}")


def live_ids():
    # real ls statuses (verified): running / idle / closed / error -- closed+error are dead
    return {str(a.get("id")) for a in paseo_ls()
            if a.get("status") not in (None, "closed", "error")}


def stop_job_agents(job):
    # killing the `paseo run` client does NOT stop the agent; stop the job's
    # agents by title, EXCEPT roles whose id is already recorded (= healthy)
    known = ({str(job.get(f"{r}_agent")) for r in ("coder", "designer", "reviewer")}
             | {str(v) for v in (job.get("reviewers") or {}).values()})
    prefix = f"AgentCoder {job['task_id']} "[:60]  # ls `name` = title, truncated ~60
    for e in paseo_ls():
        name, aid = str(e.get("name", "")), str(e.get("id"))
        if name.startswith(prefix) and aid not in known:
            run_guarded(["paseo", "stop", aid])
            job.setdefault("stopped_agents", {})[name.rsplit(" ", 1)[-1]] = aid


def do_spawn(job):
    spec = job["spec"]
    live = live_ids()
    for role in ("coder", "designer"):  # resume: a recorded id that died must respawn
        if job.get(f"{role}_agent") and str(job[f"{role}_agent"]) not in live:
            job.pop(f"{role}_agent", None), job.pop(f"{role}_cwd", None)
    for role in ("coder", "designer"):  # a half-recorded live id (no cwd): re-derive it
        if job.get(f"{role}_agent") and not job.get(f"{role}_cwd"):
            job[f"{role}_cwd"] = agent_cwd(job, job[f"{role}_agent"])
            save_job(job)
    need = [r for r in ("coder", "designer") if not job.get(f"{r}_agent")]
    if need:
        prompts = {"coder": coder_prompt(job), "designer": designer_prompt(job)}
        procs = {}
        for role in need:
            model = spec.get(f"{role}_model") or DEFAULT_MODEL
            argv = resolve(["paseo", "run", "--new-workspace", "worktree", "--worktree-mode",
                            "branch-off", "--new-branch", branch_name(job, role),
                            "--base", job["base_sha"], "--provider", model, "--title",
                            f"AgentCoder {job['task_id']} {role}", "--json", prompts[role]])
            try:
                procs[role] = subprocess.Popen(argv, cwd=spec["repo"], stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE, text=True,
                                               errors="replace")
            except OSError as exc:  # same cleanup as the other spawn failures
                _kill_all(procs)
                stop_job_agents(job)
                raise Pause(f"cannot launch paseo ({role} spawn): {exc}")
        for role, proc in procs.items():
            try:
                out, err = proc.communicate(timeout=int(spec.get("agent_timeout", 1800)))
            except subprocess.TimeoutExpired:
                _kill_all(procs)
                stop_job_agents(job)
                raise Pause(f"{role} agent turn timed out")
            try:
                record_turn(job, role, proc.returncode, out, err)
            except Pause:
                _kill_all(procs)
                stop_job_agents(job)
                raise
    for role in ("coder", "designer"):  # every recorded live role must be idle to proceed
        if job.get(f"{role}_agent"):
            wait_for_agent(job, role)
    check_permits(job)


def path_matches(p, g):
    if not isinstance(p, str) or not isinstance(g, str):
        return False
    g = g.rstrip("/")
    plain = not any(ch in g for ch in "*?[")
    return (p == g or p.startswith(g + "/")) if plain else fnmatch.fnmatch(p, g)


LOGS_PREFIX = "in-prog-logs/"  # AGENTS.md progress logs: always allowed, both agents


def scope_check(job, sha, globs, who):
    # UNFILTERED, --no-renames: a DELETED file is scope dirt too, and git splits a
    # rename into delete-old + add-new, so BOTH paths of a rename must clear the globs
    changed = [p for p in git(job["spec"]["repo"], "diff", "--name-only", "--no-renames",
                              job["base_sha"], sha).splitlines() if p]
    bad = sorted(p for p in changed if not p.startswith(LOGS_PREFIX)
                 and not any(path_matches(p, g) for g in globs))
    if bad:
        raise OutOfScope(who, bad)
    return changed


def checkout_paths(job, sha):
    # files that EXIST at sha (ACMR): `git checkout <sha> -- <path>` on a
    # deleted/renamed-away path errors forever; the scope check above uses the
    # unfiltered list on purpose -- deletions must not hide from it
    return [p for p in git(job["spec"]["repo"], "diff", "--name-only", "--diff-filter=ACMR",
                           job["base_sha"], sha).splitlines() if p]


def scope_feedback(job, exc, agent_key, round_key, rnd, sha):
    # ONE feedback round per offending sha (persisted: a resume can't loop); it
    # counts against max_rounds
    key = f"scope_sent@{agent_key}@{sha[:9]}"
    if job.get(key) or rnd >= int(job["spec"]["max_rounds"]):
        raise Escalate(f"{exc.reason} (scope feedback round already used)")
    send_to(job, agent_key,
            f"Revert these paths; they are outside your allowed globs: {exc.paths}. "
            "Keep only work under your allowed paths, commit on your branch.")
    job[key] = True  # persisted only AFTER the send: a failed send must retry on resume
    job[round_key] = rnd + 1
    save_job(job)


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
        test_sha = job.get("test_sha") or git(job["designer_cwd"], "rev-parse", "HEAD")
        job["test_sha"] = test_sha
        key = f"{rnd}@{test_sha[:8]}"  # sha-scoped: re-reviews get a fresh reviewer
        if reviewers.get(key) and str(reviewers[key]) not in live_ids():
            reviewers.pop(key)  # recorded reviewer died: respawn, not a permanent pause
        if not reviewers.get(key):
            # a recorded reviewer id that died is respawned; one saved mid-crash (by
            # record_turn, before the move into `reviewers`) is adopted, not respawned
            if not job.get("reviewer_agent") or str(job["reviewer_agent"]) not in live_ids():
                spawn_agent(job, f"review-r{rnd}-{test_sha[:6]}", spec["test_reviewer_model"],
                            test_sha, review_prompt(job))
            reviewers[key] = job.pop("reviewer_agent")
            job.pop("reviewer_cwd", None)
            save_job(job)
        rc, out, err = run_guarded(["paseo", "logs", reviewers[key], "--tail", "60"])
        if rc != 0:
            raise Pause(f"paseo logs for reviewer {reviewers[key]} failed (rc={rc}): "
                        f"{tail_text(err, 3)}")
        # logs include [Thought] blocks: only the FINAL non-empty line can be the verdict
        last = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()), "")
        m = re.fullmatch(r"VERDICT:\s*(APPROVE|CHANGES REQUESTED)", last)
        if not m:
            raise Pause(f"reviewer round {rnd} ends on {last[:80]!r}, not a VERDICT line; "
                        "refusing to guess (thought-block text never counts)")
        check_permits(job)
        if m.group(1) == "APPROVE":
            job["test_review"] = "APPROVE"
            job["review_round"] = rnd
            job["reviewed_test_sha"] = test_sha
            return
        job["test_review"] = f"CHANGES REQUESTED (round {rnd})"
        send_to(job, "designer_agent",
                f"Test review round {rnd} requested changes; the reviewer said:\n{tail_text(out)}\n"
                "Fix the tests on your branch, keep them blind, commit.")
        rnd += 1
        job["review_round"] = rnd
        job["test_sha"] = None
        save_job(job)


def expand_tests(globs, wt):
    found = sorted({p for g in globs for p in glob.glob(g, root_dir=wt, recursive=True)
                    if Path(wt, p).is_dir() or p.endswith(".py")})  # pytest can't take data files
    if not found:
        raise Pause(f"allowed_test_paths {globs} matched nothing in the worktree; "
                    "refusing to hand pytest an empty file list")
    return found


def junit_node(tc, wt):
    parts = [p for p in tc.get("classname", "").split(".") if p]
    for k in range(len(parts), 0, -1):  # longest dotted prefix naming a real .py
        mod = "/".join(parts[:k])
        if Path(wt, mod + ".py").is_file():
            rest = "".join(f"::{p}" for p in parts[k:])
            return f"{mod}.py{rest}::{tc.get('name', '')}"
    f = tc.get("file") or tc.get("classname", "").replace(".", "/") + ".py"
    return f"{f}::{tc.get('name', '')}"


def junit_outcomes(xml, wt):
    outcomes = {}
    try:
        root = ET.parse(xml).getroot()
    except (OSError, ET.ParseError):
        return outcomes
    for tc in root.iter("testcase"):
        kids = {c.tag for c in tc}
        outcomes[junit_node(tc, wt)] = ("SKIPPED" if "skipped" in kids else "FAILED" if "failure" in kids
                                        else "ERROR" if "error" in kids else "PASSED")
    return outcomes


def run_tests(job, wt):
    argv = []
    globs = job["spec"]["allowed_test_paths"]
    for part in job["spec"].get("test_command", DEFAULT_TC):
        argv.extend(expand_tests(globs, wt) if part == "{tests}" else [part])
    xml = Path(job["jobdir"]) / f"junit-{Path(wt).name}.xml"
    is_pytest = any("pytest" in part for part in argv)
    if is_pytest:
        argv += ["--junitxml", str(xml), "--rootdir", str(wt)]
    xml.unlink(missing_ok=True)
    cmd = (["prlimit"] + LIM[1:]) if shutil.which("prlimit") else []
    cmd += argv
    tmo = int(job["spec"].get("test_timeout", 120))
    try:
        rc, out, err = run_cmd(cmd, cwd=wt, env=base_env(job), timeout=tmo)
    except subprocess.TimeoutExpired:
        raise Pause(f"test command timed out after {tmo}s; nothing was judged "
                    f"and no agent was fed this output")
    outcomes = junit_outcomes(xml, wt) if is_pytest else {}
    if rc not in (0, 1, 5) and not outcomes:
        raise Pause(f"test command exited {rc} with no per-test outcomes: "
                    f"{tail_text(out + err, 8)}")
    return rc, out + err, outcomes


def load_cases(job, test_sha):
    cf = job["spec"].get("cases_file", f"tests/{job['task_id']}.cases.json")
    raw = git(job["spec"]["repo"], "show", f"{test_sha}:{cf}", check=False)
    try:
        cases = json_of(raw, "cases.json") if raw else None
    except Pause as exc:
        raise Escalate(f"{cf} in frozen test commit {test_sha[:9]} is not valid JSON: "
                       f"{exc.reason}")
    if not isinstance(cases, dict) or not cases:
        raise Escalate(f"no usable {cf} in frozen test commit {test_sha}; "
                       f"designer must declare every test id")
    for test_id, decl in cases.items():
        if not isinstance(decl, dict) or decl.get("expected_on_base") not in ("pass", "fail"):
            raise Escalate(f"cases.json entry {test_id!r} must be an object with "
                           f'expected_on_base "pass"/"fail", got {decl!r}')
    return cases


def compare_cases(cases, outcomes):
    problems = []
    for test_id, decl in sorted(cases.items()):
        want, got = decl["expected_on_base"], outcomes.get(test_id, "NOT-COLLECTED")
        if want == "pass" and got != "PASSED":
            problems.append(f"{test_id}: control declared 'pass' but on base it is {got}")
        if want == "fail" and got != "FAILED":
            problems.append(f"{test_id}: declared 'fail' (new behavior) but on base it is "
                            f"{got} — it must FAIL on base to pin the change")
    return problems


def gate_failures(cases, outcomes):
    # every declared id must have been collected and PASSED; anything else is red
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


def apply_removals(job, wt, test_sha):
    # tests the designer DELETED (or renamed away) still exist at base/coder shas:
    # without this they run in the temp worktrees and can keep a candidate red forever
    for p in git(job["spec"]["repo"], "diff", "--name-only", "--no-renames",
                 "--diff-filter=D", job["base_sha"], test_sha, check=False).splitlines():
        if p:
            git(wt, "rm", "-q", "-f", "--", p, check=False)


def do_execute(job):
    spec = job["spec"]
    rnd = int(job.get("execute_round", 0))
    while True:
        test_sha = job["test_sha"] = git(job["designer_cwd"], "rev-parse", "HEAD")
        if spec.get("test_reviewer_model") and test_sha != job.get("reviewed_test_sha"):
            return "test_review"  # designer committed new tests: re-gate via review
        try:
            scope_check(job, test_sha, spec["allowed_test_paths"], "test designer")
        except OutOfScope as exc:
            scope_feedback(job, exc, "designer_agent", "execute_round", rnd, test_sha)
            rnd += 1
            job["test_sha"] = None
            continue
        test_paths = [p for p in checkout_paths(job, test_sha)
                      if not p.endswith(".cases.json") and p != spec["cases_file"]]
        if not test_paths:
            raise Escalate(f"test designer commit {test_sha[:9]} adds no files "
                           f"under {spec['allowed_test_paths']}")
        cases = load_cases(job, test_sha)
        if not any(d["expected_on_base"] == "fail" for d in cases.values()):
            if rnd >= int(spec["max_rounds"]):
                raise Escalate(f"{spec['cases_file']} still has no 'fail' case after {rnd} "
                               "round(s): tests that cannot fail on the base prove nothing")
            send_to(job, "designer_agent",
                    f"{spec['cases_file']} declares zero tests with expected_on_base \"fail\": "
                    "at least one test must FAIL on the base commit — it is the proof the "
                    "change is needed. Add it (never weaken the rest), commit, done.")
            rnd += 1
            job["execute_round"] = rnd
            job["test_sha"] = None
            save_job(job)
            continue
        wt = ensure_worktree(job, "base-wt", job["base_sha"])
        try:
            git(wt, "checkout", "-f", test_sha, "--", *test_paths)
            apply_removals(job, wt, test_sha)
            rc, out, outcomes = run_tests(job, wt)
        finally:
            drop_worktree(job, wt)
        problems = compare_cases(cases, outcomes)
        job["execute_last"] = {"round": rnd, "rc": rc, "problems": problems,
                               "tail": tail_text(out, 30)}
        if not problems:
            job["test_paths"] = test_paths
            job["controls"] = sum(1 for d in cases.values() if d["expected_on_base"] == "pass")
            job["intended_reds"] = len(cases) - job["controls"]
            job["execute_round"] = rnd
            return
        if rnd >= int(spec["max_rounds"]):
            raise Escalate(f"tests still mismatch cases.json after {rnd} round(s): "
                           f"{'; '.join(problems[:6])}")
        send_to(job, "designer_agent",
                "Executor ran the frozen tests against the BASE commit and the outcomes "
                "contradict " + spec["cases_file"] + ":\n" + "\n".join(f"- {p}" for p in problems)
                + "\nOutput tail:\n" + tail_text(out) + "\nFix the tests (a control that "
                "fails on base, a 'fail' case that passes on base = TEST bug). Never edit it.")
        rnd += 1
        job["execute_round"] = rnd
        job["test_sha"] = None
        save_job(job)


def record_round(job, rnd, rc, failed):
    # replace-by-round: a resume re-runs the round, so keep exactly one entry
    job["candidate_results"] = [
        r for r in job.get("candidate_results", []) if r.get("round") != rnd
    ] + [{"round": rnd, "rc": rc, "failed": failed}]


def do_candidate(job):
    spec = job["spec"]
    rnd = int(job.get("candidate_round", 0))
    cases = load_cases(job, job["test_sha"])
    while True:
        coder_sha = git(job["coder_cwd"], "rev-parse", "HEAD")
        try:
            scope_check(job, coder_sha, spec["allowed_code_paths"], "coder")
        except OutOfScope as exc:
            scope_feedback(job, exc, "coder_agent", "candidate_round", rnd, coder_sha)
            rnd += 1
            continue
        wt = ensure_worktree(job, f"cand-wt-{rnd}", coder_sha)
        try:
            git(wt, "checkout", "-f", job["test_sha"], "--", *job["test_paths"])
            apply_removals(job, wt, job["test_sha"])
            rc, out, outcomes = run_tests(job, wt)
        finally:
            drop_worktree(job, wt)
        failed = gate_failures(cases, outcomes)
        if rc == 5:
            failed = failed or ["no tests were collected (exit 5)"]
        if rc == 0 and not failed:
            job["coder_sha"] = coder_sha
            record_round(job, rnd, rc, [])
            job["candidate_round"] = rnd
            return
        record_round(job, rnd, rc, failed)
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
    if job.get("coder_sha") == job.get("base_sha"):
        raise Escalate("no coder commit: the candidate sha IS the base sha; a PR "
                       "without code changes proves nothing")
    wt = job["coder_cwd"]
    head = git(wt, "rev-parse", "HEAD")
    moved = [p for p in git(wt, "diff", "--name-only", "HEAD~1", "HEAD", check=False)
             .splitlines() if p]
    frozen = job.get("test_paths") or []
    if (head != job["coder_sha"] and head != job.get("test_landed_sha")
            and git(wt, "rev-parse", "HEAD~1", check=False) == job["coder_sha"]
            and moved and all(p in frozen for p in moved)
            and all(git(wt, "rev-parse", f"HEAD:{p}", check=False)
                    == git(wt, "rev-parse", f"{job['test_sha']}:{p}", check=False)
                    for p in moved)):
        job["test_landed_sha"] = head  # land committed, then died before saving: adopt it
        save_job(job)
    if head != job["coder_sha"] and head != job.get("test_landed_sha"):
        return "candidate"  # coder moved: re-gate the new head, land gates only
    dirty = git(wt, "status", "--porcelain", "-z", "--untracked-files=no")
    if dirty:
        # -z: raw paths (no C-quoting of spaces), NUL-separated; for staged
        # renames/copies the source path follows as its own record
        records = [r for r in dirty.split("\0") if r]
        paths, skip = [], False
        for rec in records:
            if skip:
                skip = False
                continue
            paths.append(rec[3:])
            if rec[:1] in ("R", "C"):
                skip = True
        if [p for p in paths if p not in job["test_paths"]]:
            raise Escalate("coder worktree has uncommitted/staged changes outside the frozen "
                           f"test paths; refusing to sweep them:\n{tail_text(dirty, 15)}")
        # changes inside test_paths: land's own interrupted checkout; redo it idempotently
        git(wt, "reset", "-q", "--", *job["test_paths"], check=False)
        git(wt, "checkout", "--", *job["test_paths"], check=False)
    git(wt, "checkout", job["test_sha"], "--", *job["test_paths"])
    if git(wt, "diff", "--cached", "--name-only", check=False):
        try:
            git(wt, "-c", "user.name=agentcoder", "-c", "user.email=noreply@refdes.local",
                "commit", "--author", "agentcoder <noreply@refdes.local>",
                "-m", f"test: acceptance tests for {job['task_id']} (agentcoder)",
                "-m", co_trailer(job), "--", *job["test_paths"])
        except Pause:  # driver's own staged files must not read as coder dirt on resume
            git(wt, "reset", "-q", "--", *job["test_paths"], check=False)
            raise
        # driver-recorded sha (job.json is not agent-writable): identifies the
        # driver's own test commit as landable on resume, without string matching
        job["test_landed_sha"] = git(wt, "rev-parse", "HEAD")
        save_job(job)
    git(wt, "push", "-u", "origin", f"HEAD:refs/heads/{branch_name(job, 'coder')}", timeout=300)
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
            raise Escalate(f"PR(s) {[(p.get('number'), p.get('state')) for p in existing]} exist "
                           f"for {branch_name(job, 'coder')} and none is adoptable; resolve manually")
        if hit:
            job["pr_number"] = int(hit["number"])
            save_job(job)
            print(f"PR: {job['pr_number']} (adopted existing)", file=sys.stderr)
        else:
            body = Path(job["jobdir"], "report.md")
            write_report(job, landing=True)
            rc, out, err = run_guarded(["gh", "pr", "create", "--title", str(job["spec"]["title"]),
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
            print(f"PR: {job['pr_number']}", file=sys.stderr)  # JSON summary owns stdout
        write_report(job, landing=True)  # refresh report.md; the final summary prints once


def write_report(job, landing=False):
    rows = "\n".join(
        f"| {r['round']} | {r['rc']} | {', '.join(r['failed']) or '-'} |"
        for r in job.get("candidate_results", []))
    lines = [
        f"# agentcoder report — {job['task_id']}", "",
        f"- status: **{job.get('status', 'running')}**"
        + (f" — {job['reason']}" if job.get("reason") else ""),
        f"- base SHA: `{job.get('base_sha')}`", f"- frozen test SHA: `{job.get('test_sha')}`",
        f"- coder SHA: `{job.get('coder_sha')}`", f"- PR: {job.get('pr_number') or '-'}",
        f"- controls: {job.get('controls')} green, reds: {job.get('intended_reds')}",
        f"- test review: {job.get('test_review', 'not reached')}", "",
        "## Contract (summary)", "",
        tail_text(contract_text(job), 20) if job.get("spec", {}).get("contract_file") else "-",
        "", "## Candidate results per round", "",
        "| round | exit | failing tests |", "| --- | --- | --- |",
        rows or "| - | - | not reached |",
    ]
    Path(job["jobdir"], "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if landing:
        return
    summary = {"job": job["jobdir"], "task_id": job["task_id"], "status": job.get("status"),
               "reason": job.get("reason"), "base_sha": job.get("base_sha"),
               "test_sha": job.get("test_sha"), "code_sha": job.get("coder_sha"),
               "controls_green": job.get("controls"), "intended_reds": job.get("intended_reds"),
               "test_review": job.get("test_review"), "pr_number": job.get("pr_number"),
               "candidate_results": job.get("candidate_results", [])}
    print(json.dumps(summary, indent=1, sort_keys=True))


def do_report(job):
    job.update(status="ready-for-human-gate", reason=None)


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
        print("usage: agentcoder.py run SPEC.json [JOBDIR] | resume JOBDIR | status JOBDIR")
        return EXIT_ERROR
    cmd, arg = argv[0], argv[1] if len(argv) > 1 else ""
    if cmd in ("resume", "status") and not arg:  # never read a stray ./job.json
        print("usage: agentcoder.py resume JOBDIR | status JOBDIR")
        return EXIT_ERROR
    try:
        if cmd == "run":
            try:
                raw = Path(arg).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                exit_json("error", f"spec unreadable: {exc}")
                return EXIT_ERROR
            spec = json_of(raw, "spec file")
            problems = validate_spec(spec)
            if problems:
                exit_json("invalid-spec", "; ".join(problems))
                return EXIT_ERROR
            for key, value in (("test_command", DEFAULT_TC), ("coder_model", DEFAULT_MODEL),
                               ("designer_model", DEFAULT_MODEL), ("max_rounds", 2),
                               ("qwen_cap", 8), ("reserve", 1),
                               ("cases_file", f"tests/{spec['task_id']}.cases.json")):
                spec.setdefault(key, value)
            default = Path(spec["repo"]) / ".scratch" / "agentcoder" / spec["task_id"]
            jobdir = Path(argv[2] if len(argv) > 2 else default).resolve()
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
                keep = ("task_id", "phase", "status", "reason", "base_sha", "test_sha", "coder_sha",
                        "pr_number", "test_review", "execute_round", "review_round", "candidate_round")
                print(json.dumps({k: job.get(k) for k in keep}, indent=1, sort_keys=True))
                return EXIT_OK
            if job.get("phase") == "done":  # completed: replay the summary, never clobber report.md
                print(json.dumps({"status": job.get("status"), "reason": job.get("reason"),
                                  "pr_number": job.get("pr_number")}, sort_keys=True))
                return {"ready-for-human-gate": EXIT_OK, "escalated": EXIT_ESCALATED}.get(
                    job.get("status"), EXIT_ERROR)
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
