"""PR size gate: budget added lines under src/ per pull request.

Why: single-PR features with 600-1500 added src lines (see #382, #393)
consistently needed 2-3 review rounds, while small slices review in one
pass. This makes "keep PRs small" mechanical: over BUDGET src additions
fails the check unless the PR carries the `size-exempt` label.

Stdlib only, no repo imports: CI runs it with a bare checkout, and unit
tests feed it numstat text directly (no git, no network).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

BUDGET = 350
EXEMPT_LABEL = "size-exempt"

# PRs numbered below this are never failed: open PRs at the time the gate
# shipped (#396, #398, #399) predate it and must not go red from a
# workflow change. Raise this only deliberately, never to bypass the gate.
FIRST_ENFORCED_PR = 400

SRC_PREFIX = "src/"

# numstat rename forms: "src/{a.py => b.py}" (prefix + suffix shared) or
# "old/a.py => new/b.py" (full paths). Braces must close on the same
# segment; a line-wide fallback would happily turn the "a" of
# "a.py => b.py" into a bogus "new" directory.
_BRACE_RENAME_RE = re.compile(r"^(?P<pre>.*)\{(?P<old>[^{}]*) => (?P<new>[^{}]*)\}(?P<post>.*)$")
_FULL_RENAME_RE = re.compile(r"^(?P<old>.*) => (?P<new>.*)$")


def new_path_of(path: str) -> str:
    """Resolve a numstat path (which may name a rename) to the NEW path."""
    brace = _BRACE_RENAME_RE.match(path)
    if brace:
        return brace["pre"] + brace["new"] + brace["post"]
    full = _FULL_RENAME_RE.match(path)
    if full:
        return full["new"]
    return path


def parse_numstat(numstat_text: str) -> list[tuple[int, int, str]]:
    """Parse `git diff --numstat` output into (added, deleted, new_path) rows.

    A '-' added count is a binary file and counts as 0 added lines.
    """
    rows: list[tuple[int, int, str]] = []
    for line in numstat_text.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        added_raw = fields[0]
        added = 0 if added_raw == "-" else int(added_raw)
        path = new_path_of("\t".join(fields[2:]))
        rows.append((added, 0, path))
    return rows


def count_src_additions(numstat_text: str) -> int:
    """Sum added lines under src/ from `git diff --numstat` output."""
    return sum(added for added, _, path in parse_numstat(numstat_text) if path.startswith(SRC_PREFIX))


def is_exempt(labels: str) -> bool:
    """True if the comma-separated label list carries the waiver label."""
    return EXEMPT_LABEL in {label.strip() for label in labels.split(",") if label.strip()}


def over_budget(total: int, pr_number: int | None, exempt: bool) -> bool:
    """Decide the verdict.

    PRs below FIRST_ENFORCED_PR are grandfathered (never failed); the
    `size-exempt` label waives the budget; at exactly BUDGET the PR is
    within budget (over means strictly more). A missing PR number fails
    closed: the gate enforces, and CI always supplies the number.
    """
    if pr_number is not None and pr_number < FIRST_ENFORCED_PR:
        return False
    if exempt:
        return False
    return total > BUDGET


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-sha", default=os.environ.get("PR_BASE_SHA", ""))
    parser.add_argument("--head-sha", default=os.environ.get("PR_HEAD_SHA", ""))
    parser.add_argument(
        "--pr-number",
        type=int,
        default=int(os.environ.get("PR_NUMBER", "0")) or None,
    )
    parser.add_argument("--labels", default=os.environ.get("PR_LABELS", ""))
    args = parser.parse_args(argv)

    if not args.base_sha or not args.head_sha:
        print("pr-size: need --base-sha and --head-sha (or PR_BASE_SHA/PR_HEAD_SHA)", file=sys.stderr)
        return 2
    result = subprocess.run(
        ["git", "diff", "--numstat", f"{args.base_sha}...{args.head_sha}"],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = parse_numstat(result.stdout)
    total = sum(added for added, _, path in rows if path.startswith(SRC_PREFIX))
    src_rows = sorted(
        ((added, path) for added, _, path in rows if path.startswith(SRC_PREFIX)),
        reverse=True,
    )
    exempt = is_exempt(args.labels)
    fail = over_budget(total, args.pr_number, exempt)

    print(f"pr-size: {total} added src lines (budget {BUDGET}, label {args.labels or 'none'})")
    for added, path in src_rows[:10]:
        print(f"  {added:5d}  {path}")
    if args.pr_number is not None and args.pr_number < FIRST_ENFORCED_PR:
        print(f"pr-size: grandfathered (PR #{args.pr_number} < {FIRST_ENFORCED_PR}) — not enforced")
    elif total > BUDGET and exempt:
        print(f"pr-size: OVER BUDGET by {total - BUDGET} lines — waived by the `{EXEMPT_LABEL}` label.")
        print("pr-size: LOUD NOTICE — the review burden of this PR is on the reviewer, not the gate.")
    elif total > BUDGET:
        print(f"pr-size: OVER BUDGET by {total - BUDGET} lines.")
        print("  Split the PR into reviewable slices, e.g.:")
        print("    - schema/types + tests first, then the feature that uses them")
        print("    - CLI + tests in a separate follow-up PR")
        print(f"  If it genuinely cannot be split, add the `{EXEMPT_LABEL}` label to waive this check.")
    elif exempt:
        print(f"pr-size: within budget; `{EXEMPT_LABEL}` label noted, not needed")
    print(
        f"verdict: {'FAIL' if fail else 'PASS'} "
        f"({total}/{BUDGET} src additions, PR #{args.pr_number if args.pr_number is not None else '?'})"
    )
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
