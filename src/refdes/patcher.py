"""The item-span source patcher: bounded, provable edits to an items file.

docs/design/browser-editor.md, "Write-back fidelity". This is the generalized
form of the targeted rewrites `ids.py` and `links.py` already perform: the real
parser (PyYAML, the same loader `parse.py` uses) still decides meaning, and this
module only locates a bounded span of source text and replaces it. It never
serializes an untouched value, and it never writes anything -- `plan_patch()`
returns a plan naming the exact span it would touch, `apply_patch()` returns new
text. The caller decides whether those bytes ever reach a file.

The guarantee, stated exactly (the design's five points, applied to one file):

1. every byte outside the planned span is unchanged;
2. inside the item, comments, key order, flow/block style, and the quoting of
   untouched fields are preserved, because they are never re-emitted;
3. only the edited value may normalize, and its scalar style is preserved
   whenever that style can represent the new value;
4. the patched text is reparsed by PyYAML and the edited field must construct
   to exactly the intended value (Python type included, not string form); and
5. every other item in the file must construct to the same semantic projection
   as before.

A plan that cannot prove all five is a `Refusal` naming why, and `apply_patch()`
will not run it. Refusal is a result, not an exception path: the editor renders
it. Ambiguity is always resolved toward refusing -- an anchor, an alias, a
second document, a comment whose attachment the span cannot bound, a literal
`---` in prose, a duplicate key -- because a patch that guesses produces a file
that parses cleanly while meaning something the author did not write.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

import yaml
from yaml.composer import ComposerError

from . import parse as parse_mod

# Fields the patcher will not touch at any value. `id` and `key` are identity:
# rewriting one silently orphans every link that names it, which is a different
# operation with its own rules (docs/design/browser-editor.md puts display-id
# rename outside v1 entirely), so an edit aimed at them is a mistake worth
# surfacing rather than a faithful byte splice.
PROTECTED_FIELDS = frozenset({"id", "key"})


class PatchRefused(Exception):
    """Raised by `apply_patch()` when handed a `Refusal` or a stale plan.

    Plans are values; applying one that was never valid, or that was built
    against different text, is a programming error at the call site rather than
    an authoring outcome.
    """


# --------------------------------------------------------------------- results


@dataclass(frozen=True)
class Refusal:
    """The patch cannot be made with the fidelity guarantee. Never partial."""

    reason: str
    ref: str | None = None
    op: str | None = None
    field: str | None = None
    line: int | None = None
    path: str | None = None

    ok: bool = False

    def __str__(self) -> str:
        where = f" ({self.path}:{self.line})" if self.path and self.line else ""
        return f"refused: {self.reason}{where}"


@dataclass(frozen=True)
class PatchPlan:
    """One bounded replacement in one file, proven against the real parser.

    `start`/`end` are character offsets into the text the plan was built from,
    half-open; `start_line`/`end_line` are 1-indexed source lines, for messages.
    `original` is the exact text the span holds, which `apply_patch()` checks
    before splicing: a plan built against a stale revision refuses instead of
    writing at an offset that no longer means the same thing.
    """

    ref: str
    op: str
    shape: str  # "yaml-item" | "md-front-matter" | "md-body"
    start: int
    end: int
    replacement: str
    original: str
    start_line: int
    end_line: int
    old_value: Any = None
    new_value: Any = None
    field: str | None = None
    notes: tuple[str, ...] = ()
    path: str | None = None

    ok: bool = True

    def byte_span(self, text: str) -> tuple[int, int]:
        """The same span in UTF-8 bytes, for a caller that writes bytes."""
        prefix = text[: self.start].encode("utf-8")
        body = text[self.start : self.end].encode("utf-8")
        return len(prefix), len(prefix) + len(body)

    def apply(self, text: str) -> str:
        return apply_patch(text, self)

    def describe(self) -> str:
        where = f"{self.path}:{self.start_line}" if self.path else "<text>"
        target = self.field if self.field else "body"
        return f"{self.shape} {self.ref}: {self.op} {target} at {where} [{self.start}:{self.end}]"


# ------------------------------------------------------------------ operations


@dataclass(frozen=True)
class SetField:
    """Set or replace one direct scalar field of the item."""

    name: str
    value: Any


@dataclass(frozen=True)
class SetBody:
    """Replace the item's body: Markdown prose, or a list file's `body:`."""

    text: str


# --------------------------------------------------------------- locate state


@dataclass
class _Item:
    """Where one item lives, and how to find a field's value node inside it."""

    ref: str
    index: int
    shape: str
    node: yaml.Node | None = None  # the item's MappingNode (yaml / front matter)
    base: int = 0  # char offset the node's marks are relative to
    key_line: int = 1  # 1-indexed source line of the item's first line
    open_i: int = 0  # markdown: fence line indices
    close_i: int = 0
    body_start: int = 0
    body_end: int = 0
    fields: dict[str, Any] = field(default_factory=dict)
    key_nodes: dict[str, Any] = field(default_factory=dict)


@dataclass
class _File:
    text: str
    shape: str  # "yaml" | "md"
    items: list[_Item]
    eol: str
    projection: list[Any]


