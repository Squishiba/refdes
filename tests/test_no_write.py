"""Global ``--no-write`` coverage (docs/design/keys.md §2, §9 item 4).

With ``--no-write``, any command that is not itself an explicit output
command must leave the project tree -- ``items/``, ``.refdes/``, and the two
config files -- byte-identical. The site output directory is `build`'s own
product and stays outside the snapshot (keys.md §2: "refdes build --no-write
still writes `_site/`"); this fixture points ``site.out`` outside the project
tree so the snapshot below is complete.
"""

from __future__ import annotations

import hashlib
import os

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod

# The fixture project: boards registry, an append-only log type (seals), a
# keyless item, a bare link to a keyed target, a citation, and -- after
# `_snapshot_project` runs -- a stale `.refdes/schema.json` and one stamped
# baseline. The dirty state (keyless item, bare link, unsealed log, absent
# membership manifest) is *appended after* the baseline stamp so a writable
# load still has every suppression-worthy write pending at snapshot time.

NW_SCHEMA = """\
site:
  title: "No-write test"
  out: ../{site_out}
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  satisfies: {{ inverse: satisfied_by, label: Satisfies }}
  follows: {{ inverse: followed_by, label: Follows }}
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: {{ type: text, required: true }}
  decision:
    prefix: DEC
    fields:
      title: {{ type: text, required: true }}
    links:
      satisfies: [requirement]
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: {{ type: text, required: true }}
    links:
      follows: [log]
  component:
    prefix: CMP
    fields:
      title: {{ type: text, required: true }}
      datasheets: {{ type: citations }}
"""


def _snapshot(root):
    """relpath -> sha256 of bytes, for every file under the project tree."""
    files = {}
    for dirpath, _dirnames, names in os.walk(str(root)):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, str(root)).replace("\\", "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


def _snapshot_project(tmp_path):
    write_project_config(tmp_path, NW_SCHEMA.format(site_out=f"site_out_{tmp_path.name}"))
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, board: board-a }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Seeded requirement.\n",
        encoding="utf-8",
    )
    (items / "d.yaml").write_text(
        "defaults: { type: decision, board: board-a }\n"
        "items:\n"
        "  - id: DEC-001\n    title: Seeded decision.\n    satisfies: [REQ-001]\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")

    # One writable run: mints REQ-001's key, expands DEC-001's link, and
    # stamps a baseline (`revision` builds with seal_write=False, so no seal
    # or membership manifest exists yet -- `build` below must not create them
    # under --no-write).
    assert cli_mod.main(["-c", config, "revision", "rev-a"]) == 0

    # Re-dirty: everything a writable load would write is pending again.
    with open(items / "r.yaml", "a", encoding="utf-8") as fh:
        fh.write("  - id: REQ-002\n    text: Keyless item, pending a mint.\n")
    with open(items / "d.yaml", "a", encoding="utf-8") as fh:
        fh.write(
            "  - id: DEC-002\n    title: Bare link, pending expansion.\n"
            "    satisfies: [REQ-001]\n"
        )
    (items / "log.yaml").write_text(
        "defaults: { type: log, board: board-a }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Unsealed entry.\n"
        "  - id: LOG-002\n    summary: Follows LOG-001.\n"
        "    follows: [LOG-001]\n",
        encoding="utf-8",
    )
    (items / "cmp.yaml").write_text(
        "defaults: { type: component, board: board-a }\n"
        "items:\n"
        "  - id: CMP-001\n    title: TPS62913.\n"
        "    datasheets:\n      - path: https://example.com/datasheet.pdf\n",
        encoding="utf-8",
    )
    # A calc `source()` line whose CSV has drifted from its lockfile pin, so
    # check/build exercise the loud-drift path (which reads the file) and must
    # still write nothing (docs/design/calc-sources.md section 9, --no-write).
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis" / "b.csv").write_text("key,value\nk,3\n", encoding="utf-8")
    (items / "src.md").write_text(
        "---\nid: CMP-002\ntype: component\nboard: board-a\ntitle: Sourced.\n"
        "datasheets:\n  - path: analysis/b.csv\n---\n\n"
        '```calc\nP = source("analysis/b.csv", "k") | W\n```\n',
        encoding="utf-8",
    )
    refdes_dir = tmp_path / ".refdes"
    refdes_dir.mkdir(exist_ok=True)
    (refdes_dir / "citations.yaml").write_text(
        "citations:\n"
        "  https://example.com/datasheet.pdf:\n"
        "    sha256: deadbeef\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        "  analysis/b.csv:\n"
        "    sha256: deadbeef\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        "    values:\n"
        "      k: {reader: csv, value: '2'}\n",
        encoding="utf-8",
    )
    # A schema.json older than both config files: every _load() command
    # regenerates it.
    schema_json = refdes_dir / "schema.json"
    schema_json.write_text('{"stale": true}\n', encoding="utf-8")
    old = 1577836800  # 2020-01-01
    os.utime(schema_json, (old, old))
    return tmp_path, config


