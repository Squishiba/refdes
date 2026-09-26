"""Read-only browsing of a cited source file, for the editor's source-value
picker (docs/design/editor-source-picker.md -- Slice A, "the service reads").

Three reads and no writes: which of this item's own cited files a reader can
list, what rows one of those files holds, and the calc line a picked
`(path, key)` would compose to. Accepting a pick writes the item and the
lockfile and is Slice B; the panel is Slice C. Nothing in this module writes
anything, and nothing in it is reachable for a file the item has not already
cited.

The confinement is inherited rather than reimplemented, in the order it
applies:

- **Only a file this item cites.** Every path goes through
  `citations.authorize_source_path` -- the function `refdes fetch` uses to
  decide what to extract and evaluation uses to decide which lock record to
  read -- so the picker can never be authorized for something the fetcher
  would refuse, and its refusal is that function's own message. The path a
  payload carries back is the canonical project-relative one this call
  returns.
- **Only a file with a registered reader.** Dispatch is `sources.reader_for`
  by extension, exactly as extraction dispatches. A cited `.xlsx`, `.pdf`,
  `.py` or extensionless file is refused with the registry's own words and is
  never opened; there is no fallback text parse here either.
- **Bounded.** The byte and row caps live in `refdes.sources`, where the file
  is read, so they bound the read rather than the response.

**No absolute server path leaves the process, in any string.** That has to hold
for the reader's per-row diagnostics and not just for the `path` field, and it
is enforced by *naming* rather than by scrubbing: the reader is given the file
to read (`project.root + canon`) and, separately, `label=canon` -- the only
name it is allowed to say out loud -- so every message it produces is already
project-relative. An earlier version of this module rewrote the absolute path
out of the reader's text after the fact, and covered one branch and not the
other; see `_listing`.

Reads are allowed on a sealed or imported item (`editor-source-picker.md` §9
Q6, recommended A): seeing where a value came from is review, and a sealed
entry's readers do exactly that. The refusal that belongs there is Accept's,
because Accept is a body write, and it is already inherited from the edit
route.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .. import calc as calc_mod
from .. import citations as citations_mod
from .. import sources as sources_mod
from ..model import Item, Project

# The left side of the composed line is an assignment, and `calc.ASSIGN_RE` is
# the evaluator's own grammar for one, so this is a constraint of the line
# being composed rather than a naming policy invented for the picker: a name
# with a space or an operator in it would not parse as an assignment later.
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SourceRefusal(Exception):
    """The request named something this item may not read.

    Carries the reason verbatim -- `authorize_source_path`'s own words when
    that is what refused, the registry's or the row's when it is what did --
    because the panel shows the reason rather than paraphrasing it, and a
    paraphrased "not allowed" would hide which of two rules said no.
    """


def _lockfile(project: Project) -> dict[str, dict]:
    """The citation lockfile, read only. `build` keeps its parsed copy on the
    project, so a request does not re-read a file the loaded model already
    holds -- and never writes one, which is Slice B's job and not this one's.
    """
    records = getattr(project, "_source_lock", None)
    if records is None:
        records = citations_mod.load_lockfile(project)
    return records


def _target(project: Project, canon: str) -> str:
    """The file on disk for a canonical project-relative path. Every path this
    module opens arrives from `authorize_source_path`, which has already
    refused an absolute path, a scheme, a backslash and anything that escapes
    the root by `..` or by symlink."""
    return os.path.join(project.root, canon)


def _authorise(project: Project, item: Item, path: str) -> str:
    """The canonical path, or `SourceRefusal` carrying the authorizer's own
    message. This is the same call, on the same arguments, that
    `citations.fetch_all` and the source resolver make -- the picker is a third
    caller of one rule, not a second copy of it."""
    canon, why = citations_mod.authorize_source_path(project, item, path)
    if why:
        raise SourceRefusal(why)
    return canon


def _reader(canon: str) -> sources_mod.SourceReader:
    """The one reader for this file's extension, or a refusal quoting the
    registry. Dispatch happens before anything is opened, so an unreadable
    type costs nothing and reveals nothing about the file."""
    try:
        return sources_mod.reader_for(canon)
    except sources_mod.SourceExtractionError as exc:
        raise SourceRefusal("; ".join(exc.problems)) from exc


def _entry_dict(entry: sources_mod.SourceEntry) -> dict:
    """One row as the wire sees it. `value` is what the file holds now and what
    a pick would extract; `pinned` (added by the caller, next to it) is what the
    lockfile recorded and what the build keeps evaluating. The two are different
    in kind and the payload says so rather than collapsing them into one
    number."""
    return {
        "key": entry.key,
        "raw": entry.raw,
        "value": entry.value,
        "line": entry.line,
        "context": [{"name": name, "text": text} for name, text in entry.context],
        "selectable": entry.selectable,
        "problem": entry.problem,
    }


def _listing(project: Project, canon: str, reader: str) -> dict:
    """The rows of one cited file, as a payload.

    The reader is handed `project.root + canon` -- that is the file to read --
    and `label=canon` -- that is the only name it is allowed to say out loud.
    Every string it produces is therefore already project-relative before it
    gets here: the whole-file diagnostics of a failure *and* the per-row
    `problem` of a success. Nothing is rewritten after the fact, which is the
    point: a leak this module once had came from a post-hoc fixup that covered
    one branch and not the other, and a `label` cannot be forgotten by the next
    thing added to a row.

    A file `extract()` cannot read -- no `key` or `value` column, a duplicated
    header, a malformed CSV, an empty file, a file above the byte cap -- is
    answered with the reader's problems verbatim and no rows at all: a file
    `fetch` cannot read is a file the picker must not browse. Those are panel
    states, not request failures, so they are a 200 with nothing to pick."""
    target = _target(project, canon)
    try:
        listing = sources_mod.list_entries(Path(target), label=canon)
    except sources_mod.SourceExtractionError as exc:
        return {
            "path": canon,
            "reader": reader,
            "entries": [],
            "truncated": False,
            "rows": 0,
            "problems": list(exc.problems),
        }
    return {
        "path": canon,
        "reader": reader,
        "entries": [_entry_dict(entry) for entry in listing.entries],
        "truncated": listing.truncated,
        "rows": listing.rows_read,
        "problems": [],
    }


# ------------------------------------------------------------------ 1: the files


def _status_by_canon(project: Project, item: Item) -> dict:
    """This item's citation statuses keyed by canonical path. They were filled
    in by the `verify()` the snapshot build already ran, so the picker's pin
    state is the build's own state -- the same words a `refdes build` warning
    would use for the same file, with no second hash of the same bytes. An
    imported item's citations are not verified (they are not this project's to
    verify), so its file list carries pin state only where the lockfile has it.
    """
    out: dict[str, object] = {}
    for status in item.citations:
        try:
            _kind, canon = citations_mod.classify(project.root, status.spec.path)
        except citations_mod.CitationError:
            continue  # a refused path is validation's to report, not the panel's
        out[canon] = status
    return out


def files_payload(project: Project, item: Item) -> dict:
    """§2.1: the item's own cited files that a reader can read, each with its pin
    state and the values already pinned for it.

    A citation that cannot become a repo-local file a reader can open is a
    `problem`, not a file: a remote URL, a path that escapes the root, a type
    with no reader. Listing it is how the author finds out why the picker
    cannot offer it, which is the whole of the honest gap in
    editor-source-picker.md §8 -- an item that cites no CSV gets an empty
    picker, and here is why.
    """
    records = _lockfile(project)
    statuses = _status_by_canon(project, item)
    files: list[dict] = []
    problems: list[dict] = []
    seen: set[str] = set()
    told: set[str] = set()
    for spec in citations_mod.item_specs(project, item):
        try:
            canon = _authorise(project, item, spec.path)
        except SourceRefusal as exc:
            if spec.path not in told:
                told.add(spec.path)
                problems.append({"path": spec.path, "problem": str(exc)})
            continue
        if canon in seen:
            continue  # the same file cited twice is one file
        seen.add(canon)
        try:
            reader = sources_mod.reader_for(canon)
        except sources_mod.SourceExtractionError as exc:
            problems.append({"path": canon, "problem": "; ".join(exc.problems)})
            continue
        record = records.get(canon) or {}
        state, detail = _pin_state(project, canon, record, statuses.get(canon))
        files.append({
            "path": canon,
            "reader": reader.name,
            "state": state,
            "detail": detail,
            "sha256": str(record.get("sha256") or ""),
            "fetched": str(record.get("fetched") or ""),
            "pinned_values": {
                key: citations_mod.locked_source_value(record, key)
                for key in sorted(record.get("values") or {})
            },
        })
    return {"item": item.id, "files": files, "problems": problems}


def _pin_state(project: Project, canon: str, record: dict, status) -> tuple[str, str]:
    """(state, detail) for one cited file, in the vocabulary `verify()` already
    uses for it: `unpinned` when the lockfile has no record, otherwise that
    record's own state from the build, and `missing` for a cited file that is
    not on disk (a state the build only reaches for a local citation, so it is
    worked out here rather than re-hashed)."""
    if not record:
        return "unpinned", (
            f"citation to {canon} has no fetched record; run 'refdes fetch "
            f"--path {canon}' to pin it"
        )
    if status is not None and status.state != "ok":
        return status.state, status.detail
    if not os.path.isfile(_target(project, canon)):
        return "missing", f"cited local file {canon!r} does not exist"
    return "ok", ""


# ------------------------------------------------------------------ 2: the rows


def _with_pin(entry: dict, record: dict) -> dict:
    """One row with the lockfile's value for its key beside the file's.

    The two numbers are deliberately different in kind and the payload says so:
    `value` is what the file holds now and what a pick would extract, while
    `pinned` is what the lockfile recorded and what the build keeps evaluating
    even after the file moves on. `changed` is the gap between them, and it is
    false whenever there is nothing to compare -- an unparseable cell has not
    drifted from a number, and an unpinned key has nothing to drift from."""
    pinned = citations_mod.locked_source_value(record, entry["key"])
    entry["pinned"] = pinned
    entry["changed"] = bool(pinned) and bool(entry["value"]) and pinned != entry["value"]
    return entry


def entries_payload(project: Project, item: Item, path: str, query: str = "") -> dict:
    """§2.2/§5: the rows of one cited file, read from the file on disk, with the
    value the lockfile pins for each key beside it."""
    canon = _authorise(project, item, path)
    reader = _reader(canon)
    payload = _listing(project, canon, reader.name)
    if payload["problems"]:
        return payload
    record = _lockfile(project).get(canon) or {}

    needle = (query or "").strip().casefold()
    payload["entries"] = [
        _with_pin(entry, record)
        for entry in payload["entries"]
        if not needle or needle in entry["key"].casefold()
        # ^ a display filter: it changes which rows are shown, never what a row
        # is. A broken row filtered in is still broken and marked.
    ]
    payload["query"] = query or ""
    # The cap counts rows *read*, so a narrow filter cannot buy a bigger file;
    # what it narrows is the payload, and the row count reported stays the
    # number of rows the file gave up before the cap.
    payload["limits"] = {
        "max_rows": sources_mod.MAX_LIST_ROWS,
        "max_bytes": sources_mod.MAX_LIST_BYTES,
    }
    if payload["truncated"]:
        payload["truncation"] = (
            f"stopped at the {sources_mod.MAX_LIST_ROWS}-row cap; the rest of "
            "this file was not read, so it is in no count here"
        )
    return payload


# ------------------------------------------------------------------ 3: the line


def _proposed_name(key: str) -> str:
    """A variable name derived from the key: lowercased, every run of
    non-alphanumerics to one underscore. A proposal, not a decision -- the
    author edits it, and nothing is written either way."""
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_") or "value"


def _item_units(item: Item) -> list[str]:
    """Units this item's own calc lines already declare, `1` first.

    `1` is what a dimensionless value is written with
    (docs/design/calc-sources.md §6), and it is listed as a *suggestion* like
    the rest of them: a defaulted unit is the silent 1000x wrong answer this
    whole feature is shaped around, so the panel offers and the author picks.
    """
    used = {line.annotation.strip() for line in item.calcs if line.annotation.strip()}
    return ["1"] + sorted(u for u in used if u != "1")


def _item_names(item: Item) -> set[str]:
    """Every name this item's calc blocks already assign, from the lines the
    evaluator produced for it. A collision is a build error the diagnostic gate
    would refuse anyway (the evaluator's own whole-item duplicate check), so
    catching it here is a courtesy and not a new rule."""
    return {line.name for line in item.calcs if line.name}


def _checked_unit(value: str, unit: str) -> None:
    """Raise unless `unit` labels `value`, through the same pint call
    evaluation makes for a `source()` line: `1` means dimensionless, anything
    else goes through `_to_pint_units` (which applies the project's unit
    aliases) into `quantity`. An unknown unit is refused here, on the panel,
    rather than becoming a failed calc row after a save."""
    if not unit:
        return
    spelled = "" if unit == "1" else calc_mod._to_pint_units(unit)
    try:
        calc_mod.quantity(value, spelled)
    except calc_mod.CalcError as exc:
        raise SourceRefusal(f"unknown unit {unit!r} in declaration") from exc


def propose_payload(
    project: Project,
    item: Item,
    *,
    path: str,
    key: str,
    unit: str = "",
    name: str = "",
) -> dict:
    """§7: the exact calc line a picked `(path, key, unit, name)` would insert,
    composed here rather than in the browser, and the row it was read from.

    Nothing is written and nothing is selected. With no `unit` there is no line
    yet -- the unit is the author's to declare and this endpoint will not
    supply one, which is why `line` is null and `complete` is false rather than
    a default appearing in the gap.
    """
    canon = _authorise(project, item, path)
    reader = _reader(canon)
    listing = _listing(project, canon, reader.name)
    entry = next((e for e in listing["entries"] if e["key"] == key), None)
    if entry is None:
        if listing["problems"]:
            raise SourceRefusal("; ".join(listing["problems"]))
        raise SourceRefusal(
            f"no row has the key {key!r} in {canon} -- the keys come from the "
            "file, so pick one of the ones it lists"
        )
    if entry["problem"]:
        raise SourceRefusal(f"{key!r} cannot be picked: {entry['problem']}")
    # The confirm panel is shown this one row, so the pin travels with it
    # rather than costing the panel a second request for a number it already
    # needs beside the live one (§3).
    entry = _with_pin(entry, _lockfile(project).get(canon) or {})

    chosen = (name or _proposed_name(key)).strip()
    if not _NAME_RE.match(chosen):
        raise SourceRefusal(
            f"{chosen!r} is not usable as a calc variable name; use letters, "
            "digits and underscores, starting with a letter or underscore"
        )
    taken = _item_names(item)
    if chosen in taken:
        raise SourceRefusal(
            f"{chosen!r} is already assigned in this item -- a name can only be "
            f"assigned once per item; pick another, e.g. {chosen + '_2'!r}"
        )

    unit = unit.strip()
    payload = {
        "path": canon,
        "key": key,
        "entry": entry,
        "name": chosen,
        "unit": unit,
        "units": _item_units(item),
        "line": None,
        "complete": False,
    }
    if not unit:
        payload["reason"] = (
            "the file supplies a bare number, so the unit is yours to declare -- "
            "there is no default; '1' means dimensionless"
        )
        return payload
    _checked_unit(entry["value"], unit)
    payload["line"] = _compose(chosen, canon, key, unit)
    payload["complete"] = True
    return payload


def _compose(name: str, canon: str, key: str, unit: str) -> str:
    """`name = source("path", "key") | unit`, checked against the evaluator's
    own grammar before it is returned.

    The check is the point: the browser never assembles this string, and
    `source()`'s grammar is two string literals with no escape in them, so a
    path or key holding a quote is a pair the grammar cannot express. That is
    refused here with a reason, and anything else that fails to round-trip is a
    composition bug -- raised, not returned as a line that will not parse later.
    """
    for text, what in ((canon, "path"), (key, "key")):
        if '"' in text or "\\" in text:
            raise SourceRefusal(
                f"the {what} {text!r} contains a quote or a backslash, which "
                "source() cannot express -- source() takes two string literals "
                "with no escapes, so this pair has no source() spelling"
            )
    line = f'{name} = source("{canon}", "{key}") | {unit}'
    # The whole line must read back as an assignment, a pipe unit, and a
    # source() call naming exactly this path and key -- the same three steps
    # the evaluator takes, in the same order (`source_calls_in_block` strips
    # the pipe unit before the assignment is split and the right-hand side
    # parsed). Anything less is a line that would fail to evaluate later, and a
    # later failure is the expensive kind.
    pipe = calc_mod.PIPE_UNIT_RE.match(line)
    code = pipe.group("lhs") if pipe else ""
    assigned = calc_mod.ASSIGN_RE.match(code)
    parsed = calc_mod.parse_source_call(assigned.group(2)) if assigned else None
    if assigned is None or assigned.group(1) != name:
        raise RuntimeError(f"composed source line does not round-trip: {line!r}")
    if pipe is None or pipe.group("unit") != unit:
        raise RuntimeError(f"composed source unit does not round-trip: {line!r}")
    if parsed is None or (parsed[0], parsed[1]) != (canon, key):
        raise RuntimeError(
            f"composed source line parses as {parsed[:2] if parsed else None!r}, "
            f"not {(canon, key)!r}"
        )
    return line
