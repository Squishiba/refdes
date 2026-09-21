"""The project's vocabulary, as one generated reference page (finding 38).

One entry per term the *resolved* schema knows about -- item types, link
verbs, sets, engine-reserved keys -- each with its definition (the
`doc:` key from chunks 1-2), its scope, where it points and what points at
it, its fields, and a worked example of how it is written: the bundled
standard's terms carry hand-written ones in `EXAMPLES` (values from
`base.yaml` and the repo's own `items/` tree), and any other term gets a
minimal one generated from its own resolved facts. Nothing here is hand-maintained: the page is derived
from the same resolved namespaces the engine runs on, so a term that exists
in the schema appears on the page, and a preset the build did not enable
does not.

Two renderers over one structure: `render_html` for the built site's
`vocabulary.html` (via `vocabulary.html.j2`, exactly the way `tree.py`
feeds `tree.html.j2`) and `render_markdown` for the docs site's
`docs/vocabulary.md` (via `docs-site/gen_examples.py`). Both are static
markup: no script, no handler attribute, printable.

Engine-reserved keys (`id`, `type`, `history`, ...) have no `doc:` slot in
any YAML -- they are not author-declared -- so their definitions live here,
in `RESERVED_KEYS`, the one place they can be written once and cited.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from html import escape
from typing import TYPE_CHECKING

from . import diagram
from .parse import OVERRIDABLE, RESERVED

if TYPE_CHECKING:
    from .model import Project

# The page's groups, in the order a reader meets them: what things are, how
# they relate, what groups of fields travel together, and what the engine
# itself owns.
GROUPS: tuple[tuple[str, str], ...] = (
    ("types", "Item types"),
    ("links", "Link verbs"),
    ("sets", "Sets"),
    ("keys", "Engine-reserved keys"),
)

# What an undeclared definition looks like. Project terms are not required to
# define themselves, so "no definition" is the honest rendering -- the term
# still exists and still has to be explained somewhere.
NO_DEFINITION = "No definition."

# A link declaration with an empty target list (`blocked_by: []`) means the
# verb may point at anything. An empty list on the page reads like a bug.
ANY_TARGET = "any type"

# Engine-reserved keys: the ones `parse.py` refuses to let a type shadow
# (RESERVED) and the ones a type may take over (OVERRIDABLE), plus the two
# keys a YAML list file uses. Order is the page's order.
RESERVED_KEYS: dict[str, str] = {
    "id": (
        "The item's display identifier, minted from its type prefix and the "
        "project's id width. Stable in people's sentences, not in the engine: "
        "a rename moves it, and `former_ids:` records where it went."
    ),
    "type": (
        "The item's item type -- the entry in `types:` that gives it a prefix, "
        "fields, and links."
    ),
    "key": (
        "The item's surrogate key: opaque, immutable, and the identity the "
        "engine actually uses. Nothing rewrites it, and links resolve through "
        "it rather than through a display id."
    ),
    "former_ids": (
        "Display ids this item used to have. Written by the engine when an id "
        "is re-minted, so old citations still resolve."
    ),
    "body": (
        "The item's prose, below the front matter. Its change policy comes "
        "from the type's `body:` setting; for types whose content is the "
        "statement itself it is the required field."
    ),
    "history": (
        "This item's change-policy override, in place of the project's "
        "`history: default`."
    ),
    "prefix": (
        "On a type: the id prefix its items carry. As an item key it is the "
        "engine's own, and a type that declares a field of this name takes it over."
    ),
    "board": (
        "Which board an item belongs to -- the first path segment under "
        "`items/` unless the item says otherwise. Overridable by a type's own field."
    ),
    "workspace": (
        "Which workspace an item belongs to, when the project registers them. "
        "Overridable by a type's own field."
    ),
    "defaults": (
        "In a YAML list file: the type and field values every entry in that "
        "file inherits, before its own keys."
    ),
    "section": (
        "In a YAML list file: the section heading its entries file under on "
        "the item's page; in a Markdown marker block, the section a generated "
        "block belongs to."
    ),
}

# Which of the two reserved families a key belongs to, for the scope line.
_RESERVED_KIND = {**{k: "reserved" for k in RESERVED}, **{k: "overridable" for k in OVERRIDABLE}}


@dataclass
class FieldEntry:
    """One field, as the page shows it: name, definition, shape."""

    name: str
    doc: str = ""
    type: str = "text"
    required: bool = False


@dataclass
class TermEntry:
    """One vocabulary term, ready to render."""

    name: str
    kind: str  # a key of GROUPS
    doc: str = ""
    label: str = ""
    anchor: str = ""
    # Link verbs only.
    inverse: str = ""
    targets: list[str] = field(default_factory=list)
    targets_unrestricted: bool = False
    declared_on: list[str] = field(default_factory=list)
    # Item types only: (verb, source types) for every verb that may point here.
    pointed_at_by: list[tuple[str, list[str]]] = field(default_factory=list)
    # Item types and sets.
    fields: list[FieldEntry] = field(default_factory=list)
    # Sets only: the types that pull the set in with `include:`.
    included_by: list[str] = field(default_factory=list)
    # Item types only.
    prefix: str = ""
    # Engine-reserved keys only: "reserved" or "overridable".
    key_kind: str = ""
    # Every entry: a worked example of how the term is actually written --
    # YAML as it would appear in an items file (or, for a field set, in a
    # schema file), comments included.
    example: str = ""

    @property
    def defined(self) -> bool:
        return bool(self.doc.strip())


@dataclass
class Vocabulary:
    """The whole vocabulary, grouped, anchors assigned."""

    entries: dict[str, list[TermEntry]] = field(default_factory=dict)

    def terms(self):
        for kind, _title in GROUPS:
            yield from self.entries.get(kind, ())


# ------------------------------------------------------------------- building


def entries(project: Project) -> Vocabulary:
    """Every resolved term in `project`, grouped and anchored."""
    inbound: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    verbs = _verb_facts(project)

    types: list[TermEntry] = []
    for name in sorted(project.types):
        spec = project.types[name]
        for verb, sources in verbs["inbound"][name].items():
            inbound[name][verb] |= sources
        types.append(
            TermEntry(
                name=name,
                kind="types",
                doc=spec.doc,
                label=spec.label or "",
                prefix=spec.prefix,
                fields=[_field_entry(f, s) for f, s in spec.fields.items()],
                pointed_at_by=[
                    (verb, sorted(srcs)) for verb, srcs in sorted(inbound[name].items())
                ],
            )
        )

    links: list[TermEntry] = []
    for name in sorted(project.link_types):
        lt = project.link_types[name]
        facts = verbs["verbs"][name]
        links.append(
            TermEntry(
                name=name,
                kind="links",
                doc=lt.doc,
                label=lt.label or "",
                inverse=lt.inverse,
                targets=sorted(facts["targets"]),
                targets_unrestricted=facts["unrestricted"],
                declared_on=sorted(facts["declared_on"]),
            )
        )

    sets: list[TermEntry] = []
    for name in sorted(project.sets):
        raw = project.sets[name] or {}
        # A set is a type-spec fragment: its fields live under `fields:`
        # (docs/design/composition.md §1); links and body ride along with it
        # but the page lists fields, as before.
        raw_fields = raw.get("fields") or {}
        sets.append(
            TermEntry(
                name=name,
                kind="sets",
                fields=[
                    _field_entry(fname, spec if isinstance(spec, dict) else {})
                    for fname, spec in raw_fields.items()
                ],
                included_by=sorted(_includers(project, name, raw)),
            )
        )

    keys: list[TermEntry] = [
        TermEntry(
            name=name,
            kind="keys",
            doc=doc,
            key_kind=_RESERVED_KIND.get(name, "file"),
        )
        for name, doc in RESERVED_KEYS.items()
    ]

    vocab = Vocabulary(
        entries={"types": types, "links": links, "sets": sets, "keys": keys}
    )
    _assign_anchors(vocab)
    for entry in vocab.terms():
        entry.example = EXAMPLES.get((entry.kind, entry.name), "") or _fallback_example(entry)
    return vocab


def _field_entry(name: str, spec) -> FieldEntry:
    """A field from either source: a resolved `FieldSpec` or a raw field-set dict."""
    if isinstance(spec, dict):
        doc = spec.get("doc", "")
        ftype = spec.get("type", "text")
        required = spec.get("required", False)
    else:
        doc, ftype, required = spec.doc, spec.type, spec.required
    return FieldEntry(
        name=name, doc=doc or "", type=ftype or "text", required=bool(required)
    )


def _verb_facts(project: Project) -> dict:
    """Who declares each verb, what it may point at, and what points at a type.

    A type may declare a verb under its own name or under its inverse
    (`decision: {links: {recorded_by: [log]}}` is `log --records--> decision`),
    so both spellings resolve to the same edge before anything is reported.
    """
    inverse_to_verb = {lt.inverse: name for name, lt in project.link_types.items()}
    verbs: dict[str, dict] = {
        name: {"targets": set(), "unrestricted": False, "declared_on": set()}
        for name in project.link_types
    }
    inbound: dict[str, dict[str, set[str]]] = defaultdict(dict)

    for type_name, spec in project.types.items():
        for key, targets in (spec.links or {}).items():
            listed = list(targets or [])
            if key in project.link_types:
                verb = key
                verbs[verb]["declared_on"].add(type_name)
                if listed:
                    verbs[verb]["targets"].update(listed)
                    for target in listed:
                        inbound[target].setdefault(verb, set()).add(type_name)
                else:
                    verbs[verb]["unrestricted"] = True
                    inbound[ANY_TARGET].setdefault(verb, set()).add(type_name)
            elif key in inverse_to_verb:
                # The declaring type is the target; the list names the sources.
                verb = inverse_to_verb[key]
                verbs[verb]["declared_on"].add(type_name)
                verbs[verb]["targets"].add(type_name)
                inbound[type_name].setdefault(verb, set()).update(listed or {ANY_TARGET})

    return {"verbs": verbs, "inbound": inbound}


def _includers(project: Project, name: str, raw: dict) -> set[str]:
    """Types that pull this set in.

    `include:` is expanded and popped during resolution, so membership is
    re-derived the way finding 38 §5 suggests -- widened to links and body
    alongside the widening of sets themselves (docs/design/composition.md
    §5): a type matches when it still carries the set's whole contribution,
    every field under the same *semantic* spec (`doc:` may differ, which is
    exactly what a doc-only patch produces), every link verb with identical
    targets, and the same body. Matching field names alone would report
    every type with a `title` as an includer of `named_title`, required or
    not. The inference still cannot tell an include from an identical
    inherited or hand-written declaration, and a type that fully shadows a
    set's field with a different definition drops out: the page reports who
    carries the contribution, which is the honest approximation of who
    included it.
    """
    fields = raw.get("fields") or {}
    links = raw.get("links") or {}
    body = raw.get("body")
    if not (fields or links or body):
        return set()
    includers = set()
    for type_name, spec in project.types.items():
        if not all(
            _carries_field_spec(spec.fields.get(fname), fspec)
            for fname, fspec in fields.items()
        ):
            continue
        type_links = spec.links or {}
        if not all(
            verb in type_links
            and list(type_links[verb] or []) == list(targets or [])
            for verb, targets in links.items()
        ):
            continue
        if body is not None and (
            spec.body_on_change != (body or {}).get("on_change", "invalidate")
            or bool(spec.body_required) != bool((body or {}).get("required", False))
        ):
            continue
        includers.add(type_name)
    return includers


def _carries_field_spec(resolved, declared) -> bool:
    """Whether a resolved FieldSpec still carries a set's field definition:
    every key that affects validation, hashing or invalidation agrees; only
    `doc:` may differ."""
    if resolved is None:
        return False
    declared = declared or {}
    return (
        resolved.type == declared.get("type", "text")
        and resolved.on_change == declared.get("on_change", "invalidate")
        and bool(resolved.required) == bool(declared.get("required", False))
        and resolved.required_when == declared.get("required_when")
        and resolved.choices == declared.get("choices")
        and resolved.default == declared.get("default")
    )


def _assign_anchors(vocab: Vocabulary) -> None:
    """`term-<name>`, disambiguated across groups on a collision."""
    seen: set[str] = set()
    for entry in vocab.terms():
        anchor = f"term-{entry.name}"
        if anchor in seen:
            anchor = f"term-{entry.name}-{entry.kind}"
        seen.add(anchor)
        entry.anchor = anchor


# ------------------------------------------------------------------ examples

# Worked examples for the bundled standard's terms, keyed by (group, name).
# Every field name, type name, id, and value here is taken from
# `standards/hardware/v3/base.yaml` and this repo's own `items/` tree --
# nothing invented. A term the table does not cover -- a project overlay
# type, a preset's verb -- gets `_fallback_example`, generated from the
# entry's own resolved facts, so every entry on the page carries an
# example whatever schema produced it. The hand-written examples describe
# hardware@3 as shipped: a project whose overlay redefines a standard term
# still gets the standard's example, which is illustrative for that
# project, not authoritative.
EXAMPLES: dict[tuple[str, str], str] = {
    # ------------------------------------------------------------- item types
    ("types", "requirement"): (
        "# items/requirements/power.yaml -- shared fields go in defaults:,\n"
        "# and the statement itself is the body.\n"
        "defaults:\n"
        "  type: requirement\n"
        "  prefix: REQ-PWR\n"
        "  status: active\n"
        "items:\n"
        "  - id: REQ-PWR-001\n"
        "    body: The unit shall operate from an input supply of 9 V to 36 V.\n"
        "    source: Customer spec rev D, §3.1"
    ),
    ("types", "bound"): (
        "defaults:\n"
        "  type: bound\n"
        "  prefix: BND-THM\n"
        "  status: active\n"
        "items:\n"
        "  - id: BND-THM-001\n"
        "    body: Board power density\n"
        "    limit: \"<= 0.15 W/in^2\"  # required -- what makes it checkable\n"
        "    rationale: Natural convection only; the enclosure is sealed."
    ),
    ("types", "decision"): (
        "# A decision as a Markdown item: front matter, then the prose body.\n"
        "---\n"
        "id: DEC-PWR-001\n"
        "type: decision\n"
        "title: 3V3 rail regulator topology\n"
        "status: accepted  # an accepted decision closes coverage on what it satisfies\n"
        "date: 2026-03-14\n"
        "satisfies: [REQ-PWR-002, REQ-PWR-003]\n"
        "constrained_by: [BND-THM-001]\n"
        "selects: [CMP-PWR-001]\n"
        "---\n"
        "\n"
        "The 3V3 rail draws up to 1.2 A from a 9–36 V input, in a sealed enclosure."
    ),
    ("types", "test"): (
        "defaults:\n"
        "  type: test\n"
        "  prefix: TST-PWR\n"
        "items:\n"
        "  - id: TST-PWR-001\n"
        "    title: Input range sweep\n"
        "    status: passing  # only a passing test counts toward coverage\n"
        "    body: Sweep the bench supply 9 V to 36 V in 1 V steps at full load.\n"
        "    verifies: [REQ-PWR-001]"
    ),
    ("types", "component"): (
        "defaults:\n"
        "  type: component\n"
        "  prefix: CMP-PWR\n"
        "items:\n"
        "  - id: CMP-PWR-001\n"
        "    title: TPS62913 synchronous buck converter\n"
        "    part_number: TPS62913\n"
        "    status: selected"
    ),
    ("types", "group"): (
        "defaults:\n"
        "  type: group\n"
        "  prefix: GRP-IO\n"
        "items:\n"
        "  - id: GRP-IO-001\n"
        "    title: The digital IO interface spec\n"
        "# A group never lists members: each member declares part_of: [GRP-IO-001]."
    ),
    ("types", "log"): (
        "defaults:\n"
        "  type: log\n"
        "  prefix: LOG-A\n"
        "items:\n"
        "  - id: LOG-A-001\n"
        "    date: 2026-02-18\n"
        "    summary: Took delivery of the customer spec rev D.\n"
        "    addresses: [REQ-PWR-001, REQ-PWR-002]"
    ),
    # ------------------------------------------------------------- link verbs
    ("links", "refines"): (
        "# REQ-PWR-003 is a narrower statement of the same kind as REQ-PWR-002.\n"
        "- id: REQ-PWR-003\n"
        "  body: Converter efficiency shall exceed 90 % at half load.\n"
        "  refines: [REQ-PWR-002]\n"
        "# REQ-PWR-002 shows refined_by: [REQ-PWR-003] without saying so itself."
    ),
    ("links", "derives_from"): (
        "- id: BND-THM-002\n"
        "  body: Minimum converter efficiency\n"
        "  limit: \">= 0.90\"\n"
        "  derives_from: [BND-THM-001]  # the number follows from the density bound"
    ),
    ("links", "governed_by"): (
        "- id: REQ-DIO-003\n"
        "  body: The main IO board shall provide isolated discrete inputs.\n"
        "  governed_by: [REQ-DIO-001]  # must comply with its 26 V TVS rule\n"
        "# Not a narrower version of REQ-DIO-001 -- a different fact that has\n"
        "# to obey it. governs, the backlink, is computed."
    ),
    ("links", "satisfies"): (
        "# Declared from the decision (or component):\n"
        "- id: DEC-PWR-001\n"
        "  satisfies: [REQ-PWR-002, REQ-PWR-003]\n"
        "# The requirements gain satisfied_by: [DEC-PWR-001]; once the decision\n"
        "# is accepted, that closes their coverage."
    ),
    ("links", "constrained_by"): (
        "- id: DEC-PWR-001\n"
        "  constrained_by: [BND-THM-001]\n"
        "# Traceability only -- it does not close coverage on the bound; satisfies does."
    ),
    ("links", "verifies"): (
        "# Declared from the test:\n"
        "- id: TST-PWR-001\n"
        "  verifies: [REQ-PWR-001]\n"
        "# Or from the requirement, under the inverse name -- same edge either way:\n"
        "- id: REQ-PWR-001\n"
        "  verified_by: [TST-PWR-001]"
    ),
    ("links", "addresses"): (
        "- id: LOG-A-001\n"
        "  addresses: [REQ-PWR-001, REQ-PWR-002]\n"
        "# Addressed coverage: worked on and written up, without claiming it is met."
    ),
    ("links", "records"): (
        "# From the log entry:\n"
        "- id: LOG-A-004\n"
        "  records: [DEC-PWR-001]\n"
        "# Or from the decision, which declares the verb under its inverse name:\n"
        "- id: DEC-PWR-001\n"
        "  recorded_by: [LOG-A-004]"
    ),
    ("links", "amends"): (
        "- id: LOG-A-006\n"
        "  amends: [LOG-A-003]  # a correction is a new entry pointing back,\n"
        "                       # never an edit to the sealed original"
    ),
    ("links", "supersedes"): (
        "- id: DEC-PWR-002\n"
        "  supersedes: [DEC-PWR-001]\n"
        "# The link does not move DEC-PWR-001's status -- set status: superseded\n"
        "# there yourself, or the build warns that the two halves disagree."
    ),
    ("links", "selects"): (
        "- id: DEC-PWR-001\n"
        "  selects: [CMP-PWR-001]\n"
        "# The part's own status: selected is the other half of the same claim;\n"
        "# the build warns when one exists and the other does not."
    ),
    ("links", "blocked_by"): (
        "- id: DEC-IO-005\n"
        "  blocked_by: [DEC-IO-001]\n"
        "# May point at an item of any type; name only the immediate blocker --\n"
        "# reports resolve the chain to its root, and a cycle is a build error."
    ),
    ("links", "part_of"): (
        "# Membership is always declared by the member, never by the group:\n"
        "- id: REQ-DIO-003\n"
        "  part_of: [GRP-IO-001]\n"
        "# GRP-IO-001 shows contains: [REQ-DIO-003] as the computed backlink."
    ),
    ("links", "drop_in"): (
        "- id: CMP-PWR-001\n"
        "  drop_in: [CMP-PWR-002]  # self-inverse: CMP-PWR-002 gains the same edge,\n"
        "                          # and no rationale is required"
    ),
    ("links", "alternate"): (
        "- id: CMP-PWR-002\n"
        "  alternate: [CMP-PWR-001]\n"
        "  rationale: Higher ESR at the output cap; verify ripple before swapping.\n"
        "  # rationale is required whenever an alternate link is present"
    ),
    # -------------------------------------------------------------- sets
    ("sets", "provenance"): (
        "# A type pulls the set in, and its items then carry its fields:\n"
        "types:\n"
        "  requirement:\n"
        "    include: [provenance]\n"
        "# An item of that type:\n"
        "- id: REQ-PWR-001\n"
        "  source: Customer spec rev D, §3.1\n"
        "  tags: [power]"
    ),
    ("sets", "stewardship"): (
        "types:\n"
        "  requirement:\n"
        "    include: [stewardship]\n"
        "- id: REQ-PWR-001\n"
        "  owner: J. Bin\n"
        "  last_reviewed: 2026-03-02"
    ),
    ("sets", "citations"): (
        "types:\n"
        "  component:\n"
        "    include: [citations]\n"
        "- id: CMP-PWR-001\n"
        "  citations:\n"
        "    - path: https://www.ti.com/lit/ds/symlink/tps62913.pdf\n"
        "      rev: E\n"
        "      page: \"14\"\n"
        "      keep_copy: false"
    ),
    # -------------------------------------------------------------- sets
    ("sets", "statement_title"): (
        "types:\n"
        "  requirement:\n"
        "    include: [statement_title]\n"
        "    fields:\n"
        "      # a doc-only patch keeps the type's own wording for the field\n"
        "      title: { doc: \"An optional short label for tables and previews.\" }\n"
        "- id: REQ-PWR-001\n"
        "  title: 12 V rail tolerance\n"
        "  body: The 12 V rail must stay within 5% under load."
    ),
    ("sets", "named_title"): (
        "types:\n"
        "  decision:\n"
        "    include: [named_title]\n"
        "- id: DEC-PWR-001\n"
        "  title: Regulator choice\n"
        "  # title is required on decision, test and component"
    ),
    ("sets", "grouped"): (
        "types:\n"
        "  requirement:\n"
        "    include: [grouped]\n"
        "- id: REQ-IO-001\n"
        "  part_of: [GRP-IO-001]\n"
        "  # membership is declared by the member, never by the group"
    ),
    ("sets", "claims"): (
        "types:\n"
        "  decision:\n"
        "    include: [claims]\n"
        "- id: DEC-PWR-001\n"
        "  satisfies: [REQ-PWR-001]\n"
        "  constrained_by: [BND-PWR-001]"
    ),
    ("sets", "invalidate_body"): (
        "types:\n"
        "  decision:\n"
        "    include: [invalidate_body]\n"
        "# editing such a body marks downstream items suspect"
    ),
    # ---------------------------------------------------- engine-reserved keys
    ("keys", "id"): (
        "- id: REQ-PWR-001  # minted from the type prefix and the id width;\n"
        "                   # leave it out and `refdes id` writes one back"
    ),
    ("keys", "type"): (
        "# Usually stated once per file, under defaults:\n"
        "defaults:\n"
        "  type: requirement\n"
        "# An item may also state its own, or a Markdown item carries it in\n"
        "# the front matter:\n"
        "---\n"
        "id: DEC-PWR-001\n"
        "type: decision\n"
        "---"
    ),
    ("keys", "key"): (
        "- key: 1zn5skrv6k3  # written back by the tool on the first writable\n"
        "  id: REQ-PWR-001   # load; never hand-edit it, and links resolve through it"
    ),
    ("keys", "former_ids"): (
        "- id: BND-THM-001\n"
        "  former_ids: [CON-THM-001]  # written when an id is re-minted, so old\n"
        "                             # CON-THM-001 citations keep resolving"
    ),
    ("keys", "body"): (
        "- id: REQ-PWR-001\n"
        "  body: The unit shall operate from an input supply of 9 V to 36 V.\n"
        "# In a Markdown item, body is the prose below the front matter instead."
    ),
    ("keys", "history"): (
        "- id: REQ-PWR-004\n"
        "  history:\n"
        "    fields:\n"
        "      owner: ignore\n"
        "    reason: Owner rotates weekly during bring-up; not a meaningful change."
    ),
    ("keys", "prefix"): (
        "defaults:\n"
        "  type: requirement\n"
        "  prefix: REQ-PWR  # items in this file mint ids like REQ-PWR-001;\n"
        "                   # a type declaring a field of this name takes it over"
    ),
    ("keys", "board"): (
        "# The first path segment under items/ is the board; state it only\n"
        "# when the folder is not a registered board:\n"
        "defaults:\n"
        "  board: board-a  # folder predates the boards: registry"
    ),
    ("keys", "workspace"): (
        "# Only when the project registers workspaces: in its settings file:\n"
        "items:\n"
        "  - id: IFC-CAN-001\n"
        "    workspace: platform  # lives in a folder that predates the registry"
    ),
    ("keys", "defaults"): (
        "defaults:\n"
        "  type: requirement\n"
        "  status: active\n"
        "items:\n"
        "  - id: REQ-PWR-001  # inherits type and status, then its own keys apply\n"
        "    body: The unit shall operate from an input supply of 9 V to 36 V."
    ),
    ("keys", "section"): (
        "items:\n"
        "  - section: requirement  # every item after it is a requirement,\n"
        "  - id: REQ-IO-AI-001     # until the next section marker\n"
        "    body: The AI accelerator rail shall regulate to 0.85 V ±3%."
    ),
}


def _fallback_example(e: TermEntry) -> str:
    """A generic example for a term the hand-written table does not cover.

    Built only from the entry's own resolved facts -- its prefix, required
    fields, declaring types, targets -- so an overlay type or preset verb
    gets an example that is true of this project's schema even though no
    human wrote it. Values are placeholders (`...`), never invented content.
    """
    if e.kind == "types":
        lines = [
            "defaults:",
            f"  type: {e.name}",
            "items:",
            f"  - id: {e.prefix or 'X'}-001",
        ]
        lines.extend(f"    {f.name}: ..." for f in e.fields if f.required)
        return "\n".join(lines)
    if e.kind == "links":
        source = e.declared_on[0] if e.declared_on else "<declaring type>"
        lines = [f"# On a {source} item:"]
        if e.targets_unrestricted or not e.targets:
            lines.append(f"{e.name}: [<any item id>]  # may point at any type")
        else:
            lines.append(f"{e.name}: [{e.targets[0]}-001]")
            if e.inverse and e.inverse != e.name:
                lines.append(f"# The target shows {e.inverse}: [...] without saying so itself.")
            elif e.inverse == e.name:
                lines.append("# Self-inverse: the target gains the same edge.")
        return "\n".join(lines)
    if e.kind == "sets":
        owner = e.included_by[0] if e.included_by else "<type>"
        return "\n".join(["types:", f"  {owner}:", f"    include: [{e.name}]"])
    return f"{e.name}: ..."


# ------------------------------------------------------------------ rendering


def render_html(project: Project) -> str:
    """The page's body markup, for `vocabulary.html.j2` to embed."""
    vocab = entries(project)
    out: list[str] = []
    # The coverage spine above the index: it is the one picture of the
    # whole schema worth drawing, and a reader deciding where to start
    # wants it before the A-to-Z. A schema with no coverage verbs gets no
    # frame around nothing.
    spine = diagram.render_spine_svg(project)
    if spine:
        out.append(f'<div class="vocab-spine">{spine}</div>')
    out.append(_index_html(vocab))
    for kind, title in GROUPS:
        group = vocab.entries.get(kind, [])
        if not group:
            continue
        out.append(f'<section class="vocab-group" id="group-{kind}"><h2>{escape(title)}</h2>')
        out.extend(_term_html(e, project) for e in group)
        out.append("</section>")
    return "\n".join(out)


