"""Datasheet citations: declared intent in items, computed provenance in a lockfile.

An item's `citations:`-typed field says what it means to cite -- a url, maybe a
rev, page, or part number, and whether the bytes should be vendored. That is all
ordinary invalidate-mode data, hashed like any other field.

What a citation actually *resolved to* -- its sha256, when it was fetched,
whether it was vendored -- is a different kind of fact: it changes when someone
runs `refdes fetch`, not when someone edits an item. Mixing it into the item
would mean re-fetching a datasheet could retroactively mark a sealed log entry,
or any other suspect-link consumer of an item's content hash, as edited. So it
lives instead in a committed lockfile, `.refdes/citations.yaml`, keyed by url.

The bytes themselves are a third kind of fact, and the biggest: `vendor: true`
opts a citation into keeping a local copy, content-addressed at
`.refdes/vendor/<sha256><ext>`. That directory is gitignored -- manufacturer
datasheets are generally copyrighted, so vendoring is opt-in and defaults off.
Hash-only "pinned but not vendored" is a first-class, complete mode on its own.

`refdes fetch` is the only thing in this module that touches the network, and
only when actually invoked. Everything else here -- `verify`, `by_url` -- reads
only the lockfile and the local vendor cache, so `build` and `check` stay
hermetic.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import yaml

from .model import CitationSpec, CitationStatus, Item, Project

LOCKFILE = ".refdes/citations.yaml"
VENDOR_DIR = ".refdes/vendor"


class CitationError(Exception):
    pass


# ------------------------------------------------------------------------ paths


def lockfile_path(project: Project) -> str:
    return os.path.join(project.root, LOCKFILE)


def vendor_dir(project: Project) -> str:
    return os.path.join(project.root, VENDOR_DIR)


def vendor_path(project: Project, sha256: str, url: str) -> str:
    ext = os.path.splitext(urlparse(url).path)[1]
    return os.path.join(vendor_dir(project), f"{sha256}{ext}")


# --------------------------------------------------------------------- lockfile


def load_lockfile(project: Project) -> dict[str, dict]:
    path = lockfile_path(project)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return dict(data.get("citations") or {})


def save_lockfile(project: Project, records: dict[str, dict]) -> None:
    path = lockfile_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# Refdes citation lockfile. Computed provenance for each cited URL --\n"
        "# sha256, fetch timestamp, vendored flag -- keyed by URL. Written only by\n"
        "# `refdes fetch`. Never hand-edit the sha256.\n"
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
                if not isinstance(entry, dict) or not entry.get("url"):
                    continue  # malformed -- reported by validate_items
                out.append(
                    (
                        item,
                        CitationSpec(
                            field=fname,
                            index=index,
                            url=str(entry["url"]),
                            rev=str(entry.get("rev") or ""),
                            page=str(entry.get("page") or ""),
                            part_number=str(entry.get("part_number") or ""),
                            vendor=bool(entry.get("vendor", False)),
                        ),
                    )
                )
    return out


def by_url(project: Project, board: str | None = None) -> dict[str, list[CitationStatus]]:
    """`item.citations`, regrouped by url -- for `audit` and `references.html`.

    `board`, when given, scopes this to that board's own items, the same way
    `render._document_sections` and friends scope the other per-board reports.

    Only meaningful after `verify()` has run (via `build()`), which is what
    populates `item.citations` in the first place.
    """
    grouped: dict[str, list[CitationStatus]] = defaultdict(list)
    for item in project.local_items:
        if board is not None and item.board != board:
            continue
        for status in item.citations:
            grouped[status.spec.url].append(status)
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

    Hermetic -- reads `.refdes/citations.yaml` and `.refdes/vendor/`, touches no
    network. Severities:

      no lockfile entry     -- info (routine until `refdes fetch` runs), or
                                error with `require` (CI)
      vendored but no blob  -- warning, or error with `require` (CI)
      blob hash mismatch    -- ERROR always, never soft-failed: a corrupted or
                                tampered local cache is not something to wave
                                through in CI
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
    for item, spec in entries:
        grouped[spec.url].append((item, spec))
        item.citations.append(
            _resolve(project, item, spec, records.get(spec.url), severity, unpinned_severity)
        )

    for url, citers in grouped.items():
        vendor_flags = {spec.vendor for _item, spec in citers}
        if len(vendor_flags) > 1:
            ids = ", ".join(sorted({item.id for item, _spec in citers}))
            project.warn(
                f"citation {url!r} is cited with inconsistent vendor: flags "
                f"across {ids} -- pick one so the vendoring decision is "
                f"unambiguous"
            )


def _resolve(project, item, spec, record, severity, unpinned_severity) -> CitationStatus:
    status = CitationStatus(spec=spec, item_id=item.id)
    if record is None:
        status.state = "unpinned"
        status.detail = (
            f"citation to {spec.url} has no fetched record; run "
            f"'refdes fetch --url {spec.url}' to pin it"
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

    blob = vendor_path(project, status.sha256, spec.url)
    if not os.path.isfile(blob):
        status.state = "cache_missing"
        status.detail = (
            f"vendored copy of {spec.url} is missing at "
            f"{os.path.relpath(blob, project.root)}"
        )
        severity(status.detail, file=item.source_file, line=item.source_line, item_id=item.id)
        return status

    actual = _sha256_file(blob)
    if actual != status.sha256:
        status.state = "hash_mismatch"
        status.detail = (
            f"vendored copy of {spec.url} does not match its recorded hash "
            f"(cache is tampered or corrupt)"
        )
        project.error(status.detail, file=item.source_file, line=item.source_line, item_id=item.id)
        return status

    status.local_path = os.path.relpath(blob, project.root).replace("\\", "/")
    # Reuses Part A's asset-copy machinery rather than a second copy path:
    # render_site copies everything in `project.assets` into `_site/assets/`,
    # mirroring this same project-root-relative path.
    project.assets.add(status.local_path)
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
    url: str
    sha256: str = ""
    vendored: bool = False
    skipped: bool = False
    error: str = ""


def fetch_all(
    project: Project,
    item_id: str | None = None,
    url: str | None = None,
    update: bool = False,
    fetcher=None,
) -> list[FetchResult]:
    """Fetch every url a citation declares (optionally scoped), pin it, vendor it.

    Only ever called from `refdes fetch` -- the one command allowed to touch the
    network. Already-pinned urls are skipped unless `update` is set, so a
    routine re-run does not re-download anything.

    `fetcher` defaults to the module-level `fetch_bytes`, looked up at call time
    (not bound as a parameter default) so tests can monkeypatch
    `citations.fetch_bytes` and have it take effect even through `refdes fetch`,
    which never passes `fetcher` itself.
    """
    fetcher = fetcher or fetch_bytes
    entries = collect(project)
    if item_id is not None:
        if item_id not in project.items:
            raise CitationError(f"no item {item_id!r} in this project")
        entries = [(item, spec) for item, spec in entries if item.id == item_id]
        if not entries:
            raise CitationError(f"item {item_id!r} declares no citations")
    if url is not None:
        entries = [(item, spec) for item, spec in entries if spec.url == url]
        if not entries:
            raise CitationError(f"no citation in this project cites {url!r}")

    wants_vendor: dict[str, bool] = defaultdict(bool)
    for _item, spec in entries:
        wants_vendor[spec.url] = wants_vendor[spec.url] or spec.vendor

    records = load_lockfile(project)
    results: list[FetchResult] = []
    changed = False

    for target_url in sorted(wants_vendor):
        if target_url in records and not update:
            existing = records[target_url]
            results.append(
                FetchResult(
                    url=target_url,
                    sha256=str(existing.get("sha256") or ""),
                    vendored=bool(existing.get("vendored")),
                    skipped=True,
                )
            )
            continue

        try:
            data = fetcher(target_url)
        except Exception as exc:  # noqa: BLE001 -- surfaced per-url, not fatal
            results.append(FetchResult(url=target_url, error=str(exc)))
            continue

        digest = hashlib.sha256(data).hexdigest()
        want_vendor = wants_vendor[target_url]
        if want_vendor:
            os.makedirs(vendor_dir(project), exist_ok=True)
            with open(vendor_path(project, digest, target_url), "wb") as fh:
                fh.write(data)

        records[target_url] = {
            "sha256": digest,
            "fetched": _now_iso(),
            "vendored": want_vendor,
            "bytes": len(data),
        }
        changed = True
        results.append(FetchResult(url=target_url, sha256=digest, vendored=want_vendor))

    if changed:
        save_lockfile(project, records)
    return results


# ----------------------------------------------------------------------- drift


@dataclass
class DriftEntry:
    url: str
    pinned_sha256: str
    upstream_sha256: str
    citers: list[str] = field(default_factory=list)


def refresh(project: Project, fetcher=None) -> list[DriftEntry]:
    """Re-fetch every pinned citation to a scratch buffer and compare hashes.

    Read-only: writes nothing, pins nothing, vendors nothing. Only reachable via
    `refdes check --refresh`, so a plain `build` or `check` never touches the
    network. A url that fails to fetch is reported as a warning, not drift --
    drift means the bytes changed, not that the network did.

    `fetcher` defaults to the module-level `fetch_bytes` at call time, the same
    way `fetch_all` does -- see its docstring.
    """
    fetcher = fetcher or fetch_bytes
    records = load_lockfile(project)
    citers: dict[str, list[str]] = defaultdict(list)
    for item, spec in collect(project):
        citers[spec.url].append(item.id)

    drift: list[DriftEntry] = []
    for target_url in sorted(citers):
        record = records.get(target_url)
        if record is None:
            continue  # unpinned -- already flagged by verify(), nothing to compare
        try:
            data = fetcher(target_url)
        except Exception as exc:  # noqa: BLE001
            project.warn(f"could not refresh {target_url}: {exc}")
            continue
        upstream_sha256 = hashlib.sha256(data).hexdigest()
        pinned_sha256 = str(record.get("sha256") or "")
        if upstream_sha256 != pinned_sha256:
            drift.append(
                DriftEntry(
                    url=target_url,
                    pinned_sha256=pinned_sha256,
                    upstream_sha256=upstream_sha256,
                    citers=sorted(set(citers[target_url])),
                )
            )
    return drift
