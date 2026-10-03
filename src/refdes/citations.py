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
import logging
import os
import posixpath
import re
from collections import defaultdict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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
from .parse import _yaml_error_report, yaml_safe_load

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


def kept_copy_relpath(sha256: str, path: str) -> str:
    """`kept_copy_path` in the one spelling a user-facing message may use.

    Project-relative and `/`-spelled, because a citation diagnostic that
    carried the server's own directory would differ between two machines for
    no reason -- see `tests/test_citation_path_hygiene.py`. `kept_copy_path`
    joins this onto the project root rather than the other way round, so the
    path a message names and the path the bytes land in cannot drift apart.
    """
    ext = os.path.splitext(urlparse(path).path)[1]
    return f"{COPIES_DIR}/{sha256}{ext}"


def kept_copy_path(project: Project, sha256: str, path: str) -> str:
    return os.path.join(project.root, kept_copy_relpath(sha256, path))


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
# lazily through `_import_pypdf()` below and nowhere else: a project with no
# `section:` and no datasheet to browse never needs it. The one other caller is
# the editor's PDF page reader (`sources._pypdf_reader`,
# docs/design/editor-pdf-picker.md §7), which is also why the install hint below
# is a shared constant rather than a literal in one message.

PDF_EXTRA_INSTALL = "pip install refdes[pdf]"
# The one sentence that says what to do about a missing extra. It is a constant
# rather than a literal in two messages because two features now refuse on it --
# `section:` resolution and the editor's PDF page reader
# (docs/design/editor-pdf-picker.md §8) -- and an install hint that reads
# differently depending on which one you hit is a hint nobody can act on.
PDF_EXTRA_HINT = f"needs the optional PDF extra: {PDF_EXTRA_INSTALL}"
PDF_EXTRA_ERROR = f"section: {PDF_EXTRA_HINT}"


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


def page_number(text: str) -> int | None:
    """`text` as a page of a document, or None.

    A page a link can open is a positive integer and nothing else, and this is
    the one place that says so. It was written for the editor picker's page
    box (it is still `serve/sources._page_number`, under that name) and it is now
    also what the loader accepts: two page grammars in one tree is how `page: 0`
    comes to mean page 1 in the browser and an error in the terminal, and a
    document's printed page labels (`"xiv"`) are not a page index the rendered
    `#page=` fragment could carry anyway.
    """
    stripped = (text or "").strip()
    if not stripped.isascii() or not stripped.isdigit():
        return None
    value = int(stripped)
    return value if value >= 1 else None


class _PypdfLogCapture(logging.Handler):
    """pypdf's own words about a document, collected instead of printed.

    pypdf reports a damaged document partly by *logging* it -- `logger_warning
    ("EOF marker not found")` on the `pypdf._reader` logger -- and an
    application that configured no logging receives it anyway: Python's
    last-resort handler prints the bare message on stderr. That is a line with
    no file, no path and no context, arriving immediately above the refdes
    warning that explains the same failure, so it reads as the tool crashing
    and then recovering (run-5 F2). refdes owns the report of a read refdes is
    performing, so the record is collected here and folded into refdes's own
    message, where it names a file and says what to do.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.messages.append(record.getMessage())
        except Exception:  # pragma: no cover -- a log record never breaks a build
            pass


@contextmanager
def _owning_pypdf_logs() -> Iterator[list[str]]:
    """Yield the list pypdf's warnings are collected into while the block runs.

    One line of routing, which is all the finding asked for: a handler on the
    `pypdf` logger means the last-resort handler is no longer reached, and
    `propagate = False` means a project that *does* configure logging gets
    pypdf's words inside refdes's message rather than on a line of their own.
    Both are undone on the way out, so a caller that configures pypdf's logger
    for its own purposes still finds it as it left it.
    """
    logger = logging.getLogger("pypdf")
    handler = _PypdfLogCapture()
    level, propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
        logger.propagate = propagate


def _unreadable_reason(exc: Exception, logged: list[str] | None = None) -> str:
    """Why pypdf could not open these bytes, in pypdf's own words.

    Including the ones it logged rather than raised: `EOF marker not found` is
    the fact that names the damage -- a file that ends before its trailer does
    -- and the exception pypdf finally raises says only "Stream has ended
    unexpectedly". Folding the logged words in is what makes routing them safe
    to do: nothing that was printed before is lost, it is only attributed now.
    """
    message = f"pypdf could not read the PDF: {exc}"
    extra = [m for m in dict.fromkeys(logged or ()) if m and m not in message]
    if extra:
        message = f"{message} ({'; '.join(extra)})"
    return message


def _pdf_reader(data: bytes, logged: list[str] | None = None):
    """pypdf's reader over one document's bytes, or SectionError.

    The one place a PDF is opened from bytes, for both questions asked of it
    here -- its outline (`outline_titles`) and how many pages it has
    (`page_count`) -- so the missing-extra and unreadable-file wording cannot
    drift between them. `logged` is the caller's `_owning_pypdf_logs` list, so
    the reason can quote what pypdf logged during this read.
    """
    PdfReader = _import_pypdf()
    try:
        return PdfReader(io.BytesIO(data))
    except Exception as exc:  # pypdf raises many types here, none of them ours
        raise SectionError(
            "", _unreadable_reason(exc, logged), KIND_UNREADABLE
        ) from exc


def page_count(data: bytes) -> int:
    """How many pages the document these bytes hold has.

    A fact about the bytes, so it is read where the bytes are -- `refdes fetch`,
    which pins them -- and recorded in the lockfile next to the sha256. That is
    what lets a later `check` compare a cited `page:` against the real page count
    without opening a PDF, and it is also why the count is about the *pinned*
    revision: the site links `assets/citations/<sha256>.pdf`, so the count that
    matters is the one for those bytes and no other.

    Bytes pypdf cannot open raise SectionError(kind=unreadable) with pypdf's own
    message -- including what it logged instead of raising -- and nothing it
    says reaches the terminal on its own while this function is reading;
    a missing extra raises SectionError(kind=missing_extra) with the install
    hint. Neither is a document with zero pages, and neither is ever recorded
    as a count.
    """
    with _owning_pypdf_logs() as logged:
        try:
            return len(_pdf_reader(data, logged).pages)
        except SectionError:
            raise
        # pypdf parses the page tree lazily, so the failure can surface here
        # rather than in the open
        except Exception as exc:
            raise SectionError(
                "", _unreadable_reason(exc, logged), KIND_UNREADABLE
            ) from exc


def page_out_of_range(canon: str, page: int, count: int) -> str:
    """The sentence for a cited `page:` the pinned document does not have.

    `sources.page_absent_message` builds it, so the picker refusing a read and a
    build refusing to publish a dead fragment say the same thing."""
    return sources_mod.page_absent_message(canon, page, count)


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
    SectionError(kind=unreadable) carrying pypdf's own message, logged words
    included, and says it as refdes's own line rather than pypdf's bare one.
    """
    with _owning_pypdf_logs() as logged:
        reader = _pdf_reader(data, logged)
        try:
            outline = reader.outline
        except Exception as exc:  # pypdf raises many types here, none of them ours
            raise SectionError(
                "", _unreadable_reason(exc, logged), KIND_UNREADABLE
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


def _outline_hints(want: str, titles: list[str], limit: int = 5) -> list[str]:
    """The outline titles worth naming when `section` matched none of them.

    `want` and `titles` are already normalised (`_norm`); this only decides
    which ones to show and in what order. Ranking, strongest first, so the
    hint is explainable rather than a similarity score the author cannot
    reproduce:

    1. the same title differing only in case;
    2. one is a prefix of the other -- a heading retyped part-way (`Therma`
       for `Thermal Information`), or one the author wrote without the
       numbering the outline carries (`8 Application and Implementation`);
    3. one contains the other -- `Regulatory Information` against an outline
       that calls it `Regulatory`;
    4. difflib at its default 0.6 cutoff, which is what a plain typo is.

    2 and 3 are the near-misses the 0.6 cutoff is silent about, because a
    prefix of a long string scores below it (`Electrical` against
    `Electrical Characteristics` is 0.556). Within a tier the closest ratio
    comes first and equal ratios keep outline order, so the same outline
    always prints the same hint.
    """
    folded_want = want.casefold()
    ranked: list[tuple[int, float, int, str]] = []
    for index, title in enumerate(titles):
        folded = title.casefold()
        ratio = difflib.SequenceMatcher(None, want, title).ratio()
        if folded == folded_want:
            tier = 0
        elif folded and (folded.startswith(folded_want) or folded_want.startswith(folded)):
            tier = 1
        elif folded and (folded in folded_want or folded_want in folded):
            tier = 2
        elif ratio >= 0.6:
            tier = 3
        else:
            continue
        ranked.append((tier, -ratio, index, title))
    ranked.sort()
    return [title for _tier, _ratio, _index, title in ranked[:limit]]


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
    hints = _outline_hints(want, [_norm(t) for t, _p in titles])
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

# What `fetch_all` writes for every citation it pins, minus the optional
# blocks (`sections`/`sections_sha256`, `values` for a calc source, and the
# page-count pair below). The first three are required of a record because each
# one is a fact nothing else in the file can supply: the pin itself, when it was
# taken, and whether the bytes were kept. `bytes` is written too but only ever
# displayed, so a record without it is stale rather than unreadable.
_LOCKFILE_REQUIRED = ("sha256", "fetched", "kept_copy")

# The page count of the pinned bytes, or why there is none. Written only for a
# cited path some item gives a `page:` to, and written by `fetch_all` as
# `record["page_count"] = counted` / `record["page_count_error"] = why` in one
# `if`/`elif`, so exactly one of the two is ever present. Spelled out here
# because `_record_problem` has to name both -- it is what rejects a record
# carrying both, and a count that is not a number reads as no count at all.
PAGE_COUNT_KEY = "page_count"
PAGE_COUNT_ERROR_KEY = "page_count_error"

# A sha256 as `hashlib.sha256().hexdigest()` writes it: lowercase hex, always
# 64 characters. `lockfile_text` quotes an all-digit one so YAML reads it back
# as a string, so a record whose sha256 arrived as an int or a short string did
# not come out of `refdes fetch`.
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

# git's three conflict markers, at column 0 exactly as git writes them (checked
# there rather than anywhere in the line, so an indented block scalar in some
# record's `values` cannot be mistaken for one).
_MERGE_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


class LockfileError(Exception):
    """`.refdes/citations.yaml` is present but is not readable as a lockfile.

    Carries `message` (the sentence, without the file name -- a diagnostic puts
    the file and line in its own columns) and `line` where the shape gives one.
    `str(exc)` is the whole thing with both, which is what a caller refusing
    the file prints.

    Raised rather than returned as `{}` because those two states are not the
    same and must not be confused: no lockfile means this project has pinned
    nothing, which is ordinary; an unreadable one means every pin in it is
    unknown, which is the whole provenance record gone. A reader that swallowed
    this would report each citation `unpinned` -- a confident false statement
    from a file it never read -- and `refdes fetch` would overwrite the pins
    along with it.
    """

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:
        where = f"{LOCKFILE}:{self.line}" if self.line else LOCKFILE
        return f"{where}: {self.message}"


def _yaml_kind(value: object) -> str:
    """How to name what a YAML node turned out to be, in a message about it."""
    if value is None:
        return "nothing"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, int):
        return "an integer"
    if isinstance(value, float):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "a list"
    return f"a {type(value).__name__}"