class _LocateError(Exception):
    def __init__(self, reason: str, line: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.line = line


# ---------------------------------------------------------------- public API


def plan_patch(text: str, ref: str, op: Any, *, path: str | None = None) -> PatchPlan | Refusal:
    """Plan one edit to the item `ref` in `text`, or refuse with a reason.

    `ref` is the item's display id or its surrogate key, matched against the
    parsed value of `id:`/`key:` in this file. `op` is a `SetField` or a
    `SetBody`. Pure: nothing is read from or written to disk, and `text` is not
    modified.
    """
    if not isinstance(op, (SetField, SetBody)):
        return Refusal(f"unsupported operation {type(op).__name__}", ref=ref, path=path)
    try:
        f = _load(text)
    except _LocateError as exc:
        return Refusal(exc.reason, ref=ref, op=_op_name(op), line=exc.line, path=path)

    item = _find(f, ref)
    if isinstance(item, Refusal):
        return replace(item, op=_op_name(op), path=path)

    if isinstance(op, SetField):
        plan = _plan_field(f, item, op)
    else:
        plan = _plan_body(f, item, op)
    if isinstance(plan, Refusal):
        return replace(
            plan,
            ref=plan.ref if plan.ref is not None else item.ref,
            op=_op_name(op),
            path=path,
        )
    try:
        _verify(f, plan, op)
    except _LocateError as exc:
        return Refusal(
            exc.reason,
            ref=item.ref,
            op=_op_name(op),
            line=exc.line,
            path=path,
        )
    return replace(plan, path=path)


def apply_patch(text: str, plan: PatchPlan | Refusal) -> str:
    """Splice the plan into `text` and return the new text. Writes nothing."""
    if isinstance(plan, Refusal):
        raise PatchRefused(f"cannot apply a refused patch: {plan.reason}")
    if text[plan.start : plan.end] != plan.original:
        raise PatchRefused(
            "this plan was built against different text: the span at "
            f"[{plan.start}:{plan.end}] no longer holds what the plan measured"
        )
    return text[: plan.start] + plan.replacement + text[plan.end :]


def revert_plan(plan: PatchPlan) -> PatchPlan:
    """The exact inverse of a plan: put the span back the way it was.

    This is byte-identical restore, not "set the field back to the value it
    had". The distinction matters for a folded scalar, whose original wrapping
    is not recoverable from its value: re-setting the old value can re-wrap the
    text, while replaying the recorded span cannot. Apply the original plan
    first, then this one against the patched text.
    """
    if isinstance(plan, Refusal):
        raise PatchRefused("a refusal has nothing to revert")
    return PatchPlan(
        ref=plan.ref,
        op="revert",
        shape=plan.shape,
        start=plan.start,
        end=plan.start + len(plan.replacement),
        replacement=plan.original,
        original=plan.replacement,
        start_line=plan.start_line,
        end_line=plan.end_line,
        old_value=plan.new_value,
        new_value=plan.old_value,
        field=plan.field,
        notes=("replay of the recorded span, byte-identical to the original",),
        path=plan.path,
    )


def patch_item(text: str, ref: str, op: Any, *, path: str | None = None) -> tuple[str, PatchPlan | Refusal]:
    """Convenience: plan and, if it holds, apply. Returns (text, plan)."""
    plan = plan_patch(text, ref, op, path=path)
    if isinstance(plan, Refusal):
        return text, plan
    return apply_patch(text, plan), plan


def _op_name(op: Any) -> str:
    return "set_field" if isinstance(op, SetField) else "set_body"


# ------------------------------------------------------------------- loading


def _load(text: str) -> _File:
    """Parse `text` once into locate state, refusing an unusable file."""
    if isinstance(text, bytes):
        raise _LocateError("the patcher takes text, not bytes; decode the source first")
    if text.startswith("\ufeff"):
        raise _LocateError("the file carries a UTF-8 BOM, which shifts every byte offset", 1)
    eol = "\r\n" if "\r\n" in text else "\n"
    if _is_markdown(text):
        return _load_markdown(text, eol)
    return _load_yaml(text, eol)


def _is_markdown(text: str) -> bool:
    first = text.split("\n", 1)[0]
    return parse_mod.FENCE_RE.match(first.rstrip("\r") if first.endswith("\r") else first) is not None


def _line_starts(text: str) -> list[int]:
    starts = [0]
    pos = 0
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
            pos = i
    del pos
    return starts


def _compose(text: str) -> yaml.Node:
    """Compose one document, refusing anything the marks cannot be trusted on."""
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except ComposerError as exc:
        if "single document" in str(exc):
            raise _LocateError("the file holds more than one YAML document", _mark_line(exc)) from exc
        raise _LocateError(f"invalid YAML: {_first_line(exc)}", _mark_line(exc)) from exc
    except yaml.YAMLError as exc:
        raise _LocateError(f"invalid YAML: {_first_line(exc)}", _mark_line(exc)) from exc
    if node is None:
        raise _LocateError("the file is empty")
    _reject_syntax(node, text)
    return node


def _reject_syntax(node: yaml.Node, text: str) -> None:
    """Refuse anchors, aliases, and explicit tags anywhere in the file.

    An alias composes to the *same* node object as its anchor, so a shared id
    means a span that stands for two places at once; an anchor or a `!!tag`
    lives inside the value's own span, so replacing that span silently deletes
    syntax the author wrote. Neither is worth guessing about.
    """
    seen: dict[int, str] = {}

    def walk(n: yaml.Node, where: str) -> None:
        if id(n) in seen:
            raise _LocateError(
                f"an alias at {where} shares its node with {seen[id(n)]}; "
                "a span over it would stand for two places at once",
                n.start_mark.line + 1,
            )
        seen[id(n)] = where
        head = text[n.start_mark.index : n.start_mark.index + 1]
        if head == "&":
            raise _LocateError(
                f"an anchor is defined at {where}, inside the span this edit would replace",
                n.start_mark.line + 1,
            )
        if head == "!":
            raise _LocateError(
                f"an explicit tag at {where} is part of the value's span and would be dropped",
                n.start_mark.line + 1,
            )
        if isinstance(n, yaml.MappingNode):
            for i, (k, v) in enumerate(n.value):
                _mark_flow(k, n)
                _mark_flow(v, n)
                walk(k, f"{where}.{_scalar_text(k)}")
                walk(v, f"{where}.{_scalar_text(k)}#{i}")
        elif isinstance(n, yaml.SequenceNode):
            for i, child in enumerate(n.value):
                _mark_flow(child, n)
                walk(child, f"{where}[{i}]")

    walk(node, "$")


def _mark_flow(child: yaml.Node, parent: yaml.Node) -> None:
    # PyYAML nodes carry no parent link; record the one fact the patcher needs
    # from the parent -- whether it is flow style -- while the tree is fresh.
    child._refdes_flow_parent = parent.flow_style


def _first_line(exc: BaseException) -> str:
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def _mark_line(exc: BaseException) -> int | None:
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    return mark.line + 1 if mark is not None else None


def _scalar_text(node: yaml.Node) -> str:
    return node.value if isinstance(node, yaml.ScalarNode) else type(node).__name__


def _load_yaml(text: str, eol: str) -> _File:
    root = _compose(text)
    if not isinstance(root, yaml.MappingNode):
        raise _LocateError(
            "not an items file: expected a mapping with an 'items:' key "
            "(a Markdown item file must open with a '---' front-matter fence)",
            1,
        )
    entries = None
    for k, v in root.value:
        if _scalar_text(k) == "items":
            entries = v
            break
    if entries is None:
        raise _LocateError(
            "no 'items:' key: a list file is a mapping with an 'items:' list "
            "(a Markdown item file must open with a '---' front-matter fence)",
            1,
        )
    if not isinstance(entries, yaml.SequenceNode):
        raise _LocateError("'items:' must be a list", entries.start_mark.line + 1)

    keys: dict[str, Any] = {}

    items: list[_Item] = []
    for i, entry in enumerate(entries.value):
        if not isinstance(entry, yaml.MappingNode):
            raise _LocateError(
                f"list entry {i} must be a mapping, got {type(entry).__name__}",
                entry.start_mark.line + 1,
            )
        if _only_key(entry, "section"):
            continue
        fields, keys = _field_values(entry)
        ref = _ref_of(fields, i)
        items.append(
            _Item(
                ref=ref,
                index=i,
                shape="yaml-item",
                node=entry,
                base=0,
                key_line=entry.start_mark.line + 1,
                fields=fields,
                key_nodes=keys,
            )
        )
    projection = _yaml_projection(text)
    return _File(text=text, shape="yaml", items=items, eol=eol, projection=projection)


def _load_markdown(text: str, eol: str) -> _File:
    lines = text.split("\n")
    # Fence detection is line-indexed, so it can run on \r-stripped copies;
    # the spans themselves are built from the raw lines, keeping every mark
    # valid against the original text on CRLF files.
    scan_lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
    blocks, errors = parse_mod.md_front_matter_blocks(scan_lines)
    if errors:
        message, line = errors[0]
        raise _LocateError(message, line)
    if not blocks:
        raise _LocateError("no YAML front-matter (file must start with '---')", 1)

    starts = _line_starts(text)
    item_blocks = blocks[1:] if _only_key_dict(blocks[0][2], "defaults") else blocks
    items: list[_Item] = []
    for i, (open_i, close_i, parsed) in enumerate(item_blocks):
        if _only_key_dict(parsed, "section"):
            continue
        fm_text = "\n".join(lines[open_i + 1 : close_i])
        base = starts[open_i + 1] if open_i + 1 < len(starts) else len(text)
        try:
            node = _compose(fm_text)
        except _LocateError as exc:
            raise _LocateError(f"front matter: {exc.reason}", open_i + 2 + (exc.line or 0)) from exc
        if not isinstance(node, yaml.MappingNode):
            raise _LocateError("front-matter must be a mapping", open_i + 2)
        fields, keys = _field_values(node)
        ref = _ref_of(fields, i)
        nxt = item_blocks[i + 1][0] if i + 1 < len(item_blocks) else len(lines)
        items.append(
            _Item(
                ref=ref,
                index=i,
                shape="md-front-matter",
                node=node,
                base=base,
                key_line=open_i + 2,
                open_i=open_i,
                close_i=close_i,
                body_start=starts[close_i + 1] if close_i + 1 < len(starts) else len(text),
                body_end=starts[nxt] if nxt < len(starts) else len(text),
                fields=fields,
                key_nodes=keys,
            )
        )
    projection = _md_projection(lines, item_blocks)
    return _File(text=text, shape="md", items=items, eol=eol, projection=projection)


def _only_key(node: yaml.MappingNode, key: str) -> bool:
    return {_scalar_text(k) for k, _ in node.value} == {key}


def _only_key_dict(parsed: dict, key: str) -> bool:
    return {k for k in parsed if k != "__line__"} == {key}


def _field_values(node: yaml.MappingNode) -> tuple[dict[str, Any], dict[str, Any]]:
    """Direct field names of a mapping node, with their value nodes and key nodes.

    A repeated key is kept as a list of value nodes so a lookup can refuse it
    rather than silently picking the last one, which is what PyYAML does. The
    key nodes come back too: a comment between a key's colon and its value is
    only visible from the colon.
    """
    out: dict[str, Any] = {}
    keys: dict[str, Any] = {}
    for k, v in node.value:
        name = _scalar_text(k)
        if name in out:
            prior = out[name]
            out[name] = (prior if isinstance(prior, list) else [prior]) + [v]
            pk = keys[name]
            keys[name] = (pk if isinstance(pk, list) else [pk]) + [k]
        else:
            out[name] = v
            keys[name] = k
    return out, keys


def _ref_of(fields: dict[str, Any], index: int) -> str:
    for name in ("id", "key"):
        node = fields.get(name)
        if isinstance(node, yaml.ScalarNode) and node.value:
            return _plain_scalar(node)
    return f"#{index}"


def _plain_scalar(node: yaml.ScalarNode) -> str:
    """The scalar's value, refusing one whose spelling cannot be read plainly."""
    head = node.value[:1]
    if head in "&!*":
        raise _LocateError(
            f"'{node.value}' uses YAML anchor or tag syntax the patcher cannot bound",
            node.start_mark.line + 1,
        )
    return node.value


def _find(f: _File, ref: str) -> _Item | Refusal:
    matches = [i for i in f.items if i.ref == ref]
    if not matches:
        known = ", ".join(sorted(i.ref for i in f.items)) or "none"
        return Refusal(f"no item {ref!r} in this file (it holds: {known})")
    if len(matches) > 1:
        return Refusal(
            f"{ref!r} names {len(matches)} items in this file; the patch cannot tell them apart",
            line=matches[0].key_line,
        )
    return matches[0]


# --------------------------------------------------------------- field plans


def _plan_insert(f: _File, item: _Item, name: str, value: Any, what: str) -> PatchPlan | Refusal:
    """Add a key the item does not have yet, at the end of its own mapping.

    The design's write-back contract includes inserting a new field with the
    item's indentation and the local style. Appending after the item's last
    value is the one placement that cannot be wrong: it inherits the item's
    indentation, it cannot land inside a block scalar (the insertion point is
    the last character of content, and a block scalar's content ends before any
    key at the item's own indentation), and it leaves every blank line that
    separates items where it was. A flow-style item is refused because a new
    key there is a different problem -- the braces bound it.
    """
    node = item.node
    if not isinstance(node, yaml.MappingNode) or not node.value:
        return Refusal(f"cannot insert {what} into an empty item", ref=item.ref, field=name)
    if node.flow_style:
        return Refusal(
            f"item {item.ref} is written as a one-line flow mapping; inserting a key "
            "there would rewrite the whole line",
            ref=item.ref,
            field=name,
            line=node.start_mark.line + 1,
        )
    last_value = node.value[-1][1]
    # Walk back over the whitespace a block scalar's extent swallows, so the new
    # key lands directly after the item's last line of content and ahead of the
    # blank line that separates items.
    pos = item.base + last_value.end_mark.index
    while pos > 0 and f.text[pos - 1] in " \n":
        pos -= 1
    if pos <= item.base + node.start_mark.index:
        return Refusal(f"cannot find where item {item.ref} ends", ref=item.ref, field=name)
    indent = " " * (node.value[0][0].start_mark.column)
    emitted, note = _emit_scalar(
        value, style=None, indent=len(indent), eol=f.eol, allow_block=True, original=""
    )
    if emitted is None:
        return Refusal(
            f"cannot emit {value!r} as a YAML scalar PyYAML reads back unchanged",
            ref=item.ref,
            field=name,
        )
    block = "\n" in emitted
    addition = f"{f.eol}{indent}{name}:"
    addition += (" " + emitted) if not block else (" " + emitted.rstrip("\n"))
    return PatchPlan(
        ref=item.ref,
        op="insert",
        shape=item.shape,
        start=pos,
        end=pos,
        replacement=addition,
        original="",
        start_line=f.text.count("\n", 0, pos) + 1,
        end_line=f.text.count("\n", 0, pos) + 1,
        old_value=None,
        new_value=value,
        field=name,
        notes=("inserted at the end of the item's own mapping",) + ((note,) if note else ()),
    )


def _plan_field(f: _File, item: _Item, op: SetField) -> PatchPlan | Refusal:
    name = op.name
    if name in PROTECTED_FIELDS:
        return Refusal(
            f"'{name}' is identity, not a field: rewriting it orphans every link "
            "that names it, which is a rename operation and not this one",
            ref=item.ref,
            field=name,
            line=item.key_line,
        )
    got = item.fields.get(name)
    if got is None:
        return _plan_insert(f, item, name, op.value, f"field '{name}'")
    if isinstance(got, list):
        return Refusal(
            f"'{name}' appears {len(got)} times in item {item.ref}; PyYAML keeps the "
            "last one and the patch cannot tell which the author meant",
            ref=item.ref,
            field=name,
            line=got[0].start_mark.line + 1,
        )
    node = got
    if not isinstance(node, yaml.ScalarNode):
        return Refusal(
            f"'{name}' on item {item.ref} is a {type(node).__name__.replace('Node', '').lower()}, "
            "not a scalar; replacing collections is not supported yet",
            ref=item.ref,
            field=name,
            line=node.start_mark.line + 1,
        )

    start = item.base + node.start_mark.index
    end = item.base + node.end_mark.index
    original = f.text[start:end]
    if f.text[start:end] != original:  # pragma: no cover - defensive
        return Refusal("the measured span does not match the file", ref=item.ref, field=name)

    indent = _key_indent(f.text, start)
    emitted, note = _emit_scalar(
        op.value,
        style=node.style,
        indent=indent,
        eol=f.eol,
        allow_block=not _in_flow(node),
        original=original,
    )
    if emitted is None:
        return Refusal(
            f"cannot emit {op.value!r} as a YAML scalar that PyYAML reads back as the "
            "same value",
            ref=item.ref,
            field=name,
            line=node.start_mark.line + 1,
        )
    tail = _fit_trailing(f.text, end, original, emitted, f.eol)
    emitted, end, original = tail.emitted, tail.end, tail.original
    if _comment_between(f.text, _key_end(item, name), start):
        return Refusal(
            f"a comment sits between '{name}:' and its value; replacing the value span "
            "would move it onto different text, and which value it annotates is not the "
            "patcher's to decide",
            ref=item.ref,
            field=name,
            line=node.start_mark.line + 1,
        )

    return PatchPlan(
        ref=item.ref,
        op="set_field",
        shape=item.shape,
        start=start,
        end=end,
        replacement=emitted,
        original=original,
        start_line=_file_line(f, item, node.start_mark.line + 1),
        end_line=_file_line(f, item, node.end_mark.line + 1),
        old_value=_construct(original, node.value),
        new_value=op.value,
        field=name,
        notes=(note,) if note else (),
    )


@dataclass(frozen=True)
class _Tail:
    emitted: str
    end: int
    original: str


def _fit_trailing(text: str, end: int, original: str, emitted: str, eol: str) -> _Tail:
    """Preserve how many blank lines separated this value from what follows it.

    A clipped block scalar's extent swallows the blank line after it: `|` plus
    content consumes the following empty line into the token while stripping it
    from the value. So the newlines at the end of a span are two different
    things -- newlines that *are* the value, and newlines that are the file's
    layout between this field and the next. Replace a block with a one-line
    scalar and keep the whole run and you have added a paragraph break; drop it
    and you have deleted the separator between two items.

    The rule is the count of newlines from the last character of content to the
    first character of the next thing, which is `span's own + whatever follows
    the span`, and the replacement must produce the same count. A replacement
    that needs a line of its own (a block scalar) also takes ownership of the
    newlines after the span, so the plan's span grows to cover them and the
    count stays under the patch's control instead of half in and half out.
    """
    after = len(text[end:]) - len(text[end:].lstrip("\n"))
    own = len(original) - len(original.rstrip("\n"))
    total = own + after
    is_block = emitted[:1] in ("|", ">") and "\n" in emitted
    keep = emitted[:2] in ("|+", ">+")
    if is_block:
        target = max(total, 1)
        new_end = end + after
    else:
        target = total - after  # only the newlines the span itself owned
        new_end = end
    have = len(emitted) - len(emitted.rstrip("\n"))
    if keep:
        # Every trailing newline in a keep-chomped block is content; only grow.
        out = emitted + eol * max(0, target - have) if have < target else emitted
    elif have == target:
        out = emitted
    else:
        out = emitted.rstrip("\n") + eol * target
    return _Tail(out, new_end, original + text[end:new_end])


def _construct(source: str, fallback: Any) -> Any:
    """The value the author's own spelling constructs to, not its raw text.

    A plan's `old_value` is what a revert sets, so it must be the constructed
    value: `date: 2026-02-18` reverts to a date, not to the string
    '2026-02-18', which would come back quoted and mean something else.
    """
    try:
        return yaml.safe_load(source)
    except yaml.YAMLError:
        return fallback


def _file_line(f: _File, item: _Item, local_line: int) -> int:
    """A line number inside a node, as a line number in the file."""
    if item.shape != "md-front-matter":
        return local_line
    return item.open_i + 1 + local_line  # fence line, then front matter starts


def _in_flow(node: yaml.Node) -> bool:
    """Whether the node sits inside a flow collection (a one-line `{...}` item)."""
    return bool(getattr(node, "_refdes_flow_parent", False))


def _key_indent(text: str, value_start: int) -> int:
    """The indentation of the line that introduces this value.

    A block scalar's own column is where its `|` sits, which tells the emitter
    nothing about where its content must go; the key's indentation does. For
    `    body: |` the content belongs at six, not at eleven.
    """
    line_start = text.rfind("\n", 0, value_start) + 1
    line = text[line_start:]
    return len(line) - len(line.lstrip(" "))


def _comment_between(text: str, key_end: int | None, value_start: int) -> bool:
    """True when a `#` comment separates the key's colon from the value's start.

    The comment is outside the value span, so the splice leaves it in place --
    but a value that begins on its own line under a commented key means the
    comment annotates the *field*, and re-emitting the value on that same line
    would silently re-attach it. Refuse rather than decide. Measured from the
    colon, not from the value's line: on `body: # note` followed by indented
    prose, the comment is on the line *above* the value's own start.
    `key_end` is the absolute offset just past the key's own span, or None.
    """
    if key_end is None:
        return False
    gap = text[key_end:value_start]
    return "#" in gap


def _key_end(item: _Item, name: str) -> int | None:
    """Absolute offset just past the key node for `name`, if it has one."""
    keyn = item.key_nodes.get(name)
    if keyn is None or isinstance(keyn, list):
        return None
    return item.base + keyn.end_mark.index


# ---------------------------------------------------------------- body plans


def _plan_body(f: _File, item: _Item, op: SetBody) -> PatchPlan | Refusal:
    if item.shape == "md-front-matter":
        return _plan_markdown_body(f, item, op)
    return _plan_yaml_body(f, item, op)


def _plan_markdown_body(f: _File, item: _Item, op: SetBody) -> PatchPlan | Refusal:
    start, end = item.body_start, item.body_end
    original = f.text[start:end]
    # Normalize to \n first: a caller handing us text that already carries
    # CRLF must not get every line ending doubled by the eol conversion below.
    new = op.text.replace("\r\n", "\n")
    if original.rstrip("\n").endswith("---") or _has_fence(original):
        return Refusal(
            f"the body of {item.ref} contains a literal '---' line, so where this item's "
            "prose ends is exactly the thing in question",
            ref=item.ref,
            line=item.close_i + 2,
        )
    if _has_fence(new):
        return Refusal(
            "the new body contains a '---' line, which the parser reads as the start of "
            "a different item",
            ref=item.ref,
            line=item.close_i + 2,
        )
    replacement = new
    if original.endswith("\n") and not replacement.endswith("\n"):
        replacement += f.eol
    if f.eol == "\r\n":
        replacement = replacement.replace("\n", "\r\n")
    return PatchPlan(
        ref=item.ref,
        op="set_body",
        shape="md-body",
        start=start,
        end=end,
        replacement=replacement,
        original=original,
        start_line=item.close_i + 2,
        end_line=max(item.close_i + 2, item.close_i + 2 + original.count("\n")),
        old_value=original,
        new_value=new,
        field="body",
    )


def _plan_yaml_body(f: _File, item: _Item, op: SetBody) -> PatchPlan | Refusal:
    got = item.fields.get("body")
    if got is None:
        return _plan_insert(f, item, "body", op.text, "a body")
    if isinstance(got, list):
        return Refusal(
            f"'body' appears {len(got)} times in item {item.ref}; the patch cannot tell "
            "which one to replace",
            ref=item.ref,
            line=got[0].start_mark.line + 1,
        )
    node = got
    if not isinstance(node, yaml.ScalarNode):
        return Refusal(
            f"'body' on item {item.ref} is a {type(node).__name__.replace('Node', '').lower()}, "
            "not a scalar body",
            ref=item.ref,
            line=node.start_mark.line + 1,
        )
    start = node.start_mark.index
    end = node.end_mark.index
    original = f.text[start:end]
    if _has_fence(op.text):
        return Refusal(
            "the new body contains a '---' line, which YAML reads as a document boundary",
            ref=item.ref,
            line=node.start_mark.line + 1,
        )
    op = SetBody(op.text.replace("\r\n", "\n"))  # eol conversion below owns the \r
    if not op.text.endswith("\n"):
        op = SetBody(op.text + "\n")  # a YAML body keeps its final line break
    emitted, note = _emit_scalar(
        op.text,
        style=node.style,
        indent=_key_indent(f.text, start),
        eol=f.eol,
        allow_block=not _in_flow(node),
        original=original,
    )
    if emitted is not None:
        tail = _fit_trailing(f.text, end, original, emitted, f.eol)
        emitted, end, original = tail.emitted, tail.end, tail.original
    if emitted is None:
        return Refusal(
            "cannot emit the new body as a YAML scalar that PyYAML reads back unchanged",
            ref=item.ref,
            line=node.start_mark.line + 1,
        )
    if _comment_between(f.text, _key_end(item, "body"), start):
        return Refusal(
            f"a comment sits between 'body:' and its value on item {item.ref}",
            ref=item.ref,
            line=node.start_mark.line + 1,
        )
    return PatchPlan(
        ref=item.ref,
        op="set_body",
        shape=item.shape,
        start=start,
        end=end,
        replacement=emitted,
        original=original,
        start_line=node.start_mark.line + 1,
        end_line=node.end_mark.line + 1,
        old_value=_construct(original, node.value),
        new_value=op.text,
        field="body",
        notes=(note,) if note else (),
    )


def _has_fence(text: str) -> bool:
    return any(parse_mod.FENCE_RE.match(line.rstrip("\r")) for line in text.split("\n"))


# ------------------------------------------------------------------ emitting


def _emit_scalar(
    value: Any,
    *,
    style: str | None,
    indent: int,
    eol: str,
    allow_block: bool,
    original: str,
) -> tuple[str | None, str | None]:
    """Render `value` as YAML source, preserving the original style where possible.

    Returns (text, note); text is None when no emission round-trips. Every
    candidate is checked by handing it back to PyYAML, so a string that would
    construct as a date, an octal, a sexagesimal, or a bool is quoted rather
    than trusted -- the YAML 1.1 traps the design names (`yes`, `0755`, `1:20`,
    `2026-01-05`) are caught by construction, not by a list of patterns.
    """
    candidates: list[tuple[str, str | None]] = []

    def add(text: str, why: str | None = None) -> None:
        candidates.append((text, why))

    if isinstance(value, bool):
        add("true" if value else "false")
    elif value is None:
        add("null")
    elif isinstance(value, int):
        add(str(value))
    elif isinstance(value, float):
        add(repr(value))
    elif isinstance(value, str):
        literal = _literal_block(value, indent, eol) if allow_block else None
        folded = _folded_block(value, indent, eol) if allow_block else None
        if "\n" in value:
            # The author's own block style goes first: a `>` field stays a `>`
            # field, a `|` field stays a `|` field.
            if style == ">" and folded is not None:
                add(folded, "emitted as a folded block scalar, keeping the field's style")
            if style == "|" and literal is not None:
                add(literal, "emitted as a literal block scalar, keeping the field's style")
            if literal is not None:
                add(literal, "emitted as a literal block scalar")
            if folded is not None:
                add(folded, "emitted as a folded block scalar")
            add(_double_quoted(value), "emitted quoted to keep the line breaks")
        elif style == ">" and folded is not None:
            add(folded, "emitted as a folded block scalar, keeping the field's style")
        elif style == '"' or _needs_quotes(value):
            add(_double_quoted(value))
        elif style == "'":
            add(_single_quoted(value))
        else:
            add(value)
            if _needs_quotes(value):
                add(_double_quoted(value))
    else:
        text = str(value)
        add(text)
        add(_double_quoted(text))

    for text, why in candidates:
        if _roundtrips(text, value):
            if original and original != text and _roundtrips(original, value):
                # The author's own spelling already says this value: keep it.
                return original, None
            return text, why
    return None, None


def _roundtrips(emitted: str, value: Any) -> bool:
    """Does PyYAML construct `emitted` back to exactly `value`, type included?"""
    try:
        got = yaml.safe_load("k: " + emitted)
    except yaml.YAMLError:
        return False
    if not isinstance(got, dict) or "k" not in got:
        return False
    got = got["k"]
    if isinstance(value, str) or isinstance(got, str):
        if type(got) is not type(value):
            return False
    return got == value and type(got) is type(value)


def _folded_block(value: str, indent: int, eol: str) -> str | None:
    """A `>`-style block scalar, for a value that is one logical line.

    Folding is lossy in one direction only: the line breaks the author chose to
    wrap at are not part of the value, so they cannot be recovered from it and a
    re-emitted folded field may wrap somewhere else. That is a re-wrap of the
    same text, not a changed value, and it is what "the edited value alone may
    normalize" allows. A value with real line breaks inside it cannot be folded
    at all, so this returns None and the caller uses a literal block.
    """
    if "\r" in value or value == "":
        return None
    if value.rstrip("\n").count("\n"):
        return None
    if value != value.lstrip(" \t"):
        return None
    if value.rstrip("\n") != value.rstrip("\n").rstrip():
        return None
    if value.endswith("\n\n"):
        header = ">+"
    elif value.endswith("\n"):
        header = ">"
    else:
        header = ">-"
    pad = " " * (indent + 2)
    body = value.rstrip("\n")
    if not body:
        return None
    return header + eol + pad + body + eol


def _needs_quotes(value: str) -> bool:
    """Would plain style risk a different construction, or be invalid at all?"""
    if value == "" or value != value.strip():
        return True
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return True
    if value[0] in "-?:,[]{}#&*!|>'\"%@`":
        return True
    if ": " in value or value.endswith(":") or " #" in value:
        return True
    try:
        got = yaml.safe_load(value)
    except yaml.YAMLError:
        return True
    return type(got) is not str


def _double_quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _single_quoted(value: str) -> str:
    if any(ord(ch) < 0x20 for ch in value):
        return _double_quoted(value)
    return "'" + value.replace("'", "''") + "'"


def _literal_block(value: str, indent: int, eol: str) -> str | None:
    """A `|`-style block scalar for a multiline value, or None if it cannot work.

    Refuses rather than fudges: a first line that opens with whitespace needs an
    explicit indentation indicator, trailing spaces would be silently kept, and
    a value with no trailing newline and a blank last line cannot be clipped
    correctly. Any of those and the caller falls back to a quoted scalar.
    """
    if "\r" in value:
        return None
    lines = value.split("\n")
    if lines and lines[0][:1] in (" ", "\t"):
        return None
    if any(line != line.rstrip() for line in lines):
        return None
    if value.endswith("\n\n"):
        header = "|+"
    elif value.endswith("\n"):
        header = "|"
    else:
        header = "|-"
    pad = " " * (indent + 2)
    body = [pad + line if line else "" for line in lines]
    return header + eol + eol.join(body)


# ---------------------------------------------------------------- verification


def _verify(f: _File, plan: PatchPlan, op: Any) -> None:
    """Reparse the patched text with the real parser and prove points 4 and 5."""
    _check_replacement_eol(f, plan)
    patched = f.text[: plan.start] + plan.replacement + f.text[plan.end :]
    try:
        after = _load(patched)
    except _LocateError as exc:
        raise _LocateError(f"the patched file does not parse: {exc.reason}", exc.line) from exc

    if len(after.items) != len(f.items):
        raise _LocateError(
            f"the patched file parses to {len(after.items)} items instead of {len(f.items)}"
        )
    before, after_proj = f.projection, after.projection
    if len(before) != len(after_proj):
        raise _LocateError("the patched file parses to a different number of items")

    index = _projection_index(f, plan.ref)
    for i, (b, a) in enumerate(zip(before, after_proj)):
        if i == index:
            continue
        if b != a:
            raise _LocateError(
                f"item #{i} changed as a side effect of this edit; the patch is not bounded"
            )
    edited = after_proj[index]
    expected = _expected_projection(before[index], plan, op)
    if isinstance(op, SetBody):
        # A body is prose: the file's own line breaks and the break that closes
        # its last line are how that prose is spelled on disk, not part of what
        # the author asked for. Compare it on a line-ending-neutral view -- the
        # replacement itself still carries the file's eol, which
        # `_check_replacement_eol` proves above.
        name = plan.field or "body"
        edited, expected = _fold_body(edited, name), _fold_body(expected, name)
    if isinstance(edited, tuple) and isinstance(expected, tuple):
        same = edited[0] == expected[0] and edited[1] == expected[1]
        if not same:
            raise _LocateError(
                "the edited body did not construct to the intended text: "
                f"expected {expected[1]!r}, the patched file gives {edited[1]!r}"
            )
        return
    if edited != expected:
        raise _LocateError(
            "the edited item did not construct to the intended value: "
            f"expected {expected!r}, the patched file gives {edited!r}"
        )


def _fold_body(entry: Any, name: str) -> Any:
    """A projection entry with its body text reduced to `_body_view`.

    Only the edited body is folded; every other field of the item is compared
    exactly, so this cannot hide a change anywhere but the prose.
    """
    if isinstance(entry, tuple):
        fields, body = entry
        return (fields, _body_view(body))
    if isinstance(entry, dict) and isinstance(entry.get(name), str):
        out = dict(entry)
        out[name] = _body_view(out[name])
        return out
    return entry


def _body_view(body: str) -> str:
    """Prose without the accident of how its line breaks were written.

    CRLF folds to LF because the patcher emits the file's own eol, and the
    closing break of the last line is dropped because the parser reads it as a
    separator between blocks while the author wrote it as the end of a line.
    """
    folded = body.replace("\r\n", "\n")
    if folded.endswith("\n"):
        folded = folded[:-1]
    # A CRLF body read back line-by-line can end on the orphan \r of its last
    # break, which is the same closing break seen from the other side.
    return folded[:-1] if folded.endswith("\r") else folded


def _check_replacement_eol(f: _File, plan: PatchPlan) -> None:
    """The replacement's line breaks must be the file's own.

    `_body_view` makes the semantic comparison line-ending-neutral, so this is
    where the byte-level half of that bargain is enforced: a plan that splices
    LF breaks into a CRLF file (or the reverse) is not a faithful edit, even
    though it would construct to the same value.
    """
    repl = plan.replacement
    if f.eol == "\r\n":
        for i, ch in enumerate(repl):
            if ch == "\n" and (i == 0 or repl[i - 1] != "\r"):
                raise _LocateError(
                    "the planned replacement writes a bare LF line break into a CRLF file"
                )
    elif "\r\n" in repl:
        raise _LocateError(
            "the planned replacement writes a CRLF line break into a file that uses LF"
        )


def _projection_index(f: _File, ref: str) -> int:
    for i, item in enumerate(f.items):
        if item.ref == ref:
            return i
    raise _LocateError(f"item {ref} is not in this file")


def _expected_projection(entry: Any, plan: PatchPlan, op: Any) -> Any:
    if isinstance(entry, dict):
        out = dict(entry)
        name = plan.field or "body"
        out[name] = op.text if isinstance(op, SetBody) else op.value
        return out
    if isinstance(entry, tuple):  # markdown: (fields, body)
        fields, body = entry
        out = dict(fields)
        if isinstance(op, SetBody):
            return (out, op.text)
        out[plan.field] = op.value
        return (out, body)
    raise _LocateError("unsupported projection entry")


def _yaml_projection(text: str) -> list[Any]:
    """The semantic shape of every item, for the before/after comparison.

    Constructed with the plain SafeLoader rather than parse.py's line-tagging
    one, so `__line__` bookkeeping cannot make two identical items look
    different merely because the edit shifted them down a line.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise _LocateError(f"invalid YAML: {_first_line(exc)}", _mark_line(exc)) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise _LocateError("list file must be a mapping with an 'items:' key", 1)
    out = []
    for entry in raw["items"]:
        if isinstance(entry, dict) and set(entry) == {"section"}:
            continue
        out.append(entry if isinstance(entry, dict) else entry)
    return out


def _md_projection(lines: list[str], item_blocks: list[tuple[int, int, dict]]) -> list[Any]:
    out: list[Any] = []
    for i, (open_i, close_i, parsed) in enumerate(item_blocks):
        if _only_key_dict(parsed, "section"):
            continue
        fields = {k: v for k, v in parsed.items() if k != "__line__"}
        nxt = item_blocks[i + 1][0] if i + 1 < len(item_blocks) else len(lines)
        body = "\n".join(lines[close_i + 1 : nxt])
        out.append((fields, body))
    return out
