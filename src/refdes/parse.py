"""Read source files into Items.

Two serializations, one object model:

  items/**/*.md    one or more items, each YAML front-matter + markdown body
                   (decisions, anything with a body, calcs, or options) --
                   see parse_markdown_file for the several-items-in-one-file rules
  items/**/*.yaml  a list of items sharing `defaults:` (bulk requirements)
"""

from __future__ import annotations

import difflib
import os
import re
from typing import Any

import yaml

from .model import ON_CHANGE_MODES, Item, Project

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
# A candidate fence line: `---` alone on its line.
FENCE_RE = re.compile(r"^---[ \t]*$")
# A YAML mapping key opening a line at column 0 -- what has to follow a `---` for it
# to be read as a new item's front-matter rather than a literal horizontal rule.
KEY_LINE_RE = re.compile(r"^[A-Za-z_][\w.-]*\s*:(\s|$)")
# `body` is the markdown body, not a field. In a .md file it is the text after the
# front-matter; in a list file it is a `body:` key, so a running log can be written
# as a list without one file per daily entry.
RESERVED = {"id", "type", "history", "body", "former_ids"}
# Reserved, but only when the item's own type does not already declare a field of
# the same name -- so a schema that predates one of these keys keeps working
# unchanged instead of having the field silently shadowed.
OVERRIDABLE = {"prefix", "board", "workspace"}

# Fields renamed by a standard-library version bump, keyed by (type name, old
# key) -> new key. A plain rename would otherwise surface as an unknown-field
# warning on the old key plus a missing-required error on the new one --
# accurate, but a miserable way to discover that the fix is "rename this key"
# (finding 4: hardware v1's constraint.title -> v2's constraint.text). Scoped
# to the type name alone, so it also flags a hand-rolled schema that happens
# to name a type `constraint` and drop `title` for unrelated reasons -- an
# acceptable false positive given how narrowly this table is meant to stay.
_RENAMED_FIELDS: dict[tuple[str, str], str] = {
    ("constraint", "title"): "text",
}

# Types renamed by a standard-library version bump, old name -> new name
# (hardware v2's `constraint` -> v3's `bound`). The same reasoning as
# _RENAMED_FIELDS one level up: without this, moving the pin forward by hand
# reports a bare "unknown type 'constraint'." on every item in the project,
# and difflib's did-you-mean is no help at all here -- `constraint` and
# `bound` share almost no characters, so no suggestion is offered. Only ever
# consulted when the *new* name is a real type in the merged schema, so a
# hand-rolled project that has never heard of either name can't be told to
# rename something into a type it doesn't have.
_RENAMED_TYPES: dict[str, str] = {
    "constraint": "bound",
}


class _LineLoader(yaml.SafeLoader):
    """SafeLoader that tags each mapping with the source line of its first key."""


def _construct_mapping(loader: _LineLoader, node: yaml.MappingNode) -> dict:
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=True)
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _strip_lines(obj: Any) -> Any:
    """Remove the __line__ bookkeeping key from nested structures."""
    if isinstance(obj, dict):
        return {k: _strip_lines(v) for k, v in obj.items() if k != "__line__"}
    if isinstance(obj, list):
        return [_strip_lines(v) for v in obj]
    return obj


def _relpath(project: Project, path: str) -> str:
    try:
        return os.path.relpath(path, project.root).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


# Substrings PyYAML's own exception carries when a bare '>'/'>=' is misread as
# a folded-block-scalar indicator rather than a comparison -- checked with
# `or` (either is sufficient) because the exact wording of `.problem` differs
# by what immediately follows the '>' (see finding 13's own repro: '>= ' fails
# with "chomping or indentation indicators", a bare '> 9' fails with "expected
# a comment or a line break" instead), while `.context` stays this one string
# either way.
_CHOMPING_PROBLEM = "chomping or indentation indicators"
_BLOCK_SCALAR_CONTEXT = "while scanning a block scalar"


