"""Navis slice 2: key minting on writable load (in-prog-logs/navis-design-20261025.md §5, §7.2, §13).

`<!--navi: text-->` gains its minted 11-character key in the marker itself
(`<!--navi:k7f3q2x8d0f text-->`) on the same writable-load path that mints
item keys, announced on stderr, idempotent, and never on `--no-write`.
The mint writes the key at the marker's EXACT source position (the spans
`analyze_navis` produced -- never a re-search); a body whose marker bytes
cannot be located losslessly in the item's own file (a list file's `body:`
scalar) REFUSES the mint with a clear diagnostic and leaves the bytes.

The hash/seal consequence is the design's own policy (binding §7.2: minted
keys land under the same rules as the author's own edit): a body whose
`on_change` is `invalidate` changes content hash when the key is written,
an `ignore` body does not, and a sealed append-only entry answers the
writable build with the documented "modified since sealed -> `--reseal`"
error -- pinned here, not assumed.

Corruption posture (§5, `keys.malformed_key_message`): a declared key that
fails validation is reported, never repaired, and never minted over.
"""

from __future__ import annotations

import itertools
import os
import re

from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import loader, navis

SCHEMA = (
    "site: { title: Navis Mint, out: _site }\n"
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

KEYED_RE = re.compile(r"<!--navi:([0-9a-z]{11}) ")


def _setup(tmp_path, files):
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")
    return str(config)


def _setup_bytes(tmp_path, files):
    """Same, writing raw bytes (the line-terminator fixtures)."""
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, data in files.items():
        (items / name).write_bytes(data)
    return str(config)


def _bytes(root, name):
    return (root / "items" / name).read_bytes()


def _load(config, write=True):
    project, _stale = loader.load_tree(str(config), write=write)
    return project


def _md(id_, type_, body, extra=""):
    return f"---\nid: {id_}\ntype: {type_}\ntitle: T\n{extra}---\n{body}"


def _item_key() -> str:
    """A valid item key for fixtures that must NOT mint one (so a test can
    assert byte-identity of the whole file)."""
    return keys_mod.mint()


def _navi_key_with_prefix(prefix6: str, nth: int) -> str:
    """A VALID navi key (check character included) starting with prefix6.
    Two calls with the same prefix and different nth share the 6-char
    prefix, which is exactly the CLI's ambiguity case. Marker keys live in
    markdown, so YAML plain-scalar safety is not a requirement here --
    only the key grammar (`keys.malformed_key_message`) is.
    """
    assert len(prefix6) == 6 and all(c in keys_mod.ALPHABET for c in prefix6)
    for suffix in itertools.product(keys_mod.ALPHABET, repeat=4):
        data = prefix6 + "".join(suffix)
        candidate = data + keys_mod.check_char(data)
        if keys_mod.malformed_key_message(candidate) is None:
            if nth == 0:
                return candidate
            nth -= 1
    raise AssertionError("no valid key found")  # pragma: no cover


# ---------------------------------------------------------------------------
# the mint itself
# ---------------------------------------------------------------------------


def test_writable_load_mints_the_key_into_the_marker(tmp_path):
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "intro\n<!--navi: Model the copper thing-->\n")})
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "note-a.md").decode()
    m = KEYED_RE.search(text)
    assert m is not None, text
    assert keys_mod.malformed_key_message(m.group(1)) is None
    assert "<!--navi:" + m.group(1) + " Model the copper thing-->" in text


def test_minted_marker_still_scans_as_the_same_navi(tmp_path):
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "<!--navi: Recheck decoupling near U14.-->\n")})
    _load(config)
    project = _load(config, write=False)
    build_mod.build(project, seal_write=False, reseal=False)
    rows = navis.projection(project)
    assert len(rows) == 1
    assert rows[0]["text"] == "Recheck decoupling near U14."
    assert rows[0]["key"] and keys_mod.malformed_key_message(rows[0]["key"]) is None


