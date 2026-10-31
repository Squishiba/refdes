"""Navis slice 2b: key minting inside YAML list-file `body:` scalars.

The markdown mint (slice 2) writes at `Item.body_line + occ.line`, which a
list file does not have: its `body:` scalar's parsed text is not its source
text. `navis_yaml` resolves the marker's bytes for the two shapes where
that is exact -- literal block scalars (`body: |`, any indicator) and
single-line quoted scalars -- and refuses everything else: folded (`>`),
plain, flow style, multi-line quoted, a `body:` from a merge key
(`<<:`) / file-wide `defaults:`, and an alias-shared body. A minted file
must re-parse with the target bodies carrying exactly the spliced keys,
announced, idempotent, and never on `--no-write`.
"""

from __future__ import annotations

import random
import re

import pytest

from conftest import write_project_config

from refdes import build as build_mod
from refdes import keys as keys_mod
from refdes import loader, navis

SCHEMA = (
    "site: { title: Navis YAML Mint, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

KEYED_RE = re.compile(r"<!--navi:([0-9a-z]{11}) ")


def _setup(tmp_path, files):
    """Write the fixtures as BYTES: the bytes are exactly the text's, on
    every platform (a text-mode write would turn the LF fixtures into
    CRLF on Windows, and the LF assertions would be testing the writer).
    """
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_bytes(text.encode("utf-8"))
    return str(config)


def _setup_bytes(tmp_path, files):
    """Same, for fixtures whose content is raw bytes (the CRLF case)."""
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


def _item_key() -> str:
    return keys_mod.mint()


def _yaml(body_block: str, id_: str = "NOTE-001", extra: str = "") -> str:
    return (
        f"items:\n  - id: {id_}\n    key: {_item_key()}\n    type: note\n"
        f"    title: T\n{extra}    body: {body_block}\n"
    )


# ---------------------------------------------------------------------------
# the mint itself: literal block scalars
# ---------------------------------------------------------------------------


def test_literal_block_mints(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|\n      line one\n      <!--navi: reminder-->\n")},
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "items.yaml").decode()
    m = KEYED_RE.search(text)
    assert m is not None, text
    assert keys_mod.malformed_key_message(m.group(1)) is None
    assert "      <!--navi:" + m.group(1) + " reminder-->\n" in text
    # the file reparses with the key in the model
    project = _load(config, write=False)
    build_mod.build(project, seal_write=False, reseal=False)
    rows = navis.projection(project)
    assert len(rows) == 1
    assert rows[0]["text"] == "reminder"
    assert rows[0]["key"] == m.group(1)


def test_literal_block_strip_indicator_mints(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|-\n      <!--navi: clipped-->\n")},
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    assert "<!--navi:" in _bytes(tmp_path, "items.yaml").decode()


def test_literal_block_keep_indicator_mints(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|+\n      <!--navi: kept-->\n\n\n")},
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "items.yaml").decode()
    assert KEYED_RE.search(text) is not None
    assert text.endswith("kept-->" + "\n" * 4)


def test_literal_block_indent_indicator_mints(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|2\n       <!--navi: indented-->\n")},
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "items.yaml").decode()
    assert "       <!--navi:" in text  # seven spaces: 2 + the marker's own


def test_literal_block_second_line_marker_mints(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|\n      first\n      <!--navi: second-->\n      third\n")},
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "items.yaml").decode()
    lines = text.splitlines()
    keyed = [line for line in lines if KEYED_RE.search(line)]
    assert len(keyed) == 1
    assert keyed[0].strip().startswith("<!--navi:")
    # untouched neighbours, byte for byte
    assert "      first" in lines
    assert "      third" in lines


def test_literal_block_two_markers_one_body_minted(tmp_path):
    config = _setup(
        tmp_path,
        {
            "items.yaml": _yaml(
                "|\n      <!--navi: one--> x <!--navi: two-->\n"
            )
        },
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 2
    keys = KEYED_RE.findall(_bytes(tmp_path, "items.yaml").decode())
    assert len(keys) == 2 and keys[0] != keys[1]


def test_literal_block_mid_line_marker_mints(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|\n      a <!--navi: middle--> b\n")},
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "items.yaml").decode()
    m = KEYED_RE.search(text)
    assert f"      a <!--navi:{m.group(1)} middle--> b" in text


# ---------------------------------------------------------------------------
# the mint itself: single-line quoted scalars
# ---------------------------------------------------------------------------


def test_double_quoted_mints_and_keeps_escapes(tmp_path):
    config = _setup(
        tmp_path,
        {
            "items.yaml": _yaml(
                '"line one <!--navi: rem --> with \\u00e9scapes"\n'
            )
        },
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "items.yaml").decode()
    m = KEYED_RE.search(text)
    assert m is not None
    assert "\\u00e9" in text  # the escape bytes untouched
    project = _load(config, write=False)
    item = project.item_by_id("NOTE-001")
    assert item.body == f"line one <!--navi:{m.group(1)} rem --> with \u00e9scapes"


def test_double_quoted_backslash_escapes_mint(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml('"tab\\there <!--navi: q--> \\\\tail"\n')},
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    project = _load(config, write=False)
    body = project.item_by_id("NOTE-001").body
    assert "<!--navi:" in body and " q-->" in body
    assert "\there" in body and body.endswith("\\tail")


def test_single_quoted_mints_with_doubled_quote(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("'it''s <!--navi: quoted--> here'\n")},
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    text = _bytes(tmp_path, "items.yaml").decode()
    m = KEYED_RE.search(text)
    assert m is not None
    project = _load(config, write=False)
    assert project.item_by_id("NOTE-001").body == f"it's <!--navi:{m.group(1)} quoted--> here"


# ---------------------------------------------------------------------------
# refusals: the bytes stay byte-intact, the marker stays keyless
# ---------------------------------------------------------------------------


def _refused(tmp_path, name, text, id_="NOTE-001"):
    config = _setup(tmp_path, {name: text})
    before = _bytes(tmp_path, name)
    project = _load(config)
    assert _bytes(tmp_path, name) == before  # bytes intact
    assert project.load_writes.minted_navi_keys == 0
    refusals = [
        d for d in project.diagnostics
        if d.code == "NAVI_MINT_REFUSED" and (d.file or "").endswith(name)
    ]
    assert refusals, [str(d) for d in project.diagnostics]
    build_mod.build(project, seal_write=False, reseal=False)
    rows = [r for r in navis.projection(project) if r["source"]["item"] == id_]
    assert rows and all(r["key"] is None for r in rows)  # lists keyless
    return project


def test_folded_scalar_refuses(tmp_path):
    _refused(
        tmp_path,
        "items.yaml",
        _yaml(">\n      folded <!--navi: r--> text\n"),
    )


def test_plain_scalar_cannot_carry_a_keyless_marker(tmp_path):
    # `: ` in a plain scalar parses as a mapping -- the file does not load
    # as an item file at all. The mint cannot see the marker; nothing mints.
    config = _setup(
        tmp_path,
        {
            "items.yaml": (
                f"items:\n  - id: NOTE-001\n    key: {_item_key()}\n    type: note\n"
                "    title: T\n    body: a <!--navi: rem --> b\n"
            )
        },
    )
    before = _bytes(tmp_path, "items.yaml")
    project = _load(config)
    assert _bytes(tmp_path, "items.yaml") == before
    assert project.load_writes.minted_navi_keys == 0
    assert not project.item_by_id("NOTE-001")  # the file failed to parse


def test_flow_style_refuses(tmp_path):
    _refused(
        tmp_path,
        "items.yaml",
        (
            f"items: [{{id: NOTE-001, key: {_item_key()}, type: note, title: T, "
            'body: "a <!--navi: rem --> b"}]\n'
        ),
    )


def test_merge_key_body_refuses(tmp_path):
    _refused(
        tmp_path,
        "items.yaml",
        (
            "items:\n"
            "  - &base\n    key: " + _item_key() + "\n    type: note\n    title: T\n"
            "    body: |\n      <!--navi: reminder-->\n"
            f"  - id: NOTE-002\n    key: {_item_key()}\n    <<: *base\n"
        ),
        id_="NOTE-002",
    )


def test_alias_shared_body_refuses(tmp_path):
    _refused(
        tmp_path,
        "items.yaml",
        (
            "items:\n"
            f"  - id: NOTE-001\n    key: {_item_key()}\n    type: note\n    title: T\n"
            "    body: &b |\n      <!--navi: reminder-->\n"
            f"  - id: NOTE-002\n    key: {_item_key()}\n    type: note\n    title: T2\n"
            "    body: *b\n"
        ),
    )


def test_defaults_supplied_body_refuses(tmp_path):
    config = _setup(
        tmp_path,
        {
            "items.yaml": (
                f"defaults:\n  type: note\n  title: T\n  body: |\n"
                "    <!--navi: from defaults-->\n"
                f"items:\n  - id: NOTE-001\n    key: {_item_key()}\n"
            )
        },
    )
    before = _bytes(tmp_path, "items.yaml")
    project = _load(config)
    assert _bytes(tmp_path, "items.yaml") == before
    assert project.load_writes.minted_navi_keys == 0


def test_multi_line_quoted_refuses(tmp_path):
    _refused(
        tmp_path,
        "items.yaml",
        _yaml('"one\n      two <!--navi: folded--> three"\n'),
    )


def test_tab_in_block_header_refuses_by_not_loading(tmp_path):
    config = _setup(
        tmp_path,
        {
            "items.yaml": (
                f"items:\n  - id: NOTE-001\n    key: {_item_key()}\n    type: note\n"
                "    title: T\n    body: |\t\n      <!--navi: tabbed-->\n"
            )
        },
    )
    before = _bytes(tmp_path, "items.yaml")
    project = _load(config)
    assert _bytes(tmp_path, "items.yaml") == before
    assert project.load_writes.minted_navi_keys == 0


# ---------------------------------------------------------------------------
# posture: idempotence, announcement, --no-write, CRLF
# ---------------------------------------------------------------------------


def test_second_writable_run_mints_nothing(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|\n      <!--navi: one-->\n")},
    )
    _load(config)
    after_first = _bytes(tmp_path, "items.yaml")
    project = _load(config)
    assert not project.load_writes
    assert _bytes(tmp_path, "items.yaml") == after_first


def test_no_write_never_mints_yaml(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|\n      <!--navi: one-->\n")},
    )
    before = _bytes(tmp_path, "items.yaml")
    project = _load(config, write=False)
    assert not project.load_writes
    assert _bytes(tmp_path, "items.yaml") == before


def test_yaml_mint_announces(tmp_path, capsys):
    from refdes import cli as cli_mod

    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|\n      <!--navi: one-->\n")},
    )
    assert cli_mod.main(["-c", config, "navis", "ls"]) == 0
    err = capsys.readouterr().err
    assert "navi key(s)" in err
    assert "items/note-a.md" not in err
    assert "items.yaml" in err


def test_crlf_yaml_literal_block_keeps_terminators(tmp_path):
    text = _yaml("|\n      line one\n      <!--navi: one-->\n")
    body = text.replace("\n", "\r\n").encode("utf-8")
    config = _setup_bytes(tmp_path, {"items.yaml": body})
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    raw = _bytes(tmp_path, "items.yaml")
    assert raw.count(b"\n") == raw.count(b"\r\n")  # every break is CRLF
    key = KEYED_RE.findall(raw.decode("utf-8"))[0]
    # the whole change, as bytes: the key (plus its space) in the marker,
    # nothing else -- terminators, indentation, every other byte kept.
    assert raw == body.replace(
        b"      <!--navi: one-->",
        f"      <!--navi:{key} one-->".encode("utf-8"),
    )


def test_crlf_yaml_quoted_mints_key_bytes_only(tmp_path):
    text = _yaml('"a <!--navi: q--> b"\n')
    body = text.replace("\n", "\r\n").encode("utf-8")
    config = _setup_bytes(tmp_path, {"items.yaml": body})
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 1
    raw = _bytes(tmp_path, "items.yaml")
    assert raw.count(b"\n") == raw.count(b"\r\n")  # every break is CRLF
    key = KEYED_RE.findall(raw.decode("utf-8"))[0]
    assert raw == body.replace(
        b"<!--navi: q-->",
        f"<!--navi:{key} q-->".encode("utf-8"),
    )


def test_yaml_mint_changes_hash_and_lists_keyed(tmp_path):
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|\n      <!--navi: one-->\n")},
    )
    cold = _load(config, write=False)
    build_mod.build(cold, seal_write=False, reseal=False)
    a = cold.item_by_id("NOTE-001").content_hash
    warm = _load(config, write=True)
    build_mod.build(warm, seal_write=False, reseal=False)
    b = warm.item_by_id("NOTE-001").content_hash
    assert a != b  # the mint is a body edit by design (§7.2)
    rows = navis.projection(warm)
    assert len(rows) == 1 and rows[0]["key"] is not None


def test_keyed_yaml_marker_untouched(tmp_path):
    keyed = "k7f3q2x8d0f"
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml(f"|\n      <!--navi:{keyed} keyed-->\n")},
    )
    before = _bytes(tmp_path, "items.yaml")
    project = _load(config)
    assert _bytes(tmp_path, "items.yaml") == before
    assert not project.load_writes


