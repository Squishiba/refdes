"""The generated per-type examples in docs/schema-reference.md (finding 20).

The docs page shows a filled-in instance of every standard type, injected by
`docs-site/gen_examples.py` from `scaffold.new_item_text()` -- the generator
behind `refdes new <type>`. These tests are the gate that makes the injection
honest: the page must equal live generator output, byte for byte, or the suite
fails. A stale or hand-edited example is exactly the "builds fine, shows the
wrong thing" quiet failure the finding exists to kill.
"""

from __future__ import annotations

import importlib.util
import os

import pytest
from helpers import REPO

from refdes import scaffold as scaffold_mod

GEN_PATH = os.path.join(REPO, "docs-site", "gen_examples.py")
DOC_PATH = os.path.join(REPO, "docs", "schema-reference.md")

_spec = importlib.util.spec_from_file_location("gen_examples", GEN_PATH)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _page_text() -> str:
    with open(DOC_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def pinned():
    project, standard = gen.pinned_project()
    return project, standard


def test_pin_is_the_repos_own_standard():
    """The examples track the repo's pin, not a number hard-coded in the test."""
    standard = gen.standard_pin()
    assert standard["base"] == "hardware"
    assert isinstance(standard["version"], int)


def test_injected_block_equals_live_generator_output():
    """The whole generated region must equal what the generator produces now.

    This is the anti-drift gate: hand-edit any example in the page, or let the
    pin move without regenerating, and this fails.
    """
    assert gen.extract_block(_page_text()) == gen.render_block()


def test_each_type_example_equals_new_item_text(pinned):
    """Per-type equality: the fenced example for every type in the resolved
    schema is exactly `scaffold.new_item_text()`'s live output."""
    project, _ = pinned
    block = gen.extract_block(_page_text())
    assert project.types, "resolved schema has no types to check"
    for type_name, spec in project.types.items():
        expected = scaffold_mod.new_item_text(type_name, spec) + "```"
        assert expected in block, f"example for {type_name!r} diverged from generator"


def test_examples_are_labelled_with_the_standard_version(pinned):
    _, standard = pinned
    label = f"{standard['base']}@{standard['version']}"
    block = gen.extract_block(_page_text())
    assert label in block
    for type_name in pinned[0].types:
        assert f"#### `{type_name}` — {label}" in block


def test_check_mode_accepts_the_committed_page():
    assert gen.main(["--check"]) == 0


def test_check_mode_fails_a_hand_edited_example():
    """The gate itself, proven: flip one character inside a generated example
    and the check must report the page as stale."""
    page = _page_text()
    tampered = page.replace("type: requirement\n", "type: requirementX\n", 1)
    assert tampered != page, "fixture text vanished; nothing was tampered with"
    assert not gen.is_current(tampered)
