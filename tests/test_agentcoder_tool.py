"""Tests for tools/agentcoder/agentcoder.py — no network, no real paseo/gh.

The fake paseo executable records every call and simulates agents by
committing files into real temp git worktrees; the fake gh records calls and
prints a PR URL.  The driver runs in-process so tests can simulate a kill by
raising from inside the module's own helpers.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="agentcoder drives a Linux paseo host: fakes use shebang scripts, fcntl "
           "and the driver's preflight gate requires prlimit, which is Linux-only")

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "agentcoder_tool", ROOT / "tools" / "agentcoder" / "agentcoder.py")
agentcoder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agentcoder)


@pytest.fixture(autouse=True, scope="module")
def _git_identity():
    """No test may depend on the machine's git identity: runners have none."""
    old = dict(os.environ)
    os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                      GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                      GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    yield
    os.environ.clear()
    os.environ.update(old)

BASE_APP = "def add(a, b):\n    return a\n"
FIX_APP = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
TEST_FILE = (
    "import os, sys\n"
    "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
    "import app\n\n\n"
    "def test_control():\n"
    "    assert callable(app.add)\n\n\n"
    "def test_sub():\n"
    "    assert app.sub(1, 2) == -1\n"
)
CASES_OK = json.dumps({
    "tests/test_add.py::test_control":
        {"expected_on_base": "pass", "requirement": "control passes on old code"},
    "tests/test_add.py::test_sub":
        {"expected_on_base": "fail", "requirement": "sub() is added by the change"},
})
CASES_BUG = json.dumps({
    "tests/test_add.py::test_control":
        {"expected_on_base": "fail", "requirement": "mislabelled control"},
    "tests/test_add.py::test_sub":
        {"expected_on_base": "fail", "requirement": "sub() is added by the change"},
})
CASES_A = json.dumps({
    "tests/a/test_add.py::test_control":
        {"expected_on_base": "pass", "requirement": "control passes on old code"},
    "tests/a/test_add.py::test_sub":
        {"expected_on_base": "fail", "requirement": "sub() is added by the change"},
})
_HEADER = (
    "import os, sys\nimport pytest\n"
    "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
    "import app\n\n\n"
    "def test_control():\n    assert callable(app.add)\n\n\n")
TESTS_SKIP = _HEADER + (
    "@pytest.mark.skip(reason=\"hide\")\n"
    "def test_sub():\n    assert app.sub(1, 2) == -1\n")
TESTS_MISSING = _HEADER + "def test_other():\n    assert True\n"
TESTS_XFAIL = _HEADER + (
    "@pytest.mark.xfail(reason=\"hide\")\n"
    "def test_sub():\n    assert app.sub(1, 2) == -1\n")

PASEO_FAKE = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys, time

S = json.load(open(os.environ["FAKESCENARIO"]))
ARGS = sys.argv[1:]
os.makedirs(S["logdir"], exist_ok=True)
import fcntl
_LOCKFD = open(os.path.join(S["logdir"], "lock"), "w")
fcntl.flock(_LOCKFD, 2)
with open(os.path.join(S["logdir"], "paseo-calls.log"), "a") as fh:
    fh.write(json.dumps(ARGS) + "\n")
STATE_PATH = os.path.join(S["logdir"], "agents.json")
state = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {"seq": 0, "agents": {}}

def save():
    json.dump(state, open(STATE_PATH, "w"))

def git(*a):
    subprocess.run(["git", "-C", S["repo"], *a], capture_output=True, text=True)

def write_commit(ws, files, msg):
    for p, c in files.items():
        fp = os.path.join(ws, p)
        if c is None:  # a committed DELETION (scope guards must see it)
            if os.path.exists(fp):
                os.remove(fp)
            continue
        os.makedirs(os.path.dirname(fp) or ws, exist_ok=True)
        open(fp, "w").write(c)
    subprocess.run(["git", "-C", ws, "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", ws, "-c", "user.name=fake", "-c", "user.email=f@x",
                    "commit", "-m", msg], capture_output=True)