def test_two_yaml_items_both_mint(tmp_path):
    config = _setup(
        tmp_path,
        {
            "items.yaml": (
                "items:\n"
                f"  - id: NOTE-001\n    key: {_item_key()}\n    type: note\n    title: A\n"
                "    body: |\n      <!--navi: first-->\n"
                f"  - id: NOTE-002\n    key: {_item_key()}\n    type: note\n    title: B\n"
                '    body: "second <!--navi: second-->"\n'
            )
        },
    )
    project = _load(config)
    assert project.load_writes.minted_navi_keys == 2
    keys = KEYED_RE.findall(_bytes(tmp_path, "items.yaml").decode())
    assert len(keys) == 2 and keys[0] != keys[1]


def test_yaml_marker_text_survives_the_mint(tmp_path):
    """The minted key consumes the author's space after `<!--navi:` and
    nothing else: the body's text, indentation and trailing spaces are
    byte-identical to before, plus the key."""
    config = _setup(
        tmp_path,
        {"items.yaml": _yaml("|\n      x  <!--navi:   spaced  -->  y\n")},
    )
    project = _load(config)
    key = KEYED_RE.findall(_bytes(tmp_path, "items.yaml").decode())[0]
    project = _load(config, write=False)
    assert project.item_by_id("NOTE-001").body == f"x  <!--navi:{key} spaced  -->  y\n"


