"""Phase H5: sealing becomes history-backed; legacy-seal markers.

docs/design/living-notes-plan.md §H5 (and Q1/Q2). A type declaring
`sealing: history` is backed by captured history instead of the build-time
hash lock: a writable build seals none of its entries, an edit to one is the
H3 "edited after captured" warning rather than a build error, a bare
`follows:` on an entry a seal file mentions freezes (and is captured) instead
of being refused, and `--reseal` says it has nothing to do. Seal files that
already exist are read as legacy-seal markers -- never rewritten, never
deleted -- and an entry such a file mentions going missing is a warning
naming the file, never an error.

Every project here starts build-sealed and is switched to `sealing: history`
after its first writable build, so its seal file is a genuine legacy one: the
upgrade path an existing project actually takes. The build-sealed behaviour
itself is tests/test_seal.py's, unmodified; the paired tests below pin that
the scoping did not leak into it.
"""

from __future__ import annotations

import hashlib
import os

import pytest
import yaml
from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import history, loader, revise, seal
from refdes.model import SchemaError
from refdes.schema import load_project

SCHEMA = """\
site: {{ title: History Seal, out: _site }}
id: {{ width: 3, ledger: .refdes/ids.yaml }}
link_types:
  follows: {{ inverse: followed_by, label: Follows }}
  amends: {{ inverse: amended_by, label: Amends }}
types:
  log:
    prefix: LOG
    append_only: true
{sealing}    fields:
      summary: {{ type: text, required: true }}
    links:
      follows: [log]
      amends: [log]
"""

THREE = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First.\n"
    "  - id: LOG-002\n    summary: Second.\n"
    "  - id: LOG-003\n    summary: Third.\n"
)

RESEAL_NOTICE = "sealing no longer applies to the 'log' type; nothing was rewritten"


def _config(sealing: str) -> str:
    line = f"    sealing: {sealing}\n" if sealing else ""
    return SCHEMA.format(sealing=line)


def _write(tmp_path, sealing: str) -> str:
    write_project_config(tmp_path, _config(sealing))
    return str(tmp_path / "refdes-project.yaml")


def _legacy_project(tmp_path, *, adopted: bool = True, items: str = THREE) -> str:
    """A project whose `log` entries were sealed by a build-sealed build, then
    switched to `sealing: history` -- its seal file is now a legacy one."""
    (tmp_path / ".refdes").mkdir(exist_ok=True)
    if adopted:
        (tmp_path / ".refdes" / "keys-adopted.yaml").write_text(
            "adopted: true\n", encoding="utf-8"
        )
    (tmp_path / "items").mkdir(exist_ok=True)
    (tmp_path / "items" / "log.yaml").write_text(items, encoding="utf-8")
    cfg = _write(tmp_path, "")
    assert cli_mod.main(["-c", cfg, "build"]) == 0
    _age_seal_file(tmp_path)
    return _write(tmp_path, "history")


# The header an older refdes wrote -- the one this repository's own
# .refdes/log-seal-board-a.yaml still carries. `save_seals` writes a newer
# header, so any rewrite of a legacy file, even one with identical records,
# changes its bytes: the byte-identity assertions below can see it.
_OLD_HEADER = (
    "# Refdes append-only seals. Each entry records the content hash of a log\n"
    "# entry at the time it was first built. Editing a sealed entry fails the\n"
    "# build; append a new entry that `amends` it instead.\n"
)


def _age_seal_file(tmp_path) -> None:
    path = _seal_file(tmp_path)
    text = path.read_text(encoding="utf-8")
    body = "".join(line for line in text.splitlines(keepends=True) if not line.startswith("#"))
    assert body.startswith("sealed:")
    path.write_text(_OLD_HEADER + body, encoding="utf-8")


def _seal_file(tmp_path):
    return tmp_path / ".refdes" / "log-seal.yaml"


