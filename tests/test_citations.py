"""citations -- and: structural validation, verify, items_json export, fetch, drift, cli, rendering.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import hashlib
import os

import pytest
import yaml
from conftest import write_project_config
from helpers import _build_and_render, _build_at

from refdes import build as build_mod
from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes import parse, render
from refdes.schema import load_project

# ------------------------------------------------------------------- citations

CITATION_SCHEMA = """\
site: {title: "Citation Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title:      { type: text, required: true, on_change: invalidate }
      datasheets: { type: citations, on_change: invalidate }
"""


CITATION_ITEM = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: Buck converter
    datasheets:
      - path: https://example.com/ds.pdf
        rev: C
        page: "14"
        part_number: TPS62913
        vendor: true
"""


@pytest.fixture
def citation_project(tmp_path):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(CITATION_ITEM, encoding="utf-8")
    return tmp_path


def _cite_build(root, **kw):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, **kw)
    return project


def _write_citation_lockfile(root, records):
    path = root / ".refdes" / "citations.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"citations": records}), encoding="utf-8")


def _write_vendor_blob(root, sha256, ext, data):
    path = root / ".refdes" / "vendor" / f"{sha256}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _fake_fetcher(data: bytes = b"%PDF-1.4 fake"):
    def fetcher(url):
        return data

    return fetcher


# --------------------------------------------------------- structural validation


def test_citations_field_must_be_a_list(tmp_path):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n    datasheets: not-a-list\n",
        encoding="utf-8",
    )
    project = _cite_build(tmp_path)
    assert any("must be a list of citation entries" in d.message for d in project.errors)


def test_citation_entry_without_path_is_an_error(tmp_path):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n    datasheets:\n      - rev: C\n",
        encoding="utf-8",
    )
    project = _cite_build(tmp_path)
    assert any("each citation needs a 'path'" in d.message for d in project.errors)


def test_stale_url_key_gets_the_rename_error(tmp_path):
    """Finding 25 Part 2, decision D1: `url:` is a hard break, but never an
    anonymous unknown-key failure -- the diagnostic names the rename and the
    automatic way to apply it, for every project regardless of standard pin."""
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n    datasheets:\n"
        "      - url: https://example.com/ds.pdf\n",
        encoding="utf-8",
    )
    project = _cite_build(tmp_path)
    assert any(
        "url: was renamed to path:" in d.message and "standard upgrade" in d.message
        for d in project.errors
    )


def test_vendor_on_local_path_is_an_error(tmp_path):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n    datasheets:\n"
        "      - path: docs/local.pdf\n        vendor: true\n",
        encoding="utf-8",
    )
    project = _cite_build(tmp_path)
    assert any(
        "vendor: on local path" in d.message and "already local" in d.message
        for d in project.errors
    )


# ---------------------------------------------------------------------- verify


def test_unpinned_citation_is_info_by_default(citation_project):
    """Routine until `refdes fetch` runs (issue #3, finding 8) -- default-hidden
    info, not a warning that competes with actionable diagnostics."""
    project = _cite_build(citation_project)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "unpinned"
    assert any("has no fetched record" in d.message for d in project.infos)
    assert not any("has no fetched record" in d.message for d in project.warnings)
    assert not any("has no fetched record" in d.message for d in project.errors)


def test_require_citations_promotes_unpinned_to_error(citation_project):
    project = _cite_build(citation_project, require_citations=True)
    assert any("has no fetched record" in d.message for d in project.errors)


def test_hash_only_citation_is_ok_with_no_local_file_needed(citation_project):
    (citation_project / "items" / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n"
        "    datasheets:\n      - path: https://example.com/ds.pdf\n        vendor: false\n",
        encoding="utf-8",
    )
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "abc123", "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = _cite_build(citation_project)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "ok"
    assert status.local_path == ""
    assert not project.warnings and not project.errors


def _enable_publish_datasheets(root):
    # refdes-project.yaml is the settings file itself now, so this appends the
    # one setting rather than replacing the file the fixture just wrote.
    with open(root / "refdes-project.yaml", "a", encoding="utf-8") as fh:
        fh.write("publish_datasheets: true\n")


