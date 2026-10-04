"""Run-5 release-gate friction findings F1, F2, F6 and F8.

Each test here fails on `main` as of 6251ab5 and pins the fix. The findings are
written up in `in-prog-logs/user-sim-release-gate-run5.md` §6; the one-line
version of each:

  F1  `audit` printed `ok  hash-only` for a pin whose page numbers were never
      checked, because the lockfile's `page_count_error:` is not mentioned
      anywhere in the report. `#147` exists because "audit claiming it checked"
      was the problem; this is the same claim one level up.
  F2  pypdf's own logger put a bare `EOF marker not found` on stderr, with no
      file, no path and no remedy, immediately above refdes's own warning about
      the same failure. It reads as the tool crashing and then recovering.
  F6  `check --refresh --allow-unreachable` said the same thing twice for one
      unreachable citation: once naming the url, once as a summary.
  F8  one condition -- a key no live item declares -- was reported with three
      wordings, and two of them dropped the `refdes keys restore` command the
      third spelled out.
"""

from __future__ import annotations

import hashlib
import logging
import re

import pytest
import yaml
from conftest import write_project_config

from refdes import build as build_mod
from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes import keys, parse
from refdes.schema import load_project

SCHEMA = """\
site: {title: "Run5 friction", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  refines: { inverse: refined_by, label: "Refines" }
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title:      { type: text, required: true, on_change: invalidate }
      datasheets: { type: citations, on_change: invalidate }
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links:
      refines: [requirement]
    body: { on_change: invalidate }
"""

DEAD = "http://127.0.0.1:1/bad.pdf"
LIVE = "http://127.0.0.1:1/good.pdf"
NOT_A_PDF = b"%PDF-1.4 not really a pdf at all, sorry\n"
PAGE_COUNT_ERROR = (
    "counting a document's pages failed: pypdf could not read the PDF: "
    "Stream has ended unexpectedly"
)


def _citation_project(root, *urls: str) -> str:
    """One component per url, each citing `page: "99"` of it."""
    write_project_config(root, SCHEMA)
    (root / "items").mkdir()
    rows = "".join(
        f"  - id: CMP-{i:03d}\n    title: Part {i}\n    datasheets:\n"
        f"      - path: {url}\n        rev: C\n        page: \"99\"\n"
        for i, url in enumerate(urls, start=1)
    )
    (root / "items" / "cmp.yaml").write_text(
        f"defaults:\n  type: component\nitems:\n{rows}", encoding="utf-8"
    )
    return str(root / "refdes-project.yaml")


def _pin(root, urls, **extra) -> None:
    """One hash-only record per url. `extra` is what the fetch could not
    decide -- `page_count`, or the reason there is no page count."""
    path = root / ".refdes" / "citations.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "citations": {
                    url: {
                        "sha256": hashlib.sha256(url.encode()).hexdigest(),
                        "fetched": "2026-01-01T00:00:00Z",
                        "kept_copy": False,
                        **extra,
                    }
                    for url in urls
                }
            }
        ),
        encoding="utf-8",
    )


def _run(capsys, config, *args):
    code = cli_mod.main(["-c", config, *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _said_unreachable(lines):
    """The lines that say a pinned citation could not be re-fetched, in either
    of the two shapes the refresh report uses."""
    return [
        line
        for line in lines
        if "could not refresh" in line or "could not be refreshed" in line
    ]


def _audit_row(out):
    """The audit report's citation row for CMP-001, column-aligned in the real
    output and field-split here so the test is about the words."""
    lines = [line for line in out.splitlines() if "cited by CMP-001" in line]
    assert len(lines) == 1, out
    return " ".join(lines[0].split())


# ---------------------------------------------------------------- F1 -- audit


def test_audit_does_not_call_an_uncheckable_pin_ok(tmp_path, capsys):
    """The lockfile says these bytes have no countable pages, so no cited
    `page:` was ever compared to anything. `audit` used to print `ok`."""
    config = _citation_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD], page_count_error=PAGE_COUNT_ERROR)
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    row = _audit_row(out)
    assert not row.startswith("ok "), row
    assert row.startswith("pages unchecked "), row
    # and the report says why, in the words the lockfile already holds
    assert PAGE_COUNT_ERROR in out, out


def test_audit_still_calls_a_counted_pin_ok(tmp_path, capsys):
    """The fix is about the ambiguous pin, not about being generically gloomier:
    a document whose pages WERE counted keeps its `ok`."""
    config = _citation_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD], page_count=8)
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    assert _audit_row(out).split()[0] == "ok", out


# ------------------------------------------------------------------ F2 -- pypdf


def test_refdes_reads_the_pdf_so_refdes_owns_the_report(capsys, caplog):
    """pypdf logs `EOF marker not found` to its own logger, which reaches
    stderr through logging's last-resort handler: a bare line with no file, no
    path and no remedy, right above the refdes warning about the same bytes.
    Nothing may reach the terminal from a read refdes is performing."""
    with caplog.at_level(logging.WARNING), pytest.raises(
        citations_mod.SectionError
    ) as caught:
        citations_mod.page_count(NOT_A_PDF)
    captured = capsys.readouterr()
    assert captured.err == "", captured.err
    assert captured.out == "", captured.out
    # ...and nothing escapes to the application's logging either, which is how
    # the bare line got printed in the first place: a library logger with no
    # handler anywhere above it is printed by Python's last-resort handler.
    assert [r.name for r in caplog.records if r.name.startswith("pypdf")] == []
    # nothing is lost: pypdf's own words survive, inside the message
    assert "EOF marker not found" in str(caught.value), caught.value
    assert "Stream has ended unexpectedly" in str(caught.value), caught.value


