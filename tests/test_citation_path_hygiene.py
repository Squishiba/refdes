"""No citation diagnostic may carry an absolute path.

Findings P3 and P4 of `in-prog-logs/pdf-picker-exercise.md`, plus the two
further instances of the same class the sweep turned up.

The house style is a project-relative, `/`-spelled path in every user-facing
message, and one helper already says why in so many words --
`sources._cannot_read` (`src/refdes/sources.py:424`): "`str(OSError)`
interpolates the filename it was raised on -- the absolute path this reader was
handed -- so a `label` is not enough on its own here: the one string that would
undo it is the error's own text."

Every failure here had the same shape: the condition was detected correctly,
and one call site composed an `OSError`'s own `str()` (or let a reader default
its label to `path.as_posix()`) where its siblings composed the canonical
label. The consequences are not only cosmetic. P4's sentence is stored on the
calc line (`citations._source_drift`, citations.py:845) and rendered by
`build.py:2120`, so it reached `/preview/<item>.html` over `refdes serve` and
`_site/` on a plain `refdes build` -- `test_the_preview_page_carries_no_project_root`
below is that claim, over a real socket, rather than an inference from reading
the code. A message that differs between two machines for no reason is the part
that shows up in a pasted CI log, and a published static site carries no token
at all.

Each test asserts the *absence* of the project root as well as the presence of
the label. Asserting only the positive half would pass on a message carrying
both, which is exactly what was being fixed.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys, links, parse
from refdes import sources as sources_mod
from refdes.schema import load_project
from refdes.serve.server import EditorApp

# ---------------------------------------------------------------------- P3

# The sentence `check` already uses for this condition, from
# `citations._resolve_local` (citations.py:1039):
#   `cited local file 'datasheets/nope.pdf' does not exist`
CITE_CONFIG = (
    "site: { title: Path Hygiene, out: _site }\n"
    "types:\n"
    "  component:\n"
    "    prefix: CMP\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      datasheets: { type: citations }\n"
)
ONE_CITER = (
    "defaults:\n  type: component\nitems:\n"
    "  - id: CMP-PWR-001\n    title: Regulator\n    datasheets:\n"
    "      - path: datasheets/nope.pdf\n"
)
TWO_CITERS = (
    "defaults:\n  type: component\nitems:\n"
    "  - id: CMP-PWR-001\n    title: One\n    datasheets:\n"
    "      - path: datasheets/nope.pdf\n"
    "  - id: CMP-PWR-002\n    title: Two\n    datasheets:\n"
    "      - path: datasheets/nope.pdf\n"
)
MISSING = "cited local file 'datasheets/nope.pdf' does not exist"


def _cite_project(tmp_path, item_text: str = ONE_CITER, present=()):
    write_project_config(tmp_path, CITE_CONFIG)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "cmp.yaml").write_text(item_text, encoding="utf-8")
    for name in present:  # nothing by default: the missing file is the subject
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n")
    return str(tmp_path / "refdes-project.yaml")


def _assert_no_root(text: str, root, what: str) -> None:
    assert str(root) not in text, (what, text)
    assert os.path.realpath(root) not in text, (what, text)


def test_fetch_reports_a_missing_local_file_the_way_check_does(tmp_path, capsys):
    """P3. `str(FileNotFoundError)` interpolates the absolute path `open()` was
    handed, so the `FAILED` line led with neither a project-relative path nor a
    citing item -- while every other `FAILED` line names its citers (`cited by
    CMP-PWR-001`). Both halves are the requirement. The id is asserted, not
    assumed: a fix that only stripped the path would still leave an author with
    no idea whose citation to go and fix."""
    config = _cite_project(tmp_path)
    assert cli_mod.main(["-c", config, "fetch"]) == 1
    err = capsys.readouterr().err
    assert MISSING in err, err
    assert "CMP-PWR-001" in err, err
    _assert_no_root(err, tmp_path, "fetch FAILED line")


def test_the_fetch_line_names_every_citer_of_the_missing_file(tmp_path, capsys):
    """Two items on one missing file is one failure with both names, the shape
    `_section_failure` already uses for a section that would not resolve."""
    config = _cite_project(tmp_path, TWO_CITERS)
    assert cli_mod.main(["-c", config, "fetch"]) == 1
    err = capsys.readouterr().err
    assert "cited by CMP-PWR-001, CMP-PWR-002" in err, err
    _assert_no_root(err, tmp_path, "fetch FAILED line")


def test_fetch_and_check_word_the_same_condition_identically(tmp_path, capsys):
    """One sentence for one condition. The report's premise is that `check`
    already had it right and only `fetch` did not -- which is only a safe claim
    while the two cannot drift apart, so it is asserted here rather than
    assumed."""
    config = _cite_project(tmp_path)
    assert cli_mod.main(["-c", config, "fetch"]) == 1
    fetched = capsys.readouterr()
    assert cli_mod.main(["-c", config, "check"]) == 1
    checked = capsys.readouterr()
    for name, captured in (("fetch", fetched), ("check", checked)):
        said = captured.err + captured.out
        assert MISSING in said, (name, said)
        _assert_no_root(said, tmp_path, name)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="a root checkout can read a mode-000 file, so it cannot fail",
)
def test_an_unreadable_local_citation_is_also_named_by_its_label(tmp_path, capsys):
    """Not only the missing file. One `except` handled every `OSError` the open
    could raise, so one substitution covers the rest: the message carries the
    canonical path and the OS's own reason -- `sources._cannot_read`'s two
    halves -- and never the path the bytes were read from."""
    config = _cite_project(
        tmp_path,
        ONE_CITER.replace("datasheets/nope.pdf", "datasheets/locked.pdf"),
        present=("datasheets/locked.pdf",),
    )
    locked = tmp_path / "datasheets" / "locked.pdf"
    locked.chmod(0o000)
    try:
        assert cli_mod.main(["-c", config, "fetch"]) == 1
    finally:
        locked.chmod(0o644)
    err = capsys.readouterr().err
    assert "cited local file 'datasheets/locked.pdf'" in err, err
    assert "Permission denied" in err, err
    assert "CMP-PWR-001" in err, err
    _assert_no_root(err, tmp_path, "unreadable FAILED line")


# ---------------------------------------------------------------------- P4

SRC_CONFIG = (
    "site: { title: Drift, out: _site }\n"
    "types:\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      citations: { type: citations }\n"
)
CSV = "key,value,note\nrail_load,1.85,mW budget\neff,0.93,datasheet\n"
GONE = "key,value,note\nzzz,1,none\n"  # the confirmed row is gone
CALC = '```calc\nP = source("analysis/budget.csv", "rail_load") | W\n```\n'
ITEM = (
    "---\nid: DEC-001\ntype: decision\n"
    "citations:\n  - path: analysis/budget.csv\n---\n\n" + CALC
)


def _src_project(tmp_path, csv: str = CSV, item: str = ITEM):
    write_project_config(tmp_path, SRC_CONFIG)
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "budget.csv").write_text(csv, encoding="utf-8", newline="")
    (tmp_path / "items").mkdir(exist_ok=True)
    (tmp_path / "items" / "a.md").write_text(item, encoding="utf-8")
    return str(tmp_path / "refdes-project.yaml")


def _project(config: str, **build_kwargs):
    project = load_project(config_path=config)
    parse.load_items(project)
    if keys.mint_missing(project, write=True):
        project.items, project.items_by_id, project.pending = {}, {}, []
        parse.load_items(project)
    links.expand_missing_calc_refs(project, write=True)
    build_mod.build(project, **build_kwargs)
    return project


def _messages(project):
    return [d.message for d in project.errors] + [d.message for d in project.warnings]


def _drift_project(tmp_path):
    """A pinned source file whose confirmed row is gone, so the re-location
    fails rather than reporting a changed number."""
    config = _src_project(tmp_path)
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    (tmp_path / "analysis" / "budget.csv").write_text(GONE, encoding="utf-8", newline="")
    return config


def test_the_changed_source_warning_names_the_project_relative_path_only(tmp_path):
    """P4. `_source_drift` called the reader with no `label`, so the reader
    defaulted to `path.as_posix()` and the problem text went into the warning
    verbatim. Every sibling diagnostic in the same run -- the section failures,
    the pypdf messages, the pin itself -- says `analysis/budget.csv`."""
    config = _drift_project(tmp_path)
    drift = next(m for m in _messages(_project(config)) if "SOURCE FILE CHANGED" in m)
    assert "analysis/budget.csv: no row has the key 'rail_load'" in drift, drift
    _assert_no_root(drift, tmp_path, "drift warning")
    # and the build keeps evaluating the locked value, which is the point of it
    assert _project(config).item_by_id("DEC-001").calc_values["P"] == "1.85 W"


def test_the_drift_stored_on_the_calc_line_carries_no_absolute_path(tmp_path):
    """The half that is not a warning, and the one that leaked. `_source_drift`
    writes the same sentence onto the calc line, and `build.py:2120` renders it
    into the item page. Asserting on the warning alone would have passed while
    the published page still carried the server's directory."""
    config = _drift_project(tmp_path)
    drift = _project(config).item_by_id("DEC-001").calcs[0].source_drift
    assert "analysis/budget.csv: no row has the key 'rail_load'" in drift, drift
    _assert_no_root(drift, tmp_path, "calc-line drift")