def test_vendored_citation_ok_when_blob_matches(citation_project):
    """publish_datasheets defaults off, so a vendored citation resolves 'ok' but
    is not exposed as a local copy -- the rendered link stays upstream-only."""
    data = b"%PDF-1.4 real bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    project = _cite_build(citation_project)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "ok"
    assert status.local_path == ""
    assert not project.errors


def test_vendored_citation_published_when_publish_datasheets_is_on(citation_project):
    data = b"%PDF-1.4 real bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    _enable_publish_datasheets(citation_project)
    project = _cite_build(citation_project)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "ok"
    assert status.local_path == f"datasheets/{sha}.pdf"  # flattened, not .refdes/vendor/...
    assert not project.errors


def test_cache_missing_and_hash_mismatch_are_unaffected_by_publish_datasheets(citation_project):
    """Local-cache integrity checks are unconditional -- publishing is a separate
    concern from whether the vendored copy is trustworthy."""
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "deadbeef", "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _enable_publish_datasheets(citation_project)
    project = _cite_build(citation_project)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "cache_missing"
    assert status.local_path == ""


def test_vendored_citation_cache_missing_when_blob_absent(citation_project):
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "deadbeef", "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    project = _cite_build(citation_project)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "cache_missing"
    assert any("is missing at" in d.message for d in project.warnings)


def test_vendored_citation_hash_mismatch_is_always_an_error(citation_project):
    """Never soft-failed: a corrupted local cache is an error even without --require-citations."""
    data = b"%PDF-1.4 real bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", b"tampered bytes")
    project = _cite_build(citation_project)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "hash_mismatch"
    assert any("tampered or corrupt" in d.message for d in project.errors)


# ------------------------------------------------------------- items_json export


def _citation_entry(payload, item_id="CMP-001"):
    return next(i for i in payload["items"] if i["id"] == item_id)


def test_items_json_citations_unpinned(citation_project):
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    status = _citation_entry(payload)["citations"]["datasheets"][0]
    assert status["state"] == "unpinned"
    assert status["pinned"] is False
    assert status["vendored"] is False
    assert status["sha256"] == ""
    assert status["fetched"] == ""
    assert status["local_path"] == ""
    assert "has no fetched record" in status["detail"]
    # authored intent stays in `fields`, untouched by resolution
    assert _citation_entry(payload)["fields"]["datasheets"][0] == {
        "path": "https://example.com/ds.pdf",
        "rev": "C",
        "page": "14",
        "part_number": "TPS62913",
        "vendor": True,
    }


def test_items_json_citations_hash_only_pinned_not_vendored(citation_project):
    (citation_project / "items" / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n"
        "    datasheets:\n      - path: https://example.com/ds.pdf\n        vendor: false\n",
        encoding="utf-8",
    )
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "abc123", "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    status = _citation_entry(payload)["citations"]["datasheets"][0]
    assert status["state"] == "ok"
    assert status["pinned"] is True
    assert status["vendored"] is False
    assert status["sha256"] == "abc123"
    assert status["fetched"] == "2026-01-01T00:00:00Z"
    assert status["local_path"] == ""


def test_items_json_citations_vendored(citation_project):
    data = b"%PDF-1.4 real bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    status = _citation_entry(payload)["citations"]["datasheets"][0]
    assert status["state"] == "ok"
    assert status["pinned"] is True
    assert status["vendored"] is True
    assert status["sha256"] == sha
    assert status["local_path"] == ""  # publish_datasheets defaults off


def test_items_json_citations_cache_missing(citation_project):
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "deadbeef", "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    status = _citation_entry(payload)["citations"]["datasheets"][0]
    assert status["state"] == "cache_missing"
    assert status["pinned"] is True
    assert status["vendored"] is True
    assert status["sha256"] == "deadbeef"
    assert status["local_path"] == ""


def test_items_json_citations_empty_for_items_without_citation_fields(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
    )
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    payload = render.items_json(project)
    assert payload["items"][0]["citations"] == {}


