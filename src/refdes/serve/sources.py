"""Read-only browsing of a cited source file, for the editor's source-value
picker (docs/design/editor-source-picker.md -- Slice A, "the service reads";
docs/design/editor-pdf-picker.md -- Slice P-A, the same for a PDF's pages).

Three reads of a keyed file and no writes: which of this item's own cited files
a reader can list, what rows one of those files holds, and the calc line a
picked `(path, key)` would compose to. Accepting a pick writes the item and the
lockfile and is Slice B; the panel is Slice C. A PDF adds one more read -- a
page, as positioned text with its numeric candidates -- and reuses the proposal
read for a deliberately selected row/token (Slice P-B). Its key is proposed
from the row labels and is author-editable; Slice P-C passes that confirmed
row into Slice B's existing accept transaction. The picker opens the page its
citation already names.
Nothing in this module writes anything, and nothing in it is reachable for a
file the item has not already cited.

The confinement is inherited rather than reimplemented, in the order it
applies:

- **Only a file this item cites.** Every path goes through
  `citations.authorize_source_path` -- the function `refdes fetch` uses to
  decide what to extract and evaluation uses to decide which lock record to
  read -- so the picker can never be authorized for something the fetcher
  would refuse, and its refusal is that function's own message. A *remote*
  datasheet is the one case that function refuses by rule rather than by
  mismatch, because a `source()` line may only name a committed file; browsing
  one is a different question, answered separately below and by the same two
  rules -- the citation is this item's own, and the bytes are the pinned ones.
  The path a payload carries back is the canonical project-relative one the
  local case returns, or the URL as the citation spells it in the remote case.
- **Only a file with a registered reader.** Dispatch is `sources.reader_for`
  by extension, exactly as extraction dispatches. A cited `.xlsx`, `.py` or
  extensionless file is refused with the registry's own words and is never
  opened; there is no fallback text parse here either. A cited `.pdf` is
  refused too when the `refdes[pdf]` extra is not installed, with that extra's
  install hint rather than as an unhandled file type.
- **Bounded.** The caps live in `refdes.sources`, where the file is read, so
  they bound the read rather than the response.

**No absolute server path leaves the process, in any string.** That has to hold
for the reader's per-row diagnostics and not just for the `path` field, and it
is enforced by *naming* rather than by scrubbing: the reader is given the file
to read (`project.root + canon`) and, separately, `label=canon` -- the only
name it is allowed to say out loud -- so every message it produces is already
project-relative. An earlier version of this module rewrote the absolute path
out of the reader's text after the fact, and covered one branch and not the
other; see `_listing`. A pypdf failure is wrapped by the reader in the same
words `outline_titles` uses, and with the same label, so a document pypdf
cannot open says so by its own name rather than by the server's.

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


# ---------------------------------------------------------------- 4: a PDF page
#
# docs/design/editor-pdf-picker.md §2.2, §4, §8, §12 Slice P-A. A PDF is picked
# by page, not by key: the endpoint returns the page's extracted runs with their
# coordinates, the rows those runs group into, and every number in them as a
# candidate with its column-header guess. The browser never sees a PDF, only
# this JSON, and nothing here writes.


def _is_pdf_path(path: str) -> bool:
    """Whether `path` is one the pdf reader would claim.

    The suffix, through the registry's own notion of a suffix, rather than
    `reader_for` returning a reader: a server without the extra has no pdf
    reader, and a remote datasheet still has to be recognized as one so the
    refusal it gets is the install hint rather than "source() reads only a
    repo-local file" -- which would be true and useless advice for a picker."""
    return Path(path).suffix.lower() in sources_mod.PdfReader.extensions


def _canon(root: str, path: str) -> str | None:
    """`path`'s canonical local form, or None for a remote or refused one."""
    try:
        kind, canon = citations_mod.classify(root, path)
    except citations_mod.CitationError:
        return None
    return canon if kind == "local" else None