def flag(name, dflt=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else dflt

cmd = ARGS[0]
FLAGS = {  # flags the REAL CLI accepts, verified from `paseo <cmd> --help`
    "run": {"-d", "--background", "--title", "--provider", "--model", "--thinking", "--mode",
            "--new-workspace", "--worktree-mode", "--worktree-slug", "--new-branch", "--base",
            "--branch", "--pr-number", "--forge", "--workspace", "--image", "--cwd", "--env",
            "--label", "--wait-timeout", "--output-schema", "--json", "--host", "--home",
            "-o", "--format", "-q", "--no-headers", "--no-color", "-h", "--help"},
    "send": {"--prompt", "--prompt-file", "--image", "--no-wait", "--json", "--host",
             "--home", "-o", "--format", "-q", "--no-headers", "--no-color"},
    "wait": {"--timeout", "--json", "--host", "--home", "-o", "--format", "-q", "--no-headers",
             "--no-color"},
    "stop": {"--all", "--cwd", "--json", "--host", "--home", "-o", "--format", "-q",
             "--no-headers", "--no-color"},
    "logs": {"-f", "--follow", "--tail", "--filter", "--since", "--host", "--home", "-o",
             "--format", "-q", "--no-headers", "--no-color"},
    "ls": {"-a", "--all", "-g", "--global", "--label", "--thinking", "--json", "--host",
           "--home", "-o", "--format", "-q", "--no-headers", "--no-color"},
}
if cmd in FLAGS:
    for a in ARGS[1:]:
        if a.startswith("-"):
            if a == "--model":
                sys.exit("MISSING_PROVIDER: --model alone is not accepted; pass the provider "
                         "string with --provider <provider/model>")
            if a not in FLAGS[cmd]:
                sys.exit("fake paseo: %s has no flag %s" % (cmd, a))
if cmd == "ls":
    def row(k, name, provider, status, cwd):
        return {"id": k, "shortId": k[:7], "name": name, "provider": provider,
                "thinking": "auto", "status": status, "cwd": cwd, "created": "now"}
    rows = [row(k, v.get("title", ""), "opencode/qwenlocal/Qwen3.8-Flash-Next",
                v.get("status", "idle"), v["ws"])
            for k, v in state["agents"].items() if v["ws"]]
    rows += [row("q%d" % i, "busy", "opencode/qwenlocal/Qwen3.8-Flash-Next",
                 "running", "~/busy") for i in range(S.get("running_qwen", 0))]
    rows += [row("o%d" % i, "other", "claude/claude-sonnet-5-5",
                 "running", "~/other") for i in range(S.get("running_other", 0))]
    print(json.dumps(rows))
elif cmd == "permit":
    ids = {}
    for k, v in state["agents"].items():
        ids[v["role"]] = k
    print(json.dumps([{"agentId": ids[r]} for r in S.get("permits", []) if ids.get(r)]))
elif cmd == "wait":
    print(json.dumps(S.get("wait_status") or {"status": "idle"}))
elif cmd == "logs":
    rec = state["agents"].get(ARGS[1], {})
    replies = S.get("review_replies")
    tail = rec.get("role", "r0")
    m = re.match(r"\d+", tail.rsplit("review-r", 1)[-1]) if "review-r" in tail else None
    idx = int(m.group()) if m else 0
    text = replies[idx] if isinstance(replies, list) and idx < len(replies) \
        else S.get("review_reply", "checks fine\nVERDICT: APPROVE")
    print(text)
elif cmd == "run":
    role = flag("--title", "").rsplit(" ", 1)[-1]
    hang = S.get("hang", {})
    if role in hang.get("run", []):
        if S.get("pidfile"):
            open(S["pidfile"], "w").write(str(os.getpid()))
        _LOCKFD.close()  # hang WITHOUT the state lock: sweeps and ls must run
        time.sleep(120)
    if role.startswith("review-r"):
        n = state.get("rfails", 0)
        if n < int(S.get("review_fails", 0)):
            state["rfails"] = n + 1
            save()
            print(json.dumps({"status": "failed"}))
            sys.exit(0)
    ws = None
    if flag("--new-workspace") == "worktree":
        branch = flag("--new-branch")
        ws = os.path.join(S["wtroot"], branch.replace("/", "-"))
        if not os.path.isdir(ws):
            os.makedirs(S["wtroot"], exist_ok=True)
            git("worktree", "add", "-B", branch, ws, flag("--base"))
        files = S.get(role + "_files")
        if files:
            write_commit(ws, files, "fake %s work" % role)
    state["seq"] += 1
    aid = "a%d" % state["seq"]
    state["agents"][aid] = {"role": role, "ws": ws, "sends": 0,
                            "title": flag("--title", "")}
    save()
    if S.get("run_stream"):  # real `paseo run --json` prints a running doc, then the final
        print(json.dumps({"agentId": aid, "status": "running"}))
    print(json.dumps({"agentId": aid,
                      "status": S.get("run_status", {}).get(role, "completed")}))
elif cmd == "send":
    if S.get("hang", {}).get("send"):
        time.sleep(120)
    rec = state["agents"].get(ARGS[1])
    if rec is not None:
        queue = S.get("on_send", {}).get(rec["role"], [])
        n = rec.get("sends", 0)
        if n < len(queue):
            for d in queue[n].get("delete", []):
                fp = os.path.join(rec["ws"], d)
                if os.path.exists(fp):
                    os.remove(fp)
            write_commit(rec["ws"], queue[n]["files"], "fake fix")
        rec["sends"] = n + 1
        save()
    print(json.dumps({"status": "completed"}))
elif cmd == "stop":
    rec = state["agents"].get(ARGS[1])
    if rec is not None:
        rec["status"] = "closed"
        save()
    print(json.dumps({"status": "closed"}))
else:
    sys.exit("fake paseo: unknown " + cmd)
'''

GH_FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys

S = json.load(open(os.environ["FAKESCENARIO"]))
LOG = os.path.join(S["logdir"], "gh-calls.log")
with open(LOG, "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\n")
args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    if S.get("pr_list_fails"):
        sys.exit(1)
    created = S.get("pr_exists")
    if not created and os.path.exists(LOG):
        for line in open(LOG):
            if json.loads(line)[:2] == ["pr", "create"]:
                created = True
    head = S.get("pr_head")
    if head is None:
        br = args[args.index("--head") + 1] if "--head" in args else ""
        p = subprocess.run(["git", "-C", S["repo"], "rev-parse", "--verify", "-q", br],
                           capture_output=True, text=True) if br else None
        head = p.stdout.strip() if p else ""
    row = {"number": 4242, "state": S.get("pr_state", "OPEN"), "headRefOid": head}
    print(json.dumps([row] if created else []))
elif args[:2] == ["pr", "create"]:
    print("https://github.com/fake/repo/pull/4242")
else:
    print("[]")
'''


def gitat(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def build_env(tmp_path, monkeypatch, scenario_overrides=None, spec_overrides=None,
              name="env"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "repo"
    repo.mkdir()
    gitat(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text(BASE_APP)
    (repo / "contract.md").write_text("# Contract\n`add(a, b)` returns the sum.\n")
    gitat(repo, "add", "-A")
    gitat(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    origin = root / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    gitat(repo, "remote", "add", "origin", str(origin))
    gitat(repo, "push", "-q", "-u", "origin", "main")

    logdir = root / "logs"
    logdir.mkdir()
    wtroot = root / "wts"
    wtroot.mkdir()
    scenario = {
        "repo": str(repo), "logdir": str(logdir), "wtroot": str(wtroot),
        "running_qwen": 0,
        "designer_files": {"tests/test_add.py": TEST_FILE,
                           "tests/t1.cases.json": CASES_OK},
        "coder_files": {"app.py": FIX_APP},
    }
    scenario.update(scenario_overrides or {})
    scen_path = root / "scenario.json"
    scen_path.write_text(json.dumps(scenario))

    fake = root / "paseo"
    fake.write_text(PASEO_FAKE)
    fake.chmod(0o755)
    fakegh = root / "gh"
    fakegh.write_text(GH_FAKE)
    fakegh.chmod(0o755)
    monkeypatch.setenv("AGENTCODER_PASEO", str(fake))
    monkeypatch.setenv("AGENTCODER_GH", str(fakegh))
    monkeypatch.setenv("FAKESCENARIO", str(scen_path))

    spec = {
        "task_id": "t1", "title": "add sub()", "repo": str(repo), "base": "main",
        "contract_file": "contract.md", "allowed_code_paths": ["app.py"],
        "allowed_test_paths": ["tests"],
        "test_command": [sys.executable, "-m", "pytest", "-q", "{tests}"],
        "max_rounds": 2, "test_timeout": 60, "agent_timeout": 300,
    }
    spec.update(spec_overrides or {})
    spec_path = root / "spec.json"
    spec_path.write_text(json.dumps(spec))
    jobdir = root / "job"

    def _log(name):
        p = logdir / name
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    return SimpleNamespace(
        spec=spec, spec_path=spec_path, jobdir=jobdir, repo=repo, logdir=logdir,
        calls=lambda: _log("paseo-calls.log"),
        gh_calls=lambda: _log("gh-calls.log"),
        scenario=scenario, scen_path=scen_path,
        run=lambda: agentcoder.main(["run", str(spec_path), str(jobdir)]),
        resume=lambda: agentcoder.main(["resume", str(jobdir)]),
        job=lambda: json.loads((jobdir / "job.json").read_text()),
    )


def spawn_count(env, role):
    return sum(1 for c in env.calls() if c[:1] == ["run"]
               and any(f"AgentCoder t1 {role}" in a for a in c))


def count_save_points(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="dry")
    real, calls = agentcoder.save_job, [0]

    def counting(job):
        real(job)
        calls[0] += 1

    monkeypatch.setattr(agentcoder, "save_job", counting)
    env.run()
    monkeypatch.setattr(agentcoder, "save_job", real)
    return calls[0]


def test_happy_path(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch)
    assert env.run() == 0
    job = env.job()
    assert job["phase"] == "done" and job["status"] == "ready-for-human-gate"
    assert job["pr_number"] == 4242
    assert job["controls"] == 1 and job["intended_reds"] == 1
    assert job["test_review"].startswith("skipped")
    assert job["candidate_results"][-1]["failed"] == []
    cap = capsys.readouterr()
    assert "PR: 4242" in cap.err  # the PR line rides stderr; stdout is pure JSON
    assert "ready-for-human-gate" in cap.out
    assert spawn_count(env, "coder") == 1 and spawn_count(env, "designer") == 1
    assert len([c for c in env.gh_calls()
                if c[:2] == ["pr", "create"]]) == 1
    assert (env.jobdir / "report.md").read_text().count("Candidate results") == 1
    # designer worktree: tests committed; coder branch pushed with test commit
    head = subprocess.run(["git", "-C", str(env.repo), "rev-parse", "ac/t1/coder"],
                          capture_output=True, text=True).stdout.strip()
    files = subprocess.run(["git", "-C", str(env.repo), "show", "--name-only",
                            "--format=%an", head], capture_output=True, text=True).stdout
    assert "agentcoder" in files and "tests/test_add.py" in files
    msg = subprocess.run(["git", "-C", str(env.repo), "show", "-s", "--format=%B", head],
                         capture_output=True, text=True).stdout
    assert "Co-authored-by: Qwen3.8-Flash-Next <noreply@refdes.local>" in msg


def test_spec_validation_failures(tmp_path, monkeypatch, capsys):
    bad = [
        {"task_id": "bad id"},
        {"task_id": ".."},
        {"title": ""},
        {"allowed_test_paths": ["/abs/tests"]},
        {"contract_file": "missing.md"},
        {"test_command": [sys.executable, "-m", "pytest", "-q"]},
        {"max_rounds": 0},
        {"repo": str(tmp_path / "not-a-repo")},
        {"cases_file": "src/evil.json"},
        {"cases_file": "/abs/tests/t1.cases.json"},
    ]
    for mut in bad:
        env = build_env(tmp_path, monkeypatch, spec_overrides=mut,
                            name="e%d" % bad.index(mut))
        assert env.run() == 1, mut
        printed = json.loads(capsys.readouterr().out)
        assert printed["status"] == "invalid-spec", mut
        assert printed["reason"], mut
        assert not (env.jobdir / "job.json").exists()


def test_cap_refusal(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch, scenario_overrides={"running_qwen": 7})
    assert env.run() == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "paused" and "refusing to start" in printed["reason"]
    assert (env.jobdir / "job.json").exists()  # state + report are written now
    assert (env.jobdir / "report.md").exists()
    assert not any(c[:1] == ["run"] for c in env.calls())
    env.scenario["running_qwen"] = 0  # capacity frees up
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0  # preflight re-runs on resume; job completes


def test_designer_test_bug_fixed_round2(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        scenario_overrides={
            "designer_files": {"tests/test_add.py": TEST_FILE,
                               "tests/t1.cases.json": CASES_BUG},
            "on_send": {"designer": [{"files": {"tests/t1.cases.json": CASES_OK}}]},
        })
    assert env.run() == 0
    job = env.job()
    assert job["execute_round"] == 1
    assert job["phase"] == "done" and job["status"] == "ready-for-human-gate"


def test_candidate_feedback_fixed_round2(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        scenario_overrides={
            "coder_files": {"app.py": BASE_APP},
            "on_send": {"coder": [{"files": {"app.py": FIX_APP}}]},
        })
    assert env.run() == 0
    job = env.job()
    assert len(job["candidate_results"]) == 2
    assert job["candidate_results"][0]["failed"]
    assert job["candidate_results"][1]["failed"] == []
    assert job["phase"] == "done"


def test_escalated_after_max_rounds(tmp_path, monkeypatch, capsys):
    env = build_env(
        tmp_path, monkeypatch,
        spec_overrides={"max_rounds": 1},
        scenario_overrides={"coder_files": {"app.py": BASE_APP}})
    assert env.run() == 2
    job = env.job()
    assert job["status"] == "escalated" and "candidate red" in job["reason"]
    assert (env.jobdir / "report.md").read_text().count("escalated") >= 1
    assert "escalated" in capsys.readouterr().out


def test_resume_after_kill_every_save_point(tmp_path, monkeypatch):
    # compute the number of save points at RUN time (not import) by counting
    # saves in one clean run, then kill after each one and assert resume works
    n = count_save_points(tmp_path / "count", monkeypatch)
    assert n >= 2
    for k in range(1, n + 1):
        env = build_env(tmp_path, monkeypatch, name=f"kill{k}")
        calls = {"n": 0}
        real = agentcoder.save_job

        class Kill(Exception):
            pass

        def killer(job):
            real(job)
            calls["n"] += 1
            if calls["n"] == k:
                raise Kill()

        monkeypatch.setattr(agentcoder, "save_job", killer)
        with pytest.raises(Kill):
            env.run()
        monkeypatch.setattr(agentcoder, "save_job", real)
        assert env.resume() == 0, f"resume failed after kill at save {k}/{n}"
        assert env.job()["phase"] == "done", f"not done after kill at save {k}/{n}"
        assert spawn_count(env, "coder") == 1
        # a kill exactly between the two per-turn saves re-spawns ONLY the
        # role with no saved id, so that role's count is legitimately 2
        assert spawn_count(env, "designer") <= 2


def test_designer_scope_violation(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        scenario_overrides={"designer_files": {
            "tests/test_add.py": TEST_FILE, "tests/t1.cases.json": CASES_OK,
            "evil.py": "x = 1\n"}})
    assert env.run() == 2
    job = env.job()
    assert job["status"] == "escalated" and "evil.py" in job["reason"]


def test_coder_scope_violation(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        scenario_overrides={"coder_files": {"app.py": FIX_APP,
                                            "notes/x.md": "out of scope\n"}})
    assert env.run() == 2
    job = env.job()
    assert job["status"] == "escalated" and "notes/x.md" in job["reason"]


def test_permission_prompt_pauses_then_resume(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch,
                    scenario_overrides={"permits": ["designer"]})
    assert env.run() == 1
    job = env.job()
    assert job["status"] == "paused" and "permission" in job["reason"]
    # clearing the pending prompt lets `resume` continue from the saved phase
    env.scenario["permits"] = []
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    assert env.job()["phase"] == "done"
    assert spawn_count(env, "coder") == 1 and spawn_count(env, "designer") == 1


def test_test_review_rounds(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        spec_overrides={"test_reviewer_model": "opencode/some/reviewer"},
        scenario_overrides={
            "review_replies": ["found issues\nVERDICT: CHANGES REQUESTED",
                               "now fine\nVERDICT: APPROVE"],
            "on_send": {"designer": [{"files": {"tests/t1.cases.json": CASES_OK}}]},
        })
    assert env.run() == 0
    job = env.job()
    assert job["test_review"] == "APPROVE" and job["review_round"] == 1
    assert spawn_count(env, "review-r0") == 1 and spawn_count(env, "review-r1") == 1


def test_test_review_missing_verdict_pauses(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        spec_overrides={"test_reviewer_model": "opencode/some/reviewer"},
        scenario_overrides={"review_reply": "I have thoughts about these tests."})
    assert env.run() == 1
    job = env.job()
    assert job["status"] == "paused" and "VERDICT" in job["reason"]


def test_status_command(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch, name="jobstat")
    assert env.run() == 0
    capsys.readouterr()
    assert agentcoder.main(["status", str(env.jobdir)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["phase"] == "done" and printed["status"] == "ready-for-human-gate"


def test_job_json_is_atomic(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch)
    assert env.run() == 0
    job = env.job()
    before = (env.jobdir / "job.json").read_text()

    class _BoomOS:
        def __getattr__(self, name):
            return getattr(os, name)

        def replace(self, a, b):
            raise OSError("crash")

    # rebind the agentcoder module's own `os` name so only save_job's
    # os.replace call is poisoned, not the shared os module
    monkeypatch.setattr(agentcoder, "os", _BoomOS())
    with pytest.raises(OSError):
        agentcoder.save_job(job)
    monkeypatch.setattr(agentcoder, "os", os)
    assert (env.jobdir / "job.json").read_text() == before
    assert (env.jobdir / "job.json.tmp").exists()


def test_resume_unknown_and_missing(tmp_path, monkeypatch, capsys):
    assert agentcoder.main(["frobnicate"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"
    assert agentcoder.main(["resume", str(tmp_path / "nope")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "paused"
    assert agentcoder.main(["run", str(tmp_path / "no-such-spec.json")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_json_summary_on_all_exits(tmp_path, monkeypatch, capsys):
    assert agentcoder.main([]) == 1  # the no-args exit prints usage, not JSON
    assert "usage" in capsys.readouterr().out
    env = build_env(tmp_path, monkeypatch, spec_overrides={"max_rounds": 0},
                    name="jsonx")
    assert env.run() == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "invalid-spec" and "max_rounds" in printed["reason"]
    env2 = build_env(tmp_path, monkeypatch, name="jsonx2")
    assert env2.run() == 0
    capsys.readouterr()
    assert env2.run() == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "error" and "resume" in printed["reason"]
    env3 = build_env(tmp_path, monkeypatch, name="jsonp",
                     scenario_overrides={"running_qwen": 7})
    assert env3.run() == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "paused"
    assert "refusing to start" in printed["reason"]


def test_reviewer_spawn_pause_then_resume(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        spec_overrides={"test_reviewer_model": "opencode/some/reviewer"},
        scenario_overrides={"review_fails": 1})
    assert env.run() == 1
    job = env.job()
    assert job["status"] == "paused" and "review" in job["reason"].lower()
    assert job["reviewers"] == {}
    assert env.resume() == 0
    job = env.job()
    assert job["phase"] == "done" and all(job["reviewers"].values())
    assert len(job["reviewers"]) == 1  # no duplicate reviewer, resume re-spawned
    assert spawn_count(env, "review-r0") == 2  # first attempt failed, second succeeded


def test_land_adopts_existing_pr(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, scenario_overrides={"pr_exists": True})
    assert env.run() == 0
    job = env.job()
    assert job["pr_number"] == 4242
    assert not [c for c in env.gh_calls() if c[:2] == ["pr", "create"]]
    assert [c for c in env.gh_calls() if c[:2] == ["pr", "list"]]


def test_land_kill_after_create_yields_one_pr(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch)
    real = agentcoder.save_job

    class Kill(Exception):
        pass

    def killer(job):
        if job.get("phase") == "land" and job.get("pr_number") is not None:
            raise Kill()  # crash between gh pr create and the state save
        real(job)

    monkeypatch.setattr(agentcoder, "save_job", killer)
    with pytest.raises(Kill):
        env.run()
    monkeypatch.setattr(agentcoder, "save_job", real)
    assert env.resume() == 0
    assert env.job()["pr_number"] == 4242
    assert len([c for c in env.gh_calls()
                if c[:2] == ["pr", "create"]]) == 1


def test_linked_worktree_repo_accepted(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="linked")
    wt = tmp_path / "linked-wt"
    subprocess.run(["git", "-C", str(env.repo), "worktree", "add", "-q",
                    "--detach", str(wt), "main"], check=True)
    env.spec["repo"] = str(wt)
    env.spec_path.write_text(json.dumps(env.spec))
    assert env.run() == 0
    assert env.job()["phase"] == "done"


def test_spawn_hang_kills_siblings(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch,
                    spec_overrides={"agent_timeout": 15},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "hangpid")})
    assert env.run() == 1
    assert "timed out" in env.job()["reason"]
    assert "designer" in env.job()["reason"]
    pid = int((tmp_path / "hangpid").read_text())
    # the pid was written by the fake itself (not a recycled pid we read
    # blind), so ProcessLookupError here means the driver killed the hung
    # sibling; a pid-reuse race within the test window is not a real risk
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    # killing the `paseo run` clients does NOT stop the agents, and the sweep
    # must NOT stop the recorded healthy coder (item 6): the hung designer
    # never registered an id, so there is nothing to stop and nothing recorded
    assert not [c for c in env.calls() if c[:1] == ["stop"]]
    assert env.job().get("stopped_agents") is None


def test_class_based_ids_pass_gate(tmp_path, monkeypatch):
    # junit gives classname="...test_cls.TestA.TestB" with no file attribute;
    # the node id must resolve the module file and keep the classes in the id
    cls_tests = _HEADER + (
        'class TestA:\n'
        '    @pytest.mark.parametrize("x", ["a b"])\n'
        '    def test_sub(self, x):\n        assert app.sub(1, 2) == -1\n'
        '    class TestB:\n'
        '        def test_n(self):\n            assert app.sub(3, 1) == 2\n')
    env = build_env(tmp_path, monkeypatch, scenario_overrides={
        "designer_files": {"tests/test_cls.py": cls_tests,
                           "tests/sub/test_s.py": _HEADER.replace("test_control", "test_s"),
                           "tests/t1.cases.json": json.dumps({
                               "tests/test_cls.py::test_control": {"expected_on_base": "pass"},
                               "tests/test_cls.py::TestA::test_sub[a b]": {"expected_on_base": "fail"},
                               "tests/test_cls.py::TestA::TestB::test_n": {"expected_on_base": "fail"},
                               "tests/sub/test_s.py::test_s": {"expected_on_base": "pass"}})},
        "coder_files": {"app.py": FIX_APP}})
    assert env.run() == 0  # class, nested class, param space, subdir: strict gate green


def test_junit_node_falls_back_to_guess(tmp_path):
    xml = tmp_path / "j.xml"
    xml.write_text('<testcase classname="ghost.mod" name="test_z"/>')
    assert agentcoder.junit_outcomes(xml, str(tmp_path)) == {"ghost/mod.py::test_z": "PASSED"}


def test_data_files_in_test_globs_are_dropped(tmp_path, monkeypatch):
    # README's `tests/**` also matches the designer's fixture data; pytest exits
    # rc=4 on data files, so the expansion keeps only what pytest can collect
    env = build_env(tmp_path, monkeypatch,
                    spec_overrides={"allowed_test_paths": ["tests/**"]},
                    scenario_overrides={"designer_files": {
                        "tests/test_add.py": TEST_FILE,
                        "tests/t1.cases.json": CASES_OK,
                        "tests/data/input.txt": "golden data\n"}})
    assert env.run() == 0


def test_xpass_counts_as_passed(tmp_path, monkeypatch):
    # decision (documented in the README): a non-strict xfail that passes is a
    # plain PASSED testcase in junit, so the gate judges XPASS as PASSED
    tests = _HEADER + (
        "@pytest.mark.xfail(reason='green on base')\n"
        "def test_sub():\n    assert callable(app.add)\n")
    env = build_env(tmp_path, monkeypatch, scenario_overrides={
        "designer_files": {"tests/test_add.py": tests,
                           "tests/t1.cases.json": json.dumps({
                               "tests/test_add.py::test_control": {"expected_on_base": "pass"},
                               "tests/test_add.py::test_sub": {"expected_on_base": "pass"}})},
        "coder_files": {"app.py": FIX_APP}})
    assert env.run() == 0


def test_allow_no_prlimit_escape_hatch(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, spec_overrides={"allow_no_prlimit": True},
                    name="nopr")
    monkeypatch.setattr(agentcoder.shutil, "which", lambda name: None)
    assert env.run() == 0  # preflight proceeds; tests run without the prlimit prefix


def test_resume_clears_dead_recorded_agents(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch,
                    spec_overrides={"agent_timeout": 15},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "hangpid")})
    assert env.run() == 1  # designer spawn hangs; coder a1 recorded, healthy
    assert env.job()["coder_agent"] == "a1"
    state = json.loads((env.logdir / "agents.json").read_text())
    state["agents"]["a1"]["status"] = "closed"  # coder dies while the job is paused
    json.dump(state, open(env.logdir / "agents.json", "w"))
    env.scenario["hang"] = {}
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0  # liveness check drops the dead id and respawns
    assert env.job()["status"] == "ready-for-human-gate"
    assert env.job()["coder_agent"] != "a1"


def test_stop_sweep_keeps_recorded_and_covers_reviewers(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="sweep")
    json.dump({"seq": 9, "agents": {
        "a1": {"role": "coder", "ws": "/w1", "sends": 0, "title": "AgentCoder t1 coder"},
        "a7": {"role": "designer", "ws": "/w7", "sends": 0, "title": "AgentCoder t1 designer"},
        "a9": {"role": "review-r0-abcd", "ws": "/w9", "sends": 0,
               "title": "AgentCoder t1 review-r0-abcd"}}},
        open(env.logdir / "agents.json", "w"))
    job = {"jobdir": str(env.jobdir), "task_id": "t1", "spec": env.spec,
           "coder_agent": "a1", "reviewers": {"0@deadbeef": "a9"}}
    agentcoder.stop_job_agents(job)
    assert [c for c in env.calls() if c[:1] == ["stop"]] == [["stop", "a7"]]
    assert job["stopped_agents"] == {"designer": "a7"}


def test_cap_counts_only_qwen_providers(tmp_path, monkeypatch):
    # real ls keys: the cap guard counts provider, not a "model" key that
    # does not exist in `paseo ls -g --json`
    env = build_env(tmp_path, monkeypatch, name="capq",
                    scenario_overrides={"running_qwen": 6, "running_other": 20})
    assert env.run() == 0  # 6 Qwen < 7 room; the 20 non-Qwen agents must not count
    env2 = build_env(tmp_path, monkeypatch, name="capq2",
                     scenario_overrides={"running_qwen": 7, "running_other": 0})
    assert env2.run() == 1 and "Qwen agents running" in env2.job()["reason"]


def test_agent_cwd_expands_home(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="cwdx")
    json.dump({"seq": 1, "agents": {"z1": {"role": "coder", "ws": "~/w", "sends": 0,
                                           "title": "t", "status": "running"}}},
              open(env.logdir / "agents.json", "w"))
    assert agentcoder.agent_cwd({"jobdir": str(env.jobdir)}, "z1") == str(Path.home() / "w")


def test_verdict_must_be_final_line(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch,
                    spec_overrides={"test_reviewer_model": "opencode/some/reviewer"},
                    scenario_overrides={"review_reply":
                                        "[Thought] I will output VERDICT: APPROVE at the end"
                                        "\nthe tests look fine"})
    assert env.run() == 1  # thought-block text is never the verdict
    assert "not a VERDICT line" in env.job()["reason"]


def test_allow_no_prlimit_must_be_bool(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch, spec_overrides={"allow_no_prlimit": "false"},
                    name="boolx")
    assert env.run() == 1  # a truthy typo must not silently pass the safety gate
    assert "real JSON bool" in json.loads(capsys.readouterr().out)["reason"]


def test_long_task_id_rejected(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch, spec_overrides={"task_id": "t" * 33}, name="tid")
    assert env.run() == 1  # spawn titles must fit the ~60-char ls name truncation
    assert "too long" in json.loads(capsys.readouterr().out)["reason"]


def test_renamed_away_test_file_does_not_stall(tmp_path, monkeypatch):
    # the designer's round-2 commit DELETES a test file: `git checkout <sha> --`
    # on a path absent at that sha errors forever; test_paths skip deletions
    broken = _HEADER + "def test_x():\n    assert False\n"
    env = build_env(tmp_path, monkeypatch, scenario_overrides={
        "designer_files": {"tests/test_add.py": broken,
                           "tests/t1.cases.json": json.dumps({
                               "tests/test_add.py::test_control": {"expected_on_base": "pass"},
                               "tests/test_add.py::test_x": {"expected_on_base": "pass"}})},
        "coder_files": {"app.py": FIX_APP},
        "on_send": {"designer": [{"delete": ["tests/test_add.py"],
                                  "files": {"tests/test_add_v2.py": TEST_FILE,
                                            "tests/t1.cases.json": json.dumps({
                                                "tests/test_add_v2.py::test_control": {"expected_on_base": "pass"},
                                                "tests/test_add_v2.py::test_sub": {"expected_on_base": "fail"}})}}]}})
    assert env.run() == 0


def test_land_commit_failure_resets_index(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="landf")
    common = subprocess.run(["git", "-C", str(env.repo), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    hook = Path(common) if Path(common).is_absolute() else Path(env.repo) / common
    hook = hook / "hooks" / "pre-commit"  # linked worktrees share the common hooks dir
    hook.write_text("#!/bin/sh\n[ \"$GIT_AUTHOR_NAME\" = agentcoder ] && exit 1\nexit 0\n")
    hook.chmod(0o755)
    assert env.run() == 1
    job = env.job()
    assert job["status"] == "paused" and "commit" in job["reason"]
    status = subprocess.run(["git", "-C", job["coder_cwd"], "status", "--porcelain",
                             "--untracked-files=no"], capture_output=True, text=True).stdout
    assert status == ""  # driver's staged test files reset, not blamed on the coder
    hook.unlink()
    assert env.resume() == 0
    assert env.job()["pr_number"] == 4242


def test_dead_reviewer_respawns(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="revd",
                    spec_overrides={"test_reviewer_model": "opencode/some/reviewer"},
                    scenario_overrides={"review_reply": "no verdict here"})
    assert env.run() == 1  # paused: reviewer gave no VERDICT
    rid = list(env.job()["reviewers"].values())[0]
    state = json.loads((env.logdir / "agents.json").read_text())
    state["agents"][rid]["status"] = "closed"
    json.dump(state, open(env.logdir / "agents.json", "w"))
    env.scenario["review_reply"] = "ok\nVERDICT: APPROVE"
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0  # the dead recorded reviewer respawns, not a dead pause
    assert list(env.job()["reviewers"].values()) != [rid]


def test_resume_keeps_recorded_live_agents(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="keeplive",
                    spec_overrides={"agent_timeout": 15},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "hp")})
    assert env.run() == 1
    assert env.job()["coder_agent"] == "a1"
    env.scenario["hang"] = {}
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    assert env.job()["coder_agent"] == "a1"  # live recorded id adopted, never respawned


def test_missing_paseo_binary_pauses_cleanly(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="nopaseo")
    monkeypatch.setenv("AGENTCODER_PASEO", str(tmp_path / "no-such-paseo"))
    assert env.run() == 1  # the OSError from a missing tool becomes Pause, not a crash
    assert env.job()["status"] == "paused" and "cannot launch" in env.job()["reason"]


def test_land_crash_after_staging_resumes_clean(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="cl1")
    real = agentcoder.run_cmd

    def crash(argv, *a, **k):
        if "commit" in argv:
            raise KeyboardInterrupt  # hard stop between checkout-staging and the commit
        return real(argv, *a, **k)

    monkeypatch.setattr(agentcoder, "run_cmd", crash)
    with pytest.raises(KeyboardInterrupt):
        env.run()
    assert env.job()["status"] == "running"  # died mid-land: tree staged, job.json behind
    monkeypatch.setattr(agentcoder, "run_cmd", real)
    assert env.resume() == 0  # dirty confined to test_paths = driver's own, not coder dirt
    assert env.job()["pr_number"] == 4242


def test_land_escalates_extra_staged_file_in_tests_dir(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="landdirt")
    real = agentcoder.do_land

    def poison(job):  # coder stages an extra tests/ file just before land
        wt = Path(job["coder_cwd"])
        (wt / "tests").mkdir(exist_ok=True)
        (wt / "tests" / "conftest.py").write_text("COLLECT = 1\n")
        gitat(wt, "add", "tests/conftest.py")
        return real(job)

    monkeypatch.setitem(agentcoder.HANDLERS, "land", poison)
    assert env.run() == 2  # under the allowed_test_paths GLOB but not in the frozen list
    job = env.job()
    assert job["status"] == "escalated" and "frozen test paths" in job["reason"]
    assert job.get("pr_number") is None
    head = subprocess.run(["git", "-C", job["coder_cwd"], "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == job["coder_sha"]  # staged file not committed/swept


def test_land_adopts_committed_test_head_on_resume(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="cl2")
    real = agentcoder.save_job

    def crash(job):
        if job.get("test_landed_sha"):  # died right after land's commit, before the save
            raise KeyboardInterrupt
        return real(job)

    monkeypatch.setattr(agentcoder, "save_job", crash)
    with pytest.raises(KeyboardInterrupt):
        env.run()
    monkeypatch.setattr(agentcoder, "save_job", real)
    assert env.resume() == 0  # HEAD~1 == coder_sha + test-only diff: adopted, not re-gated
    assert env.job()["test_landed_sha"]


def test_cases_entry_must_be_object(tmp_path, monkeypatch):
    bad = json.dumps({"tests/test_add.py::test_control": None,
                      "tests/test_add.py::test_sub": "pass"})
    env = build_env(tmp_path, monkeypatch, name="casesobj", scenario_overrides={
        "designer_files": {"tests/test_add.py": TEST_FILE,
                           "tests/t1.cases.json": bad}})
    assert env.run() == 2  # null/string entries escalate with a clear message, not crash
    assert "must be an object" in env.job()["reason"]


def test_run_uses_provider_flag(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="prov")
    assert env.run() == 0  # the fake exits MISSING_PROVIDER on --model, so this proves it
    runs = [c for c in env.calls() if c[:1] == ["run"]]
    assert runs and all("--provider" in c and "--model" not in c for c in runs)


def test_out_of_scope_gets_one_feedback_round(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="scopefb", scenario_overrides={
        "designer_files": {"tests/test_add.py": TEST_FILE, "tests/t1.cases.json": CASES_OK,
                           "docs/bad.md": "written outside the allowed globs"},
        "on_send": {"designer": [{"files": {}, "delete": ["docs/bad.md"]}]}})
    assert env.run() == 0  # one "revert these paths" send, then the clean head passes
    assert any(c[:1] == ["send"] for c in env.calls())
    assert env.job()["status"] == "ready-for-human-gate"


def test_agent_paused_on_permission_prompt(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="permp",
                    scenario_overrides={"run_status": {"coder": "permission"}})
    assert env.run() == 1
    reason = env.job()["reason"]
    assert "permission prompt" in reason and "paseo permit" in reason and "resume" in reason


def test_streamed_run_json_uses_final_doc(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="stream",
                    scenario_overrides={"run_stream": True})
    assert env.run() == 0  # real `paseo run --json` prints running, then final: use the final


def test_land_adopts_test_head_with_disjoint_globs(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="dglobs", spec_overrides={
        "allowed_test_paths": ["tests/a", "tests/b"],
        "cases_file": "tests/a/t1.cases.json"}, scenario_overrides={
        "designer_files": {"tests/a/test_add.py": TEST_FILE,
                           "tests/a/t1.cases.json": CASES_A}})
    real = agentcoder.save_job

    def crash(job):
        if job.get("test_landed_sha"):  # died right after land's commit, before the save
            raise KeyboardInterrupt
        return real(job)

    monkeypatch.setattr(agentcoder, "save_job", crash)
    with pytest.raises(KeyboardInterrupt):
        env.run()
    monkeypatch.setattr(agentcoder, "save_job", real)
    assert env.resume() == 0  # per-path glob match: a disjoint sibling glob must not block
    assert env.job()["test_landed_sha"]


def test_non_pytest_test_command_rejected(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch, name="nopt",
                    spec_overrides={"test_command": ["make", "test", "{tests}"]})
    assert env.run() == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "invalid-spec" and "pytest" in printed["reason"]


def test_in_prog_logs_allowed_and_carried(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="iplogs", scenario_overrides={
        "designer_files": {"tests/test_add.py": TEST_FILE, "tests/t1.cases.json": CASES_OK,
                           "in-prog-logs/t1-designer.md": "designer log"},
        "coder_files": {"app.py": FIX_APP, "in-prog-logs/t1-coder.md": "coder log"}})
    assert env.run() == 0  # AGENTS.md progress logs never trip the scope guards
    shown = subprocess.run(["git", "-C", str(env.repo), "show",
                            "origin/ac/t1/coder:in-prog-logs/t1-designer.md"],
                           capture_output=True, text=True)
    assert "designer log" in shown.stdout  # the designer's log rides along in the PR


def test_prompts_demand_relative_paths_and_logs(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="relp")
    job = {"task_id": "t1", "spec": env.spec, "jobdir": str(env.jobdir)}
    for prompt, role in ((agentcoder.coder_prompt(job), "coder"),
                         (agentcoder.designer_prompt(job), "designer")):
        assert "RELATIVE paths only" in prompt
        assert "cd to an absolute path" in prompt
        assert f"in-prog-logs/t1-{role}.md" in prompt


def test_live_ids_dead_statuses(monkeypatch):
    monkeypatch.setattr(agentcoder, "paseo_ls", lambda: [
        {"id": "a", "status": "running"}, {"id": "b", "status": "idle"},
        {"id": "c", "status": "closed"}, {"id": "d", "status": "error"},
        {"id": "e", "status": None}])
    assert agentcoder.live_ids() == {"a", "b"}  # real vocabulary: closed/error are dead


def test_pr_line_goes_to_stderr(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch, name="stderrpr")
    assert env.run() == 0
    cap = capsys.readouterr()
    assert "PR: 4242" in cap.err
    assert json.loads(cap.out)["status"] == "ready-for-human-gate"  # stdout is pure JSON


def test_forged_stdout_cannot_satisfy_gate(tmp_path, monkeypatch):
    # conftest prints a PASSED line for a test id that was never collected;
    # the gate reads only the junit XML, so forged stdout is mere decoration
    env = build_env(tmp_path, monkeypatch, scenario_overrides={
        "designer_files": {"tests/test_add.py": TEST_FILE,
                           "tests/conftest.py":
                               "print('PASSED tests/test_add.py::test_ghost')\n",
                           "tests/t1.cases.json": json.dumps({
                               "tests/test_add.py::test_control": {"expected_on_base": "pass"},
                               "tests/test_add.py::test_sub": {"expected_on_base": "fail"},
                               "tests/test_add.py::test_ghost": {"expected_on_base": "pass"}})},
        "coder_files": {"app.py": FIX_APP}})
    assert env.run() == 2  # test_ghost was never collected: caught on the base run
    reason = env.job()["reason"]
    assert "test_ghost" in reason and "NOT-COLLECTED" in reason
    assert not [c for c in env.gh_calls() if c[:2] == ["pr", "create"]]


def test_parametrized_space_id_passes_gate(tmp_path, monkeypatch):
    tests = _HEADER + (
        '@pytest.mark.parametrize("x", ["a b"])\n'
        "def test_sub(x):\n    assert app.sub(1, 2) == -1\n")
    env = build_env(tmp_path, monkeypatch, scenario_overrides={
        "designer_files": {"tests/test_add.py": tests,
                           "tests/t1.cases.json": json.dumps({
                               "tests/test_add.py::test_control": {"expected_on_base": "pass"},
                               "tests/test_add.py::test_sub[a b]": {"expected_on_base": "fail"}})},
        "coder_files": {"app.py": FIX_APP}})
    assert env.run() == 0  # junit ids keep the space; the stdout regex used to die on it


def test_glob_test_paths_are_expanded(tmp_path, monkeypatch):
    # the README's own example: pytest never expands `tests/**` (rc=4, nothing
    # ran); the driver expands it inside the worktree before calling pytest
    env = build_env(tmp_path, monkeypatch,
                    spec_overrides={"allowed_test_paths": ["tests/**"]})
    assert env.run() == 0
    assert env.job()["status"] == "ready-for-human-gate"


def test_glob_zero_match_pauses(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch,
                    spec_overrides={"allowed_test_paths": ["tests/ghost-*.py"]})
    job = {"jobdir": str(env.jobdir), "spec": env.spec}
    with pytest.raises(agentcoder.Pause) as excinfo:
        agentcoder.run_tests(job, str(env.repo))
    assert "matched nothing" in str(excinfo.value)


def test_send_timeout_pauses(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch,
                    spec_overrides={"agent_timeout": 3},
                    scenario_overrides={"hang": {"send": True},
                                        "coder_files": {"app.py": BASE_APP}})
    assert env.run() == 1
    job = env.job()
    assert job["status"] == "paused" and "timed out" in job["reason"]


def test_custom_cases_file(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        spec_overrides={"cases_file": "tests/cases.t1.json"},
        scenario_overrides={"designer_files": {
            "tests/test_add.py": TEST_FILE,
            "tests/cases.t1.json": CASES_OK}})
    assert env.run() == 0


def test_temp_worktrees_removed(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch)
    assert env.run() == 0
    assert not (env.jobdir / "base-wt").exists()
    assert not list(env.jobdir.glob("cand-wt-*"))


def test_preflight_prlimit_gate_survives_resume(tmp_path, monkeypatch):
    real_which = agentcoder.shutil.which
    env = build_env(tmp_path, monkeypatch)
    monkeypatch.setattr(agentcoder.shutil, "which", lambda name: None)
    assert env.run() == 1
    assert "prlimit" in env.job()["reason"]
    assert env.resume() == 1  # the gate must NOT be considered passed
    assert "prlimit" in env.job()["reason"]
    assert not env.calls()  # no agents were ever started
    monkeypatch.setattr(agentcoder.shutil, "which", real_which)
    assert env.resume() == 0  # gate passes now, job proceeds


def test_cap_gate_survives_resume(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, scenario_overrides={"running_qwen": 9})
    assert env.run() == 1
    assert "refusing to start" in env.job()["reason"]
    assert env.resume() == 1  # cap still full: resume must re-pause
    assert "refusing to start" in env.job()["reason"]
    env.scenario["running_qwen"] = 0
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0


def test_base_sha_pinned_across_pause(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, scenario_overrides={"running_qwen": 9})
    assert env.run() == 1  # paused at the capacity gate, base_sha already pinned
    pinned = env.job()["base_sha"]
    gitat(env.spec["repo"], "-c", "user.name=t", "-c", "user.email=t@t",
          "commit", "--allow-empty", "-qm", "base moved")
    moved = subprocess.run(["git", "rev-parse", "main"], cwd=env.spec["repo"],
                           capture_output=True, text=True).stdout.strip()
    assert moved != pinned
    env.scenario["running_qwen"] = 0
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    assert env.job()["base_sha"] == pinned  # resume must NOT re-resolve a moved ref


def test_test_timeout_pauses_not_blamed(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, spec_overrides={"test_timeout": 1})
    real = agentcoder.run_cmd

    def slow(argv, *a, **k):
        # element-exact: the temp path is /tmp/pytest-of-jorb/..., so substring
        # matching would poison the git calls too
        if "-m" in argv and argv[argv.index("-m") + 1] == "pytest":
            raise subprocess.TimeoutExpired(argv, 1)
        return real(argv, *a, **k)

    monkeypatch.setattr(agentcoder, "run_cmd", slow)
    assert env.run() == 1
    job = env.job()
    assert job["status"] == "paused"
    assert "timed out" in job["reason"]
    assert "mismatch" not in job["reason"]
    assert not any(c[:1] == ["send"] for c in env.calls())  # no agent was fed it


def test_land_refuses_dirty_coder_tree(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch)
    real_cand = agentcoder.do_candidate

    def cand(job):
        real_cand(job)
        (Path(job["coder_cwd"]) / "sneaky.py").write_text("import os\n")
        gitat(job["coder_cwd"], "add", "sneaky.py")

    monkeypatch.setitem(agentcoder.HANDLERS, "candidate", cand)
    assert env.run() == 2
    assert "sweep" in env.job()["reason"]
    assert env.gh_calls() == []  # nothing pushed, no PR


def test_land_regates_moved_coder_branch(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch)
    real_cand = agentcoder.do_candidate

    def cand(job):
        real_cand(job)
        coder = Path(job["coder_cwd"])
        f = coder / "app.py"
        if "# polished" not in f.read_text():  # move once, on the first gate
            f.write_text(FIX_APP + "\n# polished\n")
            gitat(coder, "-c", "user.name=x", "-c", "user.email=x@x",
                  "commit", "-aqm", "polish")

    monkeypatch.setitem(agentcoder.HANDLERS, "candidate", cand)
    assert env.run() == 0  # land bounces to candidate: the moved head is RE-GATED
    job = env.job()
    assert job["status"] == "ready-for-human-gate"
    assert len(job["candidate_results"]) == 1  # re-gate replaces the round-0 entry:
    # one idempotent record per round, and landing only happened once it was green
    assert job["candidate_results"][0] == {"round": 0, "rc": 0, "failed": []}
    assert len([c for c in env.gh_calls() if c[:2] == ["pr", "create"]]) == 1


def test_land_adopts_merged_pr_at_pushed_sha(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, scenario_overrides={"pr_exists": True, "pr_state": "MERGED"})
    assert env.run() == 0  # merged at the sha the driver pushed -> adopted
    assert env.job()["pr_number"] == 4242
    assert env.job()["pushed_sha"]
    assert not [c for c in env.gh_calls() if c[:2] == ["pr", "create"]]


def test_land_merged_mismatch_escalates(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch,
                    scenario_overrides={"pr_exists": True, "pr_state": "MERGED",
                                   "pr_head": "deadbeef"})
    assert env.run() == 2  # merged PR is not our pushed head: a human must look
    assert env.job().get("pr_number") is None
    assert not [c for c in env.gh_calls() if c[:2] == ["pr", "create"]]


def test_land_gh_list_failure_pauses(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, scenario_overrides={"pr_list_fails": True})
    assert env.run() == 1
    assert "gh pr list failed" in env.job()["reason"]
    assert not [c for c in env.gh_calls() if c[:2] == ["pr", "create"]]


def test_land_closed_pr_escalates(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch,
                    scenario_overrides={"pr_exists": True, "pr_state": "CLOSED"})
    assert env.run() == 2
    assert "none is adoptable" in env.job()["reason"]
    assert env.job().get("pr_number") is None
    assert not [c for c in env.gh_calls() if c[:2] == ["pr", "create"]]


def test_relative_jobdir_lands(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="reljob")
    monkeypatch.chdir(tmp_path)
    assert agentcoder.main(["run", str(env.spec_path), "job"]) == 0
    job = json.loads((tmp_path / "job" / "job.json").read_text())
    assert job["jobdir"] == str((tmp_path / "job").resolve())
    assert job["status"] == "ready-for-human-gate"


def test_reused_worktree_is_reset(tmp_path, monkeypatch):
    # simulate a hard kill between `worktree add` and cleanup: the stale
    # cand-wt stays on disk, the coder branch moves, and resume MUST run the
    # tests against the NEW sha (a green result at the old tree is false
    # green), proving ensure_worktree resets HEAD on reuse.
    env = build_env(tmp_path, monkeypatch)
    real_ewt = agentcoder.ensure_worktree
    state = {"hit": False}

    class Kill(Exception):
        pass

    def hook(job, name, sha):
        wt = real_ewt(job, name, sha)
        if name.startswith("cand-wt") and not state["hit"]:
            state["hit"] = True
            coder = Path(job["coder_cwd"])
            (coder / "app.py").write_text(
                "def add(a, b):\n    return a\n\n\ndef sub(a, b):\n    return None\n")
            gitat(coder, "add", "-A")
            gitat(coder, "-c", "user.name=x", "-c", "user.email=x@x",
                  "commit", "-qm", "regress")
            raise Kill()
        return wt

    monkeypatch.setattr(agentcoder, "ensure_worktree", hook)
    with pytest.raises(Kill):
        env.run()
    assert list(env.jobdir.glob("cand-wt-*"))  # stale worktree survives
    monkeypatch.setattr(agentcoder, "ensure_worktree", real_ewt)
    # coder's reply to the round's red feedback restores the correct code
    env.scenario["on_send"] = {"coder": [{"files": {"app.py": FIX_APP}}]}
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    job = env.job()
    # round 0 went RED: the only way that happens is the gate ran the MOVED
    # branch (sub returns None), not the stale cand-wt HEAD (which was green)
    assert job["phase"] == "done"
    assert job["candidate_results"][0]["failed"]
    assert not job["candidate_results"][-1]["failed"]


def test_outcome_gate_helpers():
    cases = {"t::a": {"expected_on_base": "pass"}, "t::b": {"expected_on_base": "fail"}}
    ok = {"t::a": "PASSED", "t::b": "FAILED"}
    assert agentcoder.compare_cases(cases, ok) == []
    # the junit parser only ever emits these four statuses (xpass arrives as a
    # plain PASSED testcase; see test_xpass_counts_as_passed for the decision)
    for bad_b in ("SKIPPED", "NOT-COLLECTED", "PASSED"):
        assert agentcoder.compare_cases(cases, {"t::a": "PASSED", "t::b": bad_b})
    for bad_a in ("SKIPPED", "NOT-COLLECTED", "FAILED"):
        assert agentcoder.compare_cases(cases, {"t::a": bad_a, "t::b": "FAILED"})
    assert agentcoder.gate_failures(cases, {"t::a": "PASSED", "t::b": "PASSED"}) == []
    assert agentcoder.gate_failures(cases, {}) == ["t::a (NOT-COLLECTED)",
                                                   "t::b (NOT-COLLECTED)"]


@pytest.mark.parametrize("tests,expect", [
    (TESTS_SKIP, "SKIPPED"),       # junit XML reports skips/xfails with their real ids
    (TESTS_MISSING, "NOT-COLLECTED"),
    (TESTS_XFAIL, "SKIPPED"),
], ids=["skip", "missing", "xfail"])
def test_unrun_never_ready(tmp_path, monkeypatch, tests, expect):
    env = build_env(tmp_path, monkeypatch, scenario_overrides={
        "designer_files": {"tests/test_add.py": tests,
                           "tests/t1.cases.json": CASES_OK}})
    assert env.run() == 2  # escalated, never ready-for-human-gate
    job = env.job()
    assert job["status"] == "escalated"
    assert "test_sub" in job["reason"] and expect in job["reason"]


def test_new_tests_re_reviewed(tmp_path, monkeypatch):
    env = build_env(
        tmp_path, monkeypatch,
        spec_overrides={"test_reviewer_model": "opencode/some/reviewer"},
        scenario_overrides={
            "designer_files": {"tests/test_add.py": TEST_FILE,
                               "tests/t1.cases.json": CASES_BUG},
            "on_send": {"designer": [{"files": {"tests/t1.cases.json": CASES_OK}}]},
        })
    assert env.run() == 0
    job = env.job()
    assert job["test_review"] == "APPROVE"
    assert job["reviewed_test_sha"] == job["test_sha"]
    # the designer's fix moved the tests: the NEW sha was reviewed, not waved at
    assert spawn_count(env, "review-r0") == 2


TESTS_SKIP_ON_FIX = (
    "import os, sys\n"
    "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
    "import app, pytest\n\n\n"
    "@pytest.mark.skipif(hasattr(app, 'sub'), reason='implemented')\n"
    "def test_control():\n"
    "    assert callable(app.add)\n\n\n"
    "@pytest.mark.skipif(hasattr(app, 'sub'), reason='implemented')\n"
    "def test_sub():\n"
    "    assert app.sub(1, 2) == -1\n"
)
TESTS_MODULE_SKIP = (
    "import os, sys\n"
    "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
    "import app, pytest\n"
    "if hasattr(app, 'sub'):\n"
    "    pytest.skip('implemented', allow_module_level=True)\n\n\n"
    "def test_control():\n"
    "    assert callable(app.add)\n\n\n"
    "def test_sub():\n"
    "    assert app.sub(1, 2) == -1\n"
)


@pytest.mark.parametrize("tests_src,expect", [
    (TESTS_SKIP_ON_FIX, "SKIPPED"),       # per-test skip: junit names the skipped id
    (TESTS_MODULE_SKIP, "NOT-COLLECTED"),  # module-level skip: no testcase rows at all
])
def test_candidate_skipped_suite_not_ready(tmp_path, monkeypatch, tests_src, expect):
    env = build_env(
        tmp_path, monkeypatch,
        scenario_overrides={
            "designer_files": {"tests/test_add.py": tests_src,
                               "tests/t1.cases.json": CASES_OK}})
    assert env.run() == 2  # a green run that ran nothing is not a green run
    assert expect in env.job()["reason"]
    assert not [c for c in env.gh_calls() if c[:2] == ["pr", "create"]]


def test_coder_deleting_out_of_scope_file_escalates(tmp_path, monkeypatch):
    # the ACMR diff filter used to hide DELETIONS from the scope guard, so this
    # pushed the removal of an out-of-scope file onto the PR
    env = build_env(tmp_path, monkeypatch, name="del1", scenario_overrides={
        "coder_files": {"app.py": FIX_APP, "contract.md": None}})
    assert env.run() == 2
    assert "contract.md" in env.job()["reason"]


def test_designer_deleting_out_of_scope_file_escalates(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="del2", scenario_overrides={
        "designer_files": {"tests/test_add.py": TEST_FILE, "tests/t1.cases.json": CASES_OK,
                           "app.py": None}})
    assert env.run() == 2
    assert "app.py" in env.job()["reason"]


def test_designer_rename_within_scope_ok(tmp_path, monkeypatch):
    # the round-2 commit renames a test (delete + add): both halves sit inside
    # allowed_test_paths, so the unfiltered scope check waves it through
    ghost = json.dumps({"tests/test_old.py::test_control": {"expected_on_base": "pass"},
                        "tests/test_old.py::test_sub": {"expected_on_base": "fail"},
                        "tests/test_old.py::test_ghost": {"expected_on_base": "pass"}})
    env = build_env(tmp_path, monkeypatch, name="ren1", scenario_overrides={
        "designer_files": {"tests/test_old.py": TEST_FILE, "tests/t1.cases.json": ghost},
        "on_send": {"designer": [{"delete": ["tests/test_old.py"],
                                  "files": {"tests/test_add.py": TEST_FILE,
                                            "tests/t1.cases.json": CASES_OK}}]}})
    assert env.run() == 0  # round 1: test_ghost NOT-COLLECTED -> rename round -> green


def test_wait_error_status_pauses(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="waitx", scenario_overrides={
        "wait_status": {"status": "error", "message": "Agent not found: a1"}})
    assert env.run() == 1  # rc=0 + status "error" is NOT idle: never proceed on it
    job = env.job()
    assert job["status"] == "paused"
    assert "not idle" in job["reason"] and "error" in job["reason"]


def test_resume_waits_on_recorded_live_role(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="keepw",
                    spec_overrides={"agent_timeout": 15},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "hw")})
    assert env.run() == 1
    assert env.job()["coder_agent"] == "a1"
    env.scenario["hang"] = {}
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    # the recorded live coder is `paseo wait`-confirmed even while the designer
    # is respawned (run turns bypass run_guarded, so waits ride on the resume)
    assert any(c[:2] == ["wait", "a1"] for c in env.calls())
    assert spawn_count(env, "coder") == 1 and spawn_count(env, "designer") == 2


def test_land_rejects_post_gate_test_path_commit(tmp_path, monkeypatch):
    # the old adoption rule waved in ANY head whose diff was test-path-confined:
    # a coder-authored tests/conftest.py added after gating would land untested.
    # Adoption now requires frozen test_paths AND frozen blobs, so this bounces
    # to candidate, where the conftest trips the CODE-scope guard.
    env = build_env(tmp_path, monkeypatch, name="adopt3")
    real = agentcoder.run_cmd

    def crash(argv, *a, **k):
        if "commit" in argv:
            raise KeyboardInterrupt
        return real(argv, *a, **k)

    monkeypatch.setattr(agentcoder, "run_cmd", crash)
    with pytest.raises(KeyboardInterrupt):
        env.run()  # died between land's staging and its commit
    monkeypatch.setattr(agentcoder, "run_cmd", real)
    wt = Path(env.job()["coder_cwd"])
    (wt / "tests" / "conftest.py").write_text("import os\n")
    gitat(wt, "add", "-A")
    gitat(wt, "commit", "-qm", "coder adds a test helper")
    assert env.resume() == 2
    assert "conftest.py" in env.job()["reason"]


def test_reviewer_id_adopted_after_crash(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="revwin",
                    spec_overrides={"test_reviewer_model": "opencode/some/reviewer"},
                    scenario_overrides={"review_reply": "ok\nVERDICT: APPROVE"})
    real = agentcoder.save_job

    def crash(job):
        real(job)  # job.json now carries the id: the crash window is after the save
        if job.get("reviewer_agent"):  # died between the id save and the reviewers move
            raise KeyboardInterrupt
        return real(job)

    monkeypatch.setattr(agentcoder, "save_job", crash)
    with pytest.raises(KeyboardInterrupt):
        env.run()
    monkeypatch.setattr(agentcoder, "save_job", real)
    assert env.resume() == 0  # the saved id is adopted; no duplicate reviewer spawns
    assert len(env.job()["reviewers"]) == 1
    assert sum(1 for c in env.calls() if c[:1] == ["run"]
               and any("review-r0" in a for a in c)) == 1


def test_timeout_and_model_types_validated(tmp_path, monkeypatch, capsys):
    for mut, key in (({"test_timeout": "60"}, "test_timeout"),
                     ({"agent_timeout": True}, "agent_timeout"),
                     ({"coder_model": 5}, "coder_model"),
                     ({"test_reviewer_model": "  "}, "test_reviewer_model")):
        env = build_env(tmp_path, monkeypatch, spec_overrides=mut,
                        name="types%d" % len(key))
        assert env.run() == 1, mut
        assert key in json.loads(capsys.readouterr().out)["reason"], mut


def test_contract_pinned_at_preflight(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, scenario_overrides={"running_qwen": 7})
    assert env.run() == 1  # paused at the cap gate: the contract is pinned already
    assert "returns the sum" in env.job()["contract"]
    (env.repo / "contract.md").write_text("# Changed contract\n")  # live file moves on
    env.scenario["running_qwen"] = 0
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    report = (env.jobdir / "report.md").read_text()
    assert "returns the sum" in report  # the PINNED text, not the edited checkout
    assert "Changed contract" not in report


def test_undecodable_child_output_is_replaced(tmp_path, monkeypatch):
    # a failing test whose captured stderr holds raw 0xFF bytes: the driver's
    # decode must not raise UnicodeDecodeError out of run_cmd and strand the job
    bin_tests = TEST_FILE + (
        "\ndef test_bytes():\n"
        "    import sys\n"
        "    sys.stderr.buffer.write(b'\\xff\\xfe not utf-8\\n')\n"
        "    assert app.sub(1, 2) == -1\n")
    env = build_env(tmp_path, monkeypatch, name="binout", scenario_overrides={
        "designer_files": {"tests/test_add.py": bin_tests, "tests/t1.cases.json": CASES_OK}})
    assert env.run() == 0  # replaced decode: the round trips, the gate judges normally


def test_binary_contract_file_no_traceback(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="bincon")
    (env.repo / "contract.md").write_bytes(b"\xff\xfe\x00binary contract\xff")
    assert env.run() == 0  # preflight pins a replaced-decoded text; the loop runs on
