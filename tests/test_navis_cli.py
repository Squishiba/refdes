"""Navis slice 1 read-only CLI (in-prog-logs/navis-design-20261025.md §11, §13).

`refdes navis ls|all|show` over the same projection the `index` payload
carries (the panel/CLI "never a second implementation" rule, §11). Slice 1
is read-only: keys are minted by a later slice, archive records land in a
later slice, so `all` is the active list with an honest archived note and
`show` addresses a marker by its ls number or its full 11-character key.

Exit-code posture is the neighbours': a clean run is 0 (including a project
with no Navis at all), `show` on a selector that names nothing is a naming
error -- exit 2, like `thread <unknown-ref>`/`history capture`.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import cli as cli_mod

SCHEMA = (
    "site: { title: Navis CLI, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

TWO_MARKERS = {
    "note-a.md": (
        "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\n"
        "intro\n<!--navi:k7f3q2x8d0m Model worst-case copper temperature.-->\n"
    ),
    "note-b.md": (
        "---\nid: NOTE-002\ntype: note\ntitle: Decoupling\n---\n"
        "<!--navi: Recheck decoupling near U14.-->\n"
    ),
}

NO_MARKERS = {
    "note-a.md": (
        "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\nplain body\n"
    ),
}


def _setup(tmp_path, files):
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")
    return str(config)


def _run(config, *args):
    return cli_mod.main(["-c", config, *args])


def test_navis_ls_on_project_without_markers_exits_clean(tmp_path, capsys):
    config = _setup(tmp_path, NO_MARKERS)
    assert _run(config, "--no-write", "navis", "ls") == 0
    out = capsys.readouterr().out
    assert "no navis" in out.lower()


def test_navis_ls_lists_rows_with_source(tmp_path, capsys):
    config = _setup(tmp_path, TWO_MARKERS)
    assert _run(config, "--no-write", "navis", "ls") == 0
    out = capsys.readouterr().out
    assert "Model worst-case copper temperature." in out
    assert "Recheck decoupling near U14." in out
    # §10: CLI rows print DISPLAY-ID (file:line).
    assert "NOTE-001 (items/note-a.md:7)" in out
    assert "NOTE-002 (items/note-b.md:6)" in out


def test_navis_ls_is_ordered_by_file_and_line(tmp_path, capsys):
    config = _setup(tmp_path, TWO_MARKERS)
    _run(config, "--no-write", "navis", "ls")
    out = capsys.readouterr().out
    assert out.index("copper temperature") < out.index("decoupling near U14")
    assert "1." in out and "2." in out


def test_navis_all_includes_active_and_notes_archived(tmp_path, capsys):
    config = _setup(tmp_path, TWO_MARKERS)
    assert _run(config, "--no-write", "navis", "all") == 0
    out = capsys.readouterr().out
    assert "Model worst-case copper temperature." in out
    assert "archived" in out.lower()


def test_navis_show_by_number(tmp_path, capsys):
    config = _setup(tmp_path, TWO_MARKERS)
    assert _run(config, "--no-write", "navis", "show", "1") == 0
    out = capsys.readouterr().out
    assert "Model worst-case copper temperature." in out
    assert "NOTE-001" in out
    assert "items/note-a.md:7" in out


def test_navis_show_by_full_key(tmp_path, capsys):
    config = _setup(tmp_path, TWO_MARKERS)
    assert _run(config, "--no-write", "navis", "show", "k7f3q2x8d0m") == 0
    out = capsys.readouterr().out
    assert "k7f3q2x8d0m" in out
    assert "Model worst-case copper temperature." in out


def test_navis_show_unknown_exits_2(tmp_path, capsys):
    config = _setup(tmp_path, TWO_MARKERS)
    assert _run(config, "--no-write", "navis", "show", "99") == 2
    assert "no Navi" in capsys.readouterr().err


def test_navis_show_non_ascii_digit_selector_exits_2(tmp_path, capsys):
    # `str.isdigit()` is True for '²' and int() then raises -- the
    # documented posture for a selector that names nothing is exit 2,
    # not a traceback.
    config = _setup(tmp_path, TWO_MARKERS)
    assert _run(config, "--no-write", "navis", "show", "²") == 2
    assert "no Navi" in capsys.readouterr().err


def test_show_huge_ascii_ordinal_is_naming_error(tmp_path, capsys):
    # 5,000 digits is a valid ASCII ordinal, not a crash: the selector
    # is bounded against the row count before int() runs, so it names
    # nothing and exits 2.
    config = _setup(tmp_path, TWO_MARKERS)
    assert _run(config, "--no-write", "navis", "show", "9" * 5000) == 2
    assert "no Navi" in capsys.readouterr().err


def test_navis_ls_numbers_document_order_on_one_line(tmp_path, capsys):
    # Two markers share a line: `ls` numbers them as the page reads them
    # (design §11 (file, line) order + document order), and `show 1` is
    # the one that comes first in the file, not the one first in the
    # alphabet.
    files = {
        "note-a.md": (
            "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\n"
            "<!--navi: zebra first--><!--navi: apple second-->\n"
        ),
    }
    config = _setup(tmp_path, files)
    assert _run(config, "--no-write", "navis", "show", "1") == 0
    assert "zebra first" in capsys.readouterr().out
    assert _run(config, "--no-write", "navis", "show", "2") == 0
    assert "apple second" in capsys.readouterr().out


def test_navis_show_by_all_digit_key(tmp_path, capsys):
    # The key alphabet includes every digit, so an 11-character all-digit
    # key is legal grammar; a full-key selector must resolve as a key, not
    # be read as an out-of-range ordinal.
    files = {
        "note-a.md": (
            "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\n"
            "intro\n<!--navi:12345678901 Model worst-case copper temperature.-->\n"
        ),
    }
    config = _setup(tmp_path, files)
    assert _run(config, "--no-write", "navis", "show", "12345678901") == 0
    out = capsys.readouterr().out
    assert "Model worst-case copper temperature." in out
    assert "12345678901" in out


def test_navis_show_exits_1_when_items_file_fails_to_parse(tmp_path, capsys):
    config = _setup(tmp_path, TWO_MARKERS)
    broken = tmp_path / "items" / "broken.md"
    broken.write_text("---\nid: NOTE-999\ntype: [note\n---\nbody\n", encoding="utf-8")
    assert _run(config, "--no-write", "navis", "show", "1") == 1
    captured = capsys.readouterr()
    assert "Model worst-case copper temperature." in captured.out
    assert "broken.md" in captured.err


def test_navis_show_names_keyless_markers(tmp_path, capsys):
    config = _setup(tmp_path, TWO_MARKERS)
    assert _run(config, "--no-write", "navis", "show", "2") == 0
    out = capsys.readouterr().out
    assert "keyless" in out


def test_navis_ls_reports_malformed_markers_on_stderr(tmp_path, capsys):
    config = _setup(
        tmp_path,
        {
            "note-a.md": (
                "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\n"
                "<!--navi:-->\n"
            )
        },
    )
    assert _run(config, "--no-write", "navis", "ls") == 0
    err = capsys.readouterr().err
    assert "no text" in err
    assert "items/note-a.md:6" in err


def test_navis_help_lists_subcommands(tmp_path, capsys):
    config = _setup(tmp_path, NO_MARKERS)
    import pytest

    with pytest.raises(SystemExit) as excinfo:
        _run(config, "--no-write", "navis", "--help")
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for verb in ("ls", "all", "show"):
        assert verb in out


def test_navis_bare_names_the_subcommands(tmp_path, capsys):
    config = _setup(tmp_path, NO_MARKERS)
    import pytest

    with pytest.raises(SystemExit) as excinfo:
        _run(config, "--no-write", "navis")
    assert excinfo.value.code == 2
    assert "required" in capsys.readouterr().err


def test_navis_ls_on_empty_project_exits_clean(tmp_path, capsys):
    # A project with no items at all: still a clean answer, not a crash.
    config = str(write_project_config(tmp_path, SCHEMA))
    (tmp_path / "items").mkdir()
    assert _run(config, "--no-write", "navis", "ls") == 0