def _kept_copy(project: Project, spec, record: dict) -> tuple[str, str]:
    """(file on disk, "") for a remote citation whose bytes are here, or
    ("", why not).

    The kept copy *is* the browsable artifact for a remote datasheet, and only
    the pinned bytes: `.refdes/copies/<sha256><ext>`, read and checked against
    the sha256 the lockfile recorded, which is the "a page belongs to the bytes
    it was read out of" rule applied to a file the project does not contain
    (citations._section_bytes does the same check for `section:` resolution).
    A hash-only remote citation has no bytes in this process's reach and is
    refused with the fix rather than fetched: the editor performs no network
    I/O, and browsing bytes nothing pinned would quietly reopen what a pin
    means (editor-pdf-picker.md §10 Q4).
    """
    sha = str((record or {}).get("sha256") or "")
    if not sha:
        return "", (
            f"citation to {spec.path} has no fetched record; run 'refdes fetch "
            f"--path {spec.path}' to pin it"
        )
    if not (record or {}).get("kept_copy", False):
        return "", (
            f"no local copy of the bytes of {spec.path}: it is cited as a URL and "
            "kept as a hash only -- cite a local `path:` PDF, or set "
            f"`keep_copy: true` on this citation and re-fetch it"
        )
    blob = citations_mod.kept_copy_path(project, sha, spec.path)
    if not os.path.isfile(blob):
        # `as_posix()` on the relpath, because this string goes into a response:
        # on Windows `os.path.relpath` spells it with backslashes, and every
        # other path a payload carries is project-relative and slash-separated.
        where = Path(os.path.relpath(blob, project.root)).as_posix()
        return "", (
            f"local copy of {spec.path} is missing at {where}; run 'refdes fetch "
            f"--update --path {spec.path}' with the network available"
        )
    if citations_mod._sha256_file(blob) != sha:
        # The blob is named for its own hash, so this is a corrupted or tampered
        # cache -- the same case `verify()` treats as an error, never a soft one.
        return "", (
            f"local copy of {spec.path} does not match its pinned hash (the copy "
            "is tampered or corrupt); re-fetch it before browsing it"
        )
    return blob, ""


def _cited_pdf(
    project: Project, item: Item, path: str
) -> tuple[str, str, dict, dict]:
    """(file on disk, label, this item's citation, its lockfile record) for a
    PDF this item cites, or `SourceRefusal` naming the rule that said no.

    Two cases, two rules, one answer. A local `path:` citation is the artifact
    and goes through `authorize_source_path` -- the same call `refdes fetch` and
    the source resolver make -- so an absolute path, a scheme, a backslash, a
    `..` escape and a symlink out of the root are all refused in
    `classify()`'s own words, and a path this item does not cite is refused in
    that function's. A remote URL is refused by the same function *by rule*
    rather than by mismatch, because a `source()` line may only name a committed
    file; browsing one instead asks two questions of its own -- is this URL on
    this item (answered by looking at this item's own declarations, and
    refusing with the same sentence `authorize_source_path` uses when the answer
    is no), and are the pinned bytes on this disk (`_kept_copy`).
    """
    try:
        kind, canon = citations_mod.classify(project.root, path)
    except citations_mod.CitationError as exc:
        raise SourceRefusal(str(exc)) from exc
    records = _lockfile(project)
    if kind == "local":
        canon, why = citations_mod.authorize_source_path(project, item, path)
        if why:
            raise SourceRefusal(why)
        # Which declaration said so, so the citation's own `page:`/`section:`
        # comes with it. `authorize_source_path` just matched one of these.
        for spec in citations_mod.item_specs(project, item):
            if _canon(project.root, spec.path) == canon:
                return _target(project, canon), canon, spec, records.get(canon) or {}
        raise SourceRefusal(  # pragma: no cover - the authorizer matched one
            f"{item.id} does not cite {canon!r}"
        )
    spec = next(
        (
            found
            for found in citations_mod.item_specs(project, item)
            if (found.path or "").strip() == path.strip()
        ),
        None,
    )
    if spec is None:
        raise SourceRefusal(
            f"{item.id} does not cite {path!r}; add it to this item's citations: "
            "(a citation on another item does not authorize this one)"
        )
    record = records.get(spec.path) or {}
    target, why = _kept_copy(project, spec, record)
    if why:
        raise SourceRefusal(why)
    return target, spec.path, spec, record


