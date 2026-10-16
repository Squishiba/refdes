"""Run-7 findings F13, F14 and F16 (`in-prog-logs/user-sim-release-gate-run7.md`).

F13 (§2.17): `audit` printed `ok` for a citation whose record carries no page
count -- a plain-text document cited by `page:` reads exactly like a document
whose pages were counted and in range. `page_count_gaps` named only the
*recorded* count failure, so the row for a record with no count at all stayed
`ok`, and `audit`'s own legend ("what verification found") claimed a check that
never ran. The fix reports the no-count state honestly, with the reason the
record supports.

F14 (§2.9): the stamp/baseline-carry write refusals hardcoded the
`(read-only tree?)` marker. DIAG-WORD-008 (PR #230) made the same marker
conditional in the other destination refusals by passing the caught `OSError`
through `model.destination_refusal`; these two sites predate it and kept the
unconditional form, so a full disk answered "read-only tree?" and "make the
tree writable". The stamp refusal (and the revision engine's carried-baseline
refusal) now follow the cause.

F16 (§1.1): `ls --tag` matches a non-string `tags:` element's dict repr
(#235 left the item loading with a load error, and the filter's tag read
stringified it). The filter's tag read now yields only strings.
"""

from __future__ import annotations

import errno
import hashlib
import os

import yaml
from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import textio as textio_mod

SCHEMA = """\
site: {title: "Run7 nits", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
on_change: {default: invalidate}
units: {preferred: []}
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title:      { type: text, required: true, on_change: invalidate }
      datasheets: { type: citations, on_change: invalidate }
      tags:       { type: list, on_change: ignore }
"""


