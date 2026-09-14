"""Maintain structured links in the `DISPLAY-ID@key` composite form.

An author writes exactly what they write today -- `satisfies: [REQ-001]`.
The tool expands it in place to `satisfies: [REQ-001@k7f3m2q9x4a]` when the
target has a key. Resolution (build.resolve_link_target) uses only the key
half.

The display half is readable, tool-maintained context rather than identity.
When the keyed target is renamed, the next writable load refreshes a stale
display half unless it now names a different live item. That collision is
left untouched and warned about because it is the signature of a crossed
merge. Unknown keys are also left untouched for build.resolve_links() to
report; neither case ever falls back to the display half.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import parse as parse_mod
from .model import Item, Project

if TYPE_CHECKING:
    from .revise import FileRewrite

# A structured-link target token, either a bare display id or a composite.
# Matching is deliberately confined to parsed link fields by the write-back
# helpers below, so prose references and unrelated scalar fields are never
# candidates. The optional key half lets expansion and display-half refresh
# share exactly the same source-preserving rewrite path.
_LINK_TOKEN_RE = re.compile(
    r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+(?:@[0-9a-z]+)?\b"
)


def _field_or_link_line_re(key: str) -> re.Pattern:
    return re.compile(rf"^(\s*(?:-\s+)?){re.escape(key)}:(.*)$")


_SEQ_ENTRY_RE = re.compile(r"^(\s*)-(\s+)(\S.*?)(\s*)$")


def _item_spans(rel: str, lines: list[str], items: list[Item]) -> list[tuple[Item, int, int]]:
    """(item, start, end) 0-indexed half-open line ranges bounding where each
    item's own fields live -- narrow enough that a rewrite can never bleed
    into a neighbouring item, or -- markdown only -- into prose after the
    closing fence. `items` must be *every* item in this file, not just the
    ones being rewritten, or a skipped item's span would wrongly swallow
    whatever comes after it.

    The same technique revise.py's own `_item_spans` uses for prefix
    rewriting, reimplemented here rather than imported: this module has no
    dependency on revise.py, by design (docs/design/keys.md's later layers,
    including revise.py's own retirement, are explicitly out of scope for
    this one).
    """
    ordered = sorted(items, key=lambda i: i.source_line)
    spans: list[tuple[Item, int, int]] = []
    if rel.endswith(".md"):
        fence_lines = [i for i, line in enumerate(lines) if parse_mod.FENCE_RE.match(line)]
        for item in ordered:
            start = item.source_line - 1
            close = next((f for f in fence_lines if f > start - 1), len(lines))
            spans.append((item, start, close))
    else:
        for idx, item in enumerate(ordered):
            start = item.source_line - 1
            end = ordered[idx + 1].source_line - 1 if idx + 1 < len(ordered) else len(lines)
            spans.append((item, start, end))
    return spans


def _rewrite_tokens(text: str, replacements: dict[str, str]) -> tuple[str, set[str]]:
    """Apply exact target replacements within one known link value."""
    applied: set[str] = set()

    def _sub(mo: re.Match) -> str:
        old = mo.group(0)
        new = replacements.get(old)
        if new is None:
            return old
        applied.add(old)
        return new

    return _LINK_TOKEN_RE.sub(_sub, text), applied


def _rewrite_block_sequence(
    out: list[str], start: int, limit: int, key_indent: int, replacements: dict[str, str]
) -> set[str]:
    """Rewrite the `- VALUE` entries of a block-style link sequence."""
    applied: set[str] = set()
    for i in range(start, limit):
        line = out[i]
        if not line.strip():
            continue
        m = _SEQ_ENTRY_RE.match(line)
        if m is None or len(m.group(1)) < key_indent:
            return applied
        indent, sep, value, trail = m.groups()
        new_value, changed = _rewrite_tokens(value, replacements)
        applied |= changed
        if new_value != value:
            out[i] = f"{indent}-{sep}{new_value}{trail}"
    return applied


def _flow_value_end(line: str, start: int) -> int:
    """End of a value in a one-line flow mapping, respecting nested syntax."""
    depth = 0
    quote = ""
    escaped = False
    for i in range(start, len(line)):
        ch = line[i]
        if quote:
            if quote == '"' and ch == "\\" and not escaped:
                escaped = True
                continue
            if ch == quote and not escaped:
                quote = ""
            escaped = False
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            if depth == 0:
                return i
            depth -= 1
        elif ch == "," and depth == 0:
            return i
    return len(line)


def _rewrite_flow_mapping_field(
    line: str, key: str, replacements: dict[str, str]
) -> tuple[str, set[str]]:
    """Rewrite one field inside a one-line item/defaults flow mapping."""
    brace = line.find("{")
    if brace < 0:
        return line, set()
    prefix = line[:brace]
    if not (
        re.fullmatch(r"\s*-\s*", prefix)
        or re.fullmatch(r"\s*defaults:\s*", prefix)
    ):
        return line, set()

    field_re = re.compile(rf"(^|[{{,])(\s*){re.escape(key)}\s*:")
    match = field_re.search(line, brace)
    if match is None:
        return line, set()
    value_start = match.end()
    value_end = _flow_value_end(line, value_start)
    new_value, applied = _rewrite_tokens(line[value_start:value_end], replacements)
    if not applied:
        return line, set()
    return line[:value_start] + new_value + line[value_end:], applied


def _rewrite_link_field(
    out: list[str], start: int, end: int, key: str, replacements: dict[str, str]
) -> set[str]:
    """Rewrite one named link field in a bounded item or defaults span."""
    limit = min(end, len(out))
    direct_re = _field_or_link_line_re(key)
    for i in range(max(0, start), limit):
        match = direct_re.match(out[i])
        if match:
            indent, rest = match.groups()
            if not rest.strip():
                return _rewrite_block_sequence(out, i + 1, limit, len(indent), replacements)
            new_rest, applied = _rewrite_tokens(rest, replacements)
            if applied:
                out[i] = f"{indent}{key}:{new_rest}"
            return applied

        new_line, applied = _rewrite_flow_mapping_field(out[i], key, replacements)
        if applied:
            out[i] = new_line
            return applied
    return set()


def _rewrite_item_links(
    out: list[str], start: int, end: int, item: Item, replacements: dict[str, str]
) -> set[str]:
    """Rewrite an item's own (non-defaulted) structured-link targets."""
    applied: set[str] = set()
    for key_name in item.links:
        if key_name in item.inherited_fields:
            continue
        applied |= _rewrite_link_field(out, start, end, key_name, replacements)
    return applied


