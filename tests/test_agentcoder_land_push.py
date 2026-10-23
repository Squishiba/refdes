"""Land-phase push tests for tools/agentcoder/agentcoder.py.

Reproduces the drv-push defect: `do_land` pushed the coder branch BY NAME
(`git push -u origin ac/<task>/coder`), which pushes the LOCAL branch of that
name. After a `resume` respawn put the coder in a deduped worktree checked out
on a differently-named branch (`ac-<task>-coder`), the slash-named local branch
is a stale ref left at the base commit by the abandoned original worktree, so
the push lands the base commit — the just-landed work is never pushed.

The fix pushes HEAD explicitly:
`git push -u origin HEAD:refs/heads/<branch_name(job,'coder')>`, fast-forward
only. These tests drive the real land phase against a real local bare `origin`
(fixtures + fake gh reused from tests/test_agentcoder_tool.py).
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or __import__("shutil").which("prlimit") is None,
    reason="agentcoder drives a Linux paseo host: fakes use shebang scripts and fcntl, "
           "and the driver's preflight gate requires prlimit (skipped when absent)")

ROOT = Path(__file__).resolve().parents[1]

# Reuse the fixtures, fakes, and git-identity fixture from the land tests file.
# Loading it as a module (not importing test_agentcoder_tool, which pytest's
# rootdir bootstrap makes importable too) keeps a single source of truth for
# build_env / gitat / the bare-origin scenario.
_spec = importlib.util.spec_from_file_location(
    "agentcoder_tool", ROOT / "tests" / "test_agentcoder_tool.py")
_ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ac)

# The land tests' module-scoped autouse git-identity fixture is what makes the
# real git commits in build_env deterministic. Re-export the pieces we use.
gitat = _ac.gitat
build_env = _ac.build_env
agentcoder = _ac.agentcoder

# Re-declare the autouse git-identity fixture locally: it is module-scoped in
# test_agentcoder_tool.py and NOT auto-discovered across modules.
_git_identity = _ac._git_identity  # the fixture function object


def _origin_repo(env):
    return Path(env.spec["repo"]).parent / "origin.git"


def _origin_ref(env, branch):
    """Resolve a ref inside the bare origin (empty string if it does not exist)."""
    p = subprocess.run(["git", "-C", str(_origin_repo(env)), "rev-parse", "--verify", "-q", branch],
                       capture_output=True, text=True)
    return p.stdout.strip()


def _head(env, path):
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _dedup_rename(job):
    """Simulate a respawn-deduped coder worktree: the checked-out branch is the
    dash form `ac-<task>-coder`, while a stale slash-named branch `ac/<task>/coder`
    is left behind at the base commit (the abandoned original worktree's branch).
    """
    wt = job["coder_cwd"]
    slash = agentcoder.branch_name(job, "coder")          # ac/t1/coder
    dash = agentcoder.branch_name(job, "coder").replace("/", "-")  # ac-t1-coder
    # Move this worktree's checkout onto the dash-named branch at current HEAD
    # (the gated coder commit), detaching the slash branch.
    gitat(wt, "checkout", "-q", "-B", dash)
    # Force the now-free slash branch back to base: the stale original-worktree ref.
    gitat(wt, "branch", "-f", slash, job["base_sha"])
    return wt, slash, dash


def test_land_pushes_head_when_coder_branch_is_deduped_renamed(tmp_path, monkeypatch):
    """The landed HEAD must reach the expected remote branch even when the coder
    worktree's checked-out branch has a DIFFERENT (deduped) name. Fails on the
    push-by-name code: the stale slash branch (base) is pushed, not the landed HEAD.
    """
    env = build_env(tmp_path, monkeypatch, name="landpush")
    real_land = agentcoder.do_land

    def land(job):
        _dedup_rename(job)
        return real_land(job)

    monkeypatch.setitem(agentcoder.HANDLERS, "land", land)
    assert env.run() == 0
    job = env.job()
    wt_head = _head(env, job["coder_cwd"])
    remote = _origin_ref(env, agentcoder.branch_name(job, "coder"))
    assert remote == wt_head, (
        f"origin refs/heads/{agentcoder.branch_name(job, 'coder')} = {remote} "
        f"must equal the worktree HEAD {wt_head}: the just-landed commit must be pushed")
    # pushed_sha is the worktree's HEAD (landed commit), unchanged by the fix.
    assert job["pushed_sha"] == wt_head


def test_land_pushes_expected_branch_when_names_already_match(tmp_path, monkeypatch):
    """Control: when the coder worktree's checked-out branch already has the
    expected slash name, land pushes the landed HEAD to it. Must pass on both the
    old (push-by-name) and the fixed (push-by-refspec) code.
    """
    env = build_env(tmp_path, monkeypatch, name="landpushctl")
    assert env.run() == 0
    job = env.job()
    # the worktree is checked out on the expected slash branch (fake paseo uses -B)
    branch = subprocess.run(["git", "-C", job["coder_cwd"], "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert branch == agentcoder.branch_name(job, "coder")
    wt_head = _head(env, job["coder_cwd"])
    remote = _origin_ref(env, agentcoder.branch_name(job, "coder"))
    assert remote == wt_head
    assert job["pushed_sha"] == wt_head