def _yaml_error_report(exc: yaml.YAMLError, lines: list[str], offset: int) -> tuple[str, int]:
    """(message, line) for a YAMLError raised while parsing part of a file.

    `line` is the real, 1-indexed source line the exception's own mark names,
    falling back to 1 only when no mark is set at all -- not a blanket
    default, which was the actual bug (finding 13's real point: this was
    wrong for every malformed YAML file, not just the '>' gotcha). `lines` is
    the *whole file's* lines (0-indexed); `offset` is how many of them
    precede the text actually handed to the YAML parser (0 for a full-file
    parse; the first content line's index for a slice, e.g. front matter),
    since a mark's own `.line` is relative to whatever text was parsed, not
    the file it came from.

    `message` adds a targeted hint for the single most common way this fails:
    a bare '>' or '>=' value, which YAML reads as a folded-block-scalar
    indicator rather than a comparison. Detection is scoped to the source
    line's actual content at the failure point, not to any particular field
    name -- the same gotcha hits any field, not just `limit:`.
    """
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return str(exc), 1

    line = offset + mark.line + 1
    message = str(exc)

    is_block_scalar_failure = _CHOMPING_PROBLEM in (
        getattr(exc, "problem", None) or ""
    ) or _BLOCK_SCALAR_CONTEXT in (getattr(exc, "context", None) or "")
    if is_block_scalar_failure:
        # context_mark, when present, points at the '>' itself; problem_mark
        # points at whatever character broke the scan just after it (the '='
        # in '>=', for instance) -- prefer the more precise one.
        pointer = getattr(exc, "context_mark", None) or mark
        real_idx = offset + pointer.line
        source_line = lines[real_idx] if 0 <= real_idx < len(lines) else ""
        value = source_line[pointer.column :]
        if value.startswith(">"):
            operator = ">=" if value.startswith(">=") else ">"
            message += (
                f" -- a value starting with {operator!r} needs quotes here: YAML "
                f"reads a bare '>' as the start of a block scalar, not a "
                f'comparison. Try "{value.strip()}".'
            )

    return message, line


def _suggest(name: str, known: list[str]) -> str:
    close = difflib.get_close_matches(name, known, n=1, cutoff=0.6)
    return f" Did you mean {close[0]!r}?" if close else ""


def _only_key(mapping: dict[str, Any], key: str) -> bool:
    """True if `mapping`'s one real key (ignoring line bookkeeping) is `key`
    -- the same shape test that already distinguished a `defaults:`-only
    block from an item, generalized so `section:` markers use it too."""
    return {k for k in mapping if k != "__line__"} == {key}


def _resolve_section_marker(
    project: Project, marker: dict[str, Any], default_type: Any, rel: str, line: int
) -> str | None:
    """`marker` is already known to be a `section:`-only block/entry (finding
    6, built instead of the type-keyed `items:` mapping: same spelling in
    both formats, a bare fenced block in Markdown, a single-key list entry in
    YAML, since neither format's structure lets the other spelling work in
    both). Validate its value against a `defaults: {type: ...}` this file may
    also declare and return the asserted type, or None if the marker is
    malformed or conflicts (both already reported as errors).

    A section *asserts* rather than defaults -- unlike an ordinary
    `defaults: {type: X}`, which an item is always free to override, a
    section states what its items are. A file-level default that disagrees
    with an active section isn't a fallback being overridden, it's the file
    contradicting itself, so it's a hard error naming both values rather than
    a silent pick-a-winner.
    """
    value = marker.get("section")
    if not isinstance(value, str) or not value:
        project.error("'section:' must name a type (a non-empty string)", file=rel, line=line)
        return None
    if default_type is not None and default_type != value:
        project.error(
            f"'section: {value}' conflicts with this file's own "
            f"'defaults: {{type: {default_type}}}' -- a section asserts what "
            f"its items are; reconcile the two rather than leaving them to "
            f"silently disagree. Drop 'type:' from defaults:, or make it "
            f"match.",
            file=rel, line=line,
        )
        return None
    return value


