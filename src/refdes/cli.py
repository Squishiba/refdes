"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import build as build_mod
from . import citations as citations_mod
from . import former_ids as former_ids_mod
from . import ids as ids_mod
from . import lifecycle as lifecycle_mod
from . import parse as parse_mod
from . import render as render_mod
from . import revise as revise_mod
from . import scaffold as scaffold_mod
from . import schema_json as schema_json_mod
from . import seal as seal_mod
from . import standards
from . import stub_tests as stub_tests_mod
from .model import INVALIDATE, Project
from .schema import SchemaError, load_project


def _fix_console() -> None:
    """Windows consoles default to cp1252, which cannot print Ω, µ, or ±."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _load(args, require_ids: bool = True) -> tuple[Project, bool]:
    """Returns (project, schema_was_stale) -- the second only ever True when
    a `.refdes/schema.json` from a previous run predates the current
    `refdes.yaml`, which every caller except `cmd_check` ignores; `check`
    surfaces it as the one narrow trip-wire for the gap this command's own
    aggressive regeneration doesn't otherwise close."""
    project = load_project(config_path=args.config)
    # A cheap side effect of loading, not a job of its own -- every command
    # that reaches this point has already resolved the full merged schema,
    # so writing .refdes/schema.json here is the same housekeeping posture
    # `build` already applies to .refdes/boards.yaml and the ID ledger
    # (docs/design/standard-library.md §12).
    schema_was_stale = schema_json_mod.write_schema(project)
    parse_mod.load_items(project, require_ids=require_ids)
    return project, schema_was_stale


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
    project, schema_was_stale = _load(args)
    if schema_was_stale:
        project.warn(
            ".refdes/schema.json was older than refdes.yaml -- refreshed. If your "
            "editor's completion looked stale, it should catch up now."
        )
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
    project, _stale = _load(args)
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
        seal_write=not args.dry_run,
        reseal=args.reseal,
        accept_board_move=args.accept_board_move,
        require_citations=args.require_citations,
    )
    out_dir = render_mod.render_site(project, draft=args.dry_run)
    status = _report(project, verbose=args.verbose)
    print(f"site written to {out_dir}" + (" (dry run, not sealed)" if args.dry_run else ""))
    if status and not args.keep_going:
        print("build completed with errors (use --keep-going to exit 0)", file=sys.stderr)
        return status
    return 0


def _print_gate_table(results: list, stream) -> None:
    """The whole table on one stream, chosen by the caller.

    Row-by-row stream selection (FAIL to stderr, everything else to stdout)
    scrambled the table under any redirection -- which is to say in CI, the
    one place it most needs to be readable: the passes arrived in one file
    and the failures, the rows that matter, in another, with no way left to
    tell what order they were printed in. A gate table is one block of
    output, so it goes to one place; the block as a whole lands on stderr
    exactly when it is a failure report.
    """
    for r in results:
        line = f"  {r.status:<8} {r.name}"
        if r.offenders:
            shown = ", ".join(r.offenders[:6])
            if len(r.offenders) > 6:
                shown += f", ... ({len(r.offenders)} total)"
            line += f"  {shown}"
        print(line, file=stream)


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

    project, _stale = _load(args)
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
        sys.stdout.flush()  # keep the report below the diagnostics it follows
        print(f"\n{kind} {args.name!r} blocked -- not stamped:", file=sys.stderr)
        _print_gate_table(outcome.gate_results, sys.stderr)
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
    project, _stale = _load(args, require_ids=False)
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


def _item_tags(item) -> list[str]:
    tags = item.fields.get("tags")
    if not tags:
        return []
    return [str(t) for t in tags] if isinstance(tags, list) else [str(tags)]


def cmd_ls(args) -> int:
    """A filterable, human-readable listing of existing items (finding 9).

    `index --compact` is the same data, but a whole-project JSON blob built
    for editor tooling -- unreadable without piping it through something
    else, and with no way to ask a narrow question. This is the CLI-native
    answer to "what already exists here", for everyone not using the VS
    Code extension: a quick check over SSH, a scripted query, or reviewing
    a PR diff and deciding what to reference.

    Free-text matches title *and* `tags:` -- tags: is `on_change: ignore`
    (freely re-tagged without invalidating anything downstream), which is
    what makes it the right place to invest in findability in the first
    place; the search has to actually reach it for that to matter.
    """
    project, _stale = _load(args, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)

    query = " ".join(args.query).strip().lower()
    file_filter = args.file.replace("\\", "/") if args.file else None

    rows = []
    for item in sorted(project.local_items, key=lambda i: i.id):
        if args.type and item.type != args.type:
            continue
        if args.board and item.board != args.board:
            continue
        if file_filter and item.source_file != file_filter:
            continue
        tags = _item_tags(item)
        if args.tag and not any(args.tag.lower() in t.lower() for t in tags):
            continue
        if query:
            haystack = " ".join([item.title, *tags]).lower()
            if query not in haystack:
                continue
        rows.append(item)

    if not rows:
        print("no items match")
        return 0

    id_w = max(len(i.id) for i in rows)
    type_w = max(len(i.type) for i in rows)
    board_w = max((len(i.board) for i in rows), default=0)
    for item in rows:
        board_col = f"{item.board:<{board_w}}  " if board_w else ""
        print(f"{item.id:<{id_w}}  {item.type:<{type_w}}  {board_col}{item.title}")
    return 0


