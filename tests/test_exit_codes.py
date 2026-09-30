"""F6: the exit code of every "the name you gave does not resolve" case.

`docs/cli-reference.md` states the convention once, at the top -- `0` success,
`1` errors found, `2` configuration error -- and then commits each command to a
specific code for a name that does not resolve. Those per-command promises are
what this file pins, so none of them can drift without a test failing:

- exit `2`: `history capture` and `history redact` on an unknown target;
  `history redact` without `--confirm`; `standard add-preset` /
  `remove-preset` on an unusable name; `init` on a base standard or preset that
  does not exist; `revision` on a name that is not a usable name
  (`docs/design/lifecycle.md`, "an invalid name").
- exit `1`: `new` / `schema --graph` on an undeclared type; `former-ids propose
  --baseline` on a baseline that was never stamped; `keys restore` on a target
  it refuses.
- exit `0`: `history redact` on a target that resolves but has nothing captured;
  `history migrate-seals` with no legacy seal files.

The two cases the report (in-prog-logs/user-sim-release-gate-run2.md, F6) put
side by side are the first and last-but-one of those families: `fetch --item
NOPE-1` is `1`, `history capture NOPE-001` is `2`. Both are asserted here with
their exact code, because the report's complaint -- a script cannot predict
which -- is answered by pinning the split, not by changing either side of it.
`fetch`'s own code was undocumented before F6 and is documented now, in the
`refdes fetch` section, so this is the test that keeps that documentation true.

The last two tests pin behaviour the docs do NOT promise and that the report did
not raise: `check --board` on an undeclared board is `1` because it reports
through the ordinary diagnostic channel, and `ls --board` on one is `0`. They
are here as the current contract, flagged in
in-prog-logs/exit-code-consistency-f6.md, not as a claim that they are right.
"""

from __future__ import annotations

import pytest

from conftest import write_project_config

from refdes import cli as cli_mod