def _apply_section(
    project: Project,
    merged: dict[str, Any],
    section_type: str | None,
    section_line: int | None,
    rel: str,
    line: int,
) -> bool:
    """If a section is active, enforce that `merged` (an item's fields,
    already layered over `defaults:`, before `_build_item` sees them) agrees
    with its asserted type, then stamp that type in. False means this item
    contradicts its enclosing section and was already reported -- the caller
    must skip it rather than build it. An item that omits `type:` entirely
    (the normal case: that's the whole point of a section) always agrees by
    construction; an item that restates the same type agrees too and is left
    alone. Only an item naming a *different* type is a conflict, since a
    section asserts rather than defaults (see _resolve_section_marker)."""
    if section_type is None:
        return True
    item_type = merged.get("type")
    if item_type is not None and item_type != section_type:
        project.error(
            f"item declares type {item_type!r} but sits inside a "
            f"'section: {section_type}' block (opened at line {section_line}) "
            f"-- a section asserts its items' type; this one disagrees. Move "
            f"the item out of the section, or fix whichever of the two is "
            f"wrong.",
            file=rel, line=line,
        )
        return False
    merged["type"] = section_type
    return True


def _resolve_id_value(
    project: Project, raw_id: Any, rel: str, line: int
) -> tuple[str, str, bool]:
    """Split a raw `id:` value into (item_id, numeric_id_hint, rejected).

    Four shapes:

    - absent/blank -- `item_id`/`numeric_id_hint` both "", `rejected` False:
      the item is pending, same as always.
    - a full id (`REQ-001`, or anything else that isn't purely digits) --
      `item_id` is that string, the other two stay "" / False.
    - a bare number (finding 8 Part 1: `id: 001`, meant to expand to
      `REQ-001` once `refdes id` sees a prefix to attach) -- `item_id` stays
      "" (still pending) and `numeric_id_hint` carries the literal digit
      string.
    - a rejected number (see below) -- `item_id` stays "" but `rejected` is
      True, which keeps it *out* of `project.pending`: this item's `id:` is
      not safely blank, so `refdes id` must never treat it as free to
      allocate into. The already-reported error is the only diagnostic;
      nothing here is a placeholder waiting for the allocator.

    The bare-number case only accepts a *string* of digits, never an int:
    YAML resolves an unquoted leading zero as octal (`id: 042` parses to the
    integer 34, not 42), so trusting `raw_id` as a number here would risk
    silently freezing the wrong id forever -- the exact class of harm this
    finding exists to prevent. An unquoted number is refused with a
    diagnostic naming the fix (quote it) rather than guessed at.
    """
    if isinstance(raw_id, bool):
        return "", "", False  # YAML's `id: yes`/`no` -- not a number, not a valid id either way
    if isinstance(raw_id, (int, float)):
        # Deliberately not naming raw_id as "what you typed": by the time
        # YAML hands it here, an unquoted leading zero has already been
        # silently reinterpreted (042 -> 34), so raw_id may already be wrong
        # -- there's nothing left to recover it from.
        project.error(
            "id: is an unquoted number -- YAML reads a leading zero as octal "
            "(042 silently becomes 34, not 42), so trusting it here risks "
            "freezing the wrong id forever. Quote the value as a string "
            '(id: "042") so the digits are used literally, or write the '
            "complete id by hand.",
            file=rel, line=line,
        )
        return "", "", True
    if not raw_id:
        return "", "", False
    text = str(raw_id).strip()
    if text.isdigit():
        return "", text, False
    return text, "", False


