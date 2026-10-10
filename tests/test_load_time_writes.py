"""Chunk 2a: no load-time write may turn a parseable item file into an
unparseable one.

Reproduced on main: a Markdown item whose front matter is a flow mapping
(`{id: REQ-001, type: requirement, title: x}`) was corrupted on disk by the
plain `refdes check` command -- `keys.mint_missing` inserted `key: <minted>`
as its own line *above* the `{...}` line, which is not valid YAML next to a
flow mapping, and every later load reported "0 items, 1 error". A read-type
command permanently destroying a valid file.

Fixes here:
- `ids.insert_into_markdown` now injects the new pair INSIDE the braces
  (the way `insert_into_list` already did for flow list entries) and refuses
  (returns None) a flow mapping that doesn't close on its line; every caller
  that inserts a key line (keys.mint_missing, ids.allocate,
  former_ids.confirm) reports and skips on refusal.
- `revise.write_rewrites_verified` guards every load-time write (key minting,
  link/check expansion, follows freeze): a rewritten file that no longer
  parses, or parses into fewer items, is restored to its original bytes and
  reported as an error.
"""

from __future__ import annotations

import json
import os
import re
import time

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import ids, keys, links, model, parse, revise
from refdes.schema import load_project

FLOW_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
)


def _flow_md(item_front_matter: str) -> str:
    return f"---\n{item_front_matter}\n---\n"


# ----------------------------------------------------- minting via the CLI


def test_check_mints_key_inside_flow_front_matter(tmp_path, capsys):
    """The orchestrator's repro: two consecutive `refdes check` runs on a
    flow-front-matter item. The file must stay parseable, the item must
    survive, the minted key must live inside the braces, and the second run
    must not mint again (key stable across loads)."""
    path = tmp_path / "items" / "r.md"
    write_project_config(tmp_path, FLOW_SCHEMA)
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        _flow_md("{id: REQ-001, type: requirement, title: x}"), encoding="utf-8"
    )
    cfg = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    first = path.read_text(encoding="utf-8")
    assert first.startswith("---\n{key: ")
    assert "\nkey:" not in first  # never a bare key line outside the braces
    assert "id: REQ-001" in first

    assert cli_mod.main(["-c", cfg, "check"]) == 0
    assert path.read_text(encoding="utf-8") == first  # no second mint

    project = load_project(config_path=cfg)
    parse.load_items(project)
    build_mod.build(project)
    assert [item.id for item in project.local_items] == ["REQ-001"]
    assert project.local_items[0].key


def test_allocate_writes_id_inside_flow_front_matter(tmp_path):
    """ids.allocate (the `refdes id` write-back) shares insert_into_markdown
    and had the same corruption: `id: REQ-001` on its own line above the
    braces."""
    path = tmp_path / "items" / "r.md"
    write_project_config(tmp_path, FLOW_SCHEMA)
    path.parent.mkdir(exist_ok=True)
    path.write_text(_flow_md("{type: requirement, title: x}"), encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n{id: REQ-001, type: requirement, title: x}")
    project2 = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project2)
    assert [item.id for item in project2.local_items] == ["REQ-001"]


# ------------------------------------------------- insert_into_markdown unit


def test_insert_into_markdown_flow_replaces_existing_key_in_place():
    """A flow mapping already holding the key gets its value replaced, never
    a duplicate key inserted (YAML last-wins would keep the stale one
    authoritative -- same rule as the block path)."""
    lines = ["---", "{id: REQ-001, type: requirement}", "---"]
    out = ids.insert_into_markdown(lines, 2, "id: REQ-009")
    assert out == ["---", "{id: REQ-009, type: requirement}", "---"]


def test_insert_into_markdown_refuses_unclosed_flow_mapping():
    """A flow mapping spanning lines cannot be edited safely: refuse (None)
    rather than guess."""
    lines = ["---", "{id: REQ-001,", "  type: requirement}", "---"]
    assert ids.insert_into_markdown(lines, 2, "key: abc") is None


def test_mint_refuses_unclosed_flow_front_matter_without_touching_file(tmp_path):
    path = tmp_path / "items" / "r.md"
    write_project_config(tmp_path, FLOW_SCHEMA)
    path.parent.mkdir(exist_ok=True)
    before = _flow_md("{id: REQ-001,\n  type: requirement,\n  title: x}")
    path.write_text(before, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project)
    assert path.read_text(encoding="utf-8") == before
    assert any("flow-style front matter" in str(d) for d in project.diagnostics)


# -------------------------------------------------------- parse-guard rollback


def test_load_time_write_that_breaks_parsing_is_rolled_back(tmp_path, monkeypatch):
    """Force the guard: monkeypatch the markdown insert back to the old
    corrupting behavior (bare `key:` line above the braces) and check that
    the guarded writer restores the original bytes and errors loudly instead
    of leaving the file unparseable on disk."""
    path = tmp_path / "items" / "r.md"
    write_project_config(tmp_path, FLOW_SCHEMA)
    path.parent.mkdir(exist_ok=True)
    before = _flow_md("{id: REQ-001, type: requirement, title: x}")
    path.write_text(before, encoding="utf-8")

    def corrupting_insert(lines, line_no, new_line, old_value=None):
        index = max(0, line_no - 1)
        return lines[:index] + [new_line] + lines[index:]

    monkeypatch.setattr(ids, "insert_into_markdown", corrupting_insert)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project)
    assert path.read_text(encoding="utf-8") == before
    assert any("rolled back" in str(d) for d in project.diagnostics)