def _page_number(text: str) -> int | None:
    """`text` as a page number, or None.

    A page this can open is a positive integer, and nothing else: `page: "xiv"`
    is a real citation the rendered link can carry and a page index cannot, so
    it is reported as such rather than being read as zero.
    """
    stripped = (text or "").strip()
    if not stripped.isascii() or not stripped.isdigit():
        return None
    value = int(stripped)
    return value if value >= 1 else None


def _cited_page(spec, record: dict) -> tuple[int | None, str, str]:
    """(page, `page:` or `section:`, why there is no page) for one citation.

    The picker opens where the citation already points: an explicit `page:`
    first, otherwise the page `refdes fetch` resolved for a `section:`. The
    resolved page is read out of the lockfile and never re-resolved here -- a
    build that re-read the outline would open a datasheet at whatever revision
    happens to be on disk, which is the quiet wrong answer `sections_sha256`
    exists to prevent -- and it is used only while it still belongs to the bytes
    now pinned, which is the same check `citations._apply_section` makes before
    the rendered link uses one.

    Both the page and the section are the author's to have written, so a value
    that names no openable page is reported in the citation's own terms and the
    picker opens page 1 -- never page 0, and never a guess at what "xiv" meant.
    """
    detail = ""
    page = _page_number(spec.page)
    if page is not None:
        return page, "page", ""
    if spec.page:
        detail = (
            f"the citation's page: {spec.page!r} is not a page number this can "
            "open at, so there is no page to open"
        )
    if spec.section:
        resolved = (record.get("sections") or {}).get(spec.section)
        if resolved is not None and str(
            record.get("sections_sha256") or ""
        ) != str(record.get("sha256") or ""):
            if not detail:
                detail = (
                    f"section {spec.section!r} of {spec.path} was resolved "
                    "against different bytes than the ones now pinned; run "
                    f"'refdes fetch --update --path {spec.path}' to re-resolve it"
                )
        elif resolved is not None:
            return int(resolved), "section", detail
        elif not detail:
            detail = (
                f"section {spec.section!r} of {spec.path} has no resolved page "
                f"in the lockfile; run 'refdes fetch --path {spec.path}' to "
                "resolve it"
            )
    return None, "", detail


def _span_dict(span: sources_mod.PageSpan) -> dict:
    """One run as the wire sees it, rounded to two decimals.

    Rounded for the payload only -- the grouping, the column guess and the
    candidate decisions all happen at full precision, and a page's worth of
    seventeen-digit floats is not a page anybody can read.
    """
    return {
        "text": span.text,
        "x": round(span.x, 2),
        "y": round(span.y, 2),
        "size": round(span.size, 2),
        "width": round(span.width, 2),
    }


def _token_dict(token: sources_mod.PageToken) -> dict:
    """One token, and the two things the confirm step needs beside it: the value
    `fetch` would pin for it, and its 0-based index among the row's candidates.

    `header` is the column-header *guess* and is labelled as one here so no
    consumer can mistake it for a fact: it is presentation for recognising
    which column of a min/typ/max table a number is in, and nothing records it
    (editor-pdf-picker.md §4). There is no `selected` field, because nothing is
    ever selected -- the min/typ/max rule is a list, not a choice.
    """
    return {
        "text": token.text,
        "value": token.value,
        "x": round(token.x, 2),
        "width": round(token.width, 2),
        "index": token.index,
        "numeric_index": token.numeric_index,
        "candidate": token.candidate,
        "header_guess": token.header_guess,
    }


