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

Run-6a F10 fixed the *cadence*: printing on every run is "a permanent one-liner
in every CI check log [that] trains people to skim notes". The note now prints
when the decision is news — the first run after the opt-in appears, and again
when the set of opted-in types changes — with the set recorded under
`.refdes/`, the same posture as the `.refdes/schema.json ... refreshed` note.
A `--no-write`/`--dry-run` run prints by the same rule and records nothing;
`--verbose` always prints.

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


def _setup_in(root, config: str) -> str:
    """A whole project in its own directory. Run-6a F10 made the note
    once-per-tree stateful, so a test that wants the note from two commands
    needs two trees: the second command runs on a project that has already
    heard it."""
    root.mkdir(parents=True, exist_ok=True)
    return _setup(root, config)


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
    the type a project with more than one append-only type learns nothing.

    Two trees, because run-6a F10: on one tree only the first of the two
    commands still hears the note."""
    for command in ("check", "build"):
        cfg = _setup_in(tmp_path / command, BASE + OPT_IN)
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

    Each side is measured on a *fresh* tree, on the first run of each
    command: run-6a F10 made the note once-per-tree, so the run that carries
    it is the run that first sees the overlay, and the settled-state measure
    this test used to take (one run to absorb the one-time
    `.refdes/schema.json was older than refdes-schema.yaml` refresh, then
    measure) now measures the run *after* the note and sees only silence.
    A fresh tree absorbs the schema.json refresh the same way -- the file
    is created, not found stale -- so the summaries stay comparable.
    """
    cfg = _setup_in(tmp_path / "plain", BASE)
    before = {cmd: _run(capsys, cfg, cmd) for cmd in ("check", "build")}
    cfgs = {
        cmd: _setup_in(tmp_path / cmd, BASE + OPT_IN) for cmd in ("check", "build")
    }
    after = {cmd: _run(capsys, cfgs[cmd], cmd) for cmd in ("check", "build")}

    for cmd in ("check", "build"):
        assert before[cmd][0] == 0, cmd
        assert after[cmd][0] == 0, cmd
        assert _summary(before[cmd][1]) == _summary(after[cmd][1]) == (
            "1 items, 0 errors, 0 warnings"
        ), cmd
        assert len(_notes(after[cmd][1])) == 1, cmd
        assert _notes(before[cmd][1]) == [], cmd


# ---------------------------------------------------- once, not on every run (F10)


def _state_file(tmp_path):
    return tmp_path / ".refdes" / "sealing-optin.json"


def test_two_consecutive_checks_print_the_note_once(tmp_path, capsys):
    """Run-6a F10: the note confirms a decision, and a decision is news once.
    Two consecutive `check` runs print it on the first and are silent on the
    second — the same posture as the `.refdes/schema.json ... refreshed`
    note, which prints when the state under `.refdes/` goes out of step and
    goes quiet when a writable run puts it back. `build` after `check` is
    silent for the same reason: one set, one announcement, across commands."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    _code, first = _run(capsys, cfg, "check")
    assert len(_notes(first)) == 1
    _code, second = _run(capsys, cfg, "check")
    assert _notes(second) == []
    _code, third = _run(capsys, cfg, "build")
    assert _notes(third) == []


def test_the_note_returns_once_when_the_set_of_opted_in_types_changes(
    tmp_path, capsys
):
    """The set is the state, not the file's existence: taking the overlay out
    is recorded (silently — there is nothing to confirm), and putting it back
    is a decision again, printed exactly once. The run that re-adds has to be
    measured against the *third* run to show the note is once-per-set again,
    not just "printed once more, then forever"."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    assert len(_notes(_run(capsys, cfg, "check")[1])) == 1
    (tmp_path / "refdes-schema.yaml").write_text("types: {}\n", encoding="utf-8")
    assert _notes(_run(capsys, cfg, "check")[1]) == []  # removal: silent
    (tmp_path / "refdes-schema.yaml").write_text(OPT_IN, encoding="utf-8")
    assert len(_notes(_run(capsys, cfg, "check")[1])) == 1  # re-added: once
    assert _notes(_run(capsys, cfg, "check")[1]) == []  # and quiet again