def _rewrite_check_targets(
    out: list[str], start: int, end: int, replacements: dict[str, str]
) -> set[str]:
    """Rewrite every `against:` value within an item's `checks:` entries.

    Unlike a named link field, which appears at most once per item,
    `checks:` can hold several entries and each has its own `against:` --
    so every matching line in the span is rewritten, not just the first
    (docs/design/keys.md's "checks: against:" gap). Both shapes an entry
    can take are handled with the same helpers link fields already use:
    `- value: X` / `  against: Y` (direct field line) and one-line
    `- {value: X, against: Y}` (flow mapping, via _rewrite_flow_mapping_field
    -- its `- {...}` prefix check already matches a checks entry exactly the
    way it matches an item written in flow style).
    """
    limit = min(end, len(out))
    against_re = _field_or_link_line_re("against")
    applied: set[str] = set()
    for i in range(max(0, start), limit):
        match = against_re.match(out[i])
        if match:
            indent, rest = match.groups()
            if not rest.strip():
                continue  # `against:` is always a single scalar target
            new_rest, hit = _rewrite_tokens(rest, replacements)
            if hit:
                out[i] = f"{indent}against:{new_rest}"
            applied |= hit
            continue
        new_line, hit = _rewrite_flow_mapping_field(out[i], "against", replacements)
        if hit:
            out[i] = new_line
            applied |= hit
    return applied


