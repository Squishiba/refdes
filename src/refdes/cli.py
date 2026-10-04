"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from importlib.metadata import PackageNotFoundError

from . import adopt as adopt_mod
from . import build as build_mod
from . import calc_rewrite as calc_rewrite_mod
from . import citations as citations_mod
from . import diagram as diagram_mod
from . import docs_url as docs_url_mod
from . import former_ids as former_ids_mod
from . import get_version, model, standards, textio
from . import history as history_mod
from . import ids as ids_mod
from . import key_restore as key_restore_mod
from . import keys as keys_mod
from . import lifecycle as lifecycle_mod
from . import loader as loader_mod
from . import render as render_mod
from . import revise as revise_mod
from . import scaffold as scaffold_mod
from . import schema_json as schema_json_mod
from . import seal as seal_mod
from . import stub_tests as stub_tests_mod
from .model import INVALIDATE, Item, Project
from .schema import SCHEMA_NAME, SchemaError, load_project
from .write_lock import LockUnavailable, project_write_lock

# Where the docs actually are for someone who installed refdes from a wheel.
# Re-exported from docs_url, which carries the comment that has to travel with
# it -- build/keys/links/configcheck print diagnostics that point at a page and
# cannot import this module back (it imports all of them). Every other
# user-facing pointer to a page goes through docs_url too, so the mapping from
# page to URL lives in one file.
DOCS_URL = docs_url_mod.DOCS_URL


