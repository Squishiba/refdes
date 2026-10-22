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
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="agentcoder drives a Linux paseo host; fakes use shebang scripts, "
           "fcntl and prlimit")

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "agentcoder_tool", ROOT / "tools" / "agentcoder" / "agentcoder.py")
agentcoder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agentcoder)

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

PASEO_FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time

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
        os.makedirs(os.path.dirname(fp) or ws, exist_ok=True)
        open(fp, "w").write(c)
    subprocess.run(["git", "-C", ws, "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", ws, "-c", "user.name=fake", "-c", "user.email=f@x",
                    "commit", "-m", msg], capture_output=True)

def flag(name, dflt=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else dflt

cmd = ARGS[0]
if cmd == "ls":
    rows = [{"agentId": k, "status": "completed", "cwd": v["ws"], "model": "fake"}
            for k, v in state["agents"].items() if v["ws"]]
    rows += [{"agentId": "q%d" % i, "status": "running",
              "model": "opencode/qwenlocal/Qwen3.8-Flash-Next"}
             for i in range(S.get("running_qwen", 0))]
    print(json.dumps(rows))
elif cmd == "permit":
    ids = {}
    for k, v in state["agents"].items():
        ids[v["role"]] = k
    print(json.dumps([{"agentId": ids[r]} for r in S.get("permits", []) if ids.get(r)]))
elif cmd == "wait":
    print(json.dumps({"status": "idle"}))
elif cmd == "logs":
    rec = state["agents"].get(ARGS[1], {})
    replies = S.get("review_replies")
    idx = int(rec.get("role", "r0").rsplit("r", 1)[-1]) if rec.get("role", "").startswith("review-r") else 0
    text = replies[idx] if isinstance(replies, list) and idx < len(replies) \
        else S.get("review_reply", "checks fine\nVERDICT: APPROVE")
    print(text)
elif cmd == "run":
    role = flag("--title", "").rsplit(" ", 1)[-1]
    hang = S.get("hang", {})
    if role in hang.get("run", []):
        if S.get("pidfile"):
            open(S["pidfile"], "w").write(str(os.getpid()))
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
    state["agents"][aid] = {"role": role, "ws": ws, "sends": 0}
    save()
    print(json.dumps({"agentId": aid, "status": "completed"}))
elif cmd == "send":
    if S.get("hang", {}).get("send"):
        time.sleep(120)
    rec = state["agents"].get(ARGS[1])
    if rec is not None:
        queue = S.get("on_send", {}).get(rec["role"], [])
        n = rec.get("sends", 0)
        if n < len(queue):
            write_commit(rec["ws"], queue[n]["files"], "fake fix")
        rec["sends"] = n + 1
        save()
    print(json.dumps({"status": "completed"}))
else:
    sys.exit("fake paseo: unknown " + cmd)
'''

GH_FAKE = r'''#!/usr/bin/env python3
import json, os, sys

S = json.load(open(os.environ["FAKESCENARIO"]))
LOG = os.path.join(S["logdir"], "gh-calls.log")
with open(LOG, "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\n")
args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    created = S.get("pr_exists")
    if not created and os.path.exists(LOG):
        for line in open(LOG):
            if json.loads(line)[:2] == ["pr", "create"]:
                created = True
    print(json.dumps([{"number": 4242}] if created else []))
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
        spec=spec, spec_path=spec_path, jobdir=jobdir, repo=repo,
        calls=lambda: _log("paseo-calls.log"),
        gh_calls=lambda: _log("gh-calls.log"),
        scenario=scenario, scen_path=scen_path,
        run=lambda: agentcoder.main(["run", str(spec_path), str(jobdir)]),
        resume=lambda: agentcoder.main(["resume", str(jobdir)]),
        job=lambda: json.loads((jobdir / "job.json").read_text()),
    )


def spawn_count(env, role):
    return sum(1 for c in env.calls() if c[:1] == ["run"]
               and f"AgentCoder t1 {role}" in c)


class _EnvMP:
    def setenv(self, key, value):
        os.environ[key] = value


def _dry_run_save_count():
    """Number of job.json saves in one clean happy-path run; the kill/resume
    test parametrizes over every one of them."""
    env = build_env(Path(tempfile.mkdtemp(prefix="ac-savecount-")), _EnvMP(),
                    name="env")
    real, calls = agentcoder.save_job, [0]

    def counting(job):
        real(job)
        calls[0] += 1

    agentcoder.save_job = counting
    try:
        env.run()
    finally:
        agentcoder.save_job = real
    return calls[0]


# Only computed off Windows: the dry run spawns the fakes, which is exactly
# what Windows cannot do; the kill test is skipped there anyway.
SAVE_COUNT = 1 if sys.platform == "win32" else _dry_run_save_count()


def test_happy_path(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch)
    assert env.run() == 0
    job = env.job()
    assert job["phase"] == "done" and job["status"] == "ready-for-human-gate"
    assert job["pr_number"] == 4242
    assert job["controls"] == 1 and job["intended_reds"] == 1
    assert job["test_review"].startswith("skipped")
    assert job["candidate_results"][-1]["failed"] == []
    out = capsys.readouterr().out
    assert "PR: 4242" in out
    assert "ready-for-human-gate" in out
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
    assert "refusing to start" in capsys.readouterr().out
    assert not (env.jobdir / "job.json").exists()
    assert not any(c[:1] == ["run"] for c in env.calls())


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


@pytest.mark.parametrize("k", range(1, SAVE_COUNT + 1))
def test_resume_after_kill(tmp_path, monkeypatch, k):
    env = build_env(tmp_path, monkeypatch)
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
    assert env.resume() == 0
    assert env.job()["phase"] == "done"
    assert spawn_count(env, "coder") == 1
    assert spawn_count(env, "designer") == 1


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
    monkeypatch.setattr(agentcoder.os, "replace",
                        lambda a, b: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        agentcoder.save_job(job)
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
                    spec_overrides={"agent_timeout": 3},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "hangpid")})
    assert env.run() == 1
    assert "timed out" in env.job()["reason"]
    pid = int((tmp_path / "hangpid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


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