@dataclass
class LinkExpansionPlan:
    rewrites: list[tuple[Item, str, str, str]] = field(default_factory=list)
    files: list[FileRewrite] = field(default_factory=list)
    expansion_count: int = 0
    remaining: int = 0


def _planned_target(
    project: Project, by_key: dict[str, Item], pointer: str, item: Item, target: str
) -> str | None:
    """The rewritten form of one reference target, or ``None`` if it needs no
    rewrite right now. The three §3 refresh cases (docs/design/keys.md),
    shared between plan_expansion (structured links) and
    plan_check_expansion (`checks: against:`) so the rule can't drift
    between the two:

    - Bare, and the target has a key: expand to the composite.
    - Composite, key resolves, display half already current: nothing to do.
    - Composite, key resolves, display half stale and now names a
      *different* live item: refuse and warn -- the crossed-reference
      signature of a bad merge, named with ``pointer`` (e.g. "refines" or
      "check against").
    - Composite, key resolves, display half stale and names nothing live
      (the ordinary rename), or the target is bare with no key yet, or the
      key doesn't resolve at all: handled by the two branches above --
      either expanded, refreshed, or left untouched respectively.
    """
    if "@" not in target:
        resolved = project.item_by_id(target)
        if resolved is None or not resolved.key:
            return None
        return f"{target}@{resolved.key}"

    old_display, _, key = target.partition("@")
    resolved = by_key.get(key)
    if resolved is None or old_display == resolved.id:
        return None
    other = project.item_by_id(old_display)
    if other is not None and other is not resolved and old_display not in resolved.former_ids:
        project.warn(
            f"{pointer} references {target!r}, but that key is "
            f"{resolved.id} and {old_display} is a different live "
            "item. Refusing to refresh the label until you confirm "
            "which was meant.",
            file=item.source_file,
            line=item.source_line,
            item_id=item.id,
        )
        return None
    return f"{resolved.id}@{key}"


def plan_expansion(
    project: Project,
    source_texts: dict[str, str] | None = None,
) -> LinkExpansionPlan:
    """Plan composite expansion and stale-label refresh without writing."""
    from .revise import FileRewrite

    candidates: list[tuple[Item, str, str, str]] = []
    replacements_by_item: dict[int, dict[str, str]] = defaultdict(dict)
    by_key = {item.key: item for item in project.items.values() if item.key}
    expansion_count = 0

    for item in project.local_items:
        for link_name, targets in item.links.items():
            for target in targets:
                new_target = _planned_target(project, by_key, link_name, item, target)
                if new_target is None:
                    continue
                if "@" not in target:
                    expansion_count += 1

                candidates.append((item, link_name, target, new_target))
                replacements_by_item[id(item)][target] = new_target

    plan = LinkExpansionPlan(expansion_count=expansion_count)
    if not candidates:
        return plan

    files_touched = sorted({item.source_file for item, *_ in candidates})
    applied_by_item: dict[int, set[str]] = defaultdict(set)
    for rel in files_touched:
        path = os.path.join(project.root, rel)
        if source_texts is not None and rel in source_texts:
            text = source_texts[rel]
        else:
            with open(path, "r", encoding="utf-8", newline="") as fh:
                text = fh.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()

        # Every item in this file, not just the ones being rewritten:
        # _item_spans needs the full set to bound each span correctly.
        file_items = [i for i in project.local_items if i.source_file == rel]
        for item, start, end in _item_spans(rel, lines, file_items):
            repl = replacements_by_item.get(id(item))
            if repl:
                applied_by_item[id(item)] |= _rewrite_item_links(
                    lines, start, end, item, repl
                )

        # A link inherited from file defaults has one physical spelling shared
        # by every inheriting item. Rewrite that spelling once, then attribute
        # the applied targets to each item whose parsed links came from it.
        defaults_groups: dict[tuple[int, str], list[Item]] = defaultdict(list)
        for item in file_items:
            if item.defaults_line is None or id(item) not in replacements_by_item:
                continue
            for link_name in item.links:
                if link_name in item.inherited_fields:
                    defaults_groups[(item.defaults_line, link_name)].append(item)

        first_item = min((item.source_line - 1 for item in file_items), default=len(lines))
        for (defaults_line, link_name), inheritors in defaults_groups.items():
            combined: dict[str, str] = {}
            for item in inheritors:
                combined.update(replacements_by_item[id(item)])
            applied = _rewrite_link_field(
                lines, defaults_line - 1, first_item, link_name, combined
            )
            for item in inheritors:
                own_targets = replacements_by_item[id(item)]
                applied_by_item[id(item)] |= applied & own_targets.keys()

        after = newline.join(lines) + newline
        if after != text:
            plan.files.append(FileRewrite(path=path, rel=rel, before=text, after=after))

    plan.rewrites = [
        (item, link_name, old, new)
        for item, link_name, old, new in candidates
        if old in applied_by_item.get(id(item), ())
    ]
    written_expansions = sum(
        1 for _item, _name, old, _new in plan.rewrites if "@" not in old
    )
    plan.remaining = expansion_count - written_expansions
    return plan


