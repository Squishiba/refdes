#!/usr/bin/env bash
# Offline test runner for block-unverified-archive.sh (the Paseo archive
# safety guard). Run it as:  tools/archive-guard/test-block-unverified-archive.sh
#
# Nothing here reaches the network, a real gh, a real paseo, or the real
# ~/.paseo:
#   * fake `gh` and `paseo` executables go first on PATH, and answer from env
#     vars set per case (see the stubs written into $work/bin below)
#   * HOME is overridden per hook invocation, which is what satisfies the
#     hook's "$HOME/.paseo/worktrees/..." gate inside the scratch tree
#   * the git half runs for real: a bare "origin", a main checkout, and one
#     clone per case standing in for the agent's worktree
#
# Every case states its expected verdict explicitly. Exit status is 0 only if
# every case matched.
#
# Usage: test-block-unverified-archive.sh [-k]
#   -k  keep the scratch tree (its path is printed) instead of deleting it
set -uo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# HOOK_PATH lets you point the same cases at a different copy of the guard --
# e.g. the live one in .claude/hooks/, to confirm these cases really do catch
# the bug the fallback fixes.
hook="${HOOK_PATH:-$here/block-unverified-archive.sh}"
scratch_root="${SCRATCH_DIR:-$here/../../.scratch}"
mkdir -p "$scratch_root"
scratch_root="$(cd -- "$scratch_root" && pwd)"

keep=0
[ "${1:-}" = "-k" ] && keep=1

if [ ! -f "$hook" ]; then
  printf 'no hook next to this script (looked for %s)\n' "$hook" >&2
  exit 2
fi
for dep in git jq; do
  command -v "$dep" >/dev/null 2>&1 || { printf 'missing dependency: %s\n' "$dep" >&2; exit 2; }
done

work="$(mktemp -d "$scratch_root/archive-guard-tests.XXXXXX")" || exit 2
cleanup() {
  # Only ever removes this run's own mktemp directory.
  if [ "$keep" = 0 ] && [ -d "$work" ]; then
    case "$work" in
      "$scratch_root"/archive-guard-tests.*) rm -rf -- "$work" ;;
    esac
  fi
}
trap cleanup EXIT

# --------------------------------------------------------------------------
# stub binaries
# --------------------------------------------------------------------------
mkdir -p "$work/bin"

cat >"$work/bin/gh" <<'STUB'
#!/usr/bin/env bash
# Fake `gh pr list`. Offline: every answer comes from an env var.
#   FAKE_GH_EXIT         non-empty -> print to stderr and exit with that code
#   FAKE_GH_HEAD_MATCH   the --head value this fake has a PR for at all
#   FAKE_GH_HEAD_JSON    the answer for that --head lookup
#   FAKE_GH_MERGED_JSON  the answer for a `--state merged` lookup
# A --head lookup for any other branch name answers `[]`, which is exactly the
# real gh behaviour that motivated the ancestry fallback: Paseo's mangled local
# name (`foo-1`) has no PR of its own.
set -u
if [ -n "${FAKE_GH_EXIT:-}" ]; then
  echo "fake gh: simulated gh failure" >&2
  exit "$FAKE_GH_EXIT"
fi
head="" state=""
args=("$@") i=0
while [ "$i" -lt "${#args[@]}" ]; do
  case "${args[$i]}" in
    --head)  i=$((i + 1)); head="${args[$i]:-}" ;;
    --state) i=$((i + 1)); state="${args[$i]:-}" ;;
  esac
  i=$((i + 1))
done
if [ -n "$head" ]; then
  if [ "$head" = "${FAKE_GH_HEAD_MATCH:-}" ]; then
    printf '%s\n' "${FAKE_GH_HEAD_JSON:-[]}"
  else
    printf '[]\n'
  fi
  exit 0
fi
if [ "$state" = "merged" ]; then
  printf '%s\n' "${FAKE_GH_MERGED_JSON:-[]}"
  exit 0
fi
printf '[]\n'
STUB

cat >"$work/bin/paseo" <<'STUB'
#!/usr/bin/env bash
# Fake `paseo inspect <id> --format json`: dumps the JSON named by
# PASEO_STUB_JSON, or fails outright when PASEO_STUB_FAIL=1.
set -u
if [ "${PASEO_STUB_FAIL:-0}" = "1" ]; then
  echo "fake paseo: simulated inspect failure" >&2
  exit 1