def cmd_id(args) -> int:
    project, _stale = _load(args, require_ids=False)
    if not project.pending:
        print("no items are missing an id")
        return 0

    assignments = ids_mod.allocate(project, dry_run=args.dry_run)
    verb = "would allocate" if args.dry_run else "allocated"
    for item, new_id in assignments:
        print(f"{verb} {new_id}  ({item.source_file}:{item.source_line}) {item.title}")
    print(f"{verb} {len(assignments)} id(s)")
    # A numeric-hint collision (finding 8 Part 1) or a write-back refusal is
    # reported via project.error() inside allocate() itself, not raised --
    # surface it here rather than let a partial "allocated 0 id(s)" pass
    # for success with no explanation.
    for d in project.errors:
        print(str(d), file=sys.stderr)
    return 1 if project.errors else 0


def cmd_fetch(args) -> int:
    """The only command that touches the network. Pins and optionally vendors."""
    project, _stale = _load(args, require_ids=False)
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
    project, _stale = _load(args, require_ids=False)
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
            # A flat-layout project (no workspaces: registry) never
            # populates item.workspace at all, so usage.workspaces is
            # always empty there -- this line simply never appears rather
            # than growing an always-empty row.
            if usage.workspaces:
                label = "workspace" if len(usage.workspaces) == 1 else "workspaces"
                print(f"  {'':<14} — {label}: {', '.join(usage.workspaces)}")

    if project.former_ids:
        print("\nFormer IDs:")
        for old_id, new_id in sorted(project.former_ids.items()):
            print(f"  {old_id:<14} -> {new_id}")

    print(f"\n{len(project.items)} items audited "
          f"({len(project.local_items)} local)")
    return 0


def cmd_init(args) -> int:
    standard = None if args.standard == "none" else args.standard
    presets = list(args.preset or [])
    path = scaffold_mod.init(os.getcwd(), standard=standard, presets=presets)
    rel = os.path.relpath(path, os.getcwd()).replace("\\", "/")
    print(f"wrote {rel}")
    if standard is not None:
        version = standards.latest_version(standard)
        preset_note = f", presets: {presets}" if presets else ""
        print(f"standard: {standard}@{version}{preset_note}")
    else:
        print("standard: none -- types:/link_types: are yours to declare")
    return 0


def cmd_new(args) -> int:
    project = load_project(config_path=args.config)
    spec = project.types.get(args.type)
    if spec is None:
        import difflib

        close = difflib.get_close_matches(args.type, list(project.types), n=1, cutoff=0.5)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        print(f"unknown type {args.type!r}.{hint}", file=sys.stderr)
        return 1
    sys.stdout.write(scaffold_mod.new_item_text(args.type, spec))
    return 0


