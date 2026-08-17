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


@dataclass
class LinkType:
    name: str
    inverse: str
    label: str


@dataclass
class BoardSpec:
    """One entry in the opt-in `boards:` registry.

    A board's items are matched by the first path segment under `items/`, unless
    `path` says that segment is spelled differently from the board's own key.
    """

    name: str
    label: str
    token: str = ""  # optional; checked for consistency against item id prefixes
    path: str = ""   # alias for the items/ path segment; defaults to `name`

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
    local_path: str = ""  # project-root-relative path to the vendored blob, if any


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
    seal_violations: list[str] = field(default_factory=list)
    boards: dict[str, BoardSpec] = field(default_factory=dict)
    # (item_id, previous_board, current_board), for items whose board changed
    # since the last time `.refdes/boards.yaml` was written.
    board_moves: list[tuple[str, str, str]] = field(default_factory=list)
    # Project-root-relative paths of every local file that must be copied into
    # `_site/assets/`, mirroring this same path -- populated by resolved local
    # `<img>` references and by `site.assets:` directories.
    assets: set[str] = field(default_factory=set)
    asset_dirs: list[str] = field(default_factory=list)  # site.assets: raw config

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