def test_items_json_types_expose_citations_field_type(citation_project):
    """The field-type/schema section is how a consumer discovers `datasheets`
    is a `citations` field in the first place -- pre-existing, unrelated to
    citation resolution, but this is the mechanism `citations` above pairs with.
    """
    project = _cite_build(citation_project)
    payload = render.items_json(project)
    assert payload["types"]["component"]["fields"]["datasheets"]["type"] == "citations"


INCONSISTENT_VENDOR_ITEMS = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: A
    datasheets:
      - path: https://example.com/ds.pdf
        vendor: true
  - id: CMP-002
    title: B
    datasheets:
      - path: https://example.com/ds.pdf
        vendor: false
"""


def test_inconsistent_vendor_flags_across_citers_warns(tmp_path):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(INCONSISTENT_VENDOR_ITEMS, encoding="utf-8")
    project = _cite_build(tmp_path)
    assert any("inconsistent vendor:" in d.message for d in project.warnings)


def test_content_hash_unaffected_by_lockfile_changes(citation_project):
    """Re-fetching a datasheet must never retroactively flag an item as edited."""
    project1 = _cite_build(citation_project)
    hash1 = project1.item_by_id("CMP-001").content_hash

    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "abc", "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project2 = _cite_build(citation_project)
    hash2 = project2.item_by_id("CMP-001").content_hash
    assert hash1 == hash2


# ----------------------------------------------------------------------- fetch


def test_fetch_all_pins_every_cited_url(citation_project):
    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    results = citations_mod.fetch_all(project, fetcher=_fake_fetcher())
    assert len(results) == 1
    assert results[0].path == "https://example.com/ds.pdf"
    assert results[0].vendored is True  # the one citer declares vendor: true
    lockfile = citations_mod.load_lockfile(project)
    assert "https://example.com/ds.pdf" in lockfile
    blob = citations_mod.vendor_path(project, results[0].sha256, results[0].path)
    assert os.path.isfile(blob)


TWO_URL_ITEMS = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: A
    datasheets: [{path: "https://example.com/a.pdf"}]
  - id: CMP-002
    title: B
    datasheets: [{path: "https://example.com/b.pdf"}]
"""


@pytest.fixture
def two_url_project(tmp_path):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(TWO_URL_ITEMS, encoding="utf-8")
    return tmp_path


def test_fetch_scoped_to_item(two_url_project):
    project = load_project(config_path=str(two_url_project / "refdes-project.yaml"))
    parse.load_items(project)
    results = citations_mod.fetch_all(project, item_id="CMP-001", fetcher=_fake_fetcher())
    assert [r.path for r in results] == ["https://example.com/a.pdf"]


def test_fetch_scoped_to_url(two_url_project):
    project = load_project(config_path=str(two_url_project / "refdes-project.yaml"))
    parse.load_items(project)
    results = citations_mod.fetch_all(
        project, path="https://example.com/b.pdf", fetcher=_fake_fetcher()
    )
    assert [r.path for r in results] == ["https://example.com/b.pdf"]


def test_fetch_unknown_item_raises(citation_project):
    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    with pytest.raises(citations_mod.CitationError, match="CMP-999"):
        citations_mod.fetch_all(project, item_id="CMP-999", fetcher=_fake_fetcher())


def test_fetch_url_not_cited_raises(citation_project):
    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    with pytest.raises(citations_mod.CitationError, match="cites"):
        citations_mod.fetch_all(
            project, path="https://example.com/nope.pdf", fetcher=_fake_fetcher()
        )


def test_fetch_skips_already_pinned_unless_update(citation_project):
    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)

    first = citations_mod.fetch_all(project, fetcher=_fake_fetcher(b"version one"))
    assert first[0].skipped is False

    second = citations_mod.fetch_all(project, fetcher=_fake_fetcher(b"version two"))
    assert second[0].skipped is True
    assert second[0].sha256 == first[0].sha256

    third = citations_mod.fetch_all(project, update=True, fetcher=_fake_fetcher(b"version two"))
    assert third[0].skipped is False
    assert third[0].sha256 != first[0].sha256


