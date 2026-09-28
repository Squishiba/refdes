"""A confidently-misspelled field name is a build error, not a warning.

`in-prog-logs/user-sim-release-gate-run1.md`, finding **F3**. The exact repro:

    - id: CMP-003
      title: A part
      partnum: TPS123          # meant part_number

Before the fix that printed

    WARNING items/bad3.yaml:3 [CMP-003] — unknown field 'partnum' on component.
            Did you mean 'part_number'?
    3 items, 0 errors, 1 warnings      [exit=0]

The did-you-mean was the good part and is kept. What changed is the severity:
`part_number` is the field that feeds the parts index, so a green build on that
input means the part silently dropped out of the one report the field exists to
feed, with no error anywhere to explain where it went. A key that is close to
exactly one declared field has no reading other than "typo", and the loader
already said so for a misspelled *link* verb (`sattisfies:`) on the reasoning
that a silently-dropped thing must fail the build. This makes the field case
agree with the link case.

The lenient half is deliberately untouched and pinned here: a key close to
*nothing* has no typo interpretation -- forward-compat, a future schema version,
deliberate extra metadata -- so it stays a warning with its wording and its
`_suggest` hint exactly as they were. That is the same posture
`serve.filters.parse_filters` takes toward an unrecognized query parameter.
The difflib cutoff (0.6) is unchanged, and so is branch 1: a link-verb typo
still reports as a link (`did you mean the link 'satisfies'?`), which
`test_a_link_verb_typo_still_reports_as_a_link` pins so a later sweep at field
names cannot quietly re-point it at a field.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import build as build_mod
from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes import parse
from refdes.schema import load_project

# The bundled standard, no overlay: F3's repro is a stock `component` on
# hardware@3, and `part_number` is the standard's own field.
HARDWARE3 = """\
site: { title: "Scalar typo", out: _site }
standard: { base: hardware, version: 3, presets: [] }
"""

PARTNUM_TYPO = (
    "defaults:\n"
    "  type: component\n"
    "  prefix: CMP\n"
    "\n"
    "items:\n"
    "  - id: CMP-003\n"
    "    title: A part\n"
    "    partnum: TPS123\n"
)

PART_NUMBER_CORRECT = (
    "defaults:\n"
    "  type: component\n"
    "  prefix: CMP\n"
    "\n"
    "items:\n"
    "  - id: CMP-003\n"
    "    title: A part\n"
    "    part_number: TPS123\n"
)

# Close to nothing in the schema: no field, link verb, or reserved key within
# the 0.6 cutoff, so there is no typo to correct and nothing to error about.
NOVEL_FIELD = (
    "defaults:\n"
    "  type: component\n"
    "  prefix: CMP\n"
    "\n"
    "items:\n"
    "  - id: CMP-004\n"
    "    title: A part with metadata the schema has never heard of\n"
    "    thermal_model: yes\n"
)

# A suggestion exists, but it points at `board` -- an overridable reserved key,
# not a declared field of the type -- so the confident-match rule does not
# apply and the warning, hint and all, is what the author gets.
BOARD_TYPO = (
    "defaults:\n"
    "  type: component\n"
    "  prefix: CMP\n"
    "\n"
    "items:\n"
    "  - id: CMP-005\n"
    "    title: A part with a misspelled board key\n"
    "    boardd: main\n"
)

LINK_VERB_TYPO = (
    "defaults:\n"
    "  type: component\n"
    "  prefix: CMP\n"
    "\n"
    "items:\n"
    "  - id: CMP-006\n"
    "    title: A part with a misspelled link verb\n"
    "    sattisfies: REQ-001\n"
)


def _project(tmp_path, *files: tuple[str, str]):
    write_project_config(tmp_path, HARDWARE3)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files:
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def _loaded(tmp_path, *files: tuple[str, str]):
    project = load_project(
        config_path=str(_project(tmp_path, *files) / "refdes-project.yaml")
    )
    parse.load_items(project)
    return project


def _check(root) -> int:
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])


def _build(root) -> int:
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), "build"])


def _unknown_field(diags):
    return [d for d in diags if "unknown field" in d.message]


# -------------------------------------------------------------- the exact repro


def test_confident_scalar_field_typo_is_a_build_error(tmp_path):
    """F3 verbatim. Before the fix this was one warning and zero errors."""
    project = _loaded(tmp_path, ("bad3.yaml", PARTNUM_TYPO))

    errors = [d for d in project.errors if "unknown field 'partnum'" in d.message]
    assert len(errors) == 1
    assert errors[0].item_id == "CMP-003"
    assert errors[0].file == "items/bad3.yaml"
    # Names the correction, in the same voice as the link-verb error beside it.
    assert "did you mean the field 'part_number'?" in errors[0].message
    assert "A misspelled field name silently drops it instead of erroring." in (
        errors[0].message
    )
    assert not _unknown_field(project.warnings)


def test_check_exits_1_on_a_scalar_field_typo(tmp_path, capsys):
    """The gate a newcomer actually runs: red, with the typo and the fix both
    named. Before the fix this printed `0 errors` and exited 0."""
    root = _project(tmp_path, ("bad3.yaml", PARTNUM_TYPO))
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "items/bad3.yaml:6" in err
    assert "CMP-003" in err
    assert "unknown field 'partnum' on component" in err
    assert "did you mean the field 'part_number'?" in err


def test_build_exits_1_on_a_scalar_field_typo(tmp_path):
    """`build` is the other half: the site is not silently written around a
    field that went missing."""
    root = _project(tmp_path, ("bad3.yaml", PARTNUM_TYPO))
    assert _build(root) == 1


def test_the_corrected_spelling_builds_green(tmp_path):
    """The other half of the pair, and the reason the error is a good one: the
    same item spelled the way the standard declares it has no diagnostics."""
    root = _project(tmp_path, ("cmp.yaml", PART_NUMBER_CORRECT))
    assert _check(root) == 0
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    assert not _unknown_field(project.warnings)
    assert not _unknown_field(project.errors)
    assert project.item_by_id("CMP-003").fields["part_number"] == "TPS123"


def test_the_typo_value_is_still_loaded_parity_with_the_link_branch(tmp_path):
    """The value stays under the key as authored, exactly as the link-verb
    error branch does it: the build is red either way, and a red build that
    also threw the author's text away is harder to repair than one that kept
    it. Parity here is the point -- two unknown-key error paths that disagree
    about whether your text survives would be the F2 disease again."""
    project = _loaded(tmp_path, ("bad3.yaml", PARTNUM_TYPO))
    assert project.item_by_id("CMP-003").fields["partnum"] == "TPS123"


def test_the_typoed_part_is_absent_from_the_parts_index(tmp_path):
    """What the warning used to cost, stated as a fact rather than a claim:
    the part is simply not in the report `part_number` exists to feed. The
    build is red now, so nobody reads this index by accident."""
    project = _loaded(tmp_path, ("bad3.yaml", PARTNUM_TYPO))
    build_mod.build(project)
    parts = citations_mod.by_part_number(project)
    assert "TPS123" not in parts
    assert "CMP-003" not in [c.id for entry in parts.values() for c in entry.components]


# ------------------------------------------------- the lenient half, unchanged


def test_a_field_with_no_close_match_is_still_only_a_warning(tmp_path, capsys):
    """Genuinely novel metadata: no typo interpretation, so no error. Wording
    pinned verbatim -- this branch did not change, and a project adding a
    field ahead of the schema that declares it must keep building."""
    root = _project(tmp_path, ("novel.yaml", NOVEL_FIELD))
    assert _check(root) == 0

    out = capsys.readouterr()
    assert "unknown field 'thermal_model' on component." in out.err + out.out

    project = _loaded(tmp_path, ("novel.yaml", NOVEL_FIELD))
    warnings = _unknown_field(project.warnings)
    assert len(warnings) == 1
    assert warnings[0].message == "unknown field 'thermal_model' on component."
    assert not _unknown_field(project.errors)


def test_a_hint_pointing_at_a_non_field_stays_a_warning(tmp_path):
    """A suggestion alone is not a confident *field* match. `boardd` is close
    to `board`, which is an overridable reserved key rather than a declared
    field of `component`, so the severity stays a warning and the `_suggest`
    hint keeps its exact existing text."""
    project = _loaded(tmp_path, ("board.yaml", BOARD_TYPO))
    warnings = _unknown_field(project.warnings)
    assert len(warnings) == 1
    assert warnings[0].message == "unknown field 'boardd' on component. Did you mean 'board'?"
    assert not _unknown_field(project.errors)


# ------------------------------------------------- branch 1, unchanged by this


def test_a_link_verb_typo_still_reports_as_a_link(tmp_path):
    """The link-verb branch is untouched: it still errors, and it still names
    what it found as a *link*, not as a field. Pinned so a later change to the
    field-name match cannot swallow it."""
    project = _loaded(tmp_path, ("link.yaml", LINK_VERB_TYPO))
    errors = [d for d in project.errors if "unknown field 'sattisfies'" in d.message]
    assert len(errors) == 1
    assert "did you mean the link 'satisfies'?" in errors[0].message
    assert "the field" not in errors[0].message
