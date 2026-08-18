"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import build as build_mod
from . import citations as citations_mod
from . import ids as ids_mod
from . import lifecycle as lifecycle_mod
from . import parse as parse_mod
from . import render as render_mod
from . import seal as seal_mod
from .model import INVALIDATE, Project
from .schema import SchemaError, load_project


def _fix_console() -> None:
    """Windows consoles default to cp1252, which cannot print Ω, µ, or ±."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _load(args, require_ids: bool = True) -> Project:
    project = load_project(config_path=args.config)
    parse_mod.load_items(project, require_ids=require_ids)
    return project


def _visible(
    project: Project, verbose: bool, board: str | None, workspace: str | None = None
) -> list:
    """Diagnostics worth printing: info hidden unless `verbose`, and, when
    `board` and/or `workspace` is given, narrowed to that scope's own items --
    a report filter only. A diagnostic with no `item_id`, or whose item isn't
    found (nothing here resolves that far), is project-level rather than
    scope-specific and is never hidden by either flag: an unattributable
    problem could affect every board or workspace, and hiding it would defeat
    the point of a review.
    """
    out = []
    for d in project.diagnostics:
        if d.level == "info" and not verbose:
            continue
        if d.item_id is not None:
            item = project.items.get(d.item_id)
            if item is not None:
                if board is not None and item.board != board:
                    continue
                if workspace is not None and item.workspace != workspace:
                    continue
        out.append(d)
    return out


def _report(
    project: Project,
    verbose: bool = False,
    board: str | None = None,
    workspace: str | None = None,
) -> int:
    visible = _visible(project, verbose, board, workspace)
    for d in visible:
        stream = sys.stderr if d.level == "error" else sys.stdout
        print(str(d), file=stream)

    errors = sum(1 for d in visible if d.level == "error")
    warnings = sum(1 for d in visible if d.level == "warning")
    if board is None and workspace is None:
        item_count = len(project.items)
    else:
        item_count = sum(
            1
            for i in project.items.values()
            if (board is None or i.board == board)
            and (workspace is None or i.workspace == workspace)
        )
    summary = f"{item_count} items, {errors} errors, {warnings} warnings"
    if verbose:
        summary += f", {sum(1 for d in visible if d.level == 'info')} info"
    print(summary)
    return 1 if errors else 0


def cmd_check(args) -> int:
    project = _load(args)
    if args.board and args.board not in project.boards:
        import difflib

        close = difflib.get_close_matches(args.board, list(project.boards), n=1, cutoff=0.5)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        project.error(
            f"--board {args.board!r} is not a board declared in refdes.yaml's "
            f"boards: registry.{hint}"
        )
    if args.workspace and args.workspace not in project.workspaces:
        import difflib

        close = difflib.get_close_matches(
            args.workspace, list(project.workspaces), n=1, cutoff=0.5
        )
        hint = f" Did you mean {close[0]!r}?" if close else ""
        project.error(
            f"--workspace {args.workspace!r} is not a workspace declared in "
            f"refdes.yaml's workspaces: registry.{hint}"
        )
    # `check` never writes: it verifies existing seals without creating new ones.
    # The whole project still parses and resolves links regardless of --board/
    # --workspace -- only what gets reported below is narrowed.
    build_mod.build(project, seal_write=False, reseal=False)
    drift = citations_mod.refresh(project) if args.refresh else []
    status = _report(project, verbose=args.verbose, board=args.board, workspace=args.workspace)
    if drift:
        print(f"\n{len(drift)} citation(s) drifted from their pinned hash:")
        for d in drift:
            print(f"  {d.url}")
            print(f"    pinned    {d.pinned_sha256}")
            print(f"    upstream  {d.upstream_sha256}")
            print(f"    cited by  {', '.join(d.citers)}")
        status = 1
    return status


def cmd_build(args) -> int:
    project = _load(args)
    if args.out:
        project.out_dir = args.out
    if args.reseal and args.reseal != seal_mod.RESEAL_ALL and args.reseal not in project.boards:
        import difflib

        close = difflib.get_close_matches(args.reseal, list(project.boards), n=1, cutoff=0.5)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        project.error(
            f"--reseal {args.reseal!r} is not a board declared in refdes.yaml's "
            f"boards: registry.{hint}"
        )
    build_mod.build(
        project,
        seal_write=True,
        reseal=args.reseal,
        accept_board_move=args.accept_board_move,
        require_citations=args.require_citations,
    )
    out_dir = render_mod.render_site(project)
    status = _report(project, verbose=args.verbose)
    print(f"site written to {out_dir}")
    if status and not args.keep_going:
        print("build completed with errors (use --keep-going to exit 0)", file=sys.stderr)
        return status
    return 0


def _print_gate_table(results: list) -> None:
    for r in results:
        line = f"  {r.status:<8} {r.name}"
        if r.offenders:
            shown = ", ".join(r.offenders[:6])
            if len(r.offenders) > 6:
                shown += f", ... ({len(r.offenders)} total)"
            line += f"  {shown}"
        print(line, file=sys.stderr if r.status == "FAIL" else sys.stdout)


def _run_stamp(args, kind: str) -> int:
    """Shared body of `refdes revision <name>` / `refdes release <name>`.

    No flags on either command -- running one when the project isn't ready
    *is* the check (docs/design/lifecycle.md). Both call build() in the same
    read-only mode `check` uses; neither ever writes a seal, board, or
    citation manifest -- only the baseline file itself, and only once the
    unconditional error floor and (for anything the gate enables for this
    kind) the readiness gate both pass.
    """
    lifecycle_mod.validate_name(args.name)  # SchemaError -> exit 2, via main()

    project = _load(args)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    if project.errors:
        return _report(project)

    outcome = lifecycle_mod.stamp(project, kind=kind, name=args.name)
    # Diagnostics (including a stamped_by git_identity fallback warning, which
    # resolve_stamped_by() only adds on the path that actually stamps) print
    # through the same _report() every other command uses, before the
    # stamp-specific result below.
    _report(project)

    if outcome.status == "gate_failed":
        print(f"\n{kind} {args.name!r} blocked -- not stamped:", file=sys.stderr)
        _print_gate_table(outcome.gate_results)
        return 1

    if outcome.status == "conflict":
        print(f"\nerror: {outcome.conflict_detail}", file=sys.stderr)
        return 1

    if outcome.status == "unchanged":
        print(
            f"\n{kind} {args.name!r} unchanged since {outcome.stamped_at} -- "
            "nothing to stamp."
        )
        return 0

    # stamped
    rel_path = os.path.relpath(outcome.path, project.root).replace("\\", "/")
    tail = ", all gates passed." if kind == "release" else "."
    print(f"\n{kind} {args.name!r} stamped: {outcome.item_count} items{tail}")
    print(f"  {rel_path}")
    if kind == "release":
        print("\nConsider recording this in the design log, e.g.:")
        print("  - id: LOG-...")
        print(f"    date: {outcome.stamped_at[:10]}")
        print(f"    summary: Released {args.name} — sent to fab.")
        print("    records: [DEC-...]")
    return 0


def cmd_revision(args) -> int:
    return _run_stamp(args, kind="revision")


def cmd_release(args) -> int:
    return _run_stamp(args, kind="release")


def cmd_index(args) -> int:
    """Emit items.json to stdout without rendering the site.

    Editor tooling needs the index on every save; rendering hundreds of HTML files
    each time would make that unusable. This does everything `check` does and
    prints the export instead of a report.
    """
    project = _load(args, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    json.dump(
        render_mod.items_json(project),
        sys.stdout,
        indent=None if args.compact else 2,
        ensure_ascii=False,
        default=str,
    )
    sys.stdout.write("\n")
    return 0


def cmd_id(args) -> int:
    project = _load(args, require_ids=False)
    if not project.pending:
        print("no items are missing an id")
        return 0

    assignments = ids_mod.allocate(project, dry_run=args.dry_run)
    verb = "would allocate" if args.dry_run else "allocated"
    for item, new_id in assignments:
        print(f"{verb} {new_id}  ({item.source_file}:{item.source_line}) {item.title}")
    print(f"{verb} {len(assignments)} id(s)")
    return 0


def cmd_fetch(args) -> int:
    """The only command that touches the network. Pins and optionally vendors."""
    project = _load(args, require_ids=False)
    try:
        results = citations_mod.fetch_all(
            project, item_id=args.item, url=args.url, update=args.update
        )
    except citations_mod.CitationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    failed = 0
    for r in results:
        if r.error:
            failed += 1
            print(f"FAILED  {r.url}  {r.error}", file=sys.stderr)
            continue
        verb = "skipped" if r.skipped else "fetched"
        vendored = "vendored" if r.vendored else "hash-only"
        print(f"{verb:8} {r.url}  sha256={r.sha256[:12]}...  {vendored}")
    print(f"{len(results)} citation(s) processed, {failed} failed")
    return 1 if failed else 0


def _print_baseline_diff(diff) -> None:
    changed = ", ".join(diff.changed)
    print(f"  changed   {len(diff.changed)}" + (f"   {changed}" if changed else ""))
    added = ", ".join(diff.added)
    print(f"  added     {len(diff.added)}" + (f"   {added}" if added else ""))
    print(f"  removed   {len(diff.removed)}")
    for item_id, item_type, title in diff.removed:
        print(f"    {item_id} ({item_type}) {title!r} — no longer in the project")
    print(f"  ({diff.unchanged_count} unchanged)")


def cmd_audit(args) -> int:
    """Suppression is allowed; invisible suppression is not."""
    project = _load(args, require_ids=False)
    build_mod.build(project)

    print("Schema fields not tracked as 'invalidate':")
    any_schema = False
    for tname, spec in sorted(project.types.items()):
        muted = [f for f in spec.fields.values() if f.on_change != INVALIDATE]
        if not muted:
            continue
        any_schema = True
        print(f"  {tname}")
        for f in sorted(muted, key=lambda f: f.name):
            print(f"    {f.name:<16} {f.on_change}")
    if not any_schema:
        print("  (none)")

    print("\nItem-level overrides:")
    any_item = False
    for item in sorted(project.items.values(), key=lambda i: i.id):
        if not item.history:
            continue
        any_item = True
        reason = item.history.get("reason", "NO REASON GIVEN")
        if item.history.get("mode"):
            print(f"  {item.id:<14} whole item -> {item.history['mode']}  — {reason}")
        for fname, mode in (item.history.get("fields") or {}).items():
            print(f"  {item.id:<14} {fname} -> {mode}  — {reason}")
    if not any_item:
        print("  (none)")

    print("\nAppend-only entries edited after sealing:")
    resealed = seal_mod.resealed_ids(project)
    if resealed:
        for entry_id in resealed:
            print(f"  {entry_id}")
    else:
        print("  (none)")

    # "draft" is the state a project is in when nothing below has been
    # stamped -- not a command, nothing to run, so this is where that state
    # actually becomes visible (docs/design/lifecycle.md). `check`/`build`
    # stay exactly as permissive as they always were.
    baselines = lifecycle_mod.list_baselines(project)
    latest_any = lifecycle_mod.latest(baselines)
    latest_release = lifecycle_mod.latest(baselines, kind="release")
    print("\nBaselines:")
    if not baselines:
        print("  (none stamped yet -- project is in draft)")
    else:
        print(f"  most recent stamp:   {latest_any.name} ({latest_any.kind}, {latest_any.stamped_at})")
        if latest_release:
            print(f"  most recent release: {latest_release.name} ({latest_release.stamped_at})")
        else:
            print("  most recent release: (none stamped yet)")

    if latest_any:
        print(f"\nSince last revision ({latest_any.name}, {latest_any.stamped_at}):")
        _print_baseline_diff(lifecycle_mod.diff_against(project, latest_any))
    else:
        print("\nSince last revision: (no revision stamped yet)")

    if latest_release:
        print(f"\nSince last release ({latest_release.name}, {latest_release.stamped_at}):")
        _print_baseline_diff(lifecycle_mod.diff_against(project, latest_release))
    else:
        print("\nSince last release: (no release stamped yet)")

    if project.boards:
        print("\nBoard moves since the manifest was last written:")
        if project.board_moves:
            for item_id, old, new in project.board_moves:
                print(f"  {item_id:<14} {old} -> {new or '(none)'}")
        else:
            print("  (none)")

    if project.workspaces:
        print("\nWorkspace moves since the manifest was last written:")
        if project.workspace_moves:
            for item_id, old, new in project.workspace_moves:
                print(f"  {item_id:<14} {old} -> {new or '(none)'}")
        else:
            print("  (none)")

    print("\nBlocked chains:")
    if project.blocked_chains:
        for chain in sorted(project.blocked_chains, key=lambda c: c.path):
            path_str = " <- ".join(chain.path)
            root_status = f" ({chain.root_status}, root)" if chain.root_status else " (root)"
            line = f"  {path_str}{root_status}"
            if chain.stale:
                line += "  -- stale: edge still declared, blocker settled"
            print(line)
    else:
        print("  (none)")

    if project.imports:
        print("\nImported projects (read-only):")
        for spec in project.imports:
            count = sum(1 for i in project.items.values() if i.origin == spec.name)
            pin = f" pinned to {spec.version}" if spec.version else " unpinned"
            print(f"  {spec.name:<14} {count} items{pin}  <- {spec.items_path}")

    grouped = citations_mod.by_url(project)
    if grouped:
        print("\nCitations:")
        for url, statuses in grouped.items():
            state = statuses[0].state
            vendored = "vendored" if any(s.vendored for s in statuses) else "hash-only"
            citers = ", ".join(sorted({s.item_id for s in statuses}))
            print(f"  {url}")
            print(f"    {state:<14} {vendored:<10} cited by {citers}")

    grouped_parts = citations_mod.by_part_number(project)
    if grouped_parts:
        print("\nParts:")
        for part_number, usage in grouped_parts.items():
            used_by = []
            if usage.components:
                ids = ", ".join(sorted({c.id for c in usage.components}))
                label = "component" if len(usage.components) == 1 else "components"
                used_by.append(f"{ids} ({label})")
            if usage.citers:
                ids = ", ".join(sorted({c.id for c, _status in usage.citers}))
                label = "citation" if len(usage.citers) == 1 else "citations"
                used_by.append(f"{ids} ({label})")
            print(f"  {part_number:<14} used by {', '.join(used_by)}")
            if usage.boards:
                label = "board" if len(usage.boards) == 1 else "boards"
                print(f"  {'':<14} — {label}: {', '.join(usage.boards)}")

    print(f"\n{len(project.items)} items audited "
          f"({len(project.local_items)} local)")
    return 0


def main(argv: list[str] | None = None) -> int:
    _fix_console()

    parser = argparse.ArgumentParser(
        prog="refdes",
        description="Reference documentation for hardware design decisions.",
    )
    parser.add_argument("-c", "--config", help="path to refdes.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="render the HTML site and items.json")
    p_build.add_argument("-o", "--out", help="output directory (overrides site.out)")
    p_build.add_argument(
        "--keep-going", action="store_true", help="exit 0 even when there are errors"
    )
    p_build.add_argument(
        "--reseal",
        nargs="?",
        const=seal_mod.RESEAL_ALL,
        default=None,
        metavar="BOARD",
        help="accept edits to sealed append-only entries (recorded in `audit`); "
        "bare, this accepts every board's edits, or name one board to scope it, "
        "e.g. --reseal power",
    )
    p_build.add_argument(
        "--accept-board-move",
        action="store_true",
        help="accept a recorded board or workspace change for an item "
        "(recorded in `audit`)",
    )
    p_build.add_argument(
        "--require-citations",
        action="store_true",
        help="promote the unpinned-citation (info) and missing-cache-blob "
        "(warning) diagnostics to errors (CI)",
    )
    p_build.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="also show info-level diagnostics (routine states hidden by default)",
    )
    p_build.set_defaults(func=cmd_build)

    p_check = sub.add_parser(
        "check",
        help="validate without rendering",
        description="Validate the project without rendering a site: parse every "
        "item, resolve links, run calcs and checks, and verify (but never create "
        "or update) append-only seals and board-drift records. Exits non-zero on "
        "any error. Nothing is written to disk -- use 'build' for that.",
    )
    p_check.add_argument(
        "--refresh",
        action="store_true",
        help="also re-fetch every pinned citation and report drift (network; "
        "writes nothing)",
    )
    p_check.add_argument(
        "--board",
        metavar="NAME",
        help="only report diagnostics for one board's own items -- the whole "
        "project still parses and resolves links, so a cross-board reference "
        "is still checked, just not necessarily shown",
    )
    p_check.add_argument(
        "--workspace",
        metavar="NAME",
        help="only report diagnostics for one workspace's own items -- same "
        "report-filter posture as --board, and combinable with it",
    )
    p_check.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="also show info-level diagnostics (routine states hidden by default)",
    )
    p_check.set_defaults(func=cmd_check)

    p_revision = sub.add_parser(
        "revision",
        help="stamp an internal checkpoint baseline",
        description="Cut an internal checkpoint: stamps "
        ".refdes/baselines/<name>.yaml unconditionally, modulo the "
        "unconditional error floor (the same one 'check' already has). No "
        "readiness gate. Takes exactly one argument and no flags -- there is "
        "nothing to configure per run.",
    )
    p_revision.add_argument("name", help="baseline name, e.g. rev-b")
    p_revision.set_defaults(func=cmd_revision)

    p_release = sub.add_parser(
        "release",
        help="run the readiness gate and stamp a baseline if it passes",
        description="Run the full readiness gate (release_gate: in "
        "refdes-project.yaml) and stamp .refdes/baselines/<name>.yaml only "
        "if every enabled rule passes. On failure, nothing is written and "
        "the blocking rules are printed. Running this when the project "
        "isn't ready *is* the check -- there is no --dry-run. Takes exactly "
        "one argument and no flags.",
    )
    p_release.add_argument("name", help="baseline name, e.g. rev-b")
    p_release.set_defaults(func=cmd_release)

    p_index = sub.add_parser(
        "index", help="print items.json to stdout without rendering the site"
    )
    p_index.add_argument(
        "--compact", action="store_true", help="minified output, for tooling"
    )
    p_index.set_defaults(func=cmd_index)

    p_id = sub.add_parser("id", help="allocate IDs for items that have none")
    p_id.add_argument("--dry-run", action="store_true", help="show without writing")
    p_id.set_defaults(func=cmd_id)

    p_fetch = sub.add_parser(
        "fetch",
        help="fetch and pin (optionally vendor) datasheet citations",
        description="The only command that touches the network. Fetches every "
        "url a `citations:` field declares, records its sha256 and fetch time in "
        "the `.refdes/citations.yaml` lockfile, and vendors the bytes into "
        "`.refdes/vendor/` for any citation that declares `vendor: true`. "
        "Already-pinned urls are skipped unless --update is given.",
    )
    p_fetch.add_argument("--item", help="fetch only this item's citations")
    p_fetch.add_argument("--url", help="fetch only this url")
    p_fetch.add_argument(
        "--update", action="store_true", help="re-fetch even if already pinned"
    )
    p_fetch.set_defaults(func=cmd_fetch)

    p_audit = sub.add_parser(
        "audit",
        help="list suppressed fields, resealed entries, board/workspace moves, "
        "baseline diffs, and imports",
        description="List everything the build tracks but does not fail on: schema "
        "fields excluded from invalidation, item-level history overrides, "
        "append-only log entries edited after sealing (--reseal), accepted and "
        "outstanding board and workspace moves (--accept-board-move), what's "
        "changed since the last revision and the last release (see 'refdes "
        "revision'/'refdes release'), and imported projects. Suppression is "
        "allowed; invisible suppression is not.",
    )
    p_audit.set_defaults(func=cmd_audit)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SchemaError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
