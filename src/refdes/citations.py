"""Datasheet citations: declared intent in items, computed provenance in a lockfile.

An item's `citations:`-typed field says what it means to cite -- a url, maybe a
rev, page, or part number, and whether the bytes should be kept locally. That
is all ordinary invalidate-mode data, hashed like any other field.

What a citation actually *resolved to* -- its sha256, when it was fetched,
whether it was kept -- is a different kind of fact: it changes when someone
runs `refdes fetch`, not when someone edits an item. Mixing it into the item
would mean re-fetching a datasheet could retroactively mark a sealed log entry,
or any other suspect-link consumer of an item's content hash, as edited. So it
lives instead in a committed lockfile, `.refdes/citations.yaml`, keyed by path.

A citation's `path:` is one field dispatched on scheme (finding 25 Part 2):
`http`/`https` means remote -- fetched, hashed, optionally kept, exactly as
ever -- and anything else means a file inside the project, relative to the
project root, hashed from its local bytes at build time. Absolute paths, drive
letters, backslashes, and anything that escapes the project root are refused,
never guessed; `keep_copy:` on a local path is a hard error.

The bytes themselves are a third kind of fact, and the biggest: `keep_copy: true`
opts a citation into keeping a local copy, content-addressed at
`.refdes/copies/<sha256><ext>`. That directory is gitignored -- manufacturer
datasheets are generally copyrighted, so keeping copies is opt-in and defaults
off. Hash-only "pinned but not kept" is a first-class, complete mode on its
own.

The field used to be called `vendor:` -- retired because a hardware engineer
reads `vendor` next to `part_number` as the company that makes the part (see
docs/design/vocabulary-review.md S1). Writing `vendor:` is a loud validation
error naming `keep_copy:`; a pre-rename `.refdes/vendor/` directory or `vendored:`
lockfile key is reported, never silently ignored (see `legacy_notices`).

`refdes fetch` is the only thing in this module that touches the network, and
only when actually invoked. Everything else here -- `verify`, `by_path` --
reads only the lockfile, the local copies dir, and (for local citations)
files inside the project, so `build` and `check` stay hermetic.
"""

from __future__ import annotations

import difflib
import hashlib
import io
import os
import posixpath
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import yaml

from . import boards as boards_mod
from . import calc as calc_mod
from . import sources as sources_mod
from . import textio
from .model import CitationSpec, CitationStatus, Item, PartUsage, Project
from .parse import yaml_safe_load

LOCKFILE = ".refdes/citations.yaml"
COPIES_DIR = ".refdes/copies"
# Pre-rename spellings (the `vendor:` era, shipped through v0.5.0). Nothing
# reads them; `legacy_notices` exists so a project that still has them is told
# out loud instead of silently losing its local copies.
LEGACY_VENDOR_DIR = ".refdes/vendor"
LEGACY_LOCKFILE_KEY = "vendored"


class CitationError(Exception):
    pass


# ------------------------------------------------------------------------ paths


def lockfile_path(project: Project) -> str:
    return os.path.join(project.root, LOCKFILE)


def copies_dir(project: Project) -> str:
    return os.path.join(project.root, COPIES_DIR)


def kept_copy_path(project: Project, sha256: str, path: str) -> str:
    ext = os.path.splitext(urlparse(path).path)[1]
    return os.path.join(copies_dir(project), f"{sha256}{ext}")


def legacy_notices(project: Project, records: dict[str, dict]) -> list[tuple[str, str]]:
    """(severity, message) for pre-rename `vendor:`-era artifacts on disk.

    Two shapes strand data silently without this: a `.refdes/vendor/`
    directory nothing reads any more, and lockfile records still keyed
    `vendored:` -- which the renamed reader would see as "no keep_copy flag",
    report every vendored citation as hash-only, and call it a day. That is
    the success-while-doing-nothing shape this project's history says to
    refuse, so the lockfile half is an error, not a shrug."""
    out: list[tuple[str, str]] = []
    if os.path.isdir(os.path.join(project.root, LEGACY_VENDOR_DIR)):
        out.append((
            "warning",
            f"found a {LEGACY_VENDOR_DIR}/ directory: the local-copy directory "
            f"was renamed to {COPIES_DIR}/ -- move the blobs across (or re-run "
            f"'refdes fetch'); nothing reads {LEGACY_VENDOR_DIR}/ any more",
        ))
    stale = sorted(
        path
        for path, record in records.items()
        if isinstance(record, dict) and LEGACY_LOCKFILE_KEY in record
    )
    if stale:
        out.append((
            "error",
            f"the citation lockfile still uses the pre-rename key "
            f"'{LEGACY_LOCKFILE_KEY}:' for: {', '.join(stale)} -- the citation "
            f"field vendor: was renamed to keep_copy: and its lockfile key to "
            f"kept_copy:; rename the key in {LOCKFILE} or re-pin with 'refdes "
            f"fetch --update'",
        ))
    return out


# ---------------------------------------------------------------- classification

REMOTE_SCHEMES = ("http", "https")


def classify(project_root: str, value: str) -> tuple[str, str]:
    """Dispatch one citation `path:` value: ("remote", value) for http(s) URLs,
    ("local", canonical project-root-relative path) for everything else.

    Refuses rather than guesses (finding 25 Part 2): a scheme that is not
    http/https -- including the single-letter scheme a Windows drive letter
    parses as (`C:\\sch.pdf` is `scheme='c'` to urlparse) and `file:` -- is an
    error, as are absolute paths, UNC prefixes, backslashes (a Windows-path
    tell and non-portable anyway), and anything whose normalized form escapes
    the project root via `..` or whose resolved target does (symlinks). The
    canonical local form is slash-separated and normpath'd, so the lockfile key
    and the hash target never depend on how the author spelled it.
    """
    value = (value or "").strip()
    if not value:
        raise CitationError("citation path is empty")
    scheme = urlparse(value).scheme
    if scheme.lower() in REMOTE_SCHEMES:
        return "remote", value
    if scheme:
        hint = (
            "; this looks like a Windows drive letter, not a scheme"
            if len(scheme) == 1
            else ""
        )
        raise CitationError(
            f"citation path {value!r} has scheme {scheme!r}; only http/https "
            f"URLs are remote, and a local path must be project-relative "
            f"without a scheme{hint}"
        )
    if "\\" in value:
        raise CitationError(
            f"citation path {value!r} contains a backslash; local paths must "
            f"be project-relative and slash-separated"
        )
    if value.startswith("/"):
        raise CitationError(
            f"citation path {value!r} is absolute; local paths must be "
            f"relative to the project root"
        )
    canon = posixpath.normpath(value)
    if canon == "." or canon == ".." or canon.startswith("../"):
        raise CitationError(
            f"citation path {value!r} escapes the project root"
        )
    resolved = os.path.realpath(os.path.join(project_root, canon))
    root_real = os.path.realpath(project_root)
    if resolved != root_real and not resolved.startswith(root_real + os.sep):
        raise CitationError(
            f"citation path {value!r} resolves outside the project root "
            f"(via a symlink?)"
        )
    return "local", canon