def test_a_guard_rolled_back_mint_is_no_key_for_the_rest_of_the_load(
    tmp_path, monkeypatch
):
    """The invariant `write_rewrites_verified`'s returned set exists to keep:
    a key whose write did not reach disk is not a key -- for any of the three
    ways a write fails to land (finding KEY-GUARD-001). The insert refusing
    and the filesystem refusing both fed that set; the parse guard's own
    rollback did not, so the rolled-back item kept its minted key in memory
    and the next step of the same load froze a composite naming it.

    A forced guard (same monkeypatch as the test above) rolls back the mint
    into a flow-front-matter item, and a block-style sibling links to it
    bare. After the load's own next step -- link expansion -- the sibling
    must name no composite on disk, the sibling's in-memory link must stay
    bare, and the *following* load must find nothing to report: before the
    fix every later load errored with "points at key ... which no item
    declares", cleared only by hand-editing an item file.
    """
    a_md = tmp_path / "items" / "a.md"
    b_yaml = tmp_path / "items" / "b.yaml"
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "link_types:\n"
        "  part_of: { inverse: has_parts, label: Part of }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n"
        "    links:\n"
        "      part_of: [requirement]\n",
    )
    a_md.parent.mkdir(exist_ok=True)
    before_a = _flow_md("{id: REQ-001, type: requirement, title: x}")
    a_md.write_text(before_a, encoding="utf-8")
    b_yaml.write_text(
        "defaults:\n  type: requirement\n  prefix: REQ\n"
        "items:\n  - id: REQ-002\n    title: y\n    part_of: REQ-001\n",
        encoding="utf-8",
    )
    cfg = str(tmp_path / "refdes-project.yaml")

    def corrupting_insert(lines, line_no, new_line, old_value=None):
        index = max(0, line_no - 1)
        return lines[:index] + [new_line] + lines[index:]

    monkeypatch.setattr(ids, "insert_into_markdown", corrupting_insert)
    project = load_project(config_path=cfg)
    parse.load_items(project)
    keys.mint_missing(project)
    assert a_md.read_text(encoding="utf-8") == before_a  # the guard rolled back

    item_a = next(item for item in project.local_items if item.id == "REQ-001")
    assert not item_a.key, (
        f"key {item_a.key!r} is in memory but not on the disk the guard restored"
    )

    links.expand_missing(project, write=True)
    assert "@" not in b_yaml.read_text(), (
        "a composite naming a key that never reached disk"
    )
    item_b = next(item for item in project.local_items if item.id == "REQ-002")
    assert item_b.links["part_of"] == ["REQ-001"]

    project2 = load_project(config_path=cfg)
    parse.load_items(project2)
    build_mod.build(project2)
    assert not project2.errors, [str(d) for d in project2.errors]


def test_guard_lets_good_writes_through(tmp_path):
    """The guard must not refuse ordinary block-style minting."""
    path = tmp_path / "items" / "r.md"
    write_project_config(tmp_path, FLOW_SCHEMA)
    path.parent.mkdir(exist_ok=True)
    path.write_text("---\nid: REQ-001\ntype: requirement\ntitle: x\n---\n", encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    minted = keys.mint_missing(project)
    assert len(minted) == 1
    text = path.read_text(encoding="utf-8")
    assert "key: " in text
    assert not project.errors


# ------------------------------------------- guard judges what the loader sees

MULTI_ITEM_MD = (
    "---\n"
    "id: REQ-001\ntype: requirement\ntitle: One\n---\n"
    "Body one.\n"
    "---\n"
    "id: REQ-002\ntype: requirement\ntitle: Two\n---\n"
    "Body two.\n"
)

THEMATIC_BREAK_MD = (
    "---\n"
    "id: REQ-001\ntype: requirement\ntitle: One\n---\n"
    "Body before the rule.\n\n---\n\nBody after the rule.\n"
)


def _guard_rolls_back_broken_rewrite(tmp_path, before: str, expected_count: int):
    """The guard must judge these files by the same splitting the loader
    uses: a corrupting rewrite of a multi-item Markdown file, or of a single
    item whose body contains a `---` thematic break, is rolled back exactly
    and reported. (Both were silently skipped while the guard counted fences
    over every `---` in the file: body prose parsed as YAML gave "cannot
    judge", and None means the guard stays out of the way.)"""
    path = tmp_path / "items" / "r.md"
    write_project_config(tmp_path, FLOW_SCHEMA)
    path.parent.mkdir(exist_ok=True)
    path.write_text(before, encoding="utf-8", newline="\n")
    assert revise._parse_item_count("items/r.md", before) == expected_count

    after = before.replace("id: REQ-001", "id: [unclosed", 1)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    rewrite = revise.FileRewrite(
        path=str(path), rel="items/r.md", before=before, after=after
    )
    revise.write_rewrites_verified(project, [rewrite])
    # open(), not Path.read_text(): read_text only grew a `newline` parameter
    # in 3.13, and refdes supports 3.11 (pyproject's requires-python floor),
    # where this TypeErrors. The builtin has always taken it, with the same
    # meaning -- no translation of the file's own line endings.
    with open(path, encoding="utf-8", newline="\n") as fh:
        assert fh.read() == before
    assert any("rolled back" in str(d) for d in project.diagnostics)


def test_write_guard_judges_multi_item_markdown(tmp_path):
    _guard_rolls_back_broken_rewrite(tmp_path, MULTI_ITEM_MD, expected_count=2)


def test_write_guard_judges_markdown_body_with_thematic_break(tmp_path):
    _guard_rolls_back_broken_rewrite(tmp_path, THEMATIC_BREAK_MD, expected_count=1)


# -------------------------------------- the load's own writes get reported (F5)

LINK_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  refines: { inverse: refined_by, label: Refines }\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    fields:\n"
    "      text: { type: text, required: true }\n"
    "    links:\n"
    "      refines: [requirement]\n"
)