def _run(capsys, config, *args):
    code = cli_mod.main(["-c", config, *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _audit_row(out, citer="CMP-001"):
    lines = [line for line in out.splitlines() if f"cited by {citer}" in line]
    assert len(lines) == 1, out
    return " ".join(lines[0].split())


# ------------------------------------------------------------------ F13


CITED_TEXT = """\
---
id: CMP-001
type: component
title: One
datasheets:
  - path: docs/notes.txt
    page: "3"
---
Body.
"""


def _citation_project(root, md: str) -> str:
    config = write_project_config(root, SCHEMA)
    (root / "items").mkdir()
    (root / "items" / "one.md").write_text(md, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "notes.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    return str(config)


def test_audit_says_a_plain_texts_pages_are_unchecked(tmp_path, capsys):
    """The reported shape: a plain text file cited by page, fetched, audited.
    The row used to read `ok` because `page_count_gaps` only named recorded
    count failures, and a non-PDF record carries none -- it has no count
    because pages are never counted for these bytes. The row says so now."""
    config = _citation_project(tmp_path, CITED_TEXT)
    code, out, err = _run(capsys, config, "fetch")
    assert code == 0, err
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    assert _audit_row(out).startswith("pages unchecked"), out
    assert "it is not a PDF, so its pages are never counted" in out, out


def test_check_names_a_plain_texts_cited_page(tmp_path, capsys):
    """The finding's heading names both commands, so `check` gets the same
    fact from the same record: a document that is not a PDF has no count for
    any command to record, and the build must not publish a cited page number
    as verified. (The pre-fix silence was reasoned from "a plain fetch can
    still fill it" -- true for a PDF's bytes on the machine, false here,
    which is what the review round caught.)"""
    config = _citation_project(tmp_path, CITED_TEXT)
    _run(capsys, config, "fetch")
    code, out, err = _run(capsys, config, "check")
    assert code == 0, err
    assert "the page numbers cited for docs/notes.txt are not checked" in out + err, (
        out + err
    )
    assert "it is not a PDF, so its pages are never counted" in out + err, out + err


def _pin_local_pdf(root, path: str, page: str, **record) -> str:
    """One component citing `page: "3"` of a local PDF, the file on disk, and
    a lockfile record written by hand -- `fetch` never writes the PDF shapes
    these tests need (no count yet, count on record) for a local path."""
    config = write_project_config(root, SCHEMA)
    (root / "items").mkdir()
    (root / "items" / "one.md").write_text(
        "---\n"
        "id: CMP-001\n"
        "type: component\n"
        "title: One\n"
        "datasheets:\n"
        f"  - path: {path}\n"
        f'    page: "{page}"\n'
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )
    (root / "docs").mkdir()
    (root / "docs" / "manual.pdf").write_bytes(b"document bytes")
    data = {
        "sha256": hashlib.sha256(b"document bytes").hexdigest(),
        "fetched": "2026-01-01T00:00:00Z",
        "kept_copy": False,
        **record,
    }
    lock = root / ".refdes" / "citations.yaml"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        yaml.safe_dump({"citations": {path: data}}), encoding="utf-8"
    )
    return str(config)


def test_audit_names_the_plain_fetch_that_counts_a_pdf_with_no_count(tmp_path, capsys):
    config = _pin_local_pdf(tmp_path, "docs/manual.pdf", "3")
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    assert _audit_row(out).startswith("pages unchecked"), out
    assert "the lockfile records no page count for these bytes" in out, out
    assert "run 'refdes fetch --path docs/manual.pdf' to count them" in out, out


def test_audit_keeps_ok_for_a_counted_pdf(tmp_path, capsys):
    """The fix is about records with no count, not about being pessimistic:
    a trusted count on record keeps the row's `ok`, including when a cited
    page is out of range (that page is `check`'s warning to give, and the
    run-5 F1 promise is that the audit row stays a statement about the pin)."""
    sha = hashlib.sha256(b"document bytes").hexdigest()
    in_range = tmp_path / "in-range"
    in_range.mkdir()
    config = _pin_local_pdf(
        in_range, "docs/manual.pdf", "3", page_count=8, page_count_sha256=sha
    )
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    assert _audit_row(out).startswith("ok"), out
    assert "pages unchecked" not in out, out

    out_of_range = tmp_path / "out-of-range"
    out_of_range.mkdir()
    config99 = _pin_local_pdf(
        out_of_range, "docs/manual.pdf", "99", page_count=8, page_count_sha256=sha
    )
    code, out, err = _run(capsys, config99, "audit")
    assert code == 0, err
    assert _audit_row(out).startswith("ok"), out
    code, out, err = _run(capsys, config99, "check")
    assert "page 99" in out + err, out + err


def test_check_stays_silent_for_a_pdf_the_plain_fetch_will_count(tmp_path, capsys):
    """The asymmetry's remaining half, pinned: bytes on this machine with no
    count on record are the one state the command's own next fetch repairs,
    and `check` stays silent there (its documented rule: warn about the
    lockfile, not the citation) while `audit` names the state. The silence
    is scoped to this shape by the non-PDF test above -- a document whose
    count no fetch can write is named by both."""
    config = _pin_local_pdf(tmp_path, "docs/manual.pdf", "3")
    code, out, err = _run(capsys, config, "check")
    assert code == 0, err
    assert "not checked" not in out + err, out + err


def test_check_warns_for_a_page_past_a_zero_count(tmp_path, capsys):
    """A trusted `page_count: 0` (an empty PDF pypdf opened and found no
    pages in) is a count, not an absence: a cited page past it is the
    out-of-range warning `check` already owes, with `audit`'s row keeping
    its `ok` (the pinned-count promise). A provenance-matched zero reaching
    neither report -- `audit` silent, `check` publishing the page -- was the
    review round's finding; the load-refused negative (CITE-LOCK-012) was
    already impossible."""
    sha = hashlib.sha256(b"document bytes").hexdigest()
    zero = tmp_path / "zero"
    zero.mkdir()
    config = _pin_local_pdf(
        zero, "docs/manual.pdf", "3", page_count=0, page_count_sha256=sha
    )
    code, out, err = _run(capsys, config, "check")
    assert code == 0, err
    assert "page 3 is not in this document" in out + err, out + err
    code, out, err = _run(capsys, config, "audit")
    assert _audit_row(out).startswith("ok"), out


# ------------------------------------------------------------------ F14


def _stamp_project(root) -> str:
    config = write_project_config(root, SCHEMA)
    (root / "items").mkdir()
    (root / "items" / "one.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: One\n---\nBody.\n",
        encoding="utf-8",
    )
    return str(config)


def _refuse_baselines_like_a_full_disk(monkeypatch, names):
    """A full disk, injected: `lifecycle._save_baseline_file` writes through
    `textio.write_text`, so raising `OSError(ENOSPC)` there on a fully
    writable tree is the condition a full disk presents. A test cannot fill a
    real filesystem; the reporting of the injected cause is the fix under
    test."""
    real_write = textio_mod.write_text

    def boom(path, text):
        if os.path.basename(path) in names:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(path, text)

    monkeypatch.setattr(textio_mod, "write_text", boom)


def test_revision_reports_a_full_disk_as_a_full_disk(tmp_path, monkeypatch, capsys):
    config = _stamp_project(tmp_path)
    _refuse_baselines_like_a_full_disk(monkeypatch, {"rev-a.yaml"})
    code, out, err = _run(capsys, config, "revision", "rev-a")
    said = out + err
    assert code == 2, said
    assert "cannot write .refdes/baselines/rev-a.yaml (No space left on device)" in said, said
    assert "(read-only tree?)" not in said, said
    assert "Fix the reported failure and run it again" in said, said
    assert "Make the tree writable" not in said, said
    assert "was not stamped" in said, said
    assert not (tmp_path / ".refdes" / "baselines" / "rev-a.yaml").exists()


def test_revision_keeps_the_read_only_marker_for_a_read_only_refusal(
    tmp_path, monkeypatch, capsys
):
    """The marker the CI filters match stays byte-identical for a refusal
    with no errno to explain it -- the shape of the atomic writer's read-only
    guards (`PermissionError("file is read-only: ...")`)."""
    config = _stamp_project(tmp_path)
    real_write = textio_mod.write_text

    def boom(path, text):
        if os.path.basename(path) == "rev-a.yaml":
            raise PermissionError(f"file is read-only: {path}")
        return real_write(path, text)

    monkeypatch.setattr(textio_mod, "write_text", boom)
    code, out, err = _run(capsys, config, "revision", "rev-a")
    said = out + err
    assert code == 2, said
    assert "cannot write .refdes/baselines/rev-a.yaml (read-only tree?)" in said, said
    assert "Make the tree writable and run it again" in said, said
    assert "No space left on device" not in said, said


def test_standard_upgrade_reports_a_full_disk_on_the_carried_baseline(tmp_path, monkeypatch, capsys):
    """The engine's carried-baseline write, the other hardcoded copy of the
    marker: a v2 project with a stamped baseline, `standard upgrade --to 3`
    advancing it, and the disk full on the write."""
    config = str(
        write_project_config(
            tmp_path,
            "site: { title: T, out: _site }\n"
            "standard: { base: hardware, version: 2, presets: [] }\n",
        )
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "req.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ, status: active }\n"
        "items:\n"
        "  - id: REQ-001\n"
        "    title: Needs a verifying test\n"
        "    text: The unit shall operate from 9 V to 36 V.\n",
        encoding="utf-8",
    )
    code, out, err = _run(capsys, config, "revision", "rev-a")
    assert code == 0, out + err

    _refuse_baselines_like_a_full_disk(monkeypatch, {"rev-a.yaml"})
    code, out, err = _run(capsys, config, "standard", "upgrade", "--to", "3")
    said = out + err
    assert code == 1, said
    assert "refused:" in said, said
    assert "cannot write .refdes/baselines/rev-a.yaml (No space left on device)" in said, said
    assert "(read-only tree?)" not in said, said
    assert "Fix the reported failure and run it again" in said, said
    assert "rolled back." in said, said
    # The rename rolled back: the item is the text-field shape it started as.
    assert "text: The unit shall operate" in (items / "req.yaml").read_text(encoding="utf-8")


# ------------------------------------------------------------------ F16


MAPPING_TAGS = "---\nid: CMP-001\ntype: component\ntitle: One\ntags: [power, {name: not-a-string, verdict: x}]\n---\nBody.\n"


def _tagged_project(root, tags_yaml: str, schema: str = SCHEMA) -> str:
    config = write_project_config(root, schema)
    (root / "items").mkdir()
    (root / "items" / "one.md").write_text(tags_yaml, encoding="utf-8")
    return str(config)


def test_ls_tag_does_not_match_a_mapping_element(tmp_path, capsys):
    """#235 made the mapping element a load error, but the item loads, is
    listed, and the filter's tag read stringified it -- `--tag name` matched
    `{'name': ...}`. The filter reads strings, so the dict's repr is not
    searchable text."""
    config = _tagged_project(tmp_path, MAPPING_TAGS)
    code, out, err = _run(capsys, config, "ls")
    assert "CMP-001" in out, out  # the item loads and is listed (#235's shape)

    code, out, err = _run(capsys, config, "ls", "--tag", "not-a-string")
    assert "no items match" in out, out
    code, out, err = _run(capsys, config, "ls", "--tag", "name")
    assert "no items match" in out, out

    code, out, err = _run(capsys, config, "ls", "--tag", "power")
    assert "CMP-001" in out, out

    code, out, err = _run(capsys, config, "check")
    assert code == 1, out + err  # the load error is still reported
    assert "tags" in out + err, out + err


def test_ls_free_text_does_not_match_a_mapping_element(tmp_path, capsys):
    config = _tagged_project(tmp_path, MAPPING_TAGS)
    code, out, err = _run(capsys, config, "ls", "not-a-string")
    assert "no items match" in out, out
    code, out, err = _run(capsys, config, "ls", "power")
    assert "CMP-001" in out, out
