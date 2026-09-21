"""The one project load pipeline, with and without side effects.

`load_tree` is what every command's `_load()` runs: parse the item sources,
mint missing surrogate keys, expand bare links/checks/calc references to
composites, freeze `follows:`. With ``write=True`` those steps rewrite source
files (docs/design/keys.md §2); with ``write=False`` (the global
``--no-write``) each one still resolves in memory but nothing under `items/`
or `.refdes/` is touched.

`load_readonly` is the browser editor's entry point (docs/design/
browser-editor.md, Slice 0): load + full `build()` with every write off, and
optionally an in-memory *source overlay* -- replacement text for item files --
so a candidate edit can be built and validated before it is written. The
editor consumes this path rather than growing a second "mostly read-only"
loader.
"""

from __future__ import annotations

from collections.abc import Mapping

from . import build as build_mod
from . import imports as imports_mod
from . import keys as keys_mod
from . import links as links_mod
from . import parse as parse_mod
from . import schema_json as schema_json_mod
from .model import Project
from .schema import load_project


def parse_items(
    project: Project, require_ids: bool, discard: tuple[int, int] | None
) -> tuple[int, int]:
    """Parse (or re-parse) project.items/pending, returning the (start, end)
    index range this call's own diagnostics occupy in project.diagnostics.

    `discard`, when given, is that same kind of range from a PREVIOUS parse
    of this project, removed before this one runs. That matters because
    keys.mint_missing()/links.expand_missing() write into the source tree
    and then need a fresh parse: minting inserts a `key:` line, which shifts
    every subsequent line number in that file -- and item.source_line, read
    from the *original* parse, is exactly what a later write-back (link
    expansion's own, or a following reload) keys on. Without discarding the
    stale range first, reparsing would simply re-derive the same parse-time
    diagnostics (a missing-id error, a malformed-YAML error, ...) from the
    now-current files and append them a second time, on top of the first
    parse's now-outdated set -- silently doubling every such diagnostic
    rather than describing the project once, correctly.
    """
    if discard is not None:
        del project.diagnostics[discard[0] : discard[1]]
        project.items = {}
        project.items_by_id = {}
        project.pending = []
    start = len(project.diagnostics)
    parse_mod.load_items(project, require_ids=require_ids)
    return start, len(project.diagnostics)


def load_tree(
    config_path: str | None,
    require_ids: bool = True,
    write: bool = True,
    overlay: Mapping[str, str] | None = None,
) -> tuple[Project, bool]:
    """Returns (project, schema_was_stale); see `cli._load` for the latter.

    `overlay` maps item-source paths to replacement text (see
    `Project.source_overlay`). Overlays are only meaningful read-only: the
    write-back steps address files by path and line, and would rewrite the
    real file from overlay-derived positions.
    """
    if overlay and write:
        raise ValueError("a source overlay can only be loaded with write=False")
    project = load_project(config_path=config_path)
    if overlay:
        project.source_overlay = {
            parse_mod.overlay_key(path): text for path, text in overlay.items()
        }
    # A cheap side effect of loading, not a job of its own -- every command
    # that reaches this point has already resolved the full merged schema,
    # so writing .refdes/schema.json here is the same housekeeping posture
    # `build` already applies to .refdes/boards.yaml and the ID ledger
    # (docs/design/standard-library.md §12). `write=False` suppresses it but
    # still gets the staleness verdict, so `check`'s trip-wire diagnostic
    # survives a read-only pass (docs/design/keys.md §2).
    schema_was_stale = schema_json_mod.write_schema(project, write=write)
    parse_span = parse_items(project, require_ids, discard=None)

    # Same posture, extended to surrogate keys (docs/design/keys.md §2): a key
    # has none of what makes `refdes id` a deliberate, separate step, so any
    # command that already loads the project fills in missing ones as a side
    # effect. `--no-write` is the escape for a genuinely read-only pass (CI
    # checking out a tree, inspecting someone else's project, a bisect over
    # historical commits): it now gates every incidental write in the load
    # path -- minting, expansion, schema.json here, and, in build(), the
    # seals and the membership manifest (docs/design/keys.md §9 item 4).
    minted = keys_mod.mint_missing(project, write=write)
    if minted:
        parse_span = parse_items(project, require_ids, discard=parse_span)

    # Imported artifacts join the resolution scope before structured link
    # expansion: a bare local link to an imported keyed item must freeze to
    # the same composite form as a local target. load_imports() is idempotent,
    # so build() reuses this populated graph.
    imports_mod.load_imports(project)

    # §3: maintain structured links as `DISPLAY-ID@key` composites. Bare
    # references to keyed targets gain their key half; stale display halves
    # refresh after a target rename unless the old label now names a different
    # live item. Must run after minting (a target needs its own key before
    # there's anything to expand into). The source rewrite updates item.links
    # in memory and preserves line counts, so imported targets remain loaded.
    links_mod.expand_missing(project, write=write)

    # Same treatment for `checks: [{value, against}]` -- `against:` names an
    # item the same way a structured link target does but isn't a `links:`
    # reference, so expand_missing() alone never sees it (docs/design/keys.md's
    # disclosed gap, closed). The in-memory update above also keeps imported
    # targets available for this companion expansion.
    links_mod.expand_missing_checks(project, write=write)

    # Same treatment for cross-item calc references (`V_in = DEC-PWR-001.V_in`,
    # finding 35): a bare target freezes to the composite and stale display
    # halves refresh through the same _planned_target rule. Under --no-write
    # the bare reference still resolves on the display id; only the write-back
    # is skipped.
    links_mod.expand_missing_calc_refs(project, write=write)

    # A bare follows reference means "continue this thread", not "pin this
    # named entry". Resolve it once to the current frozen-edge tip after keys
    # exist, then reparse so build sees the durable composite-or-bare-key
    # spelling. The same global --no-write gate that protects ordinary link
    # expansion also protects this append-only-sensitive rewrite.
    frozen_follows = links_mod.freeze_follows(project, write=write)
    if frozen_follows:
        # The follow-freeze writer is the one later source rewrite that still
        # needs a reparse. Rebuild the imported portion of the resolution
        # scope afterward so build() never sees a local-only graph.
        project.imports_loaded = False
        parse_items(project, require_ids, discard=parse_span)
        imports_mod.load_imports(project)

    return project, schema_was_stale


def load_readonly(
    config_path: str | None = None,
    overlay: Mapping[str, str] | None = None,
) -> Project:
    """Load and fully build a project with every write suppressed.

    Nothing under `items/`, `.refdes/`, or the config files is created or
    modified: no key minted, no link expanded, no `schema.json`, no seal, no
    membership manifest, no ledger entry (`build(seal_write=False)`). Keyless
    items therefore carry an empty `key` in the result -- the same signal
    `--no-write` gives, and what the editor reads as "cannot write a
    composite to this target yet".

    `overlay` substitutes in-memory text for item source files, so the caller
    sees exactly the project a proposed edit would produce. Diagnostics from
    a broken file are reported on the returned project rather than raised
    (the `index` posture), so a half-typed candidate is inspectable.
    """
    project, _stale = load_tree(
        config_path, require_ids=False, write=False, overlay=overlay
    )
    build_mod.build(project, seal_write=False, reseal=False)
    return project