def _row_dict(row: sources_mod.PageRow) -> dict:
    """One row: its verbatim text (the quote a reviewer re-verifies by eye), its
    tokens, and how many of them are candidates.

    The candidates are the tokens with `candidate` set, and they are not
    repeated as a second list: at a thousand runs a page the duplication would
    double a payload for nothing, and the flag is already the structure the
    rule needs -- a list of everything, with none of it chosen."""
    return {
        "index": row.index,
        "y": round(row.y, 2),
        "text": row.text,
        "labels": list(row.labels),
        "candidate_count": row.candidate_count,
        "tokens": [_token_dict(token) for token in row.tokens],
    }


def page_payload(project: Project, item: Item, path: str, page: str = "") -> dict:
    """One page of a cited PDF: positioned text, its rows, and its candidates.

    `page` is the page the request asked for. Left empty, the page is the one
    the citation names -- `page:`, or the page the lockfile resolved for a
    `section:` -- and the payload says which it was in `open_at`, so the panel
    can show the author where they were taken. A citation whose page this
    document does not have opens page 1 and says so in `cited.detail`, because
    refusing the whole document over a stale page number would hide the very
    thing the author needs to look at.

    Every failure of the read itself raises `SourceRefusal` with the reader's
    own words (an unreadable document, a page outside it, a missing extra).
    Those are not panel states the way "this page has no text" is: the page is
    what was asked for, and if it cannot be read the answer is no page, not an
    empty one. The two panel states -- no extractable text, no numeric
    candidates -- are 200s with `detail` and nothing to pick
    (editor-pdf-picker.md §3).

    The payload ends with the sha256 of the bytes this page was read out of,
    which costs one more read of a file already read. That is the price of §4's
    rule at the read boundary: the panel has to be able to say the coordinates
    on screen came from bytes that are no longer the pinned ones, and a build
    keeps evaluating the pin either way, so the honest place for that is here
    rather than nowhere.
    """
    target, label, spec, record = _cited_pdf(project, item, path)
    reader = _reader(label)  # the registry, before a byte is opened
    cited = {"page": spec.page or "", "section": spec.section or "", "detail": ""}
    if page:
        wanted, origin = int(page), "requested"
    else:
        open_page, origin, cited["detail"] = _cited_page(spec, record)
        wanted = open_page or 1
        origin = origin or "default"

    def digest_now():
        try:
            sources_mod._check_pdf_size(Path(target), label, sources_mod.MAX_PDF_BYTES)
            return citations_mod._sha256_file(target)
        except sources_mod.SourceExtractionError as exc:
            raise SourceRefusal("; ".join(exc.problems)) from exc
        except OSError as exc:
            raise SourceRefusal(f"{label}: cannot read file: {exc.strerror}") from exc

    digest = digest_now()
    try:
        listing = sources_mod.page_candidates(Path(target), wanted, label=label)
    except sources_mod.SourceExtractionError as exc:
        if page:
            raise SourceRefusal("; ".join(exc.problems)) from exc
        # The citation's own page, not one the request asked for: open page 1 and
        # carry the reader's reason, which names both the page and the count.
        wanted, origin = 1, "default"
        cited["detail"] = f"{cited['detail']}; " if cited["detail"] else ""
        cited["detail"] += (
            f"the page this citation names could not be opened: {exc} -- "
            "browsing page 1"
        )
        try:
            listing = sources_mod.page_candidates(Path(target), wanted, label=label)
        except sources_mod.SourceExtractionError as retry:
            # Page 1 is unreadable too, so the document is: say that, rather than
            # hanging the stale page number on an error about something else.
            raise SourceRefusal("; ".join(retry.problems)) from retry
    if digest_now() != digest:
        raise SourceRefusal("this PDF changed while the page was read; reopen it to review it")
    pinned = str(record.get("sha256") or "")
    return {
        "path": label,
        "reader": reader.name,
        "page": listing.page,
        "pages": listing.pages,
        "prev": listing.prev,
        "next": listing.next,
        "open_at": {"page": wanted, "from": origin},
        "cited": cited,
        # The bytes this page was read out of, beside the bytes the lockfile
        # pins: a page's rows and coordinates are facts about specific bytes
        # (editor-pdf-picker.md §4), and a pick is only valid against those.
        "sha256": digest,
        "pinned_sha256": pinned,
        "drifted": bool(pinned) and digest != pinned,
        "spans": [_span_dict(span) for span in listing.spans],
        "page_box": list(listing.page_box),
        "rows": [_row_dict(row) for row in listing.rows],
        "span_count": listing.span_count,
        "candidate_count": listing.candidate_count,
        "truncated": listing.truncated,
        "too_dense": listing.too_dense,
        "detail": listing.detail,
        "limits": {
            "max_bytes": sources_mod.MAX_PDF_BYTES,
            "max_spans": sources_mod.MAX_PAGE_SPANS,
            "max_candidates": sources_mod.MAX_PAGE_CANDIDATES,
        },
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


def _browse(reader, spec, record: dict) -> tuple[str, int | None]:
    """(mode, page to open at) for one cited file.

    The mode is what the panel branches on: a keyed file is picked by key, a PDF
    by page, and saying so in the payload is how one list can hold both without
    the browser guessing from a file extension. The page is the one the citation
    already names -- `page:`, else the page the lockfile resolved for a
    `section:` (`_cited_page`) -- and None means the citation names none, so the
    picker opens page 1.
    """
    if reader.name != sources_mod.PdfReader.name:
        return "rows", None
    page, _origin, _detail = _cited_page(spec, record)
    return "pages", page


def _file_entry(
    project: Project, label: str, reader, record: dict, status, spec,
    remote: bool = False,
) -> dict:
    """One browsable cited file, as the wire sees it: which reader reads it, how
    it is picked, where the picker opens, its pin state, and the values already
    pinned for it."""
    state, detail = _pin_state(project, label, record, status, remote=remote)
    browse, open_page = _browse(reader, spec, record)
    return {
        "path": label,
        "reader": reader.name,
        "browse": browse,
        "open_page": open_page,
        "state": state,
        "detail": detail,
        "sha256": str(record.get("sha256") or ""),
        "fetched": str(record.get("fetched") or ""),
        "pinned_values": {
            key: citations_mod.locked_source_value(record, key)
            for key in sorted(record.get("values") or {})
        },
    }


def files_payload(project: Project, item: Item) -> dict:
    """§2.1: the item's own cited files a reader can read, each with its pin
    state, how it is picked, and the values already pinned for it.

    A citation that cannot become a file a reader can open is a `problem`, not a
    file: a remote URL with no kept copy, a path that escapes the root, a type
    with no reader. Listing it is how the author finds out why the picker cannot
    offer it, which is the whole of the honest gap in editor-source-picker.md §8
    -- an item that cites no readable file gets an empty picker, and here is why.

    A PDF is now one of those files, and it reaches the list by the same rules as
    any other: it is a citation on this item, and its bytes are on this disk. The
    one case the local rule cannot express is a *remote* datasheet -- there is no
    project-relative path to a URL -- and it is browsable exactly when the fetch
    kept the bytes, from the kept copy and only the kept copy
    (editor-pdf-picker.md §2.1, §10 Q4). A hash-only remote datasheet is a
    `problem` with the fix in it; this reader does no network I/O to change that.
    """
    records = _lockfile(project)
    statuses = _status_by_canon(project, item)
    files: list[dict] = []
    problems: list[dict] = []
    seen: set[str] = set()
    told: set[str] = set()

    def problem(path: str, why: str) -> None:
        if path not in told:
            told.add(path)
            problems.append({"path": path, "problem": why})

    for spec in citations_mod.item_specs(project, item):
        if spec.path in seen:
            continue  # the same citation declared twice is one file
        try:
            kind, _canon = citations_mod.classify(project.root, spec.path)
        except citations_mod.CitationError as exc:
            problem(spec.path, str(exc))
            continue
        if kind == "remote" and _is_pdf_path(spec.path):
            seen.add(spec.path)
            record = records.get(spec.path) or {}
            try:
                # The registry first: a server without the extra must say so
                # about the datasheet rather than list a document it cannot open.
                reader = _reader(spec.path)
            except SourceRefusal as exc:
                problem(spec.path, str(exc))
                continue
            _target_on_disk, why = _kept_copy(project, spec, record)
            if why:
                problem(spec.path, why)
                continue
            files.append(_file_entry(
                project, spec.path, reader, record, statuses.get(spec.path), spec,
                remote=True,
            ))
            continue
        try:
            canon = _authorise(project, item, spec.path)
        except SourceRefusal as exc:
            problem(spec.path, str(exc))
            continue
        if canon in seen:
            continue  # the same file cited twice is one file
        seen.add(canon)
        try:
            reader = sources_mod.reader_for(canon)
        except sources_mod.SourceExtractionError as exc:
            problem(canon, "; ".join(exc.problems))
            continue
        record = records.get(canon) or {}
        files.append(_file_entry(
            project, canon, reader, record, statuses.get(canon), spec,
        ))
    return {"item": item.id, "files": files, "problems": problems}


def _pin_state(
    project: Project, canon: str, record: dict, status, remote: bool = False
) -> tuple[str, str]:
    """(state, detail) for one cited file, in the vocabulary `verify()` already
    uses for it: `unpinned` when the lockfile has no record, otherwise that
    record's own state from the build, and `missing` for a cited file that is
    not on disk (a state the build only reaches for a local citation, so it is
    worked out here rather than re-hashed -- and so is not worked out for a
    remote one, whose bytes are the kept copy, which `_kept_copy` has already
    established is there)."""
    if not record:
        return "unpinned", (
            f"citation to {canon} has no fetched record; run 'refdes fetch "
            f"--path {canon}' to pin it"
        )
    if status is not None and status.state != "ok":
        return status.state, status.detail
    if not remote and not os.path.isfile(_target(project, canon)):
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
    page: str = "",
    row: str = "",
    token: str = "",
    sha256: str = "",
) -> dict:
    """§7: the exact calc line a picked `(path, key, unit, name)` would insert,
    composed here rather than in the browser, and the row it was read from.

    Nothing is written and nothing is selected. With no `unit` there is no line
    yet -- the unit is the author's to declare and this endpoint will not
    supply one, which is why `line` is null and `complete` is false rather than
    a default appearing in the gap.
    """
    if page or row or token:
        return _pdf_proposal(
            project, item, path=path, key=key, unit=unit, name=name,
            page=page, row=row, token=token, sha256=sha256,
        )
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

    return _proposal(item, canon, key, entry, unit, name)


