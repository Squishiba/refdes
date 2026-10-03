#!/usr/bin/env bash
# PreToolUse guard (mcp__paseo__archive_agent | mcp__paseo__archive_workspace):
# an archived Paseo agent's worktree is NOT just hidden -- Paseo runs a
# delayed, automatic sweep (daemon log: "workspace-refresh:archive-worktree")
# that deletes the worktree directory and its .git/worktrees/ metadata some
# time after archiving, with no further action and no way to cancel it.
# Verified empirically 2026-10-02: a Codex Sol worker (write-locks-everywhere)
# was archived on the unverified assumption it "never started meaningful
# work"; it had actually built a full write_lock.py primitive, wired it into
# five files, and gotten tests passing -- all uncommitted, all gone once the
# sweep ran. This is the third time a worker got archived incorrectly, and
# writing it down in memory alone did not stop a fourth time -- see
# memory/ask-before-killing-workers.md.
#
# This hook makes the actual invariant mechanical: only archive an agent
# whose worktree is clean AND whose current branch's content has genuinely
# landed -- either a merged PR for the branch name, or (fallback) HEAD being
# an ancestor of some merged PR's head commit. The fallback exists because
# Paseo renames a local branch when the real name is already checked out in
# another worktree (`living-notes-h5-sealing` -> `...-1`), and a name lookup
# then finds no PR for a branch whose commits already landed: a read-only
# verification worktree sitting on a commit squash-merged in PR #157 was
# denied that way. Squash-merged commits are not ancestors of main, so the
# comparison is against the merged PR's headRefOid, never against main.
# On any doubt -- git/gh failures, an open or unmerged PR, commits with no PR
# found, a detached HEAD -- deny and say why, rather than assume safety.
# The ancestry fallback can only ever turn a deny into an allow, never the
# other way round.
set -euo pipefail

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty')"

deny() {
  jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# landed_by_ancestry <merged-pr-json>
# True if HEAD is some already-merged PR's head commit or an ancestor of it.
# Uses only SHAs from gh -- never branch names, which are exactly what Paseo
# mangles. A merged PR's headRefOid is the tip that branch was merged from, so
# a worktree sitting on squash-merged work is that commit or an ancestor of it.
# Missing objects are fetched before comparing; a fetch that fails just means
# that one candidate cannot be compared, and the caller falls through to its
# deny path -- so this function can only ever produce an allow.
landed_by_ancestry() {
  local merged_json="$1"
  local oid remote="" fetched=0 targeted=0
  remote="$(git -C "$cwd" config --get remote.origin.url 2>/dev/null || true)"
  [ -n "$remote" ] || return 1
  while IFS= read -r oid; do
    case "$oid" in
      '' | *[!0-9a-fA-F]*) continue ;;
    esac
    [ "${#oid}" -ge 7 ] || continue
    if ! git -C "$cwd" cat-file -e "${oid}^{commit}" 2>/dev/null; then
      # Not local yet: the PR head moved after this worktree last fetched, or
      # the branch was never fetched here. One plain fetch first (one round
      # trip, brings every reachable head), then a few exact-SHA fetches for
      # heads whose branch has since been deleted -- capped, because a hook
      # must not turn into two hundred network calls.
      if [ "$fetched" = 0 ]; then
        fetched=1
        git -C "$cwd" fetch --quiet --no-tags origin >/dev/null 2>&1 || true
      fi
      if ! git -C "$cwd" cat-file -e "${oid}^{commit}" 2>/dev/null && [ "$targeted" -lt 3 ]; then
        targeted=$((targeted + 1))
        git -C "$cwd" fetch --quiet --no-tags origin "$oid" >/dev/null 2>&1 || true
      fi
      git -C "$cwd" cat-file -e "${oid}^{commit}" 2>/dev/null || continue
    fi
    if git -C "$cwd" merge-base --is-ancestor HEAD "$oid" 2>/dev/null; then
      return 0
    fi
  done < <(printf '%s' "$merged_json" | jq -r '.[].headRefOid // empty' 2>/dev/null)
  return 1
}

if [ "$tool_name" = "mcp__paseo__archive_workspace" ]; then
  deny "archive_workspace archives and removes everything the workspace owns in one call -- too broad to verify mechanically per-agent. Archive the specific finished agent(s) with archive_agent instead (each one gets checked for uncommitted/unlanded work), or ask Jared if the whole workspace genuinely needs to go."
fi

[ "$tool_name" = "mcp__paseo__archive_agent" ] || exit 0

agent_id="$(printf '%s' "$input" | jq -r '.tool_input.agentId // empty')"
[ -n "$agent_id" ] || deny "archive_agent call had no agentId to verify -- refusing rather than guessing."

info="$(paseo inspect "$agent_id" --format json 2>/dev/null)" || deny "paseo inspect '$agent_id' failed -- cannot verify this agent is safe to archive, so refusing. Check it manually (paseo logs $agent_id)."

already_archived="$(printf '%s' "$info" | jq -r '.Archived')"
[ "$already_archived" = "true" ] && exit 0

cwd="$(printf '%s' "$info" | jq -r '.Cwd // empty')"
[ -n "$cwd" ] || exit 0
[ -d "$cwd" ] || exit 0

