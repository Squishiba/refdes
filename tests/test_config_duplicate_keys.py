"""A key a *config* file spells twice is a configuration error, not a silent loss.

YAML resolves a repeated mapping key by keeping the last value and saying
nothing: not in the file, not in the loader, not in the build. In an item file
that is already an error (PR #130 -- see `parse._duplicate_keys`,
`parse._report_duplicate_keys`, and `tests/test_parse.py`'s "duplicate keys in a
mapping" section). In `refdes-project.yaml` and `refdes-schema.yaml` it was
still silent, and the shape that loses the most is a whole block:

    site:
      title: "First Title"
    ...
    site:
      title: "Second Title"

The first `site:` is simply gone -- no error, exit 0, and the project renders
under the title nobody remembered deleting. This file covers the same rule for
the config files, through the same detector (one `_duplicate_keys`, not two
that could disagree about what a repeat is) and the same message wording.

The message shape is the item-file one verbatim, including the line of *each*
occurrence, even though no other configuration error carries a line number:
`refdes-project.yaml: duplicate key 'site' in one mapping (lines 1 and 7) --
YAML keeps the last, so the value on line 1 is lost. ...` Config errors carry
no lines today; this one does, because a repeat is the one config problem whose
diagnosis *is* two line numbers.

Scope, checked by grepping the loader rather than assumed. Hand-authored YAML
refdes reads, and what happens to each:

| file | read by | this change |
|---|---|---|
| `refdes-project.yaml` | `schema.load_project` | refused |
| `refdes-schema.yaml` | `schema._load_schema_overlay` | refused |
| a `revise` mapping file | `revise.load_mapping` | refused |
| `refdes-project.yaml` for a preset edit | `scaffold._read_settings` | refused |

Refdes-written state under `.refdes/` is out of scope and deliberately
untouched: a repeat there is a refdes bug, not an authoring slip, and hardening
those files is a much wider question (seal hashes, baseline diffs and `audit`
all read them). Page front matter (`pages/_read_page`) is page *content*, not a
config file, and is left alone. The bundled standard
(`standards/_read_yaml`) ships with the package rather than being
hand-authored per project.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config
from helpers import COVERAGE_ITEMS, COVERAGE_SCHEMA

from refdes import scaffold
from refdes.model import SchemaError
from refdes.revise import load_mapping
from refdes.schema import PROJECT_SETTINGS_NAME, SCHEMA_NAME, load_project

# A clean baseline: one site, one id, one on_change, one standard, no overlay
# file. Every test below adds exactly one thing to this, so the only difference
# between a passing and a failing case is the repeat under test. The
# `standard:` block is here so the file reaches a full load -- a project
# declaring no types is refused, before any of this is even read.
CLEAN = """\
site:
  title: "First Title"
  out: _site
id:
  width: 3
on_change:
  default: invalidate
standard:
  base: hardware
  version: 3
  presets: []