# Both items already carry a display id, so `refdes id` has nothing to
# allocate -- while the load on the way in mints two keys and expands the bare
# `refines:` target. Saying only "no items are missing an id" over three
# rewritten lines of the project is the F5 defect.
ID_ITEMS = (
    "defaults: { type: requirement }\n"
    "items:\n"
    "  - id: REQ-001\n"
    "    text: Target.\n"
    "  - id: REQ-002\n"
    "    text: Refiner.\n"
    "    refines: [REQ-001]\n"
)


def _id_project(tmp_path, items_yaml=ID_ITEMS):
    write_project_config(tmp_path, LINK_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return str(tmp_path / "refdes-project.yaml")


def test_id_reports_the_keys_and_link_target_its_load_wrote(tmp_path, capsys):
    cfg = _id_project(tmp_path)
    assert cli_mod.main(["-c", cfg, "id"]) == 0
    out = capsys.readouterr().out
    assert "minted 2 key(s) and rewrote 1 reference(s) while loading" in out
    assert "no items are missing an id" in out


def test_id_reports_load_writes_alongside_its_own_allocation(tmp_path, capsys):
    """A brand-new item: the load mints its key (keys are independent of ids),
    the command allocates its id. Both are said; `allocated N id(s)` is
    unchanged."""
    cfg = _id_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: Brand new.\n"
    )
    assert cli_mod.main(["-c", cfg, "id"]) == 0
    out = capsys.readouterr().out
    assert "(minted 1 key(s) while loading)" in out
    assert "allocated 1 id(s)" in out


def test_id_quiet_case_prints_only_its_own_verdict(tmp_path, capsys):
    """Steady state -- nothing pending, nothing minted, nothing expanded: the
    second run prints exactly the one line it printed before this fix."""
    cfg = _id_project(tmp_path)
    assert cli_mod.main(["-c", cfg, "id"]) == 0
    capsys.readouterr()
    assert cli_mod.main(["-c", cfg, "id"]) == 0
    assert capsys.readouterr().out == "no items are missing an id\n"