def expand_missing(project: Project, write: bool = True) -> list[tuple[Item, str, str, str]]:
    """Expand bare link targets and refresh stale composite display halves.

    Both operations use the same source-preserving write-back. Returns
    ``(item, link_name, old_target, new_target)`` for every target actually
    rewritten.

    A composite's key half is immutable. If it resolves and its display half
    is stale, the display text is refreshed unless that old text is now the
    id of a different live item. That crossed-reference signature is warned
    about and left untouched. An unknown key is likewise untouched here so
    build.resolve_links() can report the Layer-3 error.

    Must run after keys.mint_missing() in the same load (cli._load()) because
    a bare target needs a durable key before it can be expanded. Bare targets
    that are dangling, external and keyless, or whose minting failed remain
    fully usable under the existing display-id resolution rule.
    """
    plan = plan_expansion(project)
    if not plan.rewrites:
        return []
    if not write:
        if plan.expansion_count:
            _report_missing(project, plan.expansion_count)
        return []

    from .revise import write_rewrites

    write_rewrites(plan.files)
    replacements_by_item: dict[int, dict[str, str]] = defaultdict(dict)
    for item, _link_name, old, new in plan.rewrites:
        replacements_by_item[id(item)][old] = new
    for item in project.local_items:
        replacements = replacements_by_item.get(id(item))
        if not replacements:
            continue
        for link_name, targets in item.links.items():
            item.links[link_name] = [replacements.get(target, target) for target in targets]

    if plan.remaining:
        _report_missing(project, plan.remaining)
    return plan.rewrites


def _report_missing(project: Project, count: int) -> None:
    """One project-level info line, not one per reference -- mirrors
    keys._report_missing's own reasoning (docs/design/keys.md §2): under
    `--no-write` this is the expected, correct state, not a problem."""
    noun = "reference has" if count == 1 else "references have"
    project.info(
        f"{count} link {noun} not been expanded to the composite form yet; "
        "the next writable command will expand them. Run without --no-write, "
        "or see docs/design/keys.md."
    )


# --------------------------------------------------- checks: against: (docs/design/keys.md)