def _fix_console() -> None:
    """Windows consoles default to cp1252, which cannot print Ω, µ, or ±."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _load(args, require_ids: bool = True) -> tuple[Project, bool]:
    """Returns (project, schema_was_stale) -- the second only ever True when
    a `.refdes/schema.json` from a previous run predates the newer of the two
    config files (`refdes-project.yaml`/`refdes-schema.yaml`), which every
    caller except `cmd_check` ignores; `check` surfaces it as the one narrow
    trip-wire for the gap this command's own aggressive regeneration doesn't
    otherwise close.

    The pipeline itself lives in `loader.load_tree`, shared with the browser
    editor's read-only path. `write=False` is `--no-write` -- and `--dry-run`
    too, which is the same promise made by a different name: a command that
    has already been told to report rather than write must not have the *load*
    on the way in write anyway. Loading mints every missing surrogate key and
    expands bare link references into `ID@key` composites (docs/design/keys.md
    §2), so `refdes id --dry-run` used to answer "would allocate 1 id(s)" over
    an item file it had already edited to add a `key:` line to. `--no-write`
    already forced `args.dry_run` in the two commands that have a `--dry-run`
    and load this way (`cmd_id`, `cmd_stub_tests`), so this is exactly the code
    path `--no-write` was already tested through -- there is no third
    behaviour here to get right.
    """
    return loader_mod.load_tree(
        args.config,
        require_ids=require_ids,
        write=not (args.no_write or getattr(args, "dry_run", False)),
    )


def _refuse_no_write(command: str, what: str) -> int:
    """Explicit write commands have no read-only story to tell under
    `--no-write` (unlike the ones with a --dry-run, which get forced onto
    it): running them means writing, so refuse loudly rather than write
    silently (docs/design/keys.md §2)."""
    print(
        f"--no-write: {command} writes {what}; refusing to run it under "
        "--no-write. Drop --no-write to run it for real.",
        file=sys.stderr,
    )
    return 2


def _load_write_notice(project: Project) -> str | None:
    """One terse line naming what this run's own load wrote into the source
    tree (docs/design/keys.md §2), or None when it wrote nothing. The count
    keeps `(s)` rather than hand-pluralising, the way `id`'s own
    "allocated N id(s)" line already does."""
    writes = project.load_writes
    if not writes:
        return None
    parts = []
    if writes.minted_keys:
        parts.append(f"minted {writes.minted_keys} key(s)")
    if writes.rewritten_targets:
        parts.append(f"rewrote {writes.rewritten_targets} reference(s)")
    if writes.rewritten_images:
        parts.append(f"froze {writes.rewritten_images} image(s)")
    return f"({' and '.join(parts)} while loading)"


#: How many refused files one notice names before switching to a count.
_BLOCKED_NAMED = 4


def _load_blocked_notice(project: Project, since: int = 0) -> str | None:
    """The other half of the same honesty: files this load tried to write and
    the filesystem refused (docs/design/keys.md §2). None when nothing was
    refused, so a writable run -- and every `--no-write` run -- prints nothing
    here either.

    Only for commands that print no diagnostics of their own. Where a command
    does report (`check`, `build`, `revision`/`release`, `index`), the warning
    naming each refused file already reaches the user through `project.warn`,
    and saying it twice in one run is noise that teaches people to skim past
    the line that matters.

    `since` names how much of the list was already announced, for the command
    that announces up front and can hit a further refusal later in its own
    body (`audit` reformatting a baseline's stored-hash format partway through
    its report, long after the notice went out).

    The sentence is `model.read_only_refusal()` with the file list as its
    consequence, so the summary carries `model.READ_ONLY_REFUSAL` byte for
    byte. It used to spell its own near-copy of that sentence, and a CI log
    filter written against the per-file warning missed every command that has
    no per-file warning to print (user-sim run 3, finding N2). Two spellings
    of one condition is exactly what the single constant exists to prevent.
    """
    blocked = project.load_writes.blocked[since:]
    if not blocked:
        return None
    if len(blocked) <= _BLOCKED_NAMED:
        what = ", ".join(blocked)
    else:
        what = (
            ", ".join(blocked[:_BLOCKED_NAMED])
            + f" (+{len(blocked) - _BLOCKED_NAMED} more)"
        )
    return f"(load {model.read_only_refusal(what)})"


def _announce_load_writes(
    project: Project, *, stream=None, name_blocked: bool = True
) -> None:
    """Say what this run's load did to the source tree, before the command's
    own output (docs/design/keys.md §2). Every command that loads through
    `_load()` writable owes this: the load mints keys and rewrites references
    on disk whatever the command was asked to do, and a command that reports
    as though nothing changed while its own load edited the tree is the defect
    this reports.

    `stream` is for the commands whose stdout is machine output -- `index`
    prints JSON, and a parenthetical line in front of it breaks every consumer
    -- which send it to stderr instead. `name_blocked=False` is for the
    commands that already print project diagnostics, where the per-file
    warning carries the refusal; see `_load_blocked_notice()`.
    """
    out = sys.stdout if stream is None else stream
    notice = _load_write_notice(project)
    if notice:
        print(notice, file=out)
    if name_blocked:
        refusal = _load_blocked_notice(project)
        if refusal:
            print(refusal, file=out)


def _sealing_optin_note(project: Project) -> str | None:
    """Run-5 F3: the opt-back-in overlay has to say that it took effect.

    `types: {log: {sealing: build}}` in `refdes-schema.yaml` puts the
    build-time hash lock back on a type the bundled standard had moved to
    `sealing: history` -- a different project, with different rules for the
    same files. Until now the only way to confirm those three lines did
    anything was to edit an entry and see whether the build failed, which
    leaves the author who added them unable to see that they worked and the
    author who meant to add them and forgot unable to see that they did not.
    So the note names the type and the file that declared it.

    A `note:` on stderr, not a diagnostic: F3 is graded friction (low) and the
    overlay is a *deliberate* decision, so it owes the reader no severity, no
    place in the `N errors, M warnings` count (run-5 B4 is the complaint about
    counting one condition twice), and no change to any exit code. Not a
    `project.info()` diagnostic either, for the reason the note exists at all:
    `_visible()` hides info unless `--verbose`, which would leave the author
    still hunting for the confirmation.
    """
    names = project.sealing_optins
    if not names:
        return None
    if len(names) == 1:
        moved = f"the {names[0]!r} type"
    else:
        moved = f"{len(names)} types ({', '.join(names)})"
    return (
        f"note: {SCHEMA_NAME} opts {moved} back into build sealing -- an edit "
        "to a sealed entry is a build error again, not the history-backed "
        "'edited after captured' warning"
    )


def _announce_sealing_optin(project: Project) -> None:
    """`check` and `build` only -- the two commands run-5 F3 names, and the two
    an author reaches for to ask whether their config took effect. Nothing to
    print for a project with no overlay, which is most projects and every one
    that has never thought about sealing at all."""
    note = _sealing_optin_note(project)
    if note:
        print(note, file=sys.stderr)


def _print_late_refusals(project: Project, announced: int) -> None:
    """Name writes refused *after* the command already printed its load notice.

    For the two commands that print a bespoke report rather than project
    diagnostics (`audit`, `former-ids propose`), a refusal that happens in the
    middle of that report has no diagnostic channel to travel down, and the
    notice printed at load time cannot know about it yet. Nothing to print on
    a writable run, which is every run that does not need this.
    """
    late = _load_blocked_notice(project, since=announced)
    if late:
        print(late)


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
            item = project.item_by_id(d.item_id)
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
    # `check` writes nothing of the project's own -- but its load does, and
    # said-so or not that is the tree the user is being asked about. The
    # per-file warnings reach this command through `_report` below, so the
    # notice names only what landed.
    _announce_load_writes(project, name_blocked=False)
    _announce_sealing_optin(project)
    if schema_was_stale:
        # Name the file that actually triggered it: the mtime check is a max
        # across both config files, and a warning pointing at the wrong one
        # would send the user looking for an edit in a file they never touched.
        newest = schema_json_mod.newest_config_file(project)
        if args.no_write:
            project.warn(
                f".refdes/schema.json was older than {newest} -- not refreshed "
                "(--no-write). Run without --no-write to refresh it."
            )
        elif schema_json_mod.SCHEMA_REL_DISPLAY in project.load_writes.blocked:
            # The refresh was attempted and the filesystem refused it. Saying
            # "refreshed" here would send the user back to their editor to
            # re-check a completion list that is exactly as stale as it was;
            # `write_schema` already warned about the refused write, so this
            # only corrects the trip-wire's own verdict.
            project.warn(
                f".refdes/schema.json was older than {newest} -- not refreshed "
                "(the write was refused). Make the tree writable, or run with "
                "--no-write to skip the refresh."
            )
        else:
            project.warn(
                f".refdes/schema.json was older than {newest} -- refreshed. If your "
                "editor's completion looked stale, it should catch up now."
            )
    if args.board and args.board not in project.boards:
        import difflib

        close = difflib.get_close_matches(args.board, list(project.boards), n=1, cutoff=0.5)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        project.error(
            f"--board {args.board!r} is not a board declared in refdes-project.yaml's "
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
            f"refdes-project.yaml's workspaces: registry.{hint}"
        )
    # `check` never writes: it verifies existing seals without creating new ones.
    # The whole project still parses and resolves links regardless of --board/
    # --workspace -- only what gets reported below is narrowed.
    build_mod.build(project, seal_write=False, reseal=False)
    if args.allow_unreachable and not args.refresh:
        print(
            f"note: {citations_mod.ALLOW_UNREACHABLE_FLAG} without --refresh has "
            "nothing to allow -- no pinned citation is re-fetched, so none of them "
            "can be unreachable.",
            file=sys.stderr,
        )
    drift = (
        citations_mod.refresh(project, allow_unreachable=args.allow_unreachable)
        if args.refresh
        else []
    )
    status = _report(project, verbose=args.verbose, board=args.board, workspace=args.workspace)
    if drift:
        print(f"\n{len(drift)} citation(s) drifted from their pinned hash:")
        for d in drift:
            print(f"  {d.path}")
            print(f"    pinned    {d.pinned_sha256}")
            print(f"    upstream  {d.upstream_sha256}")
            print(f"    cited by  {', '.join(d.citers)}")
        status = 1
    return status


def cmd_build(args) -> int:
    project, _stale = _load(args)
    _announce_load_writes(project, name_blocked=False)
    _announce_sealing_optin(project)
    if args.out:
        project.out_dir = args.out
    if args.reseal and args.reseal != seal_mod.RESEAL_ALL and args.reseal not in project.boards:
        import difflib

        close = difflib.get_close_matches(args.reseal, list(project.boards), n=1, cutoff=0.5)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        project.error(
            f"--reseal {args.reseal!r} is not a board declared in refdes-project.yaml's "
            f"boards: registry.{hint}"
        )
    if args.no_write and (args.reseal or args.accept_board_move):
        print(
            "note: --no-write -- --reseal/--accept-board-move record nothing; "
            "the edits they would accept stay outstanding.",
            file=sys.stderr,
        )
    build_mod.build(
        project,
        # --no-write gates the seal files and the membership manifest --
        # both live under .refdes/ and neither is the site, which is the
        # only thing build's own output is (docs/design/keys.md §2).
        seal_write=not (args.dry_run or args.no_write),
        reseal=args.reseal,
        accept_board_move=args.accept_board_move,
        require_citations=args.require_citations,
    )
    try:
        out_dir = render_mod.render_site(project, draft=args.dry_run)
    except OSError as exc:
        # The site is build's own output -- the one thing this command is for
        # -- so a destination that will not take it is a refusal rather than
        # something to degrade past: there is no partial "site written to ..."
        # worth printing and no summary that would not read as a build that
        # happened. Same exit code as the `--no-write` refusal (2), for the
        # same reason: nothing is wrong with the project. The diagnostics
        # gathered before the render are still printed, because a seal or
        # manifest write refused a moment ago is exactly what the user needs
        # alongside this.
        _report(project, verbose=args.verbose)
        target = os.path.join(project.root, project.out_dir)
        print(
            f"error: cannot write the site to {target} ({exc.strerror or exc}) -- "
            "nothing was rendered. Point -o/--out at a writable directory, or "
            "make this one writable.",
            file=sys.stderr,
        )
        return 2
    status = _report(project, verbose=args.verbose)
    print(f"site written to {out_dir}" + (" (dry run, not sealed)" if args.dry_run else ""))
    if status and not args.keep_going:
        print("build completed with errors (use --keep-going to exit 0)", file=sys.stderr)
        return status
    return 0


def _serve_port_arg(text: str) -> int:
    """argparse type for `serve --port`: a port number, or a usage error.

    Checked here rather than at bind() because Python raises `OverflowError`, not
    `OSError`, for a port outside 0-65535 -- an out-of-range value would otherwise
    reach the user as a traceback instead of one line on stderr."""
    try:
        port = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port number") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"{port} is not a port number between 1 and 65535")
    return port


def cmd_serve(args) -> int:
    """`refdes serve`: the loopback-only browser editor and rendered preview
    (docs/design/browser-editor.md). One project, one process."""
    from .serve.server import EditorApp, ServeStartupError, sigterm_stops_cleanly

    try:
        app = EditorApp(
            args.config,
            read_only=args.no_write,
            port=args.port or 0,
            token_file=args.token_file,
        )
    except ServeStartupError as exc:
        # A startup refusal -- busy port, unwritable --token-file -- is a usage
        # problem, so it gets the house `error:` line and exit 2 (as every other
        # refusal in this file does), never a traceback out of socket.bind().
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"refdes serve: {app.launch_url}", flush=True)
    if app.token_file:
        print(
            f"Launch URL written to {app.token_file} (owner-only, removed when this "
            "stops cleanly -- Ctrl+C or SIGTERM); it is a credential.",
            flush=True,
        )
    print("Listening on 127.0.0.1 only. The token in that URL is this launch's key;")
    print(
        "keep it out of screenshots and shared terminals. Ctrl+C to stop; a SIGTERM "
        "(`kill $pid`) stops it just as cleanly.",
        flush=True,
    )
    if not args.no_open:
        import webbrowser

        webbrowser.open(app.launch_url)
    # The SIGTERM handler is installed for this launch only, and only where
    # SIGTERM is deliverable at all (see `sigterm_stops_cleanly`): a scripted
    # `kill $pid` takes the very path a Ctrl+C takes, so the launch credential
    # goes with it. `stop()` is inside the `with` on purpose -- a signal that
    # lands during teardown is still caught.
    with sigterm_stops_cleanly():
        try:
            app.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            app.stop()
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
    _announce_load_writes(project, name_blocked=False)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    if project.errors:
        return _report(project)

    outcome = lifecycle_mod.stamp(project, kind=kind, name=args.name, write=not args.no_write)
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
        if outcome.uncomparable:
            # Part of why the stored content can't match may be entries whose
            # hash simply can't be checked any more, not a content move --
            # say so instead of letting "different content" overclaim.
            print(
                f"\nuncomparable {len(outcome.uncomparable)}"
                f"   {', '.join(outcome.uncomparable)}",
                file=sys.stderr,
            )
            print(
                "  older-format baseline entries whose stored hash can't be checked against the\n"
                "  current definition -- not proof of changed content; review them, then stamp a\n"
                "  new baseline once the content has been reviewed.",
                file=sys.stderr,
            )
        print(f"\nerror: {outcome.conflict_detail}", file=sys.stderr)
        return 1

    if outcome.status == "unchanged":
        print(
            f"\n{kind} {args.name!r} unchanged since {outcome.stamped_at} -- "
            "nothing to stamp."
        )
        return 0

    if outcome.status == "unwritable":
        # Exit 2, the refusal code, not 1: nothing is wrong with the project
        # -- every gate passed -- so this is a usage refusal of the same kind
        # as the `--no-write` one (`_refuse_no_write`), not the "errors found"
        # code. Naming the file is the whole point: the user asked for a stamp
        # and has to be told which path would have held it.
        print(
            f"\nerror: cannot write {outcome.refusal} (read-only tree?) -- "
            f"{kind} {args.name!r} was not stamped. Make the tree writable and "
            "run it again, or run it with --no-write to see what it would stamp.",
            file=sys.stderr,
        )
        return 2

    if outcome.status == "would_stamp":
        # --no-write: every check passed, nothing was written.
        rel_path = os.path.relpath(outcome.path, project.root).replace("\\", "/")
        print(
            f"\n{kind} {args.name!r} not stamped (--no-write): would stamp "
            f"{outcome.item_count} items to {rel_path}."
        )
        return 0

    # stamped
    rel_path = os.path.relpath(outcome.path, project.root).replace("\\", "/")
    tail = ", all gates passed." if kind == "release" else "."
    print(f"\n{kind} {args.name!r} stamped: {outcome.item_count} items{tail}")
    print(f"  {rel_path}")
    if kind == "release":
        # The ids here are placeholders, and have to look like it. `LOG-...`
        # pastes as a truncated-but-plausible id and then fails the PREFIX-NNN
        # shape check with a message about an id the author never meant to
        # write (user-sim run 2, "Lower severity" list); `LOG-A-0NN` is the
        # spelling docs/design-log.md and docs/design/lifecycle.md already
        # show for this same nudge, and the trailing comment says what to
        # substitute -- the same `refdes new` posture of marking a blank
        # rather than filling it with something that looks finished.
        print("\nConsider recording this in the design log, e.g.:")
        print("  - id: LOG-A-0NN  # placeholder: your log prefix, next free number")
        print(f"    date: {outcome.stamped_at[:10]}")
        print(f"    summary: Released {args.name} — sent to fab.")
        print("    records: [DEC-A-0NN]  # the decision(s) this release turned on")
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
    # stdout here is JSON for the VS Code extension, so the load's own writes
    # are said on stderr -- and `index`'s JSON carries the per-file warnings in
    # its `diagnostics` array, so the refused files need no second telling.
    _announce_load_writes(project, stream=sys.stderr, name_blocked=False)
    # A file that fails to parse is reported like everywhere else, but `index`
    # is the one command whose exit code is deliberately left alone: the VS
    # Code extension (editors/vscode/extension.js, refreshIndex) throws away
    # the whole index whenever this command exits non-zero, so a half-typed
    # YAML file mid-edit would blank the editor on every keystroke. Report on
    # stderr, keep the JSON on stdout, keep exiting 0.
    load_errors = project.errors
    for d in load_errors:
        print(str(d), file=sys.stderr)
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

    Free-text matches id, title, `tags:` *and* `former_ids:` -- tags: is
    `on_change: ignore` (freely re-tagged without invalidating anything
    downstream), which is what makes it the right place to invest in
    findability in the first place; the search has to actually reach it for
    that to matter. The id is in the haystack too, because the natural query
    right after `refdes id` prints one is the id itself.

    `former_ids:` earns its place in the haystack for the same reason: the
    premise of a recorded former id is that the retired one keeps turning up in
    external citations (schematics, review notes, commit messages), and "where
    did REQ-PWR-001 go?" has to be answerable by the command a person reaches
    for. Without this, the only answer was to read the whole `refdes audit`
    output (finding F3.2, in-prog-logs/keys-identity-recovery.txt).

    The listing carries a workspace column -- but only on a project that
    declares `workspaces:`, so a project without one sees the same bytes it
    saw before this column existed. Without it the `--workspace` filter below
    was the only way to find out that an item belonged to a workspace at all,
    which made the flag undiscoverable from the listing it filters.
    """
    project, _stale = _load(args, require_ids=False)
    _announce_load_writes(project)
    # Items in a file that failed to parse are not in the listing and never
    # can be -- say so, and don't let the listing pass for a complete answer.
    load_errors = project.errors
    for d in load_errors:
        print(str(d), file=sys.stderr)
    build_mod.build(project, seal_write=False, reseal=False)

    query = " ".join(args.query).strip().lower()
    file_filter = args.file.replace("\\", "/") if args.file else None

    rows: list[tuple[Item, list[str]]] = []
    # A retired id that some item still records as live: {retired id: holders}.
    # Kept aside rather than shown as a hit, because a live item wins the id
    # outright -- see the note printed under the table.
    reused: dict[str, list[str]] = {}
    for item in sorted(project.local_items, key=lambda i: i.id):
        if args.type and item.type != args.type:
            continue
        if args.board and item.board != args.board:
            continue
        if args.workspace and item.workspace != args.workspace:
            continue
        if file_filter and item.source_file != file_filter:
            continue
        tags = _item_tags(item)
        if args.tag and not any(args.tag.lower() in t.lower() for t in tags):
            continue
        # Matched former ids, under exactly the substring/case rule the rest of
        # the query uses. Read off the item rather than `project.former_ids`,
        # which by design omits any entry that collides with a live id
        # (ids.collect_former_ids) -- and this row has to still *see* that
        # entry in order to report the reuse below.
        named = [old for old in item.former_ids if query and query in old.lower()]
        retired = [old for old in named if project.item_by_id(old) is None]
        for old in named:
            if old not in retired:
                reused.setdefault(old, []).append(item.id)
        if query:
            haystack = " ".join([item.id, item.title, *tags]).lower()
            if query not in haystack and not retired:
                continue
        rows.append((item, retired))

    if not rows:
        print("no items match")
        for old_id, holders in sorted(reused.items()):
            _print_reuse_note(old_id, holders)
        return 1 if load_errors else 0

    id_w = max(len(i.id) for i, _ in rows)
    type_w = max(len(i.type) for i, _ in rows)
    board_w = max((len(i.board) for i, _ in rows), default=0)
    # Workspaces get a column under the same condition boards do, for the same
    # reason: `workspaces.resolve` is a no-op without a `workspaces:` registry,
    # so a project that declares none has nothing to put in the column and
    # keeps byte-identical output (workspaces.py's module docstring promises
    # exactly that, and the board column above is the precedent).
    # `item.workspace` is the resolved value -- the same one `--workspace`
    # filters on -- and an item in no workspace has it "", printed as blank
    # padding rather than a placeholder, since "" is not a name `--workspace`
    # will ever match.
    ws_w = max((len(i.workspace) for i, _ in rows), default=0) if project.workspaces else 0
    for item, retired in rows:
        board_col = f"{item.board:<{board_w}}  " if board_w else ""
        ws_col = f"{item.workspace:<{ws_w}}  " if ws_w else ""
        mark = f" (formerly {', '.join(retired)})" if retired else ""
        print(f"{item.id:<{id_w}}  {item.type:<{type_w}}  {ws_col}{board_col}{item.title}{mark}")
    for old_id, holders in sorted(reused.items()):
        _print_reuse_note(old_id, holders)
    return 1 if load_errors else 0