fi
[ "${1:-}" = "inspect" ] || { echo "fake paseo: unsupported args: $*" >&2; exit 2; }
cat "$PASEO_STUB_JSON"
STUB

chmod +x "$work/bin/gh" "$work/bin/paseo"

# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------
pass=0 fail=0

record() { # PASS|FAIL  <case>  <detail>
  if [ "$1" = PASS ]; then
    pass=$((pass + 1)); printf 'PASS  %-54s %s\n' "$2" "$3"
  else
    fail=$((fail + 1)); printf 'FAIL  %-54s %s\n' "$2" "$3"
  fi
}

reset_env() {
  FAKE_GH_EXIT=""
  FAKE_GH_HEAD_MATCH=""
  FAKE_GH_HEAD_JSON='[]'
  FAKE_GH_MERGED_JSON='[]'
  PASEO_STUB_FAIL=0
  TOOL_NAME="mcp__paseo__archive_agent"
}

write_inspect() { # <case dir> <cwd>
  jq -n --arg cwd "$2" '{Archived: false, Cwd: $cwd, Id: "ag_test", Status: "running"}' \
    >"$1/inspect.json"
}

# check <case name> <ALLOW|DENY> <case dir> <worktree path>
check() {
  local name="$1" expected="$2" dir="$3" cwd="$4"
  local out rc decision reason
  out="$(
    export HOME="$dir/home"
    export PATH="$work/bin:$PATH"
    export PASEO_STUB_JSON="$dir/inspect.json" PASEO_STUB_FAIL="$PASEO_STUB_FAIL"
    export FAKE_GH_EXIT FAKE_GH_HEAD_MATCH FAKE_GH_HEAD_JSON FAKE_GH_MERGED_JSON
    export TOOL_NAME
    printf '{"tool_name":"%s","tool_input":{"agentId":"ag_test"}}' "$TOOL_NAME" \
      | bash "$hook" 2>"$dir/hook.err"
  )"
  rc=$?

  if [ "$rc" -ne 0 ]; then
    record FAIL "$name" "hook exited $rc (it must always exit 0); stderr: $(tr '\n' ' ' <"$dir/hook.err" | cut -c1-160)"
    return
  fi

  if [ -z "$out" ]; then
    decision=ALLOW
  else
    decision="$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "MALFORMED"' 2>/dev/null)"
    # A deny must also carry the exact envelope the original hook emits.
    if [ "$decision" = "deny" ]; then
      jq -e '.hookSpecificOutput.hookEventName == "PreToolUse"
             and (.hookSpecificOutput.permissionDecisionReason | type == "string")
             and (.hookSpecificOutput.permissionDecisionReason | length > 0)' \
        <<<"$out" >/dev/null 2>&1 || decision=MALFORMED
    fi
  fi

  case "$decision" in
    deny) decision=DENY; reason=" | $(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecisionReason' | cut -c1-70)..." ;;
    ALLOW) reason="" ;;
    *) reason=" raw stdout: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-120)" ;;
  esac

  if [ "$decision" = "$expected" ]; then
    record PASS "$name" "$expected$reason"
  else
    record FAIL "$name" "expected $expected, got $decision$reason"
  fi
}

assert() { # <case name> <0|1 from a shell test> <detail>
  if [ "$2" = 0 ]; then record PASS "$1" "$3"; else record FAIL "$1" "$3"; fi
}

# --------------------------------------------------------------------------
# git fixtures
# --------------------------------------------------------------------------
fresh_repo() { # <case dir>: bare origin + main checkout holding one commit
  local d="$1"
  mkdir -p "$d/origin" "$d/main" "$d/home/.paseo/worktrees"
  git -c init.defaultBranch=main init --bare -q "$d/origin"
  printf 'refdes archive-guard fixture\n' >"$d/main/README.md"
  git -c init.defaultBranch=main init -q "$d/main"
  git -C "$d/main" config user.name fixture
  git -C "$d/main" config user.email fixture@example.invalid
  git -C "$d/main" add README.md
  git -C "$d/main" commit -qm 'base: archive-guard fixture'
  git -C "$d/main" remote add origin "$d/origin"
  git -C "$d/main" push -q origin main
}