def test_id_names_only_the_rewrite_when_the_keys_already_exist(tmp_path, capsys):
    """Keys on disk, one target put back to bare: the notice names the rewrite
    and no minting that did not happen."""
    cfg = _id_project(tmp_path)
    assert cli_mod.main(["-c", cfg, "id"]) == 0
    path = tmp_path / "items" / "r.yaml"
    minted = path.read_text(encoding="utf-8")
    bare = re.sub(r"REQ-001@\w+", "REQ-001", minted)
    assert bare != minted
    path.write_text(bare, encoding="utf-8")
    capsys.readouterr()

    assert cli_mod.main(["-c", cfg, "id"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("(rewrote 1 reference(s) while loading)")
    assert "minted" not in out


def test_id_no_write_says_nothing_about_writes_it_did_not_make(tmp_path, capsys):
    """`--no-write` gates every incidental write in the load path, so there is
    nothing to report and the file stays byte-identical."""
    cfg = _id_project(tmp_path)
    path = tmp_path / "items" / "r.yaml"
    before = path.read_text(encoding="utf-8")
    assert cli_mod.main(["--no-write", "-c", cfg, "id"]) == 0
    assert capsys.readouterr().out == "no items are missing an id\n"
    assert path.read_text(encoding="utf-8") == before


def test_id_dry_run_says_nothing_about_writes_it_did_not_make(tmp_path, capsys):
    """`--dry-run` is the same promise under a different name (cli._load)."""
    cfg = _id_project(tmp_path)
    path = tmp_path / "items" / "r.yaml"
    before = path.read_text(encoding="utf-8")
    assert cli_mod.main(["-c", cfg, "id", "--dry-run"]) == 0
    assert capsys.readouterr().out == "no items are missing an id\n"
    assert path.read_text(encoding="utf-8") == before


# ------------------ every command that loads writable says so (BUG 1)
#
# In-prog-logs/user-sim-release-gate-run2.md §0 BUG 1: the notice existed, but
# only `id` and `stub-tests` called it, so `check` rewrote the item file and
# then reported as though nothing had happened. These are the commands the
# report named, each measured against the same keyless project.

NOTICE = "(minted 2 key(s) and rewrote 1 reference(s) while loading)"

ANNOUNCING: list[list[str]] = [
    ["check"],
    ["ls"],
    ["index", "--compact"],
    ["audit"],
    ["build"],
    ["revision", "rev-a"],
    ["fetch"],
    ["history", "capture", "REQ-001"],
]

# The ones that still run under --no-write; `fetch` and `history capture`
# refuse outright there (`_refuse_no_write`) and are covered by their own tests.
NO_WRITE_OK: list[list[str]] = [
    ["check"],
    ["ls"],
    ["index", "--compact"],
    ["audit"],
    ["build"],
    ["revision", "rev-a"],
]


def _stream(captured, argv):
    """Where a command's own prose goes -- stderr for `index`, whose stdout is
    JSON for the editor, stdout for everything else."""
    return captured.err if argv[0] == "index" else captured.out


@pytest.mark.parametrize("argv", ANNOUNCING)
def test_every_writable_command_announces_what_its_load_wrote(tmp_path, capsys, argv):
    cfg = _id_project(tmp_path)
    path = tmp_path / "items" / "r.yaml"
    before = path.read_text(encoding="utf-8")

    assert cli_mod.main(["-c", cfg, *argv]) == 0

    captured = capsys.readouterr()
    assert NOTICE in _stream(captured, argv)
    # The notice and the file agree: something really was written.
    assert path.read_text(encoding="utf-8") != before


@pytest.mark.parametrize("argv", ANNOUNCING)
def test_the_steady_state_still_announces_nothing(tmp_path, capsys, argv):
    """Once the tree is normalised -- keys on disk, targets composite -- no
    command prints anything about writes. The notice reports writes, it is not
    a banner. Primed with `check` rather than with the command itself, so a
    command that is not idempotent (`revision rev-a` twice) is not what this
    test is accidentally about."""
    cfg = _id_project(tmp_path)
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    capsys.readouterr()

    assert cli_mod.main(["-c", cfg, *argv]) == 0
    captured = capsys.readouterr()
    assert "while loading" not in captured.out + captured.err


@pytest.mark.parametrize("argv", NO_WRITE_OK)
def test_no_write_still_announces_no_writes_it_did_not_make(tmp_path, capsys, argv):
    cfg = _id_project(tmp_path)
    path = tmp_path / "items" / "r.yaml"
    before = path.read_text(encoding="utf-8")

    assert cli_mod.main(["--no-write", "-c", cfg, *argv]) == 0

    captured = capsys.readouterr()
    assert "while loading" not in captured.out + captured.err
    assert path.read_text(encoding="utf-8") == before


def test_index_announces_on_stderr_and_keeps_its_stdout_json(tmp_path, capsys):
    """`index` is the one command here whose stdout is machine output: the
    VS Code extension parses it. The notice belongs on stderr, and the JSON
    must stay parseable."""
    cfg = _id_project(tmp_path)

    assert cli_mod.main(["-c", cfg, "index", "--compact"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["items"]
    assert NOTICE in captured.err


# ------------------------- a tree that will not take a write (BUG 2)


def _chmod_tree(root, writable: bool) -> None:
    """Flip write permission over a whole tree (or one directory of it, files
    included -- a read-only *directory* still permits writing through to the
    files inside it, so both bits matter). Always restored by the caller, or
    pytest cannot clean the temporary directory up afterwards."""
    mode_file, mode_dir = (0o644, 0o755) if writable else (0o444, 0o555)
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), mode_file)
        for name in dirnames:
            os.chmod(os.path.join(dirpath, name), mode_dir)
    os.chmod(root, mode_dir)


def test_check_survives_a_read_only_tree(tmp_path, capsys):
    """BUG 2, both crash sites refused in one run: the `.refdes/schema.json`
    refresh and the key-mint write-back. Neither was caught, so `refdes check`
    died with a PermissionError traceback instead of checking anything. A
    read-only tree is a condition of the filesystem, not of the project: warn,
    and report what `--no-write check` reports.

    The schema file is created here on purpose, because that is the half of
    `write_schema`'s write that both platforms can actually be made to refuse.
    Refusing to *overwrite an existing file* is honoured everywhere: POSIX
    checks the file's own mode bits, and Windows maps `0o444` to the read-only
    attribute, which `open(path, "w")` refuses -- which is why the item file's
    refusal has fired on every platform from the start. Refusing to *create* a
    file is the parent directory's permission, and Windows' read-only attribute
    on a directory does not block creating entries in it, so the fresh-checkout
    shape where even `.refdes/` cannot be made is POSIX-only and lives in
    `test_check_survives_a_tree_that_cannot_create_refdes`.
    """
    cfg = _id_project(tmp_path)
    path = tmp_path / "items" / "r.yaml"
    before = path.read_text(encoding="utf-8")
    # A checkout that has been loaded writable once has this gitignored file
    # sitting there. Nothing in a CLI run ever reads it back -- the schema is
    # resolved in memory -- so its contents do not matter.
    (tmp_path / ".refdes").mkdir()
    (tmp_path / ".refdes" / "schema.json").write_text("{}\n", encoding="utf-8")
    _chmod_tree(tmp_path, False)
    try:
        code = cli_mod.main(["-c", cfg, "check"])
    finally:
        _chmod_tree(tmp_path, True)

    captured = capsys.readouterr()
    assert code == 0
    out = captured.out + captured.err
    assert "Traceback" not in out
    assert "could not write" in out
    # Both spelled with "/", which is how this tool names project-relative
    # paths to a person everywhere else. Asserting the separator is the point:
    # the schema refusal once came out `.refdes\schema.json` on Windows, in the
    # same run whose trip-wire called the same file `.refdes/schema.json`.
    assert ".refdes/schema.json" in out and "items/r.yaml" in out
    assert ".refdes\\schema.json" not in out
    assert "2 items, 0 errors" in out
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX directory permission bits: Windows' read-only attribute "
    "on a directory does not stop new entries being created inside it, so a "
    "refused os.makedirs cannot be produced that way",
)
def test_check_survives_a_tree_that_cannot_create_refdes(tmp_path, capsys):
    """The other statement in the same `try`: not a refused overwrite but a
    refused `os.makedirs(".refdes")`, on a fresh checkout that never had the
    gitignored file. Same verdict expected -- warn, name it, and check the
    project anyway."""
    cfg = _id_project(tmp_path)
    path = tmp_path / "items" / "r.yaml"
    before = path.read_text(encoding="utf-8")
    assert not (tmp_path / ".refdes").exists()
    _chmod_tree(tmp_path, False)
    try:
        code = cli_mod.main(["-c", cfg, "check"])
    finally:
        _chmod_tree(tmp_path, True)

    captured = capsys.readouterr()
    assert code == 0
    out = captured.out + captured.err
    assert "Traceback" not in out
    assert ".refdes/schema.json" in out and "items/r.yaml" in out
    assert not (tmp_path / ".refdes").exists()
    assert path.read_text(encoding="utf-8") == before


def test_check_survives_a_read_only_items_dir(tmp_path, capsys):
    """The second site on its own: `.refdes/` is writable, so only the
    key-mint write-back is refused -- and only the item file is named."""
    cfg = _id_project(tmp_path)
    items = tmp_path / "items"
    path = items / "r.yaml"
    before = path.read_text(encoding="utf-8")
    _chmod_tree(items, False)
    try:
        code = cli_mod.main(["-c", cfg, "check"])
    finally:
        _chmod_tree(items, True)

    captured = capsys.readouterr()
    assert code == 0
    out = captured.out + captured.err
    assert "Traceback" not in out
    assert "items/r.yaml" in out
    assert ".refdes/schema.json" not in out
    assert "2 items, 0 errors" in out
    assert path.read_text(encoding="utf-8") == before


def test_a_refused_mint_leaves_the_run_reading_like_no_write(tmp_path, capsys):
    """A key the filesystem refused is not a key: `--no-write`'s own rule (a
    key is only durable once persisted) applies to a failed write too. So the
    index says `key: null` and the bare target stays bare, rather than
    publishing a key that exists only in this process -- and, critically, no
    later step can freeze a composite naming it into a file that *is*
    writable, which would be a reference to nothing."""
    cfg = _id_project(tmp_path)
    items = tmp_path / "items"
    _chmod_tree(items, False)
    try:
        code = cli_mod.main(["-c", cfg, "index", "--compact"])
    finally:
        _chmod_tree(items, True)

    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert [item["key"] for item in payload["items"]] == [None, None]
    assert payload["items"][1]["links"]["refines"] == ["REQ-001"]


def test_commands_without_diagnostics_still_name_the_refusal(tmp_path, capsys):
    """`ls` prints errors and nothing else, so the per-file warning would
    never be seen: the summary line naming the refused files is its only
    channel. `check` does print diagnostics, and must not say it twice."""
    cfg = _id_project(tmp_path)
    _chmod_tree(tmp_path / "items", False)
    try:
        assert cli_mod.main(["-c", cfg, "ls"]) == 0
        ls = capsys.readouterr()
        assert cli_mod.main(["-c", cfg, "check"]) == 0
        check = capsys.readouterr()
    finally:
        _chmod_tree(tmp_path / "items", True)

    assert "(load could not write this file (read-only tree?) -- items/r.yaml" in ls.out
    assert "(load could not write" not in check.out
    assert check.out.count("could not write this file") == 1


def test_both_refusal_shapes_carry_the_one_sentence(tmp_path, capsys):
    """N2, the CI-filter half: a read-only refusal used to be spelled twice.

    `model.read_only_refusal()` is the one sentence, but only the *per-file*
    diagnostics said it. A command with no diagnostics of its own -- `ls` here
    -- fell back to a summary line with its own near-copy of the wording
    ("load could not write X -- read-only tree? run with --no-write to silence
    this"), so a log filter written against the constant caught `check` and
    `build` and silently missed `ls`, `index`, `audit`, `history` and every
    other command that names the refused files in a summary instead.

    Both forms must contain `model.READ_ONLY_REFUSAL` itself -- not merely a
    paraphrase, and not merely a shared keyword -- so the filter a CI author
    writes against the documented sentence cannot go stale on one of the two
    shapes. The deliberate split is untouched: `ls` names the files in its
    summary instead of per-file, `check` says it per file and not in a
    summary, and each says it exactly once. (`stub-tests` is a pre-existing
    exception that does both, because it runs `build` after announcing the
    load; that is not this test's subject, and it is unchanged here.)
    """
    cfg = _id_project(tmp_path)
    _chmod_tree(tmp_path / "items", False)
    try:
        assert cli_mod.main(["-c", cfg, "ls"]) == 0
        ls = capsys.readouterr()
        assert cli_mod.main(["-c", cfg, "check"]) == 0
        check = capsys.readouterr()
    finally:
        _chmod_tree(tmp_path / "items", True)

    # The summary names the file as the sentence's consequence, so the whole
    # stem is intact and the list follows it.
    assert model.READ_ONLY_REFUSAL in ls.out
    assert model.READ_ONLY_REFUSAL in check.out
    assert ls.out.count(model.READ_ONLY_REFUSAL) == 1
    # And the split still holds: `check` says it once per file and never in
    # the summary form; `ls` says it once, in the summary form only.
    assert "(load " not in check.out
    assert check.out.count(model.READ_ONLY_REFUSAL) == 1
    assert ls.out.count("could not write this file") == 1
    assert "items/r.yaml" in ls.out and "items/r.yaml" in check.out
    # Built from the constant, so the tail the constant appends is there too --
    # a hand-written near-copy of the sentence is exactly what this replaced.
    assert ls.out.splitlines()[0] == (
        f"(load {model.READ_ONLY_REFUSAL} -- items/r.yaml"
        "; run with --no-write to silence this)"
    )


def test_check_does_not_call_a_refused_schema_refresh_refreshed(tmp_path, capsys):
    """The staleness trip-wire's own honesty: it says "refreshed" because the
    write ran. When the write was refused, the editor's completion list is
    exactly as stale as it was, and saying otherwise sends the user back to
    re-check a file that did not change."""
    cfg = _id_project(tmp_path)
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    capsys.readouterr()
    # Make the generated file stale again -- by an hour, not by "now": the
    # staleness check is a strict mtime comparison, and a bare os.utime() can
    # land on the same clock tick as the write it is meant to postdate.
    future = time.time() + 3600
    os.utime(tmp_path / "refdes-schema.yaml", (future, future))
    _chmod_tree(tmp_path / ".refdes", False)
    try:
        assert cli_mod.main(["-c", cfg, "check"]) == 0
    finally:
        _chmod_tree(tmp_path / ".refdes", True)

    out = capsys.readouterr().out
    assert "not refreshed (the write was refused)" in out
    assert "-- refreshed." not in out


def test_an_explicit_write_still_raises_on_a_read_only_tree(tmp_path):
    """The tolerance belongs to the load, not to writes the user asked for:
    `revise apply`, `calc-rewrite`, `keys adopt` and `keys restore` call
    `write_rewrites` without the hook, and there a refusal is a failure."""
    path = tmp_path / "items"
    path.mkdir()
    target = path / "r.yaml"
    target.write_text("items: []\n", encoding="utf-8")
    rewrite = revise.FileRewrite(
        path=str(target), rel="items/r.yaml", before="items: []\n", after="items: []\n"
    )
    _chmod_tree(path, False)
    try:
        with pytest.raises(PermissionError):
            revise.write_rewrites([rewrite])
    finally:
        _chmod_tree(path, True)


# ------------------- a file with a duplicate key is not rewritten (step 4)

# A list entry whose opening `- key:` line was deleted takes the `- ` marker
# with it, so its fields merge into the entry above and the file now holds two
# `id:` lines. This is the file the parse reports (tests/test_parse.py), and
# this is what the rest of the load must NOT do to it: mint the missing
# `key:` line back into the entry (moving the very lines the author has to
# read) and, worse, freeze a live reference in *another* file onto the item
# that swallowed the vanished one. Both happened before the parse reported the
# repeat, in the same load that discovered it.
MERGED_ITEMS = (
    "defaults: { type: requirement }\n"
    "items:\n"
    "  - id: REQ-001\n"
    "    text: First.\n"
    "  - id: REQ-002\n"
    "    text: Second.\n"
    "    refines: [REQ-001]\n"
    "    id: REQ-003\n"
    "    text: Third.\n"
)


def test_a_file_with_a_duplicate_key_is_left_byte_identical(tmp_path, capsys):
    """The merged-entry shape, through a real writable `refdes check`."""
    cfg = _id_project(tmp_path, MERGED_ITEMS)
    merged = tmp_path / "items" / "r.yaml"
    before = merged.read_text(encoding="utf-8")
    other = tmp_path / "items" / "s.yaml"
    other.write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-004\n"
        "    text: Points at the entry that swallowed REQ-002.\n"
        "    refines: [REQ-002]\n",
        encoding="utf-8",
    )

    assert cli_mod.main(["-c", cfg, "check"]) == 1
    captured = capsys.readouterr()
    # `check` streams errors to stderr and the summary to stdout.
    assert "duplicate key 'id' in one mapping (lines 5 and 8)" in captured.err
    # No `key:` line was minted into the file that could not be trusted to say
    # which entry it belongs to -- so the file is byte-identical.
    assert merged.read_text(encoding="utf-8") == before
    assert "key:" not in merged.read_text(encoding="utf-8")
    # The clean file is still normalised, and the run says so: the withholding
    # is per file, not a blanket refusal to write anything. Its `refines:`
    # target no longer exists, so it stays bare -- there is no key to name.
    assert "(minted 1 key(s) while loading)" in captured.out
    assert "key:" in other.read_text(encoding="utf-8")
    assert "refines: [REQ-002]" in other.read_text(encoding="utf-8")


