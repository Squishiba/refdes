"""Navis slice 3: the archive store (in-prog-logs/navis-design-20261025.md §6, §8, §9, §12, §13).

One gzip record per Navi under `.refdes/navis/` (design §6 B, §8 gzip), the
§9 state table over the merged projection (live marker / marker+record /
record-without-marker -> `navis.archived_orphan` / marker text edited after
archive), the §7.3 hard invariant (archive/restore write NOTHING outside
`.refdes/navis/` -- item bytes, content hashes, seal files and history
events are byte-identical through both verbs), the §12 journal refusal, and
the writer's concurrency/crash posture: one lock per store write (the
`write_lock.project_write_lock` every existing writer takes), atomic
temp+replace writes, real subprocesses archiving concurrently, and a
simulated kill mid-write.

The store reader is adversarial by contract: a corrupt, truncated,
foreign-format, keyless or unreadable record is a clear diagnostic naming
its file -- never a crash, never a silent loss of the rest of the store.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import subprocess
import sys
import tarfile

import pytest
import yaml
from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import loader, navis, navis_archive

SRC = str((os.path.dirname(__file__) + "/../src").replace("\\", "/"))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SCHEMA = (
    "site: { title: Navis Archive, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
    "  memo:\n"
    "    prefix: MEMO\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: ignore }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    append_only: true\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

MARKERS = {
    "note-a.md": (
        "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\n"
        "intro\n<!--navi: Model worst-case copper temperature.-->\n"
    ),
    "note-b.md": (
        "---\nid: NOTE-002\ntype: note\ntitle: Decoupling\n---\n"
        "<!--navi: Recheck decoupling near U14.-->\n"
    ),
}


def _setup(tmp_path, files=None, schema=SCHEMA):
    config = write_project_config(tmp_path, schema)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in (files if files is not None else MARKERS).items():
        (items / name).write_text(text, encoding="utf-8")
    return str(config)


def _load(config, write=True):
    project, _stale = loader.load_tree(str(config), write=write)
    return project


def _rows(project):
    build_mod.build(project, seal_write=False, reseal=False)
    return navis.projection(project)


def _run(config, *args):
    return cli_mod.main(["-c", config, *args])


def _navi_keys(tmp_path):
    """The marker keys as minted on a writable load, in ls order."""
    import re

    keyed = re.compile(r"<!--navi:([0-9a-z]{11}) ")
    out = []
    for name in sorted(os.listdir(tmp_path / "items")):
        out += keyed.findall(
            (tmp_path / "items" / name).read_text(encoding="utf-8")
        )
    return out


def _record_bytes(tmp_path, key):
    return (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").read_bytes()


def _record_dict(tmp_path, key):
    path = tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz"
    return yaml.safe_load(gzip.decompress(path.read_bytes()).decode("utf-8"))


def _store_paths(root):
    """Every regular file under the project, {relpath: sha256}, the lock
    file excluded (`.refdes-write.lock` is the lock primitive's own, not
    project content)."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "_site")]
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            if rel == ".refdes-write.lock":
                continue
            with open(path, "rb") as fh:
                out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out


# ---------------------------------------------------------------------------
# the record format (design §6, §8)
# ---------------------------------------------------------------------------


def test_archive_writes_one_gzip_record_named_by_the_navi_key(tmp_path):
    config = _setup(tmp_path)
    project = _load(config)
    rows = _rows(project)
    key = rows[0]["key"]
    created, record = navis_archive.archive_record(
        str(tmp_path),
        navi_key=key,
        item_key=rows[0]["source"]["key"],
        source={"file": rows[0]["source"]["file"], "line": rows[0]["source"]["line"]},
        text=rows[0]["text"],
    )
    assert created is True
    path = tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz"
    assert path.exists()
    data = _record_dict(tmp_path, key)
    assert data["archive_format"] == navis_archive.ARCHIVE_FORMAT
    assert data["navi_key"] == key
    assert data["item_key"] == rows[0]["source"]["key"]
    assert data["text"] == "Model worst-case copper temperature."
    # The line is the live scan position (the writable load mints item keys
    # too, which shifts front matter by one line -- assert against the
    # projection, not a literal).
    assert data["source"] == {
        "file": "items/note-a.md",
        "line": rows[0]["source"]["line"],
    }
    assert data["archived_at"].endswith("Z")
    # gzip: the raw bytes are not the YAML (the owner mandated compression)
    assert path.read_bytes()[:2] == b"\x1f\x8b"
    assert record.navi_key == key