def _print_reuse_note(retired_id: str, holders: list[str]) -> None:
    """Say who still records a live id as a former one, and what to do.

    A former id that has been reused is a build error (`former_ids:` may only
    name retired ids, ids.collect_former_ids), so the live item is what the
    listing answers with and the former holder is named here instead of being
    listed as though the query had found it. Without this the listing would
    silently read as though the retired id had simply never existed.
    """
    print(
        f"\nnote: {retired_id} is a live item's id again, so that item is "
        f"listed above; {', '.join(sorted(holders))} still records it as a "
        "former id, which 'refdes check' reports as an error -- former_ids: "
        "may only name retired ids."
    )


def cmd_id(args) -> int:
    if args.no_write:
        args.dry_run = True  # --no-write: report the allocation, write nothing
    project, _stale = _load(args, require_ids=False)
    # Loading mints every missing key and expands bare link targets on disk
    # (docs/design/keys.md §2), so on a project whose keys don't exist yet
    # this command rewrites item files while reporting that nothing is
    # missing. Name what it wrote, ahead of the verdict that made the silence
    # surprising. `load_writes` stays empty under --no-write/--dry-run and in
    # the steady state, so both keep printing exactly what they printed before.
    _announce_load_writes(project)
    # Nothing pending is only the honest answer when every file loaded: an
    # item in a file that failed to parse is not in project.pending either,
    # so "no items are missing an id" would be a claim about files this run
    # never saw. Report the load errors and fail instead of reassuring.
    load_errors = project.errors
    for d in load_errors:
        print(str(d), file=sys.stderr)
    if not project.pending:
        if load_errors:
            print(
                f"ids could not be checked in {len(load_errors)} file(s) that "
                "failed to load"
            )
            return 1
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
    """The only command that touches the network. Pins and optionally keeps local copies."""
    if args.no_write:
        return _refuse_no_write(
            "fetch", "the .refdes/citations.yaml lockfile and .refdes/copies/"
        )
    project, _stale = _load(args, require_ids=False)
    _announce_load_writes(project)
    # Read the lockfile before anything else, and refuse on one that cannot be
    # read. `fetch` is a writer of this file: it rewrites the whole lockfile
    # from the records it fetched, so going ahead on a lockfile it could not
    # parse would replace every pin it could not read with a fresh one --
    # turning a merge nobody has finished resolving into a merge nobody has, with
    # the losing side's provenance gone and nothing in the tree to say so. The
    # file is left byte-identical, which is the point: a lockfile a person has
    # to fix by hand must survive every attempt to run the tool that would help.
    # Exit 1, the code this command's other three refusals use: this is the
    # project's state being unusable, not a configuration error of the kind the
    # exit-2 rows name.
    try:
        records = citations_mod.load_lockfile(project)
    except citations_mod.LockfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    # Pre-rename `vendor:`-era artifacts are not read by anything any more --
    # say so here too, not just at build/check time, so `refdes fetch` cannot
    # look clean while the project's old copies and lockfile keys sit stranded.
    for _severity, message in citations_mod.legacy_notices(project, records):
        print(f"warning: {message}", file=sys.stderr)
    # A file that fails to parse is a load error, not a fetch failure -- but
    # it is still a failure: every citation in that file was never loaded,
    # so fetching cannot have processed it. Report the load errors (the same
    # `ERROR  file:line` form check/_report use) and still pin what did load,
    # then exit 1 for the run as a whole.
    load_errors = project.errors
    for d in load_errors:
        print(str(d), file=sys.stderr)
    try:
        results = citations_mod.fetch_all(
            project, item_id=args.item, path=args.path, update=args.update
        )
    except citations_mod.CitationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    failed = 0
    for r in results:
        if r.error:
            failed += 1
            print(f"FAILED  {r.path}  {r.error}", file=sys.stderr)
            continue
        if r.source_errors and not r.sha256:
            # The pin was NOT written: a source() key could not be extracted,
            # so the path's previous record (if any) is exactly as it was.
            for source_error in r.source_errors:
                failed += 1
                print(f"FAILED  {source_error}", file=sys.stderr)
            continue
        verb = "skipped" if r.skipped else "fetched"
        kept = "kept" if r.kept_copy else "hash-only"
        print(f"{verb:8} {r.path}  sha256={r.sha256[:12]}...  {kept}")
        for key, value in sorted(r.source_values.items()):
            if not any(c.startswith(f"{r.path}: {key}: ") for c in r.source_changes):
                print(f"         extracted {r.path} {key} = {value}")
        for change in r.source_changes:
            print(f"         source value changed  {change}")
        for note in r.source_notes:
            print(f"         source: {note}")
        for warning in r.source_warnings:
            print(f"WARNING  {warning}", file=sys.stderr)
        for warning in r.page_warnings:
            print(f"WARNING  {warning}", file=sys.stderr)
        for warning in r.size_warnings:
            # A big download is not a failed one: the pin landed, and this line
            # is the whole of the consequence, so it must not reach `failed`.
            print(f"WARNING  {warning}", file=sys.stderr)
        for source_error in r.source_errors:
            failed += 1
            print(f"FAILED  {source_error}", file=sys.stderr)
        for section, page in sorted(r.sections.items()):
            print(f"         section {section!r} -> page {page}")
        # The pin succeeded but the outline lookup did not: report it as its own
        # failure, so a citation whose `section:` silently went unresolved can
        # never look like a clean fetch.
        for section_error in r.section_errors:
            failed += 1
            print(f"FAILED  {section_error}", file=sys.stderr)
    summary = f"{len(results)} citation(s) processed, {failed} failed"
    if load_errors:
        summary += (
            f"; {len(load_errors)} load error(s) -- citations in files "
            "that failed to load were not processed"
        )
    print(summary)
    return 1 if (failed or load_errors) else 0