def test_fetch_records_error_without_raising(citation_project):
    def bad_fetcher(url):
        raise OSError("network unreachable")

    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    results = citations_mod.fetch_all(project, fetcher=bad_fetcher)
    assert results[0].error == "network unreachable"
    assert citations_mod.load_lockfile(project) == {}  # nothing written on failure


# ----------------------------------------------------------------------- drift


def test_refresh_detects_drift(citation_project):
    sha_old = hashlib.sha256(b"old bytes").hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha_old, "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    drift = citations_mod.refresh(project, fetcher=_fake_fetcher(b"new bytes"))
    assert len(drift) == 1
    assert drift[0].path == "https://example.com/ds.pdf"
    assert drift[0].pinned_sha256 == sha_old
    assert drift[0].citers == ["CMP-001"]


def test_refresh_no_drift_when_hash_matches(citation_project):
    data = b"same bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    assert citations_mod.refresh(project, fetcher=_fake_fetcher(data)) == []


def test_refresh_skips_unpinned(citation_project):
    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    assert citations_mod.refresh(project, fetcher=_fake_fetcher()) == []


def test_refresh_writes_nothing(citation_project):
    sha_old = hashlib.sha256(b"old bytes").hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha_old, "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    citations_mod.refresh(project, fetcher=_fake_fetcher(b"new bytes"))
    assert citations_mod.load_lockfile(project)["https://example.com/ds.pdf"]["sha256"] == sha_old


def test_refresh_warns_on_fetch_failure_not_drift(citation_project):
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": "abc", "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )

    def bad_fetcher(url):
        raise OSError("timeout")

    project = load_project(config_path=str(citation_project / "refdes-project.yaml"))
    parse.load_items(project)
    drift = citations_mod.refresh(project, fetcher=bad_fetcher)
    assert drift == []
    assert any("could not refresh" in d.message for d in project.warnings)


# ------------------------------------------------------------------------- cli


def test_cli_fetch_pins_via_monkeypatched_network(citation_project, monkeypatch, capsys):
    monkeypatch.setattr(citations_mod, "fetch_bytes", lambda url, timeout=30.0: b"%PDF-1.4 x")
    code = cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "fetch"])
    assert code == 0
    out = capsys.readouterr().out
    assert "fetched" in out
    assert "1 citation(s) processed, 0 failed" in out


def test_cli_fetch_unknown_item_returns_nonzero(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "fetch", "--item", "CMP-999"])
    assert code == 1
    assert "CMP-999" in capsys.readouterr().err


def test_cli_check_refresh_detects_drift(citation_project, monkeypatch, capsys):
    sha_old = hashlib.sha256(b"old").hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha_old, "fetched": "2026-01-01T00:00:00Z", "vendored": False}},
    )
    monkeypatch.setattr(citations_mod, "fetch_bytes", lambda url, timeout=30.0: b"new bytes")
    code = cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "check", "--refresh"])
    assert code == 1
    assert "drifted" in capsys.readouterr().out


def test_cli_check_without_refresh_never_touches_the_network(citation_project, monkeypatch):
    def boom(url, timeout=30.0):
        raise AssertionError("check must not touch the network without --refresh")

    monkeypatch.setattr(citations_mod, "fetch_bytes", boom)
    # An unpinned citation is only a warning, so plain `check` still exits 0.
    assert cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "check"]) == 0


def test_cli_build_require_citations_promotes_to_error(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "build", "--require-citations"])
    assert code == 1
    assert "has no fetched record" in capsys.readouterr().err


def test_cli_build_without_require_citations_still_succeeds(citation_project):
    assert cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "build"]) == 0


def test_cli_check_hides_info_diagnostics_by_default(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "check"])
    assert code == 0
    out = capsys.readouterr().out
    assert "has no fetched record" not in out
    assert ", 0 info" not in out  # summary line unchanged unless --verbose


def test_cli_check_verbose_shows_info_diagnostics(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "check", "--verbose"])
    assert code == 0
    out = capsys.readouterr().out
    assert "INFO" in out
    assert "has no fetched record" in out
    assert ", 1 info" in out


