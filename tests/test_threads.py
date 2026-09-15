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
    "    append_only: true\n"
    "    fields:\n"
    "      summary: { type: text, required: true }\n"
    "      date: { type: date }\n"
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


# ---------------------------------------------------- Phase 2a: follows freezing


def _minted_follows_project(tmp_path, items_yaml):
    root = _follows_project(tmp_path, items_yaml)
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    keys_mod.mint_missing(project)
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    return root, project


def _check(root, *, no_write=False):
    args = ["-c", str(root / "refdes-project.yaml")]
    if no_write:
        args.append("--no-write")
    return cli_mod.main([*args, "check"])


def test_follows_freezes_to_the_current_tip_not_the_authored_head(tmp_path):
    root, project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: Middle.\n"
        "    follows: [placeholder-middle]\n"
        "  - follows: [placeholder-tail]\n    summary: Tail.\n"
        "  - id: LOG-004\n    summary: New.\n    follows: [LOG-001]\n",
    )
    head = project.item_by_id("LOG-001")
    middle = project.item_by_id("LOG-002")
    tail = next(item for item in project.local_items if not item.id)
    path = root / "items" / "log.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("placeholder-middle", f"LOG-001@{head.key}")
        .replace("placeholder-tail", middle.key),
        encoding="utf-8",
    )

    assert _check(root) == 0
    text = path.read_text(encoding="utf-8")
    assert f"follows: [LOG-002@{middle.key}]" not in text
    assert f"follows: [{tail.key}]" in text


def test_follows_freezes_to_a_bare_key_for_an_idless_tip_and_resolves_it(tmp_path):
    root, project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - follows: [placeholder]\n    summary: Id-less tip.\n"
        "  - id: LOG-003\n    summary: New.\n    follows: [LOG-001]\n",
    )
    head = project.item_by_id("LOG-001")
    tip = next(item for item in project.local_items if not item.id)
    path = root / "items" / "log.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("placeholder", f"LOG-001@{head.key}"),
        encoding="utf-8",
    )

    assert _check(root) == 0
    refreshed = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(refreshed)
    build_mod.build(refreshed)
    assert not refreshed.errors
    assert refreshed.item_by_id("LOG-003").links["follows"] == [tip.key]
    assert refreshed.item_by_id("LOG-003").resolved_links["follows"] == [""]


def test_bare_key_follows_reports_malformed_and_unknown_key_layers(tmp_path):
    valid_unknown = keys_mod.mint()
    malformed = valid_unknown[:-1] + ("0" if valid_unknown[-1] != "0" else "1")
    root = _follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        f"  - id: LOG-002\n    summary: Broken.\n    follows: [{malformed}]\n"
        f"  - id: LOG-003\n    summary: Missing.\n    follows: [{valid_unknown}]\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    messages = [diagnostic.message for diagnostic in project.errors]
    assert any(malformed in message and "malformed" in message for message in messages)
    assert any(valid_unknown in message and "which no item declares" in message for message in messages)


def test_forked_follows_stays_bare_and_names_every_tip(tmp_path, capsys):
    root, project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: Fork A.\n    follows: [placeholder-a]\n"
        "  - id: LOG-003\n    summary: Fork B.\n    follows: [placeholder-b]\n"
        "  - id: LOG-004\n    summary: New.\n    follows: [LOG-001]\n",
    )
    head = project.item_by_id("LOG-001")
    path = root / "items" / "log.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("placeholder-a", f"LOG-001@{head.key}")
        .replace("placeholder-b", f"LOG-001@{head.key}"),
        encoding="utf-8",
    )
    before = path.read_bytes()

    assert _check(root) == 0
    output = capsys.readouterr().out
    assert path.read_bytes() == before
    assert "LOG-002" in output and "LOG-003" in output
    assert "pick one or list several to merge" in output.lower()


def test_same_load_follows_freeze_in_date_then_source_order(tmp_path):
    root, project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    date: 2026-01-01\n    summary: Head.\n"
        "  - id: LOG-003\n    date: 2026-01-03\n    summary: Third.\n    follows: [LOG-001]\n"
        "  - id: LOG-002\n    date: 2026-01-02\n    summary: Second.\n    follows: [LOG-001]\n"
        "  - id: LOG-004\n    date: 2026-01-04\n    summary: Fourth.\n    follows: [LOG-001]\n",
    )
    assert _check(root) == 0
    reparsed = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(reparsed)
    assert reparsed.item_by_id("LOG-002").links["follows"] == [
        f"LOG-001@{project.item_by_id('LOG-001').key}"
    ]
    assert reparsed.item_by_id("LOG-003").links["follows"] == [
        f"LOG-002@{project.item_by_id('LOG-002').key}"
    ]
    assert reparsed.item_by_id("LOG-004").links["follows"] == [
        f"LOG-003@{project.item_by_id('LOG-003').key}"
    ]


