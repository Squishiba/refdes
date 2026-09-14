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


@dataclass
class LinkExpansionPlan:
    rewrites: list[tuple[Item, str, str, str]] = field(default_factory=list)
    files: list[FileRewrite] = field(default_factory=list)
    expansion_count: int = 0
    remaining: int = 0


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
                if "@" not in target:
                    resolved = project.items.get(target)
                    if resolved is None or not resolved.key:
                        continue
                    new_target = f"{target}@{resolved.key}"
                    expansion_count += 1
                else:
                    old_display, _, key = target.partition("@")
                    resolved = by_key.get(key)
                    if resolved is None or old_display == resolved.id:
                        continue
                    other = project.items.get(old_display)
                    if (
                        other is not None
                        and other is not resolved
                        and old_display not in resolved.former_ids
                    ):
                        project.warn(
                            f"{link_name} references {target!r}, but that key is "
                            f"{resolved.id} and {old_display} is a different live "
                            "item. Refusing to refresh the label until you confirm "
                            "which was meant.",
                            file=item.source_file,
                            line=item.source_line,
                            item_id=item.id,
                        )
                        continue
                    new_target = f"{resolved.id}@{key}"

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
