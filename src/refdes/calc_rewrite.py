"""Rewrite retired calc unit spellings -- `name : unit = expression` -- into
the pipe form, `name = expression | unit`, project-wide.

Chunk 2 of the unit-syntax change (chunk 1 added the pipe form alongside the
old one; chunk 3 flips the old one to an error). Like `revise`, this is a
line-level surgical text edit, never a re-serialization: comments, indentation
and everything else on the line survive byte-for-byte, and only lines inside
```calc fences inside item bodies are candidates -- prose and `{{name}}`
references are never touched, because the rewrite targets the calc grammar,
not text that merely looks like it.

Safety model, borrowed wholesale from revise.apply():
- everything is computed in memory, and the whole plan is verified before any
  disk write;
- the transaction reloads and fully validates the rewritten project, and
  compares every calc's evaluated result and unit before and after -- a
  rewrite that changed what an item computes is refused and rolled back, not
  written and reported as success. That comparison is the proof that carrying
  content hashes (and calc hashes) forward is honest: the spelling moved, the
  arithmetic did not;
- sealed append-only entries are never rewritten. Their seals are historical
  records of exactly what was written, and swapping a sealed entry's hash to
  cover a text edit is precisely what sealing exists to prevent. A run with
  sealed old-spelling lines rewrites everything else, reports each sealed line
  (file:line, id), and still succeeds -- until history-backed resealing lands
  (docs/design/living-notes-plan.md phase H5), those entries stay on the old
  spelling, which chunk 1 guarantees still evaluates.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import build as build_mod
from . import calc
from . import seal as seal_mod
from . import textio
from .model import RETIRED_UNIT_SPELLING, Item, Project
from .revise import (
    FileRewrite,
    _blocking_errors,
    _capture_seal_files,
    _carry_forward_seals,
    _line_diff_report,
    _load_and_validate,
    _restore_seal_files,
    carry_forward_baselines,
    restore_rewrites,
    write_rewrites,
)

# Mirrors calc.CALC_BLOCK_RE, but on FILE lines: YAML list files hold bodies
# in indented block scalars, so the fence's indentation here is stripped by
# the YAML parser before CALC_BLOCK_RE ever sees it. Indentation is preserved
# through the rewrite for the same reason.
FENCE_OPEN_RE = re.compile(r"^\s*```calc[^\n]*$")
FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")


# The spelling transformation lives in calc.rewrite_line -- one place, shared
# with the build error that quotes the suggested fix. Re-exported here so the
# rewrite engine (and tests that swap it) address it through this module.
rewrite_line = calc.rewrite_line


@dataclass
class CalcRewriteResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    # "rel:line  old -> new" for every calc line rewritten (or, on --dry-run,
    # every line the real run would rewrite).
    line_changes: list[str] = field(default_factory=list)
    # "rel:line [ID] text" for every old-spelling calc line inside a sealed
    # append-only entry -- left untouched, by design, and reported, never quiet.
    sealed_entries: list[str] = field(default_factory=list)
    baselines_updated: list[str] = field(default_factory=list)
    seals_updated: list[str] = field(default_factory=list)
    dry_run: bool = False


def _item_spans(rel: str, lines: list[str], items: list[Item]) -> list[tuple[int, int, Item]]:
    """(start, end, item) 0-indexed half-open line ranges bounding each item's
    own text, same construction as revise._item_spans: an md item's region
    runs from its front matter to the next item's front matter (its body
    included -- which is exactly where its calc fences live); a YAML item's
    region runs from its entry line to the next entry."""
    ordered = sorted(items, key=lambda i: i.source_line)
    spans = []
    for idx, item in enumerate(ordered):
        start = item.source_line - 1
        end = ordered[idx + 1].source_line - 1 if idx + 1 < len(ordered) else len(lines)
        spans.append((start, end, item))
    return spans


def _rewrite_file(
    project: Project, path: str, rel: str
) -> tuple[FileRewrite, list[str], list[str], list[int]]:
    source = textio.SourceText.of(path)
    text = source.text
    lines = source.lines
    items = [i for i in project.local_items if i.source_file == rel]
    spans = _item_spans(rel, lines, items)

    out = list(lines)
    errors: list[str] = []
    sealed: list[str] = []
    changed_lines: list[int] = []
    in_fence = False
    for i, line in enumerate(out):
        owner = next((s for s in spans if s[0] <= i < s[1]), None)
        if not in_fence:
            # A fence outside any item's region (a narrative page's example
            # pasted into a file header) is not this command's to rewrite.
            if owner is not None and FENCE_OPEN_RE.match(line):
                in_fence = True
            continue
        if FENCE_CLOSE_RE.match(line):
            in_fence = False
            continue
        new = rewrite_line(line)
        if new is None:
            continue
        _start, _end, item = owner
        if seal_mod.is_sealed(project, item):
            sealed.append(f"{rel}:{i + 1} [{item.id or '?'}] {line.strip()}")
            continue
        out[i] = new
        changed_lines.append(i + 1)

    after = source.render(out)
    return FileRewrite(path=path, rel=rel, before=text, after=after), errors, sealed, changed_lines


def _calc_snapshot(project: Project) -> dict[tuple[str, int], dict[str, tuple[str | None, str]]]:
    """(source_file, source_line) -> {name: (result, unit)} for every item
    with calcs. The before/after comparison this engine's guarantee rests on:
    a same-line text substitution never moves an item, so positions pair
    exactly."""
    return {
        (item.source_file, item.source_line): {
            c.name: (c.result, c.annotation) for c in item.calcs
        }
        for item in project.local_items
        if item.calcs
    }


def _snapshot_diff(before: dict, after: dict) -> list[str]:
    errors: list[str] = []
    for pos, calcs in sorted(before.items()):
        after_calcs = after.get(pos, {})
        for name, (result, unit) in sorted(calcs.items()):
            if result is None:
                # The line did not compute before the rewrite (a retired
                # spelling with a second defect, say). There is no value to
                # preserve; the post-rewrite validation guards that line.
                continue
            new_result, new_unit = after_calcs.get(name, (None, None))
            if (new_result, new_unit) == (result, unit):
                continue
            errors.append(
                f"{pos[0]}:{pos[1]} {name}: was {result!r} in unit {unit!r}, "
                f"now evaluates to {new_result!r} in unit {new_unit!r} -- "
                "a rewrite must not change what a calc computes"
            )
    return errors


def apply(project_root: str, dry_run: bool = False) -> CalcRewriteResult:
    """Rewrite every old-spelling calc line the project can safely move to
    the pipe form. See the module docstring for the full safety model."""
    config_path = os.path.join(project_root, "refdes-project.yaml")
    project_before = _load_and_validate(config_path)
    # Retired-spelling errors are the point of this command, not a reason to
    # refuse it: a project that needs the rewrite by definition fails the
    # build once the old spelling is an error. Every other error still
    # refuses, and the post-rewrite validation stays fully strict.
    blocking = [d for d in _blocking_errors(project_before)
                if d.code != RETIRED_UNIT_SPELLING]
    if blocking:
        return CalcRewriteResult(
            ok=False,
            errors=[
                (
                    "project has existing build errors -- fix those first, so a "
                    "calc that changes meaning under this rewrite can't hide "
                    "behind an already-broken build"
                )
            ]
            + [str(d) for d in blocking],
        )

    snapshot_before = _calc_snapshot(project_before)

    rewrites: list[FileRewrite] = []
    sealed_entries: list[str] = []
    all_errors: list[str] = []
    rels = sorted({item.source_file for item in project_before.local_items})
    for rel in rels:
        path = os.path.join(project_before.root, *rel.split("/"))
        rw, errors, sealed, _changed = _rewrite_file(project_before, path, rel)
        all_errors += errors
        sealed_entries += sealed
        if rw.after != rw.before:
            rewrites.append(rw)

    if all_errors:
        return CalcRewriteResult(ok=False, errors=all_errors)

    if not rewrites:
        return CalcRewriteResult(
            ok=True, dry_run=dry_run, sealed_entries=sealed_entries
        )

    if dry_run:
        return _dry_run(config_path, project_before, rewrites, sealed_entries, snapshot_before)

    old_hashes = {item.id: item.content_hash for item in project_before.local_items}
    old_calc_hashes = {
        item.id: build_mod.calc_hash_for(item) for item in project_before.local_items
    }

    write_rewrites(rewrites)
    original_seals = _capture_seal_files(project_before)

    def _rollback() -> None:
        restore_rewrites(rewrites)
        _restore_seal_files(original_seals)

    try:
        project_after = _load_and_validate(config_path)
    except Exception as exc:  # noqa: BLE001 -- SchemaError and anything else a broken rewrite raises on load; all of it rolls back
        _rollback()
        return CalcRewriteResult(
            ok=False,
            errors=[f"rewritten project no longer loads: {exc} -- rolled back"],
        )

    after_blocking = _blocking_errors(project_after)
    if after_blocking:
        _rollback()
        return CalcRewriteResult(
            ok=False,
            errors=["rewritten project has build errors -- rolled back:"]
            + [str(d) for d in after_blocking],
        )

    value_errors = _snapshot_diff(snapshot_before, _calc_snapshot(project_after))
    if value_errors:
        _rollback()
        return CalcRewriteResult(
            ok=False,
            errors=[
                "a rewritten calc no longer evaluates to what it did before -- rolled back:"
            ]
            + value_errors,
        )

    new_hashes = {item.id: item.content_hash for item in project_after.local_items}
    new_calc_hashes = {
        item.id: build_mod.calc_hash_for(item) for item in project_after.local_items
    }

    seals_updated = _carry_forward_seals(project_before, old_hashes, new_hashes)
    baselines_updated, _skipped = carry_forward_baselines(
        project_before,
        old_hashes,
        new_hashes,
        old_calc_hashes=old_calc_hashes,
        new_calc_hashes=new_calc_hashes,
    )

    line_changes: list[str] = []
    for rw in rewrites:
        line_changes += _line_diff_report(rw.rel, rw.before, rw.after)

    return CalcRewriteResult(
        ok=True,
        changed_files=sorted(r.rel for r in rewrites),
        line_changes=line_changes,
        sealed_entries=sealed_entries,
        baselines_updated=baselines_updated,
        seals_updated=seals_updated,
    )


def _dry_run(
    config_path: str,
    project_before: Project,
    rewrites: list[FileRewrite],
    sealed_entries: list[str],
    snapshot_before: dict,
) -> CalcRewriteResult:
    """Full-fidelity dry run on a throwaway copy of the tree: the same writes,
    the same reload-and-validate, the same before/after calc comparison -- so
    `--dry-run`'s report is what the real run would do, including whether it
    would refuse. The real tree is never touched."""
    import shutil
    import tempfile

    root = os.path.dirname(config_path)
    tmp = tempfile.mkdtemp(prefix="refdes-calc-rewrite-")
    try:
        copy = os.path.join(tmp, "proj")
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns("_site", ".git"))
        for rw in rewrites:
            dest = os.path.join(copy, *rw.rel.split("/"))
            textio.write_text(dest, rw.after)
        copy_config = os.path.join(copy, "refdes-project.yaml")
        try:
            project_after = _load_and_validate(copy_config)
        except Exception as exc:  # noqa: BLE001 -- any load failure is a refusal the dry run must report
            return CalcRewriteResult(
                ok=False,
                errors=[f"would fail: rewritten project no longer loads: {exc}"],
                sealed_entries=sealed_entries,
                dry_run=True,
            )
        blockers = _blocking_errors(project_after)
        if blockers:
            return CalcRewriteResult(
                ok=False,
                errors=["would fail: rewritten project has build errors:"]
                + [str(d) for d in blockers],
                sealed_entries=sealed_entries,
                dry_run=True,
            )
        value_errors = _snapshot_diff(snapshot_before, _calc_snapshot(project_after))
        if value_errors:
            return CalcRewriteResult(
                ok=False,
                errors=["would fail: a rewritten calc changes meaning:"]
                + value_errors,
                sealed_entries=sealed_entries,
                dry_run=True,
            )
        line_changes: list[str] = []
        for rw in rewrites:
            line_changes += _line_diff_report(rw.rel, rw.before, rw.after)
        return CalcRewriteResult(
            ok=True,
            changed_files=sorted(r.rel for r in rewrites),
            line_changes=line_changes,
            sealed_entries=sealed_entries,
            dry_run=True,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