def test_second_writable_run_mints_nothing_and_writes_no_bytes(tmp_path):
    files = {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\nkey note\n")}
    config = _setup(tmp_path, files)
    _load(config)
    after_first = _bytes(tmp_path, "note-a.md")
    project = _load(config)
    assert not project.load_writes
    assert _bytes(tmp_path, "note-a.md") == after_first


def test_no_write_never_mints(tmp_path):
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\n")})
    before = _bytes(tmp_path, "note-a.md")
    project = _load(config, write=False)
    assert not project.load_writes
    assert _bytes(tmp_path, "note-a.md") == before


def test_load_readonly_never_mints(tmp_path):
    _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\n")})
    before = _bytes(tmp_path, "note-a.md")
    project = loader.load_readonly(str(tmp_path / "refdes-project.yaml"))
    assert not project.load_writes
    assert _bytes(tmp_path, "note-a.md") == before


def test_duplicate_texts_get_distinct_keys(tmp_path):
    config = _setup(
        tmp_path,
        {
            "note-a.md": _md("NOTE-001", "note", "<!--navi: same text-->\n"),
            "note-b.md": _md("NOTE-002", "note", "<!--navi: same text-->\n"),
        },
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 2
    keys = KEYED_RE.findall(_bytes(tmp_path, "note-a.md").decode()) + KEYED_RE.findall(_bytes(tmp_path, "note-b.md").decode())
    assert len(keys) == 2 and len(set(keys)) == 2


def test_two_markers_on_one_line_both_minted(tmp_path):
    config = _setup(
        tmp_path,
        {"note-a.md": _md("NOTE-001", "note", "<!--navi: first--> mid <!--navi: second-->\n")},
    )
    _load(config)
    text = _bytes(tmp_path, "note-a.md").decode()
    keys = KEYED_RE.findall(text)
    assert len(keys) == 2 and keys[0] != keys[1]
    assert " mid " in text


def test_multi_item_markdown_file(tmp_path):
    body = (
        _md("NOTE-001", "note", "a\n<!--navi: one-->\n")
        + "---\nid: NOTE-002\ntype: note\ntitle: T2\n---\nb\n<!--navi: two-->\n"
    )
    config = _setup(tmp_path, {"multi.md": body})
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 2
    assert len(KEYED_RE.findall(_bytes(tmp_path, "multi.md").decode())) == 2


def test_keyed_markers_are_left_alone_mixed(tmp_path):
    keyed = _navi_key_with_prefix("aaaaaa", 0)
    config = _setup(
        tmp_path,
        {"note-a.md": _md("NOTE-001", "note", f"<!--navi:{keyed} keyed one--><!--navi: keyless two-->\n")},
    )
    _load(config)
    text = _bytes(tmp_path, "note-a.md").decode()
    assert f"<!--navi:{keyed} keyed one-->" in text  # untouched, byte for byte
    keys = KEYED_RE.findall(text)
    assert len(keys) == 2 and keyed in keys
    assert keys[-1] != keyed


def test_minted_key_never_changes_on_a_later_load(tmp_path):
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\n")})
    _load(config)
    first = KEYED_RE.findall(_bytes(tmp_path, "note-a.md").decode())[0]
    (tmp_path / "items" / "note-a.md").write_text(
        _md("NOTE-001", "note", f"<!--navi:{first} one-->\nmore\n<!--navi: two-->\n"),
        encoding="utf-8",
    )
    _load(config)
    keys = KEYED_RE.findall(_bytes(tmp_path, "note-a.md").decode())
    assert keys[0] == first
    assert len(keys) == 2


# ---------------------------------------------------------------------------
# source-shape matrix: exact provenance, lossless or refuse
# ---------------------------------------------------------------------------


def test_crlf_file_keeps_terminators(tmp_path):
    text = _md("NOTE-001", "note", "line\r\n<!--navi: one-->\r\n").replace("\r\n", "\n")
    body = text.replace("\n", "\r\n").encode("utf-8")  # whole file CRLF
    config = _setup_bytes(tmp_path, {"note-a.md": body})
    _load(config)
    raw = _bytes(tmp_path, "note-a.md")
    assert raw.count(b"\n") == raw.count(b"\r\n")  # every break is CRLF
    assert b"<!--navi:" in raw and b"-->\r\n" in raw


def test_lone_cr_file_keeps_terminators(tmp_path):
    text = _md("NOTE-001", "note", "line\r<!--navi: one-->\r")
    body = text.replace("\n", "\r").encode("utf-8")  # whole file lone CR
    config = _setup_bytes(tmp_path, {"note-a.md": body})
    _load(config)
    raw = _bytes(tmp_path, "note-a.md")
    assert b"\n" not in raw  # lone CR preserved, not normalized
    assert b"<!--navi:" in raw


def test_hard_break_adjacent_bytes_preserved(tmp_path):
    config = _setup(
        tmp_path,
        {"note-a.md": _md("NOTE-001", "note", "para  \n<!--navi: one-->  \nnext\n")},
    )
    _load(config)
    raw = _bytes(tmp_path, "note-a.md").decode()
    # Line terminators are the fixture's own (write_text translates them
    # per platform), so compare line CONTENT: the two-space runs that make
    # the hard breaks survive the splice untouched, on both sides.
    lines = raw.splitlines()
    assert "para  " in lines
    marker = next(i for i, line in enumerate(lines) if line.startswith("<!--navi:"))
    assert lines[marker].startswith("<!--navi:") and lines[marker].endswith("one-->  ")
    assert lines[marker + 1] == "next"


def test_table_cell_marker_minted(tmp_path):
    config = _setup(
        tmp_path,
        {"note-a.md": _md("NOTE-001", "note", "| a | b |\n| --- | --- |\n| <!--navi: note--> | x |\n")},
    )
    _load(config)
    text = _bytes(tmp_path, "note-a.md").decode()
    m = KEYED_RE.search(text)
    assert m is not None
    assert f"| <!--navi:{m.group(1)} note--> | x |" in text


def test_inert_markers_are_not_minted_file_stays_byte_identical(tmp_path):
    body = (
        "para\n\n```\n<!--navi: fenced-->\n```\n\n"
        "text `<!--navi: span-->` tail\n"
    )
    config = _setup(
        tmp_path,
        {"note-a.md": _md("NOTE-001", "note", body, extra=f"key: {_item_key()}\n")},
    )
    before = _bytes(tmp_path, "note-a.md")
    project = _load(config)
    assert not project.load_writes
    assert _bytes(tmp_path, "note-a.md") == before


def test_yaml_list_body_scalar_mints(tmp_path):
    # A literal block scalar's marker bytes are exact file bytes, so the
    # mint lands there too (navis_yaml); see tests/test_navis_mint_yaml.py
    # for the full shape matrix.
    yaml_file = (
        f"items:\n  - id: NOTE-001\n    key: {_item_key()}\n    type: note\n"
        "    title: T\n    body: |\n"
        "      line one\n      <!--navi: reminder-->\n"
    )
    config = _setup(tmp_path, {"items.yaml": yaml_file})
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    assert re.search(r"<!--navi:[0-9a-z]{11} reminder-->", _bytes(tmp_path, "items.yaml").decode())


def test_yaml_quoted_scalar_mints(tmp_path):
    # A single-line quoted scalar decodes exactly (navis_yaml); the
    # escape bytes stay untouched.
    yaml_file = (
        f"items:\n  - id: NOTE-001\n    key: {_item_key()}\n    type: note\n"
        "    title: T\n"
        '    body: "line one <!--navi: rem --> with \\u00e9scapes"\n'
    )
    config = _setup(tmp_path, {"items.yaml": yaml_file})
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "items.yaml").decode()
    assert re.search(r'body: "line one <!--navi:[0-9a-z]{11} rem --> with \\u00e9scapes"', text)


def test_yaml_folded_scalar_refuses_mint(tmp_path):
    yaml_file = (
        f"items:\n  - id: NOTE-001\n    key: {_item_key()}\n    type: note\n"
        "    title: T\n    body: >\n"
        "      folded <!--navi: r--> text\n"
    )
    config = _setup(tmp_path, {"items.yaml": yaml_file})
    before = _bytes(tmp_path, "items.yaml")
    project = _load(config)
    assert _bytes(tmp_path, "items.yaml") == before
    assert project.load_writes.minted_navi_keys == 0


def test_refused_marker_still_lists_keyless(tmp_path):
    yaml_file = (
        f"items:\n  - id: NOTE-001\n    key: {_item_key()}\n    type: note\n"
        "    title: T\n    body: >\n"
        "      folded <!--navi: reminder--> text\n"
    )
    config = _setup(tmp_path, {"items.yaml": yaml_file})
    project = _load(config)
    build_mod.build(project, seal_write=False, reseal=False)
    rows = navis.projection(project)
    assert len(rows) == 1
    assert rows[0]["key"] is None


# ---------------------------------------------------------------------------
# corruption lint (§5: keys.malformed_key_message-style validation)
# ---------------------------------------------------------------------------


def test_corrupted_key_reported_not_fixed(tmp_path):
    # 11 alphabet characters, wrong check character: a declared key that
    # validation rejects. Reported, left in place, never minted over.
    config = _setup(
        tmp_path,
        {
            "note-a.md": _md(
                "NOTE-001", "note", "intro\n<!--navi:aaaaaaaaaaa bad key-->\n",
                extra=f"key: {_item_key()}\n",
            )
        },
    )
    before = _bytes(tmp_path, "note-a.md")
    project = _load(config)
    build_mod.build(project, seal_write=False, reseal=False)
    assert _bytes(tmp_path, "note-a.md") == before  # not repaired, not extended
    bad = [d for d in project.diagnostics if d.code == navis.NAVI_DIAGNOSTIC_CODE]
    assert any("malformed" in str(d) for d in bad), [str(d) for d in bad]
    # the marker's text is not silently dropped from the listing
    build_mod.build(project, seal_write=False, reseal=False)
    rows = navis.projection(project)
    assert [r["text"] for r in rows] == ["bad key"]


def test_valid_hand_keyed_marker_not_flagged(tmp_path):
    good = _navi_key_with_prefix("abcdef", 0)
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", f"<!--navi:{good} fine-->\n")})
    project = _load(config)
    assert not [d for d in project.diagnostics if d.code == navis.NAVI_DIAGNOSTIC_CODE]
    assert project.load_writes.minted_navi_keys == 0  # keyed: nothing to mint


# ---------------------------------------------------------------------------
# CLI: short keys (§5: 6-char prefix in the CLI, full key in show)
# ---------------------------------------------------------------------------


def _run(config, *args):
    return cli_mod.main(["-c", config, *args])


def test_ls_shows_six_char_prefix(tmp_path, capsys):
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\n")})
    assert _run(config, "navis", "ls") == 0
    key = KEYED_RE.findall(_bytes(tmp_path, "note-a.md").decode())[0]
    out = capsys.readouterr().out
    assert f"{key[:6]} one" in out


def test_writable_navis_run_announces_navi_keys(tmp_path, capsys):
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\n")})
    assert _run(config, "navis", "ls") == 0
    err = capsys.readouterr().err
    assert "navi key(s)" in err  # announced, never silent
    assert "navi key(s)" not in capsys.readouterr().out


def test_show_by_six_char_prefix(tmp_path, capsys):
    config = _setup(
        tmp_path,
        {
            "note-a.md": _md("NOTE-001", "note", "<!--navi: copper model-->\n"),
            "note-b.md": _md("NOTE-002", "note", "<!--navi: decoupling check-->\n"),
        },
    )
    _load(config)  # mint both
    keys = KEYED_RE.findall(_bytes(tmp_path, "note-a.md").decode())
    assert _run(config, "--no-write", "navis", "show", keys[0][:6]) == 0
    out = capsys.readouterr().out
    assert keys[0] in out  # full key on show
    assert "copper model" in out


def test_ambiguous_prefix_lists_candidates(tmp_path, capsys):
    k1 = _navi_key_with_prefix("aaaaaa", 0)
    k2 = _navi_key_with_prefix("aaaaaa", 1)
    assert k1[:6] == k2[:6] and k1 != k2
    config = _setup(
        tmp_path,
        {
            "note-a.md": _md("NOTE-001", "note", f"<!--navi:{k1} one-->\n"),
            "note-b.md": _md("NOTE-002", "note", f"<!--navi:{k2} two-->\n"),
        },
    )
    assert _run(config, "--no-write", "navis", "show", "aaaaaa") == 2
    err = capsys.readouterr().err
    assert "aaaaaa" in err
    assert k1 in err and k2 in err  # the candidates are named


def test_prefix_that_matches_nothing_is_a_naming_error(tmp_path, capsys):
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\n")})
    assert _run(config, "--no-write", "navis", "show", "zzzzzz") == 2
    assert "no Navi" in capsys.readouterr().err


def test_key_selector_still_wins_over_prefix_grammar(tmp_path, capsys):
    good = _navi_key_with_prefix("abcdef", 0)
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", f"<!--navi:{good} fine-->\n")})
    assert _run(config, "--no-write", "navis", "show", good) == 0
    assert "fine" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# hash / seal / baseline consequence (design §7.2 policy, pinned by test)
# ---------------------------------------------------------------------------


def _hash_of(tmp_path, files, id_, write):
    config = _setup(tmp_path, files)
    project = _load(config, write=write)
    build_mod.build(project, seal_write=False, reseal=False)
    return project.item_by_id(id_).content_hash


def test_mint_changes_hash_for_invalidate_body(tmp_path):
    files = {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\n")}
    a = _hash_of(tmp_path, files, "NOTE-001", write=False)
    b = _hash_of(tmp_path, files, "NOTE-001", write=True)
    assert a != b  # §7.1/§7.2: the mint is a body edit by design


def test_mint_is_hash_neutral_for_ignore_body(tmp_path):
    files = {"memo-a.md": _md("MEMO-001", "memo", "<!--navi: one-->\n")}
    a = _hash_of(tmp_path, files, "MEMO-001", write=False)
    b = _hash_of(tmp_path, files, "MEMO-001", write=True)
    assert a == b


def test_sealed_append_only_entry_answers_with_reseal_hint(tmp_path):
    # Design §7.2: the minted key lands under the same rules as the author's
    # own edit -- the writable load mints, and the build reports the sealed
    # entry as modified with the documented `--reseal` remedy. Policy pinned.
    config = _setup(tmp_path, {"dec-a.md": _md("DEC-001", "decision", "frozen text\n")})
    project = _load(config)
    build_mod.build(project, seal_write=True, reseal=False)
    (tmp_path / "items" / "dec-a.md").write_text(
        _md("DEC-001", "decision", "frozen text\n<!--navi: reminder-->\n"), encoding="utf-8"
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1  # the key landed
    build_mod.build(project, seal_write=False, reseal=False)
    errors = [str(d) for d in project.errors]
    assert any("append-only" in e and "sealed" in e for e in errors), errors
    assert any("--reseal" in e for e in errors), errors


# ---------------------------------------------------------------------------
# the write path: filesystem refusal
# ---------------------------------------------------------------------------


def test_read_only_file_refusal_recorded_not_fatal(tmp_path):
    config = _setup(tmp_path, {"note-a.md": _md("NOTE-001", "note", "<!--navi: one-->\n")})
    path = tmp_path / "items" / "note-a.md"
    before = path.read_bytes()
    os.chmod(path, 0o444)
    try:
        project = _load(config)
    finally:
        os.chmod(path, 0o644)
    assert path.read_bytes() == before  # bytes intact
    assert project.load_writes.minted_navi_keys == 0  # only landed writes count
    assert "items/note-a.md" in project.load_writes.blocked
