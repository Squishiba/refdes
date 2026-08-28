"""Expand-and-freeze link targets to the `DISPLAY-ID@key` composite form
(docs/design/keys.md §3), layer 2 of the surrogate-key design.

An author writes exactly what they write today -- `satisfies: [REQ-001]`.
The tool expands it in place to `satisfies: [REQ-001@k7f3m2q9x4b]` the first
time it sees a bare reference that resolves to a keyed item, the same way
`refdes id` already expands a bare-numeric `id: "042"` into a full id. Once
written, a composite is frozen: this module never touches one again, and
resolution (build.resolve_link_target) uses only the part after `@`.

This only ever *adds* the key half. It never rewrites the display half when
a target's own id later changes -- that "refresh, and one case that must not
be silent" mechanism (docs/design/keys.md §3) is a separate, more involved
piece (three cases, some of them diagnostic) and is not implemented here.
Until it exists, a stale display half is cosmetic only: resolution never
reads it.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

from . import parse as parse_mod
from .model import Item, Project

# A display-id-shaped token (same shape as ids.ID_RE / build.BARE_REF_RE),
# NOT immediately followed by '@' -- the negative lookahead is what keeps
# this from ever touching the display half of a target that is *already*
# composite. Without it, re-running expansion over a line that already reads
# `REQ-001@k7f3m2q9x4b` would match the bare "REQ-001" prefix of that very
# composite and corrupt it into `REQ-001@k7f3m2q9x4b@k7f3m2q9x4b`.
_LINK_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+\b(?!@)")


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


def _rewrite_block_sequence(
    out: list[str], start: int, limit: int, key_indent: int, replacements: dict[str, str]
) -> set[str]:
    """Rewrite the `- VALUE` entries of a block-style sequence beginning at
    `start`, in place. Ends at the first line that isn't an entry indented
    at least as deep as the key itself; a blank line inside the sequence is
    passed over, matching ordinary YAML.

    Returns the subset of `replacements`' keys actually found and rewritten
    -- see _rewrite_item_links's docstring for why the caller needs that,
    not just a bare success/failure.
    """
    applied: set[str] = set()

    def _sub(mo: re.Match) -> str:
        old = mo.group(0)
        new = replacements.get(old)
        if new is None:
            return old
        applied.add(old)
        return new

    for i in range(start, limit):
        line = out[i]
        if not line.strip():
            continue
        m = _SEQ_ENTRY_RE.match(line)
        if m is None or len(m.group(1)) < key_indent:
            return applied
        indent, sep, value, trail = m.groups()
        new_value = _LINK_TOKEN_RE.sub(_sub, value)
        if new_value != value:
            out[i] = f"{indent}-{sep}{new_value}{trail}"
    return applied


def _rewrite_item_links(
    out: list[str], start: int, end: int, item: Item, replacements: dict[str, str]
) -> set[str]:
    """Rewrite `item`'s own bare link-target tokens named in `replacements`
    (old text -> new composite text) within [start, end).

    Handles both YAML spellings a link value can take: same-line
    (`key: [A, B]` or `key: A`) and block-style (a bare `key:` with `- A`
    entries following it, indented deeper). Does NOT handle flow-style list
    entries (`- {id: ..., satisfies: [A]}`, everything on one line) --
    `_field_or_link_line_re` requires the link's own key name to open the
    line (after an optional leading `- `), which a flow-style entry's key
    never does (the entry's *id* opens it instead). Such a line is simply
    never matched, so it is left exactly as authored -- a bare reference,
    which stays fully resolvable (§2's resolution rule), just not yet
    composite-expanded. Bulk flow-style files (`- {id: ..., text: ...}`)
    rarely carry links in this project's own conventions, so this is judged
    an acceptable, honestly-scoped gap rather than a reason to build a
    second, flow-aware rewrite path for this first pass.

    Returns the subset of `replacements`' keys actually found and rewritten.
    This matters, not just for logging: expand_missing() must not claim (in
    its return value, or in item.links in memory) that a target was
    expanded when the line it lives on was never matched -- a candidate
    inside a flow-style entry is exactly that case, and claiming it anyway
    would leave the in-memory project silently disagreeing with what is
    actually on disk.
    """
    applied: set[str] = set()
    limit = min(end, len(out))
    for key_name in item.links:
        for i in range(start, limit):
            m = _field_or_link_line_re(key_name).match(out[i])
            if not m:
                continue
            indent, rest = m.groups()
            if rest.strip():
                def _sub(mo: re.Match) -> str:
                    old = mo.group(0)
                    new = replacements.get(old)
                    if new is None:
                        return old
                    applied.add(old)
                    return new

                new_rest = _LINK_TOKEN_RE.sub(_sub, rest)
                if new_rest != rest:
                    out[i] = f"{indent}{key_name}:{new_rest}"
            else:
                applied |= _rewrite_block_sequence(out, i + 1, limit, len(indent), replacements)
            break
    return applied


def expand_missing(project: Project, write: bool = True) -> list[tuple[Item, str, str, str]]:
    """Expand every local item's bare-display-id link targets that resolve
    to a keyed item into the frozen `DISPLAY-ID@key` composite, and persist
    the rewrite. Returns (item, link_name, old_target, new_target) for every
    target actually rewritten.

    Must run after keys.mint_missing() in the same load (cli._load()) --
    a target needs its own key before there's anything to expand into. A
    target that is still bare after this call is one of:

    - a dangling reference (resolve_links() reports this separately, as it
      always has -- expansion doesn't duplicate that diagnostic);
    - a reference to an *external* (imported) item -- imports never carry a
      key today (imports.py's payload doesn't export one), so a link into
      another project can never be composite-expanded yet. This is a real,
      known gap, not an oversight: closing it means adding `key` to the
      items.json export and import payload, which is a separate change with
      its own cross-project-collision considerations, not bundled in here;
    - a target whose own key-minting failed this run (rare -- see
      keys.mint_missing's own write-back-failure handling) or was skipped
      by `--no-write`;
    - already composite (frozen -- never touched again, see _LINK_TOKEN_RE);
    - inside a flow-style list entry (see _rewrite_item_links's docstring).

    None of these are errors here. §2's resolution rule keeps a bare
    reference fully working regardless of why it never got expanded.
    """
    rewrites: list[tuple[Item, str, str, str]] = []
    replacements_by_item: dict[int, dict[str, str]] = defaultdict(dict)
    for item in project.local_items:
        for link_name, targets in item.links.items():
            for target in targets:
                if "@" in target:
                    continue  # already composite -- frozen
                resolved = project.items.get(target)
                if resolved is None or not resolved.key:
                    continue
                new_target = f"{target}@{resolved.key}"
                rewrites.append((item, link_name, target, new_target))
                replacements_by_item[id(item)][target] = new_target

    if not rewrites:
        return []

    if not write:
        _report_missing(project, len(rewrites))
        return []

    files_touched = sorted({item.source_file for item, *_ in rewrites})
    applied_by_item: dict[int, set[str]] = {}
    for rel in files_touched:
        path = os.path.join(project.root, rel)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()

        # Every item in this file, not just the ones being rewritten --
        # _item_spans needs the full set to bound each span correctly.
        file_items = [i for i in project.local_items if i.source_file == rel]
        for item, start, end in _item_spans(rel, lines, file_items):
            repl = replacements_by_item.get(id(item))
            if repl:
                applied_by_item[id(item)] = _rewrite_item_links(lines, start, end, item, repl)

        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(newline.join(lines) + newline)

    # Only report/apply-in-memory what the write-back pass actually matched
    # on disk (applied_by_item) -- a candidate that fell through unmatched
    # (a flow-style entry, see _rewrite_item_links) must stay bare in both
    # places, or item.links in memory would silently disagree with the file.
    written = [
        (item, link_name, old, new)
        for item, link_name, old, new in rewrites
        if old in applied_by_item.get(id(item), ())
    ]

    for item in project.local_items:
        applied = applied_by_item.get(id(item))
        if not applied:
            continue
        repl = replacements_by_item[id(item)]
        for link_name, targets in item.links.items():
            item.links[link_name] = [repl[t] if t in applied else t for t in targets]

    still_missing = len(rewrites) - len(written)
    if still_missing:
        _report_missing(project, still_missing)

    return written


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
