"""Link edits through the write service (docs/design/browser-editor.md,
"Slice 2 -- structured links").

The patcher proves the bytes; this module pins what the *service* decides:
the verb must be one the item's type declares, the target must exist and be
of a type the schema allows for that verb, and what lands on disk is always
the `DISPLAY-ID@key` composite `links.composite_for` spells -- never a bare
id, never a composite the browser invented. Sabotage-shaped like the rest of
the write-path tests: every refusal is asserted as a result *and* as a
byte-identical tree.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import build as build_mod
from refdes import keys as keys_mod
from refdes import links as links_mod
from refdes.patcher import AddLink, RemoveLink
from refdes.serve import edit as edit_mod
from refdes.serve.edit import Applied, Conflict, EditRequest, Refused

SCHEMA = """\
site:
  title: "Link edit test"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
  verifies: { inverse: verified_by, label: Verifies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
  test:
    prefix: TST
    fields:
      title: { type: text, required: true }
    links:
      verifies: [requirement]
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

K_REQ1 = keys_mod.mint()
K_REQ2 = keys_mod.mint()

# REQ-003 deliberately carries no key: it stands in for an imported item or
# one whose key was never minted -- the null-artifact-key case the design
# says must refuse rather than write a bare id.
REQS = f"""\
# keep me: the patcher must not eat this
defaults: {{ type: requirement, board: board-a }}
items:
  - id: REQ-001
    key: {K_REQ1}
    text: The rail shall supply 3.3 V.
  - id: REQ-002
    key: {K_REQ2}
    text: The rail shall survive 5 V for a second.
  - id: REQ-003
    text: Keyless on purpose.
"""

DECS = f"""\
defaults: {{ type: decision, board: board-a }}
items:
  - id: DEC-001
    title: Use the buck regulator.
    satisfies: [REQ-001@{K_REQ1}, REQ-009@zzzzzzzzzzz]
"""

LOG = """\
defaults: { type: log, board: board-a }
items:
  - id: LOG-001
    summary: Started the rail work.
"""


@pytest.fixture
def project_root(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "reqs.yaml").write_text(REQS, encoding="utf-8", newline="\n")
    (items / "decs.yaml").write_text(DECS, encoding="utf-8", newline="\n")
    (items / "log.yaml").write_text(LOG, encoding="utf-8", newline="\n")
    return tmp_path


def tree(root, *subdirs) -> dict[str, str]:
    import hashlib

    files = {}
    for sub in subdirs:
        base = os.path.join(str(root), sub)
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, str(root)).replace("\\", "/")
                with open(path, "rb") as fh:
                    files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