def _restore_remedy(what: str) -> str:
    """The second half of every lockfile message: what to do, and what it costs.

    `what` is the shape's own answer (rewrite the record, rewrite the block),
    and the two facts after it are the same for all of them. The file is
    committed (`docs/cli-reference.md`, "Files the tool writes"), so `git
    checkout` puts the pins back exactly as they were; re-pinning instead
    downloads every cited document again, because a pin is only ever a hash of
    bytes just fetched and refdes sends no conditional request to avoid that.
    """
    return (
        f"{what}, or restore it as committed with `git checkout -- {LOCKFILE}` "
        f"-- re-pinning it downloads every cited document again"
    )


_MERGE_REMEDY = (
    "Two branches both ran `refdes fetch` into this committed file and the "
    "merge was never finished by hand: each side's hashes are of bytes fetched "
    "on a different day, so neither is wrong and taking the wrong one is "
    "silent. `git checkout --ours " + LOCKFILE + "` (or `--theirs`) takes one "
    "side, and `refdes fetch --update` afterwards regenerates every entry, "
    "re-downloading each cited document"
)


def _conflict_marker(text: str) -> tuple[int, str] | None:
    """`(line, marker)` for the first unresolved-merge marker, or None.

    Checked before parsing, not after: a file carrying `<<<<<<< HEAD` does not
    reliably fail to parse at all, and where it does PyYAML reports the
    failure a line or two below the marker and calls it a mapping problem --
    which sends whoever reads the diagnostic to the wrong line of a merge that
    is one `git checkout` from being over. Two branches that both ran `refdes
    fetch` produce exactly this, in the one file both branches are expected to
    have written.
    """
    for number, line in enumerate(text.split("\n"), start=1):
        if line.startswith(("<<<<<<<", ">>>>>>>")) or line.rstrip() == "=======":
            return number, line.strip()
    return None


def _key_line(text: str, *keys: str) -> int | None:
    """The line the value at `keys` starts on, or None if the text has no such key.

    A second parse, and only ever on the error path: the loader that reports the
    problem (`yaml_safe_load`) builds plain dicts and throws the marks away,
    while the message has to name a line the reader can go and look at. That is
    worth one extra parse of a file already known to be broken.
    """
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None
    for key in keys:
        if not isinstance(node, yaml.MappingNode):
            return None
        for key_node, value_node in node.value:
            if getattr(key_node, "value", None) == key:
                node = value_node
                break
        else:
            return None
    return node.start_mark.line + 1


def _duplicate_key(text: str) -> tuple[str, int, int, bool] | None:
    """`(key, first_line, second_line, whether anything is lost)` for the first
    repeated key in any mapping, or None.

    Walked over the composed node tree rather than the loaded mapping, because
    loading is exactly where the repeat is lost: YAML resolves a mapping with a
    repeated key to the *last* one and says nothing, so two records for one
    cited path read as though only one was ever pinned. Nothing downstream can
    notice that, `refdes fetch` included -- it rewrites the file from the mapping
    it loaded, so the record that lost would simply not be written back, and
    there is no second file to diff against. This is the shape a bad merge
    leaves when two branches each pinned the same URL and the resolution pasted
    both blocks in, so it is reported like the merge it almost always is.

    `_key_line` already pays for one extra parse of a file known to be broken;
    this reuses the same `compose` call it makes.
    """
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        # Already reported, more accurately, by the parse above.
        return None
    if node is None:
        return None

    # An alias can make a node its own ancestor (`&a {b: *a}`), so the walk
    # carries the nodes it has been through rather than trusting the composed
    # tree to be a tree.
    seen: set[int] = set()

    def walk(current: object) -> tuple[str, int, int, str] | None:
        if isinstance(current, yaml.MappingNode):
            if id(current) in seen:
                return None
            seen.add(id(current))
            firsts: dict[str, tuple[int, object]] = {}
            for key_node, value_node in current.value:
                key = getattr(key_node, "value", None)
                if not isinstance(key, str):
                    continue
                line = key_node.start_mark.line + 1
                if key not in firsts:
                    firsts[key] = (line, value_node)
                    continue
                # Whether anything is lost needs the two values compared, and a
                # repeat that agrees with itself is still a mistake -- but
                # reporting that as a dropped record when it is a dropped copy of
                # the same one would be the one wrong thing in a message whose job
                # is to be believed (parse.py says the same about item front
                # matter). Only the fact is returned; the wording is the
                # caller's, which is where the lines are in hand too.
                first_line, first_node = firsts[key]
                return key, first_line, line, not _node_equal(first_node, value_node)
            for _, value_node in current.value:
                found = walk(value_node)
                if found is not None:
                    return found
        elif isinstance(current, yaml.SequenceNode):
            if id(current) in seen:
                return None
            seen.add(id(current))
            for child in current.value:
                found = walk(child)
                if found is not None:
                    return found
        return None

    return walk(node)