def test_cli_audit_lists_citations(citation_project, capsys):
    code = cli_mod.main(["-c", str(citation_project / "refdes-project.yaml"), "audit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Citations:" in out
    assert "https://example.com/ds.pdf" in out
    assert "CMP-001" in out


# -------------------------------------------------------------------- rendering


def test_references_page_lists_citations_grouped_by_url(citation_project):
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "references.html"), encoding="utf-8").read()
    assert "https://example.com/ds.pdf" in html
    assert 'data-ref="CMP-001"' in html
    assert "pill-warn" in html  # unpinned


def test_item_page_excludes_citations_field_from_generic_table(citation_project):
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert "<h2>Citations</h2>" in html
    assert "<th>datasheets</th>" not in html


def test_reserved_name_guard_covers_references(citation_project):
    pages = citation_project / "pages"
    pages.mkdir()
    (pages / "references.md").write_text("# Nope\n", encoding="utf-8")
    project = _cite_build(citation_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)


def test_vendored_citation_pdf_is_not_published_by_default(citation_project):
    """publish_datasheets defaults off: nothing is copied into _site/, and the
    rendered citation links upstream only -- no 'local copy' link."""
    data = b"%PDF-1.4 vendored bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    project = _cite_build(citation_project)
    out = render.render_site(project)
    assert not os.path.isdir(os.path.join(out, "assets", "datasheets"))
    assert not os.path.isdir(os.path.join(out, "assets", ".refdes"))
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert "https://example.com/ds.pdf" in html
    assert "local copy" not in html


def test_vendored_citation_pdf_is_copied_into_the_site_when_published(citation_project):
    data = b"%PDF-1.4 vendored bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    _enable_publish_datasheets(citation_project)
    project = _cite_build(citation_project)
    out = render.render_site(project)
    copied = os.path.join(out, "assets", "datasheets", f"{sha}.pdf")
    assert os.path.isfile(copied)
    assert open(copied, "rb").read() == data
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert f"assets/datasheets/{sha}.pdf" in html
    assert "local copy" in html


def test_citation_page_deep_links_upstream_and_local_copy_hrefs(citation_project):
    """A citation WITH `page:` puts '#page=N' on the href of both links — the
    upstream URL and the published local copy — while the visible link text
    stays the bare URL. Asserted on the href attribute itself, not a loose
    substring: the page number is already printed in a table cell, so a naive
    `"page=14" in html` check would pass even if the href were untouched."""
    data = b"%PDF-1.4 vendored bytes"
    sha = hashlib.sha256(data).hexdigest()
    _write_citation_lockfile(
        citation_project,
        {"https://example.com/ds.pdf": {"sha256": sha, "fetched": "2026-01-01T00:00:00Z", "vendored": True}},
    )
    _write_vendor_blob(citation_project, sha, ".pdf", data)
    _enable_publish_datasheets(citation_project)
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert 'href="https://example.com/ds.pdf#page=14" target="_blank" rel="noopener">https://example.com/ds.pdf</a>' in html
    assert f'<a href="assets/datasheets/{sha}.pdf#page=14">local copy</a>' in html


def test_citation_without_page_keeps_bare_href(citation_project):
    """A citation WITHOUT `page:` renders the href bare — no '#page=' fragment
    anywhere on the item page."""
    (citation_project / "items" / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n"
        "    datasheets:\n      - path: https://example.com/ds.pdf\n",
        encoding="utf-8",
    )
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert 'href="https://example.com/ds.pdf"' in html
    assert "#page=" not in html


def test_citation_page_value_is_html_escaped(citation_project):
    """Author-controlled citation `page:` must be escaped on the rendered item
    page: `page: 14" onmouseover="alert(1)` would otherwise break out of the
    href attribute and inject a handler. Regression for autoescaping being
    silently disabled — `select_autoescape(["html"])` matches on the template
    name's suffix, and every template is named *.html.j2, so it returned False
    for all of them."""
    (citation_project / "items" / "cmp.yaml").write_text(
        "defaults: {type: component}\n"
        "items:\n  - id: CMP-001\n    title: t\n"
        "    datasheets:\n      - path: https://example.com/ds.pdf\n"
        "        page: '14\" onmouseover=\"alert(1)'\n",
        encoding="utf-8",
    )
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    # The unescaped attribute would be `onmouseover="alert(1)` breaking out of
    # the href; that must be gone...
    assert 'onmouseover="' not in html
    # ...and the escaped form (quote rendered as the `&#34;` entity) present
    # instead, both in the #page= href fragment and the page table cell.
    assert "onmouseover=&#34;" in html