def _print_baseline_diff(diff) -> None:
    changed = ", ".join(diff.changed)
    print(f"  changed   {len(diff.changed)}" + (f"   {changed}" if changed else ""))
    for item_id, lines in diff.moved_refs.items():
        for line in lines:
            print(f"    {item_id} -- {line}")
    for item_id in diff.stale_arithmetic:
        print(f"    {item_id} -- stale arithmetic: status changed, calc block did not")
    if diff.uncomparable:
        uncomparable = ", ".join(diff.uncomparable)
        print(f"  uncomparable {len(diff.uncomparable)}   {uncomparable}")
        print(
            "    older-format entries whose stored hash can't be checked against the current"
            " definition --\n    not counted as changed; review the content, then stamp a new baseline"
        )
    added = ", ".join(diff.added)
    print(f"  added     {len(diff.added)}" + (f"   {added}" if added else ""))
    print(f"  removed   {len(diff.removed)}")
    for item_id, item_type, title in diff.removed:
        print(f"    {item_id} ({item_type}) {title!r} — no longer in the project")
    print(f"  relabelled {len(diff.relabelled)}")
    for old_id, new_id, key in diff.relabelled:
        print(f"    {old_id} -> {new_id}   ({key})")
    print(f"  ({diff.unchanged_count} unchanged)")


def cmd_audit(args) -> int:
    """Suppression is allowed; invisible suppression is not."""
    project, _stale = _load(args, require_ids=False)
    _announce_load_writes(project)
    # `audit` prints no project diagnostics of its own -- its whole output is
    # the report below -- so a write refused partway through that report (the
    # baseline hash-format rewrite, which only happens once a baseline is
    # older than the current hash definition) has no other way to reach the
    # user. Re-announce from here on at the end, or it would be the one
    # refusal in the tool that nobody is told about.
    announced = len(project.load_writes.blocked)
    # An audit of a project whose files didn't all load is an incomplete
    # audit, and silence about that is exactly what an audit exists to
    # prevent. The report still comes out for what did load; the run fails.
    load_errors = project.errors
    for d in load_errors:
        print(str(d), file=sys.stderr)
    build_mod.build(project)
    # The same rule as the load errors above, one step later, and over the ones
    # the build just added -- the load errors are still in `project.errors`, so
    # leaving them out of this list is what keeps them from being printed twice.
    # A diagnostic with no `item_id` is about a project-wide file rather than an
    # item, so no section of this report can speak for it -- and this report's
    # sections speak by omission: with an unreadable `.refdes/citations.yaml`,
    # `verify()` populates no `item.citations`, so the "Citations:" section below
    # would print nothing at all rather than print a pin it does not have. An
    # audit that silently drops a section it could not produce is the thing an
    # audit exists to prevent, so say so and fail, exactly as for a file that did
    # not load. Item-level errors are left alone: `refdes check` reports those,
    # and this report's own sections can partly speak for them.
    project_wide = [
        d for d in project.errors if d.item_id is None and d not in load_errors
    ]
    for d in project_wide:
        print(str(d), file=sys.stderr)
    historical_key_infos = keys_mod.audit_historical_baselines(project)

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
            # A history-backed type's seal record is a legacy-seal marker, not
            # a lock (living-notes plan §H5): still reported, and said so.
            item = project.item_by_id(entry_id)
            legacy = item is not None and seal_mod.history_backed(project, item.type)
            note = (
                "  (legacy seal: recorded hash only; original content was not captured)"
                if legacy else ""
            )
            print(f"  {entry_id}{note}")
    else:
        print("  (none)")

    # The sibling section §H5 adds: the history-backed replacement for the
    # one above. The same finding `check`/`build` warn about, read-only.
    print("\nEntries edited after captured:")
    try:
        edited = history_mod.edited_after_captured(project)
    except (history_mod.HistoryError, OSError) as exc:
        print(f"  (not checked: the history store could not be read -- {exc})")
    else:
        if edited:
            for finding in edited:
                label = finding.item.id or finding.item.key
                print(f"  {label}  ({finding.event['kind']} event {finding.event['id']})")
        else:
            print("  (none)")

    print("\nAccepted append-only reseals (durable history):")
    history = seal_mod.reseal_history(project)
    if history:
        for board, event in history:
            # An absent board is left out, the way every other section of
            # this report leaves it out ("Board moves ...", "— board: ...")
            # -- none of them name the absence. A declared board still
            # shows, in the bracketed qualifier form a diagnostic uses for a
            # scope.
            where = f" [{board}]" if board else ""
            print(f"  {event['id']}{where} {event['occurred_at']} {event['action']}")
            if event.get("key"):
                print(f"    item key {event['key']}")
            print(f"    was {event['old_hash']}, now {event['new_hash'] or '(removed)'}")
        # The key earns its line: the event's id is the label as it stood when
        # the event happened, so a rename splits one item's history across two
        # ids and the key is the only field that ties them back together. It is
        # a user-facing value elsewhere (`refdes keys restore ID@KEY`,
        # `audit`'s own relabelled lines), so it is labelled rather than dropped.
        if any(event.get("key") for _board, event in history):
            print(
                "  (the key is the item's own surrogate key: it does not change when\n"
                "   the item is renamed, where the id above is the label as it stood)"
            )
    else:
        print("  (none)")

    # Informational only -- issue #6, finding 10 part 2's narrower half. Not
    # a warning or an error anywhere else: an id going missing from the
    # ledger's perspective is the ordinary shape of deleting an item, not a
    # defect. See ids.orphaned_allocations()'s own docstring for exactly
    # what this does and does not catch -- in particular, it is NOT a fix
    # for hand-typed id reuse after deletion; it only catches the moment
    # between deletion and any later re-typing of the same id, if audit
    # happens to run during that window.
    orphaned = ids_mod.orphaned_allocations(project)
    print("\nLedger entries with no live item and no former_ids: explaining them:")
    if orphaned:
        for entry_id in orphaned:
            print(f"  {entry_id}")
        print(
            "  (deleted on purpose? nothing to do. renamed without recording\n"
            "   former_ids:? worth adding. reused by a different item typed\n"
            "   with this exact id? this list can't tell -- see finding 10\n"
            "   part 2, docs/design/keys.md.)"
        )
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
        _print_baseline_diff(lifecycle_mod.diff_against(project, latest_any, write=not args.no_write))
    else:
        print("\nSince last revision: (no revision stamped yet)")

    if latest_release:
        print(f"\nSince last release ({latest_release.name}, {latest_release.stamped_at}):")
        _print_baseline_diff(
            lifecycle_mod.diff_against(project, latest_release, write=not args.no_write)
        )
    else:
        print("\nSince last release: (no release stamped yet)")

    print("\nOlder baseline keys no current item declares:")
    if historical_key_infos:
        for diagnostic in historical_key_infos:
            print(f"  {diagnostic}")
    else:
        print("  (none)")

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

    grouped = citations_mod.by_path(project)
    if grouped:
        print("\nCitations:")
        for path, statuses in grouped.items():
            state = statuses[0].state
            # The second column describes the pin, so it has to agree with the
            # first, and every word here is about what is on disk *now*, not
            # only about what the lockfile claims. Two rows used to get that
            # wrong by reading the lockfile alone:
            #
            # `unpinned  hash-only` -- "hash-only" means
            # pinned-by-hash-without-a-kept-copy (docs/markdown.md "Pinning vs.
            # keeping a copy") and an unpinned citation has no hash at all:
            # `record is None` short-circuits before kept_copy is ever read
            # (citations.py:981-992). Opaque, and wrong (user-sim run 2,
            # "Lower severity" list).
            #
            # `cache_missing  kept` -- here the lockfile genuinely does say
            # `kept_copy: true`, but the bytes it points at are not on disk
            # (citations.py:995-1001 sets the state precisely because
            # `kept_copy_path` is not a file), so `kept` told a user the kept
            # copy was there. It is not; `no copy` says so on the same line.
            #
            # The state column is deliberately not touched: the release gate's
            # `missing_kept_copies` rule filters on
            # `state == "cache_missing"` (lifecycle.py:577-585), so rewording
            # it would change what blocks a release.
            #
            # `hash_mismatch` keeps `kept`: the blob *is* there, and that is
            # what this column says -- the state column is what says its bytes
            # are wrong. The two agree there.
            if state == "unpinned":
                pin = "no pin"
            elif state == "cache_missing":
                pin = "no copy"
            elif any(s.kept_copy for s in statuses):
                pin = "kept"
            else:
                pin = "hash-only"
            citers = ", ".join(sorted({s.item_id for s in statuses}))
            print(f"  {path}")
            print(f"    {state:<14} {pin:<10} cited by {citers}")

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

    _print_late_refusals(project, announced)

    print(f"\n{len(project.items)} items audited "
          f"({len(project.local_items)} local)")
    return 1 if (load_errors or project_wide) else 0


