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

import re

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import keys as keys_mod

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

# A rewrite has to mint at least one surrogate key, and `keys.mint()` draws it
# from `secrets.token_bytes` (keys.py), so the plan it prints is not the same
# bytes twice -- in either spelling. The alphabet is spelled out of keys.py
# rather than retyped, so a future widening of it cannot leave this stale.
_MINTED_KEY = re.compile(
    r"(?<=key: )" + f"[{keys_mod.ALPHABET}]{{{keys_mod.KEY_LEN}}}" + r"\b"
    r"|(?<=@)" + f"[{keys_mod.ALPHABET}]{{{keys_mod.KEY_LEN}}}" + r"\b"
)


def _without_minted_keys(report: str) -> str:
    """A dry-run plan with the per-run minted keys blanked: the two spellings'
    plans differ by nothing else, so this is exact, not a loosened comparison."""
    return _MINTED_KEY.sub("<key>", report)


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
    something else consumes.

    The `--dry-run` half needs its OWN trees: run on a tree the same test has
    already renamed, both spellings would print the no-op "nothing to do"
    report and the comparison would prove nothing. And the plan is compared with
    the minted key blanked, because a plan that has to mint prints a fresh
    11-character surrogate key per RUN (`keys.mint()` is `secrets`-based), so
    two runs differ there whichever name was typed -- the only difference
    between the two spellings' plans is that key, so blanking it is exact
    rather than a loosening.
    """
    trees = [tmp_path / name for name in ("new", "old", "dry-new", "dry-old")]
    for root in trees:
        root.mkdir()
        _project(root)
    first, second, dry_first, dry_second = trees

    status_new, out_new, _ = _cli("rename", first, capsys)
    status_old, out_old, err_old = _cli("revise", second, capsys)
    assert (status_new, status_old) == (0, 0)
    assert out_old == out_new
    assert NOTE not in out_old

    status_dry_new, dry_new, _ = _cli("rename", dry_first, capsys, extra=("--dry-run",))
    status_dry_old, dry_old, _ = _cli("revise", dry_second, capsys, extra=("--dry-run",))
    assert (status_dry_new, status_dry_old) == (0, 0)
    assert "would change 1 file(s):" in dry_new  # real planned work, not the no-op
    assert "key: " in dry_new  # the plan mints, so the blanking below has work to do
    assert _without_minted_keys(dry_old) == _without_minted_keys(dry_new)


# ----------------------------------------------------------------- refusal text

# The guard's refusal is the text a stuck author actually reads, and P12 is
# about what the tool calls this command in front of them, so it is pinned here
# rather than in the engine's own tests. A `flow:`-style item whose `type:`
# cannot be reached by the rewrite is the shape that trips it.
FLOW_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    fields:\n"
    "      text: { type: text, required: true }\n"
)
FLOW_ITEM = (
    "defaults:\n  type: bound\n  prefix: BND\n"
    "items:\n"
    "  - {id: BND-001,\n"
    "    type: bound,\n"
    "    text: Board power density}\n"
)


def test_a_refusal_reached_through_rename_names_rename(tmp_path, capsys):
    """`refdes rename` on a value the rewrite cannot reach refuses (exit 1) and
    says `the rename` -- never the retired name -- while leaving the file
    untouched. `refdes standard upgrade` runs the same engine through the same
    strings (apply_standard_upgrade calls apply() per version step), which is
    why the wording is "the rename" and not a bare "rename"/"revise"."""
    write_project_config(tmp_path, FLOW_SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(FLOW_ITEM, encoding="utf-8")
    (tmp_path / "rename.yaml").write_text("types:\n  bound: constraint\n", encoding="utf-8")

    status, out, err = _cli("rename", tmp_path, capsys)
    assert status == 1
    assert "the rename cannot edit" in err
    assert "revise" not in err
    assert out == ""
    assert (tmp_path / "items" / "i.yaml").read_text(encoding="utf-8") == FLOW_ITEM


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
    their shell history gets the same description and the same two arguments.

    The help is whitespace-normalized before the 46-character phrase is matched
    (the same way tests/test_index_help.py reads its help), because argparse
    wraps the description to the terminal's width: on a narrow enough
    terminal the phrase breaks mid-sentence and the raw match fails."""
    with pytest.raises(SystemExit):
        cli_mod.main(["revise", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "Apply an explicit old->new vocabulary mapping" in out
    assert "--dry-run" in out
    assert "mapping" in out


def test_revise_unparseable_mapping_exits_2_saying_what_rename_says(tmp_path, capsys):
    """The missing-file half of the configuration refusals is pinned for both
    spellings above; the unparseable-file half was pinned for `rename` alone
    (tests/test_revise.py). The alias must carry it too: same exit 2, the
    same one-line note byte for byte, and its own note line and nothing
    more besides."""
    root = tmp_path / "p"
    root.mkdir()
    config = _project(root)
    bad = root / "bad.yaml"
    bad.write_text("prefixes: [unclosed\n", encoding="utf-8")

    capsys.readouterr()
    assert cli_mod.main(["-c", config, "rename", str(bad)]) == 2
    rename_err = capsys.readouterr().err
    assert "could not be parsed" in rename_err
    assert "Traceback" not in rename_err
    (rename_note,) = [line for line in rename_err.splitlines() if line.strip()]

    assert cli_mod.main(["-c", config, "revise", str(bad)]) == 2
    revise_err = capsys.readouterr().err
    assert "Traceback" not in revise_err
    lines = [line for line in revise_err.splitlines() if line.strip()]
    assert lines == [NOTE, rename_note]  # the alias line, then the same refusal