# Every command that loads the project without being an explicit write
# command. `revision`/`release` are here too: under --no-write they may
# report what they would stamp, but the baseline file must not appear.
READ_TYPE_COMMANDS = [
    ["check"],
    ["build"],
    ["audit"],
    ["index"],
    ["ls"],
    ["schema"],
    ["new", "decision"],
    ["former-ids", "propose"],
    ["revision", "rev-under-no-write"],
    ["release", "rel-under-no-write"],
]


def _changed(before, root):
    after = _snapshot(root)
    gone = sorted(set(before) - set(after))
    new = sorted(set(after) - set(before))
    moved = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return {"removed": gone, "added": new, "modified": moved}


def _run_no_write(config, argv):
    return cli_mod.main(["-c", config, "--no-write"] + argv)


def test_snapshot_project_starts_with_pending_writes(tmp_path, capsys):
    """Guard for the guard: the fixture really does have every write pending
    -- keyless item, bare link, unsealed log, absent manifest, stale
    schema.json -- so a passing --no-write run below means suppression, not
    an already-clean tree."""
    root, config = _snapshot_project(tmp_path)
    assert not (root / ".refdes" / "log-seal-board-a.yaml").exists()
    assert not (root / ".refdes" / "boards.yaml").exists()
    # REQ-001 was minted by the fixture's writable run; the appended REQ-002
    # is still keyless, and DEC-002's link to the keyed REQ-001 is still bare.
    assert (root / "items" / "r.yaml").read_text(encoding="utf-8").count("key:") == 1
    assert "satisfies: [REQ-001]" in (root / "items" / "d.yaml").read_text(encoding="utf-8")
    capsys.readouterr()

    # A writable check fixes all of it, proving the state was pending.
    assert cli_mod.main(["-c", config, "check"]) == 0
    assert (root / "items" / "r.yaml").read_text(encoding="utf-8").count("key:") == 2
    assert "satisfies: [REQ-001]" not in (root / "items" / "d.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize("argv", READ_TYPE_COMMANDS, ids=lambda a: "-".join(a))
def test_no_write_leaves_whole_project_tree_byte_identical(tmp_path, capsys, argv):
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, argv)
    assert status in (0, 1), f"{' '.join(argv)} crashed with exit {status}"
    changes = _changed(before, root)
    assert not any(changes.values()), (
        f"--no-write {' '.join(argv)} touched the project tree: {changes}"
    )


# ------------------------------------------------------------- history (H2)


def test_no_write_does_not_capture_follows_history(tmp_path, capsys):
    """Living notes phase H2: the `follows:` freeze is also a capture, and
    `--no-write` gates it exactly like the freeze itself -- nothing appears
    under `.refdes/history/` until a writable load freezes the edge."""
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    assert _run_no_write(config, ["check"]) == 0
    assert not any(_changed(before, root).values())
    assert not (root / ".refdes" / "history").exists()

    # The same load without the gate freezes the edge and captures: one
    # event, announced on stderr, nothing else in the store.
    assert cli_mod.main(["-c", config, "check"]) == 0
    err = capsys.readouterr().err
    assert "captured LOG-001: LOG-002 now follows it" in err
    events = list((root / ".refdes" / "history" / "events").glob("*.yaml"))
    assert len(events) == 1


def test_no_write_reports_edited_after_captured_without_touching_the_tree(
    tmp_path, capsys
):
    """Living notes phase H3: the edited-after-captured diagnostic reads the
    history store and never writes it -- under `--no-write` it still reports
    (a warning, exit unchanged), with the whole tree including
    `.refdes/history/` byte-identical."""
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    # A writable check freezes the LOG-002 -> LOG-001 edge and captures it.
    assert cli_mod.main(["-c", config, "check"]) == 0
    capsys.readouterr()

    # The author edits the captured entry after the fact.
    log = root / "items" / "log.yaml"
    log.write_text(
        log.read_text(encoding="utf-8").replace(
            "summary: Unsealed entry.", "summary: Edited after capture."
        ),
        encoding="utf-8",
    )
    before = _snapshot(root)

    assert _run_no_write(config, ["check"]) == 0
    out = capsys.readouterr().out
    assert "edited after captured" in out
    assert not any(_changed(before, root).values())


