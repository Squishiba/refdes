"""Workspace-reuse tests for tools/agentcoder/agentcoder.py.

Every spawn used to create a NEW Paseo workspace (`paseo run --new-workspace
worktree`), so one job left a pile of worktrees behind: designer, coder,
reviewer, every re-spawn, every review round -- 130+ workspaces on a busy
project. These tests pin the reuse contract: at most ONE workspace per role
per job, created with `paseo workspace create`, recorded in job.json as
`<role>_workspace`, and reused by every later spawn via `paseo run
--workspace <id>` with the tree reset to the right commit (a dirty tree
PAUSES; it is never reset over); the optional spec `workspaces` map points
roles at EXISTING workspaces (never created, and designer and coder must not
share one). The driver never archives a workspace itself.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or __import__("shutil").which("prlimit") is None,
    reason="agentcoder drives a Linux paseo host: fakes use shebang scripts and fcntl, "
           "and the driver's preflight gate requires prlimit (skipped when absent)")

ROOT = Path(__file__).resolve().parents[1]

# Single source of truth for build_env / gitat / the fakes: load the land
# tests' module the same way tests/test_agentcoder_land_push.py does.
_spec = importlib.util.spec_from_file_location(
    "agentcoder_tool", ROOT / "tests" / "test_agentcoder_tool.py")
_ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ac)

gitat = _ac.gitat
build_env = _ac.build_env
agentcoder = _ac.agentcoder
BASE_APP = _ac.BASE_APP
_git_identity = _ac._git_identity  # the autouse git-identity fixture function


def runs(env):
    return [c for c in env.calls() if c[:1] == ["run"]]


def role_runs(env, role):
    return [c for c in runs(env) if f"AgentCoder t1 {role}" in c]


def created(env, role=None):
    out = [c for c in env.calls() if c[:2] == ["workspace", "create"]]
    if role is not None:
        out = [c for c in out if f"AgentCoder t1 {role}" in c]
    return out


def ws_arg(argv):
    return argv[argv.index("--workspace") + 1]


def head_branch(path):
    return subprocess.run(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def seed_workspaces(env, ids):
    """Register EXISTING workspaces (real git worktrees of the repo) in the fake."""
    state_path = env.logdir / "agents.json"
    state = (json.loads(state_path.read_text()) if state_path.exists()
             else {"seq": 0, "agents": {}, "workspaces": {}})
    state.setdefault("workspaces", {})
    for wid in ids:
        d = env.logdir.parent / "wts" / wid
        subprocess.run(["git", "-C", str(env.repo), "worktree", "add", "-q",
                        "-B", f"wip-{wid}", str(d), "main"], check=True)
        state["workspaces"][wid] = {"cwd": str(d), "branch": f"wip-{wid}",
                                    "name": "seed " + wid}
    json.dump(state, open(state_path, "w"))


def test_every_spawn_uses_one_workspace_per_role(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wsreuse",
                    spec_overrides={"test_reviewer_model": "opencode/some/reviewer"})
    assert env.run() == 0
    assert runs(env)
    for c in runs(env):  # the headline: NO spawn ever asks for a new workspace
        assert "--new-workspace" not in c, c
        assert "--workspace" in c, c
    job = env.job()
    ids = {job["coder_workspace"], job["designer_workspace"], job["reviewer_workspace"]}
    assert len(ids) == 3  # one per role, all distinct
    for c in runs(env):
        assert ws_arg(c) in ids, c
    assert len(created(env, "coder")) == 1
    assert len(created(env, "designer")) == 1
    assert len(created(env, "reviewer")) == 1  # rounds never create more


def test_respawn_uses_the_recorded_workspace(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wsrespawn",
                    spec_overrides={"agent_timeout": 15},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "wsrp")})
    assert env.run() == 1  # designer spawn hangs; coder recorded
    job = env.job()
    assert job["coder_workspace"] and job["designer_workspace"]
    env.scenario["hang"] = {}
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    assert len(role_runs(env, "coder")) == 1  # live recorded id: never respawned
    respawn = role_runs(env, "designer")
    assert len(respawn) == 2
    assert ws_arg(respawn[1]) == job["designer_workspace"] == env.job()["designer_workspace"]
    assert len(created(env, "designer")) == 1  # the respawn reuses, never creates


def test_dead_coder_respawn_resets_recorded_workspace(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wsdead",
                    spec_overrides={"agent_timeout": 15},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "wsdp")})
    assert env.run() == 1
    job = env.job()
    ws, cwd = job["coder_workspace"], job["coder_cwd"]
    state = json.loads((env.logdir / "agents.json").read_text())
    state["agents"][job["coder_agent"]]["status"] = "closed"  # coder dies while paused
    json.dump(state, open(env.logdir / "agents.json", "w"))
    env.scenario["hang"] = {}
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    assert env.job()["coder_workspace"] == ws
    dead = role_runs(env, "coder")
    assert len(dead) == 2 and ws_arg(dead[1]) == ws
    assert len(created(env, "coder")) == 1
    assert head_branch(cwd) == "ac/t1/coder"  # clean tree at the right branch/commit


def test_review_rounds_share_one_reviewer_workspace(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wsrev",
                    spec_overrides={"test_reviewer_model": "opencode/some/reviewer"},
                    scenario_overrides={
                        "review_replies": ["found issues\nVERDICT: CHANGES REQUESTED",
                                           "now fine\nVERDICT: APPROVE"],
                        "on_send": {"designer": [{"files": {
                            "tests/t1.cases.json": _ac.CASES_OK}}]}})
    assert env.run() == 0
    assert env.job()["review_round"] == 1
    rev = [c for c in runs(env) if "review-r" in " ".join(c)]
    assert len(rev) == 2
    ws = env.job()["reviewer_workspace"]
    assert [ws_arg(c) for c in rev] == [ws, ws]  # round 2 reuses round 1's workspace
    assert len(created(env, "reviewer")) == 1


def test_dirty_workspace_tree_pauses_respawn(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wsdirty",
                    spec_overrides={"agent_timeout": 15},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "wsdr")})
    assert env.run() == 1
    job = env.job()
    (Path(job["coder_cwd"]) / "app.py").write_text("# scribbled, uncommitted\n")
    state = json.loads((env.logdir / "agents.json").read_text())
    state["agents"][job["coder_agent"]]["status"] = "closed"
    json.dump(state, open(env.logdir / "agents.json", "w"))
    env.scenario["hang"] = {}
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 1  # the driver refuses to reset a dirty tree: Pause, not guess
    # (assert the driver's own refusal phrase: a git-level checkout refusal also
    # pauses, and a tmp path containing "dirty" would vouch for that one too)
    assert "refusing to reset" in env.job()["reason"]
    assert len(role_runs(env, "coder")) == 1  # the respawn never launched onto the dirt


def test_spec_coder_designer_same_workspace_rejected(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch, name="wsame", spec_overrides={
        "workspaces": {"coder": "wks_c1", "designer": "wks_c1"}})
    seed_workspaces(env, ["wks_c1"])
    assert env.run() == 1  # blind separation: the designer must not share the coder's tree
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "invalid-spec"
    assert "blind" in printed["reason"]
    assert not (env.jobdir / "job.json").exists()
    assert not runs(env)  # nothing spawned


def test_spec_workspace_id_missing_from_ls_rejected(tmp_path, monkeypatch, capsys):
    env = build_env(tmp_path, monkeypatch, name="wsmiss",
                    spec_overrides={"workspaces": {"coder": "wks_ghost"}})
    assert env.run() == 1  # unknown id: a clear exit before anything is spawned
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "invalid-spec" and "wks_ghost" in printed["reason"]
    assert not runs(env)


@pytest.mark.parametrize("mut,frag", [
    ({"coder": 5}, "non-empty workspace id string"),
    ({"hacker": "wks_a"}, "unknown role"),
])
def test_spec_workspaces_shape_rejected(tmp_path, monkeypatch, mut, frag, capsys):
    env = build_env(tmp_path, monkeypatch, name="wsshape",
                    spec_overrides={"workspaces": mut})
    assert env.run() == 1
    assert frag in json.loads(capsys.readouterr().out)["reason"]
    assert not runs(env)


def test_spec_workspaces_are_used_not_created(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wsuse", spec_overrides={
        "workspaces": {"coder": "wks_c", "designer": "wks_d", "reviewer": "wks_r"},
        "test_reviewer_model": "opencode/some/reviewer"})
    seed_workspaces(env, ["wks_c", "wks_d", "wks_r"])
    assert env.run() == 0
    job = env.job()
    assert not created(env)  # the driver creates NOTHING: the spec ids are used as given
    assert (job["coder_workspace"], job["designer_workspace"], job["reviewer_workspace"]) \
        == ("wks_c", "wks_d", "wks_r")
    for c in runs(env):
        assert ws_arg(c) in {"wks_c", "wks_d", "wks_r"}, c
    # the pre-existing trees were reset onto the job's branches
    assert head_branch(env.logdir.parent / "wts" / "wks_c") == "ac/t1/coder"
    assert head_branch(env.logdir.parent / "wts" / "wks_d") == "ac/t1/designer"


def test_workspace_ids_survive_pause_and_resume(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wsresume",
                    spec_overrides={"agent_timeout": 15},
                    scenario_overrides={"hang": {"run": ["designer"]},
                                        "pidfile": str(tmp_path / "wsrs")})
    assert env.run() == 1
    job = env.job()
    recorded = (job["coder_workspace"], job["designer_workspace"])
    env.scenario["hang"] = {}
    env.scen_path.write_text(json.dumps(env.scenario))
    assert env.resume() == 0
    job = env.job()
    assert (job["coder_workspace"], job["designer_workspace"]) == recorded
    assert len(created(env)) == 2  # the resume created nothing new


def test_prepare_tree_resets_clean_refuses_dirty(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wspt")
    d = tmp_path / "wspt-tree"
    gitat(env.repo, "worktree", "add", "-q", "-B", "wip", str(d), "main")
    base = subprocess.run(["git", "-C", str(env.repo), "rev-parse", "main"],
                          capture_output=True, text=True).stdout.strip()
    job = {"jobdir": str(env.jobdir), "task_id": "t1", "spec": env.spec}
    (d / "app.py").write_text("# dirt\n")
    with pytest.raises(agentcoder.Pause) as ei:
        agentcoder.prepare_tree(job, str(d), "ac/t1/coder", base, "coder")
    assert "dirty" in str(ei.value)
    gitat(d, "checkout", "--", ".")
    agentcoder.prepare_tree(job, str(d), "ac/t1/coder", base, "coder")
    assert head_branch(d) == "ac/t1/coder"
    head = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == base


def test_workspace_cwd_resolves_and_refuses_unknown(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, name="wscwd")
    seed_workspaces(env, ["wks_x"])
    assert agentcoder.workspace_cwd({}, "wks_x") == str(env.logdir.parent / "wts" / "wks_x")
    with pytest.raises(agentcoder.Pause):
        agentcoder.workspace_cwd({}, "wks_ghost")
