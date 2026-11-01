"""run-15 F15-1: a YAML list file whose whole list is a flow sequence.

`items: [{id: NOTE-001, ...}]` has no line a minted `key:` can be written
into, so `ids.insert_into_list` refuses the write. The mint keeps it an
ERROR -- an item with no key may not persist -- but the message must name
the shape and the fix, the same class as the flow-style front-matter
refusal on the markdown side, instead of a bare "could not write key"
repeated against bytes that can never change (fresh key minted per run).
"""

from __future__ import annotations

import re

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod

SCHEMA = (
    "site: { title: Flow List, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

KEY_RE = re.compile(r"\bkey: [0-9a-z]{11}\b")

REFUSAL = (
    "key cannot be added to this flow-style list; rewrite it in block style"
    " (one `- id:` entry per line)"
)
MARKDOWN_REFUSAL = (
    "key cannot be added to this flow-style front matter; rewrite it in block style"
)

FLOW_SEQ = 'items: [{id: NOTE-001, type: note, title: Flow, body: "plain text no marker"}]\n'


def _project(tmp_path, text: str, name: str = "f.yaml") -> str:
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / name).write_bytes(text.encode("utf-8"))
    return str(config)


FLOW_REFUSALS = {
    "flow-sequence": FLOW_SEQ,
    "flow-sequence-several": (
        'items: [{id: NOTE-001, type: note, title: A, body: "x"},'
        ' {id: NOTE-002, type: note, title: B, body: "y"}]\n'
    ),
    "nested-flow": (
        'items: [{id: NOTE-001, type: note, title: A, tags: [one, two], body: "x"}]\n'
    ),
    "flow-entry-multiline": (
        "items:\n  - {id: NOTE-001,\n    type: note,\n    title: T,\n    body: plain}\n"
    ),
    "crlf-flow-sequence": 'items: [{id: NOTE-001, type: note, title: Flow, body: "x"}]\r\n',
    "bom-flow-sequence": '\ufeffitems: [{id: NOTE-001, type: note, title: Flow, body: "x"}]\n',
}

MINTS = {
    "block-list": "items:\n  - id: NOTE-001\n    type: note\n    title: T\n    body: plain\n",
    "flow-map-in-block-list": "items:\n  - {id: NOTE-001, type: note, title: T, body: plain}\n",
    "quoted-body-in-flow-map": (
        'items:\n  - {id: NOTE-001, type: note, title: T, body: "plain: [bracketed] text"}\n'
    ),
    "anchor-alias": (
        "base: &base\n  - id: NOTE-001\n    type: note\n    title: T\n    body: plain\n"
        "items: *base\n"
    ),
    "merge-key": (
        "shared: &shared\n  title: T\n"
        "items:\n  - <<: *shared\n    id: NOTE-001\n    type: note\n    body: plain\n"
    ),
    "bom-block-list": "\ufeffitems:\n  - id: NOTE-001\n    type: note\n    title: T\n    body: plain\n",
}


def test_flow_sequence_mint_names_the_shape(tmp_path, capsys):
    config = _project(tmp_path, FLOW_SEQ)
    before = (tmp_path / "items" / "f.yaml").read_bytes()
    assert cli_mod.main(["-c", config, "navis", "ls"]) == 1
    err = capsys.readouterr().err
    assert REFUSAL in err
    assert (tmp_path / "items" / "f.yaml").read_bytes() == before


def test_flow_sequence_refusal_is_stable_across_runs(tmp_path, capsys):
    config = _project(tmp_path, FLOW_SEQ)
    path = tmp_path / "items" / "f.yaml"
    before = path.read_bytes()
    for _ in range(3):
        assert cli_mod.main(["-c", config, "navis", "ls"]) == 1
        assert REFUSAL in capsys.readouterr().err
    assert path.read_bytes() == before
    assert not KEY_RE.search(path.read_bytes().decode("utf-8"))


@pytest.mark.parametrize("name", sorted(FLOW_REFUSALS))
def test_flow_shapes_refuse_with_the_named_shape(tmp_path, capsys, name):
    config = _project(tmp_path, FLOW_REFUSALS[name])
    before = (tmp_path / "items" / "f.yaml").read_bytes()
    assert cli_mod.main(["-c", config, "navis", "ls"]) == 1
    assert REFUSAL in capsys.readouterr().err
    assert (tmp_path / "items" / "f.yaml").read_bytes() == before


@pytest.mark.parametrize("name", sorted(MINTS))
def test_block_and_single_line_flow_shapes_mint(tmp_path, capsys, name):
    config = _project(tmp_path, MINTS[name])
    path = tmp_path / "items" / "f.yaml"
    assert cli_mod.main(["-c", config, "navis", "ls"]) == 0
    out = capsys.readouterr().out
    assert "no Navis" in out
    assert KEY_RE.search(path.read_bytes().decode("utf-8"))


def test_multi_document_list_file_is_a_parse_error(tmp_path, capsys):
    text = (
        "items:\n  - id: NOTE-001\n    type: note\n    title: A\n    body: a\n"
        "---\n"
        "items:\n  - id: NOTE-002\n    type: note\n    title: B\n    body: b\n"
    )
    config = _project(tmp_path, text)
    before = (tmp_path / "items" / "f.yaml").read_bytes()
    assert cli_mod.main(["-c", config, "navis", "ls"]) == 1
    assert "single document" in capsys.readouterr().err
    assert (tmp_path / "items" / "f.yaml").read_bytes() == before


def test_empty_flow_list_is_clean(tmp_path, capsys):
    config = _project(tmp_path, "items: []\n")
    path = tmp_path / "items" / "f.yaml"
    assert cli_mod.main(["-c", config, "navis", "ls"]) == 0
    assert "no Navis" in capsys.readouterr().out
    assert path.read_bytes() == b"items: []\n"


def test_markdown_flow_front_matter_message_unchanged(tmp_path, capsys):
    text = "---\n{id: NOTE-001, type: note,\n title: T}\n---\n\nplain body\n"
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "f.md").write_bytes(text.encode("utf-8"))
    rc = cli_mod.main(["-c", str(config), "navis", "ls"])
    assert rc == 1
    assert MARKDOWN_REFUSAL in capsys.readouterr().err
    assert (items / "f.md").read_bytes() == text.encode("utf-8")