# ---------------------------------------------------------------- explicit
# write commands: each honors --no-write (reports what would change, writes
# nothing) or refuses with exit 2 -- none may write silently.


def test_id_under_no_write_reports_allocation_and_writes_nothing(tmp_path, capsys):
    root, config = _snapshot_project(tmp_path)
    with open(root / "items" / "r.yaml", "a", encoding="utf-8") as fh:
        fh.write("  - text: No id yet, pending allocation.\n")
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, ["id"])
    out = capsys.readouterr().out
    assert status == 0
    assert "would allocate" in out
    assert not any(_changed(before, root).values())


def test_fetch_under_no_write_refuses(tmp_path, capsys):
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, ["fetch"])
    err = capsys.readouterr().err
    assert status == 2
    assert "refusing" in err
    assert not any(_changed(before, root).values())


def test_keys_adopt_under_no_write_reports_plan_without_writing(tmp_path, capsys):
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, ["keys", "adopt"])
    out = capsys.readouterr().out
    assert status == 0
    assert "would mint" in out
    assert not any(_changed(before, root).values())


def test_revise_under_no_write_reports_plan_without_writing(tmp_path, capsys):
    root, config = _snapshot_project(tmp_path)
    (tmp_path / "map.yaml").write_text("prefixes: {DEC: DCN}\n", encoding="utf-8")
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, ["revise", str(tmp_path / "map.yaml")])
    captured = capsys.readouterr()
    assert status in (0, 1)
    assert "would" in captured.out + captured.err
    assert not any(_changed(before, root).values())


def test_standard_upgrade_under_no_write_refuses(tmp_path, capsys):
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, ["standard", "upgrade", "--to", "99"])
    err = capsys.readouterr().err
    assert status == 2
    assert "refusing" in err
    assert not any(_changed(before, root).values())


def test_standard_add_preset_under_no_write_refuses(tmp_path, capsys):
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, ["standard", "add-preset", "aviation"])
    err = capsys.readouterr().err
    assert status == 2
    assert "refusing" in err
    assert not any(_changed(before, root).values())


def test_standard_remove_preset_under_no_write_refuses(tmp_path, capsys):
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, ["standard", "remove-preset", "aviation"])
    err = capsys.readouterr().err
    assert status == 2
    assert "refusing" in err
    assert not any(_changed(before, root).values())


def test_init_under_no_write_refuses(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    status = cli_mod.main(["--no-write", "init"])
    capsys.readouterr()
    assert status == 2
    assert not (tmp_path / "refdes-project.yaml").exists()
    assert not (tmp_path / ".vscode").exists()


def test_stub_tests_under_no_write_reports_stubs_without_writing(tmp_path, capsys):
    from helpers import BLOCKS_ITEMS, BLOCKS_SCHEMA

    write_project_config(tmp_path, BLOCKS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in BLOCKS_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    (tmp_path / "pages").mkdir()
    config = str(tmp_path / "refdes-project.yaml")
    capsys.readouterr()
    before = _snapshot(tmp_path)

    status = _run_no_write(config, ["stub-tests"])
    out = capsys.readouterr().out
    assert status == 0
    assert "would write" in out
    assert not any(_changed(before, tmp_path).values())


def test_former_ids_confirm_under_no_write_refuses(tmp_path, capsys):
    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    status = _run_no_write(config, ["former-ids", "propose", "--confirm", "REQ-001"])
    err = capsys.readouterr().err
    assert status == 2
    assert "refusing" in err
    assert not any(_changed(before, root).values())


# ---------------------------------------------------------------- the editor's
# read path (docs/design/browser-editor.md, Slice 0): loader.load_readonly is
# the one side-effect-free load/build entry point the browser editor consumes.


def test_load_readonly_leaves_whole_project_tree_byte_identical(tmp_path, capsys):
    from refdes import loader

    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    project = loader.load_readonly(config)
    assert project.item_by_id("REQ-002").key == ""  # keyless, and stayed so
    assert project.item_by_id("LOG-001") is not None
    assert not any(_changed(before, root).values())


def test_load_readonly_overlay_shows_candidate_without_touching_disk(tmp_path, capsys):
    from refdes import loader

    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)
    path = root / "items" / "r.yaml"
    candidate = path.read_text(encoding="utf-8").replace(
        "Keyless item, pending a mint.", "Edited in memory only."
    )

    project = loader.load_readonly(config, overlay={str(path): candidate})
    assert project.item_by_id("REQ-002").fields["text"] == "Edited in memory only."
    assert project.item_by_id("REQ-001").fields["text"] == "Seeded requirement."
    assert not any(_changed(before, root).values())

    # ...and the same load without the overlay sees the file as it is.
    assert loader.load_readonly(config).item_by_id("REQ-002").fields["text"] == (
        "Keyless item, pending a mint."
    )


def test_load_readonly_overlay_can_introduce_a_new_source_file(tmp_path, capsys):
    from refdes import loader

    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)
    new_path = root / "items" / "extra" / "new.yaml"

    project = loader.load_readonly(
        config,
        overlay={
            str(new_path): (
                "defaults: { type: requirement, board: board-a }\n"
                "items:\n  - id: REQ-777\n    text: Only in the overlay.\n"
            )
        },
    )
    assert project.item_by_id("REQ-777") is not None
    assert not new_path.exists()
    assert not any(_changed(before, root).values())


