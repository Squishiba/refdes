"""Byte storage for `POST /api/assets` (docs/design/editor-image-upload.md).

Phase 1 ("Bytes", §17): the destination, the name, the sniffed type, the §5
collision table, and one atomic create. Phase 2 ("Conflicts", §17): the
`expected_hash` replace path through `_atomic_replace` (§8) and the three
checks against *other documents* (§9) -- the hole Phase 1 left open on
purpose, because an upload is not a local operation: a new file can make an
unrelated document ambiguous, can capture a bare-name reference another item
already resolves, and a replace changes what every referring item shows.

Refusals are values, not exceptions, in `serve/edit.py`'s style;
`serve/api.py` turns them into status codes.

Explicitly not here yet: the §10 sealed-target and sealed-referenced refusals
-- Phase 3. §9.3 says a replace whose blast radius includes a sealed entry
"becomes a refusal instead (§10)"; the disclosure is here, the refusal is not.

Every check needs the built `Project`, not just its root: §9.1 asks the build's
own search (`build._search_image_matches`) what the leaf resolves to on the
`site.assets:` directories, and §9.2/§9.3 read `Project.image_results`, the
bookkeeping the last build already recorded for every per-item image
resolution (`build._process_images`). Reusing the build's functions rather
than re-deriving the rules is what keeps this module from becoming a third
spelling of image resolution that can drift from the other two.

The endpoint writes one file, at a path built from a validated destination
directory and a validated single-segment name, inside the project root with
real-path containment (`citations.classify` is the model). It creates no
directories, follows no symlinked destination, deletes nothing, and touches
no `.md` or `.yaml` file (§11).
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
from dataclasses import dataclass

from ..build import _search_image_matches
from ..citations import case_mismatch
from ..model import Project
from . import security
from .edit import _atomic_create, _atomic_replace, write_lock_for

# The per-file cap (design §6), defined once here because two layers enforce
# it: `serve/server.py` refuses an oversized `Content-Length` before reading a
# byte, and `store_asset` refuses oversized bytes it was actually handed.
# Checked twice is what §6 asks for -- the header bound alone is only as
# trustworthy as the client that sent it.
MAX_ASSET_BYTES = 8 * 1024 * 1024

# The type is decided by the bytes, never by the extension alone and never by
# the client's Content-Type -- that header is attacker-controlled text and
# the editor's posture is to reject unexpected content types outright (§6).
# WebP is `RIFF????WEBP`: bytes 0-4 and 8-12 must match, the four in between
# are the (untrusted, unchecked) container size.
_SIGNATURES: tuple[tuple[str, tuple[bytes, ...]], ...] = (
    ("png", (b"\x89PNG\r\n\x1a\n",)),
    ("jpg", (b"\xff\xd8\xff",)),
    ("gif", (b"GIF87a", b"GIF89a")),
)

# Extension -> the sniffed kind it must agree with. Anything outside this map
# -- `.svg`, `.php`, no extension at all -- has no agreed kind and refuses.
ACCEPTED_EXTENSIONS = {
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".gif": "gif",
    ".webp": "webp",
}

SVG_REFUSAL = (
    "SVG is not accepted: an SVG is an XML document that can carry script, "
    "and the only thing between an uploaded SVG and a same-origin script is "
    "the preview's CSP (script-src 'self') -- one misconfiguration away from "
    "executing. v1 accepts PNG, JPEG, GIF and WebP only "
    "(docs/design/editor-image-upload.md §6)."
)

# §8's `expected_hash`: `sha256:` plus the 64 hex digits `digest_of` returns,
# or the empty string meaning "the file does not exist" (a plain create). The
# shape is checked so a typo is a 400 -- a malformed request -- rather than a
# conflict that can never match.
_HASH_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def sniff_image(data: bytes) -> str | None:
    """The kind the file's first bytes actually are, or None for anything
    without an accepted signature. Signature bytes only -- this does not
    validate the image, and does not need to: the gate is 'these bytes are
    this format', not 'this file renders' (§6)."""
    for kind, prefixes in _SIGNATURES:
        if data.startswith(prefixes):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Uploaded:
    """Bytes are at `rel` -- written now as a new file (`created`), written
    now over a file the author confirmed they meant to replace (`replaced`), or
    already there byte for byte and left alone (§5's idempotent row). Exactly
    one of the three is true, and `replaced` is the answer to "did this change
    what other pages show", which is §9.3's subject rather than a new failure.

    `referenced_by` names the items whose bodies currently resolve to this
    file: a disclosure, not a gate (§9.3 -- "not a refusal ... but the editor
    must not let them discover the blast radius afterwards")."""

    rel: str
    digest: str
    size: int
    created: bool
    message: str
    replaced: bool = False
    referenced_by: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Conflict:
    """Something else is at the destination, or the hash the client confirmed
    against is not the hash that is there now. §5: nothing is silently
    renamed, suffixed, or overwritten; §8: the author's re-issue with the hash
    just returned *is* the confirmation. `kind` says which of the two the
    client is looking at, because the two ask different things of it --
    "collision" means choose between replacing this file and picking another
    name, "expected_hash" means the file moved under you and only the current
    hash can decide again. `current_hash` is the hash a re-issue must carry,
    and `current_size` the fact an author can compare without a diff (there
    is no diff of two PNGs, §8)."""

    rel: str
    reason: str
    kind: str = "collision"
    current_hash: str | None = None
    current_size: int | None = None
    referenced_by: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Refused:
    """The request is well formed and asks for something this endpoint will not
    do. `kind` names which rule said no, so the client can say something
    specific rather than "upload failed": "ambiguity" (§9.1, fixable by another
    name or another directory) and "capture" (§9.2, fixable by changing the
    reference in the other item) are the two checks against other documents.
    `details` carries the same facts the reason spells out, as rows, for a
    dialog that wants to list them."""

    reason: str
    status: int = 422
    kind: str = "refused"
    details: tuple[dict, ...] = ()