def test_record_filename_stem_is_the_full_key_and_the_file_gz(tmp_path):
    config = _setup(tmp_path)
    project = _load(config)
    rows = _rows(project)
    navis_archive.archive_record(
        str(tmp_path), navi_key=rows[0]["key"], item_key="",
        source={"file": "items/note-a.md", "line": 7}, text="x",
    )
    names = os.listdir(tmp_path / ".refdes" / "navis")
    assert names == [f"{rows[0]['key']}.yaml.gz"]


def test_archive_is_idempotent_the_record_is_never_rewritten(tmp_path):
    config = _setup(tmp_path)
    project = _load(config)
    rows = _rows(project)
    key = rows[0]["key"]
    args = {
        "navi_key": key,
        "item_key": "",
        "source": {"file": "items/note-a.md", "line": 7},
        "text": "Model worst-case copper temperature.",
    }
    created1, _ = navis_archive.archive_record(str(tmp_path), **args)
    first = _record_bytes(tmp_path, key)
    created2, _ = navis_archive.archive_record(str(tmp_path), **args)
    assert created1 is True and created2 is False
    assert _record_bytes(tmp_path, key) == first  # byte-identical, not re-stamped


def test_restore_removes_the_record_and_is_idempotent(tmp_path):
    config = _setup(tmp_path)
    project = _load(config)
    rows = _rows(project)
    key = rows[0]["key"]
    navis_archive.archive_record(
        str(tmp_path), navi_key=key, item_key="",
        source={"file": "items/note-a.md", "line": 7}, text="x",
    )
    assert navis_archive.restore_record(str(tmp_path), key) is True
    assert not (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").exists()
    assert navis_archive.restore_record(str(tmp_path), key) is False


# ---------------------------------------------------------------------------
# the §9 state table, over the merged projection
# ---------------------------------------------------------------------------


def _archive_cli(tmp_path, selector):
    return _run(str(tmp_path / "refdes-project.yaml"), "navis", "archive", selector)


def test_state_marker_no_record_is_active(tmp_path):
    config = _setup(tmp_path)
    rows = _rows(_load(config))
    assert [r["archived"] for r in rows] == [False, False]


def test_state_marker_plus_record_is_archived_with_snapshot(tmp_path):
    config = _setup(tmp_path)
    _load(config)  # mint
    assert _archive_cli(tmp_path, "1") == 0
    rows = _rows(_load(config, write=False))
    archived = [r for r in rows if r["archived"]]
    assert len(archived) == 1
    row = archived[0]
    assert row["text"] == "Model worst-case copper temperature."
    assert row["snapshot"]["text"] == "Model worst-case copper temperature."
    assert row["text_changed"] is False
    assert row["source"]["file"] == "items/note-a.md"
    active = [r for r in rows if not r["archived"]]
    assert [r["text"] for r in active] == ["Recheck decoupling near U14."]


def test_state_record_without_marker_is_archived_orphan(tmp_path):
    config = _setup(tmp_path)
    _load(config)  # mint
    key = _navi_keys(tmp_path)[0]
    _archive_cli(tmp_path, key)
    # hand-delete the marker from the source
    note = tmp_path / "items" / "note-a.md"
    note.write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\nintro\n",
        encoding="utf-8",
    )
    project = _load(config, write=False)
    rows = _rows(project)
    row = next(r for r in rows if r["key"] == key)
    assert row["archived"] is True
    assert row["source"]["marker_found"] is False
    assert row["text"] == "Model worst-case copper temperature."  # snapshot
    assert row["source"]["file"] == "items/note-a.md"  # stored snapshot source
    orphans = [
        d for d in project.diagnostics
        if d.code == navis_archive.NAVI_ARCHIVED_ORPHAN_CODE
    ]
    assert len(orphans) == 1
    assert key in str(orphans[0])
    assert ".refdes/navis" in (orphans[0].file or "")