# ---------------------------------------------------------------------------
# fuzz: randomized shapes, invariants only (no golden bytes)
# ---------------------------------------------------------------------------

_WORDS = ("alpha", "beta", "gamma", "delta", "keep", "x", "y", "z")
_MINTABLE = ("literal", "strip", "dq", "sq")


def _fuzz_body(rng, shape, markers):
    """One item body in one shape; markers are marker strings placed on
    content lines."""
    w = lambda: rng.choice(_WORDS)
    if shape in ("literal", "strip"):
        ind = " " * rng.choice((6, 7, 8))
        lines = [f"{w()} {w()}"]
        line = " ".join([w(), markers[0], w()])
        if len(markers) > 1:
            line = " ".join([w(), markers[0], w(), markers[1], w()])
        lines.append(ind + line)
        lines.append(f"{w()}")
        body = "|\n" if shape == "literal" else "|-\n"
        return body + "".join(f"{ind}{line}\n" for line in lines)
    if shape == "dq":
        esc = "".join(rng.choice(["", "", r"\u00e9", r"\t", r"\\", r"\u0041"]) for _ in range(3))
        text = f"{w()} {esc}{markers[0]} {esc} {w()}"
        if len(markers) > 1:
            text = f"{w()} {markers[0]} {w()} {markers[1]} {w()}"
        return '"' + text + '"\n'
    if shape == "sq":
        text = f"{w()} ''{w()} {markers[0]} {w()}"
        if len(markers) > 1:
            text = f"{w()} {markers[0]} '' {markers[1]} {w()}"
        return "'" + text + "'\n"
    # folded (refused): one content line, the marker text intact in it
    line = f"{w()} {markers[0]} {w()}"
    if len(markers) > 1:
        line = f"{w()} {markers[0]} {w()} {markers[1]} {w()}"
    return ">\n      " + line + "\n"