PROJECT = """\
site: { title: F6 Exit Codes, out: site_out_f6x }
id: { width: 3, ledger: .refdes/ids.yaml }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

STANDARD_PROJECT = """\
site: { title: F6 Exit Codes Standard, out: site_out_f6s }
id: { width: 3, ledger: .refdes/ids.yaml }
standard: { base: hardware, version: 3 }
"""

ITEMS = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First note.\n"
    "  - id: LOG-002\n    summary: Second note.\n"
)


@pytest.fixture
def config(tmp_path):
    """A loaded project, warmed by a passing `check` so key minting and schema
    regeneration are not what a later command in the test trips over."""
    path = write_project_config(tmp_path, PROJECT)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "log.yaml").write_text(ITEMS, encoding="utf-8")
    assert cli_mod.main(["-c", str(path), "check"]) == 0
    return str(path)


def _run(config, *argv):
    return cli_mod.main(["-c", config, *argv])


# ------------------------------------------------------------------- fetch: 1


def test_fetch_unknown_item_exits_one(config, capsys):
    """`fetch --item` naming no item: `1`, nothing pinned. Documented in the
    `refdes fetch` section; the case F6 opens with."""
    assert _run(config, "fetch", "--item", "NOPE-1") == 1
    assert "no item 'NOPE-1' in this project" in capsys.readouterr().err


def test_fetch_item_without_citations_exits_one(config, capsys):
    """The item exists and still has nothing to fetch: same refusal, same code."""
    assert _run(config, "fetch", "--item", "LOG-001") == 1
    assert "declares no citations" in capsys.readouterr().err


def test_fetch_unknown_path_exits_one(config, capsys):
    """`--path` no citation in the project cites: same refusal, same code."""
    assert _run(config, "fetch", "--path", "nosuch.pdf") == 1
    assert "no citation in this project cites" in capsys.readouterr().err


# --------------------------------------------------------------- history: 2


def test_history_capture_unknown_target_exits_two(config, capsys):
    """Documented verbatim -- `refdes history capture NOPE-999` is the doc's own
    example, "refused with exit 2 and nothing written". This is the half of F6
    the report wanted moved to `1`; it stays `2` because the docs say so."""
    assert _run(config, "history", "capture", "NOPE-001") == 2
    err = capsys.readouterr().err
    assert "no item 'NOPE-001' in this project" in err


def test_history_redact_unknown_target_exits_two(config, capsys):
    """Documented: a TARGET that names no item and is not a 64-hex digest."""
    assert _run(config, "history", "redact", "NOPE-001", "--confirm") == 2
    assert "no item or history object 'NOPE-001'" in capsys.readouterr().err


def test_history_redact_without_confirm_exits_two(config, capsys):
    """Not a name-resolution case, but the same code for the same reason: the
    command refuses to run as asked."""
    assert _run(config, "history", "redact", "LOG-001") == 2
    capsys.readouterr()


# --------------------------------------------------------------- history: 0


def test_history_redact_resolved_but_nothing_captured_exits_zero(config, capsys):
    """Documented: a TARGET that resolves and has nothing captured is not an
    error -- there was simply nothing to remove."""
    assert _run(config, "history", "redact", "LOG-001", "--confirm") == 0
    capsys.readouterr()


def test_history_migrate_seals_without_seals_exits_zero(config, capsys):
    """Documented: no legacy seal files is `0`, not a failure."""
    assert _run(config, "history", "migrate-seals") == 0
    capsys.readouterr()


# ------------------------------------------------------- schema and types: 1


def test_new_unknown_type_exits_one(config, capsys):
    """Documented: `new` on a type the merged schema does not declare exits 1
    with a did-you-mean suggestion."""
    assert _run(config, "new", "nosuchtype") == 1
    assert "unknown type 'nosuchtype'" in capsys.readouterr().err


def test_schema_graph_unknown_type_exits_one(config, capsys):
    """Documented: the same mistake against `schema --graph` is also `1`."""
    assert _run(config, "schema", "--graph", "nosuchtype") == 1
    assert "unknown type 'nosuchtype'" in capsys.readouterr().err


# ------------------------------------------------------------ baselines: 1


def test_former_ids_propose_unknown_baseline_exits_one(config, capsys):
    """Documented: `--baseline` naming nothing that was ever stamped exits 1."""
    assert _run(config, "former-ids", "propose", "--baseline", "nosuchbase") == 1
    assert "no baseline named 'nosuchbase'" in capsys.readouterr().err


def test_keys_restore_unknown_target_exits_one(config, capsys):
    """Documented: a refused restoration exits 1."""
    assert _run(config, "keys", "restore", "LOG-001@zzzzzzzzzzz") == 1
    assert "refused" in capsys.readouterr().err


# ---------------------------------------------------- presets and names: 2


def test_standard_add_preset_unknown_name_exits_two(tmp_path, capsys):
    """Documented: a preset the pinned standard does not have."""
    path = write_project_config(tmp_path, STANDARD_PROJECT)
    (tmp_path / "items").mkdir()
    assert _run(str(path), "standard", "add-preset", "nosuchpreset") == 2
    err = capsys.readouterr().err
    assert "preset 'nosuchpreset' does not exist" in err


def test_standard_remove_preset_unselected_name_exits_two(tmp_path, capsys):
    """Documented: a preset that is not currently selected cannot be removed."""
    path = write_project_config(tmp_path, STANDARD_PROJECT)
    (tmp_path / "items").mkdir()
    assert _run(str(path), "standard", "remove-preset", "nosuchpreset") == 2
    assert "is not currently selected" in capsys.readouterr().err


def test_init_unknown_standard_exits_two(tmp_path, monkeypatch, capsys):
    """Documented: `init`'s name checks are configuration errors, and nothing is
    written."""
    monkeypatch.chdir(tmp_path)
    assert cli_mod.main(["init", "--standard", "nosuchstd"]) == 2
    assert "standard.base must be one of" in capsys.readouterr().err
    assert not (tmp_path / "refdes-project.yaml").exists()


def test_revision_invalid_name_exits_two(config, capsys):
    """`docs/design/lifecycle.md`: `2` is a `SchemaError`, which includes an
    invalid revision name."""
    assert _run(config, "revision", "bad name!") == 2
    assert "not a valid revision/release name" in capsys.readouterr().err


# ------------------------------------------- board filters: current, not promised


def test_check_undeclared_board_exits_one(config, capsys):
    """Undocumented. `--board` reports through `project.error()`, so it lands in
    the "errors found" count and `1` is the only code a diagnostic gets."""
    assert _run(config, "check", "--board", "nosuchboard") == 1
    assert "nosuchboard" in capsys.readouterr().err


def test_ls_undeclared_board_exits_zero(config, capsys):
    """Undocumented, and flagged in in-prog-logs/exit-code-consistency-f6.md:
    `ls` validates no filters, so a typo'd board is indistinguishable from an
    empty one. Pinned as today's contract, not as a good one."""
    assert _run(config, "ls", "--board", "nosuchboard") == 0
    assert "no items match" in capsys.readouterr().out