def _pdf_proposal(
    project: Project, item: Item, *, path: str, key: str, unit: str,
    name: str, page: str, row: str, token: str, sha256: str,
) -> dict:
    """Read a deliberately selected candidate; never write a pin here.

    Coordinates identify a session pick only. The digest guards against a
    changed file between the page read and this read, and the quote and decimal
    always come from Python's fresh extraction, never the browser.
    """
    for text, label, minimum in ((page, "page", 1), (row, "row", 0), (token, "token", 0)):
        if not text.isascii() or not text.isdigit() or int(text) < minimum:
            raise SourceRefusal(f"{label} must be an integer >= {minimum} for a PDF pick")
    listing = page_payload(project, item, path, page)
    if not sha256 or sha256 != listing["sha256"]:
        raise SourceRefusal(
            "this PDF changed since the page was read; reopen the page to review it"
        )
    if listing["too_dense"]:
        raise SourceRefusal(listing["detail"])
    selected_row = next((r for r in listing["rows"] if r["index"] == int(row)), None)
    selected = next(
        (t for t in (selected_row or {}).get("tokens", []) if t["index"] == int(token)), None
    )
    if selected is None or not selected["candidate"]:
        raise SourceRefusal("this row/token is not a numeric candidate; pick one the page lists")
    key = key.strip() or _proposed_name(" ".join(selected_row["labels"]))
    entry = _with_pin({
        "key": key, "raw": selected["text"], "value": selected["value"],
        "page": listing["page"], "row": selected_row,
        "token": selected["index"], "numeric_index": selected["numeric_index"],
        "quoted": selected_row["text"], "header_guess": selected["header_guess"],
    }, _lockfile(project).get(listing["path"]) or {})
    if not name:
        stem = _proposed_name(key)
        name = stem
        suffix = 2
        taken = _item_names(item)
        while name in taken:
            name = f"{stem}_{suffix}"
            suffix += 1
    payload = _proposal(item, listing["path"], key, entry, unit, name)
    _canon, accept_reason = citations_mod.authorize_source_path(project, item, listing["path"])
    payload.update({
        "reader": "pdf", "page": listing["page"], "row": selected_row["index"],
        "token": selected["index"], "sha256": listing["sha256"],
        "accept_supported": not bool(accept_reason),
        "accept_reason": accept_reason,
        "drifted": listing["drifted"],
    })
    return payload