def cmd_init(args) -> int:
    if args.no_write:
        return _refuse_no_write(
            "init", "refdes-project.yaml and .vscode/settings.json in the "
            "current directory"
        )
    standard = None if args.standard == "none" else args.standard
    presets = list(args.preset or [])
    cwd = os.getcwd()
    # Asked before init runs: afterwards .vscode/settings.json is there either
    # way, and nothing distinguishes the file init wrote from the one it left
    # alone -- and that skip used to print nothing at all (user-sim run 2, BUG 3).
    # `scaffold.init` returns only the config path, so this pre-check is what
    # tells the two outcomes apart for the announcement below.
    vscode_settings_existed = scaffold_mod.vscode_settings_exists(cwd)
    # Read before init runs: `scaffold.init` returns only the config path, so
    # this is the only way the announcement below can say which ignore patterns
    # actually appeared -- including when the answer is none, because the
    # project's own .gitignore already covered them.
    gitignore_path = os.path.join(cwd, ".gitignore")
    gitignore_before = (
        textio.read_text(gitignore_path) if os.path.isfile(gitignore_path) else None
    )
    path = scaffold_mod.init(cwd, standard=standard, presets=presets)
    rel = os.path.relpath(path, cwd).replace("\\", "/")
    print(f"wrote {rel}")
    # init writes two files, so it names both: a second file that appears with
    # no word about it is invisible unless you list the directory (user-sim run
    # 2, "Lower severity" list). The skip case is named by the note below.
    if not vscode_settings_existed:
        print(
            "wrote .vscode/settings.json (gitignored -- the yaml.schemas path "
            "in it names one checkout)"
        )
    # ...and the `.gitignore` it wrote or appended to is a third thing that
    # appeared, so it is named too -- by what it now ignores rather than by the
    # act of writing it, which is accurate in both the wrote-a-new-file and the
    # appended-to-an-existing-one case, and empty when nothing was needed.
    added = scaffold_mod.added_gitignore_patterns(
        gitignore_before,
        textio.read_text(gitignore_path) if os.path.isfile(gitignore_path) else "",
    )
    if added:
        print(f"wrote .gitignore ({', '.join(added)} -- not yours to commit)")
    if standard is not None:
        version = standards.latest_version(standard)
        preset_note = f", presets: {presets}" if presets else ""
        print(f"standard: {standard}@{version}{preset_note}")
    else:
        print("standard: none -- types:/link_types: are yours to declare")
    if vscode_settings_existed:
        print(scaffold_mod.vscode_settings_note(cwd))
    print(
        "candidate parts live in items/<board>/candidates.yaml -- "
        f"{DOCS_URL}/parts.html#candidate-parts-the-recommended-layout"
    )
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
    if args.list:
        sys.stdout.write(scaffold_mod.new_list_text(args.type, spec))
    else:
        sys.stdout.write(scaffold_mod.new_item_text(args.type, spec))
    return 0


def cmd_schema(args) -> int:
    project = load_project(config_path=args.config)
    if args.graph:
        if args.type is not None:
            if args.type not in project.types:
                known = ", ".join(sorted(project.types))
                print(
                    f"unknown type {args.type!r}; this project's types are: {known}",
                    file=sys.stderr,
                )
                return 1
            sys.stdout.write(diagram_mod.render_term_svg(project, args.type))
        else:
            sys.stdout.write(schema_json_mod.build_graph(project))
        return 0
    json.dump(schema_json_mod.build_schema(project), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _standard_project_root(args) -> str:
    from .schema import find_config

    config_path = args.config or find_config()
    return os.path.dirname(os.path.abspath(config_path))


def cmd_standard_add_preset(args) -> int:
    if args.no_write:
        return _refuse_no_write("standard add-preset", "refdes-project.yaml")
    try:
        scaffold_mod.add_preset(_standard_project_root(args), args.name)
    except scaffold_mod.Refused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"added preset {args.name!r} to standard.presets:")
    return 0


def cmd_standard_remove_preset(args) -> int:
    if args.no_write:
        return _refuse_no_write("standard remove-preset", "refdes-project.yaml")
    try:
        diagnostics = scaffold_mod.remove_preset(_standard_project_root(args), args.name)
    except scaffold_mod.Refused as exc:
        # Refused before any of the diagnostics above would have been
        # reported -- the simulation copy never got written, so there is
        # nothing to report and the config is untouched.
        print(f"error: {exc}", file=sys.stderr)
        return 2
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
        if dry_run and result.expansions:
            print(
                "references the real run would expand first (not enough to clear the refusal):",
                file=sys.stderr,
            )
            for entry in result.expansions:
                print(f"  {entry}", file=sys.stderr)
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
    if dry_run and result.expansions:
        print(
            f"\n{len(result.expansions)} line(s) the real run would first mint/expand "
            "to composite form (keys + references), before the rename itself:"
        )
        for entry in result.expansions:
            print(f"  {entry}")
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
    if args.no_write:
        args.dry_run = True  # --no-write: report the plan, write nothing
    project_root = _standard_project_root(args)
    try:
        mapping = revise_mod.load_mapping(args.mapping)
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = revise_mod.apply(project_root, mapping, dry_run=args.dry_run)
    return _print_revision_result(result, dry_run=args.dry_run)


def cmd_calc_rewrite(args) -> int:
    if args.no_write:
        args.dry_run = True  # --no-write: report the plan, write nothing
    project_root = _standard_project_root(args)
    result = calc_rewrite_mod.apply(project_root, dry_run=args.dry_run)
    if not result.ok:
        print("would refuse:" if args.dry_run else "refused:", file=sys.stderr)
        for error in result.errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    if result.line_changes:
        verb = "would rewrite" if args.dry_run else "rewrote"
        print(
            f"{verb} {len(result.line_changes)} calc line(s) in "
            f"{len(result.changed_files)} file(s):"
        )
        for change in result.line_changes:
            print(f"  {change}")
    else:
        print("nothing to rewrite -- no old-spelling calc lines found")
    if result.sealed_entries:
        print(
            f"\n{len(result.sealed_entries)} old-spelling calc line(s) in sealed "
            "append-only entries left as written -- seals are historical records "
            "and are never rewritten; these stay on the old spelling (which still "
            "evaluates) until history-backed resealing lands or they are "
            "deliberately resealed:"
        )
        for entry in result.sealed_entries:
            print(f"  {entry}")
    if result.baselines_updated:
        print(f"baselines carried forward: {', '.join(result.baselines_updated)}")
    if result.seals_updated:
        print(f"seals carried forward: {', '.join(result.seals_updated)}")
    return 0


def cmd_standard_upgrade(args) -> int:
    if args.no_write:
        return _refuse_no_write(
            "standard upgrade", "every item file it renames plus "
            "refdes-project.yaml, and it has no dry-run"
        )
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


def cmd_keys_restore(args) -> int:
    dry_run = args.dry_run or args.no_write
    result = key_restore_mod.apply(
        _standard_project_root(args), args.targets, dry_run=dry_run, force=args.force
    )
    if not result.ok:
        print("would refuse:" if dry_run else "refused:", file=sys.stderr)
        for error in result.errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    if not result.changes:
        print("nothing to do -- original keys already declared")
        return 0
    for display, previous, original in result.changes:
        action = "would restore" if dry_run else "restored"
        print(f"{action} {display}: {previous or '(no key)'} -> {original}")
    print("files would change:" if dry_run else "changed files:")
    for path in result.changed_files:
        print(f"  {path}")
    print("Review the diff before committing.")
    return 0


