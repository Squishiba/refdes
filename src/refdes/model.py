"""Core object model.

Everything downstream -- validation, calc, checks, rendering, and eventually the
git history layer -- reads these structures and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .calc import Equation

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

# `Diagnostic.code` values. A check that ran and produced a violating result
# is a finding *about the design*, not a defect in the document -- the tool
# working, not failing -- and it is a state a real project sits in for weeks.
# Anything that needs to act on that distinction rather than just print the
# message looks for this. Today that is one caller: `refdes revise` and
# `refdes standard upgrade`, which must not be blocked by it.
CHECK_VIOLATION = "check_violation"
# A calc line using the retired `name : unit = expression` spelling. Errors
# with this code are what `refdes calc-rewrite` exists to fix, so the
# rewrite's pre-flight validation tolerates them -- no other error may hide
# behind that exemption.
RETIRED_UNIT_SPELLING = "retired_unit_spelling"


# refdes-project.yaml: project-level presentation/behaviour settings, distinct
# from refdes-project.yaml's schema. See schema.py's loader for validation.
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
    """Raised for any configuration-time problem in refdes-project.yaml, refdes-project.yaml,
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
    # A stable machine-readable tag for the *kind* of finding, set only where
    # something needs to reason about a diagnostic rather than print it.
    # Today that is one case: CHECK_VIOLATION, which `refdes revise` and
    # `refdes standard upgrade` must be able to tell apart from a project
    # that does not parse or validate. Everything else leaves it None rather
    # than growing a taxonomy nothing reads.
    code: str | None = None

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
    # The field's own definition, written next to its declaration (finding 38).
    # "" means undeclared, never rendered: a project that writes no `doc:` keys
    # exports exactly what it exported before this key existed.
    doc: str = ""


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
    # The verb's own definition (finding 38); "" when undeclared.
    doc: str = ""


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
    # Group item ids (`GRP-...`, hardware@3's `group` type) whose members this
    # board owes a per-board coverage obligation to -- "every board conforms to
    # the debug-header contract" (docs/design/backlog.md finding 24). A name
    # that does not resolve to a group item is a hard error, never a silently
    # empty obligation set.
    conforms_to: list[str] = field(default_factory=list)
    # Group item ids whose `contains` members this board DISPLAYS on its scoped
    # pages without owning them (docs/design/backlog.md finding 33): a shared
    # component both boards buy appears on each board's parts/document pages,
    # labelled shared. Display only -- counts, coverage, seals, the manifest and
    # the release gate never consult this; ownership stays `item.board`.
    includes: list[str] = field(default_factory=list)

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
    # hardware@3: true on requirement/bound, whose one content field is now
    # body: -- folded in from the old text:, a field unification distinct
    # from (and not) finding 3's own proposal. Enforced as a warning, not an
    # error (see build.validate_items()): a requirement with no statement
    # isn't one, but a stub still needs to be able to exist while it's being
    # drafted. False everywhere else, including test (method: folded in too,
    # but was never required itself, so folding it into body must not make
    # body required there either).
    body_required: bool = False
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
    # The type's own definition (finding 38); "" when undeclared.
    doc: str = ""


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
    on the item; it lives in the `.refdes/citations.yaml` lockfile, keyed by path,
    so that re-fetching a datasheet can never retroactively mark a sealed log
    entry -- or any other suspect-link consumer of an item's content hash -- as
    edited.
    """

    field: str
    index: int
    # Where the document is: an http(s) URL (fetched, hashed, optionally
    # vendored) or a project-root-relative path (never fetched, hashed from
    # the local bytes at build time). One field, dispatched on scheme --
    # "where the document is" is one idea (finding 25 Part 2).
    path: str
    rev: str = ""
    page: str = ""
    # A human-written outline title from the document itself (finding 23 Part 2),
    # resolved to a page number at `refdes fetch` time from the pinned bytes'
    # PDF outline -- never during a build, which stays hermetic. The resolved
    # page lands in the lockfile record under `sections:`, not here: this is
    # still declared intent only.
    section: str = ""
    part_number: str = ""
    vendor: bool = False
    # Optional, project-wide-unique (finding 19 Part B) -- what `[[cite:<id>]]`
    # in prose resolves to. "" when the entry declares none, which is most of
    # them: giving a citation an id is only worth doing when something needs to
    # reference this specific entry rather than the item that declares it.
    id: str = ""


@dataclass
class CitationStatus:
    """One citation, resolved against the lockfile at build/check time."""

    spec: CitationSpec
    item_id: str
    # "missing" is local-only: the cited repo file does not exist on disk.
    state: str = "ok"  # "ok" | "unpinned" | "cache_missing" | "hash_mismatch" | "missing"
    detail: str = ""
    sha256: str = ""
    fetched: str = ""
    vendored: bool = False
    # False for a repo-local citation (finding 25 Part 2); the templates use
    # this to decide whether the primary link goes upstream or to the
    # published copy under assets/ -- a repo path is not a site URL.
    remote: bool = True
    # Path to the published copy, relative to `assets/` (e.g.
    # "datasheets/<sha256>.pdf") -- set when the citation is vendored AND
    # Project.publish_datasheets is on, and always for a local citation
    # (content-addressed under "citations/"); empty otherwise, which is also
    # how the rendered citation link knows to point upstream instead of to a
    # local copy.
    local_path: str = ""
    # The page `spec.section` resolved to in the lockfile (finding 23 Part 2),
    # as a string ready for the `#page=N` fragment; "" when the citation has no
    # `section:`, or when it has one with no resolved page (never fetched, or
    # resolution failed) -- which `verify()` reports, never silently.
    section_page: str = ""


@dataclass
class PartUsage:
    """Everything that names one exact part-number string -- indexed by the
    literal string, no normalization (docs/design/standard-library.md §10).
    `components` is every local item with a field literally named
    `part_number` (regardless of declared type or item type) holding this
    string; `citers` is every `(item, CitationStatus)` whose citation's own
    nested `part_number` matches. A part cited but never made into a
    component item has `components == []`; one made into a component but
    never cited has `citers == []`.
    """

    part_number: str
    components: list["Item"] = field(default_factory=list)
    citers: list[tuple["Item", CitationStatus]] = field(default_factory=list)

    @property
    def boards(self) -> list[str]:
        return sorted(
            {i.board for i in self.components if i.board}
            | {i.board for i, _status in self.citers if i.board}
        )

    @property
    def workspaces(self) -> list[str]:
        return sorted(
            {i.workspace for i in self.components if i.workspace}
            | {i.workspace for i, _status in self.citers if i.workspace}
        )


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
    # Which spelling declared it: "|" for `P_diss = ... | W`, ":" for the
    # retired `P_diss : W = ...`. Renderers echo the author's own marker.
    unit_style: str = ":"
    # Absolute 1-indexed source line this assignment was written on, or None
    # when the owning item's body has no known position (see Item.body_line).
    # What lets an editor match a calc result to *its* line rather than the
    # first line that happens to share its name.
    line: int | None = None


@dataclass
class Item:
    id: str
    type: str
    # Opaque, immutable surrogate identity (docs/design/keys.md) -- "" until
    # `keys.mint_missing()` assigns one. Reserved like `id`/`former_ids`, never
    # a schema field a type can declare: identity must not be shadowable.
    key: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    # Raw target text exactly as authored/stored -- a bare display id, or,
    # once links.expand_missing() has run, a `DISPLAY-ID@key` composite
    # (docs/design/keys.md §3). This is what build.compute_hashes() and any
    # write-back reads; nothing that merely *traverses* the graph should
    # read it directly (see resolved_links below).
    links: dict[str, list[str]] = field(default_factory=dict)
    # Every link target's resolved reference: its display id when it has one,
    # otherwise its surrogate key. build.resolve_links() populates this once
    # per build from links above (build.resolve_link_target handles composites).
    # The reference is collision-free: display ids contain "-<digits>" and
    # keys never contain "-", so item_by_ref() can resolve either spelling.
    # Every graph consumer (blocked.py, blocks.py's cascade walker, coverage,
    # workspaces.py's cross-workspace lint, stub_tests.py, and render.py)
    # reads this, not raw links -- raw links can carry DISPLAY@key text.
    # Targets that fail to resolve or have a disallowed type are absent here,
    # exactly as resolve_links() already reports them.
    resolved_links: dict[str, list[str]] = field(default_factory=dict)
    # Inverse edges using the same resolved-reference representation as
    # resolved_links. This keeps an id-less entry reachable in both directions.
    backlinks: dict[str, list[str]] = field(default_factory=dict)
    source_file: str = ""
    source_line: int = 1
    # Absolute 1-indexed line of body's own first line in source_file -- distinct
    # from source_line (the front-matter's), since calc diagnostics and the
    # editor extension need to point *inside* the body. None when body did not
    # come from a markdown file's own text (a list file's `body:` key has no
    # cheap per-line position without deeper YAML-loader surgery), in which case
    # calc line numbers fall back to source_line rather than guessing.
    body_line: int | None = None
    # Populated during build:
    calcs: list[CalcLine] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    body_html: str = ""
    history: dict[str, Any] = field(default_factory=dict)  # item-level on_change overrides
    calc_values: dict[str, str] = field(default_factory=dict)  # name -> formatted result
    prefix_hint: str = ""  # 'prefix:' override -- own key or file/block defaults:, used by the ID allocator
    # A bare-numeric `id:` value (finding 8 Part 1), e.g. "042" from a
    # *quoted* `id: "042"` -- unquoted is never trusted here (an unquoted
    # leading zero is octal in YAML: `id: 042` parses to 34, not 42; see
    # id_rejected below). `item.id` stays "" until `refdes id` expands this
    # into the full `<prefix>-<digits>` form and writes it back, in place.
    numeric_id_hint: str = ""
    # `id:` was an unquoted number (int/float) YAML may have already silently
    # mangled -- item.id is "" like a genuinely blank id, but this item must
    # never enter project.pending: it isn't safe for `refdes id` to allocate
    # into or expand, only for a human to fix by hand. The error is already
    # reported at parse time; this just keeps the allocator away from it.
    id_rejected: bool = False
    content_hash: str = ""  # over `invalidate` fields only; drives suspect links
    external: bool = False  # imported from another project: read-only here
    origin: str = ""        # name of the import it came from
    board_hint: str = ""    # explicit `board:` override, item value beats file defaults
    board: str = ""         # resolved board key; "" if boards: is unused or no match
    workspace_hint: str = ""  # explicit `workspace:` override, same precedence as board_hint
    workspace: str = ""       # resolved workspace key; "" if workspaces: is unused or no match
    citations: list[CitationStatus] = field(default_factory=list)  # populated during build
    # IDs this item replaces after a renumbering (finding 12) -- reserved like
    # `id:`/`board:`, not a schema field, so it works on any type. [[old_id]]
    # and a bare old_id in prose resolve to this item with a visible "formerly"
    # marker; see ids.collect_former_ids for collision handling and burning.
    former_ids: list[str] = field(default_factory=list)
    # Finding 6: field names whose value came from the file's defaults:
    # block rather than this item's own keys, and the source line of that
    # defaults: block -- so a validation failure on one of them can say so
    # and point there, instead of reporting it identically to a value the
    # item actually wrote itself. Empty/None when the item overrode every
    # inherited key, or the file has no defaults: at all.
    inherited_fields: frozenset[str] = field(default_factory=frozenset)
    defaults_line: int | None = None

    @property
    def title(self) -> str:
        # `summary` is what a log entry calls its one-line description, and `name`
        # what a component calls it. `text` stays in the chain for a hand-rolled
        # project schema still free to declare a field by that name (hardware@3
        # dropped it from requirement/bound, folding its role into body: below,
        # but this fallback chain is engine-level, not standard-specific).
        for key in ("title", "text", "summary", "name"):
            value = self.fields.get(key)
            if value:
                text = str(value).strip()
                return text if len(text) <= 90 else text[:87].rstrip() + "…"
        # A requirement/bound with no title: falls back here -- body is the
        # sentence itself once text: no longer exists to hold it (hardware@3).
        # `title`, when present, still wins above: a caption is meant to be
        # the short label, not competing with the full sentence for the slot.
        if self.body:
            text = self.body.strip()
            if text:
                return text if len(text) <= 90 else text[:87].rstrip() + "…"
        return self.id

    @property
    def slug(self) -> str:
        # docs/design/threads.md §2: an item that will never get a display id
        # (a chain entry declaring `follows:` but no `id:`) still needs a page
        # filename -- its surrogate key, the one durable name it does have.
        return self.id.lower() if self.id else self.key

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


def provisional_handle(item: Item) -> str:
    """A never-written, in-memory-only dict key for an item with no
    surrogate key yet (docs/design/threads.md §2) -- a keyless import from a
    pre-key artifact, a local item parsed before `keys.mint_missing()` runs
    (in particular anything under `--no-write`), or a permanently id-less
    chain entry before its first writable build.

    Prefixed with `~`, which is outside the key alphabet (`keys.ALPHABET`),
    so this can never collide with, or be mistaken for, a real minted key --
    Layer 1-3 key lint, `refdes keys adopt`, seals, baselines, and the board
    manifest all key off `item.key` (empty here), never off this handle, so
    none of them ever see it. Stable only for the lifetime of one parse: an
    item keeps this handle only until the next reparse after minting gives
    it a real key, and it is never persisted anywhere.
    """
    if item.origin:
        return f"~{item.origin}:{item.id}"
    return f"~{item.source_file}:{item.source_line}"


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
    date_format: str
    unit_aliases: dict[str, str] = field(default_factory=dict)
    # `equations:` from refdes-project.yaml, keyed by name. Evaluation reads calc.EQUATIONS
    # (the live registry load_project installs); this is the loaded definition, for
    # anything that reports on the project's vocabulary.
    equations: dict[str, Equation] = field(default_factory=dict)
    # Keyed by surrogate key (docs/design/threads.md §2) -- or, for an item
    # that has neither a key nor a display id yet (a keyless import, a
    # keyless local item under `--no-write`, or a permanently id-less chain
    # entry, §2's "pending vs. permanently id-less" rule), a provisional
    # in-memory handle from `provisional_handle()` below. That handle is
    # never written anywhere, never a valid key spelling, and never accepted
    # as a link target -- every consumer that treats a string as *the* key
    # reads `item.key` (empty for a provisional entry), never a dict key here.
    items: dict[str, Item] = field(default_factory=dict)
    # Display id -> the same dict key `items` uses for that item (surrogate
    # key or provisional handle). The reverse index a "look up by display id"
    # site uses (item_by_id() below); items itself is no longer keyed by
    # display id, so a lookup that means "the item people call REQ-001" must
    # go through this, not `items[...]` directly.
    items_by_id: dict[str, str] = field(default_factory=dict)
    pages: list[Page] = field(default_factory=list)
    pages_dir: str = "pages"
    nav_order: list[str] = field(default_factory=list)
    pending: list[Item] = field(default_factory=list)  # parsed but not yet allocated an id
    diagnostics: list[Diagnostic] = field(default_factory=list)
    root: str = "."
    version: str = ""
    imports: list[ImportSpec] = field(default_factory=list)
    # `imports.load_imports()` absorbs the pinned artifact once per parsed
    # project. The CLI needs imported keyed targets before source write-back
    # expands a bare link; build() shares that same loaded graph afterward.
    imports_loaded: bool = False
    coverage: dict[str, Coverage] = field(default_factory=dict)
    # Per-(item, board) coverage for the members of the groups named in a
    # board's `conforms_to:` -- {(item_id, board_name): Coverage}. Stays empty
    # for a project with no `conforms_to:` anywhere, which is what keeps such a
    # project's coverage output exactly as it was (finding 24).
    board_coverage: dict[tuple[str, str], Coverage] = field(default_factory=dict)
    blocked_chains: list[BlockedChain] = field(default_factory=list)
    # {name: preset_name} for every type/link_type any bundled preset at this
    # project's base@version declares, regardless of which presets are
    # currently selected -- lets an unknown-type/unknown-link diagnostic name
    # the specific preset a since-removed name used to come from
    # (docs/design/standard-library.md §8). Empty when standard: none.
    preset_provided_types: dict[str, str] = field(default_factory=dict)
    preset_provided_links: dict[str, str] = field(default_factory=dict)
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
    # Citation id -> (owning item id, source file, source line) -- the same
    # flat, project-wide namespace `figures` above already uses, minted from a
    # citation entry's own optional `id:` (finding 19 Part B). Populated by
    # build.validate_items as each entry is seen; a second use of the same id
    # is a build error naming both locations. Unlike a figure, a citation
    # always belongs to exactly one item and is never deferred to render time:
    # every citation is known from parsed data alone, before any body renders.
    citation_ids: dict[str, tuple[str, str, int | None]] = field(default_factory=dict)
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
    # Finding 11: opt-in, following lint_tokens()'s own precedent -- an
    # "untagged item" lint fires on nothing (tags: is almost always set once
    # in a file's defaults: and inherited by everything in it), so the
    # signal that actually means something is an item with no tags: *of its
    # own*, which plenty of projects will reasonably not want the noise
    # from. Default false: tags: is optional by design
    # (field_sets.provenance, no required:), so this can't be an
    # unconditional check.
    lint_own_tags: bool = False
    release_gate: dict[str, dict[str, bool]] = field(default_factory=_default_release_gate)
    # Diagnostic level for an authored link crossing from one workspace into a
    # non-shared one (workspaces.py's cross-workspace lint). Configurable
    # because how strictly a project wants this enforced varies; defaults to
    # warning, not error, so adopting workspaces never breaks an existing build.
    cross_workspace_severity: str = WARNING
    # Old id -> current item id, one entry per declared `former_ids:` across
    # every local item. Populated by ids.collect_former_ids() (build.py calls
    # it early, before rendering); consulted by _linkify so [[old_id]] and a
    # bare old_id keep resolving after a renumbering, and by `refdes audit`.
    former_ids: dict[str, str] = field(default_factory=dict)
    # standard: {base, version} exactly as this load resolved it -- "" / None
    # when standard: none or absent. Distinct from `version` above (that's
    # site.version, this project's own document version) and from
    # lifecycle.Baseline.refdes_version (the tool's own version). Recorded so
    # a stamped baseline can carry its own standard.version forward (revise.py),
    # which nothing before this needed: no other reader of Project cared which
    # pinned version produced the types/link_types it already has in hand.
    standard_base: str = ""
    standard_version: int | None = None

    @property
    def local_items(self) -> list[Item]:
        """Items authored here -- imports are read-only and not our problem."""
        return [i for i in self.items.values() if not i.external]

    def item_by_id(self, display_id: str) -> Item | None:
        """Look up an item by its *display* id -- never a surrogate key.

        `items` is keyed by surrogate key (or a provisional handle), so a
        site that means "the item people call REQ-001" resolves through
        `items_by_id` first. Returns None for an unknown, blank, or
        never-assigned display id, exactly as a plain dict `.get()` would.
        """
        key = self.items_by_id.get(display_id)
        return self.items.get(key) if key is not None else None

    def item_by_ref(self, ref: str) -> Item | None:
        """Look up a derived-link reference: display id first, then key.

        `resolved_links` and `backlinks` use this form so id-less entries
        remain graph nodes rather than collapsing to ``""``. The two forms
        cannot collide: display ids contain "-<digits>" and surrogate keys
        never contain "-".
        """
        if not ref:
            return None
        return self.item_by_id(ref) or self.items.get(ref)

    def add_item(self, item: Item, handle: str) -> str:
        """Add `item` to `items` under `handle`, without ever silently
        dropping another item that happens to compute the same handle.

        A hand-duplicated `key:` line (the exact corruption keys.validate()'s
        Layer 2 exists to catch) would otherwise collide two items on the
        same real key, and a plain dict assignment would silently keep only
        the second -- the first vanishes from `items.values()` before
        keys.validate() ever gets a chance to compare them and report it. On
        a genuine collision the second item is stored under a disambiguated
        handle instead (never a valid key spelling, never written anywhere),
        so both stay reachable and the Layer 2 diagnostic still fires.
        Returns the handle actually used.
        """
        if handle in self.items and self.items[handle] is not item:
            handle = f"{handle}!dup:{item.source_file}:{item.source_line}"
        self.items[handle] = item
        return handle

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