def test_nav_shows_references_link_only_when_citations_exist(citation_project):
    project = _cite_build(citation_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert 'href="references.html"' in html


def test_no_references_link_without_any_citations(coverage_project):
    out = _build_and_render(coverage_project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert 'href="references.html"' not in html
    assert os.path.isfile(os.path.join(out, "references.html"))


BOARD_CITATION_SCHEMA = """\
site:
  title: "Board Citation Test"
  out: _site
boards:
  board-a: { label: "Board A" }
  board-b: { label: "Board B" }
types:
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true }
      datasheets: { type: citations }
"""


@pytest.fixture
def board_citation_project(tmp_path):
    write_project_config(tmp_path, BOARD_CITATION_SCHEMA)
    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "c.yaml").write_text(
        "defaults: {type: component}\n"
        'items:\n  - id: CMP-A-001\n    title: A\n    datasheets: [{path: "https://example.com/a.pdf"}]\n',
        encoding="utf-8",
    )
    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "c.yaml").write_text(
        "defaults: {type: component}\n"
        'items:\n  - id: CMP-B-001\n    title: B\n    datasheets: [{path: "https://example.com/b.pdf"}]\n',
        encoding="utf-8",
    )
    return tmp_path


def test_per_board_references_are_scoped(board_citation_project):
    project = _cite_build(board_citation_project)
    out = render.render_site(project)
    ref_a = open(os.path.join(out, "references-board-a.html"), encoding="utf-8").read()
    ref_b = open(os.path.join(out, "references-board-b.html"), encoding="utf-8").read()
    assert "example.com/a.pdf" in ref_a and "example.com/b.pdf" not in ref_a
    assert "example.com/b.pdf" in ref_b and "example.com/a.pdf" not in ref_b

    ref_global = open(os.path.join(out, "references.html"), encoding="utf-8").read()
    assert "example.com/a.pdf" in ref_global and "example.com/b.pdf" in ref_global


# ------------------------------------------------------- local path citations

LOCAL_ITEM = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: Schematic
    datasheets:
      - path: docs/sch.pdf
        rev: "2"
"""

LOCAL_ITEM_TWO_CITERS = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: Schematic
    datasheets:
      - path: docs/sch.pdf
  - id: CMP-002
    title: Schematic too
    datasheets:
      - path: docs/sch.pdf
"""


def _local_project(tmp_path, item_text=LOCAL_ITEM, doc_data=b"%PDF local"):
    write_project_config(tmp_path, CITATION_SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "cmp.yaml").write_text(item_text, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "sch.pdf").write_bytes(doc_data)
    return tmp_path


def _load_only(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    return project


def test_classify_dispatches_on_scheme(tmp_path):
    root = str(tmp_path)
    assert citations_mod.classify(root, "https://example.com/ds.pdf") == (
        "remote",
        "https://example.com/ds.pdf",
    )
    assert citations_mod.classify(root, "HTTP://example.com/ds.pdf")[0] == "remote"
    assert citations_mod.classify(root, "docs/sch.pdf") == ("local", "docs/sch.pdf")
    assert citations_mod.classify(root, "./docs//sub/../sch.pdf") == (
        "local",
        "docs/sch.pdf",
    )

    for bad in (
        "file:/tmp/x.pdf",
        "ftp://example.com/x",
        "C:\\x\\a.pdf",
        "c:/x/a.pdf",
        "docs\\sch.pdf",
        "/abs/sch.pdf",
        "\\\\host\\share\\x",
        "../outside.pdf",
        "docs/../../outside.pdf",
        "..",
        ".",
        "",
        "   ",
    ):
        with pytest.raises(citations_mod.CitationError):
            citations_mod.classify(root, bad)


def test_classify_refuses_symlink_escape(tmp_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"x")
    proj = tmp_path / "proj"
    proj.mkdir()
    link = proj / "sneaky.pdf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this filesystem")
    with pytest.raises(citations_mod.CitationError):
        citations_mod.classify(str(proj), "sneaky.pdf")


