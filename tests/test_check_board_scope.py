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
from refdes import model
from refdes.schema import load_project

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


# ------------------------------------------------- non-`?` unresolved item ids
#
# The path fallback exists for the literal display id `?` that parse.py
# gives id-less items. Other emitters (blocked.py's cycle refs, build.py's
# where_id, seal.py's display_id, former_ids.py's c.new_id) pass item ids
# that may name no item; those diagnostics must keep the every-scope
# visibility they had before the fix.


def test_unresolved_nonquestion_item_id_stays_visible_for_every_board(
    noid_board_project,
):
    project = load_project(
        config_path=str(noid_board_project / "refdes-project.yaml")
    )
    stray = model.Diagnostic(
        level="warning",
        message="blocked_by cycle: LOG-A-999 is not an item",
        file=NOID_FILE,
        item_id="LOG-A-999",
    )
    project.diagnostics.append(stray)
    for board in (None, "board-a", "board-b"):
        visible = cli_mod._visible(project, verbose=False, board=board)
        assert stray in visible, board


# ------------------------------------------------------- unregistered path segment
#
# A `?`-id diagnostic whose file sits under an items/ segment that names no
# registered board is unattributable: docs/cli-reference.md says an
# unattributable diagnostic is never hidden by --board. Its file (board-a's
# noid.md) is registered, so this fixture adds an id-less item under a stray
# segment carrying the same warning.


def test_id_less_item_under_unregistered_path_stays_visible(noid_board_project, capsys):
    stray_dir = noid_board_project / "items" / "stray"
    stray_dir.mkdir(parents=True)
    (stray_dir / "noid.md").write_text(
        f"---\ntype: log\nsummary: entry in an unregistered directory\n{STRAY_FIELD}\n---\n",
        encoding="utf-8",
    )
    for extra in ((), ("--board", "board-a"), ("--board", "board-b")):
        _status, out, _err = _check(noid_board_project, capsys, *extra)
        lines = [
            line
            for line in _warning_lines(out, NOID_WARNING_TEXT)
            if "items/stray/noid.md" in line
        ]
        assert len(lines) == 1, extra


# ------------------------------------------------------------- workspace layout
#
# item_layout: workspace moves boards one level down (items/<ws>/<board>/),
# and the path fallback has its own branch for that layout; the --workspace
# filter rides on the same fallback for `?`-id diagnostics.


WS_CONFIG = """\
site:
  title: "Workspace attribution"
  out: _site
id:
  width: 3
item_layout: workspace
workspaces:
  ws-a:
    label: "Workspace A"
  ws-b:
    label: "Workspace B"
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


@pytest.fixture
def noid_workspace_project(tmp_path):
    write_project_config(tmp_path, WS_CONFIG)
    a = tmp_path / "items" / "ws-a" / "board-a"
    a.mkdir(parents=True)
    (a / "noid.md").write_text(
        f"---\ntype: log\nsummary: entry with no id\n{STRAY_FIELD}\n---\n",
        encoding="utf-8",
    )
    b = tmp_path / "items" / "ws-b" / "board-b"
    b.mkdir(parents=True)
    (b / "log2.md").write_text(
        "---\nid: LOG-B-001\ntype: log\nsummary: clean entry\n---\n",
        encoding="utf-8",
    )
    return tmp_path


def test_workspace_layout_board_axis(noid_workspace_project, capsys):
    """The `?`-id warning follows its board: shown for --board board-a,
    hidden for --board board-b, under item_layout: workspace."""
    _status, out_a, _err = _check(noid_workspace_project, capsys, "--board", "board-a")
    assert _warning_lines(out_a, NOID_WARNING_TEXT) != []
    _status, out_b, _err = _check(noid_workspace_project, capsys, "--board", "board-b")
    assert _warning_lines(out_b, NOID_WARNING_TEXT) == []


def test_workspace_layout_workspace_axis(noid_workspace_project, capsys):
    """The same diagnostic follows its workspace: shown for --workspace
    ws-a, hidden for --workspace ws-b."""
    _status, out_a, _err = _check(
        noid_workspace_project, capsys, "--workspace", "ws-a"
    )
    assert _warning_lines(out_a, NOID_WARNING_TEXT) != []
    _status, out_b, _err = _check(
        noid_workspace_project, capsys, "--workspace", "ws-b"
    )
    assert _warning_lines(out_b, NOID_WARNING_TEXT) == []


def test_workspace_layout_no_id_error_visible_everywhere(noid_workspace_project, capsys):
    """The project-level no-id error keeps its every-scope visibility under
    the workspace layout too."""
    for extra in (
        (),
        ("--board", "board-a"),
        ("--board", "board-b"),
        ("--workspace", "ws-a"),
        ("--workspace", "ws-b"),
    ):
        _status, _out, err = _check(noid_workspace_project, capsys, *extra)
        assert NO_ID_ERROR in err, extra