# new_worktree <case dir> <local branch name>: a clone of origin standing in
# for the agent's Paseo worktree, under the fake HOME.
new_worktree() {
  local d="$1" b="$2" wt
  wt="$d/home/.paseo/worktrees/ws-$b/agent"
  mkdir -p "$(dirname "$wt")"
  git clone -q --no-tags -b main "$d/origin" "$wt" >/dev/null 2>&1
  git -C "$wt" config user.name fixture
  git -C "$wt" config user.email fixture@example.invalid
  [ "$b" = main ] || git -C "$wt" checkout -q -b "$b"
  write_inspect "$d" "$wt"
  printf '%s\n' "$wt"
}

commit_in() { # <repo> <msg>: one new commit, prints its sha
  local d="$1" m="$2"
  printf '%s %s\n' "$RANDOM$m" "$m" >"$d/notes.md"
  git -C "$d" add notes.md
  git -C "$d" commit -qm "$m"
  git -C "$d" rev-parse HEAD
}

# ==========================================================================
# cases
# ==========================================================================

# 1. The regression this guard was missing: Paseo checked the PR's branch out
#    under a mangled local name (`-1` suffix), so `gh pr list --head` finds
#    nothing, and the squash-merged commits are not ancestors of main either.
#    Only ancestry against the merged PR's headRefOid can allow this.
d="$work/01-ancestry-mangled"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" living-notes-h5-sealing-1)"
A="$(commit_in "$wt" 'feat(seal): history-backed sealing')"
git -C "$wt" push -q origin 'HEAD:refs/heads/living-notes-h5-sealing'
FAKE_GH_HEAD_MATCH="living-notes-h5-sealing"
FAKE_GH_HEAD_JSON='[{"state":"MERGED","mergedAt":"2026-10-01T00:00:00Z","number":157}]'
FAKE_GH_MERGED_JSON="[{\"headRefOid\":\"$A\",\"number\":157}]"
check 'merged PR by ancestry, mangled local name' ALLOW "$d" "$wt"

# 2. Same shape, but the PR has not been merged -- ancestry has nothing to
#    match against (the merged list is empty), so it stays a deny.
d="$work/02-unmerged"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" living-notes-h5-sealing-1)"
A="$(commit_in "$wt" 'feat(seal): history-backed sealing')"
git -C "$wt" push -q origin 'HEAD:refs/heads/living-notes-h5-sealing'
FAKE_GH_HEAD_MATCH="living-notes-h5-sealing"
FAKE_GH_HEAD_JSON='[{"state":"OPEN","mergedAt":null,"number":157}]'
FAKE_GH_MERGED_JSON='[]'
check 'same shape but PR unmerged' DENY "$d" "$wt"

# 3. Real commits, no PR anywhere: the shape that used to get work deleted.
d="$work/03-no-pr"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" write-inventory-everywhere)"
commit_in "$wt" 'docs: inventory of every file refdes writes' >/dev/null
FAKE_GH_HEAD_JSON='[]'
FAKE_GH_MERGED_JSON='[]'
check 'unpushed commits, no PR at all' DENY "$d" "$wt"

# 4. Dirty beats landed: even with a merged PR right overhead, uncommitted
#    work is not safe to sweep.
d="$work/04-dirty"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" living-notes-h5-sealing-1)"
A="$(commit_in "$wt" 'feat(seal): history-backed sealing')"
git -C "$wt" push -q origin 'HEAD:refs/heads/living-notes-h5-sealing'
printf 'half-finished thought\n' >"$wt/draft.md"
FAKE_GH_HEAD_MATCH="living-notes-h5-sealing"
FAKE_GH_HEAD_JSON='[{"state":"MERGED","mergedAt":"2026-10-01T00:00:00Z","number":157}]'
FAKE_GH_MERGED_JSON="[{\"headRefOid\":\"$A\",\"number\":157}]"
check 'dirty worktree (merged PR overhead)' DENY "$d" "$wt"

# 5. gh broken is not gh saying "no PR". Fail closed.
d="$work/05-gh-fails"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" locking-write-through)"
commit_in "$wt" 'feat(lock): write_lock primitive' >/dev/null
FAKE_GH_EXIT=1
check 'gh fails outright, branch ahead of main' DENY "$d" "$wt"