def case_mismatch(project_root: str, rel: str) -> str | None:
    """The on-disk name for `rel` if it exists but only case-insensitively --
    a path that builds on this machine and vanishes in a Linux CI checkout.
    None when the spelling matches disk exactly or the file is absent (its
    absence is reported as a missing file, not a case note)."""
    target = os.path.join(project_root, rel)
    if not os.path.isfile(target):
        return None
    parent = project_root
    mismatched = False
    for part in rel.split("/"):
        try:
            names = os.listdir(parent)
        except OSError:
            return None
        if part in names:
            parent = os.path.join(parent, part)
            continue
        folded = [n for n in names if n.lower() == part.lower()]
        if not folded:
            return None
        mismatched = True
        parent = os.path.join(parent, folded[0])
    return parent if mismatched else None


# ------------------------------------------------------------- PDF outline
#
# `section:` resolution (finding 23 Part 2). A datasheet's own outline is the
# only page number that survives a re-revision, so an author may cite the title
# instead of a number. Resolution happens exclusively at `refdes fetch` time,
# against the bytes being pinned -- `build`/`check` read the recorded page out
# of the lockfile and never open a PDF. pypdf is an optional extra, imported
# lazily here and nowhere else, so a project with no `section:` never needs it.

PDF_EXTRA_ERROR = "section: needs the optional PDF extra: pip install refdes[pdf]"


class SectionError(Exception):
    """One `section:` that could not be resolved, with the message to show.

    `kind` distinguishes the cases the author has to act on differently --
    a PDF with no outline at all is not "the section disappeared", and a
    section that resolved last time and does not now is the sharpest signal
    of the set. Never collapse them: each is a different instruction."""

    def __init__(self, section: str, message: str, kind: str):
        super().__init__(message)
        self.section = section
        self.kind = kind


# Kinds, in the words the messages use.
KIND_NO_OUTLINE = "no_outline"
KIND_NO_MATCH = "no_match"
KIND_AMBIGUOUS = "ambiguous"
KIND_GONE = "gone"
KIND_UNREADABLE = "unreadable"
KIND_NO_LOCAL_BYTES = "no_local_bytes"


