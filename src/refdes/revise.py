"""Rewrite schema vocabulary (type names, field names, link verbs, id
prefixes) project-wide, carrying content hashes forward across baselines and
seals so a purely cosmetic rename doesn't look like a content change.

Two front doors, one engine (finding 12, plus the two extensions the user
and I agreed on): `refdes revise <mapping-file>` applies an explicit,
hand-written `Mapping` for project-local vocabulary; `refdes standard
upgrade --to N` applies the bundled standard's own `migration.yaml` files,
one per version, chained in order (standards.load_migration_chain). Both
call `apply()` below.

Why this can't be a full re-serialization of every item file: PyYAML's
safe_dump doesn't round-trip comments, block-scalar style, or flow-vs-block
choices -- rewriting everything would silently destroy formatting the
project's items actually rely on (`rationale: >` blocks, inline comments).
Everything here is line-level surgical text editing instead, the same
philosophy `ids.py`'s write-back already uses, generalized from "insert one
line" to "replace specific existing lines, and only the ones this mapping
actually touches."

Safety model: every rewrite is computed fully in memory first, and the
*entire* result -- every file, the id ledger, the reloaded project -- is
verified before anything is written to disk. Verification failing anywhere
refuses the whole operation rather than leaving some files rewritten and
others not.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml

from . import build as build_mod
from . import ids as ids_mod
from . import lifecycle
from . import parse
from . import seal as seal_mod
from . import standards as standards_mod
from .model import Item, Project, SchemaError
from .schema import load_project

# -------------------------------------------------------------------- mapping


@dataclass
class Mapping:
    """One vocabulary delta: what `refdes revise` applies in a single step,
    and what one bundled standard version's own `migration.yaml` expresses
    as its change from the version immediately before it (standards.py).
    """

    types: dict[str, str] = field(default_factory=dict)
    # old type name -> {old field name -> new field name}. Scoped per type,
    # since two different types are free to use the same field name for
    # different things -- a field rename must never touch a same-named field
    # on a type that isn't the one named here.
    fields: dict[str, dict[str, str]] = field(default_factory=dict)
    # old link verb -> new link verb. Global, not per-type: link_types is one
    # project-wide namespace, unlike fields.
    links: dict[str, str] = field(default_factory=dict)
    prefixes: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.types or self.fields or self.links or self.prefixes)

    def merge(self, other: "Mapping") -> "Mapping":
        """Combine two *independent* deltas into one Mapping object for
        convenience -- NOT the same thing as applying them as one step.
        Chaining (standards.load_migration_chain / apply_chain below) must
        apply each step fully before starting the next, never merge first:
        if step A renames x->y and step B renames z->x, merging the two
        dicts collides (y AND z both trying to become x's target, or x's
        entry getting silently overwritten) where applying A then B in
        sequence is correct throughout. This method exists only for
        combining sibling categories within a single already-loaded step
        (e.g. reading one migration.yaml's types/fields/links/prefixes into
        one Mapping), never for combining two different steps.
        """
        merged = Mapping(
            types=dict(self.types), links=dict(self.links), prefixes=dict(self.prefixes)
        )
        merged.types.update(other.types)
        merged.links.update(other.links)
        merged.prefixes.update(other.prefixes)
        merged.fields = {t: dict(f) for t, f in self.fields.items()}
        for tname, frenames in other.fields.items():
            merged.fields.setdefault(tname, {}).update(frenames)
        return merged


def mapping_from_dict(raw: dict[str, Any], source: str) -> Mapping:
    """The shape both a hand-written mapping file and a bundled standard
    version's own migration.yaml share:

    types:
      constraint: bound
    fields:
      constraint:       # keyed by the OLD type name
        title: text
    links:
      refines: narrows
    prefixes:
      CON: BND

    Standalone from load_mapping() below so standards.py can read its own
    migration.yaml files as plain dicts (via yaml.safe_load, no import of
    this module) and hand the result here -- keeps the dependency one-way
    (revise.py imports standards.py for the chain, not the reverse).
    """
    if not isinstance(raw, dict):
        raise SchemaError(f"{source}: must be a mapping with types:/fields:/links:/prefixes: keys")

    types = {str(k): str(v) for k, v in (raw.get("types") or {}).items()}
    fields: dict[str, dict[str, str]] = {}
    for tname, frenames in (raw.get("fields") or {}).items():
        fields[str(tname)] = {str(k): str(v) for k, v in (frenames or {}).items()}
    links = {str(k): str(v) for k, v in (raw.get("links") or {}).items()}
    prefixes = {str(k): str(v) for k, v in (raw.get("prefixes") or {}).items()}
    return Mapping(types=types, fields=fields, links=links, prefixes=prefixes)


def load_mapping(path: str) -> Mapping:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return mapping_from_dict(raw, path)


# ----------------------------------------------------------------- ambiguity


def _collisions(mapping_dict: dict[str, str], label: str) -> list[str]:
    """Two different old names both wanting the same new name -- the mapping
    itself is self-contradictory, independent of what the project has."""
    errors = []
    seen: dict[str, str] = {}
    for old, new in mapping_dict.items():
        if old == new:
            continue
        if new in seen and seen[new] != old:
            errors.append(
                f"{label} rename collides: both {seen[new]!r} and {old!r} "
                f"would become {new!r}"
            )
        seen[new] = old
    return errors


def check_ambiguous(project: Project, mapping: Mapping) -> list[str]:
    """Every reason `mapping` cannot safely apply to `project`, checked
    before anything is touched -- same posture as `former_ids.confirm` and
    `lifecycle.stamp`: refuse rather than guess. An old==new entry is a
    no-op, not an error (lets a chained migration.yaml name a rename that
    happens not to apply to one particular project without that being a
    hard failure)."""
    errors: list[str] = []
    errors += _collisions(mapping.types, "type")
    errors += _collisions(mapping.links, "link")
    errors += _collisions(mapping.prefixes, "prefix")
    for tname, frenames in mapping.fields.items():
        errors += _collisions(frenames, f"{tname}.field")

    for old, new in mapping.types.items():
        if old == new:
            continue
        if new in project.types and new not in mapping.types:
            errors.append(f"type rename {old!r} -> {new!r}: {new!r} already names an existing type")

    for old, new in mapping.links.items():
        if old == new:
            continue
        if new in project.link_types and new not in mapping.links:
            errors.append(
                f"link rename {old!r} -> {new!r}: {new!r} already names an existing link type"
            )

    for tname, frenames in mapping.fields.items():
        spec = project.types.get(tname)
        if spec is None:
            errors.append(f"field renames given for unknown type {tname!r}")
            continue
        for old, new in frenames.items():
            if old == new:
                continue
            if new in spec.fields and new not in frenames:
                errors.append(
                    f"field rename {tname}.{old!r} -> {new!r}: {tname}.{new!r} already exists"
                )

    ledger = ids_mod.load_ledger(project)
    burned = ledger.get("burned") or {}
    for old, new in mapping.prefixes.items():
        if old == new:
            continue
        if new in burned and new not in mapping.prefixes:
            errors.append(
                f"prefix rename {old!r} -> {new!r}: {new!r} already has allocated ids "
                f"in the ledger"
            )

    return errors


# --------------------------------------------------------- file-level rewrite

# A `type:`/`section:` line's value is a type name wherever it appears --
# `defaults: {type: X}` (nested), a bare `section: X` marker, or an item's
# own `type: X` override -- since both keys are always and only reserved for
# exactly that (parse.py's RESERVED set / finding 6's section markers). Safe
# to rewrite file-wide with no per-item scoping.
_TYPE_OR_SECTION_LINE_RE = re.compile(r"^(\s*(?:-\s+)?)(type|section):(\s*)(\S+)(\s*)$")
_PREFIX_LINE_RE = re.compile(r"^(\s*(?:-\s+)?)prefix:(\s*)(\S+)(\s*)$")
_ID_LINE_RE = re.compile(r"^(\s*(?:-\s+)?)id:(\s*)(\S+)(\s*)$")


def _rewrite_type_and_prefix_lines(lines: list[str], mapping: Mapping) -> list[str]:
    """File-wide pass: `type:`/`section:` values and `prefix:` values,
    wherever they appear in the file (see _TYPE_OR_SECTION_LINE_RE). `id:`
    values are handled separately (_ID_LINE_RE) since only the prefix
    portion moves, the numeric suffix is preserved verbatim, not reformatted."""
    out = list(lines)
    for i, line in enumerate(out):
        m = _TYPE_OR_SECTION_LINE_RE.match(line)
        if m and m.group(4) in mapping.types:
            indent, key, sp1, _old, sp2 = m.groups()
            out[i] = f"{indent}{key}:{sp1}{mapping.types[m.group(4)]}{sp2}"
            continue
        m = _PREFIX_LINE_RE.match(line)
        if m:
            new_prefix = _rename_prefix(m.group(3), mapping.prefixes)
            if new_prefix is not None:
                indent, sp1, _old, sp2 = m.groups()
                out[i] = f"{indent}prefix:{sp1}{new_prefix}{sp2}"
                continue
        m = _ID_LINE_RE.match(line)
        if m:
            split = ids_mod.split_id(m.group(3))
            if split is not None:
                old_prefix = split[0]
                new_prefix = _rename_prefix(old_prefix, mapping.prefixes)
                if new_prefix is not None:
                    indent, sp1, old_id, sp2 = m.groups()
                    new_id = new_prefix + old_id[len(old_prefix) :]
                    out[i] = f"{indent}id:{sp1}{new_id}{sp2}"
    return out


def _item_spans(rel: str, lines: list[str], items: list[Item]) -> list[tuple[Item, int, int]]:
    """(item, start, end) 0-indexed half-open [start, end) line ranges, one
    per item, bounding where that item's *own* field/link keys can safely be
    found and rewritten -- narrow enough to never bleed into a neighboring
    item, a section/defaults marker (harmless if included; neither ever uses
    a field or link's own key name), or -- Markdown only -- an item's own
    prose body, which could otherwise coincidentally contain a line that
    looks like a key.
    """
    ordered = sorted(items, key=lambda i: i.source_line)
    spans: list[tuple[Item, int, int]] = []
    if rel.endswith(".md"):
        fence_lines = [i for i, l in enumerate(lines) if parse.FENCE_RE.match(l)]
        for item in ordered:
            start = item.source_line - 1  # 0-indexed first front-matter line
            close = next((f for f in fence_lines if f > start - 1), len(lines))
            spans.append((item, start, close))
    else:
        for idx, item in enumerate(ordered):
            start = item.source_line - 1
            end = ordered[idx + 1].source_line - 1 if idx + 1 < len(ordered) else len(lines)
            spans.append((item, start, end))
    return spans


def _field_or_link_line_re(key: str) -> re.Pattern:
    return re.compile(rf"^(\s*(?:-\s+)?){re.escape(key)}:(.*)$")


_ID_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+\b")


def _rewrite_id_tokens(value: str, prefixes: dict[str, str]) -> str:
    """Replace every id-shaped token in `value` whose prefix renames under
    `prefixes` (exact or compound, see `_rename_prefix`); every other
    character -- punctuation, other tokens -- passes through untouched."""

    def repl(m: re.Match) -> str:
        token = m.group(0)
        split = ids_mod.split_id(token)
        if split is None:
            return token
        new_prefix = _rename_prefix(split[0], prefixes)
        return token if new_prefix is None else new_prefix + token[len(split[0]) :]

    return _ID_TOKEN_RE.sub(repl, value)


def _rewrite_reference_ids(
    lines: list[str], rel: str, items: list[Item], mapping: Mapping
) -> list[str]:
    """Per-item pass: id-valued *references to other items* -- a link's own
    target list (`constrained_by: [CON-THM-001]`) and a `checks:` entry's
    `against:` -- rewritten when the referenced id's prefix renames under
    `mapping.prefixes`.

    An item's *own* id/prefix is `_rewrite_type_and_prefix_lines`'s job, not
    this one; this only ever follows a reference the item already declares
    (a verb in its own resolved `item.links`, or `against:` on an item that
    has `checks:` set), so a prefix rename can never leave a dangling
    reference behind elsewhere in the project. Scoped to lines matching one
    of those keys within the item's own span -- prose mentioning the same id
    elsewhere (a rationale, a log entry's body) is never touched, matching
    `_rewrite_fields_and_links`'s own scoping.

    Both YAML spellings of the value are handled: same-line (`key: [A, B]`
    or `key: A`) and block-style, where the key line is bare and the targets
    follow as `- A` entries under it. Block style is the idiomatic spelling
    for a list of any length, and skipping it did not merely leave those
    references alone -- the rewritten project then had a dangling link
    target, so the whole operation refused and rolled back, with a
    diagnostic ("constrained_by points at 'CON-THM-001', which does not
    exist") that named the symptom and nothing about the real cause. Only
    flow-style values had ever been run through this engine.

    Runs before `_rewrite_fields_and_links` in `_rewrite_file` so it can
    still find a link by its *current* key name, before any `mapping.links`
    verb rename has touched that same line's key.
    """
    if not mapping.prefixes:
        return lines
    out = list(lines)
    for item, start, end in _item_spans(rel, lines, items):
        keys = set(item.links)
        if "checks" in item.fields:
            keys.add("against")
        if not keys:
            continue
        limit = min(end, len(out))
        for i in range(start, limit):
            for key in keys:
                m = _field_or_link_line_re(key).match(out[i])
                if not m:
                    continue
                indent, rest = m.groups()
                if rest.strip():
                    new_rest = _rewrite_id_tokens(rest, mapping.prefixes)
                    if new_rest != rest:
                        out[i] = f"{indent}{key}:{new_rest}"
                else:
                    _rewrite_block_sequence(out, i + 1, limit, len(indent), mapping.prefixes)
                break
    return out


_SEQ_ENTRY_RE = re.compile(r"^(\s*)-(\s+)(\S.*?)(\s*)$")


def _rewrite_block_sequence(
    out: list[str], start: int, limit: int, key_indent: int, prefixes: dict[str, str]
) -> None:
    """Rewrite id tokens in the `- VALUE` entries of a block-style sequence
    beginning at `start`, in place.

    The sequence ends at the first line that isn't an entry indented deeper
    than the key itself -- YAML also permits an entry at the key's own
    indentation, which is accepted too, since the alternative is silently
    skipping half of a legally-written list. A blank line inside the
    sequence is passed over; anything else ends it, so a following sibling
    key is never walked into.
    """
    for i in range(start, limit):
        line = out[i]
        if not line.strip():
            continue
        m = _SEQ_ENTRY_RE.match(line)
        if m is None or len(m.group(1)) < key_indent:
            return
        indent, sep, value, trail = m.groups()
        new_value = _rewrite_id_tokens(value, prefixes)
        if new_value != value:
            out[i] = f"{indent}-{sep}{new_value}{trail}"


def _rewrite_one_key(
    out: list[str], start: int, end: int, rel: str, item: Item, kind: str, old_key: str, new_key: str
) -> str | None:
    """Rewrite `old_key:` to `new_key:` at the first matching line in
    [start, end), in place. Returns an error string (and touches nothing) if
    it can't be found."""
    key_re = _field_or_link_line_re(old_key)
    for i in range(start, min(end, len(out))):
        m = key_re.match(out[i])
        if m:
            indent, rest = m.groups()
            out[i] = f"{indent}{new_key}:{rest}"
            return None
    return (
        f"{rel}:{item.source_line} [{item.id or '?'}] -- expected to rename "
        f"{item.type}.{old_key!r} ({kind}) to {new_key!r} but couldn't find that "
        f"key written on this item (it may come from defaults:, which this "
        f"engine does not rewrite for fields/links -- only for type:)"
    )


def _rewrite_fields_and_links(
    lines: list[str], rel: str, items: list[Item], mapping: Mapping, project: Project
) -> tuple[list[str], list[str]]:
    """Per-item pass: field keys (scoped to the item's own old type) and
    link keys (scoped to links the item's own old type actually declares).

    A rename is only attempted -- and only an error if not found -- when the
    old key is actually *set* on the item (`item.fields`/`item.links`,
    already resolved through `defaults:`): an optional field this item never
    set at all has nothing to rename, silently. One that *is* set but isn't
    found within the item's own line span must be coming from `defaults:`,
    which this engine doesn't rewrite for fields/links -- that's the one
    case that's a real error, not a silent no-op.
    """
    out = list(lines)
    errors: list[str] = []
    for item, start, end in _item_spans(rel, lines, items):
        frenames = mapping.fields.get(item.type, {})
        spec = project.types.get(item.type)
        applicable_links = {
            old: new
            for old, new in mapping.links.items()
            if spec is not None and old in spec.links
        }
        for old_key, new_key in frenames.items():
            if old_key not in item.fields:
                continue
            err = _rewrite_one_key(out, start, end, rel, item, "field", old_key, new_key)
            if err:
                errors.append(err)
        for old_key, new_key in applicable_links.items():
            if old_key not in item.links:
                continue
            err = _rewrite_one_key(out, start, end, rel, item, "link", old_key, new_key)
            if err:
                errors.append(err)
    return out, errors


def _newline_style(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


@dataclass
class FileRewrite:
    path: str
    rel: str
    before: str
    after: str


def _rewrite_file(project: Project, path: str, rel: str, mapping: Mapping) -> tuple[FileRewrite, list[str]]:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    newline = _newline_style(text)
    lines = text.splitlines()

    items = [i for i in project.local_items if i.source_file == rel]

    lines = _rewrite_type_and_prefix_lines(lines, mapping)
    lines = _rewrite_reference_ids(lines, rel, items, mapping)
    lines, errors = _rewrite_fields_and_links(lines, rel, items, mapping, project)

    after = newline.join(lines)
    if lines and text.endswith(("\n", "\r\n")):
        after += newline
    return FileRewrite(path=path, rel=rel, before=text, after=after), errors


# ----------------------------------------------------------------- id ledger


def _relabel_ledger(project: Project, prefixes: dict[str, str]) -> dict | None:
    """Relabel `.refdes/ids.yaml` burned/allocated entries by prefix -- never
    renumbered, since the numeric suffix is untouched everywhere else too.
    Returns the original ledger dict (for the caller to restore verbatim if
    the operation is refused after this point), or None if there was no
    ledger file to touch."""
    if not any(old != new for old, new in prefixes.items()):
        return None
    path = ids_mod.ledger_path(project)
    if not os.path.isfile(path):
        return None
    ledger = ids_mod.load_ledger(project)
    original = {"burned": dict(ledger.get("burned") or {}), "allocated": list(ledger.get("allocated") or [])}

    burned = dict(ledger.get("burned") or {})
    new_burned: dict[str, int] = {}
    for prefix, number in burned.items():
        relabeled = _rename_prefix(prefix, prefixes) or prefix
        new_burned[relabeled] = max(int(new_burned.get(relabeled, 0)), int(number))
    allocated = [
        _relabel_id(str(i), prefixes) for i in (ledger.get("allocated") or [])
    ]
    ledger["burned"] = new_burned
    ledger["allocated"] = allocated
    ids_mod.save_ledger(project, ledger)
    return original


def _rename_prefix(prefix: str, prefixes: dict[str, str]) -> str | None:
    """The new spelling of `prefix` under `prefixes`, or None if untouched.

    Handles both an exact match (`CON` -> `BND`) and a project's own compound
    prefix built on a renamed base -- `ids.split_id`'s `PREFIX-NNN` shape
    can't distinguish "REQ-PWR" (one atomic prefix) from "REQ" + a board
    token, so a bare dict lookup against `mapping.prefixes` silently misses
    every item using this project's own documented convention (`REQ-PWR`,
    `CON-THM`, `DEC-PWR`, `TST-PWR` -- see refdes.yaml's boards: comment).
    The required separator is the hyphen itself, not just the substring, so
    an unrelated prefix that happens to start with the same letters (`CONFIG`)
    never matches.
    """
    if prefix in prefixes:
        return prefixes[prefix]
    for old, new in prefixes.items():
        if prefix.startswith(old + "-"):
            return new + prefix[len(old) :]
    return None


def _relabel_id(item_id: str, prefixes: dict[str, str]) -> str:
    split = ids_mod.split_id(item_id)
    if split is None:
        return item_id
    old_prefix = split[0]
    new_prefix = _rename_prefix(old_prefix, prefixes)
    if new_prefix is None:
        return item_id
    return new_prefix + item_id[len(old_prefix) :]


def _restore_ledger(project: Project, original: dict) -> None:
    ids_mod.save_ledger(project, {"burned": original["burned"], "allocated": original["allocated"]})


def _capture_seal_files(project: Project) -> dict[str, str]:
    """path -> original text, for every seal file that exists (base + every
    board) before anything is rewritten -- so a refusal that happens *after*
    seals have already been carried forward (see apply()'s ordering) can put
    them back exactly. `_carry_forward_seals` only ever edits a file that
    already exists (it swaps an already-recorded hash, never invents a new
    entry), so there is never a file to delete on rollback, only text to
    restore."""
    out: dict[str, str] = {}
    for board in {""} | set(project.boards):
        path = seal_mod.seal_path(project, board)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                out[path] = fh.read()
    return out


def _restore_seal_files(original: dict[str, str]) -> None:
    for path, text in original.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


# -------------------------------------------------------------------- result


@dataclass
class RevisionResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    id_changes: dict[str, str] = field(default_factory=dict)  # old id -> new id
    baselines_updated: list[str] = field(default_factory=list)
    baselines_skipped_no_standard: list[str] = field(default_factory=list)
    seals_updated: list[str] = field(default_factory=list)
    # "file:line  OLD-ID" for every prose mention of a renamed id left behind
    # -- see _stale_prose_references().
    stale_references: list[str] = field(default_factory=list)
    dry_run: bool = False


def _load_and_validate(config_path: str) -> Project:
    """Full validation, not just parsing -- required fields, enums, limits,
    link targets, the lot. `revise`'s whole safety model is "verify the
    rewritten project is as clean as the original was"; a weaker check here
    (parse.load_items() + compute_hashes() alone, this function's first
    draft) would happily pass a rewrite that silently orphaned a required
    field, which is exactly the class of mistake this exists to catch.
    seal_write=False: read-only, the same mode `check`/`revision`/`release`
    already validate through -- never writes a seal, board, or citation
    manifest of its own.
    """
    project = load_project(config_path=config_path)
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    return project


def apply(
    project_root: str,
    mapping: Mapping,
    dry_run: bool = False,
    mutate_config: Callable[[str], None] | None = None,
    standard_transition: tuple[dict, dict] | None = None,
) -> RevisionResult:
    """Apply one vocabulary delta to the project at `project_root`.

    Everything is computed in memory and verified before any disk write:
    ambiguity is checked against the pre-rewrite project, every file's
    rewrite is computed and checked for un-locatable renames, and only once
    all of that is clean does anything actually get written -- files, the id
    ledger, baselines, seals, in that order.

    `mutate_config`, if given, is called with refdes.yaml's own path *after*
    old hashes are captured and item files are rewritten, but *before* the
    rewritten project is reloaded and verified -- `standards.py`'s upgrade
    chain uses this to bump `standard.version:` atomically with the file
    rewrite it's paired with, so "before" (old version, old files) and
    "after" (new version, new files) are each independently valid and there
    is never a real on-disk moment where the two disagree. Plain `revise`
    passes none: it only ever touches item files, never refdes.yaml's own
    schema declarations (see the module docstring's "Where" scope), so a
    type or required-field rename through it needs the project's schema to
    already agree with the new names -- if it doesn't, "after" verification
    fails and this refuses/rolls back rather than leaving the project in a
    state where the data and the schema disagree.

    `standard_transition`, if given, is `({base, version}, {base, version})`
    -- the project's standard pin immediately before and after this step.
    Used only to advance a baseline's *own* recorded `standard:` (the field
    that says which vocabulary version its hashes reflect) once this step is
    confirmed to leave the whole project valid -- not just the baselines
    whose items this step's mapping actually touched, but every baseline
    still recorded at the "before" version, since a successful apply() means
    the whole project (everything any of them could reference) is now
    confirmed consistent with the "after" version too.
    """
    config_path = os.path.join(project_root, "refdes.yaml")
    project_before = _load_and_validate(config_path)
    if project_before.errors:
        return RevisionResult(
            ok=False,
            errors=[
                "project has existing build errors -- fix those first, so a "
                "hash change caused by this rename can't hide behind one "
                "already-broken build"
            ]
            + [str(d) for d in project_before.errors],
        )

    ambiguous = check_ambiguous(project_before, mapping)
    if ambiguous:
        return RevisionResult(ok=False, errors=ambiguous)

    old_hashes = {item.id: item.content_hash for item in project_before.local_items}

    rewrites: list[FileRewrite] = []
    all_errors: list[str] = []
    # Only files that actually parsed into at least one item -- a file that
    # parsed into nothing (or only markers) has no `type:`/field/link/prefix
    # spelling of its own to touch, and project_before.errors is already
    # confirmed empty above, so there's no silently-dropped item hiding here.
    rels = sorted({item.source_file for item in project_before.local_items})
    for rel in rels:
        path = os.path.join(project_before.root, *rel.split("/"))
        rw, errors = _rewrite_file(project_before, path, rel, mapping)
        all_errors += errors
        if rw.after != rw.before:
            rewrites.append(rw)

    if all_errors:
        return RevisionResult(ok=False, errors=all_errors)

    if not rewrites and not any(old != new for old, new in mapping.prefixes.items()) and mutate_config is None:
        return RevisionResult(ok=True, dry_run=dry_run)  # nothing to do

    if dry_run:
        return RevisionResult(ok=True, dry_run=True, changed_files=[r.rel for r in rewrites])

    for rw in rewrites:
        with open(rw.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(rw.after)

    original_ledger = _relabel_ledger(project_before, mapping.prefixes)
    original_seals = _capture_seal_files(project_before)
    with open(config_path, "r", encoding="utf-8") as fh:
        config_before = fh.read()

    def _rollback() -> None:
        for rw in rewrites:
            with open(rw.path, "w", encoding="utf-8", newline="") as fh:
                fh.write(rw.before)
        if original_ledger is not None:
            _restore_ledger(project_before, original_ledger)
        _restore_seal_files(original_seals)
        with open(config_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(config_before)

    if mutate_config is not None:
        mutate_config(config_path)

    # A light reload -- parse + compute_hashes only, no full build() -- just
    # to learn each item's new id/hash. Deliberately lighter than
    # _load_and_validate: seal.verify() is part of that full build, and a
    # rename that changes a *sealed* item's hash would otherwise always trip
    # it here, before seals have had any chance to be carried forward (the
    # same hash drives both baseline diffing and seal.py's append-only
    # comparison -- a seal mismatch is a build ERROR, not a diff). So seals
    # are carried forward against this light pass's hashes first, and only
    # *then* is the real, full, strict validation run below -- by which
    # point a purely cosmetic rename's own seal has already moved with it.
    try:
        project_light = load_project(config_path=config_path)
        parse.load_items(project_light, require_ids=False)
        build_mod.compute_hashes(project_light)
    except SchemaError as exc:
        _rollback()
        return RevisionResult(ok=False, errors=[f"rewritten project no longer loads: {exc}"])

    if project_light.errors:
        _rollback()
        return RevisionResult(
            ok=False,
            errors=["rewritten project has parse errors -- rolled back:"]
            + [str(d) for d in project_light.errors],
        )

    # Correlate old<->new items by (source_file, source_line): a pure
    # same-line text substitution never changes line counts, so this pairing
    # is exact -- it is how an id's *old* value (used as the baseline/seal
    # lookup key) is recovered even after this same rewrite has already
    # changed that id's own prefix on disk.
    by_pos_before = {(i.source_file, i.source_line): i for i in project_before.local_items}
    by_pos_after = {(i.source_file, i.source_line): i for i in project_light.local_items}
    id_changes: dict[str, str] = {}
    new_hashes: dict[str, str] = {}
    for pos, before_item in by_pos_before.items():
        after_item = by_pos_after.get(pos)
        if after_item is None:
            continue
        if before_item.id != after_item.id:
            id_changes[before_item.id] = after_item.id
        new_hashes[before_item.id] = after_item.content_hash

    seals_updated = _carry_forward_seals(project_before, old_hashes, new_hashes, id_changes)

    try:
        project_after = _load_and_validate(config_path)
    except SchemaError as exc:
        _rollback()
        return RevisionResult(ok=False, errors=[f"rewritten project no longer loads: {exc}"])

    if project_after.errors:
        _rollback()
        return RevisionResult(
            ok=False,
            errors=["rewritten project has build errors -- rolled back:"]
            + [str(d) for d in project_after.errors],
        )

    baselines_updated, baselines_skipped = _carry_forward_baselines(
        project_before, old_hashes, new_hashes, id_changes, standard_transition
    )

    return RevisionResult(
        ok=True,
        changed_files=[r.rel for r in rewrites],
        id_changes=id_changes,
        baselines_updated=baselines_updated,
        baselines_skipped_no_standard=baselines_skipped,
        seals_updated=seals_updated,
        stale_references=_stale_prose_references(project_after, id_changes),
    )


def _stale_prose_references(project: Project, id_changes: dict[str, str]) -> list[str]:
    """Every prose mention of an id this operation renamed that no longer
    resolves to anything, as "file:line  OLD-ID -> NEW-ID".

    Only structured references move (see `_rewrite_reference_ids`): an id
    written into a rationale, a log entry's body, or a narrative page is
    deliberately left alone, because rewriting prose means editing a
    sentence -- including, for a sealed append-only entry, one that is not
    supposed to change. But leaving it alone silently is the wrong other
    half: a bare `CON-THM-001` that used to autolink renders as dead plain
    text afterward with no diagnostic at all, and the operation reports
    success. So the engine doesn't guess, and it doesn't go quiet either --
    it says exactly which lines it did not touch and now can't resolve.

    A token that still resolves -- to a live item, or through some item's
    `former_ids:` -- is not stale and is not reported.
    """
    if not id_changes:
        return []

    def resolves(token: str) -> bool:
        return token in project.items or token in project.former_ids

    sources = {item.source_file for item in project.local_items}
    sources |= {page.source_file for page in project.pages}

    out: list[str] = []
    for rel in sorted(sources):
        path = os.path.join(project.root, *rel.split("/"))
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            for token in dict.fromkeys(_ID_TOKEN_RE.findall(line)):
                if token in id_changes and not resolves(token):
                    out.append(f"{rel}:{lineno}  {token} -> {id_changes[token]}")
    return out


# --------------------------------------------------------- hash carry-forward


def _carry_forward_baselines(
    project: Project,
    old_hashes: dict[str, str],
    new_hashes: dict[str, str],
    id_changes: dict[str, str],
    standard_transition: tuple[dict, dict] | None = None,
) -> tuple[list[str], list[str]]:
    """Swap each affected item's old hash (and, for a prefix rename, its old
    id key) for the new one in every stamped baseline.

    Plain `revise` (standard_transition=None) matches purely by hash: an
    old_hash that matches what's stored is proof enough this baseline's
    entry really does predate the rename, id or vocabulary version aside --
    there is only one relevant "before" state for a single, atomic project-
    local rename, so there's no separate provenance question to ask.

    A standard-upgrade step is different: a project can have several
    baselines stamped at different points in a multi-version history, and
    THIS step's "before" hash is only the right thing to compare against a
    baseline that started at exactly the version this step steps from --
    one several versions further behind would need the *intervening* steps
    replayed first, which a single step's hash-match can't tell apart from
    "this baseline was never touched by this rename at all" on its own. So
    when `standard_transition` is given, a baseline is only touched (hash
    swap, or just advancing its own recorded `standard:`, even with nothing
    to swap) if its `standard:` exactly matches this step's "before" side;
    one recording anything else -- including None, never stamped under a
    known vocabulary version, or written before that field existed -- is
    skipped, not guessed at (lifecycle.Baseline.standard's own docstring).
    """
    updated: list[str] = []
    skipped: list[str] = []
    from_standard = standard_transition[0] if standard_transition else None
    to_standard = standard_transition[1] if standard_transition else None
    for baseline in lifecycle.list_baselines(project):
        if standard_transition is not None and baseline.standard != from_standard:
            if any(old_id in baseline.items for old_id in old_hashes):
                skipped.append(baseline.name)
            continue
        changed = False
        new_items = dict(baseline.items)
        for old_id, old_hash in old_hashes.items():
            entry = new_items.get(old_id)
            if entry is None:
                continue
            if entry.get("hash") != old_hash:
                # Stale for an unrelated reason (a real content edit since
                # this baseline was stamped) -- swapping it in would hide
                # that, so this id is left untouched rather than guessed at.
                continue
            new_id = id_changes.get(old_id, old_id)
            new_entry = dict(entry)
            new_entry["hash"] = new_hashes.get(old_id, entry["hash"])
            del new_items[old_id]
            new_items[new_id] = new_entry
            changed = True

        advance = from_standard is not None and baseline.standard == from_standard
        if changed or advance:
            new_standard = to_standard if advance else baseline.standard
            _rewrite_baseline_file(project, baseline, new_items, new_standard)
            updated.append(baseline.name)
    return updated, skipped


def _rewrite_baseline_file(
    project: Project, baseline: lifecycle.Baseline, new_items: dict, standard: dict | None = None
) -> None:
    data: dict[str, Any] = {
        "kind": baseline.kind,
        "name": baseline.name,
        "stamped_at": baseline.stamped_at,
        "stamped_by": baseline.stamped_by,
        "refdes_version": baseline.refdes_version,
    }
    if standard is not None:
        data["standard"] = standard
    if baseline.gate is not None:
        data["gate"] = baseline.gate
    data["items"] = dict(sorted(new_items.items()))
    lifecycle._save_baseline_file(project, data)


def _carry_forward_seals(
    project: Project,
    old_hashes: dict[str, str],
    new_hashes: dict[str, str],
    id_changes: dict[str, str],
) -> list[str]:
    """Swap the same old-hash-for-new (and id key, for a prefix rename) in
    every per-board (and the base) seal file. The same hash that drives
    baseline diffs also drives seal.py's append-only comparison, and a seal
    mismatch is a build ERROR, not a noisy diff -- a purely cosmetic rename
    left uncovered here would turn a clean build into a failing one on every
    sealed log entry it touched."""
    updated: list[str] = []
    boards = {""} | set(project.boards)
    for board in sorted(boards):
        path = seal_mod.seal_path(project, board)
        if not os.path.isfile(path):
            continue
        seals = seal_mod.load_seals(project, board)
        changed = False
        new_seals = dict(seals)
        for old_id, old_hash in old_hashes.items():
            recorded = new_seals.get(old_id)
            if recorded is None or recorded != old_hash:
                continue
            new_id = id_changes.get(old_id, old_id)
            del new_seals[old_id]
            new_seals[new_id] = new_hashes.get(old_id, recorded)
            changed = True
        if changed:
            seal_mod.save_seals(project, new_seals, board)
            updated.append(board or "(base)")
    return updated


# ------------------------------------------------------------ standard upgrade

_STANDARD_KEY_RE = re.compile(r"^(\s*)standard:(\s*\{.*)?$")
_VERSION_KV_RE = re.compile(r"(^\s*version:\s*)\d+(\s*)$")
_VERSION_FLOW_RE = re.compile(r"(version:\s*)\d+")


def _bump_standard_version(config_path: str, new_version: int) -> None:
    """Rewrite refdes.yaml's own `standard: {..., version: N, ...}` in
    place, block or flow style -- the one piece of schema.py's territory
    revise.py ever touches, and only this one number, only for a bundled
    standard's own upgrade (never for plain `revise`, which has no
    standard.version to move)."""
    with open(config_path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines(keepends=True)

    for i, line in enumerate(lines):
        if _STANDARD_KEY_RE.match(line):
            break
    else:
        raise SchemaError(f"{config_path}: no 'standard:' key found to bump")

    if "{" in line:
        new_line, count = _VERSION_FLOW_RE.subn(rf"\g<1>{new_version}", line)
        if count != 1:
            raise SchemaError(f"{config_path}: could not find version: inside the standard: block")
        lines[i] = new_line
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        return

    base_indent = len(line) - len(line.lstrip(" "))
    j = i + 1
    while j < len(lines):
        candidate = lines[j]
        if candidate.strip() == "":
            j += 1
            continue
        indent = len(candidate) - len(candidate.lstrip(" "))
        if indent <= base_indent:
            break
        new_line, count = _VERSION_KV_RE.subn(rf"\g<1>{new_version}\g<2>", candidate)
        if count:
            lines[j] = new_line
            with open(config_path, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            return
        j += 1
    raise SchemaError(f"{config_path}: could not find version: inside the standard: block")


@dataclass
class UpgradeStepResult:
    from_version: int
    to_version: int
    result: RevisionResult


def apply_standard_upgrade(project_root: str, to_version: int) -> list[UpgradeStepResult]:
    """Chain every version's own migration.yaml, in order, from the
    project's currently pinned version up to `to_version` -- one call to
    apply() per version step, each bumping standard.version to *that* step's
    own number via _bump_standard_version, atomically with that step's file
    rewrite.

    Deliberately never merges the chain's steps into one combined Mapping
    before applying (extension 2): if step N renames a->b and step N+1
    renames c->a, a merged dict would collide (b and c would both be
    claiming a's old identity, or naively updating one dict with the next
    would just silently drop the first rename) where applying N fully, then
    N+1 against the *result* of N, is correct throughout -- by the time step
    N+1 runs, nothing in the project is named `a` anymore, so its own
    `c -> a` rename lands cleanly with no collision to resolve.

    Stops at the first step that fails, returning every step attempted so
    far (including the failed one) -- a partial chain never applies further
    than the point that failed, and every step actually written is already
    independently verified (apply()'s own safety model), so the project is
    left at a fully valid, if not fully upgraded, version.
    """
    config_path = os.path.join(project_root, "refdes.yaml")
    project = load_project(config_path=config_path)
    if not project.standard_base:
        raise SchemaError(
            "project is not pinned to a bundled standard (standard: none, or absent) "
            "-- nothing for 'refdes standard upgrade' to chain"
        )
    if project.standard_version is None or project.standard_version >= to_version:
        raise SchemaError(
            f"project is already at {project.standard_base}@{project.standard_version}, "
            f"not below the requested --to {to_version}"
        )

    base = project.standard_base
    results: list[UpgradeStepResult] = []
    current = project.standard_version
    while current < to_version:
        next_version = current + 1
        raw = standards_mod.load_migration_raw(base, next_version)
        mapping = (
            mapping_from_dict(raw, f"{base}@{next_version} migration.yaml")
            if raw is not None
            else Mapping()
        )

        def _bump(cfg_path: str, v: int = next_version) -> None:
            _bump_standard_version(cfg_path, v)

        transition = (
            {"base": base, "version": current},
            {"base": base, "version": next_version},
        )
        result = apply(project_root, mapping, mutate_config=_bump, standard_transition=transition)
        results.append(UpgradeStepResult(from_version=current, to_version=next_version, result=result))
        if not result.ok:
            break
        current = next_version
    return results