def _build_item(
    project: Project,
    raw: dict[str, Any],
    rel: str,
    line: int,
    body: str = "",
) -> Item | None:
    type_name = raw.get("type")
    if not type_name:
        project.error("item has no 'type'", file=rel, line=line)
        return None
    spec = project.types.get(str(type_name))
    if spec is None:
        preset_name = project.preset_provided_types.get(str(type_name))
        if preset_name:
            project.error(
                f"unknown type {type_name!r} -- it was provided by the "
                f"{preset_name!r} preset, which is not listed under "
                f"standard.presets:. Add it back, or migrate this item to a "
                f"declared type.",
                file=rel, line=line,
            )
        else:
            renamed_to = _RENAMED_TYPES.get(str(type_name))
            if renamed_to is not None and renamed_to in project.types:
                if project.standard_base and project.standard_version is not None:
                    where = f"{project.standard_base}@{project.standard_version}"
                    fix = (
                        f"If you moved standard.version: forward by hand, put it "
                        f"back and run 'refdes standard upgrade --to "
                        f"{project.standard_version}' instead -- that rewrites every "
                        f"item, and the ids too, since the prefix moved with it."
                    )
                else:
                    where = "this project's schema"
                    fix = "Rename it here, or see 'refdes revise' to rewrite the project."
                project.error(
                    f"unknown type {type_name!r} -- it is now {renamed_to!r} in "
                    f"{where}. {fix}",
                    file=rel,
                    line=line,
                )
            else:
                project.error(
                    f"unknown type {type_name!r}.{_suggest(str(type_name), list(project.types))}",
                    file=rel,
                    line=line,
                )
        return None

    item_id, numeric_id_hint, id_rejected = _resolve_id_value(project, raw.get("id"), rel, line)
    item = Item(
        id=item_id,
        type=spec.name,
        source_file=rel,
        source_line=line,
        body=body,
        numeric_id_hint=numeric_id_hint,
        id_rejected=id_rejected,
    )

    if not item.body and raw.get("body"):
        item.body = str(raw["body"])

    former_ids = raw.get("former_ids")
    if former_ids:
        item.former_ids = [str(v) for v in (former_ids if isinstance(former_ids, list) else [former_ids]) if v]

    history = raw.get("history")
    if isinstance(history, str):
        if history not in ON_CHANGE_MODES:
            project.error(
                f"history: {history!r} must be one of {list(ON_CHANGE_MODES)}",
                file=rel, line=line, item_id=item.id,
            )
        else:
            item.history = {"mode": history}
    elif isinstance(history, dict):
        item.history = _strip_lines(history)
        if item.history.get("fields") and not item.history.get("reason"):
            project.warn(
                "item-level history override has no 'reason'; suppression should be "
                "self-documenting",
                file=rel, line=line, item_id=item.id,
            )

    known_keys = set(spec.fields) | set(spec.links) | RESERVED | OVERRIDABLE
    for key, value in raw.items():
        if key == "__line__" or key in RESERVED:
            continue
        if key in OVERRIDABLE and key not in spec.fields:
            if key == "prefix" and value:
                item.prefix_hint = str(value)
            elif key == "board" and value:
                item.board_hint = str(value)
            elif key == "workspace" and value:
                item.workspace_hint = str(value)
            continue
        if key in spec.links:
            targets = value if isinstance(value, list) else [value]
            item.links[key] = [str(t) for t in targets if t]
        elif key in spec.fields:
            item.fields[key] = _strip_lines(value)
        elif (spec.name, key) in _RENAMED_FIELDS:
            new_key = _RENAMED_FIELDS[(spec.name, key)]
            project.error(
                f"'{spec.name}.{key}' is now '{spec.name}.{new_key}' -- rename this "
                f"key in the source file. Its value is used for {new_key!r} in this "
                f"build so the rest of it doesn't also report a missing required "
                f"field.",
                file=rel, line=line, item_id=item.id or "?",
            )
            item.fields[new_key] = _strip_lines(value)
        else:
            # A typo'd link name (`sattisfies:` for `satisfies:`) doesn't just lose a
            # field -- it drops a traceability edge, so it must fail the build rather
            # than pass with a warning that's easy to miss.
            link_match = difflib.get_close_matches(key, sorted(spec.links), n=1, cutoff=0.6)
            preset_name = project.preset_provided_links.get(key)
            if preset_name and key not in project.link_types:
                project.error(
                    f"unknown field {key!r} on {spec.label.lower()} -- it was "
                    f"provided by the {preset_name!r} preset, which is not listed "
                    f"under standard.presets:. Add it back, or remove this link.",
                    file=rel, line=line, item_id=item.id or "?",
                )
            elif link_match:
                project.error(
                    f"unknown field {key!r} on {spec.label.lower()} -- did you mean "
                    f"the link {link_match[0]!r}? A misspelled link name silently "
                    f"drops the edge instead of erroring.",
                    file=rel, line=line, item_id=item.id or "?",
                )
            else:
                project.warn(
                    f"unknown field {key!r} on {spec.label.lower()}."
                    f"{_suggest(key, sorted(known_keys))}",
                    file=rel, line=line, item_id=item.id or "?",
                )
            item.fields[key] = _strip_lines(value)

    for fname, fspec in spec.fields.items():
        if fname not in item.fields:
            if fspec.default is not None:
                item.fields[fname] = fspec.default
        elif item.fields[fname] is None and fspec.default is not None:
            # A bare `key:` with nothing after the colon is YAML null, not absence --
            # left alone, it would look "already resolved" to validate_items() and skip
            # both the default and the enum/limit/etc. check right below it, silently
            # dropping whatever the author meant to write. Coalesce it into absent so
            # it gets the same default an omitted key would, and say so: unlike an
            # omitted key, an explicit null was something the author typed, so it's
            # worth a warning rather than a silent correction.
            item.fields[fname] = fspec.default
            project.warn(
                f"{fname!r} was written as an explicit null (a bare {fname}: with no "
                f"value) -- treating it as absent and using the default {fspec.default!r} "
                f"instead of leaving it unset and unvalidated.",
                file=rel, line=line, item_id=item.id or "?",
            )

    return item