def _import_pypdf():
    """Import pypdf lazily -- the one place in the codebase that touches it.

    Raises SectionError (not ImportError) with the install hint, so a caller
    without the extra gets a diagnostic naming the fix rather than a traceback
    or, worse, a silently unresolved section.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise SectionError("", PDF_EXTRA_ERROR, "missing_extra") from exc
    return PdfReader


def _norm(title: str) -> str:
    """Outline-title normalisation: strip, collapse internal whitespace.
    Case-sensitive on purpose -- datasheet outlines capitalise section titles
    the way the prose cites them, and a case-insensitive match would turn two
    differently-titled entries into one."""
    return " ".join((title or "").split())


def _destination_page(reader, entry):
    """The 1-based page an outline entry points at, or None when it has no
    usable destination. An entry that cannot be resolved is left out of the
    title list rather than failing the whole document: it is one dead bookmark,
    not a broken PDF, and a cited title that happens to live behind it is then
    reported as "no outline entry titled ..." -- which is what is true."""
    try:
        return reader.get_destination_page_number(entry) + 1
    except Exception:  # noqa: BLE001 -- pypdf's resolvers raise whatever they like
        return None


def outline_titles(data: bytes) -> list[tuple[str, int]]:
    """Every outline entry as (title, 1-based page), nested entries included.

    [] means the PDF genuinely has no outline -- the caller reports that as its
    own case, never as "section not found". A PDF pypdf cannot open raises
    SectionError(kind=unreadable) carrying pypdf's own message.
    """
    PdfReader = _import_pypdf()
    try:
        reader = PdfReader(io.BytesIO(data))
        outline = reader.outline
    except Exception as exc:  # pypdf raises many types here, none of them ours
        raise SectionError(
            "", f"pypdf could not read the PDF: {exc}", KIND_UNREADABLE
        ) from exc

    out: list[tuple[str, int]] = []

    def walk(items) -> None:
        for entry in items:
            if isinstance(entry, list):
                walk(entry)
                continue
            title = getattr(entry, "title", None)
            if title is None:
                continue
            page = _destination_page(reader, entry)
            if page is None:
                continue
            out.append((str(title), page))

    try:
        walk(outline)
    except Exception as exc:  # a malformed outline tree, not a bad section
        raise SectionError(
            "", f"pypdf could not read the PDF outline: {exc}", KIND_UNREADABLE
        ) from exc
    return out


def match_outline_title(titles: list[tuple[str, int]], section: str) -> int:
    """The page one `section:` string resolves to, or SectionError.

    Exact match after normalisation, case-sensitive. Ambiguity is an error,
    never "take the first": two entries with the same title is the document
    telling you it cannot be resolved by title alone.
    """
    want = _norm(section)
    matches = [page for title, page in titles if _norm(title) == want]
    if len(matches) > 1:
        raise SectionError(
            section,
            f"the outline has {len(matches)} entries titled {section!r} "
            f"(pages {', '.join(str(p) for p in matches)}) -- cite page: instead",
            KIND_AMBIGUOUS,
        )
    if matches:
        return matches[0]
    hints = difflib.get_close_matches(want, [_norm(t) for t, _p in titles], n=5)
    hint = f"; closest outline titles: {', '.join(repr(h) for h in hints)}" if hints else ""
    raise SectionError(
        section, f"no outline entry titled {section!r}{hint}", KIND_NO_MATCH
    )


def resolve_sections(
    data: bytes,
    wanted: dict[str, list[str]],
    previous: dict | None = None,
) -> tuple[dict[str, int], list[SectionError]]:
    """Resolve every cited section of one document's pinned bytes.

    `wanted` maps a section string to the item ids citing it; `previous` is the
    path's lockfile record from before this fetch, which is what turns a
    no-longer-matching title into "the section you cited no longer exists in
    the new revision (was page N)" instead of a generic not-found.

    Returns (resolved map of section -> page, failures). A document with no
    outline at all, or bytes pypdf cannot open, is ONE failure for the
    document, not one per section -- the author's fix is the same for all of
    them and repeating it buries the message.
    """
    try:
        titles = outline_titles(data)
    except SectionError as exc:
        if exc.kind == "missing_extra":
            return {}, [SectionError("", PDF_EXTRA_ERROR, exc.kind)]
        return {}, [exc]
    if not titles:
        return {}, [
            SectionError(
                "",
                "this PDF has no outline (bookmarks); section: cannot be "
                "resolved -- cite page: instead",
                KIND_NO_OUTLINE,
            )
        ]

    resolved: dict[str, int] = {}
    failures: list[SectionError] = []
    prev_sections = (previous or {}).get("sections") or {}
    for section in sorted(wanted):
        try:
            resolved[section] = match_outline_title(titles, section)
        except SectionError as exc:
            if exc.kind == KIND_NO_MATCH and section in prev_sections:
                failures.append(
                    SectionError(
                        section,
                        f"the section you cited no longer exists in the new "
                        f"revision (was page {prev_sections[section]})",
                        KIND_GONE,
                    )
                )
            else:
                failures.append(exc)
    return resolved, failures


# --------------------------------------------------------------------- lockfile


def load_lockfile(project: Project) -> dict[str, dict]:
    path = lockfile_path(project)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml_safe_load(fh) or {}
    return dict(data.get("citations") or {})


def save_lockfile(project: Project, records: dict[str, dict]) -> None:
    path = lockfile_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# Refdes citation lockfile. Computed provenance for each cited path --\n"
        "# sha256, fetch timestamp, kept-copy flag, resolved sections and the\n"
        "# sha256 those sections were read out of -- keyed by the citation's\n"
        "# path (URL or project-relative file). Written only by\n"
        "# `refdes fetch`.\n"
        "# Never hand-edit the sha256.\n"
    )
    # The lockfile is machine-owned and rewritten whole, so its bytes must not
    # depend on the platform that last ran `refdes fetch`: a text-mode write
    # translated every LF to CRLF on Windows, and this file is committed.
    textio.write_text(
        path,
        header
        + yaml.safe_dump(
            {"citations": records}, sort_keys=True, default_flow_style=False
        ),
    )


# -------------------------------------------------------------------- collection


def item_specs(project: Project, item: Item) -> list[CitationSpec]:
    """Every citation one item declares across its `citations:`-typed fields.

    Public because three callers now need it and none of them should re-derive
    it: `collect()` (this project), `authorize_source_path()` (is this path one
    *this* item cites), and the editor's read-only source listing, which walks
    one item's own declarations so that the rule deciding what may be listed is
    the same rule deciding what may be read.
    """
    out: list[CitationSpec] = []
    spec = project.types.get(item.type)
    if spec is None:
        return out
    for fname, fspec in spec.fields.items():
        if fspec.type != "citations":
            continue
        entries = item.fields.get(fname)
        if not isinstance(entries, list):
            continue  # malformed -- reported by validate_items
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not entry.get("path"):
                continue  # malformed -- reported by validate_items
            out.append(
                CitationSpec(
                    field=fname,
                    index=index,
                    path=str(entry["path"]),
                    rev=str(entry.get("rev") or ""),
                    page=str(entry.get("page") or ""),
                    section=str(entry.get("section") or ""),
                    part_number=str(entry.get("part_number") or ""),
                    keep_copy=bool(entry.get("keep_copy", False)),
                    id=str(entry.get("id") or ""),
                )
            )
    return out


def collect(project: Project) -> list[tuple[Item, CitationSpec]]:
    """Every citation declared across every `citations:`-typed field, in order."""
    return [
        (item, cspec)
        for item in project.local_items
        for cspec in item_specs(project, item)
    ]


# ------------------------------------------------------------- calc source() uses


def authorize_source_path(project: Project, item: Item, path: str) -> tuple[str, str]:
    """`(canonical path, "")` when `path` is a repo-local file this item itself
    cites under `citations:`, else `("", why not)` (docs/design/calc-sources.md
    §1). The one rule shared by fetch (which keys to extract) and evaluation
    (which lock record to read), so the two can never disagree about what a
    `source()` line is allowed to name."""
    try:
        kind, canon = classify(project.root, path)
    except CitationError as exc:
        return "", str(exc)
    if kind != "local":
        return "", (
            f"{path!r} is a remote citation; source() reads only a repo-local "
            "file committed with the project"
        )
    for cspec in item_specs(project, item):
        try:
            ckind, ccanon = classify(project.root, cspec.path)
        except CitationError:
            continue
        if ckind == "local" and ccanon == canon:
            return canon, ""
    return "", (
        f"{item.id} does not cite {canon!r}; add it to this item's citations: "
        "(a citation on another item does not authorize this one)"
    )


@dataclass
class SourceUse:
    """One `name = source("path", "key")` line, located for fetch."""

    item: Item
    name: str
    path: str  # as authored
    key: str
    line: int | None
    canon: str = ""  # canonical local path when authorized
    problem: str = ""  # why it is not authorized ("" when it is)


def collect_source_uses(project: Project) -> list[SourceUse]:
    out: list[SourceUse] = []
    for item in project.local_items:
        for block, offset, _block_id in calc_mod.extract_blocks_with_lines(item.body):
            for line_offset, name, path, key in calc_mod.source_calls_in_block(block):
                line = (
                    item.body_line + offset + line_offset
                    if item.body_line is not None else None
                )
                canon, problem = authorize_source_path(project, item, path)
                out.append(SourceUse(item, name, path, key, line, canon, problem))
    return out


def locked_source_value(record: dict | None, key: str) -> str | None:
    """The canonical decimal text the lockfile pinned for `key`, or None."""
    entry = ((record or {}).get("values") or {}).get(key)
    if isinstance(entry, dict) and entry.get("value") is not None:
        return str(entry["value"])
    return None


def by_path(
    project: Project, board: str | None = None, workspace: str | None = None
) -> dict[str, list[CitationStatus]]:
    """`item.citations`, regrouped by path -- for `audit` and `references.html`.

    `board`/`workspace`, when given, scope this to that board's or workspace's
    own items, the same way `render._document_sections` and friends scope the
    other per-board/per-workspace reports. Callers pass at most one of the two.

    Only meaningful after `verify()` has run (via `build()`), which is what
    populates `item.citations` in the first place.

    A board also lists the citations of the items its `includes:` groups bring
    onto its pages (finding 33) -- displayed, not owned.
    """
    included = boards_mod.included_map(project, board)
    grouped: dict[str, list[CitationStatus]] = defaultdict(list)
    for item in project.local_items:
        if board is not None and not boards_mod.displays(item, board, included):
            continue
        if workspace is not None and item.workspace != workspace:
            continue
        for status in item.citations:
            grouped[status.spec.path].append(status)
    return dict(sorted(grouped.items()))


def by_part_number(
    project: Project, board: str | None = None, workspace: str | None = None
) -> dict[str, PartUsage]:
    """Every part number, regrouped by the exact string -- no normalization,
    no family grouping (docs/design/standard-library.md §10). Two sources,
    neither requiring a new declaration: a field literally named
    `part_number` (recognized by name, the same way `limit`/`options`/
    `checks` already are -- on any item type, not only `component`), and a
    citation's own nested `part_number` (`item.citations`, populated by
    `verify()`). `board`/`workspace` scope the same way `by_path` does, `includes:` included:
    a shared component a board includes is listed on its parts page.
    """
    included = boards_mod.included_map(project, board)
    grouped: dict[str, PartUsage] = {}

    def usage(part_number: str) -> PartUsage:
        return grouped.setdefault(part_number, PartUsage(part_number=part_number))

    for item in project.local_items:
        if board is not None and not boards_mod.displays(item, board, included):
            continue
        if workspace is not None and item.workspace != workspace:
            continue
        spec = project.types.get(item.type)
        if spec is not None and "part_number" in spec.fields:
            value = item.fields.get("part_number")
            if value:
                usage(str(value)).components.append(item)
        for status in item.citations:
            if status.spec.part_number:
                usage(status.spec.part_number).citers.append((item, status))

    return dict(sorted(grouped.items()))


# ------------------------------------------------------------------- verification


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(project: Project, require: bool = False) -> None:
    """Resolve every declared citation against the lockfile and the local copies.

    Hermetic -- reads `.refdes/citations.yaml`, `.refdes/copies/`, and cited
    local files, but touches no network. Severities:

      pre-rename artifacts  -- warning for a leftover `.refdes/vendor/`
                                directory; error for lockfile records still
                                keyed `vendored:` (see `legacy_notices`)
      no lockfile entry     -- info (routine until `refdes fetch` runs), or
                                error with `require` (CI)
      keep_copy: true, no blob   -- warning, or error with `require` (CI)
      blob hash mismatch    -- ERROR always, never soft-failed: a corrupted or
                                tampered local cache is not something to wave
                                through in CI
      local file missing    -- ERROR always: a cited file that isn't there is
                                not a routine state
      local file changed    -- warning naming every citer (review the change,
                                then re-pin), or error with `require` (CI)
      inconsistent keep_copy:    -- warning, always (not promoted by `require`;
      across citers of a       it is a hygiene note about the declaration, not
      shared url                a missing artifact)
    """
    records = load_lockfile(project)
    for severity, message in legacy_notices(project, records):
        (project.error if severity == "error" else project.warn)(message)

    entries = collect(project)
    if not entries:
        return
    severity = project.error if require else project.warn
    unpinned_severity = project.error if require else project.info

    grouped: dict[str, list[tuple[Item, CitationSpec]]] = defaultdict(list)
    changed_local: dict[str, list[str]] = defaultdict(list)
    for item, spec in entries:
        grouped[spec.path].append((item, spec))
        record = records.get(spec.path)
        status = _resolve(
            project, item, spec, record,
            severity, unpinned_severity, changed_local,
        )
        _apply_section(project, item, spec, record, status, severity)
        item.citations.append(status)

    source_drift = _source_drift(project, changed_local)
    for canon, citers in sorted(changed_local.items()):
        ids = ", ".join(sorted(set(citers)))
        if canon in source_drift:
            # The file feeds calc values: the generic "changed" note is not
            # loud enough, and would hide which numbers are now stale.
            (project.error if require else project.warn)(source_drift[canon])
            continue
        (project.error if require else project.warn)(
            f"local citation {canon!r} has changed since it was pinned -- "
            f"review the change, then run 'refdes fetch --update --path "
            f"{canon}' (cited by {ids})"
        )

    for path, citers in grouped.items():
        try:
            kind = classify(project.root, path)[0]
        except CitationError:
            continue  # refused path -- _resolve already flagged it; nothing to reconcile
        if kind != "remote":
            continue  # keep_copy: on a local path is a validation error, not a flag to reconcile
        keep_copy_flags = {spec.keep_copy for _item, spec in citers}
        if len(keep_copy_flags) > 1:
            ids = ", ".join(sorted({item.id for item, _spec in citers}))
            project.warn(
                f"citation {path!r} is cited with inconsistent keep_copy: flags "
                f"across {ids} -- pick one so the keep-a-copy decision is "
                f"unambiguous"
            )


def _source_drift(project: Project, changed_local: dict[str, list[str]]) -> dict[str, str]:
    """For each changed local file that feeds `source()` values, the loud
    warning text (docs/design/calc-sources.md section 11 Q2, decided
    2026-09-21): the file, every used key with the value the lockfile pinned
    against the value the file holds now, and the exact command that accepts
    the change. The build keeps using the *locked* value regardless -- this
    only describes the gap, and marks the affected calc rows so the rendered
    item shows it too.

    Reading the file here is diagnostic only. The value a calc row evaluates
    to came from the lockfile before this ran and nothing below can alter it;
    if the file can no longer be read as a source at all, that is said in
    place of a value."""
    used: dict[str, dict[str, tuple[str, list[str]]]] = defaultdict(dict)
    for item in project.local_items:
        for canon, key, text in getattr(item, "_source_uses", []):
            if canon not in changed_local or text is None:
                continue
            _t, ids = used[canon].setdefault(key, (text, []))
            if item.id not in ids:
                ids.append(item.id)
    out: dict[str, str] = {}
    for canon, keys in sorted(used.items()):
        try:
            now = _extract_source_values(project, canon, {k: [] for k in keys})
            failure = ""
        except sources_mod.SourceExtractionError as exc:
            now, failure = {}, "; ".join(exc.problems)
        command = f"refdes fetch --update --path {canon}"
        parts = []
        for key, (locked, ids) in sorted(keys.items()):
            current = _value_text(now.get(key))
            who = ", ".join(sorted(ids))
            if failure:
                gap = f"locked {locked}, but the file can no longer supply it ({failure})"
            elif current == locked:
                gap = f"locked {locked}, file now {current} (this value is unchanged)"
            else:
                gap = f"locked {locked}, file now {current} (CHANGED)"
            parts.append(f"{key!r}: {gap} [used by {who}]")
            drift = f"{canon} changed: {key!r} {gap} -- accept with: {command}"
            for item in project.local_items:
                for line in item.calcs:
                    if line.source_path == canon and line.source_key == key:
                        line.source_drift = drift
        out[canon] = (
            f"SOURCE FILE CHANGED: {canon!r} no longer matches its pin, but the "
            f"build is still using the LOCKED values, not the file -- "
            + "; ".join(parts)
            + f". Review the change, then accept it with: {command}"
        )
    return out


def _apply_section(project, item, spec, record, status, severity) -> None:
    """Attach the lockfile's resolved page for `spec.section` to `status`.

    Reads the lockfile only -- a build never opens a PDF. All three outcomes
    are visible: a resolved page goes on the href and into the page cell; no
    resolved page (never fetched, or resolution failed) is reported with the
    same posture as an unpinned pin, because rendering a section citation with
    no page is the quiet wrong answer; and a `page:` that disagrees with the
    resolved page warns naming both, with the author's explicit `page:` winning
    for the href -- an explicit value is a decision, a resolved one an
    inference.
    """
    if not spec.section or status.state == "invalid":
        return
    sections = (record or {}).get("sections") or {}
    page = sections.get(spec.section)
    # A page is a fact about specific bytes. `refdes fetch` records which bytes
    # it read them out of; if that is not the sha256 now in the record, the page
    # belongs to a document this one is not, and rendering it would be the
    # silent-wrong-link failure this whole feature is here to avoid. Better a
    # citation with no page and a loud warning than a confident wrong page.
    pinned = str((record or {}).get("sha256") or "")
    resolved_against = str((record or {}).get("sections_sha256") or "")
    if page is not None and resolved_against != pinned:
        status.detail = (
            f"section {spec.section!r} of {spec.path} was resolved against "
            f"different bytes than the ones now pinned; run 'refdes fetch "
            f"--update --path {spec.path}' to re-resolve it"
        )
        severity(
            status.detail, file=item.source_file, line=item.source_line, item_id=item.id
        )
        return
    if page is None:
        status.detail = (
            f"section {spec.section!r} of {spec.path} has no resolved page in "
            f"the lockfile; run 'refdes fetch --path {spec.path}' to resolve it"
        )
        severity(
            status.detail, file=item.source_file, line=item.source_line, item_id=item.id
        )
        return
    status.section_page = str(page)
    if spec.page and str(spec.page) != str(page):
        project.warn(
            f"citation to {spec.path} gives page: {spec.page!r} but section "
            f"{spec.section!r} resolves to page {page}; the explicit page: is "
            f"used for the link -- fix one or the other",
            file=item.source_file, line=item.source_line, item_id=item.id,
        )


def _resolve(project, item, spec, record, severity, unpinned_severity, changed_local) -> CitationStatus:
    status = CitationStatus(spec=spec, item_id=item.id)
    try:
        kind, canon = classify(project.root, spec.path)
    except CitationError as exc:
        # Malformed path -- validate_items has already reported it with
        # file:line; resolving further would only duplicate the noise.
        status.state = "invalid"
        status.detail = str(exc)
        return status
    if kind == "local":
        return _resolve_local(
            project, item, spec, canon, record, status, unpinned_severity, changed_local
        )
    if record is None:
        status.state = "unpinned"
        status.detail = (
            f"citation to {spec.path} has no fetched record; run "
            f"'refdes fetch --path {spec.path}' to pin it"
        )
        unpinned_severity(
            status.detail, file=item.source_file, line=item.source_line, item_id=item.id
        )
        return status

    status.sha256 = str(record.get("sha256") or "")
    status.fetched = str(record.get("fetched") or "")
    status.kept_copy = bool(record.get("kept_copy", False))
    if not status.kept_copy:
        return status

    blob = kept_copy_path(project, status.sha256, spec.path)
    if not os.path.isfile(blob):
        status.state = "cache_missing"
        status.detail = (
            f"local copy of {spec.path} is missing at "
            f"{os.path.relpath(blob, project.root)}"
        )
        severity(status.detail, file=item.source_file, line=item.source_line, item_id=item.id)
        return status

    actual = _sha256_file(blob)
    if actual != status.sha256:
        status.state = "hash_mismatch"
        status.detail = (
            f"local copy of {spec.path} does not match its recorded hash "
            f"(the copy is tampered or corrupt)"
        )
        project.error(status.detail, file=item.source_file, line=item.source_line, item_id=item.id)
        return status

    if project.publish_datasheets:
        # Flattened (assets/datasheets/<sha256><ext>), not mirrored under
        # `.refdes/copies/` -- a dot-prefixed directory is skipped by several
        # static hosts, GitHub Pages via Jekyll included. Tracked separately
        # from `project.assets`, whose copy step mirrors source path to dest
        # path; here they differ, so render_site copies this dict instead.
        ext = os.path.splitext(blob)[1]
        status.local_path = f"datasheets/{status.sha256}{ext}"
        project.datasheet_assets[status.local_path] = blob
    return status


def _resolve_local(project, item, spec, canon, record, status, unpinned_severity, changed_local):
    """Resolve a repo-local citation (finding 25 Part 2): the file itself is
    the artifact -- no fetch, no copies dir, no publish_datasheets gate (the
    project wrote the file, so publishing a content-addressed copy is safe).
    A changed-but-unre-pinned file is a warning, not an error: the pin did its
    job by noticing, and re-pinning is a review decision, not a build failure.
    """
    status.remote = False
    target = os.path.join(project.root, canon)
    if not os.path.isfile(target):
        status.state = "missing"
        status.detail = f"cited local file {canon!r} does not exist"
        project.error(
            status.detail, file=item.source_file, line=item.source_line, item_id=item.id
        )
        return status
    on_disk = case_mismatch(project.root, canon)
    if on_disk:
        project.warn(
            f"citation path {spec.path!r} differs in case from the file on disk "
            f"({os.path.relpath(on_disk, project.root)}); a case-sensitive "
            f"checkout (e.g. Linux CI) would not find it",
            file=item.source_file, line=item.source_line, item_id=item.id,
        )
    if record is None:
        status.state = "unpinned"
        status.detail = (
            f"citation to {canon} has no fetched record; run "
            f"'refdes fetch --path {canon}' to pin it"
        )
        unpinned_severity(
            status.detail, file=item.source_file, line=item.source_line, item_id=item.id
        )
        return status

    status.sha256 = str(record.get("sha256") or "")
    status.fetched = str(record.get("fetched") or "")
    actual = _sha256_file(target)
    if actual != status.sha256:
        status.state = "hash_mismatch"
        status.detail = (
            f"local file {canon} does not match its pinned hash "
            f"(changed since it was last fetched)"
        )
        changed_local[canon].append(item.id)  # one diagnostic per file, naming every citer
        return status

    # Always published: the site link for a local citation is the pinned copy,
    # since the repo path itself is not a URL a published page can point at.
    ext = os.path.splitext(canon)[1]
    status.local_path = f"citations/{status.sha256}{ext}"
    project.datasheet_assets[status.local_path] = target
    return status


# ------------------------------------------------------------------------ fetch


def fetch_bytes(url: str, timeout: float = 30.0) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "refdes/fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FetchResult:
    path: str
    sha256: str = ""
    kept_copy: bool = False
    skipped: bool = False
    error: str = ""
    # One line per `section:` that could not be resolved against the bytes that
    # were just pinned. Separate from `error` because the pin itself succeeded
    # -- the file was fetched fine, only the outline lookup failed -- and the
    # caller must still report it loudly and exit non-zero.
    section_errors: list[str] = field(default_factory=list)
    # Sections that did resolve, as {section as written: page}, for the caller
    # to print next to the pin.
    sections: dict[str, int] = field(default_factory=dict)
    # calc `source()` extraction (docs/design/calc-sources.md section 5).
    # `source_errors` are failures that leave the path's old record untouched;
    # `source_values` is {key: canonical text} this run newly recorded or
    # changed; `source_changes` are the `path: key: old -> new` lines of an
    # update; `source_warnings` the advisory 1000x notes; `source_notes` plain
    # statements (e.g. "file changed, locked values kept").
    source_errors: list[str] = field(default_factory=list)
    source_values: dict[str, str] = field(default_factory=dict)
    source_changes: list[str] = field(default_factory=list)
    source_warnings: list[str] = field(default_factory=list)
    source_notes: list[str] = field(default_factory=list)


def _extract_source_values(
    project: Project, canon: str, keys: dict[str, list[str]]
) -> dict[str, dict]:
    """Every used key of one local file, in one parse, as lockfile `values`
    entries -- or SourceExtractionError. Nothing is written here: the caller
    replaces the path's record only if this returns."""
    reader = sources_mod.reader_for(canon)
    got = reader.extract(
        Path(os.path.join(project.root, canon)),
        [sources_mod.SourceRequest(canon, key) for key in sorted(keys)],
    )
    return {k: {"reader": v.reader, "value": v.text} for k, v in sorted(got.items())}