def test_the_preview_page_carries_no_project_root(tmp_path):
    """The HTTP half, over a real socket: `refdes serve` renders the same site
    into a preview generation (`serve/preview.py:77`) and serves it at
    `/preview/<slug>.html`. Measured before this was fixed -- an HTTP 200 whose
    body contained the server's absolute path once, in the drift span."""
    config = _drift_project(tmp_path)
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        client = Client(app)
        slug = app.state.snapshot.project.item_by_id("DEC-001").slug
        for page in (f"{slug}.html", "document.html"):
            status, _headers, body = client.page(f"/preview/{page}")
            assert status == 200, (page, status)
            html = body.decode("utf-8")
            assert "calc-source-drift" in html, page
            assert "analysis/budget.csv" in html, page
            _assert_no_root(html, tmp_path, f"preview {page}")
    finally:
        app.stop()


def test_fetch_reports_an_unextractable_source_by_its_label(tmp_path, capsys):
    """P4's second instance, on the first-pin path: the same reader, the same
    forgotten `label`, in `fetch_all`."""
    config = _src_project(tmp_path, csv="key,value\nzzz,1\n")
    assert cli_mod.main(["-c", config, "fetch"]) == 1
    err = capsys.readouterr().err
    assert "analysis/budget.csv: no row has the key 'rail_load'" in err, err
    _assert_no_root(err, tmp_path, "first-pin FAILED line")


