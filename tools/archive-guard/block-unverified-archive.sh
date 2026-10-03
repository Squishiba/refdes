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
#
# archive_workspace is checked the same way, one worktree at a time: the
# workspace's cwd is looked up in `paseo workspace ls`, and that worktree goes
# through the identical checks. A workspace the active list does not hold, or
# whose directory is already gone, has no worktree left for the sweep to
# delete, so archiving it only clears a record and is allowed.
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

# verify_worktree <cwd> <label>
# Returns 0 (allow) only when the worktree at <cwd> holds nothing the delayed
# sweep would lose; denies (exits) on any doubt. <label> names the thing being
# archived in the deny messages, e.g. "agent 'ag_x'" or "workspace 'wks_x'".
verify_worktree() {
  cwd="$1"
  local label="$2"
  local dirty branch pr_json gh_failed ahead merged_count open_or_closed_count
  local merged_json landed_pr pr_num

  # The delayed archive-worktree sweep only has anything to delete for a
  # directory Paseo itself created and manages -- that's always under
  # ~/.paseo/worktrees/. A "local_checkout" workspace (the main checkout
  # itself, or any other pre-existing directory just pointed at) was never
  # Paseo's to create, so archiving has no deletion risk there regardless of
  # git state. Checked via path, not an agent-level field -- `paseo inspect`'s
  # own output has no workspace kind/isolation field to key off directly.
  case "$cwd" in
    "$HOME"/.paseo/worktrees/*) ;;
    *) return 0 ;;
  esac

  git -C "$cwd" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

  dirty="$(git -C "$cwd" status --short 2>/dev/null || echo UNKNOWN)"
  if [ "$dirty" = "UNKNOWN" ]; then
    deny "git status failed in $cwd -- cannot verify this worktree is clean, so refusing. Check manually before archiving."
  fi
  if [ -n "$dirty" ]; then
    deny "$label worktree ($cwd) has uncommitted changes -- archiving schedules an automatic, delayed, unstoppable deletion of this worktree (Paseo's own workspace-refresh:archive-worktree sweep). Check 'git -C $cwd status' and commit+push anything real before archiving, or ask Jared."
  fi

  branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
    deny "$label worktree ($cwd) is in a detached HEAD state -- cannot identify a branch to check for a landed PR, so refusing. Verify manually."
  fi
  [ "$branch" = "main" ] && return 0

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
      deny "could not reach gh to check for a merged PR, and could not compare '$branch' against origin/main either -- refusing rather than guessing. Check manually: git -C $cwd log."
    fi
    if [ "$ahead" = "0" ]; then
      return 0
    fi
    deny "could not reach gh to check for a merged PR on '$branch', and it has $ahead commit(s) ahead of origin/main -- refusing rather than guessing whether that work landed. Check manually: git -C $cwd log."
  fi

  merged_count="$(printf '%s' "$pr_json" | jq '[.[] | select(.state == "MERGED")] | length' 2>/dev/null || echo 0)"
  if [ "$merged_count" -gt 0 ]; then
    return 0
  fi

  open_or_closed_count="$(printf '%s' "$pr_json" | jq 'length' 2>/dev/null || echo 0)"
  if [ "$open_or_closed_count" -gt 0 ]; then
    pr_num="$(printf '%s' "$pr_json" | jq -r '.[0].number')"
    deny "$label branch '$branch' has PR #$pr_num but it is not merged -- archiving now would schedule deletion of a worktree whose work has not landed. Land it first, or ask Jared."
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
    return 0
  fi

  # Still nothing landed. Safe only if the branch never actually diverged from
  # main -- otherwise this is exactly the ff2c83f shape: real commits, no PR,
  # about to be swept.
  ahead="$(git -C "$cwd" rev-list --count origin/main.."$branch" 2>/dev/null || echo "")"
  if [ -z "$ahead" ]; then
    deny "no PR found for branch '$branch' and could not compare it against origin/main -- refusing rather than guessing. Check manually: git -C $cwd log."
  fi
  if [ "$ahead" = "0" ]; then
    return 0
  fi

  deny "$label branch '$branch' has $ahead commit(s) ahead of origin/main and no PR was ever opened for it -- this is exactly the shape of work that gets permanently lost once Paseo's delayed archive-worktree sweep runs. Check 'git -C $cwd log' for what it actually did; commit/push and open a PR first if there's real work, or ask Jared."
}

# expand_home <path>: `paseo ls` prints cwds with a leading ~, `paseo workspace
# ls` prints them in full. Expand before comparing either.
expand_home() {
  printf '%s' "${1/#\~/$HOME}"
}

# workspace_listing
# Sets WS_LISTING to the active workspace list as a JSON array, or denies.
# Must not run inside $(...): deny exits the script, and a subshell would
# swallow that and leave the caller to read an empty list as "no workspaces".
workspace_listing() {
  local raw
  raw="$(paseo workspace ls --json 2>/dev/null)" || deny "paseo workspace ls failed -- cannot verify this worktree's workspace, so refusing. Check it manually."
  printf '%s' "$raw" | jq -e 'type == "array" or (type == "object" and (.workspaces | type == "array"))' >/dev/null 2>&1 \
    || deny "paseo workspace ls returned output this guard cannot read -- refusing rather than guessing."
  WS_LISTING="$(printf '%s' "$raw" | jq -c 'if type == "array" then . else .workspaces end')"
}

# agent_listing
# Sets AGENT_LISTING to the active (non-archived) agents as a JSON array, or
# denies. Same no-subshell rule as workspace_listing.
agent_listing() {
  local raw
  raw="$(paseo ls -g --json 2>/dev/null)" || deny "paseo ls failed -- cannot tell which agents are still running, so refusing. Check it manually."
  printf '%s' "$raw" | jq -e 'type == "array" or (type == "object" and (.agents | type == "array"))' >/dev/null 2>&1 \
    || deny "paseo ls returned output this guard cannot read -- refusing rather than guessing."
  AGENT_LISTING="$(printf '%s' "$raw" | jq -c 'if type == "array" then . else .agents end')"
}

# owning_workspaces <expanded cwd>
# Prints the workspace IDs whose cwd is this directory, one per line.
owning_workspaces() {
  printf '%s' "$WS_LISTING" | jq -r --arg target "$1" \
    '.[] | select(((.cwd // "") | sub("^~"; env.HOME)) == $target) | .workspaceId'
}

# unfinished_agents_in <expanded cwd>
# Prints "id status name" for every active agent in this directory whose status
# is not a finished one (idle, closed, error). Anything else, including a status
# this guard has not seen before, counts as unfinished.
unfinished_agents_in() {
  printf '%s' "$AGENT_LISTING" | jq -r --arg target "$1" '
    .[]
    | select(((.cwd // "") | sub("^~"; env.HOME)) == $target)
    | select(.status as $s | ["idle", "closed", "error"] | index($s) | not)
    | "\(.id) \(.status) \(.name // "")"'
}

# verify_workspace_call
# archive_workspace names a workspace, not an agent: look up its cwd in the
# active workspace list, refuse if any agent in it is still working, and verify
# that one worktree. Fails closed on every lookup error. A workspace missing
# from the active list is allowed: the daemon drops a workspace whose directory
# is already gone, so there is no worktree left for the sweep to delete and
# archiving only clears the record.
verify_workspace_call() {
  local ws_id ws_cwd blocking
  ws_id="$(printf '%s' "$input" | jq -r '.tool_input.workspaceId // empty')"
  [ -n "$ws_id" ] || deny "archive_workspace call had no workspaceId to verify -- refusing rather than guessing."

  workspace_listing
  ws_cwd="$(printf '%s' "$WS_LISTING" | jq -r --arg id "$ws_id" \
    'map(select(.workspaceId == $id)) | .[0].cwd // empty')"

  if [ -z "$ws_cwd" ]; then
    printf 'archive-guard: allowing workspace %s -- not in the active workspace list, so no worktree is left to sweep\n' "$ws_id" >&2
    return 0
  fi
  ws_cwd="$(expand_home "$ws_cwd")"

  # Archiving a workspace archives its agents too, and an agent still working
  # is interrupted by that. Let it finish first.
  agent_listing
  blocking="$(unfinished_agents_in "$ws_cwd")"
  if [ -n "$blocking" ]; then
    deny "workspace '$ws_id' still has agent(s) that are not finished, and archiving the workspace would interrupt them: $(printf '%s' "$blocking" | tr '\n' ';'). Let them finish, or stop them, then archive."
  fi

  [ -d "$ws_cwd" ] || return 0
  verify_worktree "$ws_cwd" "workspace '$ws_id'"
}

if [ "$tool_name" = "mcp__paseo__archive_workspace" ]; then
  verify_workspace_call
  exit 0
fi

[ "$tool_name" = "mcp__paseo__archive_agent" ] || exit 0

agent_id="$(printf '%s' "$input" | jq -r '.tool_input.agentId // empty')"
[ -n "$agent_id" ] || deny "archive_agent call had no agentId to verify -- refusing rather than guessing."

info="$(paseo inspect "$agent_id" --format json 2>/dev/null)" || deny "paseo inspect '$agent_id' failed -- cannot verify this agent is safe to archive, so refusing. Check it manually (paseo logs $agent_id)."

already_archived="$(printf '%s' "$info" | jq -r '.Archived')"
[ "$already_archived" = "true" ] && exit 0

agent_cwd="$(printf '%s' "$info" | jq -r '.Cwd // empty')"
[ -n "$agent_cwd" ] || exit 0
[ -d "$agent_cwd" ] || exit 0

# Clean and landed, or deny. A local checkout returns from here with nothing
# to leak, so the agent archive is allowed.
verify_worktree "$agent_cwd" "agent '$agent_id'"

# A Paseo-owned worktree is removed only when its workspace is archived, not
# when an agent in it is. Archiving the agent alone is what leaves a workspace
# and its worktree behind, one per finished worker. Send the archive to the
# owning workspace, which also archives this agent.
case "$agent_cwd" in
  "$HOME"/.paseo/worktrees/*) ;;
  *) exit 0 ;;
esac
workspace_listing
owners="$(owning_workspaces "$agent_cwd" | tr '\n' ' ' | sed 's/ *$//')"
if [ -n "$owners" ]; then
  deny "agent '$agent_id' runs in a Paseo-owned worktree ($agent_cwd) that workspace $owners owns. Archiving the agent alone leaves that workspace and its worktree behind. Archive the workspace instead (archive_workspace $owners): it archives this agent with it, and the worktree is removed with the workspace."
fi
exit 0
exit 0
