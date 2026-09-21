"""The edit service: `serve.edit.apply_edit` (docs/design/browser-editor.md).

Sabotage-shaped, because that is what a write path deserves: every refusal is
asserted as a result *and* as a byte-identical tree. The proof that matters is
not "the happy path wrote the right bytes" but "the five ways this can say no
each left `items/` and `.refdes/` exactly as they were" -- the same posture
tests/test_no_write.py pins for the CLI (docs/design/keys.md §2).
"""

from __future__ import annotations

import os
import threading

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import build as build_mod
from refdes.patcher import SetBody, SetField
from refdes.serve import edit as edit_mod
from refdes.serve.edit import Applied, Conflict, EditRequest, Invalid, Refused

SCHEMA = """\
site:
  title: "Edit test"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
      status: { type: enum, choices: [draft, approved] }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

# REQ-002 carries the pre-existing error the delta gate exists for: a status
# outside its enum. Nothing else in the project is broken.
REQS = """\
# keep me: the patcher must not eat this
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.   # trailing comment
    status: approved
  - id: REQ-002
    text: Broken on purpose.
    status: bogus
"""

DECS = """\
defaults: { type: decision, board: board-a }
items:
  - id: DEC-001
    title: Use the buck regulator.
    satisfies: [REQ-001]
"""

LOG = """\
defaults: { type: log, board: board-a }
items:
  - id: LOG-001
    summary: Started the rail work.
"""

NOTES = """\
---
id: REQ-010
type: requirement
board: board-a
text: A markdown requirement.
---

