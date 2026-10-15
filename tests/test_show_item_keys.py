"""run-6b F2: an item's surrogate key in human-facing output.

A merge of items files needs composite `ID@key` pins (a bare id anchors on
the tip and collides), and no human-facing output printed the key half:
`ls` had no key column and `thread --json`'s projection carried no per-entry
key, so the key was reachable only by scraping `refdes index`'s JSON payload
(where it exists as `items[].key`). These tests pin the two added surfaces:

- `refdes ls --keys`: an opt-in key column, whose value is the *same* string
  the index reports (compared against the index payload, not recomputed),
  blank-padded for an item with no minted key, and a column that disappears
  when no row has one;
- the plain `refdes ls` listing: byte-identical to the one people and
  scripts parse -- the flag is opt-in, so the default answer carries no key.

The thread half pins `--json`'s per-entry `key` (null when there is none)
and `--keys`' composite `ID@key` header line, with the plain header's bytes
untouched.
"""

from __future__ import annotations

import json
import re

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod

CONFIG = (
    "site: { title: Keys CLI, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

THREAD_ITEMS = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
)


def _setup(tmp_path, items_yaml=THREAD_ITEMS):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _run(root, *args):
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), *args])


def _keys_from_the_index(root, capsys) -> dict[str, str]:
    """The key of every item, read from `refdes index` -- the payload the
    task names as the key's source of truth, so every assertion below
    compares the new surfaces against it rather than a second computation."""
    assert _run(root, "index", "--compact") == 0
    payload = json.loads(capsys.readouterr().out)
    return {item["id"]: item["key"] for item in payload["items"]}


def test_ls_keys_prints_the_key_the_index_reports(tmp_path, capsys):
    """The column's value is `items[].key` itself, as its own aligned cell
    between the id and the type -- not a recomputation to drift from it."""
    root = _setup(tmp_path)
    assert _run(root, "ls") == 0  # one writable run: the keys get minted
    capsys.readouterr()
    keys = _keys_from_the_index(root, capsys)
    assert all(keys.values())  # the warm run minted every item
    assert _run(root, "ls", "--keys") == 0
    out = capsys.readouterr().out
    for item_id, key in keys.items():
        row = next(line for line in out.splitlines() if line.startswith(item_id))
        assert row.split()[1] == key
        assert item_id in row.split()[0]


def test_default_ls_carries_no_key_the_column_is_opt_in(tmp_path, capsys):
    """The plain listing is what people and scripts parse, so the key only
    ever appears with the flag: on a fully-keyed project the default bytes
    name no key at all."""
    root = _setup(tmp_path)
    assert _run(root, "ls") == 0
    capsys.readouterr()
    keys = _keys_from_the_index(root, capsys)
    assert _run(root, "ls") == 0
    out = capsys.readouterr().out
    for key in keys.values():
        assert key not in out


def test_ls_keys_adds_blank_padding_to_an_item_with_no_minted_key(tmp_path, capsys):
    """A cold project under `--no-write` has minted nothing, so every cell
    is empty -- and an empty column is no column: the listing is byte-for-byte
    the plain one (the board/workspace zero-width rule, applied to the flag
    the reader opted into)."""
    root = _setup(tmp_path)
    assert _run(root, "--no-write", "ls") == 0
    plain = capsys.readouterr().out
    assert _run(root, "--no-write", "ls", "--keys") == 0
    assert capsys.readouterr().out == plain


