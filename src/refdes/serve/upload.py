"""Byte storage for `POST /api/assets` (docs/design/editor-image-upload.md).

Phase 1 ("Bytes", §17): the destination, the name, the sniffed type, the §5
collision table, and one atomic create. Refusals are values, not exceptions,
in `serve/edit.py`'s style; `serve/api.py` turns them into status codes.

Explicitly not here yet: the `expected_hash` replace path (§8) and the §9
checks against other documents -- Phase 2 -- and the §10 sealed-target and
sealed-referenced refusals -- Phase 3. The design documents the hole Phase 1
leaves open (an upload can break another document) and orders the phases
around closing it; do not "fix" it here.

The endpoint writes one file, at a path built from a validated destination
directory and a validated single-segment name, inside the project root with
real-path containment (`citations.classify` is the model). It creates no
directories, follows no symlinked destination, deletes nothing, and touches
no `.md` or `.yaml` file (§11).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from ..citations import case_mismatch
from . import security
from .edit import _atomic_create, write_lock_for

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
    """Bytes are at `rel` -- written now (`created`) or already there, byte
    for byte, and left alone (§5's idempotent row)."""

    rel: str
    digest: str
    size: int
    created: bool
    message: str


@dataclass(frozen=True)
class Conflict:
    """Something else is at the destination. §5: nothing is silently renamed,
    suffixed, or overwritten; the refusal names the existing file and the
    author's two real choices (replace -- Phase 2 -- or another name)."""

    rel: str
    reason: str


@dataclass(frozen=True)
class Refused:
    reason: str
    status: int = 422


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


def store_asset(project_root: str, *, dest: str, name: str, data: bytes):
    """Store one uploaded image under the project root. Returns `Uploaded`,
    `Conflict`, or `Refused`; on any non-`Uploaded` nothing is written.

    The whole decide-then-write sequence runs under the project's write lock:
    the §5 collision table is a check-then-act, and an unguarded one can be
    raced by a concurrent save of the same path."""
    root = os.path.abspath(project_root)

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

        if os.path.exists(target):
            try:
                with open(target, "rb") as fh:
                    existing = fh.read()
            except OSError as exc:
                return Refused(f"could not read the existing {rel}: {exc}", 500)
            if existing == data:
                # §5 row 2: identical bytes are not a conflict. No write --
                # not even a rewrite of the same bytes -- and the client
                # inserts the reference anyway.
                return Uploaded(
                    rel=rel,
                    digest=digest_of(existing),
                    size=len(existing),
                    created=False,
                    message="identical bytes already at the destination; nothing was written",
                )
            return Conflict(
                rel,
                f"{rel} already exists with different bytes "
                f"({len(existing)} bytes, {digest_of(existing)}); nothing was written -- "
                "replace it or choose another name",
            )

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