Body prose before a rule.
"""


@pytest.fixture
def project_root(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    # newline="\n": these fixtures are LF files, like a git worktree checkout.
    # A CRLF markdown body is covered separately, because the patcher's own
    # fidelity check refuses one today (see test_crlf_markdown_body).
    (items / "reqs.yaml").write_text(REQS, encoding="utf-8", newline="\n")
    (items / "decs.yaml").write_text(DECS, encoding="utf-8", newline="\n")
    (items / "log.yaml").write_text(LOG, encoding="utf-8", newline="\n")
    (items / "notes.md").write_text(NOTES, encoding="utf-8", newline="\n")
    return tmp_path


def tree(root, *subdirs) -> dict[str, str]:
    """relpath -> sha256 for every file under the given subdirectories."""
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


def req(path) -> EditRequest:
    """An EditRequest against items/reqs.yaml with the revision it holds now."""
    return EditRequest(
        who="local-author",
        ref=path[0],
        op=path[1],
        expected_revision=edit_mod.file_revision(str(path[2])),
    )


def target(root) -> str:
    return str(root / "items" / "reqs.yaml")


# ------------------------------------------------------------------- applied


def test_applied_edit_changes_only_the_planned_span(project_root):
    path = target(project_root)
    before_file = read(path)
    before_tree = tree(project_root, "items", ".refdes")

    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-001", SetField("status", "draft"), path))
    )

    assert isinstance(result, Applied), result.message
    after_file = read(path)
    plan = result.plan
    # byte fidelity: everything outside the planned span is the same bytes
    assert after_file[: plan.start] == before_file[: plan.start]
    assert after_file[len(after_file) - len(before_file) + plan.end :] == before_file[plan.end :]
    assert after_file != before_file
    # the comment survived, and only the one value changed
    assert "keep me: the patcher must not eat this" in after_file
    assert "# trailing comment" in after_file
    assert "status: draft" in after_file
    # every other file is untouched -- no key minted, no .refdes/ write
    after_tree = tree(project_root, "items", ".refdes")
    changed = {k for k, v in after_tree.items() if before_tree.get(k) != v}
    assert changed == {"items/reqs.yaml"}


def test_applied_returns_the_new_file_revision(project_root):
    path = target(project_root)
    old = edit_mod.file_revision(path)
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-001", SetField("text", "The rail shall supply 5 V."), path))
    )
    assert isinstance(result, Applied), result.message
    assert result.revision == edit_mod.file_revision(path)
    assert result.revision != old


def test_applied_body_edit_on_a_markdown_item(project_root):
    path = str(project_root / "items" / "notes.md")
    before = read(path)
    result = edit_mod.apply_edit(
        str(project_root),
        req(("REQ-010", SetBody("New prose only.\n"), path)),
    )
    assert isinstance(result, Applied), result.message
    after = read(path)
    assert "New prose only." in after
    assert "Body prose before a rule." not in after
    # front matter untouched
    assert after.startswith("---\nid: REQ-010\n")
    assert before.split("---")[1] == after.split("---")[1]


def test_a_crlf_yaml_file_keeps_its_line_endings(project_root):
    """Jared's checkout has CRLF working copies, so a save must not silently
    reformat the whole file: the untouched bytes, break included, stay put."""
    path = target(project_root)
    with open(path, "rb") as fh:
        original = fh.read()
    with open(path, "wb") as fh:
        fh.write(original.replace(b"\n", b"\r\n"))
    before = read(path)

    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-001", SetField("status", "draft"), path))
    )
    assert isinstance(result, Applied), result.message
    with open(path, "rb") as fh:
        after = fh.read()
    assert b"\r\n" in after
    assert after.count(b"\r\n") == before.count("\r\n")  # no stray LF-only break
    assert "status: draft" in after.decode("utf-8")


def test_a_crlf_markdown_body_is_refused_not_garbled(project_root):
    """The patcher's own fidelity check cannot yet prove a CRLF markdown body
    edit (it compares the op's LF text against the file's CRLF one), so the
    save refuses. Refusing is the right outcome for the service -- a write it
    cannot prove is a write it does not make -- and this pins that the refusal
    leaves the file byte-identical rather than half-converted."""
    path = str(project_root / "items" / "notes.md")
    with open(path, "rb") as fh:
        original = fh.read()
    crlf = original.replace(b"\n", b"\r\n")
    with open(path, "wb") as fh:
        fh.write(crlf)

    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-010", SetBody("New prose.\n"), path))
    )
    assert isinstance(result, Refused), result.message
    with open(path, "rb") as fh:
        assert fh.read() == crlf


# ------------------------------------------------------------------ conflict


def test_stale_revision_conflicts_with_a_diff_and_writes_nothing(project_root):
    path = target(project_root)
    # the client saw the file before a second change landed on disk
    stale = edit_mod.file_revision(path)
    moved = read(path).replace("3.3 V", "5.0 V").encode("utf-8")  # read before truncating
    with open(path, "wb") as fh:
        fh.write(moved)
    before_tree = tree(project_root, "items", ".refdes")  # the state the save must not touch

    result = edit_mod.apply_edit(
        str(project_root),
        EditRequest("local-author", "REQ-001", SetField("status", "draft"), stale),
    )

    assert isinstance(result, Conflict), result.message
    assert result.expected_revision == stale
    assert result.current_revision == edit_mod.file_revision(path)
    assert result.current_text is not None  # the span as it stands on disk
    assert "---" in result.diff and "+++" in result.diff
    assert "5.0 V" in result.diff  # the diff is against the *current* file
    assert tree(project_root, "items", ".refdes") == before_tree


def test_an_item_that_no_longer_exists_is_refused_not_guessed(project_root):
    """If the item is gone from the current project, there is no span to
    conflict over and no file to check the revision against: the honest answer
    is a refusal naming that, not a diff invented against a file we can no
    longer attribute the request to."""
    path = target(project_root)
    stale = edit_mod.file_revision(path)
    with open(path, "wb") as fh:
        fh.write(b"defaults: { type: requirement, board: board-a }\nitems: []\n")
    before_tree = tree(project_root, "items", ".refdes")

    result = edit_mod.apply_edit(
        str(project_root),
        EditRequest("local-author", "REQ-001", SetField("status", "draft"), stale),
    )
    assert isinstance(result, Refused), result.message
    assert tree(project_root, "items", ".refdes") == before_tree


# -------------------------------------------------------------- sealed items


def test_sealed_item_is_refused_and_untouched(project_root):
    project = _build_at(project_root)
    build_mod.build(project, seal_write=True)
    seals = list((project_root / ".refdes").glob("log-seal*.yaml"))
    assert seals, "the fixture did not actually seal anything"

    path = str(project_root / "items" / "log.yaml")
    before_tree = tree(project_root, "items", ".refdes")
    result = edit_mod.apply_edit(
        str(project_root), req(("LOG-001", SetField("summary", "rewritten history"), path))
    )

    assert isinstance(result, Refused), result.message
    assert "sealed" in result.message
    assert tree(project_root, "items", ".refdes") == before_tree


def test_append_only_item_without_a_seal_may_be_edited(project_root):
    path = str(project_root / "items" / "log.yaml")
    result = edit_mod.apply_edit(
        str(project_root), req(("LOG-001", SetField("summary", "still open"), path))
    )
    assert isinstance(result, Applied), result.message


# ----------------------------------------------------------- the delta gate


def test_an_edit_that_introduces_an_error_is_invalid_and_untouched(project_root):
    path = target(project_root)
    before_tree = tree(project_root, "items", ".refdes")
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-001", SetField("status", "not-a-choice"), path))
    )

    assert isinstance(result, Invalid), result.message
    assert any("not one of" in d.message for d in result.diagnostics)
    assert tree(project_root, "items", ".refdes") == before_tree


def test_an_unrelated_pre_existing_error_does_not_block_an_edit(project_root):
    """REQ-002 is already broken (`status: bogus`); fixing its text must still
    save. Requiring a globally clean project would make the editor useless
    exactly when it is needed."""
    path = target(project_root)
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-002", SetField("text", "Repaired wording."), path))
    )
    assert isinstance(result, Applied), result.message
    # the pre-existing error is still there, reported but not blocking
    assert any("bogus" in d.message for d in result.diagnostics)
    assert "Repaired wording." in read(path)


def test_editing_the_broken_field_itself_is_still_blocked(project_root):
    """The other half of the gate: a pre-existing error attributed to the field
    being edited blocks, because the edit did not fix it."""
    path = target(project_root)
    before_tree = tree(project_root, "items", ".refdes")
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-002", SetField("status", "also-bogus"), path))
    )
    assert isinstance(result, Invalid), result.message
    assert any("status" in d.message for d in result.diagnostics)
    assert tree(project_root, "items", ".refdes") == before_tree


def test_an_edit_that_repairs_the_pre_existing_error_applies(project_root):
    path = target(project_root)
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-002", SetField("status", "approved"), path))
    )
    assert isinstance(result, Applied), result.message
    assert not any("bogus" in d.message for d in result.diagnostics)


def test_an_edit_on_one_file_leaves_another_files_diagnostics_alone(project_root):
    """The after-load is the whole project, so an unrelated file's diagnostics
    must survive the comparison unchanged -- otherwise every save would look
    like it introduced (or removed) errors it had nothing to do with."""
    path = str(project_root / "items" / "notes.md")
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-010", SetBody("Repaired prose.\n"), path))
    )
    assert isinstance(result, Applied), result.message
    # REQ-002's pre-existing error is still reported, uncounted as new
    assert any("bogus" in d.message for d in result.diagnostics)


# --------------------------------------------------------------- refusals


def test_unknown_ref_is_refused_and_writes_nothing(project_root):
    before_tree = tree(project_root, "items", ".refdes")
    result = edit_mod.apply_edit(
        str(project_root),
        EditRequest("local-author", "REQ-999", SetField("text", "x"), "anything"),
    )
    assert isinstance(result, Refused), result.message
    assert tree(project_root, "items", ".refdes") == before_tree


def test_protected_identity_fields_are_refused(project_root):
    path = target(project_root)
    before_tree = tree(project_root, "items", ".refdes")
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-001", SetField("id", "REQ-777"), path))
    )
    assert isinstance(result, Refused), result.message
    assert tree(project_root, "items", ".refdes") == before_tree


# ------------------------------------------------------------- the write step


def test_a_failed_replace_leaves_the_original_bytes(project_root, monkeypatch):
    path = target(project_root)
    before = read(path)
    before_tree = tree(project_root, "items", ".refdes")

    def boom(*_args, **_kw):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(edit_mod.os, "replace", boom)
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-001", SetField("status", "draft"), path))
    )

    assert isinstance(result, Refused), result.message
    assert read(path) == before
    assert tree(project_root, "items", ".refdes") == before_tree
    # no temp file left behind next to the source
    leftovers = [n for n in os.listdir(str(project_root / "items")) if n.startswith(".")]
    assert leftovers == []


def test_a_mismatched_write_is_restored(project_root, monkeypatch):
    """If the bytes that land are not the bytes planned, the original comes
    back and the save reports the failure -- the re-read is not decoration."""
    path = target(project_root)
    before = read(path)
    real_unlink = os.unlink

    def hijack(src, dst):
        # the replacement "succeeds" but lands the wrong bytes
        with open(dst, "wb") as fh:
            fh.write(b"not what was planned\n")
        real_unlink(src)

    monkeypatch.setattr(edit_mod.os, "replace", hijack)
    result = edit_mod.apply_edit(
        str(project_root), req(("REQ-001", SetField("status", "draft"), path))
    )
    assert isinstance(result, Refused), result.message
    assert read(path) == before


# ------------------------------------------------------------- concurrency


def test_concurrent_applies_serialize_and_never_clobber(project_root):
    """Two saves carrying the same revision: exactly one wins, the other comes
    back as a Conflict -- never an interleaved file, never a silent overwrite.
    That is the lock plus the revision check doing the only job they have."""
    path = target(project_root)
    shared_revision = edit_mod.file_revision(path)
    barrier = threading.Barrier(2)
    results = []
    guard = threading.Lock()

    def apply(ref, op):
        barrier.wait()
        result = edit_mod.apply_edit(
            str(project_root), EditRequest("local-author", ref, op, shared_revision)
        )
        with guard:
            results.append(result)

    threads = [
        threading.Thread(target=apply, args=("REQ-001", SetField("status", "draft"))),
        threading.Thread(target=apply, args=("REQ-002", SetField("text", "Reworded."))),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert len(results) == 2
    applied = [r for r in results if isinstance(r, Applied)]
    conflicts = [r for r in results if isinstance(r, Conflict)]
    assert len(applied) == 1, [r.message for r in results]
    assert len(conflicts) == 1, [r.message for r in results]

    final = read(path)
    # exactly one change landed, and the file is still the file it was elsewhere
    assert ("status: draft" in final) != ("Reworded." in final)
    assert "keep me: the patcher must not eat this" in final


def test_sequential_applies_both_land(project_root):
    path = target(project_root)
    first = edit_mod.apply_edit(
        str(project_root), req(("REQ-001", SetField("status", "draft"), path))
    )
    assert isinstance(first, Applied), first.message
    second = edit_mod.apply_edit(
        str(project_root),
        EditRequest("local-author", "REQ-002", SetField("text", "Reworded."), first.revision),
    )
    assert isinstance(second, Applied), second.message
    final = read(path)
    assert "status: draft" in final and "Reworded." in final


def test_the_write_lock_is_per_project():
    a = edit_mod.write_lock_for("/tmp/project-a")
    b = edit_mod.write_lock_for("/tmp/project-b")
    again = edit_mod.write_lock_for("/tmp/project-a")
    assert a is again
    assert a is not b