def read(path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def decs_file(root) -> str:
    return str(root / "items" / "decs.yaml")


def apply(root, ref, op, revision=None):
    path = decs_file(root)
    return edit_mod.apply_edit(
        str(root),
        EditRequest(
            who="local-author",
            ref=ref,
            op=op,
            expected_revision=revision if revision is not None else edit_mod.file_revision(path),
        ),
    )


# ------------------------------------------------------------------- applied


def test_add_link_writes_the_composite_the_freeze_pass_would_write(project_root):
    """The written text is links.composite_for's own output, not a copy of the
    browser's string: whatever handle the client sent, the disk gets the same
    DISPLAY-ID@key spelling `_planned_target` expands a bare reference to."""
    project = _build_at(project_root)
    expected = links_mod.composite_for(project.item_by_id("REQ-002"))
    assert expected == f"REQ-002@{K_REQ2}"

    before_tree = tree(project_root, "items", ".refdes")
    before = read(decs_file(project_root))
    result = apply(project_root, "DEC-001", AddLink("satisfies", "REQ-002"))

    assert isinstance(result, Applied), result.message
    after = read(decs_file(project_root))
    assert f"REQ-002@{K_REQ2}" in after
    assert after != before
    # exactly one file moved: no key minted, no other file touched
    after_tree = tree(project_root, "items", ".refdes")
    changed = {k for k, v in after_tree.items() if before_tree.get(k) != v}
    assert changed == {"items/decs.yaml"}
    assert "# keep me" in read(str(project_root / "items" / "reqs.yaml"))


@pytest.mark.parametrize("spelling", ["REQ-002", K_REQ2])
def test_the_target_may_be_named_by_display_id_or_surrogate_key(project_root, spelling):
    result = apply(project_root, "DEC-001", AddLink("satisfies", spelling))
    assert isinstance(result, Applied), result.message
    assert f"REQ-002@{K_REQ2}" in read(decs_file(project_root))


def test_remove_link_accepts_the_display_id_or_the_key_half(project_root):
    result = apply(project_root, "DEC-001", RemoveLink("satisfies", "REQ-001"))
    assert isinstance(result, Applied), result.message
    after = read(decs_file(project_root))
    assert f"REQ-001@{K_REQ1}" not in after
    assert "REQ-009@zzzzzzzzzzz" in after  # the other target is untouched


def test_remove_link_reaches_a_dangling_target_without_resolving_it(project_root):
    """The dangling REQ-009@zzzzzzzzzzz in the fixture has no item behind it.
    Removal is text matching, not identity resolution -- cleaning up a broken
    link must not require the broken thing to exist."""
    result = apply(project_root, "DEC-001", RemoveLink("satisfies", "zzzzzzzzzzz"))
    assert isinstance(result, Applied), result.message
    assert "REQ-009" not in read(decs_file(project_root))


# ------------------------------------------------------------------ refusals


def assert_untouched(project_root, before_tree):
    assert tree(project_root, "items", ".refdes") == before_tree


def test_a_verb_the_type_does_not_declare_is_refused(project_root):
    before = tree(project_root, "items", ".refdes")
    result = apply(project_root, "DEC-001", AddLink("verifies", "REQ-001"))
    assert isinstance(result, Refused), result.message
    assert "does not declare" in result.reason
    assert_untouched(project_root, before)


def test_a_target_of_the_wrong_type_is_refused_with_the_types_named(project_root):
    before = tree(project_root, "items", ".refdes")
    result = edit_mod.apply_edit(
        str(project_root),
        EditRequest(
            who="local-author",
            ref="LOG-001",
            op=AddLink("summary", "REQ-001"),  # not a link at all
            expected_revision=edit_mod.file_revision(str(project_root / "items" / "log.yaml")),
        ),
    )
    assert isinstance(result, Refused), result.message
    assert "does not declare" in result.reason
    assert_untouched(project_root, before)

    # a declared verb, wrong target type: give a decision a link to a log
    # by aiming at the only log item -- satisfies accepts requirements only.
    # (LOG-001 is a log, so the type check is what says no here.)
    result = edit_mod.apply_edit(
        str(project_root),
        EditRequest(
            who="local-author",
            ref="DEC-001",
            op=AddLink("satisfies", "LOG-001"),
            expected_revision=edit_mod.file_revision(decs_file(project_root)),
        ),
    )
    assert isinstance(result, Refused), result.message
    assert "requirement" in result.reason and "log" in result.reason
    assert_untouched(project_root, before)


def test_a_target_with_a_null_artifact_key_is_refused_not_written_bare(project_root):
    """The design's explicit rule: an imported or never-minted target has no
    key to composite, and writing the bare id would drop exactly the identity
    the link exists to carry."""
    before = tree(project_root, "items", ".refdes")
    result = apply(project_root, "DEC-001", AddLink("satisfies", "REQ-003"))
    assert isinstance(result, Refused), result.message
    assert "artifact key" in result.reason
    assert_untouched(project_root, before)
    assert "REQ-003" not in read(decs_file(project_root))


def test_an_unknown_target_is_refused(project_root):
    before = tree(project_root, "items", ".refdes")
    result = apply(project_root, "DEC-001", AddLink("satisfies", "REQ-099"))
    assert isinstance(result, Refused), result.message
    assert "no item" in result.reason
    assert_untouched(project_root, before)


def test_adding_a_link_that_is_already_there_refuses_from_the_patcher(project_root):
    before = tree(project_root, "items", ".refdes")
    result = apply(project_root, "DEC-001", AddLink("satisfies", "REQ-001"))
    assert isinstance(result, Refused), result.message
    assert "already links" in result.reason
    assert_untouched(project_root, before)


# ------------------------------------------------ the shared no-write paths


def test_a_stale_revision_on_a_link_edit_is_a_conflict_like_any_other(project_root):
    before = tree(project_root, "items", ".refdes")
    result = apply(
        project_root, "DEC-001", AddLink("satisfies", "REQ-002"), revision="0" * 64
    )
    assert isinstance(result, Conflict), result.message
    assert result.kind == "conflict"
    assert_untouched(project_root, before)


def test_a_sealed_item_refuses_a_link_edit_before_anything_else(project_root):
    """The seal check runs before link resolution: even a request naming a
    verb the type does not declare is refused as what it is -- an edit to a
    sealed entry."""
    project = _build_at(project_root)
    build_mod.build(project, seal_write=True)
    assert list((project_root / ".refdes").glob("log-seal*.yaml"))

    path = str(project_root / "items" / "log.yaml")
    before = tree(project_root, "items", ".refdes")
    result = edit_mod.apply_edit(
        str(project_root),
        EditRequest(
            who="local-author",
            ref="LOG-001",
            op=AddLink("satisfies", "REQ-001"),
            expected_revision=edit_mod.file_revision(path),
        ),
    )
    assert isinstance(result, Refused), result.message
    assert "sealed" in result.message
    assert_untouched(project_root, before)
