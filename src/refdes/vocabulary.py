"""The project's vocabulary, as one generated reference page (finding 38).

One entry per term the *resolved* schema knows about -- item types, link
verbs, field sets, engine-reserved keys -- each with its definition (the
`doc:` key from chunks 1-2), its scope, where it points and what points at
it, and its fields. Nothing here is hand-maintained: the page is derived
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
    ("field_sets", "Field sets"),
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
    # Item types and field sets.
    fields: list[FieldEntry] = field(default_factory=list)
    # Field sets only: the types that pull the set in with `include:`.
    included_by: list[str] = field(default_factory=list)
    # Item types only.
    prefix: str = ""
    # Engine-reserved keys only: "reserved" or "overridable".
    key_kind: str = ""

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

    field_sets: list[TermEntry] = []
    for name in sorted(project.field_sets):
        raw = project.field_sets[name] or {}
        field_sets.append(
            TermEntry(
                name=name,
                kind="field_sets",
                fields=[
                    _field_entry(fname, spec if isinstance(spec, dict) else {})
                    for fname, spec in raw.items()
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
        entries={"types": types, "links": links, "field_sets": field_sets, "keys": keys}
    )
    _assign_anchors(vocab)
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
    """Types that pull this field set in.

    `include:` is expanded and popped during resolution, so membership is
    re-derived the way finding 38 §5 suggests: a type whose fields are a
    superset of the set's fields includes it. Exact for the ordinary case --
    a type that re-declares one of the set's fields with a different
    definition still shows as an includer, which is the honest answer.
    """
    names = set(raw)
    if not names:
        return set()
    return {
        type_name
        for type_name, spec in project.types.items()
        if names <= set(spec.fields)
    }


def _assign_anchors(vocab: Vocabulary) -> None:
    """`term-<name>`, disambiguated across groups on a collision."""
    seen: set[str] = set()
    for entry in vocab.terms():
        anchor = f"term-{entry.name}"
        if anchor in seen:
            anchor = f"term-{entry.name}-{entry.kind}"
        seen.add(anchor)
        entry.anchor = anchor


# ------------------------------------------------------------------ rendering


# The filename the docs site's generated page points at for the diagram:
# it cannot inline SVG (its markdown renders with html disabled), so the
# same bytes gen_examples writes there are what `render_markdown` names.
DIAGRAM_ASSET = "vocabulary-graph.svg"


def render_html(project: Project) -> str:
    """The page's body markup, for `vocabulary.html.j2` to embed."""
    vocab = entries(project)
    out: list[str] = [_graph_html(project), _index_html(vocab)]
    for kind, title in GROUPS:
        group = vocab.entries.get(kind, [])
        if not group:
            continue
        out.append(f'<section class="vocab-group" id="group-{kind}"><h2>{escape(title)}</h2>')
        out.extend(_term_html(e) for e in group)
        out.append("</section>")
    return "\n".join(out)


def _graph_html(project: Project) -> str:
    """The diagram, above the index: the shape of the vocabulary first, then
    its terms one at a time. Inline SVG from `diagram.py` -- no script, no
    embed, so it renders with JavaScript off and on paper."""
    return f'<div class="vocab-graph">{diagram.render_svg(project)}</div>'


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


def _term_html(e: TermEntry) -> str:
    parts = [f'<div class="vocab-term" id="{escape(e.anchor)}">']
    heading = f"<code>{escape(e.name)}</code>"
    if e.label and e.label != e.name:
        heading += f' <span class="vocab-label">{escape(e.label)}</span>'
    parts.append(f"<h3>{heading}</h3>")
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
    elif e.kind == "field_sets" and e.included_by:
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
    out: list[str] = [
        f"![Type and link graph]({DIAGRAM_ASSET})",
        "",
        (
            "*Generated from the resolved schema by `refdes/vocabulary.py` and "
            "`refdes/diagram.py`; the same drawing every built site's vocabulary "
            "page carries inline.*"
        ),
        "",
    ]
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
    elif e.kind == "field_sets" and e.included_by:
        lines.append("- **Included by:** " + ", ".join(f"`{d}`" for d in e.included_by))
    elif e.kind == "keys":
        scope = {
            "reserved": "every item; a type may not shadow it",
            "overridable": "every item, unless its type declares a field of that name",
            "file": "a YAML list file, not an item",
        }[e.key_kind]
        lines.append(f"- **Scope:** {scope}")
    return lines