def test_fetch_local_pins_without_network(tmp_path):
    _local_project(tmp_path)
    project = _load_only(tmp_path)

    def no_network(url):
        raise AssertionError("a local citation must not touch the network")

    results = citations_mod.fetch_all(project, fetcher=no_network)
    assert len(results) == 1 and not results[0].error
    sha = hashlib.sha256(b"%PDF local").hexdigest()
    assert results[0].path == "docs/sch.pdf" and results[0].sha256 == sha

    project2 = _cite_build(tmp_path)
    status = project2.item_by_id("CMP-001").citations[0]
    assert status.state == "ok" and status.remote is False
    assert status.local_path == f"citations/{sha}.pdf"
    assert not project2.warnings and not project2.errors


def test_local_pinned_copy_is_published_even_with_publish_datasheets_off(tmp_path):
    """The publish_datasheets gate exists for copyrighted third-party PDFs.
    A file the project itself wrote has no such problem -- its pinned copy is
    published unconditionally, because it is the only URL the site can carry."""
    _local_project(tmp_path)
    project = _load_only(tmp_path)
    citations_mod.fetch_all(project, fetcher=lambda u: b"unused")
    project = _cite_build(tmp_path)
    out = render.render_site(project)
    sha = hashlib.sha256(b"%PDF local").hexdigest()
    published = os.path.join(out, "assets", "citations", f"{sha}.pdf")
    assert os.path.isfile(published)
    with open(published, "rb") as fh:
        assert fh.read() == b"%PDF local"


def test_local_file_changed_since_pin_warns_and_names_citers(tmp_path):
    _local_project(tmp_path, item_text=LOCAL_ITEM_TWO_CITERS)
    project = _load_only(tmp_path)
    citations_mod.fetch_all(project, fetcher=lambda u: b"unused")
    (tmp_path / "docs" / "sch.pdf").write_bytes(b"%PDF edited")

    project = _cite_build(tmp_path)
    states = [c.state for c in project.item_by_id("CMP-001").citations]
    assert states == ["hash_mismatch"]
    notes = [d.message for d in project.warnings if "changed since it was pinned" in d.message]
    assert len(notes) == 1  # one diagnostic per file, not per citer
    assert "CMP-001" in notes[0] and "CMP-002" in notes[0]
    assert "refdes fetch --update" in notes[0]
    assert not project.errors


def test_local_file_changed_since_pin_errors_under_require(tmp_path):
    _local_project(tmp_path)
    project = _load_only(tmp_path)
    citations_mod.fetch_all(project, fetcher=lambda u: b"unused")
    (tmp_path / "docs" / "sch.pdf").write_bytes(b"%PDF edited")
    project = _cite_build(tmp_path, require_citations=True)
    assert any("changed since it was pinned" in d.message for d in project.errors)


def test_local_file_missing_is_error(tmp_path):
    _local_project(tmp_path)
    (tmp_path / "docs" / "sch.pdf").unlink()
    project = _cite_build(tmp_path)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "missing"
    assert any("does not exist" in d.message for d in project.errors)


def test_local_unpinned_is_info_then_error_under_require(tmp_path):
    _local_project(tmp_path)
    project = _cite_build(tmp_path)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "unpinned"
    assert any("has no fetched record" in d.message for d in project.infos)
    assert not project.errors
    project = _cite_build(tmp_path, require_citations=True)
    assert any("has no fetched record" in d.message for d in project.errors)


def test_fetch_all_refuses_vendor_on_local(tmp_path):
    _local_project(
        tmp_path,
        item_text=LOCAL_ITEM.replace('rev: "2"', "rev: \"2\"\n        vendor: true"),
    )
    project = _load_only(tmp_path)
    with pytest.raises(citations_mod.CitationError, match="already local"):
        citations_mod.fetch_all(project, fetcher=lambda u: b"unused")