def _fuzz_key(rng):
    return "".join(rng.choice(keys_mod.ALPHABET) for _ in range(11))


def _fuzz_file(rng):
    n_items = rng.choice((1, 1, 2))
    out = ["items:"]
    shapes, bodies = [], []
    for i in range(n_items):
        shape = rng.choice(_MINTABLE + ("folded",))
        markers = []
        for _ in range(rng.choice((1, 1, 2))):
            if rng.random() < 0.3:
                markers.append(f"<!--navi:{_fuzz_key(rng)} {rng.choice(_WORDS)}-->")
            else:
                markers.append(f"<!--navi: {rng.choice(_WORDS)} {rng.choice(_WORDS)}-->")
        body = _fuzz_body(rng, shape, markers)
        shapes.append(shape)
        bodies.append(body)
        out.append(f"  - id: NOTE-{i + 1:03d}")
        out.append(f"    key: {keys_mod.mint()}")
        out.append("    type: note")
        out.append("    title: T")
        indented = body.split("\n")
        head = indented[0]
        out.append(f"    body: {head}")
        for line in indented[1:-1]:
            out.append(line)
    return "\n".join(out) + "\n", shapes


@pytest.mark.parametrize("seed", range(150))
def test_fuzz_yaml_mint_invariants(tmp_path, seed):
    rng = random.Random(seed)
    text, shapes = _fuzz_file(rng)
    config = _setup(tmp_path, {"items.yaml": text})
    name = "items.yaml"
    before = _bytes(tmp_path, name)

    # posture: --no-write never touches the bytes
    cold = _load(config, write=False)
    assert _bytes(tmp_path, name) == before
    assert not cold.load_writes

    old_bodies = {
        item.id: item.body
        for item in cold.local_items
        if item.id
    }

    # writable load
    project = _load(config)
    after = _bytes(tmp_path, name)
    minted_any = any(
        s in _MINTABLE
        and any(
            not o.key and o.error is None
            for o in navis.analyze_navis(old_bodies[f"NOTE-{i + 1:03d}"]).occurrences
        )
        for i, s in enumerate(shapes)
    )
    assert (project.load_writes.minted_navi_keys > 0) == minted_any
    if not minted_any:
        assert after == before  # refusal keeps bytes intact
        return

    # reload: every marker survives, keyless markers are validly keyed
    warm = _load(config, write=False)
    for i, shape in enumerate(shapes):
        old = navis.analyze_navis(old_bodies[f"NOTE-{i + 1:03d}"]).occurrences
        item = warm.item_by_id(f"NOTE-{i + 1:03d}")
        assert item is not None
        new = navis.analyze_navis(item.body).occurrences
        assert len(new) == len(old), (seed, shape)
        for o, n in zip(old, new):
            assert n.text == o.text, (seed, shape)
            if shape in _MINTABLE and not o.key and o.error is None:
                assert n.key
                assert keys_mod.malformed_key_message(n.key) is None
            else:
                assert n.key == o.key

    # idempotence: a second writable load writes nothing
    state = _bytes(tmp_path, name)
    again = _load(config)
    assert not again.load_writes
    assert _bytes(tmp_path, name) == state
