"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys

from . import build as build_mod
from . import citations as citations_mod
from . import ids as ids_mod
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


def _report(project: Project, verbose: bool = False) -> int:
    for d in project.diagnostics:
        if d.level == "info" and not verbose:
            continue
        stream = sys.stderr if d.level == "error" else sys.stdout
        print(str(d), file=stream)

    errors, warnings = len(project.errors), len(project.warnings)
    summary = f"{len(project.items)} items, {errors} errors, {warnings} warnings"
    if verbose:
        summary += f", {len(project.infos)} info"
    print(summary)
    return 1 if errors else 0


def cmd_check(args) -> int:
    project = _load(args)
    # `check` never writes: it verifies existing seals without creating new ones.
    build_mod.build(project, seal_write=False, reseal=False)
    drift = citations_mod.refresh(project) if args.refresh else []
    status = _report(project, verbose=args.verbose)
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

    if project.boards:
        print("\nBoard moves since the manifest was last written:")
        if project.board_moves:
            for item_id, old, new in project.board_moves:
                print(f"  {item_id:<14} {old} -> {new or '(none)'}")
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
        action="store_true",
        help="accept edits to sealed append-only entries (recorded in `audit`)",
    )
    p_build.add_argument(
        "--accept-board-move",
        action="store_true",
        help="accept a recorded board change for an item (recorded in `audit`)",
    )
    p_build.add_argument(
        "--require-citations",
        action="store_true",
        help="promote unpinned/missing-cache citation warnings to errors (CI)",
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
        "-v", "--verbose",
        action="store_true",
        help="also show info-level diagnostics (routine states hidden by default)",
    )
    p_check.set_defaults(func=cmd_check)

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
        help="list suppressed fields, resealed entries, board moves, and imports",
        description="List everything the build tracks but does not fail on: schema "
        "fields excluded from invalidation, item-level history overrides, "
        "append-only log entries edited after sealing (--reseal), accepted and "
        "outstanding board moves (--accept-board-move), and imported projects. "
        "Suppression is allowed; invisible suppression is not.",
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