def _validate_name(name: str) -> tuple[str, str] | Refused:
    """The author's filename, reduced to one safe segment or refused. A
    client-supplied path is never joined to anything and never normalized
    into safety: a name carrying a separator or `..` is a refusal, not a
    puzzle to resolve (§5). `safe_relative_parts` supplies the shared rules
    (no `.`/`..`, no backslash, drive or ADS colon, NUL, reserved Windows
    device names, no trailing space or dot)."""
    if not name:
        return Refused("name is required: a single filename, not a path", 400)
    if "/" in name or "\\" in name:
        return Refused(
            f"name {name!r} must be a single filename: no directories, no separators", 400
        )
    parts = security.safe_relative_parts(name)
    if parts is None or len(parts) != 1:
        return Refused(f"name {name!r} is not a safe filename", 400)
    ext = os.path.splitext(name)[1].lower()
    if ext == ".svg":
        return Refused(SVG_REFUSAL)
    return (name, ext)


def _validate_dest(root: str, dest: str) -> tuple[str, tuple[str, ...]] | Refused:
    """The destination directory, validated independently of the name (§5:
    both halves are checked on their own, never a joined client path).
    Must be an existing directory inside the project under real-path
    containment -- the endpoint creates no directories -- and never anything
    under `.refdes/`, which is refdes's own state (§4, §13)."""
    parts = security.safe_relative_parts(dest) if dest else []
    if parts is None:
        return Refused(
            f"destination {dest!r} is not a safe project-relative directory: no '..', "
            "no backslash, no drive or ADS colon, no reserved device names",
            400,
        )
    if any(part == ".refdes" for part in parts):
        return Refused(
            "the .refdes/ directory is refdes's own state; an uploaded image belongs "
            "in the tracked tree where a review sees it (§4)",
            400,
        )
    dest_dir = os.path.join(root, *parts)
    if not os.path.isdir(dest_dir):
        return Refused(
            f"destination directory {dest or '.'} does not exist; the upload creates no directories",
            400,
        )
    root_real = os.path.realpath(root)
    dest_real = os.path.realpath(dest_dir)
    if dest_real != root_real and not dest_real.startswith(root_real + os.sep):
        return Refused(
            f"destination {dest!r} resolves outside the project root (via a symlink?)", 400
        )
    return dest_dir, tuple(parts)


def _check_type(name: str, ext: str, data: bytes) -> str | Refused:
    kind = sniff_image(data)
    if kind is None:
        return Refused(
            "the request bytes do not carry a recognized image signature; accepted: "
            "PNG, JPEG, GIF, WebP (the type is read from the bytes, not the name "
            "or the Content-Type)"
        )
    if ACCEPTED_EXTENSIONS.get(ext) != kind:
        claimed = ext or "no extension"
        return Refused(
            f"name {name!r} claims {claimed} but the bytes are {kind}; "
            "the extension must agree with the file's signature"
        )
    return kind


# ----------------------------------------------------- the §9 checks, before the write
#
# Three checks, one shared input. The build already decided, for every image
# reference in every item body, which file that reference resolves to, and
# recorded it in `Project.image_results` (`build._process_images`); and the
# build's own bare-name search is a pure function of the project and a leaf
# name (`build._search_image_matches`). So "what would this file change?" is a
# question about values the build computed anyway -- no second resolution
# pass, and no third spelling of the rule that could drift from the two the
# build already has.