def _yaml_mapping(text: str) -> dict | None:
    """Parse `text` as YAML, returning it only if it is a mapping (empty -> {})."""
    parsed = yaml.load(text, Loader=_LineLoader)
    if parsed is None:
        return {}
    return parsed if isinstance(parsed, dict) else None


def parse_markdown_file(project: Project, path: str) -> list[Item]:
    """Read one or more `---`-fenced item documents from a single .md file.

    A file must open with `---`, YAML, `---` -- exactly today's single-item form,
    matched the same way so a plain file is unaffected byte-for-byte. After that,
    a further `---` only starts a new item if the line right after it looks like a
    YAML key, a closing `---` exists later, and the text between actually parses as
    a YAML mapping. Failing any of those, it is left alone as a literal horizontal
    rule inside the previous item's body -- which is what makes a today-style file
    with a `---` in its prose keep working unmigrated.

    If the first block's only key is `defaults:`, it is not an item -- its mapping
    is merged under every item that follows, the same way `defaults:` works in a
    list file. A `defaults:`-shaped block anywhere else in the file is an error,
    not a second application point (see the error message inline below).

    A block whose only key is `section:` (finding 6) is likewise not an item --
    it asserts a type for every item after it until the next section or end of
    file, the Markdown spelling of a YAML list file's `- section: <type>` entry.
    """
    rel = _relpath(project, path)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    lines = text.split("\n")

    fence_idx = [i for i, l in enumerate(lines) if FENCE_RE.match(l)]
    if len(fence_idx) < 2 or fence_idx[0] != 0:
        project.error("no YAML front-matter (file must start with '---')", file=rel, line=1)
        return []

    close0 = fence_idx[1]
    head_text = "\n".join(lines[1:close0])
    try:
        parsed0 = _yaml_mapping(head_text)
    except yaml.YAMLError as exc:
        message, err_line = _yaml_error_report(exc, lines, offset=1)
        project.error(f"invalid YAML front-matter: {message}", file=rel, line=err_line)
        return []
    if parsed0 is None:
        project.error("front-matter must be a mapping", file=rel, line=1)
        return []

    blocks: list[tuple[int, int, dict]] = [(0, close0, parsed0)]

    # Every remaining fence is independently a candidate to open the next item,
    # paired with whichever fence comes right after it -- including a fence that is
    # already serving as the previous item's close, which is what lets one `---`
    # between two back-to-back items do double duty as both. A fence with nothing
    # later to close it (the last one in the file) is never reachable as an opener
    # here, which is exactly "a closing fence exists later".
    for k in range(1, len(fence_idx) - 1):
        open_i = fence_idx[k]
        close_i = fence_idx[k + 1]
        next_line = lines[open_i + 1] if open_i + 1 < len(lines) else ""
        if not KEY_LINE_RE.match(next_line):
            continue
        # Past this point the block opens with a `key:` line, so it was meant
        # as an item -- a malformed one must be reported, never skipped. A
        # silent `continue` here dropped the whole item from the project with
        # a clean, zero-error build, and folded its body text into the
        # previous item's, which is the same class of harm as the later
        # `defaults:` block below (and strictly quieter: that one at least
        # produced a warning). The very first block already reports both of
        # these; every later one now reports them identically.
        try:
            parsed = _yaml_mapping("\n".join(lines[open_i + 1 : close_i]))
        except yaml.YAMLError as exc:
            message, err_line = _yaml_error_report(exc, lines, offset=open_i + 1)
            project.error(f"invalid YAML front-matter: {message}", file=rel, line=err_line)
            continue
        if parsed is None:
            project.error("front-matter must be a mapping", file=rel, line=open_i + 2)
            continue
        blocks.append((open_i, close_i, parsed))

    defaults: dict[str, Any] = {}
    start = 0
    first_keys = {k for k in blocks[0][2] if k != "__line__"}
    if first_keys == {"defaults"} and isinstance(blocks[0][2].get("defaults"), dict):
        defaults = _strip_lines(blocks[0][2]["defaults"])
        start = 1
    default_type = defaults.get("type")

    item_blocks = blocks[start:]
    if not item_blocks:
        project.error("file has no items after 'defaults:'", file=rel, line=1)
        return []

    # `---\nsection: <type>\n---` (finding 6): a marker block, not an item --
    # the Markdown spelling of the same thing `- section: <type>` is in a
    # YAML list file. Asserts the type for every item after it until the next
    # section or end of file; see _resolve_section_marker/_apply_section for
    # why this is stricter than `defaults:` rather than a second spelling of
    # it, and parse_list_file for the identical logic there.
    section_type: str | None = None
    section_line: int | None = None

    out: list[Item] = []
    for index, (open_i, close_i, parsed) in enumerate(item_blocks):
        line = open_i + 2
        body_end = item_blocks[index + 1][0] if index + 1 < len(item_blocks) else len(lines)

        if _only_key(parsed, "defaults"):
            # Only blocks[0] is ever read as file-wide defaults (above). One
            # anywhere else used to be silently misparsed as a malformed item
            # -- reporting "unknown field 'defaults'" on whatever type was
            # already active, then leaving every item after it wrongly typed
            # too, with nothing louder than that one warning to notice by.
            project.error(
                "'defaults:' only applies as the very first block in a file "
                "-- a later one here doesn't take effect. Use "
                "'section: <type>' to change what applies to the items that "
                "follow.",
                file=rel, line=line,
            )
            continue

        if _only_key(parsed, "section"):
            resolved = _resolve_section_marker(project, parsed, default_type, rel, line)
            if resolved is not None:
                section_type = resolved
                section_line = line
            continue

        body = "\n".join(lines[close_i + 1 : body_end])
        merged: dict[str, Any] = dict(defaults)
        merged.update({k: v for k, v in parsed.items() if k != "__line__"})
        if not _apply_section(project, merged, section_type, section_line, rel, line):
            continue
        item = _build_item(project, merged, rel, line=line, body=body)
        if item:
            out.append(item)
    return out