def test_the_duplicate_key_run_makes_no_key_claim_it_cannot_keep(tmp_path, capsys):
    """`--no-write`'s rule -- a key is only durable once persisted -- applied
    to a key that was never offered: both entries in the merged file publish no
    key, rather than a key that exists only in this process. Withholding is per
    file, not per item: a `key:` line cannot be inserted into a mapping whose
    `- ` marker is missing without guessing which entry it belongs to."""
    cfg = _id_project(tmp_path, MERGED_ITEMS)
    assert cli_mod.main(["-c", cfg, "index", "--compact"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in payload["items"]] == ["REQ-001", "REQ-003"]
    assert [item["key"] for item in payload["items"]] == [None, None]
    assert (tmp_path / "items" / "r.yaml").read_text(encoding="utf-8") == MERGED_ITEMS


# ------------------- writes that are the command's own job (run-3 N1)
#
# In-prog-logs/user-sim-release-gate-run3.md §3 N1: run 2's BUG 2 fix covered
# the two *load-time* sites, and `build`/`revision`/`release` write further
# down -- the append-only seal file, `.refdes/baselines/<name>.yaml`, and the
# rendered site under `site.out`. Each died with a raw PermissionError
# traceback, before any output, exit 1 -- indistinguishable from a broken
# project. Same three shapes as the tests above, one command at a time.

STAMP_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  verifies: { inverse: verified_by, label: Verifies }\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    coverable: true\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      status: { type: enum, choices: [draft, active], default: active }\n"
    "  test:\n"
    "    prefix: TST\n"
    "    verifying_statuses: [passing]\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      status: { type: enum, choices: [planned, passing], default: planned }\n"
    "    links:\n"
    "      verifies: [requirement]\n"
    "  log:\n"
    "    prefix: LOG\n"
    "    append_only: true\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
)