def _node_equal(left: object, right: object, depth: int = 0) -> bool:
    """Whether two composed nodes are the same value, structurally.

    Compared here rather than by re-serializing both nodes and comparing the
    text: this runs on a file already known to be corrupt, and a comparison that
    can raise on the malformed input would be a worse outcome than the duplicate
    report it feeds. `depth` stops a mutually recursive pair of aliases
    (`&a [*a]` against `&b [*b]`) from recursing forever -- two documents that
    differ only by anchor *names* are the same value here, which is the reading
    that matches what the loader does with them.
    """
    if depth > 64:
        return True
    if isinstance(left, yaml.ScalarNode) and isinstance(right, yaml.ScalarNode):
        return left.tag == right.tag and left.value == right.value
    if isinstance(left, yaml.SequenceNode) and isinstance(right, yaml.SequenceNode):
        return len(left.value) == len(right.value) and all(
            _node_equal(one, other, depth + 1)
            for one, other in zip(left.value, right.value)
        )
    if isinstance(left, yaml.MappingNode) and isinstance(right, yaml.MappingNode):
        if len(left.value) != len(right.value):
            return False
        return all(
            _node_equal(lkey, rkey, depth + 1) and _node_equal(lval, rval, depth + 1)
            for (lkey, lval), (rkey, rval) in zip(left.value, right.value)
        )
    return False


def _record_problem(cited: object, record: object) -> str | None:
    """Why one `citations:` entry is not a pin record, or None when it is."""
    if not isinstance(record, dict):
        return (
            f"the entry for {_yaml_kind(cited) if not isinstance(cited, str) else repr(cited)} "
            f"is {_yaml_kind(record)}, not a mapping of the fields `refdes fetch` writes "
            f"({', '.join(_LOCKFILE_REQUIRED)}, and optionally bytes, sections, "
            f"{PAGE_COUNT_KEY}, {PAGE_COUNT_ERROR_KEY}, values)"
        )
    # A pre-rename record carries `vendored:` where `kept_copy:` now is, and
    # is missing the new spelling entirely. Exempt here so `legacy_notices`
    # still gets to report it -- by the old key's name and the rename's, which
    # says more than "no kept_copy" ever could -- rather than this check
    # answering first with the wrong half of it.
    required = [
        name
        for name in _LOCKFILE_REQUIRED
        if name not in record and not (
            name == "kept_copy" and LEGACY_LOCKFILE_KEY in record
        )
    ]
    if required:
        return (
            f"the entry for {cited!r} has no {', '.join(required)} -- every record `refdes "
            f"fetch` writes carries all three, and each is a fact nothing else in the file "
            f"can supply (the pin, when it was taken, whether the bytes were kept)"
        )
    sha = record["sha256"]
    if not isinstance(sha, str) or not _SHA256_RE.match(sha):
        return (
            f"the entry for {cited!r} has sha256 {sha!r}, which is not a 64-character "
            f"lowercase hex digest. `refdes fetch` records exactly that and never edits "
            f"it afterwards, so this line was changed by hand or resolved wrongly in a "
            f"merge"
        )
    fetched = record["fetched"]
    if not isinstance(fetched, str) or not fetched.strip():
        return (
            f"the entry for {cited!r} has fetched {fetched!r}, which is not the timestamp "
            f"`refdes fetch` wrote when it took the pin"
        )
    kept = record.get("kept_copy")
    if kept is not None and not isinstance(kept, bool):
        return (
            f"the entry for {cited!r} has kept_copy: {kept!r}, which is neither true nor "
            f"false. It is read as a flag: a value that is merely non-empty would claim "
            f"the bytes are kept when they are not"
        )
    size = record.get("bytes")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int)):
        return (
            f"the entry for {cited!r} has bytes: {size!r}, which is not a whole number of "
            f"bytes -- it is the size `refdes fetch` measured, not a field it re-reads"
        )
    sections = record.get("sections")
    if sections is not None and not isinstance(sections, dict):
        return (
            f"the entry for {cited!r} has sections: {_yaml_kind(sections)}, not a mapping of "
            f"section name to the page it resolved to"
        )
    sections_sha = record.get("sections_sha256")
    if sections_sha is not None and (
        not isinstance(sections_sha, str) or not _SHA256_RE.match(sections_sha)
    ):
        return (
            f"the entry for {cited!r} has sections_sha256 {sections_sha!r}, which is not a "
            f"64-character lowercase hex digest -- it names the bytes its sections were "
            f"read out of, and a page read from different bytes is not the page"
        )
    values = record.get("values")
    if values is not None and not isinstance(values, dict):
        return (
            f"the entry for {cited!r} has values: {_yaml_kind(values)}, not a mapping of "
            f"source key to what was read for it"
        )
    # The pair `fetch_all` writes when a citation names a `page:` and the pinned
    # bytes have a countable page count: the count, or -- when pypdf was not
    # there to count them -- why there is none. Mutually exclusive there (`if
    # counted is not None: ... elif why:`), so a record carrying both is not one
    # the tool wrote: `_apply_page` reads the count and never looks at the
    # reason, so a stale `page_count_error:` beside a good count would be a claim
    # nobody could ever see again.
    #
    # Both are optional, deliberately: a record with neither says nothing about
    # its pages -- a hand-written one, or one written before page counting
    # existed -- and every project has to fetch before check can pass it, which
    # is what establishes the count. Requiring either would report the tool's own
    # older lockfiles as malformed.
    if PAGE_COUNT_KEY in record and PAGE_COUNT_ERROR_KEY in record:
        return (
            f"the entry for {cited!r} has both {PAGE_COUNT_KEY} and "
            f"{PAGE_COUNT_ERROR_KEY}, and only one of them can be true of these bytes: a "
            f"count and a reason there is no count are opposites, and a check reads the "
            f"count and never reaches the reason. `refdes fetch` writes one or the other"
        )
    counted = record.get(PAGE_COUNT_KEY)
    if counted is not None and (isinstance(counted, bool) or not isinstance(counted, int)):
        # Type only, and no range: `page_count(data)` is `len(reader.pages)`, so
        # `fetch` really does record `page_count: 0` for a document pypdf opens
        # and finds no pages in. Demanding a positive count here would report
        # `fetch`'s own output as malformed -- the one failure this validator
        # must not be able to cause. (`_apply_page` reads a count below 1 as no
        # count, which is its own business and is not contradicted here.)
        return (
            f"the entry for {cited!r} has {PAGE_COUNT_KEY} {counted!r}, which is not a whole "
            f"number of pages -- it is the count `refdes fetch` took of the bytes it was "
            f"pinning, and a count that is not a number reads as no count at all, which "
            f"silently drops the page check that count exists for"
        )
    why = record.get(PAGE_COUNT_ERROR_KEY)
    if why is not None and (not isinstance(why, str) or not why.strip()):
        return (
            f"the entry for {cited!r} has {PAGE_COUNT_ERROR_KEY} {why!r}, which is not the "
            f"reason the pages could not be counted. `refdes fetch` records that sentence "
            f"when it pins a document whose pages it could not count, and `check` reports it "
            f"back as the reason the page numbers are not checked"
        )
    return None


