"""Core object model.

Everything downstream -- validation, calc, checks, rendering, and eventually the
git history layer -- reads these structures and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# on_change modes. Only `invalidate` does anything today: compute_hashes()
# (build.py) is the sole consumer and only checks for INVALIDATE, so `log` and
# `ignore` are currently indistinguishable -- both are excluded from the content
# hash and neither is written anywhere. `log` is reserved for a future per-field
# history layer; until that exists it behaves exactly like `ignore`.
INVALIDATE = "invalidate"  # feeds the content hash and suspect-link invalidation
LOG = "log"                # reserved for a future history layer -- behaves as ignore today
IGNORE = "ignore"          # excluded from the content hash
ON_CHANGE_MODES = (INVALIDATE, LOG, IGNORE)


# Diagnostic severities, in descending order of consequence.
ERROR = "error"      # blocks the build
WARNING = "warning"  # visible by default; worth a look
INFO = "info"        # default-hidden; the normal state of an incomplete project
DIAGNOSTIC_LEVELS = (ERROR, WARNING, INFO)


# refdes-project.yaml: project-level presentation/behaviour settings, distinct
# from refdes.yaml's schema. See schema.py's loader for validation.
# "flat" is today's items/<board>/; "workspace" adds one more path segment,
# items/<workspace>/<board>/ -- a fixed choice, not a path template, so the
# tool never has to promise arbitrary nesting depth. See boards.py/workspaces.py
# and docs/workspaces.md.
ITEM_LAYOUTS = ("flat", "workspace")
BASELINE_IDENTITIES = ("os_user", "git_identity")

# The eight configurable release-gate rules from docs/design/lifecycle.md §1
# (unaccepted_workspace_moves added alongside its board-move counterpart,
# see docs/lifecycle.md), with their shipped (release, revision) defaults.
RELEASE_GATE_DEFAULTS: dict[str, dict[str, bool]] = {
    "draft_items":                {"release": True,  "revision": False},
    "unpinned_citations":         {"release": True,  "revision": False},
    "missing_vendored_copies":    {"release": True,  "revision": False},
    "uncovered_requirements":     {"release": True,  "revision": False},
    "unverified_requirements":    {"release": False, "revision": False},
    "info_check_failures":        {"release": False, "revision": False},
    "unaccepted_board_moves":     {"release": True,  "revision": False},
    # Same default as unaccepted_board_moves -- a silent workspace change is
    # the same class of drift a release shouldn't ship past unnoticed.
    "unaccepted_workspace_moves": {"release": True,  "revision": False},
}


def _default_release_gate() -> dict[str, dict[str, bool]]:
    return {name: dict(rule) for name, rule in RELEASE_GATE_DEFAULTS.items()}


class SchemaError(Exception):
    """Raised for any configuration-time problem in refdes.yaml, refdes-project.yaml,
    or the standard library bundle -- never for a per-item build-time diagnostic,
    which goes through Project.error() instead. Defined here, not in schema.py or
    standards.py, so both can raise it without importing each other."""


@dataclass
class Diagnostic:
    """A validation message. `where` is rendered as file:line for editors."""

    level: str  # "error" | "warning" | "info"
    message: str
    file: str | None = None
    line: int | None = None
    item_id: str | None = None

    @property
    def where(self) -> str:
        if self.file and self.line:
            return f"{self.file}:{self.line}"
        if self.file:
            return self.file
        return self.item_id or "<project>"

    def __str__(self) -> str:
        head = f"{self.where}"
        if self.item_id and self.file:
            head += f" [{self.item_id}]"
        return f"{self.level.upper():7} {head} — {self.message}"


@dataclass
class FieldSpec:
    name: str
    type: str = "text"
    on_change: str = INVALIDATE
    required: bool = False
    choices: list[str] | None = None
    default: Any = None
    # Conditional requiredness: {other_field_or_"links": value_or_[values]}, ANDed
    # across keys, ORed within a key's value list. Mutually exclusive with
    # `required` -- see docs/design/standard-library.md §2 "Conditional
    # requiredness". None means unconditional (ordinary `required:` behavior only).
    required_when: dict[str, Any] | None = None


@dataclass
class LinkType:
    name: str
    inverse: str
    label: str
    # Whether this verb participates in a {{cascade}} block's default `via`
    # set. Schema-declared metadata, exactly like check_severity or
    # satisfying_statuses -- a fact about the verb, set once, not something
    # an author composes per-block. True by default: every link traces
    # unless its schema explicitly opts it out (amends/records/supersedes/
    # addresses in the bundled standard, none of which is "this item's
    # correctness is justified by that one").
    trace: bool = True


@dataclass
class BoardSpec:
    """One entry in the opt-in `boards:` registry.

    A board's items are matched by the first path segment under `items/`, unless
    `path` says that segment is spelled differently from the board's own key --
    or, under `item_layout: workspace`, the second segment (see WorkspaceSpec).
    """

    name: str
    label: str
    token: str = ""  # optional; checked for consistency against item id prefixes
    path: str = ""   # alias for the items/ path segment; defaults to `name`

    @property
    def path_segment(self) -> str:
        return self.path or self.name


@dataclass
class WorkspaceSpec:
    """One entry in the opt-in `workspaces:` registry -- an ownership boundary
    one level above boards. A workspace holds everything used only by that
    workspace; it's the seam along which a project would later split, so
    extracting it is a folder move, not a renumbering. Matched by the first
    path segment under `items/` when `item_layout: workspace`, unless `path`
    says that segment is spelled differently from the workspace's own key.

    `shared: true` means any workspace may depend on this one -- see
    workspaces.py's cross-workspace reference lint, which otherwise flags an
    authored link crossing from one workspace into another as a hidden
    dependency that would make the source workspace harder to extract later.
    """

    name: str
    label: str
    shared: bool = False
    path: str = ""  # alias for the items/ path segment; defaults to `name`

    @property
    def path_segment(self) -> str:
        return self.path or self.name


@dataclass
class ItemType:
    name: str
    prefix: str
    label: str
    plural: str = ""
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    links: dict[str, list[str]] = field(default_factory=dict)  # link name -> allowed target types
    preview: list[str] = field(default_factory=list)
    body_on_change: str = INVALIDATE
    append_only: bool = False  # sealed after first build; corrections go in new entries
    # Which `status` values count as "settled" when this type satisfies a
    # requirement or constraint. None means unconfigured: every link counts, same
    # as before this existed, so existing projects see no behavior change.
    satisfying_statuses: list[str] | None = None
    # Diagnostic level a failing `checks:` entry is reported at for items of this
    # type. A decision either meets its constraints or it doesn't, so ERROR is
    # the default; a type whose items are still candidates being compared (e.g.
    # "option") can set this to INFO so a failed criterion is a finding, not a
    # build-blocking defect.
    check_severity: str = ERROR
    # Engine-level coverage-participation flags -- schema language, not standard
    # content (docs/design/standard-library.md §2). None means "not declared":
    # compute_coverage() falls back to the pre-existing name-based convention
    # (requirement/constraint are coverable) with a one-time warning, so a project
    # written before these existed sees no behavior change.
    coverable: bool | None = None
    # Statuses at which an item of this type actually counts as coverable, e.g.
    # [active] to exclude both draft and retired. None means unconfigured: falls
    # back to excluding `status == "retired"` if a status field exists, and
    # excluding nothing otherwise -- see compute_coverage().
    coverable_statuses: list[str] | None = None
    # Statuses at which a verifier item (one that declares a `verifies`-family
    # link) actually counts as having verified something, mirroring
    # satisfying_statuses. None means every link counts, same as before this
    # existed.
    verifying_statuses: list[str] | None = None


@dataclass
class CheckResult:
    """One `checks:` entry, evaluated."""

    value_name: str
    against: str                 # target item id
    ok: bool | None = None       # None => could not evaluate
    detail: str = ""
    actual: str = ""
    limit: str = ""
    margin: float | None = None  # fractional slack; negative means violated

    @property
    def margin_pct(self) -> float | None:
        return None if self.margin is None else self.margin * 100.0


@dataclass
class CitationSpec:
    """One entry of a `citations:`-typed field -- declared intent only.

    Computed provenance (hash, fetch time, vendored flag) is never stored here or
    on the item; it lives in the `.refdes/citations.yaml` lockfile, keyed by url,
    so that re-fetching a datasheet can never retroactively mark a sealed log
    entry -- or any other suspect-link consumer of an item's content hash -- as
    edited.
    """

    field: str
    index: int
    url: str
    rev: str = ""
    page: str = ""
    part_number: str = ""
    vendor: bool = False


@dataclass
class CitationStatus:
    """One citation, resolved against the lockfile at build/check time."""

    spec: CitationSpec
    item_id: str
    state: str = "ok"  # "ok" | "unpinned" | "cache_missing" | "hash_mismatch"
    detail: str = ""
    sha256: str = ""
    fetched: str = ""
    vendored: bool = False
    # Path to the published copy, relative to `assets/` (e.g.
    # "datasheets/<sha256>.pdf") -- set only when the citation is vendored AND
    # Project.publish_datasheets is on; empty otherwise, which is also how the
    # rendered citation link knows to point upstream instead of to a local copy.
    local_path: str = ""


@dataclass
class CalcLine:
    """One line of a ```calc block, evaluated."""

    name: str
    expression: str
    result: str = ""        # formatted nominal, e.g. "0.298 W"
    bounds: str = ""        # formatted interval when the value has tolerance
    comment: str = ""
    error: str | None = None
    annotation: str = ""    # declared unit, e.g. "W" in `P_diss : W = ...`


@dataclass
class Item:
    id: str
    type: str
    fields: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    links: dict[str, list[str]] = field(default_factory=dict)
    backlinks: dict[str, list[str]] = field(default_factory=dict)
    source_file: str = ""
    source_line: int = 1
    # Populated during build:
    calcs: list[CalcLine] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    body_html: str = ""
    history: dict[str, Any] = field(default_factory=dict)  # item-level on_change overrides
    calc_values: dict[str, str] = field(default_factory=dict)  # name -> formatted result
    prefix_hint: str = ""  # 'prefix:' override -- own key or file/block defaults:, used by the ID allocator
    content_hash: str = ""  # over `invalidate` fields only; drives suspect links
    external: bool = False  # imported from another project: read-only here
    origin: str = ""        # name of the import it came from
    board_hint: str = ""    # explicit `board:` override, item value beats file defaults
    board: str = ""         # resolved board key; "" if boards: is unused or no match
    workspace_hint: str = ""  # explicit `workspace:` override, same precedence as board_hint
    workspace: str = ""       # resolved workspace key; "" if workspaces: is unused or no match
    citations: list[CitationStatus] = field(default_factory=list)  # populated during build

    @property
    def title(self) -> str:
        # `summary` is what a log entry calls its one-line description, and `name`
        # what a component calls it. Without them those types fall back to their own
        # ID, so every table that shows a title renders a column of bare IDs.
        for key in ("title", "text", "summary", "name"):
            value = self.fields.get(key)
            if value:
                text = str(value).strip()
                return text if len(text) <= 90 else text[:87].rstrip() + "…"
        return self.id

    @property
    def slug(self) -> str:
        return self.id.lower()

    def on_change_for(self, field_name: str, spec: ItemType, default: str) -> str:
        """Precedence: item override > schema field > project default."""
        override = (self.history or {}).get("fields", {}).get(field_name)
        if override in ON_CHANGE_MODES:
            return override
        whole = self.history.get("mode") if isinstance(self.history, dict) else None
        if whole in ON_CHANGE_MODES:
            return whole
        fs = spec.fields.get(field_name)
        if fs:
            return fs.on_change
        return default


@dataclass
class Page:
    """A narrative markdown page: prose, not an item.

    Pages have no ID, no fields, no links, and no coverage. They exist because a
    project needs somewhere to put a board overview or a "how to read this" note
    that is not a requirement. They can reference items by ID and get the same
    hover previews as anywhere else.
    """

    slug: str
    title: str
    body: str
    source_file: str
    order: int = 100
    in_nav: bool = True
    board: str = ""  # optional `board:` tag; groups this page under that board's nav entry
    workspace: str = ""  # optional `workspace:` tag; groups this page under that workspace's nav entry
    body_html: str = ""
    headings: list[tuple[int, str, str]] = field(default_factory=list)  # level, text, anchor


@dataclass
class ImportSpec:
    name: str
    items_path: str
    version: str | None = None


@dataclass
class Coverage:
    """Four distinct notions of 'done' for one requirement or constraint."""

    item_id: str
    addressed_by: list[str] = field(default_factory=list)   # log entries
    claimed_by: list[str] = field(default_factory=list)     # decisions/components, not yet settled
    satisfied_by: list[str] = field(default_factory=list)   # decisions/components, settled
    verified_by: list[str] = field(default_factory=list)    # tests

    @property
    def stage(self) -> str:
        if self.verified_by:
            return "verified"
        if self.satisfied_by:
            return "satisfied"
        if self.claimed_by:
            return "claimed"
        if self.addressed_by:
            return "addressed"
        return "open"


@dataclass
class BlockedChain:
    """One direct `blocked_by:` edge, resolved to its structural root
    (docs/design/standard-library.md §9). The declared edge is direct; this
    is the transitive resolution -- naming the root cause, not just the
    nearest link in the chain, is the whole point of building this.

    `path` is the full walk from the declaring item to the root, both ends
    inclusive: `[item_id, ..., root_id]`. `len(path) == 2` for a direct
    block with no further chain of its own.
    """

    item_id: str
    path: list[str]
    root_id: str
    root_status: str | None
    # Whether path[1] (the *direct* target, not necessarily the root) has
    # reached a settled status while this edge is still declared -- a fact
    # about this one edge, independent of how deep the chain runs past it.
    stale: bool


@dataclass
class Project:
    title: str
    out_dir: str
    types: dict[str, ItemType]
    link_types: dict[str, LinkType]
    inverse_of: dict[str, str]
    default_on_change: str
    id_width: int
    id_ledger: str
    preferred_units: list[str]
    unit_aliases: dict[str, str] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    pages: list[Page] = field(default_factory=list)
    pages_dir: str = "pages"
    nav_order: list[str] = field(default_factory=list)
    pending: list[Item] = field(default_factory=list)  # parsed but not yet allocated an id
    diagnostics: list[Diagnostic] = field(default_factory=list)
    root: str = "."
    version: str = ""
    imports: list[ImportSpec] = field(default_factory=list)
    coverage: dict[str, Coverage] = field(default_factory=dict)
    blocked_chains: list[BlockedChain] = field(default_factory=list)
    seal_violations: list[str] = field(default_factory=list)
    boards: dict[str, BoardSpec] = field(default_factory=dict)
    # (item_id, previous_board, current_board), for items whose board changed
    # since the last time `.refdes/boards.yaml` was written.
    board_moves: list[tuple[str, str, str]] = field(default_factory=list)
    workspaces: dict[str, WorkspaceSpec] = field(default_factory=dict)
    # Same shape as board_moves, for workspace membership -- recorded in the
    # same `.refdes/boards.yaml` manifest, under its own `workspaces:` key.
    workspace_moves: list[tuple[str, str, str]] = field(default_factory=list)
    # Every local file that must be copied into `_site/assets/`: source path
    # (project-root-relative) -> destination path (relative to assets/).
    # Populated by resolved local `<img>` references (hashed leaf filename,
    # docs/design/index-blocks.md §10) and by `site.assets:` directories
    # (identity mapping -- an author's own hand-typed href to one of those
    # files must keep working unrewritten, so those never hash). Keyed by
    # source so the same image referenced from many items/pages hashes once.
    assets: dict[str, str] = field(default_factory=dict)
    asset_dirs: list[str] = field(default_factory=list)  # site.assets: raw config
    # Figure id -> (owner label for a collision message, source file, source
    # line or None) -- one flat, project-wide namespace, the same posture
    # item ids already have (docs/design/index-blocks.md §9). Populated by
    # _apply_figure_attrs as each `{id="..."}` is seen; a second use of the
    # same id is a build error naming both locations.
    figures: dict[str, tuple[str, str, int | None]] = field(default_factory=dict)
    # Vendored datasheet copies to publish into the site: {dest path relative to
    # assets/ (flattened, e.g. "datasheets/<sha256>.pdf") -> absolute source
    # path in the vendor cache}. Populated by citations.verify() only when
    # publish_datasheets is on; copied by render.render_site(). Unlike `assets`
    # above, source and destination paths differ (flattened, not mirrored), so
    # this can't reuse that set.
    datasheet_assets: dict[str, str] = field(default_factory=dict)

    # refdes-project.yaml settings -- see schema.py's loader. Every default here
    # matches today's behaviour except `publish_datasheets` (see its own field)
    # and `sigfigs`/`baseline_identity`, which had no prior behaviour to match.
    sigfigs: int = 4
    item_layout: str = "flat"  # "flat" | "workspace" -- see model.ITEM_LAYOUTS
    baseline_identity: str = "os_user"  # "os_user" | "git_identity"
    require_rejection_rationale: bool = True  # decision.rationale required_when toggle
    # Whether verify() copies vendored citation PDFs into _site/. Default false:
    # manufacturer datasheets are generally copyrighted, and publishing them is
    # a redistribution question a project must opt into, not one this tool
    # should decide by default -- a deliberate change from pre-config behaviour,
    # which copied unconditionally.
    publish_datasheets: bool = False
    release_gate: dict[str, dict[str, bool]] = field(default_factory=_default_release_gate)
    # Diagnostic level for an authored link crossing from one workspace into a
    # non-shared one (workspaces.py's cross-workspace lint). Configurable
    # because how strictly a project wants this enforced varies; defaults to
    # warning, not error, so adopting workspaces never breaks an existing build.
    cross_workspace_severity: str = WARNING

    @property
    def local_items(self) -> list[Item]:
        """Items authored here -- imports are read-only and not our problem."""
        return [i for i in self.items.values() if not i.external]

    def error(self, message: str, **kw: Any) -> None:
        self.diagnostics.append(Diagnostic(ERROR, message, **kw))

    def warn(self, message: str, **kw: Any) -> None:
        self.diagnostics.append(Diagnostic(WARNING, message, **kw))

    def info(self, message: str, **kw: Any) -> None:
        self.diagnostics.append(Diagnostic(INFO, message, **kw))

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.level == ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.level == WARNING]

    @property
    def infos(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.level == INFO]
