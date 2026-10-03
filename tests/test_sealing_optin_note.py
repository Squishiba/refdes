"""Run-5 F3: the opt-back-in overlay has to say that it took effect.

`hardware@3`'s `log` is `sealing: history` (`base.yaml:298`): an edit to an
entry leaves no trace beyond a warning. Three lines in `refdes-schema.yaml`

    types:
      log:
        sealing: build

put the build-time lock back — a different project, with different rules for
the same file. Run-5 §F3: "The only output on the first run after the edit is
an unrelated one-time `.refdes/schema.json was older than ...` line ... There
is no `note:`, no `WARNING`, nothing confirming the overlay resolved. A user
who adds it and runs `check` cannot tell whether it worked, and a user whose
*intent* was the overlay but who forgot it has no way to discover that either."

So `check` and `build` name the decision: the type, and the file that made it.
Severity is the report's, not ours — F3 is graded **friction (low)** and the
overlay is a *deliberate* choice, so it is a `note:` line, not a WARNING: run-5
B4 is exactly the complaint about a second diagnostic inflating the
`N errors, M warnings` counts, and a permanent warning about a decision the
author just made would inflate them on every run of every project that has one.
A `project.info()` diagnostic was rejected for the same reason the note is not
one: `_visible()` hides info unless `--verbose`, which leaves the author still
unable to see that the overlay took effect.

Nothing here may change an exit code — that is the whole of the contract, and
each test below asserts it.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod
from refdes.schema import load_project

BASE = (
    "site: { title: Opt-in Test, out: ../site_out_optin }\n"
    "standard: { base: hardware, version: 3 }\n"
)
OPT_IN = "types:\n  log:\n    sealing: build\n"
LOG_ITEMS = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    date: 2025-03-01\n    summary: First.\n"
)


def _setup(tmp_path, config: str) -> str:
    write_project_config(tmp_path, config)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(LOG_ITEMS, encoding="utf-8")
    return str(tmp_path / "refdes-project.yaml")


def _run(capsys, cfg: str, *args: str) -> tuple[int, str]:
    """Run a command and hand back (exit code, everything it printed). The
    note goes to stderr, so both streams are one haystack here."""
    code = cli_mod.main(["-c", cfg, *args])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _notes(output: str) -> list[str]:
    return [
        line
        for line in output.splitlines()
        if line.startswith("note:") and "sealing" in line
    ]


def _summary(output: str) -> str:
    return [line for line in output.splitlines() if " errors" in line][-1]


# ------------------------------------------------------- the note, both commands


def test_check_announces_the_overlay_and_still_exits_zero(tmp_path, capsys):
    cfg = _setup(tmp_path, BASE + OPT_IN)
    code, output = _run(capsys, cfg, "check")
    assert code == 0
    assert len(_notes(output)) == 1


def test_build_announces_the_overlay_and_still_exits_zero(tmp_path, capsys):
    cfg = _setup(tmp_path, BASE + OPT_IN)
    code, output = _run(capsys, cfg, "build")
    assert code == 0
    assert len(_notes(output)) == 1


def test_the_note_names_the_type_and_the_file_that_declared_it(tmp_path, capsys):
    """The two things run-5 F3 asked for: which type, and where the decision
    came from. Without the file the reader cannot find the line again; without
    the type a project with more than one append-only type learns nothing."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    for command in ("check", "build"):
        _code, output = _run(capsys, cfg, command)
        note = _notes(output)[0]
        assert "refdes-schema.yaml" in note, command
        assert "'log'" in note, command
        assert "build sealing" in note, command


def test_a_project_without_the_overlay_hears_nothing(tmp_path, capsys):
    """The other half of F3: the note must not be a greeting. A project that
    left the overlay out — the state F3 says is indistinguishable from a
    deliberate one — has to stay silent, or the note tells the author nothing.
    """
    cfg = _setup(tmp_path, BASE)
    for command in ("check", "build"):
        code, output = _run(capsys, cfg, command)
        assert code == 0, command
        assert _notes(output) == [], command
        assert "build sealing" not in output, command


