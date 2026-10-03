"""Run-5 finding B3: an edit to an *uncaptured* history-backed entry is said.

in-prog-logs/user-sim-release-gate-run5.md §4: a `sealing: history` type keeps
no build-time lock, so an entry with no capture in `.refdes/history/` could be
rewritten wholesale with `check`, `build` and `release` all silent, and the next
release would stamp the rewrite as the recorded truth. The owner's decision is
a WARNING and nothing more — no gate, no changed exit code, and no change to
the `log` type's sealing default.

The fixture is the upgrade path the finding describes: a project whose entries
were sealed by a build-sealed build, then switched to `sealing: history`, so
its `.refdes/log-seal.yaml` is a legacy record holding each entry's prior hash.
The build-sealed behaviour itself is tests/test_seal.py's, unmodified.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import history, loader

SCHEMA = """\
site: {{ title: Uncaptured, out: _site }}
id: {{ width: 3, ledger: .refdes/ids.yaml }}
types:
  log:
    prefix: LOG
    append_only: true
{sealing}    fields:
      summary: {{ type: text, required: true }}
"""

TWO = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First.\n"
    "  - id: LOG-002\n    summary: Second.\n"
)

WARNING = "edited while uncaptured"


def _config(sealing: str) -> str:
    line = f"    sealing: {sealing}\n" if sealing else ""
    return SCHEMA.format(sealing=line)


def _write(tmp_path, sealing: str) -> str:
    write_project_config(tmp_path, _config(sealing))
    return str(tmp_path / "refdes-project.yaml")


def _upgraded_project(tmp_path, *, adopted: bool = False) -> str:
    """Sealed by a build-sealed build, then switched to `sealing: history`."""
    if adopted:
        (tmp_path / ".refdes").mkdir()
        (tmp_path / ".refdes" / "keys-adopted.yaml").write_text(
            "adopted: true\n", encoding="utf-8"
        )
    (tmp_path / "items").mkdir(exist_ok=True)
    (tmp_path / "items" / "log.yaml").write_text(TWO, encoding="utf-8")
    cfg = _write(tmp_path, "")
    assert cli_mod.main(["-c", cfg, "build"]) == 0
    return _write(tmp_path, "history")


def _replace(tmp_path, old: str, new: str) -> None:
    log = tmp_path / "items" / "log.yaml"
    text = log.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    log.write_text(text.replace(old, new), encoding="utf-8")


def _run(capsys, cfg, *argv):
    capsys.readouterr()
    code = cli_mod.main(["-c", cfg, *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _lines(output: str, needle: str) -> list[str]:
    return [line for line in output.splitlines() if needle in line]


# ------------------------------------------------------- the warning itself


def test_an_uncaptured_edit_is_warned_on_check_and_build(tmp_path, capsys):
    """The finding's transcript: upgrade, rewrite an entry, and `check` says
    so instead of calling the project clean."""
    cfg = _upgraded_project(tmp_path)
    _replace(tmp_path, "summary: First.", "summary: First, rewritten.")

    for command in ("check", "build"):
        code, output = _run(capsys, cfg, command)
        assert code == 0, (command, output)
        matches = _lines(output, WARNING)
        assert len(matches) == 1, (command, output)
        # Names the item, says the edit is uncaptured, names the record the
        # prior hash came from, and gives the remedy command.
        assert "LOG-001" in matches[0]
        assert ".refdes/log-seal.yaml" in matches[0]
        assert "`refdes history capture LOG-001`" in matches[0]
        assert "0 errors" in output


def test_the_unchanged_project_draws_no_warning(tmp_path, capsys):
    """The warning is about an edit, not about the upgrade: a project whose
    entries still match their legacy hashes stays quiet."""
    cfg = _upgraded_project(tmp_path)

    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert WARNING not in output


def test_a_keyed_legacy_seal_is_read_the_same_way(tmp_path, capsys):
    """Both shapes of seal record — legacy scalar and §5 surrogate-keyed —
    carry the prior hash, so both detect the edit."""
    cfg = _upgraded_project(tmp_path, adopted=True)
    _replace(tmp_path, "summary: Second.", "summary: Second, rewritten.")

    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    matches = _lines(output, WARNING)
    assert len(matches) == 1, output
    assert "LOG-002" in matches[0]
    # The record really is the §5 keyed shape, not the scalar one.
    assert "hash_format:" in (tmp_path / ".refdes" / "log-seal.yaml").read_text(
        encoding="utf-8"
    )


def test_the_remedy_command_silences_it(tmp_path, capsys):
    """The remedy the warning prints is the command that works: capture the
    entry and the same edit stops being an uncaptured one."""
    cfg = _upgraded_project(tmp_path)
    _replace(tmp_path, "summary: First.", "summary: First, rewritten.")
    assert _lines(_run(capsys, cfg, "check")[1], WARNING)

    code, output = _run(capsys, cfg, "history", "capture", "LOG-001")
    assert code == 0, output

    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert WARNING not in output


# ------------------------------------------- one report per entry, not two


def test_a_captured_entry_is_left_to_the_edited_after_captured_warning(
    tmp_path, capsys
):
    """No double report: once the entry has a capture, H3's diagnostic is the
    one that speaks, and its wording is untouched."""
    cfg = _upgraded_project(tmp_path)
    assert _run(capsys, cfg, "history", "capture", "LOG-001")[0] == 0
    _replace(tmp_path, "summary: First.", "summary: First, rewritten.")

    for command in ("check", "build"):
        code, output = _run(capsys, cfg, command)
        assert code == 0, (command, output)
        assert _lines(output, "edited after captured"), (command, output)
        assert WARNING not in output, (command, output)


# ------------------------------------------------------ never a gate


def test_the_warning_changes_no_exit_code(tmp_path, capsys):
    """`check` and `build` both exit 0 with the warning on screen — the owner's
    decision is a warning, not a gate."""
    cfg = _upgraded_project(tmp_path)
    _replace(tmp_path, "summary: First.", "summary: First, rewritten.")

    for command in ("check", "build"):
        code, output = _run(capsys, cfg, command)
        assert WARNING in output, (command, output)
        assert code == 0, (command, output)


def test_a_project_with_no_legacy_seal_stays_silent(tmp_path, capsys):
    """Nothing ever recorded the entry's content, so there is no edit to
    report: a fresh history-backed project is not warned at."""
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "log.yaml").write_text(TWO, encoding="utf-8")
    cfg = _write(tmp_path, "history")
    _replace(tmp_path, "summary: First.", "summary: First, rewritten.")

    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert WARNING not in output


def test_check_writes_nothing_while_warning(tmp_path, capsys):
    """Read-only like the diagnostic it sits beside: no capture, no seal
    rewrite, no new files."""
    cfg = _upgraded_project(tmp_path)
    _replace(tmp_path, "summary: First.", "summary: First, rewritten.")
    seal_before = (tmp_path / ".refdes" / "log-seal.yaml").read_bytes()

    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert WARNING in output
    assert (tmp_path / ".refdes" / "log-seal.yaml").read_bytes() == seal_before
    assert not (tmp_path / ".refdes" / "history").exists()


def test_an_unreadable_store_is_named_once_and_still_exits_zero(tmp_path, capsys):
    """A history store that refuses to be read must not crash the run, must not
    fail it, and must not be complained about twice: the sibling diagnostic one
    step earlier in the same build is the one that names it."""
    cfg = _upgraded_project(tmp_path)
    _replace(tmp_path, "summary: First.", "summary: First, rewritten.")
    events = tmp_path / ".refdes" / "history" / "events"
    events.mkdir(parents=True)
    (events / "hand-rolled.yaml").write_text(
        "history_format: 1\nid: hand-rolled\nkind: followed\n", encoding="utf-8"
    )

    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert len(_lines(output, "not checked")) == 1
    assert WARNING not in output


def test_the_diagnostic_is_a_warning_object_not_an_error(tmp_path):
    """Unit level: it lands on `project.warnings` with the item attributed,
    and `project.errors` stays empty."""
    cfg = _upgraded_project(tmp_path)
    _replace(tmp_path, "summary: First.", "summary: First, rewritten.")
    project, _stale = loader.load_tree(cfg, write=False)
    build_mod.build(project)

    findings = history.uncaptured_edits(project)
    assert [f.item.id for f in findings] == ["LOG-001"]
    assert findings[0].seal_file == ".refdes/log-seal.yaml"
    warnings = [d for d in project.warnings if WARNING in d.message]
    assert len(warnings) == 1
    assert warnings[0].item_id == "LOG-001"
    assert warnings[0].file == "items/log.yaml"
    assert [d for d in project.errors if "uncaptured" in d.message] == []