def _value_text(entry) -> str | None:
    return str(entry["value"]) if isinstance(entry, dict) and "value" in entry else None


def _diff_source_values(canon: str, old: dict, new: dict, result: FetchResult) -> None:
    """Fill `result` with what changed between two `values` maps: the
    `old -> new` diff lines, and the advisory 1000x note (never a block --
    section 6, decided 2026-09-19)."""
    for key in sorted(new):
        before, after = _value_text(old.get(key)), _value_text(new[key])
        if after is None:
            continue
        if before is None:
            result.source_values[key] = after
            continue
        if before == after:
            continue
        result.source_values[key] = after
        result.source_changes.append(f"{canon}: {key}: {before} -> {after}")
        try:
            old_d, new_d = Decimal(before), Decimal(after)
        except Exception:  # noqa: BLE001 -- a hand-edited lock value; the diff line still shows it
            continue
        if old_d != 0 and new_d != 0 and (new_d == old_d * 1000 or new_d * 1000 == old_d):
            result.source_warnings.append(
                f"{canon}: {key}: changed by exactly a factor of 1000 "
                f"({before} -> {after}) -- check the spreadsheet's unit (mW vs W?) "
                f"against the `| unit` on the calc line; advisory only"
            )


def _refresh_pinned_sources(
    project: Project, canon: str, existing: dict, keys: dict[str, list[str]],
    result: FetchResult,
) -> bool:
    """The no-`--update` half for a path that is already pinned: extract the
    used keys that are missing, but only from bytes that ARE the pinned bytes.
    True when the record changed."""
    values = existing.get("values") or {}
    if not keys:
        if values:
            existing.pop("values")  # nothing cites a key from this file any more
            return True
        return False
    target = os.path.join(project.root, canon)
    missing = sorted(k for k in keys if _value_text(values.get(k)) is None)
    pinned = str(existing.get("sha256") or "")
    if not os.path.isfile(target):
        if missing:
            result.source_errors.append(
                f"{canon}: source key(s) {', '.join(map(repr, missing))} were never "
                "extracted and the cited file is not on disk"
            )
        return False
    if _sha256_file(target) != pinned:
        if missing:
            result.source_errors.append(
                f"{canon}: source key(s) {', '.join(map(repr, missing))} were never "
                "extracted, and the file has changed since it was pinned -- "
                "extracting now would pair the old hash with new bytes. Review the "
                f"change, then run 'refdes fetch --update --path {canon}'"
            )
        else:
            result.source_notes.append(
                "the file changed since it was pinned; the locked source values "
                f"are kept -- accept the change with 'refdes fetch --update --path {canon}'"
            )
        return False
    try:
        new_values = _extract_source_values(project, canon, keys)
    except sources_mod.SourceExtractionError as exc:
        result.source_errors.extend(
            f"{p} (source key extraction; the record is unchanged)" for p in exc.problems
        )
        return False
    if new_values == values:
        return False
    _diff_source_values(canon, values, new_values, result)
    existing["values"] = new_values
    existing["fetched"] = _now_iso()
    return True