def _source_files_by_id(project: Project) -> dict[str, str]:
    """display id -> that item's source file, project-relative with forward
    slashes (the spelling `image_results`' `rel` and this module's `rel` both
    use). An id with no item -- a stale record -- is simply absent, and the
    checks skip it rather than guess a directory."""
    return {
        item.id: item.source_file.replace("\\", "/")
        for item in project.items.values()
        if item.id and item.source_file
    }


def _on_search_path(project: Project, rel: str) -> bool:
    """Whether `rel` would be found by the bare-name `site.assets:` search --
    i.e. it sits under one of the declared directories, compared by real path
    so a symlink cannot put a file on the search path (or off it) by pointing
    somewhere else. A destination outside every declared directory is not on
    the search path at all, which is why §4's default destination cannot be
    ambiguous."""
    root = project.root
    target = os.path.realpath(os.path.join(root, *rel.split("/")))
    for rel_dir in project.asset_dirs:
        base = os.path.realpath(os.path.join(root, *rel_dir.replace("\\", "/").split("/")))
        if target == base or target.startswith(base + os.sep):
            return True
    return False


def _referencing_items(project: Project, rel: str, sources: dict[str, str]) -> list[dict]:
    """Every item whose body currently resolves to the file at `rel` (§9.3).

    `image_results` is keyed by display id and records the *resolved* project
    path, so this is the reverse mapping the design calls "free": an item whose
    src is ambiguous or dangling has `rel: None` and is not counted, because
    it is not currently showing this file."""
    rows: list[dict] = []
    for item_id, records in sorted(project.image_results.items()):
        if not any(r.get("ok") and r.get("rel") == rel for r in records):
            continue
        rows.append(
            {
                "item": item_id,
                "source_file": sources.get(item_id, ""),
                "srcs": sorted({r.get("src", "") for r in records if r.get("rel") == rel}),
            }
        )
    return rows


def _ambiguity_refusal(project: Project, rel: str, matches: list[str]) -> Refused | None:
    """§9.1: refuse a write that would put a second file with this leaf on the
    search path.

    The condition is stated as what the *build* would do, not as a comparison
    of directory lists, and computed by the build's own search: after this
    write, `_search_image_matches` would return these candidates plus the
    proposed file, and `_search_image_src` turns "more than one" into a build
    error naming every candidate (docs/markdown.md: "Two matches is a build
    error, not a tie-break"). A leaf that is already among the matches -- an
    existing file, which is what a replace targets -- adds nothing to the
    search, so it is not this check's business; a destination that is not on
    the search path at all cannot make anything ambiguous.

    `matches` is passed in rather than recomputed so the caller and this
    function cannot disagree about what is there."""
    if not matches or rel in matches or not _on_search_path(project, rel):
        return None
    return Refused(
        f"{rel} would be a second {posixpath.basename(rel)!r} on the site.assets: "
        f"search path: {', '.join(matches)} is already there, and a bare reference to "
        f"that filename is resolved by searching the declared directories, so a bare "
        f"reference to it would be ambiguous -- two matches is a build error naming "
        f"every candidate rather than a tie-break -- and this would break documents "
        f"that work today (docs/design/editor-image-upload.md §9.1, docs/markdown.md). "
        f"Nothing was written: upload under a different name, into a directory that is "
        f"not a declared site.assets: directory, or rename {matches[0]}",
        422,
        kind="ambiguity",
        details=tuple({"path": m} for m in matches),
    )


