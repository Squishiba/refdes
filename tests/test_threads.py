"""Threads Phase 1: identity for entries with a key and no display id.

docs/design/threads.md §2 -- `project.items` re-keyed on surrogate key (or a
provisional in-memory handle for a keyless item), `Project.item_by_id()`, the
`Item.slug` fallback, and the pending-vs-permanently-id-less rule (an item
with no `id:` but a non-empty `follows:` is a real project member, not
pending). `follows:`/`followed_by:` resolution beyond ordinary link
resolution -- the chain walk, forks, cycles, coverage fallback, and thread
rendering -- is later-phase work and is deliberately not exercised here.
"""

from __future__ import annotations

import json
import os

from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import parse, render
from refdes.schema import load_project

# A minimal hand-rolled schema declaring `follows:` as an ordinary link on its
# own type -- `follows:` isn't part of any bundled standard yet (a later
# phase adds it to `log`), so this is exactly the "any project whose schema
# declares it" case the pending rule is written to generalize over.
FOLLOWS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  follows: { inverse: followed_by, label: Follows }\n"
    "types:\n"
    "  log:\n"
    "    prefix: LOG\n"
    "    label: Log entry\n"
    "    plural: Log entries\n"
    "    fields: { summary: { type: text, required: true } }\n"
    "    links: { follows: [log] }\n"
)


def _follows_project(tmp_path, items_yaml):
    write_project_config(tmp_path, FOLLOWS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def test_idless_item_with_follows_is_a_real_project_member(tmp_path):
    root = _follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: First entry.\n"
        "  - follows: [LOG-001]\n    summary: Continuation with no id.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)  # require_ids defaults True

    # Not pending, and no "run 'refdes id'" error for it -- the whole point
    # of the pending-vs-permanently-id-less rule.
    assert project.pending == []
    assert not any("run 'refdes id'" in d.message for d in project.errors)
    assert len(project.items) == 2

    continuation = next(i for i in project.items.values() if not i.id)
    assert continuation.links["follows"] == ["LOG-001"]

    # Gets a key from minting like any other item.
    written = keys_mod.mint_missing(project)
    assert len(written) == 2
    cont_key = next(key for item, key in written if item is continuation)
    assert continuation.key == cont_key

    # Durable: reparsing from disk finds the same item, still id-less, keyed.
    project2 = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project2)
    assert not project2.pending
    assert not project2.errors
    cont2 = project2.items[cont_key]
    assert cont2.id == ""
    assert cont2.key == cont_key
    assert cont2.slug == cont_key

    build_mod.build(project2)
    assert not project2.errors
    assert cont2.content_hash  # hashed exactly like an id-having item

    out = render.render_site(project2)
    assert os.path.isfile(os.path.join(out, f"{cont_key}.html"))
    log_html_path = os.path.join(out, "log.html")
    assert os.path.isfile(log_html_path)
    with open(log_html_path, encoding="utf-8") as fh:
        assert f"{cont_key}.html" in fh.read()  # listed on the log report

    payload = render.items_json(project2)
    assert any(
        e["fields"].get("summary") == "Continuation with no id." for e in payload["items"]
    )


def test_idless_item_without_follows_is_still_pending(tmp_path):
    root = _follows_project(
        tmp_path,
        "defaults: { type: log }\nitems:\n  - summary: No id, no follows either.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)

    assert len(project.pending) == 1
    assert project.pending[0].links.get("follows") in (None, [])
    assert any(
        d.message == "item has no id — run 'refdes id' to allocate one"
        for d in project.errors
    )


def test_duplicate_display_ids_still_error(tmp_path):
    root = _follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: First.\n"
        "  - id: LOG-001\n    summary: Second, same id.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)

    assert any(d.message.startswith("duplicate id 'LOG-001'") for d in project.errors)
    assert len(project.items) == 1  # the duplicate never displaces the first


IMPORT_UPSTREAM = {
    "title": "Upstream",
    "version": "1.0",
    "items": [
        {
            "id": "IFC-001",
            "type": "bound",
            "fields": {"limit": "<= 1 A"},
            "links": {},
            "content_hash": "upstreamhash",
        }
    ],
}


def test_imported_keyless_item_resolves_renders_and_links_by_display_id(tmp_path):
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "items.json").write_text(
        json.dumps(IMPORT_UPSTREAM), encoding="utf-8"
    )
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "imports:\n  - name: platform\n    items: upstream/items.json\n"
        "link_types:\n"
        "  constrained_by: { inverse: constrains, label: Constrained by }\n"
        "types:\n"
        "  bound: { prefix: IFC, fields: { limit: { type: limit, required: true } } }\n"
        "  decision:\n"
        "    prefix: DEC\n"
        "    fields: { title: { type: text, required: true } }\n"
        "    links: { constrained_by: [bound] }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n  - id: DEC-001\n    title: Uses the import.\n"
        "    constrained_by: [IFC-001]\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors

    upstream = project.item_by_id("IFC-001")
    assert upstream is not None
    assert upstream.external is True
    assert upstream.key == ""  # imports carry no key -- a disclosed gap
    assert project.item_by_id("DEC-001").resolved_links["constrained_by"] == ["IFC-001"]

    out = render.render_site(project)
    assert os.path.isfile(os.path.join(out, "ifc-001.html"))


def test_no_write_keyless_item_resolves_renders_and_links_by_display_id(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "link_types:\n"
        "  satisfies: { inverse: satisfied_by, label: Satisfies }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n"
        "  decision:\n"
        "    prefix: DEC\n"
        "    fields: { title: { type: text, required: true } }\n"
        "    links: { satisfies: [requirement] }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A.\n",
        encoding="utf-8",
    )
    (items / "d.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n  - id: DEC-001\n    title: Uses it.\n    satisfies: [REQ-001]\n",
        encoding="utf-8",
    )

    class Args:
        config = str(tmp_path / "refdes-project.yaml")
        no_write = True

    project, _stale = cli_mod._load(Args())
    assert not project.errors
    req = project.item_by_id("REQ-001")
    assert req is not None
    assert req.key == ""  # --no-write suppressed minting

    build_mod.build(project)  # cli._load() only parses/mints/expands, never builds
    assert not project.errors
    assert project.item_by_id("DEC-001").resolved_links["satisfies"] == ["REQ-001"]
    out = render.render_site(project)
    assert os.path.isfile(os.path.join(out, "req-001.html"))

    text = (items / "r.yaml").read_text(encoding="utf-8")
    assert "key:" not in text  # --no-write: nothing under items/ was touched


def test_item_by_id_helper(tmp_path):
    root = _follows_project(
        tmp_path,
        "defaults: { type: log }\nitems:\n  - id: LOG-001\n    summary: Only one.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)

    item = project.item_by_id("LOG-001")
    assert item is not None and item.id == "LOG-001"
    assert project.item_by_id("LOG-999") is None
    assert project.item_by_id("") is None


def test_no_provisional_handle_ever_appears_in_a_written_file(tmp_path):
    root = _follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: First entry.\n"
        "  - follows: [LOG-001]\n    summary: Continuation with no id.\n",
    )

    class Args:
        config = str(root / "refdes-project.yaml")
        no_write = True  # keep the continuation entry's handle provisional

    project, _stale = cli_mod._load(Args())
    handles = [h for h in project.items if h.startswith("~")]
    assert handles  # the continuation entry is indeed provisional-handled here

    build_mod.build(project)
    project.out_dir = str(root / "_site")
    render.render_site(project)

    for dirpath, _dirs, filenames in os.walk(str(root)):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            for handle in handles:
                assert handle not in text