def cmd_keys_adopt(args) -> int:
    if args.no_write:
        args.dry_run = True  # --no-write: show the complete plan, write nothing
    result = adopt_mod.apply(_standard_project_root(args), dry_run=args.dry_run)
    if not result.ok:
        print("would refuse:" if args.dry_run else "refused:", file=sys.stderr)
        for error in result.errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    if result.already_adopted:
        print("nothing to do -- project already adopted")
    elif args.dry_run:
        print(f"would mint {result.minted} key(s)")
        print(
            f"would expand {result.expanded} link reference(s) "
            "to composite form"
        )
        print(
            f"would expand {result.checks_expanded} check reference(s) "
            "to composite form"
        )
        print(
            f"would freeze {result.frozen_follows} follows reference(s) "
            "at their thread tips"
        )
    else:
        print(f"minted {result.minted} key(s)")
        print(
            f"expanded {result.expanded} link reference(s) "
            "to composite form"
        )
        print(
            f"expanded {result.checks_expanded} check reference(s) "
            "to composite form"
        )
        print(
            f"froze {result.frozen_follows} follows reference(s) "
            "at their thread tips"
        )

    if result.baselines and not result.already_adopted:
        heading = "baselines would be rebased:" if args.dry_run else "baselines rebased:"
        print(heading)
        for baseline in result.baselines:
            print(
                f"  {baseline.name} "
                f"({baseline.carried}/{baseline.total} entries carried)"
            )
    for baseline in result.baselines:
        for item_id in baseline.uncomparable:
            print(f"  uncomparable baseline entry {baseline.name}: {item_id}")

    if result.seals and not result.already_adopted:
        heading = "seals would be rebased:" if args.dry_run else "seals rebased:"
        print(heading)
        for seal in result.seals:
            print(f"  {seal.file} ({seal.carried}/{seal.total} entries carried)")
    for seal in result.seals:
        for item_id in seal.uncomparable:
            print(f"  uncomparable seal entry {seal.file}: {item_id}")

    if result.memberships and not result.already_adopted:
        heading = (
            "membership manifests would be rebased:"
            if args.dry_run
            else "membership manifests rebased:"
        )
        print(heading)
        for membership in result.memberships:
            print(
                f"  {membership.file} "
                f"({membership.carried}/{membership.total} entries carried)"
            )
    for membership in result.memberships:
        for identity in membership.unidentified:
            print(f"  unidentified membership entry {identity}")
        if membership.stale:
            action = "would drop" if args.dry_run else "dropped"
            count = len(membership.stale)
            noun = "entry" if count == 1 else "entries"
            print(
                f"  {action} {count} stale membership {noun}: "
                f"{', '.join(membership.stale)}"
            )

    if result.changed_files:
        heading = "files that would change:" if args.dry_run else "changed files:"
        print(heading)
        for rel in result.changed_files:
            print(f"  {rel}")
        print("Review the diff before committing.")
    return 0