STAMP_ITEMS = (
    "defaults: { type: requirement }\n"
    "items:\n"
    "  - id: REQ-001\n    title: Covered requirement.\n"
)

STAMP_TEST = (
    "defaults: { type: test }\n"
    "items:\n"
    "  - id: TST-001\n    title: Verifies it.\n    status: passing\n"
    "    verifies: [REQ-001]\n"
)


def _stamp_project(tmp_path, out: str = "_site") -> str:
    """A project that is green for every command below, with one append-only
    entry so `build` has a seal to write and nothing else to complain about.

    `release` runs its whole gate *before* it reaches the baseline write --
    that is the order `stamp()` uses -- so the fixture has to be releasable
    or the test would be asserting on a gate failure: hence the active
    requirement, the passing test that covers it, and no citations.
    """
    write_project_config(
        tmp_path, STAMP_SCHEMA.replace("out: _site", f"out: {out}")
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(STAMP_ITEMS, encoding="utf-8")
    (items / "t.yaml").write_text(STAMP_TEST, encoding="utf-8")
    (items / "log.yaml").write_text(
        "defaults: { type: log }\nitems:\n  - id: LOG-001\n    title: An entry.\n",
        encoding="utf-8",
    )
    return str(tmp_path / "refdes-project.yaml")


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX permission bits: Windows maps 0o444 to the read-only "
    "attribute, which refuses an overwrite but not a new file, so the "
    "fresh-checkout half of each shape cannot be produced there",
)
def test_build_refuses_a_read_only_tree_instead_of_crashing(tmp_path, capsys):
    """The whole tree read-only, on a project `build` would otherwise seal.

    Two writes are refused here and they are refused differently, because
    they are different in kind. The seal file degrades: `build` has a site to
    render afterwards, so the entries go unsealed *and say so* -- an error
    naming the file, which is what makes the run exit non-zero and stops it
    reading as a successful seal (`refdes check --help` is explicit that an
    unbuilt entry has no append-only protection at all). The site output is
    `build`'s own product, the one thing the command is for, so there is
    nothing to degrade to: refuse, name the path, exit 2.
    """
    cfg = _stamp_project(tmp_path)
    log_before = (tmp_path / "items" / "log.yaml").read_text(encoding="utf-8")
    _chmod_tree(tmp_path, False)
    try:
        code = cli_mod.main(["-c", cfg, "build"])
    finally:
        _chmod_tree(tmp_path, True)

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Traceback" not in out
    # The seal half: named, error-level, and honest about what it cost.
    assert ".refdes/log-seal.yaml" in out
    assert "are NOT sealed" in out
    assert "read-only tree?" in out
    # The render half: a refusal naming the destination.
    assert "error: cannot write the site to" in out
    assert "_site" in out
    assert "site written to" not in out
    # 2, not 1: nothing is wrong with the project (see
    # docs/cli-reference.md's exit-code table).
    assert code == 2
    assert not (tmp_path / ".refdes" / "log-seal.yaml").exists()
    assert (tmp_path / "items" / "log.yaml").read_text(encoding="utf-8") == log_before


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX directory permission bits; see the test above",
)
def test_build_renders_the_site_when_only_refdes_is_read_only(tmp_path, capsys):
    """The other half of the same condition: `items/` and the site output are
    writable, only `.refdes/` is not. This is the shape a CI checkout
    actually has when the site goes somewhere else, and it is the one where
    the two refusals must not be confused -- the render succeeds and says so,
    the seal does not and says that too.

    `site.out` points outside the project entirely, so the assertion that the
    site really landed is about a directory the read-only tree does not own.
    """
    site = tmp_path / "site-out"
    site.mkdir()
    cfg = _stamp_project(tmp_path, out=str(site))
    refdes = tmp_path / ".refdes"
    _chmod_tree(tmp_path / "items", True)
    refdes.mkdir()
    _chmod_tree(refdes, False)
    try:
        code = cli_mod.main(["-c", cfg, "build"])
    finally:
        _chmod_tree(refdes, True)

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Traceback" not in out
    assert ".refdes/log-seal.yaml" in out and "are NOT sealed" in out
    assert f"site written to {site}" in out
    assert "error: cannot write the site to" not in out
    # Errors found (1), not a refusal: the render is what the command was
    # asked for and it happened.
    assert code == 1
    assert (site / "index.html").is_file()
    assert not (refdes / "log-seal.yaml").exists()