def test_state_marker_text_edited_after_archive_shows_note(tmp_path):
    config = _setup(tmp_path)
    _load(config)  # mint
    key = _navi_keys(tmp_path)[0]
    _archive_cli(tmp_path, key)
    note = tmp_path / "items" / "note-a.md"
    text = note.read_text(encoding="utf-8")
    note.write_text(text.replace("Model worst-case copper temperature.",
                                 "EDITED copper model"), encoding="utf-8")
    rows = _rows(_load(config, write=False))
    row = next(r for r in rows if r["key"] == key)
    assert row["archived"] is True
    assert row["text"] == "EDITED copper model"  # live marker text
    assert row["snapshot"]["text"] == "Model worst-case copper temperature."
    assert row["text_changed"] is True


def test_restore_round_trip_the_marker_is_active_with_current_text(tmp_path):
    config = _setup(tmp_path)
    _load(config)
    key = _navi_keys(tmp_path)[0]
    _archive_cli(tmp_path, key)
    assert _run(config, "navis", "restore", key) == 0
    rows = _rows(_load(config, write=False))
    assert all(r["archived"] is False for r in rows)
    row = next(r for r in rows if r["key"] == key)
    assert row["text"] == "Model worst-case copper temperature."


def test_record_deleted_by_hand_the_marker_is_active_again(tmp_path):
    config = _setup(tmp_path)
    _load(config)
    key = _navi_keys(tmp_path)[0]
    _archive_cli(tmp_path, key)
    (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").unlink()
    rows = _rows(_load(config, write=False))
    assert [r["archived"] for r in rows] == [False, False]


# ---------------------------------------------------------------------------
# the §7.3 hard invariant: archive/restore touch NO item bytes
# ---------------------------------------------------------------------------


def _invariant_project(tmp_path):
    """All the item kinds a Navi can live in: a markdown `invalidate` body,
    a `log`-family append-only sealed entry, a CRLF markdown file, a YAML
    list file, and a history-captured item."""
    config = _setup(
        tmp_path,
        {
            "note-a.md": MARKERS["note-a.md"],
            "memo-crlf.md": (
                "---\nid: MEMO-001\ntype: memo\ntitle: M\n---\r\n"
                "para\r\n<!--navi: CRLF navi-->\r\n"
            ),
        },
    )
    (tmp_path / "items" / "dec-a.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: D\n---\nfrozen\n"
        "<!--navi: sealed reminder-->\n",
        encoding="utf-8",
    )
    (tmp_path / "items" / "entries.yaml").write_text(
        "items:\n  - id: NOTE-100\n    type: note\n    title: L\n"
        "    body: |\n      list body\n      <!--navi: list marker-->\n",
        encoding="utf-8",
    )
    return config


def _hashes(config):
    project = _load(config, write=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return {i.id: i.content_hash for i in project.local_items}


def test_archive_and_restore_are_byte_identity_invariants(tmp_path):
    config = _invariant_project(tmp_path)
    # writable load mints marker keys, build writes seals, capture records
    # history -- the state the invariant must survive.
    _load(config)
    assert _run(config, "build") == 0
    assert _run(config, "history", "capture", "NOTE-001") == 0
    _run(config, "build")  # site written
    before = _store_paths(tmp_path)
    hashes_before = _hashes(config)

    keys = _navi_keys(tmp_path)
    assert len(keys) >= 2  # note-a and the CRLF memo (list file refuses mint)
    for key in keys:
        assert _run(config, "navis", "archive", key) == 0

    archived = _store_paths(tmp_path)
    added = set(archived) - set(before)
    assert added, "archive wrote no record"
    for rel in added:
        assert rel.startswith(os.path.join(".refdes", "navis") + os.sep), rel
    for rel in set(before) & set(archived):
        assert archived[rel] == before[rel], f"archive touched {rel}"
    assert _hashes(config) == hashes_before  # content hashes unchanged

    for key in keys:
        assert _run(config, "navis", "restore", key) == 0
    after = _store_paths(tmp_path)
    for rel in set(before) & set(after):
        assert after[rel] == before[rel], f"restore touched {rel}"
    # nothing new outside the (now empty) store dir
    assert {r for r in set(after) - set(before) if not r.startswith(".refdes")} == set()
    assert _hashes(config) == hashes_before
    # seals and history events specifically named (the files §7.3 lists)
    assert archived.get(".refdes" + os.sep + "log-seal.yaml") == \
        before.get(".refdes" + os.sep + "log-seal.yaml")
    seal_events = [r for r in before if r.startswith(os.path.join(".refdes", "history"))]
    assert seal_events, "fixture wrote no history store"
    for rel in seal_events:
        assert after[rel] == before[rel], rel


# ---------------------------------------------------------------------------
# the store reader: corrupt input is a diagnostic, never a crash
# ---------------------------------------------------------------------------


def _corrupt_store(tmp_path, content: bytes, name="12zmcmfc039.yaml.gz"):
    store = tmp_path / ".refdes" / "navis"
    store.mkdir(parents=True, exist_ok=True)
    (store / name).write_bytes(content)


CORRUPT_CASES = {
    "truncated gzip": (gzip.compress(b"archive_format: 1\nnavi_key: x\n")[:9],
                       "gzip"),
    "garbage bytes": (b"not gzip at all, just text", "gzip"),
    "gzip of non-YAML": (gzip.compress(b": : : not yaml"), "YAML"),
    "empty gzip of empty file": (gzip.compress(b""), "empty"),
    "foreign format": (gzip.compress(
        b"archive_format: 99\nnavi_key: 12zmcmfc039\n"
        b"text: future\ntext: x\nitem_key: ''\nsource: {file: f.md, line: 1}\n"
        b"archived_at: now\n"
    ), "99"),
    "key grammar": (gzip.compress(
        b"archive_format: 1\nnavi_key: NOT-A-KEY!!\nitem_key: ''\n"
        b"source: {file: f.md, line: 1}\ntext: t\narchived_at: 'x'\n"
    ), "malformed"),
    "text missing": (gzip.compress(
        b"archive_format: 1\nnavi_key: 12zmcmfc039\nitem_key: ''\n"
        b"source: {file: f.md, line: 1}\narchived_at: 'x'\n"
    ), "text"),
    "source missing": (gzip.compress(
        b"archive_format: 1\nnavi_key: 12zmcmfc039\nitem_key: ''\n"
        b"text: t\narchived_at: 'x'\n"
    ), "source"),
    "name mismatch": (gzip.compress(
        (
            "archive_format: 1\nnavi_key: "
            + "55qgq630y6"
            + keys_mod.check_char("55qgq630y6")
            + "\nitem_key: ''\n"
            "source: {file: f.md, line: 1}\ntext: t\narchived_at: 'x'\n"
        ).encode()
    ), "not its own key"),
    "list not mapping": (gzip.compress(b"- a\n- b\n"), "mapping"),
}


@pytest.mark.parametrize("case", sorted(CORRUPT_CASES))
def test_corrupt_record_is_a_clear_diagnostic_never_a_crash(tmp_path, capsys, case):
    content, needle = CORRUPT_CASES[case]
    _setup(tmp_path)
    _corrupt_store(tmp_path, content)
    records, diagnostics = navis_archive.load_records(str(tmp_path))
    assert records == []
    assert len(diagnostics) == 1, [str(d) for d in diagnostics]
    assert diagnostics[0].code == navis_archive.NAVI_ARCHIVE_CORRUPT_CODE
    msg = str(diagnostics[0])
    assert "12zmcmfc039.yaml.gz" in msg
    assert needle.lower() in msg.lower()
    # the CLI surfaces it, and survives the whole run with it
    assert _run(str(tmp_path / "refdes-project.yaml"), "--no-write", "navis", "all") == 0
    assert needle.lower() in capsys.readouterr().err.lower()


def test_corrupt_record_does_not_eclipse_the_good_ones(tmp_path):
    _setup(tmp_path)
    project = _load(str(tmp_path / "refdes-project.yaml"))
    rows = _rows(project)
    key = rows[0]["key"]
    navis_archive.archive_record(
        str(tmp_path), navi_key=key, item_key="",
        source={"file": "items/note-a.md", "line": 7},
        text="Model worst-case copper temperature.",
    )
    _corrupt_store(tmp_path, b"garbage", name="zzzzzzzzzzz.yaml.gz")
    records, diagnostics = navis_archive.load_records(str(tmp_path))
    assert [r.navi_key for r in records] == [key]  # the good record survives
    assert len(diagnostics) == 1
    assert "zzzzzzzzzzz" in str(diagnostics[0])


def test_store_dir_missing_is_healthy(tmp_path):
    _setup(tmp_path)
    records, diagnostics = navis_archive.load_records(str(tmp_path))
    assert records == [] and diagnostics == []


def test_store_path_replaced_by_a_file_is_a_diagnostic(tmp_path):
    _setup(tmp_path)
    (tmp_path / ".refdes").mkdir(exist_ok=True)
    (tmp_path / ".refdes" / "navis").write_text("not a dir", encoding="utf-8")
    records, diagnostics = navis_archive.load_records(str(tmp_path))
    assert records == []
    assert len(diagnostics) == 1
    assert diagnostics[0].code == navis_archive.NAVI_ARCHIVE_CORRUPT_CODE
    assert "not a directory" in str(diagnostics[0])


# ---------------------------------------------------------------------------
# §12: the journal dir means refuse
# ---------------------------------------------------------------------------


def test_archive_refuses_while_the_journal_is_present(tmp_path, capsys):
    config = _setup(tmp_path)
    _load(config)
    journal = tmp_path / ".refdes" / "editor-transaction"
    journal.mkdir(parents=True)
    (journal / "journal.yaml").write_text("stub", encoding="utf-8")
    before = _store_paths(tmp_path)
    assert _run(config, "navis", "archive", "1") == 2
    assert "editor transaction" in capsys.readouterr().err
    assert _store_paths(tmp_path) == before  # the store is untouched
    (journal / "journal.yaml").unlink()
    journal.rmdir()


def test_store_writer_refuses_journal_directly(tmp_path):
    _setup(tmp_path)
    store = tmp_path / ".refdes"
    store.mkdir(exist_ok=True)
    (store / "editor-transaction").mkdir()
    with pytest.raises(navis_archive.JournalPending):
        navis_archive.archive_record(
            str(tmp_path), navi_key=keys_mod.mint(), item_key="",
            source={"file": "items/note-a.md", "line": 7}, text="x",
        )
    assert not (store / "navis").exists()


# ---------------------------------------------------------------------------
# concurrency: real subprocesses, the project lock is the whole story
# ---------------------------------------------------------------------------


def _driver(tmp_path, config):
    script = (
        "import sys\n"
        f"sys.path.insert(0, {SRC!r})\n"
        "from refdes.cli import main\n"
        f"sys.exit(main(['-c', {config!r}] + sys.argv[1:]))\n"
    )
    path = tmp_path / "driver.py"
    path.write_text(script, encoding="utf-8")
    return str(path)


def test_two_processes_archiving_different_navis(tmp_path):
    config = _setup(tmp_path)
    _load(config)  # mint both keys (sequential before the race)
    driver = _driver(tmp_path, config)
    # Full keys, not ordinals: an ordinal addresses the list as it is
    # *now*, and the list is exactly what the racing processes are
    # changing. The key is the stable identity (design §5).
    keys = _navi_keys(tmp_path)
    assert len(keys) == 2
    procs = [
        subprocess.Popen(
            [sys.executable, driver, "navis", "archive", key],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for key in keys
    ]
    outs = [p.communicate() for p in procs]
    codes = [p.returncode for p in procs]
    assert codes == [0, 0], outs
    store = tmp_path / ".refdes" / "navis"
    names = sorted(p.name for p in store.iterdir())
    assert names == sorted(f"{k}.yaml.gz" for k in keys)
    texts = {_record_dict(tmp_path, k)["text"] for k in keys}
    assert texts == {
        "Model worst-case copper temperature.",
        "Recheck decoupling near U14.",
    }
    # no temp litter
    assert [p.name for p in store.iterdir() if p.name.startswith(".")] == []


def test_two_processes_archiving_the_same_navi_deterministic(tmp_path):
    config = _setup(tmp_path)
    _load(config)
    driver = _driver(tmp_path, config)
    key = _navi_keys(tmp_path)[0]
    procs = [
        subprocess.Popen(
            [sys.executable, driver, "navis", "archive", key],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(2)
    ]
    outs = [p.communicate() for p in procs]
    codes = [p.returncode for p in procs]
    assert codes == [0, 0], outs
    keys = _navi_keys(tmp_path)
    store = tmp_path / ".refdes" / "navis"
    names = [p.name for p in store.iterdir()]
    assert names == [f"{keys[0]}.yaml.gz"]  # exactly one record
    assert _record_dict(tmp_path, keys[0])["text"] == (
        "Model worst-case copper temperature."
    )
    assert [p.name for p in store.iterdir() if p.name.startswith(".")] == []


def test_kill_mid_write_leaves_the_previous_record_intact(tmp_path):
    config = _setup(tmp_path)
    _load(config)
    first_key = _navi_keys(tmp_path)[0]
    assert _run(config, "navis", "archive", "1") == 0
    first_before = _record_bytes(tmp_path, first_key)
    second_key = _navi_keys(tmp_path)[1]
    script = (
        "import sys, os\n"
        f"sys.path.insert(0, {SRC!r})\n"
        "import refdes.cli as cli\n"
        "os.replace = lambda a, b: (_ for _ in ()).throw(\n"
        "    OSError(28, 'simulated crash mid-write'))\n"
        f"sys.exit(cli.main(['-c', {config!r}] + sys.argv[1:]))\n"
    )
    path = tmp_path / "killer.py"
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(path), "navis", "archive", second_key],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "could not write" in proc.stderr
    keys = _navi_keys(tmp_path)
    assert _record_bytes(tmp_path, first_key) == first_before  # intact
    assert not (tmp_path / ".refdes" / "navis" / f"{keys[1]}.yaml.gz").exists()
    store = tmp_path / ".refdes" / "navis"
    assert [p.name for p in store.iterdir() if p.name.startswith(".")] == []


# ---------------------------------------------------------------------------
# text shapes: unicode/astral, duplicate texts, huge (1 MB) lines
# ---------------------------------------------------------------------------


def test_unicode_and_astral_text_round_trips(tmp_path):
    config = _setup(
        tmp_path,
        {"note-a.md": (
            "---\nid: NOTE-001\ntype: note\ntitle: T\n---\n"
            "<!--navi: copper 250°C ±2Ω -->\n"
            "<!--navi: check \U0001f30d \U0001f4a1 near U14-->\n"
        )},
    )
    _load(config)
    assert _run(config, "navis", "archive", "2") == 0
    keys = _navi_keys(tmp_path)
    record = _record_dict(tmp_path, keys[1])
    assert record["text"] == "check \U0001f30d \U0001f4a1 near U14"
    assert _run(config, "navis", "restore", keys[1]) == 0
    rows = _rows(_load(config, write=False))
    assert [r["text"] for r in rows] == [
        "copper 250°C ±2Ω",
        "check \U0001f30d \U0001f4a1 near U14",
    ]


def test_duplicate_texts_archive_independently(tmp_path):
    config = _setup(
        tmp_path,
        {
            "note-a.md": (
                "---\nid: NOTE-001\ntype: note\ntitle: T\n---\n"
                "<!--navi: same text-->\n"
            ),
            "note-b.md": (
                "---\nid: NOTE-002\ntype: note\ntitle: T\n---\n"
                "<!--navi: same text-->\n"
            ),
        },
    )
    _load(config)
    assert _run(config, "navis", "archive", "1") == 0
    rows = _rows(_load(config, write=False))
    assert sorted(r["archived"] for r in rows) == [False, True]
    key = _navi_keys(tmp_path)[0]
    assert _record_dict(tmp_path, key)["text"] == "same text"


def test_huge_navi_megabyte_line_is_handled(tmp_path):
    # HANDLED, not refused: the scan is linear in body size and gzip makes
    # the record small; there is no length cap in v1.
    text = "x" * (1024 * 1024)
    config = _setup(
        tmp_path,
        {"note-a.md": (
            "---\nid: NOTE-001\ntype: note\ntitle: T\n---\n"
            f"<!--navi: {text}-->\n"
        )},
    )
    _load(config)
    assert _run(config, "navis", "archive", "1") == 0
    key = _navi_keys(tmp_path)[0]
    record = _record_dict(tmp_path, key)
    assert record["text"] == text
    raw = (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").read_bytes()
    assert len(raw) < len(text)  # compressed, as mandated (§2.4)
    assert _run(config, "navis", "restore", key) == 0


# ---------------------------------------------------------------------------
# the differential: a project without Navis builds byte-identical to main
# ---------------------------------------------------------------------------


def _git_tree(ref: str, dest: str) -> str | None:
    os.makedirs(dest, exist_ok=True)
    proc = subprocess.run(
        ["git", "-C", REPO, "archive", ref],
        stdout=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return None
    import io

    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        members = [m for m in tar.getmembers() if m.name == "src" or m.name.startswith("src/")]
        tar.extractall(dest, members=members, filter="data")
    return os.path.join(dest, "src")


DIFFERENTIAL_FILES = {
    "note-a.md": (
        "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\n"
        "plain body, no marker\n"
    ),
    "memo-crlf.md": (
        "---\nid: MEMO-001\ntype: memo\ntitle: M\n---\r\n"
        "para\r\nplain\r\n"
    ),
}


def _write_items(root: str) -> None:
    from pathlib import Path

    items = Path(root) / "items"
    items.mkdir(exist_ok=True)
    for name, text in DIFFERENTIAL_FILES.items():
        (items / name).write_text(text, encoding="utf-8")


def _write_differential_project(root: str) -> str:
    from pathlib import Path

    Path(root).mkdir(parents=True, exist_ok=True)
    write_project_config(Path(root), SCHEMA)
    _write_items(root)
    return str(Path(root) / "refdes-project.yaml")


def _build_with(src_root: str, config: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=src_root)
    return subprocess.run(
        [sys.executable, "-m", "refdes.cli", "-c", config, "--no-write", "build"],
        capture_output=True, text=True, env=env, check=False,
    )


@pytest.mark.parametrize("with_refdes", [False, True])
def test_navis_free_project_builds_byte_identical_to_main(tmp_path, with_refdes):
    main_tree = _git_tree("origin/main", str(tmp_path / "main-tree"))
    if main_tree is None:
        pytest.skip("origin/main not available to diff against")
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    cfg_a = _write_differential_project(a)
    cfg_b = _write_differential_project(b)
    if with_refdes:
        # an existing .refdes/ directory: build once (writable, main tree)
        # and hand both trees that warmed state before the compared build
        warm = subprocess.run(
            [sys.executable, "-m", "refdes.cli", "-c", cfg_a, "build"],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=main_tree),
            check=False,
        )
        assert warm.returncode == 0, warm.stderr
        import shutil

        # The warm build is writable: it minted item keys into a's item
        # files. The compared build must start from identical SOURCE bytes
        # in both trees, so a's items go back to the fixture text (the
        # .refdes ledger keeps the minted keys -- the state a real project
        # is in when this build runs).
        shutil.rmtree(os.path.join(a, "items"))
        _write_items(a)
        shutil.copytree(
            os.path.join(a, ".refdes"), os.path.join(b, ".refdes")
        )
    ra = _build_with(main_tree, cfg_a)
    rb = _build_with(SRC, cfg_b)
    assert ra.returncode == 0, ra.stderr
    assert rb.returncode == 0, rb.stderr
    tree_a, tree_b = _store_paths(a), _store_paths(b)
    assert set(tree_a) == set(tree_b), set(tree_a) ^ set(tree_b)
    for rel in tree_a:
        assert tree_a[rel] == tree_b[rel], f"build output differs: {rel}"