def _tree(root, *, under: str = "") -> dict[str, str]:
    """relpath -> sha256 for every file under `root` (optionally a subdir)."""
    files = {}
    top = os.path.join(str(root), under)
    if not os.path.isdir(top):
        return files
    for dirpath, _dirnames, names in os.walk(top):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, str(root)).replace("\\", "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


def _add_follows(tmp_path, after_summary: str, target: str) -> None:
    log = tmp_path / "items" / "log.yaml"
    lines = log.read_text(encoding="utf-8").splitlines()
    edited = []
    for line in lines:
        edited.append(line)
        if line.strip() == f"summary: {after_summary}":
            edited.append(f"    follows: [{target}]")
    assert len(edited) == len(lines) + 1
    log.write_text("\n".join(edited) + "\n", encoding="utf-8")


def _replace(tmp_path, old: str, new: str) -> None:
    log = tmp_path / "items" / "log.yaml"
    text = log.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    log.write_text(text.replace(old, new), encoding="utf-8")


def _drop_item(tmp_path, item_id: str) -> str:
    """Delete one item's block from items/log.yaml; return the file's old
    text so the caller can restore it."""
    log = tmp_path / "items" / "log.yaml"
    text = log.read_text(encoding="utf-8")
    # Blocks start at "  - "; key minting puts `key:` on that first line, so
    # the id is matched anywhere in the block.
    blocks: list[list[str]] = [[]]
    for line in text.splitlines(keepends=True):
        if line.startswith("  - "):
            blocks.append([])
        blocks[-1].append(line)
    kept = [b for b in blocks if f"id: {item_id}\n" not in "".join(b).replace("- id:", "  id:")]
    assert len(kept) == len(blocks) - 1, item_id
    log.write_text("".join("".join(b) for b in kept), encoding="utf-8")
    return text


def _run(capsys, cfg, *argv):
    capsys.readouterr()
    code = cli_mod.main(["-c", cfg, *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# ------------------------------------------------------------ the decisive one


def test_a_bare_follows_on_a_legacy_sealed_entry_freezes_and_is_captured(
    tmp_path, capsys
):
    """The plan's decisive transcript: a history-backed project, an entry a
    legacy seal file mentions, a bare `follows:` added to it. Before H5 this
    ended in the "already sealed" refusal and an edge bare forever; now the
    edge freezes, the chain forms, the capture line prints, and `check`
    reports zero errors."""
    cfg = _legacy_project(tmp_path)
    seal_before = _seal_file(tmp_path).read_bytes()
    _add_follows(tmp_path, "Second.", "LOG-001")

    code, output = _run(capsys, cfg, "index")
    assert code == 0, output
    assert "already sealed" not in output
    assert "captured LOG-001: LOG-002 now follows it" in output

    project, _stale = loader.load_tree(cfg, write=False)
    first, second = project.item_by_id("LOG-001"), project.item_by_id("LOG-002")
    text = (tmp_path / "items" / "log.yaml").read_text(encoding="utf-8")
    assert f"follows: [LOG-001@{first.key}]" in text  # frozen, not bare
    assert second.links["follows"] == [f"LOG-001@{first.key}"]
    events = [e for e in history.load_events(str(tmp_path)) if e["kind"] == "followed"]
    assert [(e["item_key"], e["successor_key"]) for e in events] == [
        (first.key, second.key)
    ]

    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert "0 errors" in output
    # The legacy seal file was read, never rewritten.
    assert _seal_file(tmp_path).read_bytes() == seal_before


def test_the_same_transcript_on_a_build_sealed_type_still_refuses(tmp_path, capsys):
    """The refusal was scoped, not removed: without `sealing: history` the
    identical transcript keeps today's warning text and a bare edge."""
    cfg = _legacy_project(tmp_path)
    cfg = _write(tmp_path, "")  # back to the default, build
    _add_follows(tmp_path, "Second.", "LOG-001")

    code, output = _run(capsys, cfg, "index")
    assert code == 0, output
    assert (
        "follows is still bare, but this append-only entry is already sealed; "
        "leaving it unchanged because freezing would change its hash."
    ) in output
    assert "follows: [LOG-001]" in (tmp_path / "items" / "log.yaml").read_text(
        encoding="utf-8"
    )
    assert not history.load_events(str(tmp_path))


# ------------------------------------------------------------- edits are warnings


def test_an_edit_after_capture_is_a_warning_under_check_and_build(tmp_path, capsys):
    cfg = _legacy_project(tmp_path)
    _add_follows(tmp_path, "Second.", "LOG-001")
    assert _run(capsys, cfg, "index")[0] == 0
    seal_before = _seal_file(tmp_path).read_bytes()

    _replace(tmp_path, "summary: First.", "summary: First, edited.")

    for command in ("check", "build"):
        code, output = _run(capsys, cfg, command)
        assert code == 0, output
        assert "LOG-001: edited after captured" in output
        assert "modified since it was sealed" not in output
        assert "ERROR" not in output
    assert _seal_file(tmp_path).read_bytes() == seal_before


def test_an_edit_to_an_uncaptured_legacy_sealed_entry_is_not_an_error(
    tmp_path, capsys
):
    """No capture, so no H3 warning either -- but above all no build error
    and no rewritten seal: the lock is off for this type."""
    cfg = _legacy_project(tmp_path)
    seal_before = _seal_file(tmp_path).read_bytes()
    _replace(tmp_path, "summary: Third.", "summary: Third, edited.")

    code, output = _run(capsys, cfg, "build")
    assert code == 0, output
    assert "ERROR" not in output
    assert _seal_file(tmp_path).read_bytes() == seal_before


def test_the_same_edit_on_a_build_sealed_type_is_still_a_build_error(tmp_path, capsys):
    cfg = _legacy_project(tmp_path)
    cfg = _write(tmp_path, "")
    _replace(tmp_path, "summary: Third.", "summary: Third, edited.")

    code, output = _run(capsys, cfg, "build")
    assert code == 1
    assert "LOG-003 is append-only and has been modified since it was sealed" in output


def test_a_new_history_backed_entry_is_never_sealed(tmp_path, capsys):
    cfg = _legacy_project(tmp_path)
    seal_before = _seal_file(tmp_path).read_bytes()
    log = tmp_path / "items" / "log.yaml"
    log.write_text(
        log.read_text(encoding="utf-8") + "  - id: LOG-004\n    summary: Fourth.\n",
        encoding="utf-8",
    )
    code, output = _run(capsys, cfg, "build")
    assert code == 0, output
    assert _seal_file(tmp_path).read_bytes() == seal_before
    assert "LOG-004" not in _seal_file(tmp_path).read_text(encoding="utf-8")


# ------------------------------------------------------------------- --reseal


def test_reseal_on_a_history_backed_entry_rewrites_nothing(tmp_path, capsys):
    """Q2: accepted, says so, captures nothing; the legacy seal's prior hash
    is not overwritten -- its bytes are identical before and after."""
    cfg = _legacy_project(tmp_path)
    _add_follows(tmp_path, "Second.", "LOG-001")
    assert _run(capsys, cfg, "index")[0] == 0
    _replace(tmp_path, "summary: First.", "summary: First, edited.")
    seal_before = _seal_file(tmp_path).read_bytes()
    history_before = _tree(tmp_path, under=".refdes/history")

    code, output = _run(capsys, cfg, "build", "--reseal")
    assert code == 0, output
    assert RESEAL_NOTICE in output
    assert "resealed after an edit" not in output
    assert _seal_file(tmp_path).read_bytes() == seal_before
    assert _tree(tmp_path, under=".refdes/history") == history_before

    # And nothing was recorded as an accepted reseal either.
    code, output = _run(capsys, cfg, "audit")
    assert code == 0, output
    reseals = output.split("Accepted append-only reseals (durable history):")[1]
    assert reseals.lstrip().startswith("(none)")


def test_reseal_is_silent_about_history_on_a_build_only_project(tmp_path, capsys):
    cfg = _legacy_project(tmp_path)
    cfg = _write(tmp_path, "")
    code, output = _run(capsys, cfg, "build", "--reseal")
    assert code == 0, output
    assert "no longer applies" not in output


# ------------------------------------------------------------ sabotage: deletion


@pytest.mark.parametrize("adopted", [True, False], ids=["keyed-seal", "scalar-seal"])
def test_deleting_a_legacy_sealed_entry_warns_and_restoring_is_clean(
    tmp_path, capsys, adopted
):
    """The asymmetry the plan names: `_report_deleted` iterates seal files,
    so without the policy a type that stopped locking edits would still
    error on deletion. For a history-backed type it is a warning naming the
    record and the seal file, exit 0 -- and `--reseal` does not drop it."""
    cfg = _legacy_project(tmp_path, adopted=adopted)
    _add_follows(tmp_path, "Second.", "LOG-001")
    assert _run(capsys, cfg, "index")[0] == 0
    project, _stale = loader.load_tree(cfg, write=False)
    key = project.item_by_id("LOG-003").key
    seal_before = _seal_file(tmp_path).read_bytes()

    original = _drop_item(tmp_path, "LOG-003")
    for argv in (("check",), ("build",), ("build", "--reseal")):
        code, output = _run(capsys, cfg, *argv)
        assert code == 0, (argv, output)
        assert "LOG-003 has a legacy seal record in .refdes/log-seal.yaml" in output
        assert "original content was not captured" in output
        assert (f"(key {key})" in output) is adopted
        assert "no item with that id is in the project" not in output
        assert _seal_file(tmp_path).read_bytes() == seal_before

    (tmp_path / "items" / "log.yaml").write_text(original, encoding="utf-8")
    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert "legacy seal record" not in output
    assert "0 errors" in output


def test_deleting_a_build_sealed_entry_is_still_an_error(tmp_path, capsys):
    cfg = _legacy_project(tmp_path)
    cfg = _write(tmp_path, "")
    _drop_item(tmp_path, "LOG-003")
    code, output = _run(capsys, cfg, "check")
    assert code == 1
    assert "LOG-003 is append-only and was sealed, but no item with that id" in output


MIXED = """\
site: { title: Mixed, out: _site }
id: { width: 3, ledger: .refdes/ids.yaml }
types:
  log:
    prefix: LOG
    append_only: true
    SEALING_LOG
    fields:
      summary: { type: text, required: true }
  note:
    prefix: NTE
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

MIXED_ITEMS = (
    "items:\n"
    "  - id: LOG-001\n    type: log\n    summary: A log.\n"
    "  - id: LOG-002\n    type: log\n    summary: Another log.\n"
    "  - id: NTE-001\n    type: note\n    summary: A note.\n"
    "  - id: NTE-002\n    type: note\n    summary: Another note.\n"
)


def test_the_policy_is_per_type_in_one_project(tmp_path, capsys):
    """One seal file, two append-only types, only one history-backed: the
    build-sealed type keeps its edit and deletion errors; the other's are
    gone. An orphan record is classified by its display id's prefix."""
    (tmp_path / ".refdes").mkdir()
    (tmp_path / ".refdes" / "keys-adopted.yaml").write_text("adopted: true\n", encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "log.yaml").write_text(MIXED_ITEMS, encoding="utf-8")
    write_project_config(tmp_path, MIXED.replace("    SEALING_LOG\n", ""))
    cfg = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", cfg, "build"]) == 0
    _age_seal_file(tmp_path)
    write_project_config(tmp_path, MIXED.replace("SEALING_LOG", "sealing: history"))
    seal_before = _seal_file(tmp_path).read_bytes()

    _replace(tmp_path, "summary: A log.", "summary: A log, edited.")
    _replace(tmp_path, "summary: A note.", "summary: A note, edited.")
    _drop_item(tmp_path, "LOG-002")
    _drop_item(tmp_path, "NTE-002")

    code, output = _run(capsys, cfg, "check")
    assert code == 1
    assert "NTE-001 is append-only and has been modified since it was sealed" in output
    assert "NTE-002 is append-only and was sealed, but no item" in output
    assert "LOG-001" not in output
    assert "LOG-002 has a legacy seal record in .refdes/log-seal.yaml" in output
    assert "LOG-002 is append-only" not in output
    assert _seal_file(tmp_path).read_bytes() == seal_before

    # Resealing accepts the build-sealed type's edit and removal only.
    code, output = _run(capsys, cfg, "build", "--reseal")
    assert code == 0, output
    text = _seal_file(tmp_path).read_text(encoding="utf-8")
    assert "NTE-002" not in text.split("reseals:")[0]  # dropped, recorded in reseals
    assert "id: LOG-001" in text and "id: LOG-002" in text  # legacy records kept
    project = load_project(config_path=cfg)
    seals = seal.load_seals(project)
    before = yaml.safe_load(seal_before.decode("utf-8"))["sealed"]
    for record_id, value in before.items():
        if value["id"].startswith("LOG-"):
            assert seals[record_id] == value


# ------------------------------------------------------------ corruption stays loud


def test_a_changed_key_on_a_legacy_sealed_entry_is_still_an_error(tmp_path, capsys):
    """A key never changes legitimately; dropping the build lock on content
    must not drop the corruption check on identity."""
    cfg = _legacy_project(tmp_path)
    project, _stale = loader.load_tree(cfg, write=False)
    old_key = project.item_by_id("LOG-003").key
    new_key = "zzzzzzzzzzz"
    assert len(new_key) == len(old_key)
    _replace(tmp_path, f"key: {old_key}", f"key: {new_key}")

    code, output = _run(capsys, cfg, "check")
    assert code == 1
    assert "LOG-003's key changed since its legacy seal record in .refdes/log-seal.yaml" in output


# ------------------------------------------------------------------- audit


def test_audit_reports_legacy_seals_and_edited_after_captured(tmp_path, capsys):
    cfg = _legacy_project(tmp_path)
    _add_follows(tmp_path, "Second.", "LOG-001")
    assert _run(capsys, cfg, "index")[0] == 0
    _replace(tmp_path, "summary: First.", "summary: First, edited.")

    code, output = _run(capsys, cfg, "audit")
    assert code == 0, output
    sealed = output.split("Append-only entries edited after sealing:")[1].split("\n\n")[0]
    # LOG-001 (edited) and LOG-002 (gained a frozen follows:) both differ from
    # their legacy seal; said so, never as a lock.
    assert "LOG-001  (legacy seal: recorded hash only; original content was not captured)" in sealed
    assert "LOG-002  (legacy seal" in sealed
    assert "LOG-003" not in sealed
    captured = output.split("Entries edited after captured:")[1].split("\n\n")[0]
    assert "LOG-001  (followed event" in captured
    assert "LOG-002" not in captured


def test_audit_of_a_build_sealed_project_is_unchanged_but_for_the_new_section(
    tmp_path, capsys
):
    cfg = _legacy_project(tmp_path)
    cfg = _write(tmp_path, "")
    _replace(tmp_path, "summary: Third.", "summary: Third, edited.")
    code, output = _run(capsys, cfg, "audit")
    assert code == 0, output
    assert "Append-only entries edited after sealing:\n  LOG-003\n" in output
    assert "Entries edited after captured:\n  (none)\n" in output


# ----------------------------------------------------------- migrate-seals


def test_migrate_seals_writes_markers_and_leaves_the_seal_file_alone(tmp_path, capsys):
    cfg = _legacy_project(tmp_path)
    seal_before = _seal_file(tmp_path).read_bytes()
    code, output = _run(capsys, cfg, "history", "migrate-seals")
    assert code == 0, output
    markers = [e for e in history.load_events(str(tmp_path)) if e["kind"] == "legacy-seal"]
    assert len(markers) == 3
    assert all("original content was not captured" in e["reason"] for e in markers)
    assert _seal_file(tmp_path).read_bytes() == seal_before

    code, output = _run(capsys, cfg, "build")
    assert code == 0, output
    assert _seal_file(tmp_path).read_bytes() == seal_before


# ----------------------------------------------------------------- revise


def test_revise_does_not_carry_hashes_into_a_legacy_seal_file(tmp_path, capsys):
    """`revise` carries a renamed entry's hash forward so a sealed entry is
    not reported as modified. A history-backed type has no lock to trip, and
    its seal records are legacy-seal markers -- read, never rewritten -- so
    the same rename leaves the file byte-identical and the project clean."""
    cfg = _legacy_project(tmp_path)
    seal_before = _seal_file(tmp_path).read_bytes()

    def summary_to_note(config_path: str) -> None:
        schema = os.path.join(os.path.dirname(config_path), "refdes-schema.yaml")
        with open(schema, encoding="utf-8") as fh:
            text = fh.read()
        with open(schema, "w", encoding="utf-8") as fh:
            fh.write(text.replace("summary: { type: text", "note: { type: text"))

    result = revise.apply(
        str(tmp_path),
        revise.Mapping(fields={"log": {"summary": "note"}}),
        mutate_config=summary_to_note,
    )
    assert result.ok, result.errors
    assert result.seals_updated == []
    assert _seal_file(tmp_path).read_bytes() == seal_before
    assert "note: First." in (tmp_path / "items" / "log.yaml").read_text(encoding="utf-8")

    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert "0 errors" in output


# ------------------------------------------------------------- read-only check


def test_check_on_a_history_backed_project_writes_nothing(tmp_path, capsys):
    cfg = _legacy_project(tmp_path)
    _replace(tmp_path, "summary: Third.", "summary: Third, edited.")
    before = _tree(tmp_path)
    code, output = _run(capsys, cfg, "check")
    assert code == 0, output
    assert _tree(tmp_path) == before


# ------------------------------------------------------------- boards


BOARDS = """\
site: { title: Boards, out: _site }
id: { width: 3, ledger: .refdes/ids.yaml }
boards:
  board-a: { label: Board A, token: A }
types:
  log:
    prefix: LOG
    append_only: true
SEALING    fields:
      summary: { type: text, required: true }
"""


def test_a_legacy_base_file_seal_is_never_migrated_for_a_history_backed_type(
    tmp_path, capsys
):
    """Build-sealed entries that moved onto a board get their base-file seal
    migrated into the board's file by a writable build. A history-backed
    type's records are never touched -- neither file is written."""
    (tmp_path / ".refdes").mkdir()
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log }\nitems:\n  - id: LOG-A-001\n    summary: First.\n",
        encoding="utf-8",
    )
    # Sealed before boards: existed -- into the base file.
    write_project_config(
        tmp_path,
        BOARDS.replace("boards:\n  board-a: { label: Board A, token: A }\n", "").replace(
            "SEALING", ""
        ),
    )
    cfg = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", cfg, "build"]) == 0
    assert "LOG-A-001" in _seal_file(tmp_path).read_text(encoding="utf-8")
    _age_seal_file(tmp_path)

    (tmp_path / "items" / "board-a").mkdir()
    os.replace(tmp_path / "items" / "log.yaml", tmp_path / "items" / "board-a" / "log.yaml")
    write_project_config(tmp_path, BOARDS.replace("SEALING", "    sealing: history\n"))
    seal_before = _seal_file(tmp_path).read_bytes()

    code, output = _run(capsys, cfg, "build", "--accept-board-move")
    assert code == 0, output
    assert _seal_file(tmp_path).read_bytes() == seal_before
    assert not (tmp_path / ".refdes" / "log-seal-board-a.yaml").exists()


# ------------------------------------------------------------- schema


def _schema_error(tmp_path, config: str) -> str:
    write_project_config(tmp_path, config)
    with pytest.raises(SchemaError) as excinfo:
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    return str(excinfo.value)


def test_sealing_defaults_to_build(tmp_path):
    project = load_project(config_path=_write(tmp_path, ""))
    assert project.types["log"].sealing == "build"


def test_sealing_rejects_an_unknown_value(tmp_path):
    message = _schema_error(tmp_path, _config("forever"))
    assert "sealing" in message and "build, history" in message


def test_sealing_history_needs_append_only(tmp_path):
    message = _schema_error(
        tmp_path, _config("history").replace("    append_only: true\n", "")
    )
    assert "types.log.sealing is 'history', but log is not append_only" in message


def test_a_subtype_cannot_lift_the_build_lock(tmp_path):
    config = _config("") + (
        "  entry:\n"
        "    extends: log\n"
        "    prefix: ENT\n"
        "    label: Entry\n"
        "    plural: Entries\n"
        "    sealing: history\n"
    )
    message = _schema_error(tmp_path, config)
    assert "types.entry.sealing is 'history', but 'log' is append_only" in message


def test_the_bundled_log_is_history_backed_and_a_project_overlay_can_opt_out(tmp_path):
    """hardware@3's `log` declares `sealing: history`; every other type keeps
    the engine default, `build`. A project that wants the old build-time lock
    back for its log says so with an overlay."""
    write_project_config(tmp_path, "site: { title: T, out: _site }\nstandard: { base: hardware, version: 3 }\n")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    assert project.types["log"].append_only is True
    assert project.types["log"].sealing == "history"
    assert {
        name for name, spec in project.types.items() if spec.sealing != "build"
    } == {"log"}

    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\nstandard: { base: hardware, version: 3 }\n"
        "types:\n  log:\n    sealing: build\n",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    assert project.types["log"].append_only is True
    assert project.types["log"].sealing == "build"