def parse_list_file(project: Project, path: str) -> list[Item]:
    rel = _relpath(project, path)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        raw = yaml.load(text, Loader=_LineLoader) or {}
    except yaml.YAMLError as exc:
        message, err_line = _yaml_error_report(exc, text.split("\n"), offset=0)
        project.error(f"invalid YAML: {message}", file=rel, line=err_line)
        return []

    if not isinstance(raw, dict) or "items" not in raw:
        project.error("list file must be a mapping with an 'items:' key", file=rel, line=1)
        return []

    defaults = _strip_lines(raw.get("defaults") or {})
    default_type = defaults.get("type")

    out: list[Item] = []
    entries = raw.get("items") or []
    if not isinstance(entries, list):
        project.error("'items:' must be a list", file=rel, line=1)
        return []

    # `- section: <type>` (finding 6): a marker entry, not an item -- asserts
    # the type for every entry after it until the next section or end of
    # list. Interleaving two types under one section is structurally
    # impossible rather than something to lint for after the fact, since an
    # item that names a conflicting type is simply an error (_apply_section).
    section_type: str | None = None
    section_line: int | None = None

    for entry in entries:
        if not isinstance(entry, dict):
            project.error(f"list entry must be a mapping, got {type(entry).__name__}",
                          file=rel, line=1)
            continue
        line = entry.get("__line__", 1)

        if _only_key(entry, "section"):
            resolved = _resolve_section_marker(project, entry, default_type, rel, line)
            if resolved is not None:
                section_type = resolved
                section_line = line
            continue

        merged: dict[str, Any] = dict(defaults)
        merged.update({k: v for k, v in entry.items() if k != "__line__"})
        if not _apply_section(project, merged, section_type, section_line, rel, line):
            continue
        item = _build_item(project, merged, rel, line=line)
        if item:
            out.append(item)
    return out