def _section_bytes(project, kind, canon, record):
    """The *pinned* bytes to resolve a section against, for a path that was not
    fetched this run (already pinned, no --update). (data, "") on success,
    (None, message) when they are not available.

    "pinned" is the whole point: a page number only means something next to the
    bytes it was read out of, so the bytes handed back are checked against the
    record's sha256 before anyone is allowed to resolve against them. Reading
    the current file without that check is how a section silently resolves to
    the page a heading moved to.
    """
    sha = str((record or {}).get("sha256") or "")
    if kind == "local":
        target = os.path.join(project.root, canon)
        if not os.path.isfile(target):
            return None, f"local file {canon!r} is not on disk"
        with open(target, "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != sha:
            return None, (
                "the file on disk changed since it was pinned; run 'refdes "
                f"fetch --update --path {canon}' to re-pin and resolve"
            )
        return data, ""
    blob = kept_copy_path(project, sha, canon)
    if not os.path.isfile(blob):
        return None, (
            "the kept bytes are not in .refdes/copies/, so the outline "
            "cannot be read offline -- run 'refdes fetch --update --path "
            f"{canon}' with the network available"
        )
    with open(blob, "rb") as fh:
        data = fh.read()
    # The blob's name is its sha256, so a mismatch is a corrupted cache rather
    # than a moved file -- and resolving against it would be resolving against
    # bytes nothing pinned.
    if hashlib.sha256(data).hexdigest() != sha:
        return None, (
            f"the local copy for {canon} does not match its pinned sha256"
        )
    return data, ""


def _section_failure(canon: str, err: SectionError, sections: dict[str, list[str]]) -> str:
    """One fetch-time section failure, naming the path, the section(s) and the
    citing item ids -- the three things an author needs to act on it."""
    if err.section:
        ids = ", ".join(sorted(set(sections.get(err.section) or [])))
        what = f"section {err.section!r} (cited by {ids})"
    else:
        names = ", ".join(repr(s) for s in sorted(sections))
        who = sorted({i for group in sections.values() for i in group})
        what = f"sections {names} (cited by {', '.join(who)})"
    return f"{canon}: {what}: {err}"


def fetch_all(
    project: Project,
    item_id: str | None = None,
    path: str | None = None,
    update: bool = False,
    fetcher=None,
) -> list[FetchResult]:
    """Fetch every path a citation declares (optionally scoped), pin it, and keep a local copy where asked.

    Only ever called from `refdes fetch` -- the one command allowed to touch the
    network, and only for remote citations: a local path is read from disk, so
    pinning one works with the network down. Already-pinned paths are skipped
    unless `update` is set, so a routine re-run does not re-download anything.

    `fetcher` defaults to the module-level `fetch_bytes`, looked up at call time
    (not bound as a parameter default) so tests can monkeypatch
    `citations.fetch_bytes` and have it take effect even through `refdes fetch`,
    which never passes `fetcher` itself.
    """
    fetcher = fetcher or fetch_bytes
    entries = collect(project)
    if item_id is not None:
        if project.item_by_id(item_id) is None:
            raise CitationError(f"no item {item_id!r} in this project")
        entries = [(item, spec) for item, spec in entries if item.id == item_id]
        if not entries:
            raise CitationError(f"item {item_id!r} declares no citations")
    if path is not None:
        entries = [(item, spec) for item, spec in entries if spec.path == path]
        if not entries:
            raise CitationError(f"no citation in this project cites {path!r}")

    wants_keep_copy: dict[str, bool] = defaultdict(bool)
    for item, spec in entries:
        wants_keep_copy[spec.path] = wants_keep_copy[spec.path] or spec.keep_copy

    # {canonical path: {section as written: [citing item ids]}} -- what each
    # path's outline has to be asked for, and whom to tell when the answer
    # fails. Collected from EVERY item in the project, not from this run's
    # scope: a page number is a fact about the bytes being pinned, so re-
    # pinning a path under `--item A` has to re-resolve B's section too, or B
    # is left citing a page of the file it used to be. Scoping a fetch narrows
    # which paths are re-pinned; it cannot narrow what a re-pin means.
    all_sections: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item, spec in collect(project):
        if not spec.section:
            continue
        try:
            _kind, canon = classify(project.root, spec.path)
        except CitationError:
            continue  # a refused path is validation's to report, not ours
        all_sections[canon][spec.section].append(item.id)

    records = load_lockfile(project)
    results: list[FetchResult] = []
    changed = False

    # {canonical path: {source key: [citing item ids]}} from EVERY item, for the
    # same reason as sections: a re-pin replaces the whole record, so it has to
    # carry every key anyone uses, not only this run's scope. A use that names
    # a file its own item does not cite is that fetch's error -- never a silent
    # extraction for an unauthorized reader of the file.
    source_keys: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for use in collect_source_uses(project):
        if use.problem:
            if item_id is None or use.item.id == item_id:
                results.append(FetchResult(
                    path=use.path,
                    error=f"{use.item.id}: source({use.path!r}, {use.key!r}): {use.problem}",
                ))
            continue
        source_keys[use.canon][use.key].append(use.item.id)

    for target in sorted(wants_keep_copy):
        try:
            kind, canon = classify(project.root, target)
        except CitationError as exc:
            # A refused path is this one citation's failure, not the whole
            # fetch's: report it and keep pinning the rest.
            results.append(FetchResult(path=target, error=str(exc)))
            continue
        want_keep_copy = wants_keep_copy[target]
        sections = {
            section: sorted(set(ids))
            for section, ids in sorted(all_sections.get(canon, {}).items())
        }
        if kind == "local" and want_keep_copy:
            raise CitationError(
                f"keep_copy: on local citation path {canon!r} is meaningless -- "
                f"a local file is already local"
            )
        if canon in records and not update:
            existing = records[canon]
            result = FetchResult(
                path=canon,
                sha256=str(existing.get("sha256") or ""),
                kept_copy=bool(existing.get("kept_copy")),
                skipped=True,
            )
            # A `section:` added to an already-pinned citation still has to be
            # resolved, or `refdes fetch` reports success while having done
            # nothing about it. But a recorded page is only as good as the bytes
            # it was read out of, and only as live as the citation that asked
            # for it: a section nobody cites any more goes, and a map that
            # cannot show which bytes it came from goes, because a page with no
            # provenance is the confident wrong link this feature exists to
            # prevent. What is still cited and still vouched for is kept, and
            # only the gaps are resolved.
            already = existing.get("sections") or {}
            pinned = str(existing.get("sha256") or "")
            verified = (
                bool(pinned) and str(existing.get("sections_sha256") or "") == pinned
            )
            kept = (
                {s: p for s, p in already.items() if s in sections} if verified else {}
            )
            todo = {s: ids for s, ids in sections.items() if s not in kept}
            resolved: dict[str, int] = {}
            if todo:
                # The bytes are on disk -- the file itself for a local path, the
                # kept copy for a remote -- so this needs no network;
                # when they are not, the reason is the error.
                data, why = _section_bytes(project, kind, canon, existing)
                if data is None:
                    err = SectionError("", why, KIND_NO_LOCAL_BYTES)
                    result.section_errors.append(_section_failure(canon, err, todo))
                else:
                    resolved, failures = resolve_sections(data, todo, existing)
                    for failure in failures:
                        for dropped in (
                            [failure.section] if failure.section else list(todo)
                        ):
                            kept.pop(dropped, None)
                    result.section_errors = [
                        _section_failure(canon, f, todo) for f in failures
                    ]
            if _refresh_pinned_sources(
                project, canon, existing, source_keys.get(canon, {}), result
            ):
                changed = True
            result.sections = resolved
            merged = {**kept, **resolved}
            if merged != already or ("sections_sha256" in existing) != bool(merged):
                changed = True
            if merged:
                existing["sections"] = merged
                existing["sections_sha256"] = pinned
            else:
                existing.pop("sections", None)
                existing.pop("sections_sha256", None)
            results.append(result)
            continue

        try:
            if kind == "local":
                with open(os.path.join(project.root, canon), "rb") as fh:
                    data = fh.read()
            else:
                data = fetcher(canon)
        except Exception as exc:  # noqa: BLE001 -- surfaced per-path, not fatal
            results.append(FetchResult(path=canon, error=str(exc)))
            continue

        digest = hashlib.sha256(data).hexdigest()
        # Source values are extracted BEFORE anything is written and pinned
        # with the bytes they were read from: a failure leaves the path's old
        # record exactly as it was (never a new hash over a stale or partial
        # value set, never the old hash over new bytes).
        new_values: dict[str, dict] = {}
        keys_here = source_keys.get(canon)
        if kind == "local" and keys_here:
            try:
                new_values = _extract_source_values(project, canon, keys_here)
            except sources_mod.SourceExtractionError as exc:
                results.append(FetchResult(
                    path=canon,
                    source_errors=[
                        f"{p} (the existing record for {canon} is unchanged)"
                        for p in exc.problems
                    ],
                ))
                continue
            if _sha256_file(os.path.join(project.root, canon)) != digest:
                results.append(FetchResult(
                    path=canon,
                    error="the file changed while it was being fetched; run again",
                ))
                continue
        if want_keep_copy:
            os.makedirs(copies_dir(project), exist_ok=True)
            with open(kept_copy_path(project, digest, canon), "wb") as fh:
                fh.write(data)

        # `previous` is what turns "no title matches" into "the section you
        # cited no longer exists in the new revision (was page N)" on --update.
        previous = records.get(canon)
        record: dict = {
            "sha256": digest,
            "fetched": _now_iso(),
            "kept_copy": want_keep_copy,
            "bytes": len(data),
        }
        resolved: dict[str, int] = {}
        failures: list[SectionError] = []
        if sections:
            resolved, failures = resolve_sections(data, sections, previous)
        # Nothing from the old record is carried across a sha change. Every
        # cited section -- from every item, in or out of this run's scope --
        # was just re-resolved against these bytes, so what is recorded is
        # exactly that and nothing more: a section that failed is dropped
        # rather than left pointing at a page the new bytes may not have, and a
        # section nobody cites any more goes with the bytes it was found in.
        if resolved:
            record["sections"] = resolved
            # The pages are only meaningful next to the bytes they came from.
            # `build` checks this against `sha256` before trusting one.
            record["sections_sha256"] = digest
        result = FetchResult(
            path=canon,
            sha256=digest,
            kept_copy=want_keep_copy,
            sections=resolved,
            section_errors=[_section_failure(canon, f, sections) for f in failures],
        )
        if new_values:
            record["values"] = new_values
            _diff_source_values(
                canon, (previous or {}).get("values") or {}, new_values, result
            )
        records[canon] = record
        changed = True
        results.append(result)

    if changed:
        save_lockfile(project, records)
    return results


# ----------------------------------------------------------------------- drift


@dataclass
class DriftEntry:
    path: str
    pinned_sha256: str
    upstream_sha256: str
    citers: list[str] = field(default_factory=list)


def refresh(project: Project, fetcher=None) -> list[DriftEntry]:
    """Re-fetch every pinned citation to a scratch buffer and compare hashes.

    Read-only: writes nothing, pins nothing, copies nothing. Only reachable via
    `refdes check --refresh`, so a plain `build` or `check` never touches the
    network. A url that fails to fetch is reported as a warning, not drift --
    drift means the bytes changed, not that the network did. Local paths are
    skipped: verify() already compares them against the live file on every
    build, so there is no second upstream to ask.

    `fetcher` defaults to the module-level `fetch_bytes` at call time, the same
    way `fetch_all` does -- see its docstring.
    """
    fetcher = fetcher or fetch_bytes
    records = load_lockfile(project)
    citers: dict[str, list[str]] = defaultdict(list)
    for item, spec in collect(project):
        citers[spec.path].append(item.id)

    drift: list[DriftEntry] = []
    for target in sorted(citers):
        try:
            kind = classify(project.root, target)[0]
        except CitationError:
            continue  # refused path -- validate_items has already reported it
        if kind != "remote":
            continue  # local -- verify() re-hashes it against the pin every run
        record = records.get(target)
        if record is None:
            continue  # unpinned -- already flagged by verify(), nothing to compare
        try:
            data = fetcher(target)
        except Exception as exc:  # noqa: BLE001
            project.warn(f"could not refresh {target}: {exc}")
            continue
        upstream_sha256 = hashlib.sha256(data).hexdigest()
        pinned_sha256 = str(record.get("sha256") or "")
        if upstream_sha256 != pinned_sha256:
            drift.append(
                DriftEntry(
                    path=target,
                    pinned_sha256=pinned_sha256,
                    upstream_sha256=upstream_sha256,
                    citers=sorted(set(citers[target])),
                )
            )
    return drift
