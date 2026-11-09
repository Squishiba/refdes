"""The navis verbs say when id-less items were not scanned (run-16 F16-1).

Items with no `id:` yet sit in `project.pending` and never enter the
navis scan, so a project whose only markers live in such items prints
"no Navis: no `<!--navi: text-->` marker in any item body" while the
markers are on disk -- a listing that is silently incomplete. Every
verb that lists (ls/all) now adds one note line, on stderr like the
run's other notices, naming the exact number of skipped items; a
project with no id-less items prints exactly what it printed before,
and `refdes id` makes the note disappear.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import cli as cli_mod

CONFIG = (
    "site: { title: Navis idless, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

# One yaml list entry, no id: -- the marker lives in a body the scan
# cannot see (the item is pending, not a project member yet).
IDLESS_MARKER = (
    "defaults:\n"
    "  type: requirement\n"
    "  prefix: REQ-PWR\n"
    "  owner: X\n"
    "  tags: [power]\n"
    "  status: active\n"
    "items:\n"
    '  - body: "text <!--navi: check the surge rating-->"\n'
    "    source: S\n"
)

# An id'd entry carrying a marker, plus an id-less entry: the listing
# is non-empty and STILL owes the note.
IDLED_AND_IDLESS = (
    "defaults:\n"
    "  type: requirement\n"
    "  prefix: REQ-PWR\n"
    "  owner: X\n"
    "  tags: [power]\n"
    "  status: active\n"
    "items:\n"
    "  - id: REQ-PWR-001\n"
    '    body: "surviving <!--navi: recheck the fuse rating-->"\n'
    "    source: S\n"
    '  - body: "text <!--navi: check the surge rating-->"\n'
    "    source: S\n"
)

# Everything has an id: no note anywhere, byte-identical output.
ALL_IDLED = (
    "defaults:\n"
    "  type: requirement\n"
    "  prefix: REQ-PWR\n"
    "  owner: X\n"
    "  tags: [power]\n"
    "  status: active\n"
    "items:\n"
    "  - id: REQ-PWR-001\n"
    '    body: "surviving <!--navi: recheck the fuse rating-->"\n'
    "    source: S\n"
)

NOTE_SINGULAR = (
    "note: 1 item has no id yet and was not scanned -- "
    "run 'refdes id' to allocate it"
)


def _setup(tmp_path, yaml_text):
    config = write_project_config(tmp_path, CONFIG)
    reqs = tmp_path / "items" / "requirements"
    reqs.mkdir(parents=True)
    (reqs / "power.yaml").write_text(yaml_text, encoding="utf-8", newline="\n")
    return str(config)


def _run(config, *args):
    return cli_mod.main(["-c", config, *args])


def test_empty_listing_names_the_id_less_item_it_skipped(tmp_path, capsys):
    config = _setup(tmp_path, IDLESS_MARKER)
    assert _run(config, "--no-write", "navis", "ls") == 0
    captured = capsys.readouterr()
    assert "no Navis" in captured.out
    assert NOTE_SINGULAR in captured.err
    # The note is a note on the run, not part of the piped answer: it
    # rides stderr, where every neighbouring notice already lives.
    assert NOTE_SINGULAR not in captured.out


def test_nonempty_listing_also_notes_the_skipped_item(tmp_path, capsys):
    config = _setup(tmp_path, IDLED_AND_IDLESS)
    assert _run(config, "--no-write", "navis", "ls") == 0
    captured = capsys.readouterr()
    assert "recheck the fuse rating" in captured.out
    assert "check the surge rating" not in captured.out
    assert NOTE_SINGULAR in captured.err
    assert NOTE_SINGULAR not in captured.out
    # `all` shares the listing block and the note.
    assert _run(config, "--no-write", "navis", "all") == 0
    captured = capsys.readouterr()
    assert NOTE_SINGULAR in captured.err


def test_project_without_id_less_items_prints_no_note(tmp_path, capsys):
    config = _setup(tmp_path, ALL_IDLED)
    assert _run(config, "--no-write", "navis", "ls") == 0
    captured = capsys.readouterr()
    assert "recheck the fuse rating" in captured.out
    assert "no id" not in captured.out
    assert "no id" not in captured.err


def test_note_goes_away_after_refdes_id(tmp_path, capsys):
    config = _setup(tmp_path, IDLESS_MARKER)
    assert _run(config, "id") == 0
    capsys.readouterr()
    assert _run(config, "--no-write", "navis", "ls") == 0
    captured = capsys.readouterr()
    assert "check the surge rating" in captured.out
    assert "no id" not in captured.out
    assert "no id" not in captured.err