def source_files(project: Project) -> list[str]:
    items_dir = os.path.join(project.root, "items")
    found: list[str] = []
    if not os.path.isdir(items_dir):
        return found
    for dirpath, dirnames, filenames in os.walk(items_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if name.endswith((".md", ".yaml", ".yml")):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def load_items(project: Project, require_ids: bool = True) -> None:
    """Parse every source file into project.items, reporting duplicate IDs.

    Items with no id yet go to project.pending so `refdes id` can allocate one.
    """
    for path in source_files(project):
        if path.endswith(".md"):
            items = parse_markdown_file(project, path)
        else:
            items = parse_list_file(project, path)
        for item in items:
            if not item.id:
                if item.id_rejected:
                    # Already reported at parse time (an unquoted, possibly
                    # YAML-mangled number) -- must not enter project.pending,
                    # or `refdes id` would "fix" it by allocating a fresh,
                    # unrelated id and writing it in *alongside* the bad
                    # value instead of replacing it, corrupting the file the
                    # same way Part 0's original bug did.
                    continue
                project.pending.append(item)
                if require_ids:
                    if item.numeric_id_hint:
                        message = (
                            f"id: {item.numeric_id_hint} has no prefix yet -- "
                            f"run 'refdes id' to expand it into a full id"
                        )
                    else:
                        message = "item has no id — run 'refdes id' to allocate one"
                    project.error(message, file=item.source_file, line=item.source_line)
                continue
            existing = project.items.get(item.id)
            if existing:
                project.error(
                    f"duplicate id {item.id!r} (also defined at "
                    f"{existing.source_file}:{existing.source_line})",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            project.items[item.id] = item