def load_lockfile(project: Project) -> dict[str, dict]:
    """The lockfile's records, keyed by cited path. Raises LockfileError.

    A file that is not there is `{}` -- an ordinary project that has pinned
    nothing. A file that is there and cannot be read as a lockfile is
    `LockfileError`, carrying one sentence that names the file, the line where
    the shape gives one, what is wrong, and what to do about it.

    Refusing is the point. This file is committed and hand-mergeable
    (`docs/cli-reference.md`: "Files the tool writes" says commit it), so the
    realistic way to get a broken one is two branches both running `refdes
    fetch` and the merge being resolved badly -- and every shape below is what
    that leaves behind. Each one used to be a raw traceback out of `fetch` and
    every command that builds, because the shape was handed straight to
    `dict()`; each one is now a diagnostic a person can act on, and none of
    them is allowed to become `{}`.
    """
    path = lockfile_path(project)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    conflict = _conflict_marker(text)
    if conflict is not None:
        conflict_line, marker = conflict
        raise LockfileError(
            f"unresolved merge conflict: {marker!r} on line {conflict_line}. "
            f"{_MERGE_REMEDY}.",
            line=conflict_line,
        )

    try:
        data = yaml_safe_load(text) or {}
    except yaml.YAMLError as exc:
        # The same one-line report every other YAML file in the project gets,
        # from the same helper, so a lockfile reads like an item file does.
        message, line = _yaml_error_report(exc, text.split("\n"), offset=0)
        raise LockfileError(
            f"is not valid YAML: {message}. "
            + _restore_remedy("Rewrite that line by hand"),
            line=line,
        ) from None

    duplicate = _duplicate_key(text)
    if duplicate is not None:
        key, first, second, lost = duplicate
        # A single-line flow mapping puts both occurrences on one line, and
        # "(lines 1 and 1)" reads like a bug in the diagnostic rather than in the
        # file -- parse.py words the same shape the same way in item front matter.
        where = (
            f", twice on line {second}"
            if first == second
            else f" (lines {first} and {second})"
        )
        dropped = (
            f"one of the two on line {second} is dropped for the other"
            if first == second
            else f"the block on line {first} is dropped for the one on line {second}"
        )
        why = (
            f"YAML keeps the last, so {dropped}, and the file no longer says which "
            f"of them was the pin. `refdes fetch` rewrites this whole file from the "
            f"mapping it loads, so the dropped one would go with nothing left to say "
            f"so."
            if lost
            else "YAML keeps the last, and both blocks read the same, so nothing is "
            "lost here -- but a mapping may only carry one of them, and `refdes fetch` "
            "would go on rewriting this file without ever noticing."
        )
        raise LockfileError(
            f"duplicate key {key!r} in one mapping{where} -- {why} "
            + _restore_remedy("Rewrite the mapping so each key appears once"),
            line=second,
        )

    if not isinstance(data, dict):
        raise LockfileError(
            f"is {_yaml_kind(data)}, not a mapping with one `citations:` key -- the whole "
            f"document is the wrong shape. " + _restore_remedy("Rewrite it by hand"),
            line=1,
        )
    records = data.get("citations")
    if records is None:
        return {}
    if not isinstance(records, dict):
        raise LockfileError(
            f"`citations:` is {_yaml_kind(records)}, not a mapping of cited path to that "
            f"path's record -- each key is a URL or a project-relative file, each value "
            f"the pin `refdes fetch` took for it. "
            + _restore_remedy("Rewrite that block by hand"),
            line=_key_line(text, "citations"),
        )
    out: dict[str, dict] = {}
    for cited, record in records.items():
        problem = _record_problem(cited, record)
        if problem is not None:
            raise LockfileError(
                f"{problem}. " + _restore_remedy("Rewrite that record by hand"),
                # The record's own line, not the block's: a lockfile holds one
                # record per cited document, so the block's line names every
                # one of them and the record's names this one.
                line=_key_line(text, "citations", str(cited)),
            )
        out[cited] = record
    return out


def read_lockfile(project: Project) -> tuple[dict[str, dict], LockfileError | None]:
    """`(records, problem)` -- the lockfile, or the problem with it, never both,
    with the problem also reported once as an ERROR diagnostic on `project`.

    For every reader that goes on to say something *else* about the project.
    With the pins unreadable there is nothing to check a citation against, so
    each of them returns rather than reporting every citation `unpinned` -- a
    confident false statement, derived from a file that was never read, in
    enough volume to bury the one diagnostic that matters. Not fatal: the rest
    of the build still runs and still reports what else is wrong with the tree.

    Reported here rather than by each caller so that the several readers one
    run goes through (`build` reads the lockfile for calc `source()` values and
    again for `verify`; `check --refresh` reads it a third time) say it once.
    Guarded on the project for that reason -- the diagnostic channel has no
    dedupe of its own, and a build that named the same corrupt file three times
    would read as three problems with one cause.

    The write path does not come through here. `refdes fetch` and the editor's
    accept-pins operation are the two writers of this file, and both take
    `load_lockfile` directly, because a lockfile neither could read is a
    lockfile neither may overwrite: `fetch` would write a fresh record for what
    it just fetched and drop every pin it could not read, which is the one
    outcome this file exists to prevent.
    """
    try:
        return load_lockfile(project), None
    except LockfileError as exc:
        if not getattr(project, "_lockfile_reported", False):
            project._lockfile_reported = True
            project.error(exc.message, file=LOCKFILE, line=exc.line)
        return {}, exc


def lockfile_text(records: dict[str, dict]) -> str:
    """The whole lockfile's text for these records -- the bytes `save_lockfile`
    writes, in memory.

    Split out of `save_lockfile` because there is a second writer of this file:
    the editor's accept operation (docs/design/editor-source-picker.md §4) has
    to stage the file and replace it atomically inside its own transaction, and
    a lockfile it writes has to be a lockfile `refdes fetch` would have written
    -- same header, same key order, same line endings -- so the next fetch sees
    a normal file and skips it. Two places spelling the format is how the two
    stop agreeing; this is the one place.
    """
    header = (
        "# Refdes citation lockfile. Computed provenance for each cited path --\n"
        "# sha256, fetch timestamp, kept-copy flag, resolved sections and the\n"
        "# sha256 those sections were read out of, and the pinned document's page\n"
        "# count (or, when pypdf was not available to count it, why there is no\n"
        "# count) -- keyed by the citation's path (URL or project-relative\n"
        "# file). Written only by `refdes fetch`.\n"
        "# Never hand-edit the sha256.\n"
    )
    return header + yaml.safe_dump(
        {"citations": records}, sort_keys=True, default_flow_style=False
    )


def save_lockfile(project: Project, records: dict[str, dict]) -> None:
    path = lockfile_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # The lockfile is machine-owned and rewritten whole, so its bytes must not
    # depend on the platform that last ran `refdes fetch`: a text-mode write
    # translated every LF to CRLF on Windows, and this file is committed.
    textio.write_text(path, lockfile_text(records))


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
                    # `is None`, not `or ""`: `page: 0` is a page number and
                    # not the absence of one, and reading it as absent would
                    # make `page: 0` render as no page at all -- the one shape
                    # that looked deliberate. It is refused at load either way
                    # (see `build.validate_items`), but nothing below should
                    # quietly turn a wrong value into a missing one.
                    page=("" if entry.get("page") is None else str(entry["page"])),
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