def test_load_tree_refuses_an_overlay_combined_with_writes(tmp_path):
    from refdes import loader

    root, config = _snapshot_project(tmp_path)
    with pytest.raises(ValueError):
        loader.load_tree(config, write=True, overlay={str(root / "items" / "r.yaml"): ""})


def test_the_editor_get_and_preview_paths_leave_the_tree_byte_identical(tmp_path, capsys):
    """`refdes serve`'s own reads -- the launch redirect, the rendered preview,
    the editor shell and assets, every API GET, and a rebuild after an outside
    edit -- must not mint a key, expand a link, seal an entry, or write
    schema.json. The fixture has all of those pending (keyless REQ-002, a bare
    link on DEC-002, an unsealed log, a stale schema.json)."""
    import http.client

    from refdes.serve import security
    from refdes.serve.server import EditorApp

    root, config = _snapshot_project(tmp_path)
    capsys.readouterr()
    before = _snapshot(root)

    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        assert not any(_changed(before, root).values()), "the launch load wrote"

        def get(path, **headers):
            conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
            headers.setdefault("Host", f"127.0.0.1:{app.port}")
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp.status

        cookie = {"Cookie": f"{security.cookie_name(app.port)}={app.token}"}
        api = {"X-Refdes-Token": app.token}
        assert get(f"/?token={app.token}") == 302
        for path in ("/preview/", "/preview/summary.html", "/preview/coverage.html", "/edit/",
                     "/edit/static/app.js"):
            assert get(path, **cookie) == 200, path
        for key in app.state.snapshot.project.items:
            slug = app.state.snapshot.project.items[key].slug
            assert get(f"/preview/{slug}.html", **cookie) == 200
        assert get("/api/revision", **api) == 200

        # the read-side editor API (Slice 1 chunk 2): filtered lists, every
        # facet, and an item view per item -- all must stay side-effect-free
        # (no mint, no expansion, no seal, no schema.json), including the
        # item view's seal check, which reads .refdes/ seal files.
        import json as _json
        from urllib.parse import quote

        def get_body(path, **headers):
            conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
            headers.setdefault("Host", f"127.0.0.1:{app.port}")
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            assert resp.status == 200, path
            return _json.loads(data)

        list_paths = [
            "/api/items",
            "/api/items?type=requirement",
            "/api/items?board=board-a&stage=open",
            "/api/items?check=none&blocked=no",
            "/api/items?q=rail",
            "/api/items?links_to=REQ-001",
            "/api/items?linked_from=DEC-001",
        ]
        for path in list_paths:
            assert get(path, **api) == 200, path
        for row in get_body("/api/items", **api)["items"]:
            assert get(f"/api/item/{quote(row['handle'], safe='')}", **api) == 200
        for ref in ("REQ-001", "DEC-001", "LOG-001"):
            assert get(f"/api/item/{ref}", **api) == 200

        # an outside edit, then the poll-triggered rebuild and re-render
        with open(root / "items" / "r.yaml", "a", encoding="utf-8") as fh:
            fh.write("  - id: REQ-003\n    text: Added from outside.\n")
        edited = _snapshot(root)
        assert app.state.refresh() is True
        assert get("/preview/", **cookie) == 200
        assert _snapshot(root) == edited, "the rebuild wrote into the project"
    finally:
        app.stop()
    assert _snapshot(root) == edited