def _capture_refusal(
    project: Project, rel: str, sources: dict[str, str]
) -> Refused | None:
    """§9.2: refuse a write that would silently re-point another item's image.

    The relative lookup runs first and always wins (docs/markdown.md), so
    landing `curve.png` beside an item's source silently re-points a bare
    `curve.png` in *any* item in that same directory -- including one the
    author never opened, and including their own. The last build recorded what
    each of those references resolves to, so the check is a scan of
    `image_results`, not a re-render.

    Scoped to items whose source file sits in the proposed destination
    directory, because that is exactly the set whose relative lookup would find
    this file: an item one directory up looks in its own directory, not here.
    A reference that already resolves *to this path* is not a capture -- that
    is the replace case, and §9.3's disclosure is what it needs.

    A reference that resolves to nothing counts too. Whether it is a build
    error because the file is missing or because the name is already ambiguous
    on the search path, the page is not showing this picture, and landing the
    file changes what it shows -- the design's rule is "whose resolved `rel` is
    not that directory", and `None` is not that directory either."""
    dest_dir = posixpath.dirname(rel)
    leaf = posixpath.basename(rel)
    rows: list[dict] = []
    for item_id, records in sorted(project.image_results.items()):
        source_file = sources.get(item_id)
        if source_file is None or posixpath.dirname(source_file) != dest_dir:
            continue
        for record in records:
            # The build only records the src as written, so this is a bare
            # filename or nothing: a src with a separator never reached the
            # search and is not capturable by a file in this directory.
            if record.get("src") != leaf:
                continue
            resolved = record.get("rel") if record.get("ok") else None
            if resolved == rel:
                continue
            rows.append(
                {
                    "item": item_id,
                    "source_file": source_file,
                    "src": leaf,
                    "resolves_to": resolved,
                    "why": (
                        "that image currently resolves elsewhere, and a path that "
                        "resolves beside its own source file always wins, so landing "
                        "this file would silently re-point it"
                        if resolved
                        else (
                            "that image resolves to nothing today (its src is a build "
                            "error), so landing this file would change what its page "
                            "shows"
                        )
                    ),
                }
            )
    if not rows:
        return None
    named = "; ".join(
        f"{row['item']} ({row['source_file']}) writes {leaf!r}, which "
        + (f"resolves to {row['resolves_to']} today" if row["resolves_to"] else "resolves to nothing today")
        for row in rows
    )
    return Refused(
        f"{rel} would capture a bare-name reference in another document: {named}. A "
        f"src that resolves beside its own source file always wins over the "
        f"site.assets: search, so nothing would error -- the page would just show a "
        f"different picture than it does now (docs/design/editor-image-upload.md "
        f"§9.2). Nothing was written: upload under another name, or change those "
        f"references to a path relative to their own source file",
        422,
        kind="capture",
        details=tuple(rows),
    )


def _check_expected_hash(expected_hash: str) -> str | Refused:
    """§8's `expected_hash`, normalized: the empty string for a plain create,
    or `sha256:<64 hex>` lowercased so the comparison is about the digest and
    not about how a client cased it. A malformed value is a 400 -- a request
    that could never match anything is not a conflict, it is a typo."""
    if not expected_hash:
        return ""
    if not _HASH_RE.match(expected_hash):
        return Refused(
            "expected_hash must be 'sha256:' followed by 64 hex digits -- the hash a "
            "previous response returned -- or empty to mean 'the file does not exist' "
            "(docs/design/editor-image-upload.md §8)",
            400,
        )
    return expected_hash.lower()


