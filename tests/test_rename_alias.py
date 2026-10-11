"""P12 (docs/design/vocabulary-review.md §3.3): `refdes revise` is `refdes
rename` now -- `revise` and `revision` are two letters apart and do unrelated
things, and the command's own description has always been a rename: it applies
an explicit old->new vocabulary mapping to every item file.

The alias is what these tests are for, not the new name: `revise` keeps
working with identical behaviour and exit codes until the next minor release,
it says so once on stderr (stdout is the report a script reads), and it has
stopped appearing in `refdes --help`, where anyone who has not read the
changelog looks up the word they already type.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod

SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
)

MAPPING = "prefixes:\n  BND: LIM\n"

NOTE = (
    "`refdes revise` is now `refdes rename`; `revise` will be removed in the "
    "next minor release"
)


def _project(root) -> str:
    """A project whose one rename need is a prefix: the rename category that
    never depends on the schema, so both spellings have real work to do.
    Returns the `refdes-project.yaml` path."""
    write_project_config(root, SCHEMA)
    (root / "items").mkdir()
    (root / "items" / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        '  - id: BND-001\n    text: Board power density\n    limit: "<= 0.15 W/in^2"\n',
        encoding="utf-8",
    )
    (root / "rename.yaml").write_text(MAPPING, encoding="utf-8")
    return str(root / "refdes-project.yaml")


def _cli(command: str, root, capsys, extra=()):
    """Run one spelling of the command against `root`, returning its exit status
    and the two streams separately -- which is the whole subject here."""
    capsys.readouterr()
    status = cli_mod.main(
        [
            "-c",
            str(root / "refdes-project.yaml"),
            command,
            str(root / "rename.yaml"),
            *extra,
        ]
    )
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def _renamed_text(root) -> str:
    return (root / "items" / "i.yaml").read_text(encoding="utf-8")


# ------------------------------------------------------------------ the new name


def test_rename_lists_in_help_and_the_alias_does_not_appear_at_all(capsys):
    """`rename` is listed; `revise` is not merely demoted but absent, usage
    line included. argparse's own `help=SUPPRESS` hides an *option*, while a
    subcommand's row is printed by `_format_action` without consulting it and
    the usage line's `{...}` list is built from the parser map that dispatches
    the alias -- both verified on this Python (3.13.5), which is why cli.py has
    `_hide_command` rather than the argparse idiom."""
    with pytest.raises(SystemExit):
        cli_mod.main(["--help"])
    out = capsys.readouterr().out
    assert "rename" in out
    assert "revise" not in out


def test_rename_does_the_work_and_says_nothing_on_stderr(tmp_path, capsys):
    _project(tmp_path)
    status, out, err = _cli("rename", tmp_path, capsys)
    assert status == 0
    assert "changed 1 file(s):" in out
    assert "BND-001 -> LIM-001" in out
    assert err == ""
    text = _renamed_text(tmp_path)
    assert "prefix: LIM" in text
    assert "id: LIM-001" in text


# ---------------------------------------------------------------------- the alias


def test_revise_still_does_the_work_and_says_so_once(tmp_path, capsys):
    _project(tmp_path)
    status, out, err = _cli("revise", tmp_path, capsys)
    assert status == 0
    assert err.strip() == NOTE  # one line, and nothing else on stderr
    text = _renamed_text(tmp_path)
    assert "prefix: LIM" in text
    assert "id: LIM-001" in text


def test_revise_stdout_is_rename_stdout_byte_for_byte(tmp_path, capsys):
    """The note may never touch stdout: this command's stdout *is* its report,
    so a script reading `changed N file(s):` has to get the same bytes whichever
    name was typed -- including under `--dry-run`, whose whole point is output
    something else consumes."""
    first = tmp_path / "new"
    second = tmp_path / "old"
    first.mkdir()
    second.mkdir()
    _project(first)
    _project(second)

    status_new, out_new, _ = _cli("rename", first, capsys)
    status_old, out_old, err_old = _cli("revise", second, capsys)
    assert (status_new, status_old) == (0, 0)
    assert out_old == out_new
    assert NOTE not in out_old

    _, dry_new, _ = _cli("rename", first, capsys, extra=("--dry-run",))
    _, dry_old, _ = _cli("revise", second, capsys, extra=("--dry-run",))
    assert dry_old == dry_new


def test_revise_keeps_the_configuration_exit_codes(tmp_path, capsys):
    """Identical behaviour includes the refusals: a mapping file that is not on
    disk is the configuration error docs/cli-reference.md's exit-code table
    gives `2` for, on either spelling."""
    root = tmp_path / "p"
    root.mkdir()
    config = _project(root)
    capsys.readouterr()
    missing = str(root / "nope.yaml")
    assert cli_mod.main(["-c", config, "rename", missing]) == 2
    assert cli_mod.main(["-c", config, "revise", missing]) == 2
    capsys.readouterr()


def test_revise_help_still_explains_itself(capsys):
    """Hidden from the list, still self-documenting: whoever has the old name in
    their shell history gets the same description and the same two arguments."""
    with pytest.raises(SystemExit):
        cli_mod.main(["revise", "--help"])
    out = capsys.readouterr().out
    assert "Apply an explicit old->new vocabulary mapping" in out
    assert "--dry-run" in out
    assert "mapping" in out