def _index_html(vocab: Vocabulary) -> str:
    parts = ['<nav class="vocab-index">']
    for kind, title in GROUPS:
        group = vocab.entries.get(kind, [])
        if not group:
            continue
        parts.append(f'<h2><a href="#group-{kind}">{escape(title)}</a></h2><ul class="tight">')
        parts.extend(
            f'<li><a href="#{escape(e.anchor)}"><code>{escape(e.name)}</code></a></li>'
            for e in group
        )
        parts.append("</ul>")
    parts.append("</nav>")
    return "".join(parts)


def _term_html(e: TermEntry, project: Project) -> str:
    parts = [f'<div class="vocab-term" id="{escape(e.anchor)}">']
    heading = f"<code>{escape(e.name)}</code>"
    if e.label and e.label != e.name:
        heading += f' <span class="vocab-label">{escape(e.label)}</span>'
    parts.append(f"<h3>{heading}</h3>")
    if e.kind == "types":
        # The term's own connections, drawn beside the term: one small
        # diagram per type, not one whole-schema hairball.
        parts.append(
            f'<div class="vocab-term-diagram">{diagram.render_term_svg(project, e.name)}</div>'
        )
    parts.append(
        f'<p class="vocab-doc">{escape(e.doc)}</p>'
        if e.defined
        else f'<p class="vocab-doc vocab-none">{NO_DEFINITION}</p>'
    )
    facts = _facts(e)
    if facts:
        parts.append('<dl class="vocab-facts">')
        parts.extend(f"<dt>{escape(k)}</dt><dd>{v}</dd>" for k, v in facts)
        parts.append("</dl>")
    if e.fields:
        parts.append(_fields_table(e))
    if e.example:
        parts.append(
            '<div class="vocab-example"><h4>Example</h4>'
            f"<pre><code>{escape(e.example.rstrip())}</code></pre></div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _facts(e: TermEntry) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    if e.kind == "types":
        if e.prefix:
            facts.append(("Id prefix", f"<code>{escape(e.prefix)}</code>"))
        if e.pointed_at_by:
            facts.append(
                (
                    "Pointed at by",
                    "; ".join(
                        f"<code>{escape(verb)}</code> from {_join(sources)}"
                        for verb, sources in e.pointed_at_by
                    ),
                )
            )
    elif e.kind == "links":
        facts.append(
            (
                "Points at",
                ANY_TARGET if e.targets_unrestricted else _join(e.targets, code=True),
            )
        )
        if e.inverse:
            facts.append(("Inverse", f"<code>{escape(e.inverse)}</code>"))
        if e.declared_on:
            facts.append(("Declared on", _join(e.declared_on, code=True)))
    elif e.kind == "sets" and e.included_by:
        facts.append(("Included by", _join(e.included_by, code=True)))
    elif e.kind == "keys":
        scope = {
            "reserved": "Every item; a type may not shadow it",
            "overridable": "Every item, unless its type declares a field of that name",
            "file": "A YAML list file, not an item",
        }[e.key_kind]
        facts.append(("Scope", escape(scope)))
    return facts


def _join(names, code: bool = False) -> str:
    if not names:
        return "nothing"
    return ", ".join(f"<code>{escape(n)}</code>" if code else escape(n) for n in names)


def _fields_table(e: TermEntry) -> str:
    rows = [
        "<tr><th>Field</th><th>Definition</th><th>Type</th><th>Required</th></tr>",
    ]
    for f in e.fields:
        doc = escape(f.doc) if f.doc.strip() else f'<span class="vocab-none">{NO_DEFINITION}</span>'
        rows.append(
            f"<tr><td><code>{escape(f.name)}</code></td><td>{doc}</td>"
            f"<td>{escape(f.type)}</td><td>{'yes' if f.required else 'no'}</td></tr>"
        )
    return f'<table class="vocab-fields">{"".join(rows)}</table>'


# ----------------------------------------------------------------- markdown


def render_markdown(project: Project) -> str:
    """The same vocabulary as a docs page: markdown, so the docs site's own
    renderer gives it the site's chrome and anchors."""
    vocab = entries(project)
    out: list[str] = []
    for kind, title in GROUPS:
        group = vocab.entries.get(kind, [])
        if not group:
            continue
        out.append(f"## {title}\n")
        for e in group:
            out.append(f"### `{e.name}`\n")
            out.append(f"{_md_doc(e)}\n")
            facts = _md_facts(e)
            if facts:
                out.extend(facts)
                out.append("")
            if e.fields:
                out.append("| Field | Definition | Type | Required |")
                out.append("|---|---|---|---|")
                for f in e.fields:
                    doc = _md(f.doc) if f.doc.strip() else NO_DEFINITION
                    out.append(
                        f"| `{f.name}` | {doc} | {f.type} | {'yes' if f.required else 'no'} |"
                    )
                out.append("")
            if e.example:
                out.append("**Example:**\n")
                out.append("```yaml")
                out.append(e.example.rstrip())
                out.append("```")
                out.append("")
    return "\n".join(out).rstrip() + "\n"


def _md(text: str) -> str:
    return text.replace("|", "\\|").strip()


def _md_doc(e: TermEntry) -> str:
    return _md(e.doc) if e.defined else f"_{NO_DEFINITION}_"


def _md_facts(e: TermEntry) -> list[str]:
    lines: list[str] = []
    if e.kind == "types":
        if e.prefix:
            lines.append(f"- **Id prefix:** `{e.prefix}`")
        if e.pointed_at_by:
            lines.append(
                "- **Pointed at by:** "
                + "; ".join(
                    f"`{verb}` from " + (", ".join(f"`{s}`" for s in sources) or "nothing")
                    for verb, sources in e.pointed_at_by
                )
            )
    elif e.kind == "links":
        targets = ", ".join(f"`{t}`" for t in e.targets) or "nothing"
        lines.append(
            "- **Points at:** "
            + (ANY_TARGET if e.targets_unrestricted else targets)
        )
        if e.inverse:
            lines.append(f"- **Inverse:** `{e.inverse}`")
        if e.declared_on:
            lines.append("- **Declared on:** " + ", ".join(f"`{d}`" for d in e.declared_on))
    elif e.kind == "sets" and e.included_by:
        lines.append("- **Included by:** " + ", ".join(f"`{d}`" for d in e.included_by))
    elif e.kind == "keys":
        scope = {
            "reserved": "every item; a type may not shadow it",
            "overridable": "every item, unless its type declares a field of that name",
            "file": "a YAML list file, not an item",
        }[e.key_kind]
        lines.append(f"- **Scope:** {scope}")
    return lines