def page_count_gaps(records: Mapping[str, Mapping]) -> dict[str, str]:
    """`path` -> why this document's pages could not be counted, for every
    pinned record that records the attempt's failure instead of a count.

    The lockfile already holds this fact (`fetch` writes it, `_apply_page` reads
    it so that `check` can warn without the bytes), and `audit` -- the command a
    release reviewer actually runs -- printed nothing about it, so a pin whose
    cited page numbers were never compared to anything read `ok` (run-5 F1).

    Two kinds of record are deliberately absent: one with a count, whose pages
    were checked, and one with neither, which claims nothing about its pages --
    a pin written before any count was attempted. That is `_apply_page`'s
    distinction, kept here so the two commands cannot disagree about what "we
    could not check this" means.
    """
    gaps: dict[str, str] = {}
    for path, record in records.items():
        counted = record.get(PAGE_COUNT_KEY)
        if isinstance(counted, int) and counted >= 1:
            continue
        why = record.get(PAGE_COUNT_ERROR_KEY)
        if why:
            gaps[path] = str(why)
    return gaps


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
      local file changed    -- warning naming every cacher (review the change,
                                 then re-pin), or error with `require` (CI)
      page: past the end,   -- warning naming the citer, or error with
      or never checked          `require` (CI). `refdes fetch` counts the pinned
                                 document's pages and records the count, so this
                                 reads the lockfile and never opens a PDF
      inconsistent keep_copy:    -- warning, always (not promoted by `require`;
      across citers of a       it is a hygiene note about the declaration, not
      shared url                a missing artifact)
    """
    records, lockfile_problem = read_lockfile(project)
    if lockfile_problem is not None:
        # Reported already, by `read_lockfile`. Declining here is the point:
        # with the pins unreadable there is nothing to check a citation
        # against, and continuing would report every one of them `unpinned` --
        # a claim about a file that was never read, in enough volume to bury
        # the one line that says so.
        return
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
        _apply_page(project, item, spec, record, status, severity)
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
            # `label=canon`, not the reader's default: the default is
            # `path.as_posix()` -- the server's own directory -- and this string
            # is stored on the calc line and rendered into the item page, so it
            # reaches `/preview/` over `refdes serve` and `_site/` on a plain
            # build (`sources.CsvReader.extract`, sources.py:245).
            now = _extract_source_values(
                project, canon, {k: [] for k in keys}, label=canon,
            )
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


def _apply_page(project, item, spec, record, status, severity) -> None:
    """Check an authored `page:` against the pinned document's page count.

    Reads the lockfile only -- a build never opens a PDF, and never will for
    this: `refdes fetch` counted the pages while it had the bytes and recorded
    the count next to the sha256 they belong to, which is what makes this check
    possible without giving up the hermetic promise.

    Three outcomes, and which one applies is decided by what the lockfile knows,
    not by how bad the number looks:

    - **The record is not usable** -- no lockfile entry, an unpinned or missing
      or tampered local file, a hash-only remote path whose count was never
      established. Every one of those is already reported by `_resolve` with the
      command that fixes it, so this says nothing: two complaints about one
      citation, one of them about bytes that are not the ones being linked, is
      noise an author has to read past.
    - **The count is known and the page is past it**: reported, in the picker's
      own words, with the same severity a `section:` that resolves to nothing
      gets -- a warning naming the citer, escalated by `--require-citations`.
    - **The count is known not to exist**, because `refdes fetch` pinned these
      bytes without pypdf to count them. Reported too, with the reason the pin
      recorded, in that sentence's own grammar.

    A record with neither `page_count` nor `page_count_error` claims nothing
    about its pages -- a hand-written lockfile, or one written before any of
    this -- and is left alone. That is not leniency: every project has to run
    `refdes fetch` before `check` can pass it, and that run records the count.
    Reporting the gap in the meantime would warn about a lockfile rather than
    about a citation.
    """
    if not spec.page or status.state != "ok":
        return
    page = page_number(spec.page)
    if page is None:
        return  # a load-time declaration error already reported it, with file:line
    count = (record or {}).get(PAGE_COUNT_KEY)
    if not isinstance(count, int) or count < 1:
        why = str((record or {}).get(PAGE_COUNT_ERROR_KEY) or "")
        if not why:
            return  # no count was ever claimed for these bytes
        status.detail = (
            f"the page numbers cited for {spec.path} are not checked: the "
            f"lockfile records no page count for this document because {why} -- "
            f"run 'refdes fetch --update --path {spec.path}' to establish it"
        )
        severity(
            status.detail, file=item.source_file, line=item.source_line, item_id=item.id
        )
        return
    if page <= count:
        return
    status.detail = page_out_of_range(spec.path, page, count)
    severity(
        status.detail, file=item.source_file, line=item.source_line, item_id=item.id
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


# The one size a fetched citation is warned about, in bytes. A datasheet is
# allowed to be enormous -- some vendor PDFs are -- so this is a warning and
# not a cap: the download still succeeds, the pin still lands, and the exit
# code is the one a small fetch would have produced. Refusing a size is a
# judgement about somebody's document, and it is not one this constant gets to
# make.
#
# Deliberately not a content-type check either: a citation may legitimately
# point at something that is not a PDF, so what the bytes *are* is the author's
# call, and a diagnostic here would be advice about a decision already made.
#
# Measured on the bytes actually received, never on the `Content-Length`
# header, and the reason is that the received length *is* the length of the
# pin: it is what gets hashed, what the lockfile's `bytes:` records, and what a
# kept copy is written from. A header is not that number, in either direction --
# both halves of that are measured over a real socket in
# `tests/test_fetch_size_warning.py::test_a_chunked_response_with_no_content_length_still_warns`
# (a chunked response carries no `Content-Length` at all and its body still
# arrives whole, so a header-driven warning would go silent for exactly the
# streaming transfer a big datasheet tends to be), and by hand against a
# hand-rolled local origin for the rest: a header that *overstates* makes
# `resp.read()` raise `IncompleteRead` before any warning could be printed, and
# one that *understates* truncates the body to its own claim, so the pin is
# small and the warning says so. The honest consequence, documented in
# `docs/cli-reference.md`, is that there is no pre-download cap either -- a
# large body is read into memory before this fires. The point is that the
# author is told, not that the disk is protected.
FETCH_SIZE_WARN_BYTES = 100 << 20


def _size_label(size: int) -> str:
    """`size` as MB to one decimal -- the unit the threshold is quoted in."""
    return f"{size / (1 << 20):.1f} MB"


def large_fetch_message(canon: str, size: int, kept: str | None) -> str:
    """The warning for a remote citation fetched past `FETCH_SIZE_WARN_BYTES`.

    Names all three things an author needs to act on it: which citation, how
    big it actually turned out to be, and where the bytes went -- the kept
    copy's project-relative path, or the fact that there isn't one. `kept` is
    `kept_copy_relpath` or `None`; it is never composed here from an absolute
    path, per `tests/test_citation_path_hygiene.py`.
    """
    where = f"kept at {kept}" if kept else "no local copy kept (hash-only)"
    return (
        f"{canon}: fetched {size} bytes ({_size_label(size)}), over the "
        f"{_size_label(FETCH_SIZE_WARN_BYTES)} a fetch is warned at -- pinned "
        f"anyway, {where}"
    )


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
    # One line per cited `page:` this fetch could not confirm against the bytes
    # it pinned, for the same reason `section_errors` is separate from `error`:
    # the pin succeeded, and a warning (not a failure) is the honest severity
    # because the number is the author's own decision -- the pin is not rolled
    # back over it, but the citation is named either at fetch time and at every
    # `check`/`build` after it.
    page_warnings: list[str] = field(default_factory=list)
    # Set when this fetch's bytes were over `FETCH_SIZE_WARN_BYTES`: one line
    # naming the citation, its size and where the copy went. A warning and
    # never a failure, for the reason the constant's own comment gives -- a
    # big datasheet is a legitimate thing to have cited, and the author is told
    # rather than stopped.
    size_warnings: list[str] = field(default_factory=list)
    # How many pages the pinned document has, when a citation here names a
    # `page:` and pypdf could count them. Recorded in the lockfile so a later
    # `check` can range-check a page without opening the PDF.
    pages: int | None = None


def _extract_source_values(
    project: Project, canon: str, keys: dict[str, list[str]], *, label: str | None = None,
    values: dict | None = None,
    anchors: dict[str, sources_mod.PdfAnchor] | None = None,
) -> dict[str, dict]:
    """Every used key of one local file, in one parse, as lockfile `values`
    entries -- or SourceExtractionError. Nothing is written here: the caller
    replaces the path's record only if this returns.

    `label` is what the reader calls the file in its problems, and every caller
    in this module passes it: the reader's default is `path.as_posix()`, the
    absolute path it was handed, and a problem string is not somewhere that
    belongs (`editor-source-picker.md` §6, and `sources._cannot_read` for what
    undoing it from the other side takes). These problems are printed as
    `FAILED` lines by `fetch`, stored on the calc line by `_source_drift` and
    rendered into the item page, so a caller that omits the label leaks the
    server's own directory to a terminal and to `/preview/`.

    PDF requests take their confirmed anchors from `values` (the old record,
    or the fresh on-disk lockfile when omitted). Accept can add server-derived
    `anchors`; the browser's quote is never an input to this function.
    """
    reader = sources_mod.reader_for(canon)
    if values is None:
        # Read leniently, like every other reader: this is a fallback for a
        # caller that had no values to hand, and a lockfile this project
        # cannot read has already been reported as an error by whoever read it
        # first. Not reaching for `{}` silently -- that is the distinction
        # `read_lockfile` exists to keep.
        records, _problem = read_lockfile(project)
        values = (records.get(canon) or {}).get("values") or {}
    requests = []
    for key in sorted(keys):
        anchor = (anchors or {}).get(key)
        entry = values.get(key)
        if anchor is None and reader.name == "pdf" and isinstance(entry, dict):
            # Validation belongs to the reader, including malformed lockfile
            # provenance: no guessed page or numeric index on a partial pin.
            anchor = sources_mod.PdfAnchor(
                entry.get("page"), entry.get("quoted"), entry.get("token"),
            )
        requests.append(sources_mod.SourceRequest(canon, key, anchor))
    got = reader.extract(
        Path(os.path.join(project.root, canon)),
        requests,
        label=label,
    )
    return {
        k: {"reader": v.reader, "value": v.text, **({
            "page": v.anchor.page, "quoted": v.anchor.quoted, "token": v.anchor.token,
        } if v.anchor is not None else {})}
        for k, v in sorted(got.items())
    }


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
        # `label=canon` for the same reason as `_source_drift` above: these
        # problems are printed as `FAILED` lines, so the reader must name the
        # file by the path the author wrote, never by the one it was handed.
        new_values = _extract_source_values(
            project, canon, keys, label=canon, values=values,
        )
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


def stage_source_pins(
    project: Project, records: dict[str, dict], pins: list[tuple[str, str]], *,
    anchors: dict[tuple[str, str], sources_mod.PdfAnchor] | None = None,
    digests: dict[str, str] | None = None,
) -> tuple[list[str], list[dict]]:
    """Add `(canon, key)` pins to `records` in memory, exactly as `refdes fetch`
    would have written them, and report what stopped it.

    This is the accept operation's half of docs/design/editor-source-picker.md
    §4: the editor writes the lockfile, and what it writes has to be what fetch
    writes -- the same record keys, the same `values` shape, the same policy
    about which bytes a value may come from -- or the next `refdes fetch` looks
    at the file and sees something it did not write. So this does not
    reimplement that policy, it applies it:

    - **A path with no record is allowed**, and gets the record `fetch_all`
      would have made for it: `sha256`, `fetched`, `kept_copy: false` (a local
      file is already local -- `fetch` makes `keep_copy:` on one an error),
      `bytes`, and `values`. Hash and value are pinned in one write, which is
      the only way a key can be pinned from bytes nobody has accepted yet.
    - **A path with a record is only re-read from the bytes that record names.**
      A file whose hash moved is refused in `fetch`'s own words, pointing at
      `refdes fetch --update`: re-accepting a changed source value stays a
      deliberate act in a terminal where the `old -> new` diff is printed
      (`calc-sources.md` Q2, decided 2026-09-21).
    - **A value already pinned for another key survives.** `values` is merged,
      never replaced by the one key being accepted -- the whole-map replacement
      `_refresh_pinned_sources` does is correct for a fetch that walked every
      body in the project and wrong for one key from one item.

    `records` is mutated only when every pin succeeded; on any error nothing
    changed and the caller writes nothing either. Returns `(errors, pinned)`,
    `pinned` being one `{path, key, reader, value}` per accepted pair -- the
    value the *reader* read, which is the only value this operation knows.

    PDF pins also carry `page`, `quoted`, and the numeric `token` index. Their
    `anchors` come from server re-validation of a session pick, and `digests`
    guards the bytes that pick belonged to through the second extraction.
    A key already naming another PDF candidate cannot be rebound by accept.
    """
    wanted: dict[str, list[str]] = {}
    for canon, key in pins:
        keys = wanted.setdefault(canon, [])
        if key not in keys:
            keys.append(key)

    errors: list[str] = []
    staged: dict[str, dict] = {}
    pinned: list[dict] = []
    for canon in sorted(wanted):
        target = os.path.join(project.root, canon)
        if not os.path.isfile(target):
            errors.append(f"{canon}: cited local file {canon!r} is not on disk")
            continue
        record = records.get(canon)
        digest = _sha256_file(target)
        if canon in (digests or {}) and digests[canon] != digest:
            errors.append(f"{canon}: this PDF changed since the page was read; reopen it")
            continue
        if record is not None and str(record.get("sha256") or "") != digest:
            errors.append(
                f"{canon}: the file has changed since it was pinned -- accepting "
                f"{wanted[canon][0]!r} from these bytes would pair the old hash "
                "with new ones. Review the change, then run "
                f"'refdes fetch --update --path {canon}'"
            )
            continue
        # Everything this file already pins is re-read alongside the new key,
        # from bytes just confirmed to BE the pinned ones: `values` is written
        # whole, so a key left out of the extraction is a key deleted.
        keep = {
            k: v for k, v in ((record or {}).get("values") or {}).items() if _value_text(v)
        }
        selected = {key: a for (path, key), a in (anchors or {}).items() if path == canon}
        conflict = False
        for key, anchor in selected.items():
            old = keep.get(key)
            if old is not None and (
                old.get("reader") != "pdf" or old.get("token") != anchor.token
                or not isinstance(old.get("quoted"), str)
                or sources_mod.pdf_quote_labels(old["quoted"])
                != sources_mod.pdf_quote_labels(anchor.quoted)
            ):
                errors.append(
                    f"{canon}: key {key!r} already names a different confirmed PDF "
                    "candidate -- choose a new source key"
                )
                conflict = True
        if conflict:
            continue
        try:
            values = _extract_source_values(
                project, canon, {k: [] for k in sorted(set(keep) | set(wanted[canon]))},
                label=canon, values=keep, anchors=selected,
            )
        except sources_mod.SourceExtractionError as exc:
            errors.extend(f"{p} (nothing was pinned)" for p in exc.problems)
            continue
        if _sha256_file(target) != digest:
            errors.append(f"{canon}: the file changed while it was being read; reopen it")
            continue
        new_record = dict(record) if record else {
            "sha256": digest,
            "fetched": _now_iso(),
            "kept_copy": False,
            "bytes": os.path.getsize(target),
        }
        if values != keep or record is None:
            new_record["values"] = values
            if record is not None:
                new_record["fetched"] = _now_iso()
        staged[canon] = new_record
        for key in sorted(wanted[canon]):
            entry = values.get(key)
            if entry is None:  # unreachable past the reader; a missing key is its error
                errors.append(f"{canon}: {key!r} was not extracted")
                continue
            pinned.append({"path": canon, "key": key, **entry})

    if errors:
        return errors, []
    records.update(staged)
    return [], pinned


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


def _local_read_failure(
    canon: str, exc: Exception, citers: list[str], source_citers: dict[str, list[str]],
) -> str:
    """A cited local file `fetch` could not open, in `check`'s words and naming
    every item that wanted it.

    The two halves are not decoration. `check` already reports this exact
    condition as `cited local file <canon> does not exist`
    (`_resolve_local`), so a project that gets one message from `fetch` and the
    other from `check` reads as two different problems; and a fetch failure
    with no item id on it is a failure an author has to locate by hand. The
    `source()` users of the file are named too: they are why the file is cited
    even when no `citations:` entry spells a key out of it.

    `reason` is `exc.strerror`, never `str(exc)`: `sources._cannot_read`'s
    docstring says why in one line ("`str(OSError)` interpolates the filename
    it was raised on"), and `errno` covers the rare OSErrors that carry none.
    """
    who = sorted(set(citers) | {i for group in source_citers.values() for i in group})
    cited_by = f" (cited by {', '.join(who)})" if who else ""
    if isinstance(exc, FileNotFoundError):
        return f"cited local file {canon!r} does not exist{cited_by}"
    reason = getattr(exc, "strerror", None) or f"OS error {getattr(exc, 'errno', None)}"
    return f"cited local file {canon!r} cannot be read: {reason}{cited_by}"


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


def _check_pages(
    canon: str, count: int, pages: dict[str, list[str]], result: FetchResult
) -> None:
    """One warning per cited `page:` the pinned document does not have.

    The sentence is `sources.page_absent_message`'s, the one the editor picker
    already refuses with, so "page 99 is not in this document -- it has 8
    page(s)" means the same thing wherever it is read."""
    for page_text, ids in sorted(pages.items()):
        page = page_number(page_text)
        if page is None or page <= count:
            continue
        who = ", ".join(sorted(set(ids)))
        result.page_warnings.append(
            f"{page_out_of_range(canon, page, count)} (cited by {who})"
        )


def _page_count_remedy(canon: str, why: str) -> str:
    """What to do about a page count that could not be taken, or "" when `why`
    already carries the fix.

    Only one of `_page_count_for_pin`'s two reasons needs this: a missing extra
    is repaired by the install command `why` itself names, and telling an author
    their *file* is broken because they did not install a library is a false
    lead. Bytes that will not open are theirs to fix, and this fetch-time line
    is all they get until `check` repeats it -- which is why it has to say what
    to do, in the shape `_apply_page` already uses (run-5 F2: pypdf's complaint
    used to print itself above this line, and read as a crash because nothing on
    the screen attributed it).
    """
    if PDF_EXTRA_HINT in why:
        return ""
    return (
        f". The page numbers cited for {canon} are not checked: confirm that "
        f"{canon} really is a complete PDF -- a download that ended early is "
        f"the usual cause -- then run 'refdes fetch --update --path {canon}' "
        f"to count its pages"
    )


def _page_count_for_pin(canon: str, data: bytes) -> tuple[int | None, str]:
    """`(count, "")` when this document's pages can be counted, else
    `(None, why they cannot)`.

    Only a PDF has pages, so a `page:` on any other cited file is not this
    function's business: `(None, "")`, which records nothing and reports nothing
    -- "not applicable" is not "we tried and could not". A PDF whose pages
    cannot be counted -- no extra installed, bytes pypdf cannot open -- answers
    with the reason, which is a clause both call sites read: the fetch that
    pinned these bytes prints it as the warning it is, and the lockfile keeps it
    so a later `check` can say the same thing without having the bytes."""
    if os.path.splitext(canon)[1].lower() not in sources_mod.PdfReader.extensions:
        return None, ""
    try:
        return page_count(data), ""
    except SectionError as exc:
        # The extra's own hint for a missing import, pypdf's own words for bytes
        # it cannot open -- neither of which is a count of zero.
        return None, (
            f"counting a document's pages {PDF_EXTRA_HINT}"
            if exc.kind == "missing_extra"
            else f"counting a document's pages failed: {exc}"
        )


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

    # {canonical path: [citing item ids]} -- every citation in the project, for
    # the same reason as the two below: a failure has to say whose citation it
    # is, and the ids of the two above only cover a citation that names a
    # section or a page. A bare `path:` entry -- the commonest local citation of
    # all -- is in neither, and it is exactly the one that fails to open.
    cited_by: dict[str, list[str]] = defaultdict(list)
    for item, spec in collect(project):
        try:
            _kind, canon = classify(project.root, spec.path)
        except CitationError:
            continue  # a refused path is validation's to report, not ours
        if item.id not in cited_by[canon]:
            cited_by[canon].append(item.id)

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

    # {canonical path: {page as written: [citing item ids]}} -- the same
    # argument, for the number the author typed: re-pinning a path replaces the
    # page count every `page:` here is checked against, so a `--item A` re-pin
    # that shortened the document has to notice B's page too. A `page:` that is
    # not a page number at all is not collected -- that is a load-time
    # declaration error, and reporting it again from fetch would be the same
    # complaint twice.
    all_pages: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item, spec in collect(project):
        if page_number(spec.page) is None:
            continue
        try:
            _kind, canon = classify(project.root, spec.path)
        except CitationError:
            continue  # a refused path is validation's to report, not ours
        all_pages[canon][spec.page].append(item.id)

    # Strictly `load_lockfile`, not `read_lockfile`: this is the writer, and a
    # lockfile it cannot read is a lockfile it must not overwrite. The
    # `LockfileError` propagates to `cmd_fetch`, which refuses -- see
    # `read_lockfile` for why the two are separate. Read before any of the work
    # above has an effect, so a corrupt lockfile costs a refusal and not a
    # re-pin that then cannot be written back.
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
        pages = {
            page: sorted(set(ids))
            for page, ids in sorted(all_pages.get(canon, {}).items())
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
            # The page count is a derived value like a resolved section: it is
            # recorded for the pages actually cited and dropped with the last
            # one, so a path nobody gives a `page:` any more stops growing a
            # lockfile key. It is checked here rather than left to `check`
            # alone because the recorded count is right there -- a `page:`
            # edited since the last fetch is the commonest way a wrong page gets
            # written, and fetch is the command the author just ran. A record
            # with neither key claims no count (a hand-written or older
            # lockfile), and there is nothing here to check it against: the
            # first `refdes fetch` records one, and `check` says so until then.
            counted = existing.get(PAGE_COUNT_KEY)
            stale = [k for k in (PAGE_COUNT_KEY, PAGE_COUNT_ERROR_KEY) if k in existing]
            if not pages and stale:
                for key in stale:
                    existing.pop(key)
                changed = True
            elif isinstance(counted, int) and pages:
                result.pages = counted
                _check_pages(canon, counted, pages, result)
            results.append(result)
            continue

        try:
            if kind == "local":
                with open(os.path.join(project.root, canon), "rb") as fh:
                    data = fh.read()
            else:
                data = fetcher(canon)
        except Exception as exc:  # noqa: BLE001 -- surfaced per-path, not fatal
            # A local read that fails is reported in `check`'s own words, with
            # the citing ids: `str(OSError)` interpolates the absolute path this
            # open() was handed, so composing it here would put the server's own
            # directory on a line that is otherwise project-relative, and would
            # leave the author with a failure naming no item of theirs. Both are
            # what `_resolve_local` already gets right for the same condition
            # (citations.py:1039); this is the fetch half of that one sentence.
            results.append(FetchResult(
                path=canon,
                error=(
                    _local_read_failure(canon, exc, cited_by[canon], source_keys[canon])
                    if kind == "local"
                    else str(exc)
                ),
            ))
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
                new_values = _extract_source_values(
                    project, canon, keys_here, label=canon,
                    values=(records.get(canon) or {}).get("values") or {},
                )
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

        # The size warning is measured on what arrived, and is only about a
        # remote citation: a local path was already sitting on the author's own
        # disk, so nothing was downloaded and nothing is duplicated by pinning
        # it. Built here rather than at the read above because the kept copy's
        # path does not exist until the line above has run, and naming where
        # the bytes went is half of what makes the warning actionable.
        oversize = (
            large_fetch_message(
                canon, len(data),
                kept_copy_relpath(digest, canon) if want_keep_copy else None,
            )
            if kind == "remote" and len(data) > FETCH_SIZE_WARN_BYTES
            else ""
        )

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
            size_warnings=[oversize] if oversize else [],
        )
        # The page count, for the same reason and with the same scope argument as
        # the sections above: these are the bytes being pinned, so every cited
        # page is checked against them -- including the pages of items this run
        # did not ask about. Recorded only for a path that cites a page, and
        # recorded against this sha256 with nothing carried over from the old
        # record, so a later `check` can compare a page to a count that is
        # certainly about the bytes the site links.
        if pages:
            counted, why = _page_count_for_pin(canon, data)
            if counted is not None:
                record[PAGE_COUNT_KEY] = counted
                result.pages = counted
                _check_pages(canon, counted, pages, result)
            elif why:
                # The pages could not be counted, so they are not checked --
                # which is a different fact from "this document has no pages",
                # and the reason is kept so a later `check` can say it without
                # having the bytes. pypdf's own complaint about these bytes now
                # arrives inside `why` instead of as a bare line of stderr
                # above this warning (run-5 F2), so this line is the whole of
                # what the author gets, and it carries the remedy too.
                result.page_warnings.append(
                    f"{canon}: the pages could not be counted to check the page "
                    f"numbers cited here -- {why}"
                    + _page_count_remedy(canon, why)
                )
                record[PAGE_COUNT_ERROR_KEY] = why
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


# Owned here and read by cli.py when it registers the flag, so the name in the
# diagnostics and the name on the command line cannot drift apart. A failure
# message that names a flag which does not exist is worse than no hint at all.
ALLOW_UNREACHABLE_FLAG = "--allow-unreachable"


def refresh(project: Project, fetcher=None, allow_unreachable: bool = False) -> list[DriftEntry]:
    """Re-fetch every pinned citation to a scratch buffer and compare hashes.

    Read-only: writes nothing, pins nothing, copies nothing. Only reachable via
    `refdes check --refresh`, so a plain `build` or `check` never touches the
    network. Local paths are skipped: verify() already compares them against the
    live file on every build, so there is no second upstream to ask.

    A url whose bytes could not be obtained is *not* drift -- drift means the
    bytes changed, and no bytes arrived -- so it never appears in the returned
    list. What happens to it instead is the whole point of `allow_unreachable`:
    by default each such url is an **error**, because a drift scan that silently
    scanned nothing is exactly the failure a CI guard must not have (in an
    outage, or when the vendor has deleted the datasheet). `allow_unreachable`
    downgrades them to warnings, which is what a laptop on a train wants.

    "Could not be obtained" is deliberately everything the fetcher can raise --
    DNS failure, connection refused, timeout, and the HTTP error statuses
    `urlopen` raises for (`HTTPError`). A redirect is not in that set: `fetch_bytes`
    follows 3xx inside `urlopen`, so a hop that lands on a 200 is an ordinary
    successful fetch compared on its final bytes, exactly as `fetch_all` pins it.
    A hop that ends in an error status, exceeds urllib's redirect cap, or loops
    raises like any other unreachable url does.

    A partial outage is not special-cased: every url is attempted, the ones that
    answered are compared as usual, and the unreachable ones are reported
    separately so the run says how much was and was not verified.

    `fetcher` defaults to the module-level `fetch_bytes` at call time, the same
    way `fetch_all` does -- see its docstring.
    """
    fetcher = fetcher or fetch_bytes
    records, lockfile_problem = read_lockfile(project)
    if lockfile_problem is not None:
        # Already reported. Drift is a statement about how a pin compares to
        # today's bytes; with no readable pin there is nothing to compare, and
        # reporting no drift would be the loudest possible way to say nothing.
        return []
    citers: dict[str, list[str]] = defaultdict(list)
    for item, spec in collect(project):
        citers[spec.path].append(item.id)

    drift: list[DriftEntry] = []
    unreachable: list[tuple[str, Exception]] = []
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
            unreachable.append((target, exc))
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
    if unreachable:
        # One line per url that could not be reached, and the count line only
        # when there is more than one url to count. It used to be printed for
        # one as well, which said the same thing twice on one screen -- the
        # per-url line naming the url and the reason, the summary saying the
        # same citation could not be refreshed -- and the summary's only
        # non-repeated word was the number one, which the reader can count
        # (run-5 F6). So with a single url the remedy rides on its own line
        # instead, and nothing about the failure or the escape hatch is lost.
        n = len(unreachable)
        plural = "s" if n != 1 else ""
        for target, exc in unreachable:
            head = f"could not refresh {target}: {exc}"
            if allow_unreachable:
                project.warn(
                    head
                    + " -- upstream drift was NOT verified for it"
                    + (
                        f" -- drop {ALLOW_UNREACHABLE_FLAG} to fail the run on "
                        "this instead" if n == 1 else ""
                    )
                )
            else:
                project.error(
                    head
                    + " -- upstream drift was NOT verified for this citation "
                    "(no bytes arrived, so there is nothing to compare the pin "
                    "against)"
                    + (
                        " -- the run cannot claim to have checked it. Fix the "
                        f"network or the urls, or pass {ALLOW_UNREACHABLE_FLAG} "
                        "to treat an unreachable source as a warning and let the "
                        "exit code reflect only real findings (you then get no "
                        "guarantee that every pinned source was checked at all)"
                        if n == 1
                        else ""
                    )
                )
        if n > 1:
            if allow_unreachable:
                project.warn(
                    f"{n} pinned citation{plural} could not be refreshed, so upstream "
                    f"drift was NOT verified for them -- "
                    f"drop {ALLOW_UNREACHABLE_FLAG} to fail the run on this instead"
                )
            else:
                project.error(
                    f"{n} pinned citation{plural} could not be refreshed, so upstream "
                    f"drift was NOT verified for them -- the "
                    f"run cannot claim to have checked them. "
                    f"Fix the network or the urls, or pass {ALLOW_UNREACHABLE_FLAG} to "
                    f"treat an unreachable source as a warning and let the exit code "
                    f"reflect only real findings (you then get no guarantee that every "
                    f"pinned source was checked at all)"
                )
    return drift