def test_ls_keys_pads_blank_for_the_keyless_item_and_keeps_the_columns(tmp_path, capsys):
    """The mixed row: a warm project gains a fifth item that the read-only
    load cannot mint. The keyed rows keep their key cell; the keyless row
    pads blank in its place (the workspace column's style for empties --
    positional alignment, no placeholder), and the row's remaining cells
    stay in their columns."""
    root = _setup(tmp_path)
    assert _run(root, "ls") == 0
    capsys.readouterr()
    keys = _keys_from_the_index(root, capsys)
    path = root / "items" / "log.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "  - id: LOG-003\n"
        "    summary: Added after the keys were minted.\n"
        "    date: 2026-09-03\n"
        "    follows: LOG-002\n",
        encoding="utf-8",
    )
    assert _run(root, "--no-write", "ls", "--keys") == 0
    out = capsys.readouterr().out
    keyed = next(line for line in out.splitlines() if line.startswith("LOG-001"))
    assert keyed.split()[1] == keys["LOG-001"]
    keyless = next(line for line in out.splitlines() if line.startswith("LOG-003"))
    assert keyless.split()[1] == "log"  # no key cell content: type comes next
    assert not any(key in keyless for key in keys.values())
    # Blank padding, not a placeholder: the cells after the (empty) key
    # column start at the same offset as on the keyed rows.
    assert keyless.index("log") == keyed.index("log")


def test_thread_json_entries_carry_each_entrys_key(tmp_path, capsys):
    """Each projection entry gains its `key` -- the index payload's value,
    paired with the label the projection prints."""
    root = _setup(tmp_path)
    assert _run(root, "thread", "LOG-001") == 0  # writable: mints the keys
    capsys.readouterr()
    keys = _keys_from_the_index(root, capsys)
    assert _run(root, "thread", "LOG-001", "--json") == 0
    view = json.loads(capsys.readouterr().out)
    assert view["entries"] == [
        {"entry": "LOG-001", "key": keys["LOG-001"]},
        {"entry": "LOG-002", "key": keys["LOG-002"]},
    ]


def test_thread_json_entry_key_is_null_when_the_entry_has_none(tmp_path, capsys):
    """`--no-write` on a cold project mints nothing: the key is null, not
    absent and not empty-string -- the index payload's own convention for
    exactly this load (`key` is always present, nullable)."""
    root = _setup(tmp_path)
    assert _run(root, "--no-write", "thread", "LOG-001", "--json") == 0
    view = json.loads(capsys.readouterr().out)
    assert view["entries"] == [
        {"entry": "LOG-001", "key": None},
        {"entry": "LOG-002", "key": None},
    ]


def test_thread_keys_prints_the_composite_header(tmp_path, capsys):
    """The text view's half: `--keys` renders the header's labels in the
    composite `ID@key` form -- the whole thread's merge pins on one line --
    and leaves every line below it untouched."""
    root = _setup(tmp_path)
    assert _run(root, "thread", "LOG-001") == 0
    capsys.readouterr()
    keys = _keys_from_the_index(root, capsys)
    assert _run(root, "thread", "LOG-001", "--keys") == 0
    out = capsys.readouterr().out
    head, *rest = out.splitlines()
    assert head == (
        f"Thread: LOG-001@{keys['LOG-001']} -> LOG-002@{keys['LOG-002']}  (one tip)"
    )
    assert not any("@" in line for line in rest)


def test_thread_text_header_is_plain_without_the_flag(tmp_path, capsys):
    """The default thread view keeps its bytes: the composite form is a
    flag, not a layout change (`refdes work` shares the header composer and
    has no such flag, so its bytes ride on this too)."""
    root = _setup(tmp_path)
    assert _run(root, "thread", "LOG-001") == 0
    capsys.readouterr()
    keys = _keys_from_the_index(root, capsys)
    assert _run(root, "thread", "LOG-001") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "Thread: LOG-001 -> LOG-002  (one tip)"
    for key in keys.values():
        assert key not in out


def test_ls_help_and_thread_help_name_the_new_surfaces(capsys):
    """The column and the pins have to be discoverable from --help, the way
    every other ls/thread surface is."""
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main(["ls", "--help"])
    assert excinfo.value.code == 0
    ls_help = capsys.readouterr().out
    assert re.search(r"--keys", ls_help)
    assert re.search(r"ID@key", ls_help)
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main(["thread", "--help"])
    assert excinfo.value.code == 0
    thread_help = capsys.readouterr().out
    assert re.search(r"--keys", thread_help)
    assert re.search(r"ID@key", thread_help)