def _proposal(item: Item, canon: str, key: str, entry: dict, unit: str, name: str) -> dict:
    """Shared confirm contract: author-owned unit/name, server-owned syntax."""

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


def body_source_pairs(project: Project, item: Item, body: str) -> set[tuple[str, str]]:
    """Every `(canonical path, key)` a `source()` call in `body` asks for.

    The same walk `citations.collect_source_uses` does, on one body instead of a
    whole project: `calc.source_calls_in_block` is the evaluator's grammar, so a
    line indented differently, or with a different unit, or a different variable
    name, is still the same pair -- which is exactly why this is not a string
    match against the composed line. A match on text would refuse a body the
    evaluator reads fine, and agreeing with the evaluator about which keys a body
    names is the whole point:
    `citations.stage_source_pins` is about to pin one, and a pin nothing cites is
    dead state in a tracked file (editor-source-picker.md §4).

    A path this item does not cite is not a pair, and is not reported here: that
    is the validator's error to make, on the line that made it.
    """
    pairs: set[tuple[str, str]] = set()
    for block, _offset, _block_id in calc_mod.extract_blocks_with_lines(body):
        for _line, _name, raw_path, key in calc_mod.source_calls_in_block(block):
            canon, why = citations_mod.authorize_source_path(project, item, raw_path)
            if not why:
                pairs.add((canon, key))
    return pairs


