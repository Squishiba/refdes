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

from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import ids, keys, parse, revise
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