def test_refresh_skips_local_paths(tmp_path):
    _local_project(tmp_path)
    project = _load_only(tmp_path)
    citations_mod.fetch_all(project, fetcher=lambda u: b"unused")

    def no_network(url):
        raise AssertionError("local citations are already compared every build")

    assert citations_mod.refresh(project, fetcher=no_network) == []


def test_local_citation_renders_link_to_pinned_copy(tmp_path):
    _local_project(tmp_path)
    project = _load_only(tmp_path)
    citations_mod.fetch_all(project, fetcher=lambda u: b"unused")
    project = _cite_build(tmp_path)
    out = render.render_site(project)
    sha = hashlib.sha256(b"%PDF local").hexdigest()
    with open(os.path.join(out, "cmp-001.html"), encoding="utf-8") as fh:
        item_html = fh.read()
    with open(os.path.join(out, "references.html"), encoding="utf-8") as fh:
        ref_html = fh.read()
    assert f"assets/citations/{sha}.pdf" in item_html
    assert f"assets/citations/{sha}.pdf" in ref_html
    assert "docs/sch.pdf" in item_html and "docs/sch.pdf" in ref_html


def test_case_mismatch_between_path_and_disk_warns(tmp_path):
    _local_project(tmp_path)  # docs/sch.pdf on disk
    (tmp_path / "items" / "cmp.yaml").write_text(
        LOCAL_ITEM.replace("docs/sch.pdf", "docs/SCH.pdf"), encoding="utf-8"
    )
    if not os.path.exists(tmp_path / "docs" / "SCH.pdf"):
        pytest.skip("case-sensitive filesystem: the path is simply missing there")
    project = _cite_build(tmp_path)
    assert any("differs in case" in d.message for d in project.warnings)


REFUSED_PATH_CASES = [
    ("../outside.pdf", "escapes the project root"),
    ("C:/x/main.pdf", "Windows drive letter"),
    ("docs\\sch.pdf", "backslash"),
]


@pytest.mark.parametrize("command", ["check", "build"])
@pytest.mark.parametrize("bad_path,reason", REFUSED_PATH_CASES)
def test_cli_refused_citation_path_reports_error_not_traceback(
    tmp_path, capsys, command, bad_path, reason
):
    _local_project(tmp_path, item_text=LOCAL_ITEM.replace("docs/sch.pdf", f"'{bad_path}'"))
    code = cli_mod.main(["-c", str(tmp_path / "refdes-project.yaml"), command])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert code != 0
    assert "Traceback" not in combined
    assert "[CMP-001]" in combined
    assert reason in combined


def test_cli_refused_path_does_not_stop_the_valid_citation(tmp_path, capsys):
    _local_project(tmp_path)  # CMP-001 cites docs/sch.pdf, valid
    (tmp_path / "items" / "bad.yaml").write_text(
        LOCAL_ITEM.replace("CMP-001", "CMP-002").replace(
            "docs/sch.pdf", "../outside.pdf"
        ),
        encoding="utf-8",
    )
    code = cli_mod.main(["-c", str(tmp_path / "refdes-project.yaml"), "fetch"])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert code != 0
    assert "Traceback" not in combined
    assert "escapes the project root" in combined
    records = citations_mod.load_lockfile(_load_only(tmp_path))
    assert "docs/sch.pdf" in records  # the valid one still pinned
    assert "../outside.pdf" not in records


def test_refresh_skips_refused_paths_without_raising(tmp_path):
    _local_project(
        tmp_path, item_text=LOCAL_ITEM.replace("docs/sch.pdf", "../outside.pdf")
    )
    project = _load_only(tmp_path)
    assert citations_mod.refresh(project, fetcher=lambda u: b"") == []


def test_drive_letter_refusal_message_punctuation(tmp_path):
    with pytest.raises(citations_mod.CitationError) as ei:
        citations_mod.classify(str(tmp_path), "C:/x/main.pdf")
    assert (
        "without a scheme; this looks like a Windows drive letter, not a scheme"
        in str(ei.value)
    )
