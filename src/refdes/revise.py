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

from . import build as build_mod
from . import ids as ids_mod
from . import keys as keys_mod
from . import lifecycle, parse
from . import links as links_mod
from . import seal as seal_mod
from . import standards as standards_mod
from .model import CHECK_VIOLATION, Item, Project, SchemaError
from .parse import yaml_safe_load
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
    migration.yaml files as plain dicts (via yaml_safe_load, no import of
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
        raw = yaml_safe_load(fh) or {}
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

    return errors


def check_body_merge_conflicts(project: Project, mapping: Mapping) -> list[str]:
    """Refuse a field rename that targets the reserved `body:` key wherever
    an item already has body content of its own (list-file `body:`, or a
    markdown item's prose after the closing fence).

    `body:` isn't a schema field -- there is nothing in `spec.fields` for
    `check_ambiguous`'s own "does the target already exist" check to find,
    so a rename into it needs this instead. Without it, `_rewrite_one_key`
    would rename the old field's key in place (e.g. `text:` ->
    `body:` in front matter) while the item's *real* body -- whatever
    `item.body` already held -- stays exactly where it is; whichever the
    parser reads back after rewrite silently wins, and the other is an
    orphaned, unreferenced key nothing reports as wrong. Caught here,
    before anything is written, rather than trusted to the reload-and-
    verify safety net: a value simply going missing produces no invalid
    state for that net to catch.
    """
    errors: list[str] = []
    for tname, frenames in mapping.fields.items():
        targets_body = {old for old, new in frenames.items() if new == "body" and old != new}
        if not targets_body:
            continue
        for item in project.local_items:
            if item.type != tname:
                continue
            if not any(old in item.fields for old in targets_body):
                continue
            if item.body.strip():
                errors.append(
                    f"{item.source_file}:{item.source_line} [{item.id or '?'}] -- "
                    f"can't rename {tname}.{'/'.join(sorted(targets_body))} to body: "
                    f"this item already has its own body content, which the rename "
                    f"would silently orphan or overwrite. Merge them by hand first."
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
        fence_lines = [i for i, line in enumerate(lines) if parse.FENCE_RE.match(line)]
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
    existed: bool = True


def write_rewrites(rewrites: list[FileRewrite]) -> None:
    """Write a computed set using the transaction engine's exact text mode."""
    for rewrite in rewrites:
        os.makedirs(os.path.dirname(rewrite.path), exist_ok=True)
        with open(rewrite.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(rewrite.after)


def restore_rewrites(rewrites: list[FileRewrite]) -> None:
    """Restore every computed set member, including removing new files."""
    for rewrite in rewrites:
        if not rewrite.existed:
            if os.path.isfile(rewrite.path):
                os.remove(rewrite.path)
            continue
        with open(rewrite.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(rewrite.before)


def _rewrite_file(project: Project, path: str, rel: str, mapping: Mapping) -> tuple[FileRewrite, list[str]]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    newline = _newline_style(text)
    lines = text.splitlines()

    items = [i for i in project.local_items if i.source_file == rel]

    lines = _rewrite_type_and_prefix_lines(lines, mapping)
    lines, errors = _rewrite_fields_and_links(lines, rel, items, mapping, project)

    after = newline.join(lines)
    if lines and text.endswith(("\n", "\r\n")):
        after += newline
    return FileRewrite(path=path, rel=rel, before=text, after=after), errors


def _rename_prefix(prefix: str, prefixes: dict[str, str]) -> str | None:
    """The new spelling of `prefix` under `prefixes`, or None if untouched.

    Handles both an exact match (`CON` -> `BND`) and a project's own compound
    prefix built on a renamed base -- `ids.split_id`'s `PREFIX-NNN` shape
    can't distinguish "REQ-PWR" (one atomic prefix) from "REQ" + a board
    token, so a bare dict lookup against `mapping.prefixes` silently misses
    every item using this project's own documented convention (`REQ-PWR`,
    `CON-THM`, `DEC-PWR`, `TST-PWR` -- see refdes-project.yaml's boards: comment).
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
    # Dry-run only: "file:line  old -> new" for every line the real run would
    # rewrite while minting keys and expanding references to composite form
    # before the rename itself (docs/design/keys.md §4).
    expansions: list[str] = field(default_factory=list)
    # True when this step changed refdes-project.yaml itself -- today, a standard
    # upgrade bumping `standard.version:`. Distinguishes "no item file needed
    # rewriting, and the pin moved" from "this mapping does not apply here",
    # which look identical from changed_files alone.
    config_updated: bool = False
    dry_run: bool = False


def _blocking_errors(project: Project) -> list:
    """Errors that must stop a vocabulary rewrite -- every error except a
    check that ran and produced a violating result.

    The rule this enforces is "a hash change caused by this rename must not
    be able to hide behind an already-broken build", and that is about the
    document: an item that doesn't parse, a required field that isn't there,
    a link pointing at nothing, a schema the data no longer satisfies. Those
    still refuse.

    A failing `checks:` result is not that. It means the arithmetic ran, the
    comparison happened, and the design does not currently meet a bound --
    the tool working exactly as designed, and the single most likely state
    for a board mid-revision to be sitting in for weeks at a time. This
    project's own sample carries one deliberately, as the teaching example
    on the front page of the docs. Blocking a vocabulary migration on it
    made `refdes revise` and `refdes standard upgrade` unusable on precisely
    the projects most likely to need them, and bought nothing: a rename
    cannot change a check's verdict, since the arithmetic and the limit both
    move with it, and if one somehow did, the post-rewrite validation below
    compares the same way and would catch it.
    """
    return [d for d in project.errors if d.code != CHECK_VIOLATION]


def _load_light(config_path: str) -> Project:
    project = load_project(config_path=config_path)
    parse.load_items(project, require_ids=False)
    return project


def _run_key_ensure(config_path: str) -> list[FileRewrite]:
    """Run the writable-load key maintenance pipeline (docs/design/keys.md
    §2-§3: mint, link expansion, `checks: against:` expansion, follows
    freeze) for real, and return the net text changes as FileRewrites so the
    caller can roll them back if the operation that needed them is refused.

    This is the same sequence `cli._load()` runs on every writable command;
    `revise` used to be the one path that bypassed it (it calls apply()
    directly, never through the CLI loader), which is why a prefix rename
    here had to carry its own reference-rewriting machinery. With the
    pipeline run first, every expandable structured reference is already a
    `DISPLAY@key` composite whose key half no rename touches, and the only
    references left bare are the ones expansion cannot reach -- which the
    rename must refuse over, not silently rewrite around.
    """
    rels = sorted(
        {
            i.source_file
            for i in _load_light(config_path).local_items + _load_light(config_path).pending
        }
    )
    before: dict[str, str] = {}
    for rel in rels:
        path = os.path.join(os.path.dirname(config_path), *rel.split("/"))
        with open(path, "r", encoding="utf-8", newline="") as fh:
            before[rel] = fh.read()

    project = _load_light(config_path)
    if keys_mod.mint_missing(project, write=True):
        project = _load_light(config_path)
    if links_mod.expand_missing(project, write=True):
        project = _load_light(config_path)
    if links_mod.expand_missing_checks(project, write=True):
        project = _load_light(config_path)
    links_mod.freeze_follows(project, write=True)

    rewrites: list[FileRewrite] = []
    for rel, text in before.items():
        path = os.path.join(os.path.dirname(config_path), *rel.split("/"))
        with open(path, "r", encoding="utf-8", newline="") as fh:
            now = fh.read()
        if now != text:
            rewrites.append(FileRewrite(path=path, rel=rel, before=text, after=now))
    return rewrites


def _snapshot_item_texts(project: Project) -> dict[str, str]:
    """rel -> exact on-disk text, for every file holding an item (local or
    pending) -- the baseline the ensure/refresh rollback diffs against."""
    out: dict[str, str] = {}
    for item in project.local_items + project.pending:
        rel = item.source_file
        if rel in out:
            continue
        path = os.path.join(project.root, *rel.split("/"))
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", newline="") as fh:
                out[rel] = fh.read()
    return out


def _simulate_key_ensure(
    config_path: str, snapshot: dict[str, str], mapping: Mapping
) -> tuple[list[str], list[str]]:
    """Dry-run twin of the whole real run: copy the tree to a throwaway
    directory and perform the entire sequence there -- key ensure, the
    rename's own file rewrites, and the post-rename display-half refresh --
    then report (blockers, per-line changes). The real tree is never
    touched; the report is what the real run would write, file-for-file,
    including the refresh files that only exist because of the rename."""
    import shutil
    import tempfile

    root = os.path.dirname(config_path)
    tmp = tempfile.mkdtemp(prefix="refdes-revise-")
    try:
        copy = os.path.join(tmp, "proj")
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns("_site", ".git"))
        copy_config = os.path.join(copy, "refdes-project.yaml")
        _run_key_ensure(copy_config)
        simulated = _load_light(copy_config)
        blockers = _bare_reference_blockers(simulated, mapping)
        if not blockers:
            # The rename itself, on the copy: same per-file rewrite the real
            # run performs, then the same post-rename display-half refresh.
            for rel in sorted({item.source_file for item in simulated.local_items}):
                path = os.path.join(copy, *rel.split("/"))
                rw, errors = _rewrite_file(simulated, path, rel, mapping)
                if errors:
                    return errors, []
                if rw.after != rw.before:
                    with open(path, "w", encoding="utf-8", newline="") as fh:
                        fh.write(rw.after)
            _refresh_display_halves(copy_config)
        report: list[str] = []
        for rel, text in sorted(snapshot.items()):
            path = os.path.join(copy, *rel.split("/"))
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8", newline="") as fh:
                after = fh.read()
            report.extend(_line_diff_report(rel, text, after))
        return blockers, report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _line_diff_report(rel: str, before: str, after: str) -> list[str]:
    if before == after:
        return []
    b, a = before.splitlines(), after.splitlines()
    if len(b) == len(a):
        return [
            f"{rel}:{i + 1}  {x.strip()} -> {y.strip()}"
            for i, (x, y) in enumerate(zip(b, a))
            if x != y
        ]
    import difflib

    out: list[str] = []
    matcher = difflib.SequenceMatcher(None, b, a, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                x = b[i1 + k].strip() if i1 + k < i2 else ""
                y = a[j1 + k].strip() if j1 + k < j2 else ""
                out.append(f"{rel}:{j1 + k + 1}  {x} -> {y}")
        elif tag == "insert":
            out += [f"{rel}:{j1 + k + 1}  (added) {a[j1 + k].strip()}" for k in range(j2 - j1)]
        else:
            out += [f"{rel}:{i1 + k + 1}  (removed) {b[i1 + k].strip()}" for k in range(i2 - i1)]
    return out


def _refresh_display_halves(config_path: str) -> None:
    """After a rename, refresh stale composite display halves (the §3 pass a
    writable load runs). Key-resolved hashes are untouched by this -- only
    the display text moves -- so it is safe between the file rewrite and the
    hash carry-forward."""
    project = _load_light(config_path)
    if links_mod.expand_missing(project, write=True):
        project = _load_light(config_path)
    links_mod.expand_missing_checks(project, write=True)


def _affected_ids(project: Project, mapping: Mapping) -> dict[str, str]:
    """old id -> new id for every local item whose display id this prefix
    rename would move (exact or compound prefix, see _rename_prefix)."""
    affected: dict[str, str] = {}
    for item in project.local_items:
        split = ids_mod.split_id(item.id or "")
        if split is None:
            continue
        new_prefix = _rename_prefix(split[0], mapping.prefixes)
        if new_prefix is not None:
            affected[item.id] = new_prefix + item.id[len(split[0]) :]
    return affected


def _bare_reference_blockers(project: Project, mapping: Mapping) -> list[str]:
    """Every structured reference that still spells, bare, an id this prefix
    rename would move -- as file:line refusals. Bare references are what
    key expansion could not reach (a `checks:` inherited from defaults: is
    the known case, docs/design/keys.md's disclosed gap); rewriting them is
    exactly what this engine no longer does, so a rename that would leave
    one behind refuses instead."""
    affected = _affected_ids(project, mapping)
    if not affected:
        return []

    blockers: list[str] = []

    def check(item: Item, pointer: str, target: str, inherited: bool) -> None:
        if "@" in target:
            return
        target_item = project.item_by_id(target)
        if target_item is None or target_item.id not in affected:
            return
        note = (
            " (inherited from defaults:, which key expansion does not reach -- "
            "docs/design/keys.md's disclosed gap)" if inherited else ""
        )
        blockers.append(
            f"{item.source_file}:{item.source_line} [{item.id or '?'}] {pointer}: "
            f"{target!r} is still a bare reference to an id this rename moves "
            f"({target} -> {affected[target]}); key expansion could not reach it"
            f"{note}, and revise does not rewrite bare references -- fix it by hand"
        )

    for item in project.local_items:
        for verb, targets in item.links.items():
            for target in targets:
                check(item, verb, str(target), verb in item.inherited_fields)
        entries = item.fields.get("checks")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and "against" in entry:
                    check(
                        item,
                        "check against",
                        str(entry["against"]),
                        "checks" in item.inherited_fields,
                    )
    return blockers


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

    `mutate_config`, if given, is called with refdes-project.yaml's own path *after*
    old hashes are captured and item files are rewritten, but *before* the
    rewritten project is reloaded and verified -- `standards.py`'s upgrade
    chain uses this to bump `standard.version:` atomically with the file
    rewrite it's paired with, so "before" (old version, old files) and
    "after" (new version, new files) are each independently valid and there
    is never a real on-disk moment where the two disagree. Plain `revise`
    passes none: it only ever touches item files, never refdes-project.yaml's own
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
    config_path = os.path.join(project_root, "refdes-project.yaml")
    project_before = _load_and_validate(config_path)
    blocking = _blocking_errors(project_before)
    if blocking:
        return RevisionResult(
            ok=False,
            errors=[
                "project has existing build errors -- fix those first, so a "
                "hash change caused by this rename can't hide behind one "
                "already-broken build"
            ]
            + [str(d) for d in blocking],
        )

    ambiguous = check_ambiguous(project_before, mapping)
    ambiguous += check_body_merge_conflicts(project_before, mapping)
    if ambiguous:
        return RevisionResult(ok=False, errors=ambiguous)

    # A prefix rename moves display ids that structured references may still
    # spell bare. This engine no longer rewrites bare references (docs/design/
    # keys.md §4): it runs the same writable-load key maintenance every other
    # command performs -- mint, link/check expansion, follows freeze -- inside
    # its own transaction first, and refuses with file:line if a structured
    # reference to an affected id is *still* bare afterwards. A dry run
    # simulates that whole pipeline on a throwaway copy of the tree, so the
    # report says what the real run would expand instead of pretending the
    # rename is smaller than it is.
    prefix_rename = bool(_affected_ids(project_before, mapping))
    ensure_rewrites: list[FileRewrite] = []
    refresh_rewrites: list[FileRewrite] = []
    expansions: list[str] = []
    snapshot: dict[str, str] = {}
    if prefix_rename:
        snapshot = _snapshot_item_texts(project_before)
        if dry_run:
            blockers, expansions = _simulate_key_ensure(config_path, snapshot, mapping)
            if blockers:
                return RevisionResult(ok=False, errors=blockers, expansions=expansions)
        else:
            ensure_rewrites = _run_key_ensure(config_path)
            project_before = _load_and_validate(config_path)
            blockers = _bare_reference_blockers(project_before, mapping)
            if blockers:
                restore_rewrites(ensure_rewrites)
                return RevisionResult(ok=False, errors=blockers)

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

    if not rewrites and not prefix_rename and mutate_config is None:
        return RevisionResult(ok=True, dry_run=dry_run)  # nothing to do

    if dry_run:
        changed = {r.rel for r in rewrites}
        changed |= {rel for entry in expansions for rel in [entry.split(":", 1)[0]] if ":" in entry}
        return RevisionResult(
            ok=True, dry_run=True, changed_files=sorted(changed), expansions=expansions
        )

    write_rewrites(rewrites)

    original_seals = _capture_seal_files(project_before)
    with open(config_path, "r", encoding="utf-8") as fh:
        config_before = fh.read()

    def _rollback() -> None:
        restore_rewrites(refresh_rewrites)
        restore_rewrites(rewrites)
        restore_rewrites(ensure_rewrites)
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

    light_blocking = _blocking_errors(project_light)
    if light_blocking:
        _rollback()
        return RevisionResult(
            ok=False,
            errors=["rewritten project has parse errors -- rolled back:"]
            + [str(d) for d in light_blocking],
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

    # Composite display halves naming a renamed item are now stale text.
    # Refresh them with the same §3 pass a writable load runs -- it rewrites
    # only the display half of `DISPLAY@key` references, and hashes are
    # key-resolved, so this cannot disturb the carry-forward below. Writes go
    # through the snapshot so a later refusal puts every byte back.
    _refresh_display_halves(config_path)
    for rel, before in snapshot.items():
        path = os.path.join(project_before.root, *rel.split("/"))
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8", newline="") as fh:
            now = fh.read()
        if now != before and rel not in {r.rel for r in rewrites} | {
            r.rel for r in ensure_rewrites
        }:
            refresh_rewrites.append(
                FileRewrite(path=path, rel=rel, before=before, after=now)
            )

    seals_updated = _carry_forward_seals(project_before, old_hashes, new_hashes)

    try:
        project_after = _load_and_validate(config_path)
    except SchemaError as exc:
        _rollback()
        return RevisionResult(ok=False, errors=[f"rewritten project no longer loads: {exc}"])

    after_blocking = _blocking_errors(project_after)
    if after_blocking:
        _rollback()
        return RevisionResult(
            ok=False,
            errors=["rewritten project has build errors -- rolled back:"]
            + [str(d) for d in after_blocking],
        )

    baselines_updated, baselines_skipped = _carry_forward_baselines(
        project_before, old_hashes, new_hashes, standard_transition
    )

    changed_files = sorted(
        {r.rel for r in ensure_rewrites} | {r.rel for r in rewrites} | {r.rel for r in refresh_rewrites}
    )
    return RevisionResult(
        ok=True,
        changed_files=changed_files,
        id_changes=id_changes,
        baselines_updated=baselines_updated,
        baselines_skipped_no_standard=baselines_skipped,
        seals_updated=seals_updated,
        stale_references=_stale_prose_references(
            project_before, project_after, id_changes, mapping.fields
        ),
        config_updated=mutate_config is not None,
    )


def _stale_prose_references(
    project_before: Project,
    project: Project,
    id_changes: dict[str, str],
    field_renames: dict[str, dict[str, str]],
) -> list[str]:
    """Every prose mention this operation leaves pointing at something that no
    longer resolves, as "file:line  OLD -> NEW" -- two independent ways a
    rename can do that:

    Whole-id staleness: an id this operation renamed, still spelled the old
    way, that no longer resolves to anything (a bare `CON-THM-001`, or the
    id half of an explicit `[[CON-THM-001]]` or `[[CON-THM-001#field]]` --
    `_ID_TOKEN_RE` matches the id either way, brackets and fragment along for
    the ride). Only structured references move (see
    structured references move by key expansion, never by text rewrite): an id written into a rationale, a log entry's
    body, or a narrative page is deliberately left alone, because rewriting
    prose means editing a sentence -- including, for a sealed append-only
    entry, one that is not supposed to change. But leaving it alone silently
    is the wrong other half: a bare id that used to autolink renders as dead
    plain text afterward with no diagnostic at all, and the operation reports
    success. So the engine doesn't guess, and it doesn't go quiet either -- it
    says exactly which lines it did not touch and now can't resolve.

    Field-fragment staleness: an explicit `[[ID#field]]` whose *id* still
    resolves fine, but whose `field` named the old side of a field rename
    this same mapping applied to that id's own (pre-rewrite) type -- the
    fragment now names a field the target's type no longer declares, exactly
    the "undeclared field" case `build._linkify` would warn about if it saw
    this rewritten project, except prose is never rewritten so nothing ever
    makes it run that check. `project_before` is what recovers the id's type
    as it was named in the mapping (`field_renames` is keyed by the OLD type
    name), since prose always still spells ids and fields the old way.

    A whole-id mention that still resolves -- to a live item, or through some
    item's `former_ids:` -- is not stale and is not reported; nor is a
    fragment on it, since `_stale_prose_references` only ever gets called
    with the delta this operation itself introduced.
    """
    if not id_changes and not field_renames:
        return []

    def resolves(token: str) -> bool:
        return project.item_by_id(token) is not None or token in project.former_ids

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
            if not field_renames:
                continue
            for m in build_mod.EXPLICIT_REF_RE.finditer(line):
                target_id, target_field = m.group(1), m.group(2)
                if not target_field or not resolves(target_id):
                    continue
                before_item = project_before.item_by_id(target_id)
                if before_item is None:
                    continue
                frenames = field_renames.get(before_item.type)
                if frenames and target_field in frenames:
                    out.append(
                        f"{rel}:{lineno}  {target_id}#{target_field} -> "
                        f"{target_id}#{frenames[target_field]}"
                    )
    return out


# --------------------------------------------------------- hash carry-forward


def _carry_forward_baselines(
    project: Project,
    old_hashes: dict[str, str],
    new_hashes: dict[str, str],
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
        indexes = lifecycle._baseline_indexes(baseline.items)
        if standard_transition is not None and baseline.standard != from_standard:
            if any(
                lifecycle._match_baseline_entry(
                    indexes,
                    old_id,
                    {"key": project.item_by_id(old_id).key} if project.item_by_id(old_id).key else {},
                )
                is not None
                for old_id in old_hashes
            ):
                skipped.append(baseline.name)
            continue
        changed = False
        new_items = dict(baseline.items)
        for old_id, old_hash in old_hashes.items():
            item = project.item_by_id(old_id)
            matched = lifecycle._match_baseline_entry(
                indexes, old_id, {"key": item.key} if item.key else {}
            )
            if matched is None:
                continue
            record_id, _display_id, entry = matched
            if entry.get("hash") != old_hash:
                # Stale for an unrelated reason (a real content edit since
                # this baseline was stamped) -- swapping it in would hide
                # that, so this identity is left untouched rather than guessed at.
                continue
            new_entry = dict(entry)
            new_entry["hash"] = new_hashes.get(old_id, entry["hash"])
            # The record key never moves: a keyed entry's key is immutable
            # identity and its stored display id is the historical label that
            # makes `relabelled` observable; a legacy display-id-keyed entry
            # keeps its stamp-time label for the same reason (docs/design/
            # keys.md §4 -- the id-remapping half of this function is gone).
            new_items[record_id] = new_entry
            if new_entry != entry:
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
) -> list[str]:
    """Carry matching hashes forward in every legacy or key-keyed seal file.

    Only the hash moves: a §5 seal is keyed by immutable identity and keeps
    its stamp-time display label, and a legacy display-id-keyed entry keeps
    its stamp-time key for the same reason (docs/design/keys.md §4 -- the
    id-remapping half of this function is gone).
    """
    updated: list[str] = []
    live_keys = {item.key for item in project.local_items if item.key}
    boards = {""} | set(project.boards)
    for board in sorted(boards):
        path = seal_mod.seal_path(project, board)
        if not os.path.isfile(path):
            continue
        seals = seal_mod.load_seals(project, board)
        changed = False
        new_seals = dict(seals)
        for old_id, old_hash in old_hashes.items():
            item = project.item_by_id(old_id)
            found = seal_mod._find_seal(new_seals, item, live_keys)
            if found is None:
                continue
            record_id, value, recorded, _hash_format = found
            if recorded != old_hash:
                continue
            new_hash = new_hashes.get(old_id, recorded)
            new_value = seal_mod._with_seal_hash(value, new_hash, hash_format=build_mod.HASH_FORMAT)
            new_seals[record_id] = new_value
            if new_value != value:
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
    """Rewrite refdes-project.yaml's own `standard: {..., version: N, ...}` in
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
    config_path = os.path.join(project_root, "refdes-project.yaml")
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
