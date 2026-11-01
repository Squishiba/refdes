"""P13 (docs/design/vocabulary-review.md §3.3), landed the way P14 prescribes for
a vague name: `refdes index` keeps its name, and its help text and first doc line
say what it is for and what it puts on stdout. The old help -- "print items.json
to stdout without rendering the site" -- named an artifact and a negation, and
told a reader nothing about who the command is for.

The keys the help now names are named here as well *and* checked against a
payload the tool actually produced, because a help text that lists keys from
memory is precisely the quiet failure this proposal exists to prevent. No
behaviour is asserted beyond that: P13 changed none.
"""

from __future__ import annotations

import json
import re

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod

_HYPHEN_WRAP = re.compile(r"-\s*\n\s*")

SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
)

# What a project with no boards:/workspaces: registry, no threads and no
# captured-history store still gets on every run: the unconditional keys of
# render.items_json().
ALWAYS = ("title", "version", "coverage", "types", "items", "next_ids", "diagnostics")


def _project(root) -> str:
    write_project_config(root, SCHEMA)
    (root / "items").mkdir()
    (root / "items" / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        '  - id: BND-001\n    text: Board power density\n    limit: "<= 0.15 W/in^2"\n',
        encoding="utf-8",
    )
    return str(root / "refdes-project.yaml")


def _index_help(capsys) -> str:
    with pytest.raises(SystemExit):
        cli_mod.main(["index", "--help"])
    # argparse re-wraps help to the terminal width (COLUMNS) and may break
    # inside a hyphenated word; rejoin those breaks and collapse whitespace
    # runs so the pins below are width independent.
    text = _HYPHEN_WRAP.sub("-", capsys.readouterr().out)
    return " ".join(text.split())


def test_index_help_says_who_the_command_is_for(capsys):
    """The thing the old sentence could not answer: why this exists at all."""
    help_text = _index_help(capsys)
    assert "machine-readable" in help_text
    assert "editor tooling" in help_text


def test_index_help_names_the_payload_it_prints(capsys):
    help_text = _index_help(capsys)
    for key in ALWAYS:
        assert key in help_text
    # The conditional keys are named as conditional, which is the only honest
    # way to name them: a plain project's payload does not carry them.
    assert "when the project declares those registries" in help_text


def test_index_help_no_longer_says_only_that_it_prints_items_json(capsys):
    """The old wording pinned by its own words, so it cannot come back by
    paraphrase: an artifact name plus a negation is not a description."""
    assert "print items.json to stdout without rendering the site" not in _index_help(capsys)


def test_the_named_keys_are_the_ones_a_real_payload_carries(tmp_path, capsys):
    """The help names keys, so the help is checked against the payload rather
    than against anyone's memory of it."""
    config = _project(tmp_path)
    capsys.readouterr()
    assert cli_mod.main(["-c", config, "index"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(ALWAYS) <= set(payload)
    assert "boards" not in payload  # this project declares no boards: registry
    assert "threads" not in payload  # and has no follows: anywhere