def test_the_note_is_a_note_and_not_a_warning(tmp_path, capsys):
    """Severity, from the report: friction (low), so `note:` — and the
    `N errors, M warnings` summary has to read the same with the overlay as
    without it, which is what makes it a note rather than run-5 B4's second
    diagnostic for one condition."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    code, output = _run(capsys, cfg, "check")
    note = _notes(output)[0]
    assert note.startswith("note:")
    assert "WARNING" not in note
    assert _summary(output) == "1 items, 0 errors, 0 warnings"
    assert code == 0


def test_the_summary_and_exit_codes_are_identical_with_and_without(tmp_path, capsys):
    """The whole point of the note is that nothing else moves: same summary
    line, same exit code, from both commands, overlay or not.

    Each state is measured on a *settled* project — one run first to absorb
    the one-time `.refdes/schema.json was older than refdes-schema.yaml`
    refresh that adding the overlay provokes. That warning is run-5 F3's own
    "unrelated one-time" line, is not this note's doing, and goes away on the
    next run; measuring it would be measuring the editor-completion trip-wire.
    """
    cfg = _setup(tmp_path, BASE)
    _run(capsys, cfg, "check")  # settle: first run mints keys and schema.json
    before = {cmd: _run(capsys, cfg, cmd) for cmd in ("check", "build")}
    (tmp_path / "refdes-schema.yaml").write_text(OPT_IN, encoding="utf-8")
    _run(capsys, cfg, "check")  # settle: the overlay refreshes schema.json once
    after = {cmd: _run(capsys, cfg, cmd) for cmd in ("check", "build")}

    for cmd in ("check", "build"):
        assert before[cmd][0] == 0, cmd
        assert after[cmd][0] == 0, cmd
        assert _summary(before[cmd][1]) == _summary(after[cmd][1]) == (
            "1 items, 0 errors, 0 warnings"
        ), cmd
        assert len(_notes(after[cmd][1])) == 1, cmd
        assert _notes(before[cmd][1]) == [], cmd


# ------------------------------------------------------ what counts as an opt-in


def test_the_overlay_is_recorded_on_the_project(tmp_path):
    """Unit level: the detection, separate from the printing."""
    _setup(tmp_path, BASE)
    config = str(tmp_path / "refdes-project.yaml")
    assert load_project(config_path=config).sealing_optins == []
    (tmp_path / "refdes-schema.yaml").write_text(OPT_IN, encoding="utf-8")
    assert load_project(config_path=config).sealing_optins == ["log"]


def test_declaring_build_on_a_type_the_standard_never_moved_is_not_an_opt_in(
    tmp_path, capsys
):
    """`sealing: build` is the engine default, so a project that declares it
    for its own append-only type has changed nothing and must not be told it
    changed something. Only a type the standard had moved *off* build can be
    opted back into it."""
    cfg = _setup(
        tmp_path,
        BASE
        + "types:\n"
        "  log:\n    sealing: build\n"
        "  memo:\n"
        "    prefix: MEMO\n"
        "    label: Memo\n"
        "    append_only: true\n"
        "    sealing: build\n"
        "    fields:\n"
        "      summary: { type: text, required: true }\n",
    )
    project = load_project(config_path=cfg)
    assert project.sealing_optins == ["log"]
    _code, output = _run(capsys, cfg, "check")
    notes = _notes(output)
    assert len(notes) == 1
    assert "'log'" in notes[0]
    assert "memo" not in notes[0]


@pytest.mark.parametrize("command", ["check", "build"])
def test_the_note_appears_once_per_run(tmp_path, capsys, command):
    """One decision, one line. A note that printed per item, per board, or
    per load would be the noise version of the thing F3 asks for."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    _code, output = _run(capsys, cfg, command)
    assert len([line for line in output.splitlines() if "back into build sealing" in line]) == 1


def test_a_type_that_stopped_being_append_only_is_not_reported(tmp_path, capsys):
    """`sealing:` names what backs an append-only type's guarantee — schema.py's
    own rule, which refuses `sealing: history` without `append_only: true`. A
    project that switched the type off append-only has no lock to have opted
    back into, so it hears nothing about one."""
    cfg = _setup(
        tmp_path,
        BASE + "types:\n  log:\n    append_only: false\n    sealing: build\n",
    )
    assert load_project(config_path=cfg).sealing_optins == []
    _code, output = _run(capsys, cfg, "check")
    assert _notes(output) == []