def test_new_follows_entry_never_freezes_against_itself(tmp_path):
    root, project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: New.\n    follows: [LOG-001]\n",
    )

    assert _check(root) == 0
    text = (root / "items" / "log.yaml").read_text(encoding="utf-8")
    assert f"follows: [LOG-001@{project.item_by_id('LOG-001').key}]" in text
    assert f"LOG-002@{project.item_by_id('LOG-002').key}" not in text


def test_rename_refreshes_frozen_follows_label_without_hash_churn(tmp_path):
    root, project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: New.\n    follows: [LOG-001]\n",
    )
    assert _check(root) == 0
    before = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(before)
    build_mod.build(before)
    hash_before = before.item_by_id("LOG-002").content_hash
    path = root / "items" / "log.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("id: LOG-001", "id: LOG-009"),
        encoding="utf-8",
    )

    assert _check(root) == 0
    after = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(after)
    build_mod.build(after)
    assert after.item_by_id("LOG-002").content_hash == hash_before
    assert f"follows: [LOG-009@{project.item_by_id('LOG-001').key}]" in path.read_text(
        encoding="utf-8"
    )


def test_no_write_leaves_bare_follows_and_second_writable_load_is_idempotent(tmp_path):
    root, _project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: New.\n    follows: [LOG-001]\n",
    )
    path = root / "items" / "log.yaml"
    before = path.read_bytes()

    assert _check(root, no_write=True) == 0
    assert path.read_bytes() == before
    assert _check(root) == 0
    frozen = path.read_bytes()
    assert _check(root) == 0
    assert path.read_bytes() == frozen


def test_sealed_append_only_follows_is_not_rewritten(tmp_path, capsys):
    root, _project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: New.\n    follows: [LOG-001]\n",
    )
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "build"]) == 0
    path = root / "items" / "log.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(text.split("follows: [", 1)[1].split("]", 1)[0], "LOG-001"),
        encoding="utf-8",
    )
    before = path.read_bytes()

    assert _check(root) == 0
    assert path.read_bytes() == before
    assert "already sealed" in capsys.readouterr().out


def test_ordinary_addresses_still_expands_to_a_named_target_key(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "link_types:\n"
        "  addresses: { inverse: addressed_by, label: Addresses }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields: { text: { type: text, required: true } }\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    fields: { summary: { type: text, required: true } }\n"
        "    links: { addresses: [requirement] }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    path = items / "items.yaml"
    path.write_text(
        "items:\n"
        "  - id: REQ-001\n    type: requirement\n    text: Target\n"
        "  - id: LOG-001\n    type: log\n    summary: Investigated\n"
        "    addresses: [REQ-001]\n",
        encoding="utf-8",
    )

    assert _check(tmp_path) == 0
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    target = project.item_by_id("REQ-001")
    assert f"addresses: [REQ-001@{target.key}]" in path.read_text(encoding="utf-8")


def test_same_date_follows_freeze_uses_source_file_order(tmp_path):
    write_project_config(tmp_path, FOLLOWS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "head.yaml").write_text(
        "defaults: { type: log }\nitems:\n"
        "  - id: LOG-001\n    date: 2026-01-01\n    summary: Head\n",
        encoding="utf-8",
    )
    (items / "a.yaml").write_text(
        "defaults: { type: log }\nitems:\n"
        "  - id: LOG-003\n    date: 2026-01-02\n    summary: First by file\n"
        "    follows: [LOG-001]\n",
        encoding="utf-8",
    )
    (items / "b.yaml").write_text(
        "defaults: { type: log }\nitems:\n"
        "  - id: LOG-002\n    date: 2026-01-02\n    summary: Second by file\n"
        "    follows: [LOG-001]\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys_mod.mint_missing(project)

    assert _check(tmp_path) == 0
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    assert project.item_by_id("LOG-002").links["follows"] == [
        f"LOG-003@{project.item_by_id('LOG-003').key}"
    ]


def test_follows_freeze_deduplicates_matching_merge_targets(tmp_path):
    root, project = _minted_follows_project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: Merge.\n    follows: [LOG-001, LOG-001]\n",
    )

    assert _check(root) == 0
    text = (root / "items" / "log.yaml").read_text(encoding="utf-8")
    frozen = f"LOG-001@{project.item_by_id('LOG-001').key}"
    assert text.count(frozen) == 1