def cmd_stub_tests(args) -> int:
    if args.no_write:
        args.dry_run = True  # --no-write: report the stubs, write nothing
    project, _stale = _load(args, require_ids=False)
    # Same gap `cmd_id` had (F5): this command loads the way that command
    # does, so on a project whose keys don't exist yet it rewrites item files
    # while reporting that nothing is missing a test. Name what the load wrote
    # before the verdict that made the silence surprising. `load_writes` stays
    # empty under --no-write/--dry-run and in the steady state, so both keep
    # printing exactly what they printed before.
    _announce_load_writes(project)
    build_mod.build(project, seal_write=False, reseal=False)
    if project.errors:
        return _report(project)
    try:
        written = stub_tests_mod.generate(project, verifier_type=args.type, dry_run=args.dry_run)
    except stub_tests_mod.Refused as exc:
        # Some files landed and some did not, so both halves are reported: the
        # stubs that are on disk (and the reminder that gives them ids), then
        # the refusal naming each file the filesystem would not take. Exit 1 --
        # a run that left work undone is not a clean run, and the files it did
        # write are a checklist to finish, not a result to bank.
        for path, ids in exc.written:
            print(f"wrote {len(ids)} stub(s) to {path}: {', '.join(ids)}")
        total = sum(len(ids) for _path, ids in exc.written)
        if total:
            print(f"wrote {total} stub test(s) across {len(exc.written)} file(s)")
            print("Run 'refdes id' to allocate ids for the new items.")
        print("refused:", file=sys.stderr)
        for e in exc.errors:
            print(f"  {e}", file=sys.stderr)
        return 1
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
    if args.no_write and args.confirm:
        return _refuse_no_write(
            "former-ids propose --confirm", "former_ids: into the item files"
        )
    project, _stale = _load(args, require_ids=False)
    _announce_load_writes(project)
    announced = len(project.load_writes.blocked)
    # A file that never parsed was never searched for candidates either, so
    # both of this command's quiet answers -- "no candidates" and a --confirm
    # run that finds errors -- have to say so rather than pass for clean.
    load_errors = project.errors
    for d in load_errors:
        print(str(d), file=sys.stderr)
    build_mod.build(project, seal_write=False, reseal=False)
    try:
        candidates = former_ids_mod.propose(
            project, baseline_name=args.baseline, write=not args.no_write
        )
    except former_ids_mod.ProposeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    # `propose` compares against a baseline, which is where a stored-hash
    # format rewrite can be refused. This command prints candidates and
    # nothing else -- no diagnostics channel for it to arrive through -- so
    # the refusal is announced here, from the point the notice above was
    # printed rather than from the start of the list.
    _print_late_refusals(project, announced)

    if not candidates:
        if load_errors:
            print(
                "no candidate former-id mappings found -- "
                f"{len(load_errors)} load error(s); files that failed to "
                "load were not searched"
            )
            return 1
        print("no candidate former-id mappings found")
        return 0

    print(f"{len(candidates)} candidate former-id mapping(s):")
    for c in candidates:
        print(
            f"  {c.old_id} ({c.old_type} {c.old_title!r}) -> {c.new_id} "
            f"({c.new_title!r})  "
            + ("exact match (surrogate key)" if c.exact else f"confidence {c.confidence:.0%}")
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
        item = project.item_by_id(c.new_id)
        print(f"wrote former_ids: [{c.old_id}] to {c.new_id} ({item.source_file})")
    return 1 if project.errors else 0


_REDACT_WARNING = (
    "Redaction reaches this history store only. It cannot remove data "
    "already committed to Git, present in clones, or published in built "
    "sites: rewrite Git history and republish (and revoke anything secret) "
    "the way you would for any leaked file."
)


def cmd_history_capture(args) -> int:
    """One manual `captured` event for an item a thread will never supply a
    successor for (living-notes §2 decision 3). Says "captured", never
    "final"."""
    if args.no_write:
        return _refuse_no_write("history capture", "the .refdes/history/ store")
    project, _stale = _load(args)
    _announce_load_writes(project)
    item = project.item_by_ref(args.item)
    if item is None:
        print(
            f"error: no item {args.item!r} in this project "
            "(looked up by display id, then surrogate key)",
            file=sys.stderr,
        )
        return 2
    try:
        result = history_mod.capture(str(project.root), item)
    except history_mod.HistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result.created_event:
        print(result.announcement)
    else:
        print(f"{item.id or item.key} is already captured; nothing was written")
    return 0


def cmd_history_redact(args) -> int:
    """Remove history objects/events and write an auditable redaction event
    that names what was removed without repeating its content (§3)."""
    if args.no_write:
        return _refuse_no_write("history redact", "the .refdes/history/ store")
    if not args.confirm:
        print(
            "history redact permanently removes captured snapshots and events "
            "from .refdes/history/ and cannot be undone. Re-run with --confirm "
            "to acknowledge that.",
            file=sys.stderr,
        )
        print(_REDACT_WARNING, file=sys.stderr)
        return 2
    project, _stale = _load(args)
    _announce_load_writes(project)
    target = args.target
    try:
        if re.fullmatch(r"[0-9a-f]{64}", target):
            result = history_mod.redact(str(project.root), object_digest=target)
        else:
            item = project.item_by_ref(target)
            if item is None:
                print(
                    f"error: no item or history object {target!r} in this "
                    "project (an item is addressed by display id or surrogate "
                    "key; an object by its full 64-hex digest)",
                    file=sys.stderr,
                )
                return 2
            if not item.key:
                print(
                    f"error: {item.id or target} has no surrogate key; run "
                    "`refdes id` first",
                    file=sys.stderr,
                )
                return 2
            result = history_mod.redact(str(project.root), item_key=item.key)
    except history_mod.HistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result.event_path is None:
        print(f"no history objects or events matched {target}; nothing was redacted")
        return 0
    print(
        f"redacted {len(result.removed_objects)} object(s) and "
        f"{len(result.removed_events)} event(s)"
    )
    print(
        "wrote redaction event "
        f"{os.path.basename(result.event_path)[: -len('.yaml')]} "
        "naming what was removed (by digest and event id only -- its content "
        "is not repeated anywhere in this output)"
    )
    print(_REDACT_WARNING)
    return 0


def cmd_history_migrate_seals(args) -> int:
    """Legacy seal files -> `legacy-seal` markers, one documented
    transaction (§8); the seal files themselves are left on disk."""
    if args.no_write:
        return _refuse_no_write(
            "history migrate-seals", "the .refdes/history/ store"
        )
    project, _stale = _load(args)
    _announce_load_writes(project)
    if args.capture_current:
        build_mod.compute_hashes(project)
    try:
        markers = history_mod.migrate_seals(
            project, capture_current=args.capture_current
        )
    except history_mod.HistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not markers:
        print("no legacy seal files found; nothing to migrate")
        return 0
    created = 0
    for m in markers:
        who = m.display_id or m.record_id
        if m.marker_created:
            created += 1
            print(f"legacy-seal marker for {who} ({m.seal_file})")
            print(
                "  recorded hash only; original content was not captured; "
                "the seal file is left untouched"
            )
        else:
            print(f"{who}: already migrated ({m.seal_file})")
        if m.current == "captured":
            print(
                f"  captured current content of {who} as a migrated-current "
                "event -- clearly dated, not seal-time text"
            )
        elif m.current == "differs":
            print(
                f"  {who}: live content differs from the recorded hash; no "
                "migrated-current snapshot was taken"
            )
        elif m.current == "unresolved":
            print(
                f"  {who}: no live item for this seal record; no "
                "migrated-current snapshot was taken"
            )
    print(
        f"{created} legacy-seal marker(s) written, "
        f"{len(markers) - created} already present"
    )
    return 0


def _version_line() -> str:
    """The `--version` output: the installed package's own version, or an
    honest admission when running from a raw checkout with nothing installed.
    Never raises -- a version flag that dies with a traceback is worse than
    one that says it does not know."""
    try:
        return f"refdes {get_version()}"
    except PackageNotFoundError:
        return "refdes (version unknown -- not installed as a package)"


def main(argv: list[str] | None = None) -> int:
    _fix_console()

    parser = argparse.ArgumentParser(
        prog="refdes",
        description="Reference documentation for hardware design decisions.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=_version_line(),
        help="show the installed version and exit",
    )
    parser.add_argument("-c", "--config", help="path to refdes-project.yaml")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="never modify anything under items/ or .refdes/ -- suppresses "
        "key minting, link/check expansion to composite form, "
        ".refdes/schema.json regeneration, seal recording, "
        "board/workspace membership manifest, baseline stamping, "
        "and the ID ledger (.refdes/ids.yaml); explicit write commands "
        "either report what would change (id, revise, calc-rewrite, "
        "stub-tests, revision, release, keys adopt) or refuse (fetch, init, "
        "standard upgrade, standard add-preset/remove-preset, "
        "former-ids propose --confirm, history capture/redact/"
        "migrate-seals). 'refdes build --no-write' still "
        "writes the site -- that is the command's own output, not a side effect",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser(
        "serve",
        # Abbreviations are off here for one reason: `--token` is a prefix of
        # `--token-file`, and argparse would happily accept `--token=<t>` as the
        # latter -- turning "no flag can carry a token" (docs/design/
        # editor-vscode-adapter.md §3.2 row 4, pinned by
        # tests/test_vscode_adapter_contract.py) into a launch URL written to a
        # file named after the token.
        allow_abbrev=False,
        help="serve the rendered site and a browser editor on 127.0.0.1",
        description="Load this one project and serve two surfaces on a "
        "127.0.0.1 port (ephemeral by default, --port to pin one): the rendered "
        "site as a preview (rebuilt into an OS temp directory, never _site/) at "
        "/preview/, and the "
        "editor at /edit/. The launch URL carries a random per-launch token "
        "that gates every read and write. Loading is side-effect-free: no "
        "key minted, no link expanded, nothing sealed, and no file under "
        "items/ or .refdes/ touched. Edits made outside the browser are "
        "picked up by polling.",
    )
    p_serve.add_argument(
        "--no-open", action="store_true", help="print the launch URL but do not open a browser"
    )
    p_serve.add_argument(
        "--port",
        metavar="PORT",
        type=_serve_port_arg,
        help="bind this exact 127.0.0.1 port instead of an ephemeral one; a port "
        "something else holds is an error and exit 2, never a silent fallback to "
        "another port",
    )
    p_serve.add_argument(
        "--token-file",
        metavar="PATH",
        help="write this launch's URL (which carries the launch token) to PATH "
        "with owner-only permissions, so a script reads the credential instead "
        "of scraping stdout; removed when serve stops cleanly -- on Ctrl+C or "
        "on a SIGTERM (kill $pid), not on a hard kill (kill -9), which cannot "
        "be caught",
    )
    p_serve.set_defaults(func=cmd_serve)

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
        help="accept edits/removals of sealed append-only entries (persisted in "
        "the seal file and shown in `audit`); "
        "bare, this accepts every board's edits, or name one board to scope it, "
        "e.g. --reseal power. A `sealing: history` type has nothing to reseal "
        "and is left untouched",
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
        "or update) append-only seals and board-drift records. What any of that "
        "protects depends on the type's `sealing:`: a `sealing: build` type is "
        "sealed only once 'build' has run over the entry, so an entry that has "
        "never been built has none, however many clean runs of this command it "
        "has behind it, while a `sealing: history` type -- the bundled "
        "hardware@3 `log` -- is never sealed at all, and is protected instead by "
        "the snapshot 'refdes history capture' writes into '.refdes/history/', "
        "an entry that has never been captured having no protection of its own. "
        "Exits non-zero on any error. This command "
        "writes nothing of the project's own -- no site, no seal, no board or "
        "citation manifest, no baseline. Loading the project does write, and "
        "this command loads it like every other: surrogate 'key:' fields on "
        "items that lack one, bare link references normalised to "
        "'DISPLAY-ID@key' composites, and '.refdes/schema.json', the gitignored "
        "editor-completion schema. Those are reported as they happen, and "
        "'--no-write' skips them entirely "
        f"({docs_url_mod.SURROGATE_KEYS_DOCS}).",
    )
    p_check.add_argument(
        "--refresh",
        action="store_true",
        help="also re-fetch every pinned citation and report drift (network; "
        "writes nothing). A pinned citation whose bytes cannot be obtained -- "
        "network down, DNS failure, connection refused, timeout, or an HTTP "
        "error status -- fails the run, because drift was not verified for it; "
        f"see {citations_mod.ALLOW_UNREACHABLE_FLAG}",
    )
    p_check.add_argument(
        citations_mod.ALLOW_UNREACHABLE_FLAG,
        dest="allow_unreachable",
        action="store_true",
        help="with --refresh, downgrade every citation that could not be "
        "re-fetched to a warning, so the exit code reflects only real findings "
        "-- drift, and real project errors. What you give up: the guarantee "
        "that --refresh reached every pinned source. Whatever could not be "
        "fetched is left unverified, and a datasheet deleted at the vendor "
        "passes exactly as a laptop with no network does. Without --refresh "
        "this does nothing.",
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
        "readiness gate. Takes exactly one argument (the name); the global "
        "--no-write flag is accepted to report what would be stamped without "
        "writing.",
    )
    p_revision.add_argument("name", help="baseline name, e.g. rev-b")
    p_revision.set_defaults(func=cmd_revision)

    p_release = sub.add_parser(
        "release",
        help="run the readiness gate and stamp a baseline if it passes",
        description="Run the full readiness gate (release_gate: in "
        "refdes-project.yaml) and stamp .refdes/baselines/<name>.yaml only "
        "if every enabled rule passes. The eight rules are draft_items, "
        "unpinned_citations, missing_kept_copies, uncovered_requirements, "
        "unverified_requirements, info_check_failures, "
        "unaccepted_board_moves, and unaccepted_workspace_moves. On failure, "
        "nothing is written and the blocking rules are printed. Running this "
        "when the project "
        "isn't ready *is* the check -- there is no --dry-run. Takes exactly "
        "one argument (the name); the global --no-write flag is accepted to "
        "report what would be stamped without writing.",
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
        "ls",
        help="list existing items: id, type, [workspace,] board, title -- filterable",
        description="A filterable, human-readable listing of existing items, as "
        "aligned text: id, type, workspace, board, title -- the workspace column "
        "only on a project that declares workspaces:, so the --workspace filter "
        "below is discoverable from the listing it filters. Workspace comes "
        "before board because it groups it one level up. An item in no "
        "workspace leaves that column blank, which is also how it behaves when "
        "you filter: no name passed to --workspace will ever match it. A "
        "project with no workspaces: registry has no workspace for any item, so "
        "it gets no column and byte-identical output. Every filter combines as "
        "a plain AND, and an unknown --type/--board/--workspace name is "
        "answered with 'no items match' (exit 0), the way a query command "
        "answers a typo rather than with a registry error. An items file that "
        "fails to parse is printed to stderr and exits 1 with the listing "
        "intact.",
    )
    p_ls.add_argument(
        "query", nargs="*",
        help="free text, matched against id, title, tags: and former_ids: "
        "(case-insensitive)",
    )
    p_ls.add_argument("--type", help="only items of this type")
    p_ls.add_argument("--board", help="only items on this board")
    p_ls.add_argument("--workspace", help="only items in this workspace")
    p_ls.add_argument("--file", help="only items declared in this source file")
    p_ls.add_argument("--tag", help="only items with a tag containing this text")
    p_ls.set_defaults(func=cmd_ls)

    p_id = sub.add_parser("id", help="allocate IDs for items that have none")
    p_id.add_argument("--dry-run", action="store_true", help="show without writing")
    p_id.set_defaults(func=cmd_id)

    p_fetch = sub.add_parser(
        "fetch",
        help="fetch and pin (optionally keep copies of) datasheet citations",
        description="The only command that touches the network. Fetches every "
        "remote path a `citations:` field declares (local ones are read from "
        "disk), records each sha256 and fetch time in the "
        "`.refdes/citations.yaml` lockfile, and keeps the bytes in "
        "`.refdes/copies/` for any remote citation that declares "
        "`keep_copy: true`. Already-pinned paths are skipped unless --update is "
        "given. A local file cited by a calc `source(\"path\", \"key\")` line "
        "also has each used key extracted and pinned in the lockfile; "
        "--update is how a changed file's new values are accepted.",
    )
    p_fetch.add_argument("--item", help="fetch only this item's citations")
    p_fetch.add_argument("--path", help="fetch only this citation path")
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
        "outstanding append-only seal drift and durable accepted reseal history "
        "(--reseal), accepted and "
        "outstanding board and workspace moves (--accept-board-move), what's "
        "changed since the last revision and the last release (see 'refdes "
        "revision'/'refdes release'), and imported projects. Suppression is "
        "allowed; invisible suppression is not.",
    )
    p_audit.set_defaults(func=cmd_audit)

    p_init = sub.add_parser(
        "init",
        help="write a minimal refdes-project.yaml that points at the standard",
        description="Write a minimal refdes-project.yaml in the current directory -- "
        "site:/standard:/id: only, no types:/link_types:/sets: -- plus "
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
        description="Scaffold a starter item's front matter (or, with --list, "
        "a starter list file) for TYPE, generated "
        "from the identical resolved schema 'refdes schema --json' emits -- not "
        "a second, hand-maintained template that could drift from it. Prints to "
        "stdout; redirect it where you want the item to live, e.g. "
        "'refdes new decision > items/power/dec-005.md'.",
    )
    p_new.add_argument("type", help="an item type in the merged schema, standard or project-defined")
    p_new.add_argument(
        "--list",
        action="store_true",
        help="print a list-file skeleton (defaults: plus one empty entry) "
        "instead of a single item -- redirect it into place, e.g. "
        "'refdes new component --list > items/power/candidates.yaml'",
    )
    p_new.set_defaults(func=cmd_new)

    p_schema = sub.add_parser(
        "schema",
        help="print the project's merged JSON Schema, or type/link graph, to stdout",
        description="Emit the project's actual merged schema -- base at its "
        "pinned version, plus selected presets, plus the project overlay -- "
        "as JSON Schema (--json, the default; the same schema is written to "
        ".refdes/schema.json by every command that loads the project, this is "
        "the explicit standalone form) or as one connection diagram per "
        "type, each a standalone SVG document (--graph): generated from the "
        "resolved schema so it can't go stale the way a hand-drawn diagram "
        "would the moment a preset or overlay changes a verb, and drawn "
        "here rather than handed to Mermaid or graphviz so the picture "
        "needs no renderer beyond a browser. Each drawing shows one type "
        "and its own connections: types that may point at it on the left, "
        "types it points at on the right, verbs labelled on the arrows. "
        "With TYPE, draw only that type's diagram; without it, every "
        "type's in turn.",
    )
    p_schema.add_argument(
        "--json", action="store_true", help="JSON Schema output (the default)"
    )
    p_schema.add_argument(
        "--graph",
        action="store_true",
        help="draw each type's connection diagram as an SVG document, to stdout",
    )
    p_schema.add_argument(
        "type",
        nargs="?",
        default=None,
        help="with --graph: draw only this type's diagram",
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
        "chain of individual deltas, in order. Refuses the failing step, "
        "rolling it back cleanly rather than guessing at an ambiguous or "
        "ill-formed one; earlier steps in the chain stay applied.",
    )
    p_standard_upgrade.add_argument(
        "--to", type=int, required=True, metavar="N",
        help="target standard.version: to upgrade to",
    )
    p_standard_upgrade.set_defaults(func=cmd_standard_upgrade)

    p_keys = sub.add_parser(
        "keys",
        help="manage immutable surrogate-key storage",
    )
    keys_sub = p_keys.add_subparsers(dest="keys_command", required=True)
    p_keys_adopt = keys_sub.add_parser(
        "adopt",
        help="transactionally adopt key-keyed baselines and seals",
        description="Mint every missing local key, expand structured links, "
        "re-key every baseline and seal file, then reload and fully validate "
        "the project. Any failure restores every touched file.",
    )
    p_keys_adopt.add_argument(
        "--dry-run", action="store_true", help="show the complete plan without writing"
    )
    p_keys_adopt.set_defaults(func=cmd_keys_adopt)

    p_keys_restore = keys_sub.add_parser(
        "restore",
        help="restore explicitly supplied original item keys",
        description="After checking git history to confirm each item's identity, "
        "supply DISPLAY-ID@ORIGINAL-KEY for every lost or regenerated key. "
        "Validate the proposed project before writing and reload afterwards; "
        "any failure restores the original files. References and history are "
        "not rewritten. Refuses keys already owned by another item, current "
        "keys recorded in history, and -- where a baseline records the key "
        "under a different title or content hash than the item it is being "
        "moved onto -- that restore too, since it would hand the old item's "
        "references to an unrelated one; --force overrides that one refusal. "
        "Supply multiple targets to repair them together.",
    )
    p_keys_restore.add_argument("targets", nargs="+", metavar="DISPLAY-ID@ORIGINAL-KEY")
    p_keys_restore.add_argument(
        "--dry-run", action="store_true", help="validate the complete plan without writing"
    )
    p_keys_restore.add_argument(
        "--force",
        action="store_true",
        help="restore even when the most recent baseline recording the key "
        "shows different content than the item it is being moved onto -- for "
        "the same item edited since the baseline was stamped",
    )
    p_keys_restore.set_defaults(func=cmd_keys_restore)

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
        help=(
            "path to a YAML file with types:/fields:/links:/prefixes:/"
            "citation_keys: renames -- any other top-level section is refused"
        ),
    )
    p_revise.add_argument(
        "--dry-run", action="store_true", help="show what would change without writing"
    )
    p_revise.set_defaults(func=cmd_revise)

    p_calc_rewrite = sub.add_parser(
        "calc-rewrite",
        help="rewrite retired 'name : unit = expression' calc lines to the "
        "pipe form 'name = expression | unit'",
        description="Rewrite every old-spelling unit assertion inside ```calc "
        "fences in item bodies to the pipe form, in place, preserving "
        "indentation and comments. Prose and {{name}} references are never "
        "touched. Transactional like 'refdes revise': the rewritten project is "
        "reloaded, fully validated, and every calc's evaluated result and unit "
        "are compared against before -- any change in what a calc computes "
        "rolls every file back. Content hashes and calc hashes are carried "
        "forward across stamped baselines, since a spelling-only rewrite is "
        "not a content change. Sealed append-only entries are never rewritten; "
        "they are listed and left on the old spelling, which still evaluates.",
    )
    p_calc_rewrite.add_argument(
        "--dry-run", action="store_true", help="show what would change without writing"
    )
    p_calc_rewrite.set_defaults(func=cmd_calc_rewrite)

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

    p_history = sub.add_parser(
        "history",
        help="capture, redact, and migrate the captured-history store",
        description="Direct author-facing access to .refdes/history/: capture "
        "one item's snapshot by hand (for terminal and unthreaded notes a "
        "`follows:` edge will never supply), redact objects and events out of "
        "the store with an auditable trail, and migrate legacy append-only "
        "seal files into legacy-seal history markers. Every subcommand "
        "refuses under --no-write rather than pretending it wrote something.",
    )
    history_sub = p_history.add_subparsers(dest="history_command", required=True)

    p_history_capture = history_sub.add_parser(
        "capture",
        help="capture an item's current snapshot as a `captured` event",
        description="Capture ITEM's current semantic snapshot into "
        ".refdes/history/ as a manual `captured` event, and announce it. "
        "Says 'captured', never 'final': the item stays editable, and a "
        "later edit is the same 'edited after captured' diagnostic any other "
        "capture gives. Idempotent -- one capture event per item; a second "
        "run writes nothing new and announces nothing.",
    )
    p_history_capture.add_argument(
        "item", help="display id or surrogate key of the item to capture"
    )
    p_history_capture.set_defaults(func=cmd_history_capture)

    p_history_redact = history_sub.add_parser(
        "redact",
        help="remove history objects and events, with an auditable redaction event",
        description="Remove matching history objects and events from "
        ".refdes/history/ and write one redaction event naming what was "
        "removed -- by digest and event id only, without repeating any of its "
        "content. TARGET is an item (display id or surrogate key: every "
        "capture event of it, plus the snapshots no other event still "
        "references) or a full 64-hex object digest. Requires --confirm. "
        "This cannot remove data already committed to Git, present in "
        "clones, or published in built sites, and says so in its own "
        "output.",
    )
    p_history_redact.add_argument(
        "target",
        help="display id, surrogate key, or 64-hex history object digest",
    )
    p_history_redact.add_argument(
        "--confirm",
        action="store_true",
        help="acknowledge that redaction is irreversible and cannot reach "
        "Git, clones, or published copies",
    )
    p_history_redact.set_defaults(func=cmd_history_redact)

    p_history_migrate = history_sub.add_parser(
        "migrate-seals",
        help="record legacy seal files as legacy-seal history markers",
        description="Read the legacy append-only seal files "
        "(.refdes/log-seal*.yaml) and write one `legacy-seal` marker event "
        "per seal record: recorded hash only; original content was not "
        "captured. The seal files themselves are read, never modified, and "
        "stay on disk until a later phase retires them. Idempotent. This is "
        "the documented migration §8 requires before legacy seal support is "
        "ever deleted.",
    )
    p_history_migrate.add_argument(
        "--capture-current",
        action="store_true",
        help="also capture the current snapshot of each sealed item whose "
        "live content still matches its recorded hash, as a clearly dated "
        "`migrated-current` event -- never labelled seal-time text",
    )
    p_history_migrate.set_defaults(func=cmd_history_migrate_seals)

    args = parser.parse_args(argv)
    try:
        # Take the lock before loading: the load itself can rewrite sources,
        # and ID planning must see the ledger left by the previous process.
        if args.no_write or getattr(args, "dry_run", False) or args.command in {
            "serve", "init", "new", "schema"
        }:
            return args.func(args)
        from .schema import find_config

        config = args.config or find_config()
        with project_write_lock(os.path.dirname(os.path.abspath(config))):
            return args.func(args)
    except SchemaError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except LockUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
