"""`refdes check --help` describes append-only protection for both sealings.

Run-5 F5. The parser's description used to say, flatly:

> A seal exists only once 'build' has run over the entry, so an entry that has
> never been built has no append-only protection at all, however many clean
> runs of this command it has behind it.

That was written for a `sealing: build` log and is false for the bundled
`hardware@3` one, which is `sealing: history` (`base.yaml:298`): it is never
sealed at all, so "has never been built" describes every one of its entries
and the sentence reads as "your log has no protection". Its protection is the
snapshot `refdes history capture` writes into `.refdes/history/`, and an entry
that has never been *captured* is the one with no protection -- which is what
`docs/schema-reference.md`'s `sealing:` row and `docs/design-log.md`'s
history-backed section both say.

`build --help` was updated for this delta (`--reseal`: "A `sealing: history`
type has nothing to reseal and is left untouched"); this epilog sentence was
the one that was missed.
"""

from __future__ import annotations

import pytest

from refdes import cli as cli_mod

STALE = "so an entry that has never been built has no append-only protection at all"


def _check_help(capsys) -> str:
    with pytest.raises(SystemExit):
        cli_mod.main(["check", "--help"])
    return " ".join(capsys.readouterr().out.split())


def test_check_help_no_longer_calls_an_unbuilt_entry_unprotected(capsys):
    """The stale claim, pinned by its own words so it cannot come back by
    paraphrase. It is true of a `sealing: build` type and of nothing else, and
    the help does not qualify it."""
    assert STALE not in _check_help(capsys)


def test_check_help_names_both_sealings_and_the_history_escape(capsys):
    """What replaces it: the two ways an append-only type is protected, and
    the command that supplies the one `check` cannot."""
    help_text = _check_help(capsys)
    assert "sealing: build" in help_text
    assert "sealing: history" in help_text
    assert "refdes history capture" in help_text
