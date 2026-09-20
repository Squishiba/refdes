"""Status/link agreement warnings (vocabulary review P11).

`supersedes`/`superseded` and `selects`/`selected` store the same fact twice,
and either half can be the stale one. These cover both directions of both
pairs, the silence when the two halves agree, and the guards that keep the
check quiet in a vocabulary that does not carry both halves.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config
from helpers import REPO, _build_at

from refdes import build as build_mod
from refdes import parse
from refdes import schema as schema_mod

# A miniature of the two halves of hardware's vocabulary: a decision that can
# supersede a decision and select a component, and the two statuses those
# links assert on their targets. Deliberately bespoke -- the check is about
# the shape, and pinning it to the bundled standard would let a standard bump
# silently change what these tests prove.
STATUS_LINK_SCHEMA = """\
site: {title: "Status Links", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  supersedes: { inverse: superseded_by, label: "Supersedes" }
  selects:    { inverse: selected_by,   label: "Selects" }
types:
  decision:
    prefix: DEC
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [proposed, accepted, superseded], default: accepted, on_change: invalidate }
    links:
      supersedes: [decision]
      selects: [component]
    body: { on_change: invalidate }
  component:
    prefix: CMP
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [candidate, selected, obsolete], default: candidate, on_change: invalidate }
    satisfying_statuses: [selected]
    links: {}
    body: { on_change: invalidate }