sigfigs: 4
"""


def _write(tmp_path, settings: str, schema: str | None = None) -> str:
    """Write the two config files verbatim and return the settings path.

    Deliberately not `write_project_config`: that helper splits *one combined
    text* into the two files, which cannot express a file this change is about
    -- a repeat is by definition two spellings of a key, and the point of these
    tests is which file and which lines it names.
    """
    settings_path = tmp_path / PROJECT_SETTINGS_NAME
    settings_path.write_text(settings, encoding="utf-8")
    schema_path = tmp_path / SCHEMA_NAME
    if schema is None:
        if schema_path.is_file():
            schema_path.remove()
    else:
        schema_path.write_text(schema, encoding="utf-8")
    return str(settings_path)


def _config_error(settings_path: str) -> str:
    """The one message, as `load_project` refuses it."""
    with pytest.raises(SchemaError) as exc:
        load_project(config_path=settings_path)
    return str(exc.value)


# ------------------------------------------------------------- the top level


def test_a_second_top_level_block_is_a_configuration_error(tmp_path):
    """The reported shape, verified rather than assumed: two `site:` blocks in
    `refdes-project.yaml`. Before this change the first was silently replaced
    and the project loaded clean (see in-prog-logs/config-duplicate-keys.txt
    §1 for the run against main's code)."""
    settings = _write(tmp_path, CLEAN + '\nsite:\n  title: "Second Title"\n  out: _other\n')

    message = _config_error(settings)
    assert message.startswith(f"{PROJECT_SETTINGS_NAME}: duplicate key 'site'"), message
    # The line of *each* occurrence, the same way the item-file diagnostic
    # names them -- and both are real file lines.
    assert "(lines 1 and 14)" in message, message
    # ... and it says what the reader cannot see: which one is lost.
    assert "YAML keeps the last" in message, message
    assert "the value on line 1 is lost" in message, message
    # The remedy is this file family's, not the item-file `- key:` one.
    assert "keep the one you meant and delete the other" in message, message
    assert "'- key:'" not in message, message
    # The published page for the family, never a repo-relative path.
    assert "troubleshooting.html#items-and-fields" in message, message
    assert "docs/troubleshooting.md" not in message, message


def test_the_repeat_is_reported_before_anything_else_in_the_file(tmp_path):
    """Ordering, and it is a decision rather than an accident.

    A duplicate `site:` also means `out:` from the first block is gone. If the
    repeat were reported after the settings checks, the author could be told
    about a consequence (`_other` is not a real directory) before being told
    about the two lines that caused it. Checked by pairing a repeat with a
    *separate* mistake in the same file: the repeat is what is named.
    """
    settings = _write(
        tmp_path,
        CLEAN + '\nsite:\n  titel: A typo in its own right\n',
    )

    message = _config_error(settings)
    assert "duplicate key 'site'" in message, message
    assert "site.titel is not valid" not in message, message


def test_every_repeat_in_the_file_is_named_in_one_error(tmp_path):
    """`configcheck`'s own rule for a block with two typos: one read of an
    error, not one per `refdes check`. Two repeats, one message -- and the
    second is named rather than swallowed by the first."""
    settings = _write(tmp_path, CLEAN + "\nsigfigs: 6\non_change:\n  default: invalidate\n")

    message = _config_error(settings)
    assert "duplicate key 'sigfigs'" in message, message
    assert "Also: duplicate key 'on_change'" in message, message
    # Only the first is written out with the remedy and the page pointer; the
    # rest follow it, which is what keeps the message one readable paragraph.
    assert message.count("keep the one you meant") == 1, message


def test_a_key_written_three_times_names_every_line_once(tmp_path):
    """Same rule as the item-file diagnostic: a repeat is paired with the
    occurrence immediately before it, so three lines name 2 and 4, then 4 and
    6 -- every line accounted for exactly once, and each pair's two values are
    the two YAML actually weighed."""
    settings = _write(tmp_path, "sigfigs: 4\nsigfigs: 6\nsigfigs: 8\n")

    message = _config_error(settings)
    assert "(lines 1 and 2)" in message, message
    assert "Also: duplicate key 'sigfigs' in one mapping (lines 2 and 3)" in message, message


# ------------------------------------------------------------------- nested


def test_a_nested_duplicate_is_refused_too(tmp_path):
    """Two `sigfigs:` lines is the top-level shape; this is the same repeat one
    level down, inside `release_gate:`'s own per-rule mapping. A config check
    that only walked the file's top-level mapping would miss every repeat in a
    block, and every nested block is where the settings a project actually
    tunes live."""
    settings = _write(
        tmp_path,
        CLEAN
        + "release_gate:\n"
        + "  draft_items:\n"
        + "    release: true\n"
        + "    release: false\n",
    )

    message = _config_error(settings)
    assert "duplicate key 'release'" in message, message
    assert "(lines 15 and 16)" in message, message
    # The two values are named, so which one survived is not a guess.
    assert "'true' is dropped for 'false'" in message, message


def test_a_repeat_inside_a_named_block_is_found(tmp_path):
    """The other nested shape, and the one `configcheck` validates: two
    `title:` lines inside one `site:` block. The unknown-key/wrong-type checks
    for `site:` run on the mapping YAML handed them, which already lost the
    first title -- so without this the validator would be judging a `site:`
    the file does not contain."""
    settings = _write(
        tmp_path,
        'site:\n  title: "First"\n  title: "Second"\n  out: _site\n',
    )

    message = _config_error(settings)
    assert "duplicate key 'title'" in message, message
    assert "(lines 2 and 3)" in message, message


def test_a_one_line_flow_mapping_names_the_line_once(tmp_path):
    """`id: {width: 3, width: 4}` -- both occurrences on one line, so
    "(lines 1 and 1)" would read as a bug in the diagnostic. Same wording as
    the item-file family."""
    settings = _write(tmp_path, "id: {width: 3, width: 4}\n")

    message = _config_error(settings)
    assert "duplicate key 'width'" in message, message
    assert "twice on line 1" in message, message
    assert "(lines 1 and 1)" not in message, message


def test_a_repeat_that_agrees_with_itself_claims_no_loss(tmp_path):
    """Two identical lines lose nothing, and saying otherwise would be the one
    wrong thing in a message whose job is to be believed. It is still refused:
    one of the two lines was not meant to be there."""
    settings = _write(tmp_path, "sigfigs: 4\nsigfigs: 4\n")

    message = _config_error(settings)
    assert "both lines read '4', so nothing is lost here" in message, message


def test_a_merge_key_is_not_a_repeat(tmp_path):
    """`<<:` is not an author spelling a key twice. The detector reads the node
    before `flatten_mapping` folds a merge in, so a mapping that merges an
    anchor alongside its own keys is legal -- verified here because getting it
    wrong would refuse a shape that works. The shape is one that is legal on
    its own terms too: both `fields:` blocks spell legal keys."""
    settings = _write(
        tmp_path,
        CLEAN,
        schema=(
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            "    fields: &shared\n"
            "      title: {type: text}\n"
            "  memo:\n"
            "    prefix: MEM\n"
            "    fields:\n"
            "      <<: *shared\n"
            "      subject: {type: text}\n"
        ),
    )

    project = load_project(config_path=settings)
    assert "subject" in project.types["memo"].fields
    assert "title" in project.types["memo"].fields


# ------------------------------------------------- the schema overlay file


def test_a_duplicate_in_the_schema_overlay_is_refused(tmp_path):
    """`refdes-schema.yaml` is the other hand-authored config file, and its
    repeat is the expensive kind: a `types:` block declared twice means every
    field the first block declared is gone from the merged schema, so every
    item using one of them reports a missing field instead."""
    settings = _write(
        tmp_path,
        CLEAN,
        schema=(
            "types:\n"
            "  requirement:\n"
            "    prefix: REQ\n"
            "  requirement:\n"
            "    prefix: OTHER\n"
        ),
    )

    message = _config_error(settings)
    assert message.startswith(f"{SCHEMA_NAME}: duplicate key 'requirement'"), message
    assert "(lines 2 and 4)" in message, message


def test_a_duplicate_nested_in_the_overlay_is_refused(tmp_path):
    """Inside a type's own `fields:`, which is where an overlay spends most of
    its lines: two `source:` lines means one field spec silently replaces the
    other, and the type still validates."""
    settings = _write(
        tmp_path,
        CLEAN,
        schema=(
            "types:\n"
            "  requirement:\n"
            "    prefix: REQ\n"
            "    fields:\n"
            "      source: {type: text, doc: first}\n"
            "      source: {type: text, doc: second}\n"
        ),
    )

    message = _config_error(settings)
    assert message.startswith(f"{SCHEMA_NAME}: duplicate key 'source'"), message
    assert "(lines 5 and 6)" in message, message


def test_the_overlay_is_checked_before_its_own_key_check(tmp_path):
    """Ordering again, and here it decides *which* error the author reads. A
    repeat plus a misplaced setting is two problems; the repeat is the cause of
    any downstream surprise, so it is named first."""
    settings = _write(
        tmp_path,
        CLEAN,
        schema="types:\n  note: {prefix: NTE}\ntypes: {other: {prefix: OTH}}\n",
    )

    message = _config_error(settings)
    assert "duplicate key 'types'" in message, message
    assert "not a schema key" not in message, message


# ------------------------------------------------------- the other readers


def test_a_revise_mapping_file_with_a_duplicate_is_refused(tmp_path):
    """`revise`'s mapping file is hand-authored YAML too, and a repeat there
    drops one of the two renames the file asked for -- then applies the other
    without a word, which is worse than dropping both: the rename the author
    wanted happens and the one they did not."""
    mapping = tmp_path / "rename.yaml"
    mapping.write_text(
        "types:\n  requirement: REQ\nprefixes:\n  REQ: REQ-PWR\n  REQ: OTHER\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaError) as exc:
        load_mapping(str(mapping))
    message = str(exc.value)
    assert "duplicate key 'REQ'" in message, message
    assert "(lines 4 and 5)" in message, message
    assert "'REQ-PWR' is dropped for 'OTHER'" in message, message


def test_add_preset_refuses_a_config_it_could_not_read(tmp_path):
    """The one path that *writes* the config, and so the one where a repeat is
    most expensive: `add_preset` appends to the text of a `presets:` span, so a
    file with two `presets:` lines would get the preset appended to the first
    while the loader resolves the second. `add_preset` does not load the
    project, so `load_project`'s check does not cover it -- checked here
    because the write is what makes it matter."""
    config_path = tmp_path / PROJECT_SETTINGS_NAME
    config_path.write_text(
        "site: {title: T, out: _site}\nstandard:\n  base: hardware\n  version: 3\n"
        "  presets: []\n  presets: [design-debate]\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaError) as exc:
        scaffold.add_preset(str(tmp_path), "design-debate")
    message = str(exc.value)
    assert "duplicate key 'presets'" in message, message
    # And nothing was written: the file is byte-identical to what was there.
    assert "  presets: [design-debate]\n  presets: [design-debate]" not in (
        config_path.read_text(encoding="utf-8")
    )


# -------------------------------------------------------------- the controls


def test_a_clean_config_loads_exactly_as_before(tmp_path):
    """The control that matters most: a config with no repeat in any mapping
    must be untouched by all of this -- same title, same width, and the
    `__line__` bookkeeping the duplicate-collecting loader must NOT add (it
    would surface as an unknown setting in every block)."""
    settings = _write(tmp_path, CLEAN)

    project = load_project(config_path=settings)
    assert project.title == "First Title"
    assert project.id_width == 3
    # The loader reports no repeats for a clean file.
    assert project.duplicate_key_files == set()


def test_a_clean_overlay_still_loads(tmp_path):
    """The other control: an overlay with several types, links and sets and no
    repeat anywhere, which is what most projects' looks like."""
    settings = _write(
        tmp_path,
        CLEAN,
        schema=(
            "types:\n"
            "  requirement:\n"
            "    prefix: REQ\n"
            "    fields:\n"
            "      source: {type: text}\n"
            "  decision:\n"
            "    prefix: DEC\n"
            "link_types:\n"
            "  satisfies: {inverse: satisfied_by}\n"
            "sets:\n"
            "  common: {fields: {source: {type: text}}}\n"
        ),
    )

    project = load_project(config_path=settings)
    assert {"requirement", "decision"} <= set(project.types)
    assert project.link_types["satisfies"].inverse == "satisfied_by"


def test_this_repositorys_own_config_files_load(tmp_path):
    """The acceptance test for the whole file, and the real one: this repo's
    own two configs, loaded verbatim. A config that was right yesterday has to
    load today, or the check has eaten a legal shape."""
    import os

    repo = os.path.join(os.path.dirname(__file__), "..")
    project = load_project(config_path=os.path.join(repo, PROJECT_SETTINGS_NAME))
    assert project.title.startswith("Example Board")
    assert project.standard_base == "hardware"
    assert project.standard_version == 3


def test_the_coverage_fixture_config_has_no_repeat(tmp_path):
    """The fixture most of the suite builds a project from, split into the two
    real files. If this one grew a repeat the suite would break everywhere, so
    it is worth a test that says it has not."""
    settings_path = write_project_config(tmp_path, COVERAGE_SCHEMA)

    project = load_project(config_path=str(settings_path))
    assert project.title == "Coverage Test"
    assert "requirement" in project.types


def test_the_coverage_fixture_items_still_load_unchanged(tmp_path):
    """The item side of the fixture, as a control that sharing the detector
    between item files and config files changed nothing for item files."""
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in COVERAGE_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")

    from refdes.parse import load_items

    project = load_project(config_path=str(tmp_path / PROJECT_SETTINGS_NAME))
    load_items(project)
    assert project.errors == []
    assert sorted(project.items_by_id) == [
        "DEC-A-001", "DEC-B-001", "REQ-A-001", "REQ-B-001",
    ]


def test_a_syntax_error_still_wins_over_a_duplicate(tmp_path):
    """Checked rather than assumed: PyYAML fails before it reaches the later
    mappings, so a file with both a syntax error and a repeat reports only the
    syntax error. The repeat is still there -- fix the syntax and it is
    reported next. Same behaviour as the item-file family, and the same
    reason."""
    settings = _write(tmp_path, "site: {title: T, out: _site}\nsigfigs: [4\nsigfigs: 6\n")

    with pytest.raises(Exception) as exc:
        load_project(config_path=settings)
    assert not isinstance(exc.value, SchemaError), exc.value