# 6. Plain main, clean: nothing to lose.
d="$work/06-clean-main"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" main)"
check 'clean worktree at main' ALLOW "$d" "$wt"

# --- extra cases: the checks the fallback must not have disturbed ----------

# 7. A merged PR overhead proves the deny really comes from the detached-HEAD
#    check and not from the ancestry lookup.
d="$work/07-detached"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" living-notes-h5-sealing-1)"
A="$(commit_in "$wt" 'feat(seal): history-backed sealing')"
git -C "$wt" push -q origin "HEAD:refs/heads/living-notes-h5-sealing"
git -C "$wt" checkout -q --detach "$A"
FAKE_GH_HEAD_MATCH="living-notes-h5-sealing"
FAKE_GH_MERGED_JSON="[{\"headRefOid\":\"$A\",\"number\":157}]"
check 'detached HEAD (merged PR overhead)' DENY "$d" "$wt"

# 8. A PR found by name that is not merged keeps its old, specific deny.
d="$work/08-open-pr-by-name"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" locking-write-through)"
commit_in "$wt" 'feat(lock): write_lock primitive' >/dev/null
FAKE_GH_HEAD_MATCH="locking-write-through"
FAKE_GH_HEAD_JSON='[{"state":"OPEN","mergedAt":null,"number":161}]'
FAKE_GH_MERGED_JSON='[]'
check 'open PR found by branch name' DENY "$d" "$wt"

# 9. Parity check on the gh-failure path: the fallback may only ever allow
#    more, and a branch that never diverged from main was allowed before.
d="$work/09-gh-fails-never-diverged"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" docs/typo-sweep)"
FAKE_GH_EXIT=1
check 'gh fails but branch never diverged from main' ALLOW "$d" "$wt"

# 10. paseo inspect failing means we know nothing: deny.
d="$work/10-inspect-fails"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" main)"
PASEO_STUB_FAIL=1
check 'paseo inspect fails' DENY "$d" "$wt"

# 11. archive_workspace is denied outright, whatever the git state.
d="$work/11-workspace-tool"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" main)"
TOOL_NAME="mcp__paseo__archive_workspace"
check 'archive_workspace call' DENY "$d" "$wt"

# 12. The merged PR head is a commit this worktree has never seen (the PR
#     branch took another commit after this worktree last fetched). The guard
#     must fetch the object, then allow on ancestry.
d="$work/12-fetch-missing-head"; fresh_repo "$d"; reset_env
wt="$(new_worktree "$d" living-notes-h5-sealing-1)"
A="$(commit_in "$wt" 'feat(seal): history-backed sealing')"
git -C "$wt" push -q origin 'HEAD:refs/heads/living-notes-h5-sealing'
git clone -q --no-tags -b living-notes-h5-sealing "$d/origin" "$d/prside" >/dev/null 2>&1
git -C "$d/prside" config user.name fixture
git -C "$d/prside" config user.email fixture@example.invalid
B="$(commit_in "$d/prside" 'fix(seal): address review on #157')"
git -C "$d/prside" push -q origin living-notes-h5-sealing
FAKE_GH_HEAD_MATCH="living-notes-h5-sealing"
FAKE_GH_HEAD_JSON='[{"state":"MERGED","mergedAt":"2026-10-01T00:00:00Z","number":157}]'
FAKE_GH_MERGED_JSON="[{\"headRefOid\":\"$B\",\"number\":157}]"
if git -C "$wt" cat-file -e "${B}^{commit}" 2>/dev/null; then
  assert 'merged PR head absent locally (setup)' 1 'fixture bug: the head commit was already local'
else
  assert 'merged PR head absent locally (setup)' 0 'the merged head commit was not local before the run'
fi
check 'merged PR head fetched on demand, then ancestry' ALLOW "$d" "$wt"
if git -C "$wt" cat-file -e "${B}^{commit}" 2>/dev/null; then
  assert 'merged PR head fetched on demand' 0 'the guard fetched the missing object before comparing'
else
  assert 'merged PR head fetched on demand' 1 'the head commit is still missing locally'
fi

# ==========================================================================
printf '\n%d passed, %d failed  (scratch: %s)\n' "$pass" "$fail" "$work"
[ "$fail" -eq 0 ] || exit 1
