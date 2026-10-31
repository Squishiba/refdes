"""Navis slice 3 CLI: `refdes navis archive/restore`, the Show-all listing
and the archived `show` (in-prog-logs/navis-design-20261025.md §10, §11,
§13 slice 3).

Selectors are the slice-2 `show` selector verbatim -- full 11-char key,
unique 6..10-char key prefix (ambiguous names its candidates, exit 2),
`ls` ordinal -- resolved over the Show-all rows. `--no-write` refuses both
verbs through `_refuse_no_write` (design §7.3, cli.py). The §9 restore
refusal (archived orphan) exits 1. `ls` is the active list; `all` is active
plus archived, labelled; `show` of an archived Navi prints the snapshot and
the "marker text has changed" note when the live text differs.
"""

from __future__ import annotations

import gzip

import yaml
from conftest import write_project_config

from refdes import cli as cli_mod

SCHEMA = (
    "site: { title: Navis Archive, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

NOTE_A = (
    "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\n"
    "intro\n<!--navi: Model worst-case copper temperature.-->\n"
)
NOTE_B = (
    "---\nid: NOTE-002\ntype: note\ntitle: Decoupling\n---\n"
    "<!--navi: Recheck decoupling near U14.-->\n"
)


def _setup(tmp_path, files=None):
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    files = files if files is not None else {
        "note-a.md": NOTE_A,
        "note-b.md": NOTE_B,
    }
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")
    return str(config)


def _run(config, *args):
    return cli_mod.main(["-c", config, *args])


def _navi_keys(tmp_path):
    import os
    import re

    keyed = re.compile(r"<!--navi:([0-9a-z]{11}) ")
    out = []
    for name in sorted(os.listdir(tmp_path / "items")):
        out += keyed.findall((tmp_path / "items" / name).read_text(encoding="utf-8"))
    return out


def _mint(tmp_path):
    """A writable load mints the keys (slice 2); tests that address a
    Navi by key mint first -- exactly what the archive verb's own run
    does. Keys are in (file, line) marker order."""
    _run(str(tmp_path / "refdes-project.yaml"), "navis", "ls")
    return _navi_keys(tmp_path)


# ---------------------------------------------------------------------------
# the verbs exist and archive the right thing
# ---------------------------------------------------------------------------


def test_archive_by_ordinal_writes_the_record(tmp_path, capsys):
    config = _setup(tmp_path)
    assert _run(config, "navis", "archive", "1") == 0
    key = _navi_keys(tmp_path)[0]
    out = capsys.readouterr().out
    assert "archived" in out
    assert key in out  # the full key is printed once, §5 full-key display
    path = tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz"
    record = yaml.safe_load(gzip.decompress(path.read_bytes()).decode("utf-8"))
    assert record["text"] == "Model worst-case copper temperature."
    assert record["source"]["file"] == "items/note-a.md"
    # The line is the live scan position at archive time; the writable load
    # mints item keys (front-matter lines) before the archive, so assert
    # the marker's own line in the current file, not a fixture literal.
    lines = (tmp_path / "items" / "note-a.md").read_text(encoding="utf-8").splitlines()
    assert record["source"]["line"] == next(
        i for i, ln in enumerate(lines, 1) if "<!--navi:" in ln
    )
    assert record["item_key"]  # the source item's key, §6


def test_archive_by_full_key_and_by_prefix(tmp_path):
    config = _setup(tmp_path)
    keys = _mint(tmp_path)
    assert _run(config, "navis", "archive", keys[0]) == 0
    assert _run(config, "navis", "archive", keys[1][:6]) == 0
    for key in keys:
        assert (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").exists()


def test_ambiguous_prefix_names_candidates_and_exits_2(tmp_path, capsys):
    config = _setup(tmp_path)
    keys = _mint(tmp_path)
    # fabricate an ambiguity: rewrite NOTE-002's key to share NOTE-001's
    # 6-char prefix (a hand-edit of the marker bytes is legal input). The
    # fabricated key must be valid grammar (a malformed key is a scan
    # diagnostic, not a row), so compute its check character.
    from refdes import keys as keys_mod

    data = keys[0][:6] + "zzzz"
    fabricated = data + keys_mod.check_char(data)
    note_b = tmp_path / "items" / "note-b.md"
    note_b.write_text(
        note_b.read_text(encoding="utf-8").replace(keys[1], fabricated),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert _run(config, "navis", "archive", keys[0][:6]) == 2
    err = capsys.readouterr().err
    assert "ambiguous" in err
    assert keys[0] in err  # names every candidate by full key
    assert fabricated in err
    assert not (tmp_path / ".refdes" / "navis").exists()


def test_selector_that_names_nothing_exits_2(tmp_path, capsys):
    config = _setup(tmp_path)
    assert _run(config, "navis", "archive", "9") == 2
    assert _run(config, "navis", "archive", "nosuchkey") == 2
    assert _run(config, "navis", "restore", "nosuchkey") == 2
    assert "no Navi" in capsys.readouterr().err
    assert not (tmp_path / ".refdes" / "navis").exists()


def test_archive_is_idempotent_announces_already_archived(tmp_path, capsys):
    # By KEY, not by ordinal: an ordinal addresses the Show-all list as
    # it is now, and archiving row 1 moves the numbers (the key is the
    # stable identity, design §5).
    config = _setup(tmp_path)
    keys = _mint(tmp_path)
    assert _run(config, "navis", "archive", keys[0]) == 0
    capsys.readouterr()
    assert _run(config, "navis", "archive", keys[0]) == 0
    assert "already archived" in capsys.readouterr().out
    names = [p.name for p in (tmp_path / ".refdes" / "navis").iterdir()]
    assert names == [f"{keys[0]}.yaml.gz"]


def test_restore_by_key_and_by_prefix(tmp_path, capsys):
    config = _setup(tmp_path)
    keys = _mint(tmp_path)
    _run(config, "navis", "archive", "1")
    capsys.readouterr()
    assert _run(config, "navis", "restore", keys[0]) == 0
    out = capsys.readouterr().out
    assert "restored" in out and keys[0] in out
    assert not (tmp_path / ".refdes" / "navis" / f"{keys[0]}.yaml.gz").exists()
    _run(config, "navis", "archive", "2")
    assert _run(config, "navis", "restore", keys[1][:6]) == 0
    assert not (tmp_path / ".refdes" / "navis" / f"{keys[1]}.yaml.gz").exists()


def test_restore_of_a_never_archived_navi_is_a_naming_error(tmp_path, capsys):
    config = _setup(tmp_path)
    assert _run(config, "navis", "restore", "1") == 2
    assert "not archived" in capsys.readouterr().err


def test_restore_of_an_archived_orphan_refuses(tmp_path, capsys):
    config = _setup(tmp_path)
    key = _mint(tmp_path)[0]
    assert _run(config, "navis", "archive", key) == 0
    (tmp_path / "items" / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\nintro\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    assert _run(config, "navis", "restore", key) == 1
    err = capsys.readouterr().err
    assert "navis.archived_orphan" in err
    assert "marker not found" in err
    assert (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").exists()
    # the §9 escape hatch: hand-restore the marker (with its key -- the
    # pair re-links by key, §9 row 3), then restore is legal again
    (tmp_path / "items" / "note-a.md").write_text(
        NOTE_A.replace("<!--navi: ", f"<!--navi:{key} "), encoding="utf-8"
    )
    assert _run(config, "navis", "restore", key) == 0
    assert not (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").exists()


# ---------------------------------------------------------------------------
# the keyless marker (§5, §7.2): archive names the minting load
# ---------------------------------------------------------------------------


def test_archive_of_a_keyless_marker_names_the_writable_load(tmp_path, capsys):
    # A folded YAML list-file body cannot be spliced at the marker's source
    # position, so it remains keyless and archive must refuse it.
    config = _setup(
        tmp_path,
        {
            "entries.yaml": (
                "items:\n  - id: NOTE-100\n    type: note\n    title: L\n"
                "    body: >\n      list body\n      <!--navi: list marker-->\n"
            )
        },
    )
    capsys.readouterr()
    assert _run(config, "navis", "archive", "1") == 2
    err = capsys.readouterr().err
    assert "no key" in err
    assert "next writable command" in err
    assert "this marker's body is one refdes will not mint into" in err
    assert "see the mint warnings above" in err
    assert not (tmp_path / ".refdes" / "navis").exists()


def test_archive_mints_and_archives_literal_block_yaml_marker(tmp_path, capsys):
    config = _setup(
        tmp_path,
        {
            "entries.yaml": (
                "items:\n  - id: NOTE-100\n    type: note\n    title: L\n"
                "    body: |\n      list body\n"
                "      <!--navi: literal marker-->\n"
            )
        },
    )

    assert _run(config, "navis", "archive", "1") == 0
    out = capsys.readouterr().out
    assert "archived Navi" in out
    assert "literal marker" in out
    key = _navi_keys(tmp_path)[0]
    assert (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").exists()


# ---------------------------------------------------------------------------
# --no-write (§7.3): both verbs refuse, nothing is written
# ---------------------------------------------------------------------------


def test_no_write_refuses_archive_and_restore(tmp_path, capsys):
    config = _setup(tmp_path)
    key = _mint(tmp_path)[0]
    _run(config, "navis", "archive", "1")  # a real archive to restore from
    capsys.readouterr()
    assert _run(config, "--no-write", "navis", "archive", "2") == 2
    err = capsys.readouterr().err
    assert "--no-write" in err and ".refdes/navis" in err
    assert _run(config, "--no-write", "navis", "restore", key) == 2
    err = capsys.readouterr().err
    assert "--no-write" in err and ".refdes/navis" in err
    assert (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").exists()


# ---------------------------------------------------------------------------
# ls / all / show over the merged projection (§9, §11)
# ---------------------------------------------------------------------------


def test_ls_is_the_active_list_archived_rows_are_appended(tmp_path, capsys):
    config = _setup(tmp_path)
    keys = _mint(tmp_path)
    _run(config, "navis", "archive", keys[0])
    capsys.readouterr()
    assert _run(config, "--no-write", "navis", "ls") == 0
    out = capsys.readouterr().out
    assert "Recheck decoupling" in out
    assert "Model worst-case" not in out
    assert out.count("Navis:") == 1
    # the surviving active row keeps the ordinal ls gave it before archiving
    assert "1. " in out


def test_all_lists_active_and_archived_labelled(tmp_path, capsys):
    config = _setup(tmp_path)
    keys = _mint(tmp_path)
    _run(config, "navis", "archive", keys[0])
    capsys.readouterr()
    assert _run(config, "--no-write", "navis", "all") == 0
    out = capsys.readouterr().out
    assert "Recheck decoupling" in out
    assert "Model worst-case" in out
    assert "archived" in out.lower()
    assert keys[0][:6] in out  # the archived row shows its short key


def test_show_of_an_archived_navi_prints_the_snapshot(tmp_path, capsys):
    config = _setup(tmp_path)
    key = _mint(tmp_path)[0]
    _run(config, "navis", "archive", "1")
    capsys.readouterr()
    assert _run(config, "--no-write", "navis", "show", key) == 0
    out = capsys.readouterr().out
    assert "Model worst-case copper temperature." in out
    assert "archived" in out.lower()
    assert "changed" not in out  # text identical: no note
    assert "items/note-a.md:" in out  # live marker position (§9: scan is truth)


def test_show_notes_marker_text_changed_since_archive(tmp_path, capsys):
    config = _setup(tmp_path)
    key = _mint(tmp_path)[0]
    _run(config, "navis", "archive", "1")
    note = tmp_path / "items" / "note-a.md"
    # edit the live text, keeping the minted key (a rewrite of NOTE_A
    # would keyless the marker and make it an orphan, not an edit)
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "Model worst-case copper temperature.", "EDITED"
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert _run(config, "--no-write", "navis", "show", key) == 0
    out = capsys.readouterr().out
    assert "snapshot: Model worst-case copper temperature." in out
    assert "marker text has changed" in out
    assert "EDITED" in out  # the live text is shown as the current marker


def test_show_of_an_orphan_labels_the_source_not_found(tmp_path, capsys):
    config = _setup(tmp_path)
    key = _mint(tmp_path)[0]
    _run(config, "navis", "archive", key)
    (tmp_path / "items" / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\nintro\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    assert _run(config, "--no-write", "navis", "show", key) == 0
    out = capsys.readouterr().out
    assert "marker not found" in out
    assert "items/note-a.md" in out  # the stored source, labelled


def test_restore_ordinal_addresses_the_archived_row(tmp_path, capsys):
    config = _setup(tmp_path)
    keys = _mint(tmp_path)
    _run(config, "navis", "archive", "1")  # NOTE-001 archived
    capsys.readouterr()
    assert _run(config, "--no-write", "navis", "all") == 0
    out = capsys.readouterr().out
    # Show-all order: active first, archived appended -- ordinal 2 is the
    # archived Navi (the slice-2 selector over the Show-all rows)
    assert out.index("Recheck decoupling") < out.index("Model worst-case")
    assert _run(config, "navis", "restore", "2") == 0
    assert not (tmp_path / ".refdes" / "navis" / f"{keys[0]}.yaml.gz").exists()


def test_project_with_no_navis_archives_nothing(tmp_path, capsys):
    config = _setup(tmp_path, {"note-a.md": NOTE_A.replace("<!--navi: Model worst-case copper temperature.-->", "")})
    assert _run(config, "navis", "ls") == 0
    assert _run(config, "navis", "archive", "1") == 2
    assert not (tmp_path / ".refdes" / "navis").exists()
    assert _run(config, "navis", "all") == 0
    assert "no Navis" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# help surface
# ---------------------------------------------------------------------------


def test_help_lists_the_verbs():
    import pytest

    for verb, needle in (("archive", "archive"), ("restore", "restore")):
        with pytest.raises(SystemExit) as exc:
            cli_mod.main(["navis", verb, "--help"])
        assert exc.value.code == 0