"""


def _write(root, name, text):
    (root / "items" / name).write_text(text, encoding="utf-8")


@pytest.fixture
def status_project(tmp_path):
    write_project_config(tmp_path, STATUS_LINK_SCHEMA)
    (tmp_path / "items").mkdir()
    _write(
        tmp_path,
        "dec-001.md",
        "---\nid: DEC-001\ntype: decision\ntitle: The newer call.\n"
        "status: accepted\n---\n",
    )
    _write(
        tmp_path,
        "dec-002.md",
        "---\nid: DEC-002\ntype: decision\ntitle: The older call.\n"
        "status: accepted\n---\n",
    )
    _write(
        tmp_path,
        "cmp-001.md",
        "---\nid: CMP-001\ntype: component\ntitle: The chosen part.\n"
        "status: candidate\n---\n",
    )
    return tmp_path


def _warned(project, needle, item_id=None):
    """The messages of warnings that contain `needle` (and belong to `item_id`,
    when given) -- empty list means the check stayed quiet."""
    return [
        d.message
        for d in project.warnings
        if needle in d.message and (item_id is None or d.item_id == item_id)
    ]


# ---------------------------------------------------------- supersedes/superseded


def test_supersedes_link_without_the_status_warns(status_project):
    _write(
        status_project,
        "dec-003.md",
        "---\nid: DEC-003\ntype: decision\ntitle: Replaces DEC-002.\n"
        "status: accepted\nsupersedes: [DEC-002]\n---\n",
    )
    project = _build_at(status_project)
    found = _warned(project, "supersedes DEC-002", item_id="DEC-003")
    assert len(found) == 1, [str(d) for d in project.warnings]
    # Names the target, the status it has, the one it should have, and both fixes.
    assert "'accepted'" in found[0]
    assert "'superseded'" in found[0]
    assert "not something the link does" in found[0] or "does not move a status" in found[0]
    assert "remove the supersedes link" in found[0]
    # A disagreement is a warning, never a build failure.
    assert not project.errors


def test_superseded_status_without_a_link_warns(status_project):
    _write(
        status_project,
        "dec-002.md",
        "---\nid: DEC-002\ntype: decision\ntitle: The older call.\n"
        "status: superseded\n---\n",
    )
    project = _build_at(status_project)
    found = _warned(project, "nothing supersedes it", item_id="DEC-002")
    assert len(found) == 1, [str(d) for d in project.warnings]
    assert "'superseded'" in found[0]
    assert "supersedes:" in found[0]
    assert not project.errors


def test_supersedes_and_superseded_agree_is_silent(status_project):
    _write(
        status_project,
        "dec-003.md",
        "---\nid: DEC-003\ntype: decision\ntitle: Replaces DEC-002.\n"
        "status: accepted\nsupersedes: [DEC-002]\n---\n",
    )
    _write(
        status_project,
        "dec-002.md",
        "---\nid: DEC-002\ntype: decision\ntitle: The older call.\n"
        "status: superseded\n---\n",
    )
    project = _build_at(status_project)
    assert not project.warnings, [str(d) for d in project.warnings]


# -------------------------------------------------------------- selects/selected


def test_selects_link_without_the_status_warns(status_project):
    _write(
        status_project,
        "dec-004.md",
        "---\nid: DEC-004\ntype: decision\ntitle: Picks CMP-001.\n"
        "status: accepted\nselects: [CMP-001]\n---\n",
    )
    project = _build_at(status_project)
    found = _warned(project, "selects CMP-001", item_id="DEC-004")
    assert len(found) == 1, [str(d) for d in project.warnings]
    assert "'candidate'" in found[0]
    assert "'selected'" in found[0]
    assert "remove the selects link" in found[0]
    assert not project.errors


def test_selected_status_without_a_link_warns(status_project):
    _write(
        status_project,
        "cmp-001.md",
        "---\nid: CMP-001\ntype: component\ntitle: The chosen part.\n"
        "status: selected\n---\n",
    )
    project = _build_at(status_project)
    found = _warned(project, "nothing selects it", item_id="CMP-001")
    assert len(found) == 1, [str(d) for d in project.warnings]
    assert "'selected'" in found[0]
    assert "selects:" in found[0]
    assert not project.errors


def test_selects_and_selected_agree_is_silent(status_project):
    _write(
        status_project,
        "dec-004.md",
        "---\nid: DEC-004\ntype: decision\ntitle: Picks CMP-001.\n"
        "status: accepted\nselects: [CMP-001]\n---\n",
    )
    _write(
        status_project,
        "cmp-001.md",
        "---\nid: CMP-001\ntype: component\ntitle: The chosen part.\n"
        "status: selected\n---\n",
    )
    project = _build_at(status_project)
    assert not project.warnings, [str(d) for d in project.warnings]


# ---------------------------------------------------------------------- the edges


def test_several_stale_targets_warn_once_from_the_declaring_item(status_project):
    """One item superseding two not-yet-superseded ones is one authored claim
    that needs one fix pass, not a warning per target."""
    _write(
        status_project,
        "dec-004.md",
        "---\nid: DEC-004\ntype: decision\ntitle: Replaces two.\n"
        "status: accepted\nsupersedes: [DEC-001, DEC-002]\n---\n",
    )
    project = _build_at(status_project)
    found = _warned(project, "whose status is not 'superseded'", item_id="DEC-004")
    assert len(found) == 1, [str(d) for d in project.warnings]
    assert "DEC-001" in found[0] and "DEC-002" in found[0]


def test_a_type_without_the_status_choice_never_triggers(status_project):
    """`component` has no `superseded` in its enum, so pointing `supersedes:`
    at one is a target-type error to be reported by resolve_links, never a
    status disagreement. Here the reverse guard: a status value the target's
    type does not offer cannot be 'missing'."""
    schema = STATUS_LINK_SCHEMA.replace(
        "status: { type: enum, choices: [candidate, selected, obsolete], default: candidate, on_change: invalidate }",
        "status: { type: enum, choices: [candidate, obsolete], default: candidate, on_change: invalidate }",
    ).replace("satisfying_statuses: [selected]", "")
    write_project_config(status_project, schema)
    _write(
        status_project,
        "dec-004.md",
        "---\nid: DEC-004\ntype: decision\ntitle: Picks CMP-001.\n"
        "status: accepted\nselects: [CMP-001]\n---\n",
    )
    project = _build_at(status_project)
    # `selected` is not even a legal value for this component now, so neither
    # direction has anything to say about it.
    assert not _warned(project, "selects CMP-001"), [str(d) for d in project.warnings]


def test_a_vocabulary_without_the_verb_is_silent(tmp_path):
    """A project that never declares `supersedes`/`selects` cannot disagree
    with itself: the statuses may be set with nothing behind them, and that is
    the author's whole vocabulary, not a contradiction."""
    schema = STATUS_LINK_SCHEMA.replace("  supersedes: { inverse: superseded_by, label: \"Supersedes\" }\n", "")
    schema = schema.replace("  selects:    { inverse: selected_by,   label: \"Selects\" }\n", "")
    schema = schema.replace("    links:\n      supersedes: [decision]\n      selects: [component]\n", "    links: {}\n")
    write_project_config(tmp_path, schema)
    (tmp_path / "items").mkdir()
    _write(
        tmp_path,
        "dec-002.md",
        "---\nid: DEC-002\ntype: decision\ntitle: Marked superseded, nothing more.\n"
        "status: superseded\n---\n",
    )
    _write(
        tmp_path,
        "cmp-001.md",
        "---\nid: CMP-001\ntype: component\ntitle: Marked selected, nothing more.\n"
        "status: selected\n---\n",
    )
    project = _build_at(tmp_path)
    assert not project.errors, [str(d) for d in project.errors]
    assert not project.warnings, [str(d) for d in project.warnings]


def test_the_bundled_hardware_standard_carries_both_pairs(tmp_path):
    """The check is wired into a real build of the shipped vocabulary, not
    just the miniature above: hardware@3 declares `supersedes`/`selects` and
    the `superseded`/`selected` statuses, so a project on it gets the warning."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 3, presets: [] }\n",
    )
    (tmp_path / "items").mkdir()
    _write(
        tmp_path,
        "cmp-001.md",
        "---\nid: CMP-001\ntype: component\ntitle: A part nobody selected.\n"
        "status: selected\n---\n",
    )
    project = _build_at(tmp_path)
    found = _warned(project, "nothing selects it", item_id="CMP-001")
    assert len(found) == 1, [str(d) for d in project.warnings]


def test_the_repo_own_project_agrees():
    """This repo's own project builds with no status/link disagreement -- the
    warning is live on real content, and real content is clean."""
    project = schema_mod.load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    stale = [
        d.message
        for d in project.warnings
        if "nothing selects it" in d.message or "nothing supersedes it" in d.message
        or "not something the link does" in d.message
        or "does not move a status" in d.message
    ]
    assert not stale, stale