def plan_check_expansion(
    project: Project,
    source_texts: dict[str, str] | None = None,
) -> LinkExpansionPlan:
    """`checks: against:` counterpart of plan_expansion(). `against:` isn't a
    `links:` reference -- it's a field entry inside `checks:` -- but it names
    an item the same way a structured link target does, so it gets the same
    treatment: reuses _planned_target for the §3 refresh rule and
    _item_spans/_rewrite_check_targets for the source-preserving write-back,
    rather than a second implementation of either.
    """
    from .revise import FileRewrite

    candidates: list[tuple[Item, str, str, str]] = []
    replacements_by_item: dict[int, dict[str, str]] = defaultdict(dict)
    by_key = {item.key: item for item in project.items.values() if item.key}
    expansion_count = 0

    for item in project.local_items:
        if "checks" in item.inherited_fields:
            continue  # lives in file defaults, not this item's own span
        entries = item.fields.get("checks")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or "against" not in entry:
                continue
            target = str(entry["against"])
            new_target = _planned_target(project, by_key, "check against", item, target)
            if new_target is None:
                continue
            if "@" not in target:
                expansion_count += 1
            candidates.append((item, "against", target, new_target))
            replacements_by_item[id(item)][target] = new_target

    plan = LinkExpansionPlan(expansion_count=expansion_count)
    if not candidates:
        return plan

    files_touched = sorted({item.source_file for item, *_ in candidates})
    applied_by_item: dict[int, set[str]] = defaultdict(set)
    for rel in files_touched:
        path = os.path.join(project.root, rel)
        if source_texts is not None and rel in source_texts:
            text = source_texts[rel]
        else:
            with open(path, "r", encoding="utf-8", newline="") as fh:
                text = fh.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()

        file_items = [i for i in project.local_items if i.source_file == rel]
        for item, start, end in _item_spans(rel, lines, file_items):
            repl = replacements_by_item.get(id(item))
            if repl:
                applied_by_item[id(item)] |= _rewrite_check_targets(lines, start, end, repl)

        after = newline.join(lines) + newline
        if after != text:
            plan.files.append(FileRewrite(path=path, rel=rel, before=text, after=after))

    plan.rewrites = [
        (item, name, old, new)
        for item, name, old, new in candidates
        if old in applied_by_item.get(id(item), ())
    ]
    written_expansions = sum(
        1 for _item, _name, old, _new in plan.rewrites if "@" not in old
    )
    plan.remaining = expansion_count - written_expansions
    return plan


def expand_missing_checks(
    project: Project, write: bool = True
) -> list[tuple[Item, str, str, str]]:
    """Expand bare `checks: against:` targets and refresh stale composite
    display halves -- the `checks:` counterpart of expand_missing(), run on
    the same writable load path and gated by `--no-write` the same way
    (cli._load()). Returns ``(item, "against", old_target, new_target)`` for
    every target actually rewritten.

    Must run after keys.mint_missing() for the same reason expand_missing()
    must: a bare target needs a durable key before there is anything to
    expand into. Safe to run either before or after expand_missing() itself
    -- the two touch disjoint fields (`links` vs. `checks`) and never
    contend for the same source line.
    """
    plan = plan_check_expansion(project)
    if not plan.rewrites:
        return []
    if not write:
        if plan.expansion_count:
            _report_missing_checks(project, plan.expansion_count)
        return []

    from .revise import write_rewrites

    write_rewrites(plan.files)
    replacements_by_item: dict[int, dict[str, str]] = defaultdict(dict)
    for item, _name, old, new in plan.rewrites:
        replacements_by_item[id(item)][old] = new
    for item in project.local_items:
        replacements = replacements_by_item.get(id(item))
        if not replacements:
            continue
        entries = item.fields.get("checks")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            current = str(entry.get("against", ""))
            if current in replacements:
                entry["against"] = replacements[current]

    if plan.remaining:
        _report_missing_checks(project, plan.remaining)
    return plan.rewrites


def _report_missing_checks(project: Project, count: int) -> None:
    """`checks:` counterpart of _report_missing() -- see its own docstring."""
    noun = "reference has" if count == 1 else "references have"
    project.info(
        f"{count} check {noun} not been expanded to the composite form yet; "
        "the next writable command will expand them. Run without --no-write, "
        "or see docs/design/keys.md."
    )