def _stamp_command_refuses_read_only(tmp_path, capsys, argv, rel: str) -> int:
    """`revision`/`release` on a read-only tree: refuse, name the file, and
    never print the word that would read as a stamp that happened."""
    cfg = _stamp_project(tmp_path)
    _chmod_tree(tmp_path, False)
    try:
        code = cli_mod.main(["-c", cfg, *argv])
    finally:
        _chmod_tree(tmp_path, True)

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Traceback" not in out
    assert f"error: cannot write {rel}" in out
    assert "read-only tree?" in out
    assert "was not stamped" in out
    assert "stamped:" not in out
    assert not (tmp_path / rel).exists()
    return code


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX directory permission bits; see the test above",
)
def test_revision_refuses_a_read_only_tree_instead_of_crashing(tmp_path, capsys):
    assert _stamp_command_refuses_read_only(
        tmp_path, capsys, ["revision", "rev-a"], ".refdes/baselines/rev-a.yaml"
    ) == 2


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX directory permission bits; see the test above",
)
def test_release_refuses_a_read_only_tree_instead_of_crashing(tmp_path, capsys):
    assert _stamp_command_refuses_read_only(
        tmp_path, capsys, ["release", "rel-a"], ".refdes/baselines/rel-a.yaml"
    ) == 2


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX directory permission bits; see the test above",
)
def test_a_refused_stamp_leaves_no_baseline_for_a_later_run_to_mistake(
    tmp_path, capsys
):
    """The refusal is only worth anything if the next run behaves as though
    nothing was stamped. Making the tree writable again and re-running must
    stamp for real -- an empty or half-written file here would turn into a
    'conflict' or a bogus 'unchanged' on the retry, which is the failure a
    silently-truncated write causes."""
    cfg = _stamp_project(tmp_path)
    _chmod_tree(tmp_path, False)
    try:
        assert cli_mod.main(["-c", cfg, "revision", "rev-a"]) == 2
    finally:
        _chmod_tree(tmp_path, True)
    capsys.readouterr()

    assert cli_mod.main(["-c", cfg, "revision", "rev-a"]) == 0
    assert "stamped:" in capsys.readouterr().out
    assert (tmp_path / ".refdes" / "baselines" / "rev-a.yaml").is_file()