def cmd_schema(args) -> int:
    project = load_project(config_path=args.config)
    if args.graph:
        sys.stdout.write(schema_json_mod.build_graph(project))
    else:
        json.dump(schema_json_mod.build_schema(project), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def _standard_project_root(args) -> str:
    from .schema import find_config

    config_path = args.config or find_config()
    return os.path.dirname(os.path.abspath(config_path))


def cmd_standard_add_preset(args) -> int:
    scaffold_mod.add_preset(_standard_project_root(args), args.name)
    print(f"added preset {args.name!r} to standard.presets:")
    return 0


def cmd_standard_remove_preset(args) -> int:
    diagnostics = scaffold_mod.remove_preset(_standard_project_root(args), args.name)
    for d in diagnostics:
        stream = sys.stderr if d.level == "error" else sys.stdout
        print(str(d), file=stream)
    error_count = sum(1 for d in diagnostics if d.level == "error")
    print(f"removed preset {args.name!r} from standard.presets:")
    if error_count:
        print(
            f"{error_count} error(s) above -- fix these, or add the preset back "
            "with 'refdes standard add-preset'",
            file=sys.stderr,
        )
        return 1
    return 0


def _print_revision_result(result, dry_run: bool) -> int:
    if not result.ok:
        print("refused:" if not dry_run else "would refuse:", file=sys.stderr)
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    verb = "would change" if dry_run else "changed"
    if not result.changed_files and not result.id_changes:
        if result.config_updated:
            # A version step whose delta renames nothing still did the work
            # that matters: it moved the pin and re-validated the whole
            # project against the new version. Saying "nothing to do" here
            # would describe a real, and possibly refusable, step as a no-op.
            print("no item file needed rewriting -- standard.version: bumped "
                  "and the project re-validated against it")
        else:
            print("nothing to do -- mapping doesn't apply to this project")
        return 0

    print(f"{verb} {len(result.changed_files)} file(s):")
    for rel in result.changed_files:
        print(f"  {rel}")
    if result.id_changes:
        print("id changes:")
        for old_id, new_id in sorted(result.id_changes.items()):
            print(f"  {old_id} -> {new_id}")
    if dry_run:
        return 0
    if result.baselines_updated:
        print(f"baselines carried forward: {', '.join(result.baselines_updated)}")
    if result.baselines_skipped_no_standard:
        print(
            "baselines skipped (no recorded standard to migrate from): "
            + ", ".join(result.baselines_skipped_no_standard)
        )
    if result.seals_updated:
        print(f"seals carried forward: {', '.join(result.seals_updated)}")
    if result.stale_references:
        # Not a failure -- prose is deliberately never rewritten -- but never
        # silent either: these lines used to resolve and no longer do. On
        # stdout with the rest of the success report, not stderr, so it can't
        # interleave above the step header it belongs to.
        print(
            f"\n{len(result.stale_references)} prose mention(s) of a renamed id "
            "left behind -- these no longer resolve, and were not rewritten "
            "(a rename never edits prose):"
        )
        for ref in result.stale_references:
            print(f"  {ref}")
    return 0


def cmd_revise(args) -> int:
    project_root = _standard_project_root(args)
    try:
        mapping = revise_mod.load_mapping(args.mapping)
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = revise_mod.apply(project_root, mapping, dry_run=args.dry_run)
    return _print_revision_result(result, dry_run=args.dry_run)


def cmd_standard_upgrade(args) -> int:
    project_root = _standard_project_root(args)
    steps = revise_mod.apply_standard_upgrade(project_root, args.to)
    ok = True
    for step in steps:
        print(f"v{step.from_version} -> v{step.to_version}:")
        # A refused step reports on stderr; without this the two streams
        # interleave and the refusal lands above the header naming the step
        # it belongs to.
        sys.stdout.flush()
        status = _print_revision_result(step.result, dry_run=False)
        if status != 0:
            ok = False
            break
    if ok:
        print(f"\nupgraded to v{args.to}.")
    return 0 if ok else 1


def cmd_stub_tests(args) -> int:
    project, _stale = _load(args, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    if project.errors:
        return _report(project)
    written = stub_tests_mod.generate(project, verifier_type=args.type, dry_run=args.dry_run)
    if not written:
        print("no coverable item is missing a verifying test")
        return 0
    verb = "would write" if args.dry_run else "wrote"
    total = 0
    for path, ids in written:
        total += len(ids)
        print(f"{verb} {len(ids)} stub(s) to {path}: {', '.join(ids)}")
    print(f"{verb} {total} stub test(s) across {len(written)} file(s)")
    if not args.dry_run:
        print("Run 'refdes id' to allocate ids for the new items.")
    return 0


def cmd_former_ids_propose(args) -> int:
    """Show inferred old-to-new id mappings; write none unless --confirm names them.

    Never a build error on its own -- comparing a baseline that predates
    unrelated errors elsewhere in the project is still useful, so this only
    needs the project to parse, not to pass validate_items()/resolve_links().
    """
    project, _stale = _load(args, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    try:
        candidates = former_ids_mod.propose(project, baseline_name=args.baseline)
    except former_ids_mod.ProposeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not candidates:
        print("no candidate former-id mappings found")
        return 0

    print(f"{len(candidates)} candidate former-id mapping(s):")
    for c in candidates:
        print(
            f"  {c.old_id} ({c.old_type} {c.old_title!r}) -> {c.new_id} "
            f"({c.new_title!r})  confidence {c.confidence:.0%}"
        )

    if not args.confirm:
        print(
            "\nNothing written. Re-run with --confirm OLD_ID[,OLD_ID...] to "
            "record the ones you accept as former_ids:."
        )
        return 0

    requested = [x.strip() for x in args.confirm.split(",") if x.strip()]
    try:
        confirmed = former_ids_mod.confirm(project, candidates, requested)
    except former_ids_mod.ProposeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print()
    for c in confirmed:
        item = project.items[c.new_id]
        print(f"wrote former_ids: [{c.old_id}] to {c.new_id} ({item.source_file})")
    return 1 if project.errors else 0


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
        "--dry-run",
        action="store_true",
        help="render the site without sealing (unlike id/revise/stub-tests, "
        "this still writes real, browsable HTML -- only the seal-recording "
        "side effect on not-yet-sealed log entries is skipped; the output "
        "is watermarked as a draft)",
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
        "any error. Nothing of the project's own is written -- no site, no seal, "
        "no board or citation manifest, no baseline. The one exception is "
        "'.refdes/schema.json', the gitignored editor-completion schema every "
        "project-loading command refreshes.",
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

    p_ls = sub.add_parser(
        "ls", help="list existing items: id, type, board, title -- filterable"
    )
    p_ls.add_argument(
        "query", nargs="*",
        help="free text, matched against title and tags: (case-insensitive)",
    )
    p_ls.add_argument("--type", help="only items of this type")
    p_ls.add_argument("--board", help="only items on this board")
    p_ls.add_argument("--file", help="only items declared in this source file")
    p_ls.add_argument("--tag", help="only items with a tag containing this text")
    p_ls.set_defaults(func=cmd_ls)

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

    p_init = sub.add_parser(
        "init",
        help="write a minimal refdes.yaml that points at the standard",
        description="Write a minimal refdes.yaml in the current directory -- "
        "site:/standard:/id: only, no types:/link_types:/field_sets: -- plus "
        ".vscode/settings.json wiring up schema completion for items/**/*.yaml. "
        "standard: points at the standard library rather than copying it; "
        "<latest> is resolved to a concrete pinned integer, never written as "
        "the literal word 'latest'.",
    )
    p_init.add_argument(
        "--standard",
        default="hardware",
        metavar="NAME",
        help="base standard to pin (default: hardware), or 'none' for the "
        "fully self-declared escape hatch (today's pre-standard behavior)",
    )
    p_init.add_argument(
        "--preset",
        action="append",
        metavar="NAME",
        help="layer a preset on top of the base (repeatable). Requires a base "
        "standard -- combining with --standard none is a load-time error, "
        "since every preset's types target base types.",
    )
    p_init.set_defaults(func=cmd_init)

    p_new = sub.add_parser(
        "new",
        help="print a starter item for one type to stdout",
        description="Scaffold a starter item's front matter for TYPE, generated "
        "from the identical resolved schema 'refdes schema --json' emits -- not "
        "a second, hand-maintained template that could drift from it. Prints to "
        "stdout; redirect it where you want the item to live, e.g. "
        "'refdes new decision > items/power/dec-005.md'.",
    )
    p_new.add_argument("type", help="an item type in the merged schema, standard or project-defined")
    p_new.set_defaults(func=cmd_new)

    p_schema = sub.add_parser(
        "schema",
        help="print the project's merged JSON Schema, or type/link graph, to stdout",
        description="Emit the project's actual merged schema -- base at its "
        "pinned version, plus selected presets, plus the project overlay -- "
        "as JSON Schema (--json, the default; the same schema is written to "
        ".refdes/schema.json by every command that loads the project, this is "
        "the explicit standalone form) or as Mermaid flowchart source "
        "describing the type/link graph (--graph): generated from the "
        "resolved schema so it can't go stale the way a hand-drawn diagram "
        "would the moment a preset or overlay changes a verb.",
    )
    p_schema.add_argument(
        "--json", action="store_true", help="JSON Schema output (the default)"
    )
    p_schema.add_argument(
        "--graph",
        action="store_true",
        help="Mermaid flowchart source describing the actual type/link graph, to stdout",
    )
    p_schema.set_defaults(func=cmd_schema)

    p_standard = sub.add_parser(
        "standard",
        help="add or remove a preset from standard.presets:",
        description="Change standard.presets: with validation and reporting. "
        "Hand-editing standard.presets: directly and re-running 'refdes build' "
        "does exactly the same thing -- these commands exist for the "
        "validation and reporting step, not because the underlying operation "
        "needs a command.",
    )
    standard_sub = p_standard.add_subparsers(dest="standard_command", required=True)

    p_add_preset = standard_sub.add_parser(
        "add-preset", help="validate a preset name and add it to standard.presets:"
    )
    p_add_preset.add_argument("name")
    p_add_preset.set_defaults(func=cmd_standard_add_preset)

    p_remove_preset = standard_sub.add_parser(
        "remove-preset",
        help="remove a preset from standard.presets:, reporting what breaks first",
    )
    p_remove_preset.add_argument("name")
    p_remove_preset.set_defaults(func=cmd_standard_remove_preset)

    p_standard_upgrade = standard_sub.add_parser(
        "upgrade",
        help="move a pinned standard forward, rewriting item files and "
        "standard.version: to match",
        description="Chain the bundled standard's own migration.yaml files, "
        "one version at a time, from the project's currently pinned "
        "standard.version: up to --to N -- each step rewrites item files "
        "for that version's own rename, bumps standard.version: to match, "
        "and carries content hashes forward in every stamped baseline and "
        "seal so the rename doesn't look like a content change. Never "
        "merges steps: a multi-version jump is always applied as its full "
        "chain of individual deltas, in order. Refuses (rolling back "
        "cleanly) rather than guessing at an ambiguous or ill-formed step.",
    )
    p_standard_upgrade.add_argument(
        "--to", type=int, required=True, metavar="N",
        help="target standard.version: to upgrade to",
    )
    p_standard_upgrade.set_defaults(func=cmd_standard_upgrade)

    p_revise = sub.add_parser(
        "revise",
        help="rewrite project-local vocabulary (types/fields/links/prefixes) "
        "from a hand-written mapping file",
        description="Apply an explicit old->new vocabulary mapping (type "
        "names, field names scoped per type, link verb names, id prefixes) "
        "to every item file in one operation, carrying each affected item's "
        "content hash forward in stamped baselines and seals so the rename "
        "doesn't look like a content change. For a bundled standard's own "
        "version upgrade, use 'refdes standard upgrade --to N' instead, "
        "which needs no hand-written mapping. Refuses (rolling back "
        "cleanly) rather than guessing at an ambiguous mapping, an "
        "already-used target name, or a rename the current schema doesn't "
        "yet support.",
    )
    p_revise.add_argument(
        "mapping",
        help="path to a YAML file with types:/fields:/links:/prefixes: renames",
    )
    p_revise.add_argument(
        "--dry-run", action="store_true", help="show what would change without writing"
    )
    p_revise.set_defaults(func=cmd_revise)

    p_stub_tests = sub.add_parser(
        "stub-tests",
        help="generate starter test items for coverable items with no verifying test",
        description="Write one multi-item markdown file per board/workspace, "
        "one starter item per still-uncovered coverable item in that scope -- "
        "verifies: already pointing at it, status: planned, and an empty "
        "method: to fill in. Deduplicates by declared links, not text: an "
        "item that already has a verifying test (allocated or still pending "
        "an id) is skipped, so re-running never doubles up, and deleting a "
        "stub makes its target eligible again. A starting point only -- "
        "refdes does not own test items afterward.",
    )
    p_stub_tests.add_argument(
        "--type",
        metavar="NAME",
        help="which type to generate (only needed if more than one type "
        "declares a 'verifies' link)",
    )
    p_stub_tests.add_argument(
        "--dry-run", action="store_true", help="show what would be written without writing"
    )
    p_stub_tests.set_defaults(func=cmd_stub_tests)

    p_former_ids = sub.add_parser(
        "former-ids",
        help="infer and record former_ids: mappings after a renumbering",
    )
    former_ids_sub = p_former_ids.add_subparsers(dest="former_ids_command", required=True)

    p_former_ids_propose = former_ids_sub.add_parser(
        "propose",
        help="show inferred old-to-new id candidates; write none unless --confirm",
        description="Compare the most recent baseline snapshot to the live "
        "project: an id present at baseline time but gone now, matched by "
        "title similarity against a same-type id that's new since, is a "
        "candidate former_ids: mapping, shown with its confidence. Never "
        "written automatically -- a wrong link in a traceability tool is "
        "worse than a missing one. Pass --confirm to write former_ids: for "
        "the candidates you accept, named by their old id.",
    )
    p_former_ids_propose.add_argument(
        "--baseline",
        metavar="NAME",
        help="compare against this baseline instead of the most recently stamped one",
    )
    p_former_ids_propose.add_argument(
        "--confirm",
        metavar="OLD_ID[,OLD_ID...]",
        help="write former_ids: for these candidates (by old id), and only these",
    )
    p_former_ids_propose.set_defaults(func=cmd_former_ids_propose)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SchemaError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
