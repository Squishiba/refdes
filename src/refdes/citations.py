"""Datasheet citations: declared intent in items, computed provenance in a lockfile.

An item's `citations:`-typed field says what it means to cite -- a url, maybe a
rev, page, or part number, and whether the bytes should be vendored. That is all
ordinary invalidate-mode data, hashed like any other field.

What a citation actually *resolved to* -- its sha256, when it was fetched,
whether it was vendored -- is a different kind of fact: it changes when someone
runs `refdes fetch`, not when someone edits an item. Mixing it into the item
would mean re-fetching a datasheet could retroactively mark a sealed log entry,
or any other suspect-link consumer of an item's content hash, as edited. So it
lives instead in a committed lockfile, `.refdes/citations.yaml`, keyed by path.

A citation's `path:` is one field dispatched on scheme (finding 25 Part 2):
`http`/`https` means remote -- fetched, hashed, optionally vendored, exactly as
ever -- and anything else means a file inside the project, relative to the
project root, hashed from its local bytes at build time. Absolute paths, drive
letters, backslashes, and anything that escapes the project root are refused,
never guessed; `vendor:` on a local path is a hard error.

The bytes themselves are a third kind of fact, and the biggest: `vendor: true`
opts a citation into keeping a local copy, content-addressed at
`.refdes/vendor/<sha256><ext>`. That directory is gitignored -- manufacturer
datasheets are generally copyrighted, so vendoring is opt-in and defaults off.
Hash-only "pinned but not vendored" is a first-class, complete mode on its own.

`refdes fetch` is the only thing in this module that touches the network, and
only when actually invoked. Everything else here -- `verify`, `by_path` --
reads only the lockfile, the local vendor cache, and (for local citations)
files inside the project, so `build` and `check` stay hermetic.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import yaml

from .model import CitationSpec, CitationStatus, Item, PartUsage, Project
from .parse import yaml_safe_load

LOCKFILE = ".refdes/citations.yaml"
VENDOR_DIR = ".refdes/vendor"


class CitationError(Exception):
    pass


# ------------------------------------------------------------------------ paths


def lockfile_path(project: Project) -> str:
    return os.path.join(project.root, LOCKFILE)


def vendor_dir(project: Project) -> str:
    return os.path.join(project.root, VENDOR_DIR)


def vendor_path(project: Project, sha256: str, path: str) -> str:
    ext = os.path.splitext(urlparse(path).path)[1]
    return os.path.join(vendor_dir(project), f"{sha256}{ext}")


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
            " this looks like a Windows drive letter, not a scheme"
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
        "# sha256, fetch timestamp, vendored flag -- keyed by the citation's path:\n"
        "# value (URL or project-relative file). Written only by `refdes fetch`.\n"
        "# Never hand-edit the sha256.\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(
            {"citations": records}, fh, sort_keys=True, default_flow_style=False
        )


# -------------------------------------------------------------------- collection


def collect(project: Project) -> list[tuple[Item, CitationSpec]]:
    """Every citation declared across every `citations:`-typed field, in order."""
    out: list[tuple[Item, CitationSpec]] = []
    for item in project.local_items:
        spec = project.types.get(item.type)
        if spec is None:
            continue
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
                    (
                        item,
                        CitationSpec(
                            field=fname,
                            index=index,
                            path=str(entry["path"]),
                            rev=str(entry.get("rev") or ""),
                            page=str(entry.get("page") or ""),
                            part_number=str(entry.get("part_number") or ""),
                            vendor=bool(entry.get("vendor", False)),
                            id=str(entry.get("id") or ""),
                        ),
                    )
                )
    return out


def by_path(
    project: Project, board: str | None = None, workspace: str | None = None
) -> dict[str, list[CitationStatus]]:
    """`item.citations`, regrouped by path -- for `audit` and `references.html`.

    `board`/`workspace`, when given, scope this to that board's or workspace's
    own items, the same way `render._document_sections` and friends scope the
    other per-board/per-workspace reports. Callers pass at most one of the two.

    Only meaningful after `verify()` has run (via `build()`), which is what
    populates `item.citations` in the first place.
    """
    grouped: dict[str, list[CitationStatus]] = defaultdict(list)
    for item in project.local_items:
        if board is not None and item.board != board:
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
    `verify()`). `board`/`workspace` scope the same way `by_path` does.
    """
    grouped: dict[str, PartUsage] = {}

    def usage(part_number: str) -> PartUsage:
        return grouped.setdefault(part_number, PartUsage(part_number=part_number))

    for item in project.local_items:
        if board is not None and item.board != board:
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
    """Resolve every declared citation against the lockfile and the vendor cache.

    Hermetic -- reads `.refdes/citations.yaml`, `.refdes/vendor/`, and cited
    local files, but touches no network. Severities:

      no lockfile entry     -- info (routine until `refdes fetch` runs), or
                                error with `require` (CI)
      vendored but no blob  -- warning, or error with `require` (CI)
      blob hash mismatch    -- ERROR always, never soft-failed: a corrupted or
                                tampered local cache is not something to wave
                                through in CI
      local file missing    -- ERROR always: a cited file that isn't there is
                                not a routine state
      local file changed    -- warning naming every citer (review the change,
                                then re-pin), or error with `require` (CI)
      inconsistent vendor:  -- warning, always (not promoted by `require`;
      across citers of a       it is a hygiene note about the declaration, not
      shared url                a missing artifact)
    """
    entries = collect(project)
    if not entries:
        return

    records = load_lockfile(project)
    severity = project.error if require else project.warn
    unpinned_severity = project.error if require else project.info

    grouped: dict[str, list[tuple[Item, CitationSpec]]] = defaultdict(list)
    changed_local: dict[str, list[str]] = defaultdict(list)
    for item, spec in entries:
        grouped[spec.path].append((item, spec))
        item.citations.append(
            _resolve(
                project, item, spec, records.get(spec.path),
                severity, unpinned_severity, changed_local,
            )
        )

    for canon, citers in sorted(changed_local.items()):
        ids = ", ".join(sorted(set(citers)))
        (project.error if require else project.warn)(
            f"local citation {canon!r} has changed since it was pinned -- "
            f"review the change, then run 'refdes fetch --update --path "
            f"{canon}' (cited by {ids})"
        )

    for path, citers in grouped.items():
        if classify(project.root, path)[0] != "remote":
            continue  # vendor: on a local path is a validation error, not a flag to reconcile
        vendor_flags = {spec.vendor for _item, spec in citers}
        if len(vendor_flags) > 1:
            ids = ", ".join(sorted({item.id for item, _spec in citers}))
            project.warn(
                f"citation {path!r} is cited with inconsistent vendor: flags "
                f"across {ids} -- pick one so the vendoring decision is "
                f"unambiguous"
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
    status.vendored = bool(record.get("vendored", False))
    if not status.vendored:
        return status

    blob = vendor_path(project, status.sha256, spec.path)
    if not os.path.isfile(blob):
        status.state = "cache_missing"
        status.detail = (
            f"vendored copy of {spec.path} is missing at "
            f"{os.path.relpath(blob, project.root)}"
        )
        severity(status.detail, file=item.source_file, line=item.source_line, item_id=item.id)
        return status

    actual = _sha256_file(blob)
    if actual != status.sha256:
        status.state = "hash_mismatch"
        status.detail = (
            f"vendored copy of {spec.path} does not match its recorded hash "
            f"(cache is tampered or corrupt)"
        )
        project.error(status.detail, file=item.source_file, line=item.source_line, item_id=item.id)
        return status

    if project.publish_datasheets:
        # Flattened (assets/datasheets/<sha256><ext>), not mirrored under
        # `.refdes/vendor/` -- a dot-prefixed directory is skipped by several
        # static hosts, GitHub Pages via Jekyll included. Tracked separately
        # from `project.assets`, whose copy step mirrors source path to dest
        # path; here they differ, so render_site copies this dict instead.
        ext = os.path.splitext(blob)[1]
        status.local_path = f"datasheets/{status.sha256}{ext}"
        project.datasheet_assets[status.local_path] = blob
    return status


def _resolve_local(project, item, spec, canon, record, status, unpinned_severity, changed_local):
    """Resolve a repo-local citation (finding 25 Part 2): the file itself is
    the artifact -- no fetch, no vendor cache, no publish_datasheets gate (the
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
    vendored: bool = False
    skipped: bool = False
    error: str = ""


def fetch_all(
    project: Project,
    item_id: str | None = None,
    path: str | None = None,
    update: bool = False,
    fetcher=None,
) -> list[FetchResult]:
    """Fetch every path a citation declares (optionally scoped), pin it, vendor it.

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

    wants_vendor: dict[str, bool] = defaultdict(bool)
    for _item, spec in entries:
        wants_vendor[spec.path] = wants_vendor[spec.path] or spec.vendor

    records = load_lockfile(project)
    results: list[FetchResult] = []
    changed = False

    for target in sorted(wants_vendor):
        kind, canon = classify(project.root, target)
        want_vendor = wants_vendor[target]
        if kind == "local" and want_vendor:
            raise CitationError(
                f"vendor: on local citation path {canon!r} is meaningless -- "
                f"a local file is already local"
            )
        if canon in records and not update:
            existing = records[canon]
            results.append(
                FetchResult(
                    path=canon,
                    sha256=str(existing.get("sha256") or ""),
                    vendored=bool(existing.get("vendored")),
                    skipped=True,
                )
            )
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
        if want_vendor:
            os.makedirs(vendor_dir(project), exist_ok=True)
            with open(vendor_path(project, digest, canon), "wb") as fh:
                fh.write(data)

        records[canon] = {
            "sha256": digest,
            "fetched": _now_iso(),
            "vendored": want_vendor,
            "bytes": len(data),
        }
        changed = True
        results.append(FetchResult(path=canon, sha256=digest, vendored=want_vendor))

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

    Read-only: writes nothing, pins nothing, vendors nothing. Only reachable via
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
        if classify(project.root, target)[0] != "remote":
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
