"""CHK-ATTR-003: `check --board NAME` leaks an id-less item's diagnostics.

docs/cli-reference.md: `check --board` reports one board's own item
diagnostics, while project-level diagnostics stay visible. A warning for an
item WITHOUT an id (display id `[?]`) used to name the item's file but was
attributed by item id, so it showed up under every `--board` selection. The
fix attributes `?`-id item diagnostics by the diagnostic's file path /
owning board; the project-level "item has no id" error keeps its
every-board visibility.

Fixture mirrors the reference reproduction: two boards; board-a has an item
with an id and an item without one, each carrying the same unknown-field
warning (so only the file path tells their diagnostics apart); board-b has a
clean item.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod

CONFIG = """\
site:
  title: "Board attribution"
  out: _site
id:
  width: 3
boards:
  board-a:
    label: "Board A"
  board-b:
    label: "Board B"
types:
  log:
    prefix: LOG
    label: "Log Entry"
    fields:
      summary: { type: text, required: true }
"""

# Both board-a items carry this field, so the emitted warning text is
# identical for them; only the file path in the rendered line distinguishes
# the id-bearing item's warning from the id-less item's.
STRAY_FIELD = "text: stray field, unknown on the log type"

NO_ID_ERROR = "item has no id"
NO_ID_HINT = "run 'refdes id' to allocate one"
NOID_WARNING_TEXT = "unknown field 'text' on log entry"
NOID_FILE = "items/board-a/noid.md"
ID_BEARING_FILE = "items/board-a/log.md"


@pytest.fixture
def noid_board_project(tmp_path):
    write_project_config(tmp_path, CONFIG)

    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "log.md").write_text(
        "---\nid: LOG-A-001\ntype: log\nsummary: first entry\n"
        f"{STRAY_FIELD}\n---\n",
        encoding="utf-8",
    )
    (a / "noid.md").write_text(
        f"---\ntype: log\nsummary: entry with no id\n{STRAY_FIELD}\n---\n",
        encoding="utf-8",
    )

    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "log2.md").write_text(
        "---\nid: LOG-B-001\ntype: log\nsummary: clean entry\n---\n",
        encoding="utf-8",
    )
    return tmp_path


def _check(project_dir, capsys, *extra):
    status = cli_mod.main(
        ["-c", str(project_dir / "refdes-project.yaml"), "--no-write", "check", *extra]
    )
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def _warning_lines(out: str, needle: str) -> list[str]:
    return [
        line
        for line in out.splitlines()
        if line.startswith("WARNING") and needle in line
    ]


def test_id_less_item_warning_shown_for_its_own_board(noid_board_project, capsys):
    """The id-less board-a item's own warning must be reported for
    --board board-a (control: already true today; the fix must not hide it)."""
    _status, out, _err = _check(noid_board_project, capsys, "--board", "board-a")
    lines = _warning_lines(out, NOID_WARNING_TEXT)
    noid_lines = [line for line in lines if NOID_FILE in line]
    assert len(noid_lines) == 1
    assert "[?]" in noid_lines[0]  # the id-less item's display id


def test_own_board_summary_keeps_id_less_item_warning(noid_board_project, capsys):
    """board-a's summary counts both of board-a's warnings (control)."""
    _status, out, _err = _check(noid_board_project, capsys, "--board", "board-a")
    assert "1 items, 1 errors, 2 warnings" in out


def test_id_less_item_warning_absent_for_other_board(noid_board_project, capsys):
    """The new behavior: --board board-b must NOT report the id-less
    board-a item's warning. On the buggy code it leaks (attributed by the
    unresolvable display id `?`, so no board matched it and it was treated
    as project-level and always shown)."""
    _status, out, _err = _check(noid_board_project, capsys, "--board", "board-b")
    assert _warning_lines(out, NOID_FILE) == []
    assert _warning_lines(out, NOID_WARNING_TEXT) == []


def test_other_board_summary_excludes_id_less_item_warning(noid_board_project, capsys):
    """Same leak seen through the summary line: board-b's own warnings are
    none, so the count must read 0 (buggy code counts the leaked warning)."""
    _status, out, _err = _check(noid_board_project, capsys, "--board", "board-b")
    assert "1 items, 1 errors, 0 warnings" in out


def test_project_level_no_id_error_visible_on_every_board(noid_board_project, capsys):
    """The 'item has no id' error is project-level and keeps its documented
    visibility: shown for every board selection and for the unscoped run
    (control)."""
    for extra in ((), ("--board", "board-a"), ("--board", "board-b")):
        status, _out, err = _check(noid_board_project, capsys, *extra)
        assert NO_ID_ERROR in err
        assert NO_ID_HINT in err
        assert status == 1  # the visible error keeps check red on every run


def test_id_bearing_item_warning_scoping_unchanged(noid_board_project, capsys):
    """Items WITH ids keep today's scoping: LOG-A-001's identical warning
    shows for board-a and is hidden for board-b (control)."""
    _status, out_a, _err = _check(noid_board_project, capsys, "--board", "board-a")
    assert _warning_lines(out_a, ID_BEARING_FILE) != []
    _status, out_b, _err = _check(noid_board_project, capsys, "--board", "board-b")
    assert _warning_lines(out_b, ID_BEARING_FILE) == []


def test_check_without_board_shows_all_diagnostics(noid_board_project, capsys):
    """An unscoped check reports every diagnostic (control)."""
    status, out, err = _check(noid_board_project, capsys)
    assert len(_warning_lines(out, NOID_WARNING_TEXT)) == 2
    assert _warning_lines(out, NOID_FILE) != []
    assert _warning_lines(out, ID_BEARING_FILE) != []
    assert NO_ID_ERROR in err
    assert "2 items, 1 errors, 2 warnings" in out
    assert status == 1