def test_the_refresh_failure_line_names_the_project_relative_path_only(
    tmp_path, capsys
):
    """P4's third instance, found in the sweep. `_refresh_pinned_sources` -- the
    no-`--update` half -- called the same reader with no `label` either, so
    adding a `source()` line for a key the *pinned* file does not have produced
    a `FAILED` line naming the server's own directory. Three call sites, one
    forgotten argument each; this is the one the report did not name."""
    config = _src_project(tmp_path)
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    (tmp_path / "items" / "a.md").write_text(
        ITEM + '```calc\nQ = source("analysis/budget.csv", "not_a_key") | W\n```\n',
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", config, "fetch"]) == 1
    err = capsys.readouterr().err
    assert "analysis/budget.csv: no row has the key 'not_a_key'" in err, err
    assert "(source key extraction; the record is unchanged)" in err, err
    _assert_no_root(err, tmp_path, "refresh FAILED line")


# ------------------------------------------------------------------ the sweep


def test_the_csv_readers_own_open_failure_does_not_undo_the_label(tmp_path):
    """`sources.CsvReader.extract`'s `OSError` branch composed `str(exc)` where
    every other reader in the file calls `_cannot_read` -- the house helper
    whose docstring is the whole argument (`sources.py:424`). With a `label`
    passed the leak was the *error's own text*; with none, the path appeared
    twice. Reachable from the browser as well: the editor's accept path runs
    `citations.stage_source_pins` -> `_extract_source_values` -> here, and its
    problems go back to the client. Both shapes are asserted."""
    reader = sources_mod.reader_for("analysis/budget.csv")
    # With no label the reader names the file by `path.as_posix()` -- documented
    # and unchanged (sources.py:245) -- so the whole claim here is about the
    # other half: before the fix the path appeared *twice*, once as the label
    # and again inside the error's own text, and `str(exc)`'s `[Errno 2]`
    # bracket was the only thing distinguishing them.
    with pytest.raises(sources_mod.SourceExtractionError) as exc:
        reader.extract(tmp_path / "analysis" / "absent.csv", [])
    target = (tmp_path / "analysis" / "absent.csv").as_posix()
    assert exc.value.problems == [
        f"{target}: cannot read file: No such file or directory"
    ], exc.value.problems

    with pytest.raises(sources_mod.SourceExtractionError) as exc:
        reader.extract(
            tmp_path / "analysis" / "absent.csv", [], label="analysis/absent.csv"
        )
    assert exc.value.problems == [
        "analysis/absent.csv: cannot read file: No such file or directory"
    ], exc.value.problems


def test_the_serve_side_reader_surface_is_project_relative(tmp_path):
    """The invariant the picker design docs promise (`editor-source-picker.md`
    §6, "project-relative paths only"), asserted on the payload rather than
    trusted: the rows of a cited file that cannot be read come back naming the
    canonical path, with the server's own directory in none of them.

    This was already clean and needed no change -- `serve/sources.py` hands the
    reader `label=canon` at every call site and uses `exc.strerror` on the one
    `OSError` of its own, which is the whole reason the leak could not reach the
    item payload or the sources list (the half of the report's HTTP check that
    was right). The test is here so a later change that drops the `label=` at a
    `serve/sources.py` call site fails instead of quietly reintroducing it."""
    from refdes.serve import sources as serve_sources

    config = _cite_project(
        tmp_path,
        "defaults:\n  type: component\nitems:\n"
        "  - id: CMP-PWR-001\n    title: One\n    datasheets:\n"
        "      - path: analysis/budget.csv\n",
    )  # cited, authorized, and not on disk
    project = load_project(config_path=config)
    parse.load_items(project)
    payload = serve_sources.entries_payload(
        project, project.item_by_id("CMP-PWR-001"), "analysis/budget.csv"
    )
    assert payload["entries"] == []
    assert payload["problems"] == [
        "analysis/budget.csv: cannot read file: No such file or directory"
    ], payload["problems"]
    _assert_no_root(repr(payload), tmp_path, "serve sources payload")