@pytest.mark.parametrize("argv", [["revision", "rev-a"], ["release", "rel-a"]])
def test_no_write_stamps_nothing_on_a_read_only_tree_too(tmp_path, capsys, argv):
    """`--no-write` is unchanged by any of this: it never reaches the write,
    so it reports what it would stamp and exits 0 whether or not the tree
    would have taken it."""
    cfg = _stamp_project(tmp_path)
    _chmod_tree(tmp_path, False)
    try:
        code = cli_mod.main(["--no-write", "-c", cfg, *argv])
    finally:
        _chmod_tree(tmp_path, True)

    out = capsys.readouterr().out
    assert code == 0
    assert "not stamped (--no-write): would stamp" in out
    assert "cannot write" not in out
    assert not (tmp_path / ".refdes" / "baselines").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX directory permission bits; see the test above",
)
def test_build_reports_a_refused_board_manifest_too(tmp_path, capsys):
    """The fourth `.refdes/` write `build` makes, which the report did not
    name because it only bites a project with a `boards:` registry: the
    membership manifest. Reproduced on main the same way as the seal file --
    `PermissionError` out of `boards.save_manifest`, exit 1, before any
    output.

    Same severity for the same reason: an unrecorded membership means the
    *next* build reports a board move that was already accepted as new again,
    so the run is not a clean build and must not say it is.
    """
    site = tmp_path / "site-out"
    site.mkdir()
    cfg = _stamp_project(tmp_path, out=str(site))
    with open(cfg, "a", encoding="utf-8") as fh:
        fh.write('boards:\n  power:\n    label: "Board A"\n')
    # The manifest is only written when membership changed, so at least one
    # item has to resolve onto the registered board.
    board_items = tmp_path / "items" / "power"
    board_items.mkdir()
    (board_items / "r.yaml").write_text(STAMP_ITEMS, encoding="utf-8")
    (tmp_path / "items" / "r.yaml").unlink()
    (board_items / "t.yaml").write_text(STAMP_TEST, encoding="utf-8")
    (tmp_path / "items" / "t.yaml").unlink()
    refdes = tmp_path / ".refdes"
    refdes.mkdir()
    _chmod_tree(refdes, False)
    try:
        code = cli_mod.main(["-c", cfg, "build"])
    finally:
        _chmod_tree(refdes, True)

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Traceback" not in out
    assert ".refdes/boards.yaml" in out
    assert "membership was NOT recorded" in out
    assert "read-only tree?" in out
    assert code == 1
    assert (site / "index.html").is_file()


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX directory permission bits; see the test above",
)
def test_audit_names_a_baseline_it_could_not_rewrite(tmp_path, capsys):
    """`audit` diffs against a baseline and prints no diagnostics of its own,
    so a write it could not make has no channel to travel down -- the one
    refusal in the tool that would have been silently dropped. It names the
    file instead, and still answers its own question: the comparison is
    computed in memory, so the diff below the notice is correct.

    Needs a baseline older than the current hash definition, since that is
    the only write `audit` attempts.
    """
    cfg = _stamp_project(tmp_path)
    assert cli_mod.main(["-c", cfg, "revision", "rev-a"]) == 0
    capsys.readouterr()
    baseline = tmp_path / ".refdes" / "baselines" / "rev-a.yaml"
    baseline.write_text(
        re.sub(r", hash_format: \d+", "", baseline.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    _chmod_tree(tmp_path / ".refdes", False)
    try:
        code = cli_mod.main(["-c", cfg, "audit"])
    finally:
        _chmod_tree(tmp_path / ".refdes", True)

    out = capsys.readouterr().out
    assert "Traceback" not in out
    assert "could not write this file (read-only tree?) -- .refdes/baselines/rev-a.yaml" in out
    # Once per file, not once per comparison -- `audit` diffs the latest
    # revision and the latest release, which are the same file here.
    assert out.count(".refdes/baselines/rev-a.yaml") == 1
    assert "3 items audited" in out
    assert code == 0


@pytest.mark.skipif(
    os.name == "nt",
    reason="needs POSIX directory permission bits; see the test above",
)
def test_history_capture_refuses_a_read_only_tree_instead_of_crashing(
    tmp_path, capsys
):
    """A fourth command with a `.refdes/` write of its own, found by sweeping
    every command rather than by reading the report: `history capture`.

    It refuses under `--no-write` already, so this is not a `--no-write`
    question -- it is the same goal statement ("no command prints a traceback
    because a destination isn't writable") in a command this task did not name.
    The refusal rides the existing `HistoryError` channel every caller already
    prints as `error: <exc>`.

    The content-addressed filename in the message is asserted by prefix, not
    spelled out: the digest is a function of the item's content and would make
    this test a change-detector for unrelated edits.
    """
    cfg = _stamp_project(tmp_path)
    # The load mints keys, so this needs a writable tree first -- the point is
    # the *capture's* write, not the load's.
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    capsys.readouterr()
    _chmod_tree(tmp_path, False)
    try:
        code = cli_mod.main(["-c", cfg, "history", "capture", "REQ-001"])
    finally:
        _chmod_tree(tmp_path, True)

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Traceback" not in out
    assert "error: cannot write .refdes/history/objects/" in out
    assert "read-only tree?" in out
    assert "nothing was captured" in out
    assert "captured REQ-001" not in out
    assert code == 1
    assert not (tmp_path / ".refdes" / "history").exists()