def accept_plan(
    project: Project,
    item: Item,
    *,
    path: str,
    key: str,
    unit: str = "",
    name: str = "",
    body: str,
    page: str = "",
    row: str = "",
    token: str = "",
    sha256: str = "",
) -> dict:
    """§4 step 3, under the write lock: re-validate the pick, compose its line,
    and prove the body being saved is the body that names it.

    The re-validation is `propose_payload`, called again. Not a second copy of
    its rules -- authorization against the server's copy of the item, the key
    still existing, the row still being selectable, the name still usable, the
    unit still checking out, and the line composed by the same `_compose` that
    showed it to the author. Whatever changed between the proposal and the
    accept, this sees the state as of the accept, which is the only state worth
    checking.

    Two things a proposal cannot know are checked here. That a unit arrived at
    all -- the panel disables Accept until it has one, and a disabled button is
    not a rule -- and that the submitted body carries a `source()` call for this
    exact pair, which is what makes the body and the pin one fact rather than two
    writes that happen to be adjacent.

    Raises `SourceRefusal`; returns the proposal payload, whose `line` is the
    text and whose `path` is canonical.
    """
    # Browsing a kept remote PDF is allowed; source() still only names a
    # repo-local citation. Use its existing authorization before any write.
    _authorise(project, item, path)
    proposal = propose_payload(
        project, item, path=path, key=key, unit=unit, name=name,
        page=page, row=row, token=token, sha256=sha256,
    )
    if not proposal["complete"]:
        raise SourceRefusal(
            proposal.get("reason")
            or "a source value cannot be pinned without the unit it is to be read as"
        )
    if (proposal["path"], proposal["key"]) not in body_source_pairs(project, item, body):
        raise SourceRefusal(
            f"the body being saved names no source() call for {proposal['key']!r} in "
            f"{proposal['path']} -- a source value is pinned only for a body that "
            "asks for it, so nothing was written"
        )
    return proposal


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