def test_fetch_says_what_to_do_about_uncountable_pages(tmp_path, monkeypatch, capsys):
    """The line that survives F2's routing is the one the author reads, so it
    has to carry the remedy the `check`-time wording already carries."""
    config = _citation_project(tmp_path, DEAD)
    monkeypatch.setattr(
        citations_mod, "fetch_bytes", lambda url, timeout=30.0: NOT_A_PDF
    )
    code, _out, err = _run(capsys, config, "fetch")
    assert code == 0, err
    lines = [line for line in err.splitlines() if "EOF marker not found" in line]
    assert len(lines) == 1, err  # one line, not a bare one plus a warning
    assert DEAD in lines[0], lines[0]
    assert "refdes fetch --update" in lines[0], lines[0]


# ------------------------------------------------------------------- F6 -- refresh


def test_unreachable_refresh_is_said_once(tmp_path, monkeypatch, capsys):
    """One unreachable citation, two warnings saying it: the per-url line and a
    summary that repeats it. The summary only earns its line when there is more
    than one url to count."""
    config = _citation_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD])
    monkeypatch.setattr(citations_mod, "fetch_bytes", _dead_fetcher)
    code, out, err = _run(capsys, config, "check", "--refresh", "--allow-unreachable")
    combined = out + err
    assert code == 0, combined
    said = _said_unreachable(combined.splitlines())
    assert len(said) == 1, combined
    # and that one line keeps both halves: which url, and the escape hatch
    assert DEAD in said[0], said[0]
    assert citations_mod.ALLOW_UNREACHABLE_FLAG in said[0], said[0]


def test_several_unreachable_urls_are_still_counted(tmp_path, monkeypatch, capsys):
    """With two urls the summary is the only place the count lives, so it stays
    -- and each url is still named exactly once."""
    config = _citation_project(tmp_path, DEAD, LIVE)
    _pin(tmp_path, [DEAD, LIVE])
    monkeypatch.setattr(citations_mod, "fetch_bytes", _dead_fetcher)
    code, out, err = _run(capsys, config, "check", "--refresh", "--allow-unreachable")
    combined = out + err
    assert code == 0, combined
    assert combined.count(DEAD) == 1, combined
    assert combined.count(LIVE) == 1, combined
    said = _said_unreachable(combined.splitlines())
    assert len(said) == 3, combined  # two urls and the count, not four lines
    assert "2 pinned citations could not be refreshed" in combined, combined


# -------------------------------------------------------------------- F8 -- keys


def _dead_fetcher(url, timeout=30.0):
    raise OSError("[Errno 111] Connection refused")


def _keyless_project(tmp_path):
    """A project with one live item that declares no key at all."""
    config = write_project_config(tmp_path, SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "req.yaml").write_text(
        "defaults:\n  type: requirement\nitems:\n"
        "  - id: REQ-001\n    title: Keyless\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(config))
    parse.load_items(project)
    build_mod.compute_hashes(project)
    return project


def _wording(message: str) -> str:
    """What is left of a diagnostic once the parts that legitimately vary are
    removed: which key and label are named, the one extra fact about a live
    item that carries the label (a fact, not a wording -- and
    docs/troubleshooting.md promises it), and the argument of the restore
    command, which is a value."""
    tail = message.split("which no item declares. ")[1]
    tail = re.sub(r"^A live item labelled \S+ .*?different item\. ", "", tail)
    return re.sub(r"restore \S+ --dry-run", "restore <target> --dry-run", tail)


def test_one_wording_for_a_key_no_item_declares(tmp_path):
    """Three wordings, one condition. The remedy the report itself gives
    (`docs/troubleshooting.md`: `refdes keys restore`) was spelled out in one
    wording and dropped in the other two, so the same trap sent an author to
    git history from one reference and to the right command from another."""
    project = _keyless_project(tmp_path)
    messages = [
        build_mod._unknown_key_message(project, "refines points at", target)
        for target in (f"REQ-001@{keys.mint()}", f"REQ-999@{keys.mint()}", keys.mint())
    ]
    for message in messages:
        assert "which no item declares." in message, message
        assert "keys restore" in message, message
    # one wording, not three: the explanation and the remedy are the same text
    tails = {_wording(message) for message in messages}
    assert len(tails) == 1, tails


def test_the_restore_command_is_spelled_out_for_a_composite_reference(tmp_path):
    """Not a placeholder and not a paraphrase: the command, with this
    reference's own label and key in it, ready to paste."""
    project = _keyless_project(tmp_path)
    original = keys.mint()
    message = build_mod._unknown_key_message(
        project, "refines points at", f"REQ-001@{original}"
    )
    assert f"run `refdes keys restore REQ-001@{original} --dry-run`" in message, message