def store_asset(
    project: Project,
    *,
    dest: str,
    name: str,
    data: bytes,
    expected_hash: str = "",
):
    """Store one uploaded image in the project. Returns `Uploaded`, `Conflict`,
    or `Refused`; on any non-`Uploaded` nothing is written.

    `project` is the built model, not a path: the §9 checks are questions about
    what the *build* resolves, and they answer them from the build's own
    bookkeeping (`Project.image_results`) and its own search
    (`build._search_image_matches`). A path could not answer them, and
    re-deriving the rules here would be a third spelling of image resolution
    that can drift from the two the build already has.

    `expected_hash` is §8's binary `expected_revision`: the hash of the bytes
    the client believes are at the destination, or empty to mean "it is not
    there yet". It turns a §5 collision into the author's confirmation and
    nothing else -- a hash that does not match is still a `Conflict`, with
    nothing written.

    The whole decide-then-write sequence runs under the project's write lock:
    the §5 collision table and the §9 checks are all check-then-act, and an
    unguarded one can be raced by a concurrent upload or save of the same path.
    """
    root = os.path.abspath(project.root)

    checked = _validate_name(name)
    if isinstance(checked, Refused):
        return checked
    name, ext = checked

    # The second half of §6's double bound: the transport refused a
    # `Content-Length` over the cap, and this refuses the bytes in hand, so no
    # caller -- today or after a refactor to a streaming read -- lands more than
    # the cap on disk.
    if len(data) > MAX_ASSET_BYTES:
        return Refused(
            f"{len(data)} bytes is over the {MAX_ASSET_BYTES}-byte upload limit "
            "(docs/design/editor-image-upload.md §6); nothing was written",
            413,
        )

    checked_dest = _validate_dest(root, dest)
    if isinstance(checked_dest, Refused):
        return checked_dest
    dest_dir, dest_parts = checked_dest

    verdict = _check_type(name, ext, data)
    if isinstance(verdict, Refused):
        # The bytes refuse here: signature unknown, or disagreeing with the
        # name. (A `.svg` *name* was already refused in _validate_name, with
        # the CSP reason, before any byte was looked at.)
        return verdict

    checked_hash = _check_expected_hash(expected_hash)
    if isinstance(checked_hash, Refused):
        return checked_hash
    expected_hash = checked_hash

    rel = "/".join([*dest_parts, name])
    target = os.path.join(dest_dir, name)

    with write_lock_for(root):
        # Case-only collision first: on a case-insensitive filesystem the
        # exact-spelling check below would read the *other* file's bytes and
        # call a different file "identical" or "conflicting" without naming
        # what is really there. `case_mismatch` is the existing answer to
        # "does this exist only case-insensitively?" (citations.py).
        mismatched = case_mismatch(root, rel)
        if mismatched is not None:
            existing_rel = os.path.relpath(mismatched, root).replace("\\", "/")
            return Conflict(
                rel,
                f"{rel} differs only in case from the existing {existing_rel}; "
                "on a case-insensitive checkout these are the same file and on a "
                "case-sensitive one they are two -- pick the existing spelling or "
                "a different name",
            )

        # §9.1, before anything is written: would this file put a second copy
        # of the leaf on the search path? Asked of the build's own search, with
        # the leaf exactly as it will be written, and vacuous both for a
        # destination that is not on the search path (§4's default) and for a
        # leaf that is already one of the matches (a replace adds nothing).
        refusal = _ambiguity_refusal(project, rel, _search_image_matches(project, name))
        if refusal is not None:
            return refusal

        sources = _source_files_by_id(project)

        if os.path.exists(target):
            try:
                with open(target, "rb") as fh:
                    existing = fh.read()
            except OSError as exc:
                return Refused(f"could not read the existing {rel}: {exc}", 500)
            current = digest_of(existing)
            # §9.3: every outcome that leaves a file at `rel` discloses the
            # items currently showing it. The refusal for a *sealed* referrer
            # is Phase 3's (§10); the disclosure is here, because the author has
            # to know the blast radius before they confirm, not afterwards.
            referencing = tuple(_referencing_items(project, rel, sources))

            if existing == data:
                # §5 row 2: identical bytes are not a conflict. No write --
                # not even a rewrite of the same bytes -- and the client
                # inserts the reference anyway.
                return Uploaded(
                    rel=rel,
                    digest=current,
                    size=len(existing),
                    created=False,
                    message="identical bytes already at the destination; nothing was written",
                    referenced_by=referencing,
                )

            if not expected_hash:
                return Conflict(
                    rel,
                    f"{rel} already exists with different bytes "
                    f"({len(existing)} bytes, {current}); nothing was written -- "
                    "replace it or choose another name",
                    current_hash=current,
                    current_size=len(existing),
                    referenced_by=referencing,
                )

            if expected_hash != current:
                # §8: the bytes the client confirmed are not the bytes that are
                # there. Nothing is written, and the current hash goes back so
                # the client can re-fetch and decide again rather than guess.
                return Conflict(
                    rel,
                    f"expected_hash {expected_hash} does not match the "
                    f"{len(existing)} bytes at {rel}, which now hash to {current}; "
                    "nothing was written -- that file changed since you looked at "
                    f"it. Re-issue with expected_hash={current} to replace it anyway, "
                    "or choose another name",
                    kind="expected_hash",
                    current_hash=current,
                    current_size=len(existing),
                    referenced_by=referencing,
                )

            # §8 row 1: the client confirmed this exact version, so replace it
            # through the same atomic write every other edit uses.
            # `_atomic_replace` re-reads and compares after the write and puts
            # the original bytes back if they disagree.
            failure = _atomic_replace(target, data)
            if failure is not None:
                return Refused(failure, 500)

            return Uploaded(
                rel=rel,
                digest=digest_of(data),
                size=len(data),
                created=False,
                replaced=True,
                message=f"replaced the {len(existing)} bytes at {rel} ({current}) with "
                f"{len(data)} bytes ({digest_of(data)})",
                referenced_by=referencing,
            )

        if expected_hash:
            # §8 row 4: the file the author meant to replace is gone. A create
            # was not what was asked for, so this is not quietly downgraded to
            # one.
            return Conflict(
                rel,
                f"expected_hash {expected_hash} was sent but there is no file at {rel}; "
                "nothing was written -- the file you meant to replace is gone. Re-issue "
                "with no expected_hash to create it, or choose another name",
                kind="expected_hash",
            )

        # §9.2, before anything is written: does landing this file change what
        # another item's page shows?
        refusal = _capture_refusal(project, rel, sources)
        if refusal is not None:
            return refusal

        failure = _atomic_create(target, data)
        if failure is not None:
            return Refused(failure)

    return Uploaded(
        rel=rel,
        digest=digest_of(data),
        size=len(data),
        created=True,
        message="written",
    )