def test_a_no_write_run_prints_the_note_without_consuming_it(tmp_path, capsys):
    """`--no-write` promises the tree is untouched, and recording "already
    announced" *is* touching it (docs/design/keys.md §2). So a read-only run
    prints by the same rule — set differs from what is recorded — but records
    nothing: the next writable run, the one that owns the tree, still prints
    it, and only that run goes quiet afterwards."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    assert len(_notes(_run(capsys, cfg, "--no-write", "check")[1])) == 1
    assert not _state_file(tmp_path).exists(), "--no-write recorded a state file"
    assert len(_notes(_run(capsys, cfg, "--no-write", "check")[1])) == 1
    assert len(_notes(_run(capsys, cfg, "check")[1])) == 1  # not consumed
    assert _notes(_run(capsys, cfg, "check")[1]) == []


def test_a_dry_run_build_does_not_consume_the_note(tmp_path, capsys):
    """`build --dry-run` is `--no-write`'s promise made under its own name
    (cli._load says so); its load writes nothing, and its announcement
    records nothing for the same reason."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    assert len(_notes(_run(capsys, cfg, "build", "--dry-run")[1])) == 1
    assert not _state_file(tmp_path).exists()
    assert len(_notes(_run(capsys, cfg, "check")[1])) == 1


def test_verbose_always_prints_the_note(tmp_path, capsys):
    """The decided answer for `--verbose` (run-6a F10): a reader who asked to
    see everything sees the confirmation on the run they asked for it,
    settled project or not. It records as usual: a `--verbose` run on an
    unannounced set is that set's announcement, so the next plain run of the
    same project is already settled and quiet."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    assert len(_notes(_run(capsys, cfg, "check", "-v")[1])) == 1
    assert len(_notes(_run(capsys, cfg, "check", "-v")[1])) == 1  # settled: still
    fresh = _setup_in(tmp_path / "fresh", BASE + OPT_IN)
    assert len(_notes(_run(capsys, fresh, "check", "-v")[1])) == 1  # prints...
    assert _notes(_run(capsys, fresh, "check")[1]) == []  # ...and records


def test_a_project_without_the_overlay_never_grows_the_state_file(
    tmp_path, capsys
):
    """Most projects have no overlay, and for them this whole mechanism must
    be invisible: no note (pinned above), and no file under `.refdes/` to
    gitignore, to wonder about, or to `git add`."""
    cfg = _setup(tmp_path, BASE)
    for cmd in ("check", "build"):
        assert _run(capsys, cfg, cmd)[0] == 0, cmd
    assert not _state_file(tmp_path).exists()


def test_a_corrupt_state_file_prints_the_note_and_is_rewritten(tmp_path, capsys):
    """A lost tool state re-derives: an unparseable record reads as
    "never announced", so the note prints and the next writable run rewrites
    the file — it does not silence the note it guards."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    assert len(_notes(_run(capsys, cfg, "check")[1])) == 1
    _state_file(tmp_path).write_text("{not json", encoding="utf-8")
    assert len(_notes(_run(capsys, cfg, "check")[1])) == 1  # re-printed
    assert _notes(_run(capsys, cfg, "check")[1]) == []  # record repaired


def test_the_note_still_changes_no_count_and_no_exit_code_after_settling(
    tmp_path, capsys
):
    """The run-5 F3 contract re-pinned through the F10 lens: the settled
    project — the state every later CI run lives in — prints nothing and
    scores exactly like a project that never had the overlay. A note that
    leaked into the counts, once per run or not, breaks this."""
    cfg = _setup(tmp_path, BASE + OPT_IN)
    _run(capsys, cfg, "check")  # first run: the note, and it records
    code, output = _run(capsys, cfg, "check")
    assert code == 0
    assert _notes(output) == []
    assert _summary(output) == "1 items, 0 errors, 0 warnings"


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