# The delayed archive-worktree sweep only has anything to delete for a
# directory Paseo itself created and manages -- that's always under
# ~/.paseo/worktrees/. A "local_checkout" workspace (the main checkout
# itself, or any other pre-existing directory just pointed at) was never
# Paseo's to create, so archiving the agent has no deletion risk there
# regardless of git state. Checked via path, not an agent-level field --
# `paseo inspect`'s own output has no workspace kind/isolation field to key
# off directly.
case "$cwd" in
  "$HOME"/.paseo/worktrees/*) ;;
  *) exit 0 ;;
esac

git -C "$cwd" rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

dirty="$(git -C "$cwd" status --short 2>/dev/null || echo UNKNOWN)"
if [ "$dirty" = "UNKNOWN" ]; then
  deny "git status failed in $cwd -- cannot verify this worktree is clean, so refusing. Check manually before archiving."
fi
if [ -n "$dirty" ]; then
  deny "agent '$agent_id' worktree ($cwd) has uncommitted changes -- archiving schedules an automatic, delayed, unstoppable deletion of this worktree (Paseo's own workspace-refresh:archive-worktree sweep). Check 'paseo logs $agent_id' for what it was doing; commit+push anything real before archiving, or ask Jared."
fi

branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
  deny "agent '$agent_id' worktree ($cwd) is in a detached HEAD state -- cannot identify a branch to check for a landed PR, so refusing. Verify manually."
fi
[ "$branch" = "main" ] && exit 0

pr_json="$( (cd "$cwd" && gh pr list --head "$branch" --state all --json state,mergedAt,number --limit 5) 2>/dev/null )" || pr_json=""
if [ -z "$pr_json" ]; then
  gh_failed=1
else
  gh_failed=0
fi

if [ "$gh_failed" = "1" ]; then
  # gh failed outright (network, auth, etc) rather than returning an empty
  # list -- distinguish by checking the branch's relationship to main instead
  # of assuming either way. The ancestry fallback needs gh's merged-PR list
  # too, so there is nothing to fall back to here; this stays name-free.
  ahead="$(git -C "$cwd" rev-list --count origin/main.."$branch" 2>/dev/null || echo "")"
  if [ -z "$ahead" ]; then
    deny "could not reach gh to check for a merged PR, and could not compare '$branch' against origin/main either -- refusing rather than guessing. Check manually: paseo logs $agent_id, git -C $cwd log."
  fi
  if [ "$ahead" = "0" ]; then
    exit 0
  fi
  deny "could not reach gh to check for a merged PR on '$branch', and it has $ahead commit(s) ahead of origin/main -- refusing rather than guessing whether that work landed. Check manually: paseo logs $agent_id, git -C $cwd log."
fi

merged_count="$(printf '%s' "$pr_json" | jq '[.[] | select(.state == "MERGED")] | length' 2>/dev/null || echo 0)"
if [ "$merged_count" -gt 0 ]; then
  exit 0
fi

open_or_closed_count="$(printf '%s' "$pr_json" | jq 'length' 2>/dev/null || echo 0)"
if [ "$open_or_closed_count" -gt 0 ]; then
  pr_num="$(printf '%s' "$pr_json" | jq -r '.[0].number')"
  deny "agent '$agent_id' branch '$branch' has PR #$pr_num but it is not merged -- archiving now would schedule deletion of a worktree whose work has not landed. Land it first, or ask Jared."
fi

# No PR at all for this branch name. Two shapes reach here: work that never
# opened a PR (must be denied), and work whose PR exists and landed but whose
# *local* branch name was mangled by Paseo, so the name lookup could not find
# it. Try ancestry before deciding -- an allow here is backed by a merged PR's
# own head commit, not by a name.
merged_json="$( (cd "$cwd" && gh pr list --state merged --json headRefOid,number --limit 200) 2>/dev/null )" || merged_json=""
if [ -n "$merged_json" ] && landed_by_ancestry "$merged_json"; then
  landed_pr="$(printf '%s' "$merged_json" | jq -r --arg head "$(git -C "$cwd" rev-parse HEAD 2>/dev/null || echo '')" \
    'map(select(.headRefOid == $head)) | .[0].number // empty' 2>/dev/null || true)"
  # Allow, silently: hooks emit nothing on allow, and a stray stdout line here
  # would be parsed as hook JSON. The PR number is only resolved for the log
  # line below, which goes to stderr and is not part of the hook protocol.
  printf 'archive-guard: allowing %s -- HEAD is contained in merged PR%s%s\n' \
    "$branch" "${landed_pr:+ #}" "${landed_pr:-}" >&2 2>/dev/null || true
  exit 0
fi

# Still nothing landed. Safe only if the branch never actually diverged from
# main -- otherwise this is exactly the ff2c83f shape: real commits, no PR,
# about to be swept.
ahead="$(git -C "$cwd" rev-list --count origin/main.."$branch" 2>/dev/null || echo "")"
if [ -z "$ahead" ]; then
  deny "no PR found for branch '$branch' and could not compare it against origin/main -- refusing rather than guessing. Check manually: paseo logs $agent_id."
fi
if [ "$ahead" = "0" ]; then
  exit 0
fi

deny "agent '$agent_id' branch '$branch' has $ahead commit(s) ahead of origin/main and no PR was ever opened for it -- this is exactly the shape of work that gets permanently lost once Paseo's delayed archive-worktree sweep runs. Check 'paseo logs $agent_id' for what it actually did; commit/push and open a PR first if there's real work, or ask Jared."
