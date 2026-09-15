"""Flow-style YAML spellings of `type:`/`section:`/`prefix:`/`id:` are invisible
to `refdes revise` (chunk 1: reproduce and characterise -- every test here FAILS
on main, by design; chunk 2 makes them pass).

`revise._rewrite_type_and_prefix_lines` only rewrites these four keys when each
is alone on its own line (`^(\\s*(?:-\\s+)?)(type|section):(\\s*)(\\S+)(\\s*)$`
and friends), so a value written inside a one-line flow mapping is never
touched. The file-level pass handles exactly two mapping kinds -- `types:`
(values of `type:` and `section:`) and `prefixes:` (values of `prefix:` and the
prefix half of `id:`) -- so those are the two axes below. `fields:`/`links:`/
`citation_keys:` are per-item passes; the links pass already reaches flow
mappings via `links._rewrite_flow_mapping_field`.

Characterised on main via the real CLI path
(`cli.main(["-c", cfg, "revise", mapping])`, with and without `--dry-run`):

  spelling                              prefixes:                          types:
  ------------------------------------  ---------------------------------  ---------------------------------
  block `defaults:` (control)           (c) works                          (b) refuses, rolls back
  flow `defaults: {type:, prefix:}`     (a) SILENT: exit 0, reports the    (a) SILENT: "nothing to do",
                                        id change, leaves `prefix: BND`    file unchanged
  flow item `- {id:, type:}`            (a) SILENT: exit 0, id stays       (a) SILENT: "nothing to do"
                                        BND-001
  flow section `- {section:}`           n/a (no id/prefix in the marker)   (a) SILENT: "nothing to do"
  md flow front matter `{id:, type:}`   (b) refuses, rolls back -- the     (a) SILENT: "nothing to do"
                                        key-mint pass corrupts it first
  md flow `defaults:` block             (a) SILENT: id renames, flow       (a) SILENT: "nothing to do"
                                        `prefix: BND` stays

The (b) refusal for md flow front matter is a second bug the probe surfaced:
`keys.mint_missing` inserts a `key:` line *before* the `{...}` front-matter
line instead of inside the braces, producing invalid YAML which revise's
reload-and-verify then (correctly) refuses and rolls back.

The (b) refusals for block-style `types:` renames are by design: plain `revise`
never edits the schema, so the rewrite lands, verification fails ("unknown
type"), and everything rolls back. The bug is that the flow spellings don't
even reach that stage -- they report success ("nothing to do") or partial
success while leaving the old spelling on disk.

Tests below assert the *fixed* behavior: flow spellings rewrite in place, and
a `types:` rename over a flow spelling goes through the same rewrite-then-
refuse path as its block-style control instead of reporting "nothing to do".
"""

from __future__ import annotations

import os

from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import revise

SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    fields:\n"
    "      text: { type: text, required: true }\n"
)


def _project(tmp_path, filename, content):
    write_project_config(tmp_path, SCHEMA)
    path = tmp_path / "items" / filename
    path.parent.mkdir(exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_mapping(tmp_path, text):
    path = tmp_path / "mapping.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _cli_revise(tmp_path, mapping_path, dry_run=False):
    argv = ["-c", str(tmp_path / "refdes-project.yaml"), "revise"]
    if dry_run:
        argv.append("--dry-run")
    argv.append(str(mapping_path))
    return cli_mod.main(argv)


# --------------------------------------------------------------- prefixes:

PREFIX_MAPPING = "prefixes:\n  BND: LIM\n"


def test_cli_revise_rewrites_prefix_inside_flow_defaults(tmp_path, capsys):
    """`defaults: { type: bound, prefix: BND }` -- today the run exits 0 and
    reports the id change while the flow `prefix: BND` stays, leaving the
    file's own defaults disagreeing with every id in it."""
    path = _project(
        tmp_path, "i.yaml",
        "defaults: { type: bound, prefix: BND }\n"
        "items:\n  - id: BND-001\n    text: Hello\n",
    )
    mapping = _write_mapping(tmp_path, PREFIX_MAPPING)
    assert _cli_revise(tmp_path, mapping) == 0
    text = path.read_text(encoding="utf-8")
    assert "prefix: LIM" in text
    assert "BND" not in text


def test_cli_revise_rewrites_id_inside_flow_item_mapping(tmp_path, capsys):
    """`- {id: BND-001, text: Hello}` -- today the run exits 0, mints the
    key inside the braces, and leaves the id itself on the old prefix."""
    path = _project(
        tmp_path, "i.yaml",
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n  - {id: BND-001, text: Hello}\n",
    )
    mapping = _write_mapping(tmp_path, PREFIX_MAPPING)
    assert _cli_revise(tmp_path, mapping) == 0
    text = path.read_text(encoding="utf-8")
    assert "id: LIM-001" in text
    assert "BND-001" not in text


def test_cli_revise_renames_flow_item_id_and_flow_defaults_prefix_together(tmp_path, capsys):
    """Both flow spellings in one file: the whole rename must land."""
    path = _project(
        tmp_path, "i.yaml",
        "defaults: { type: bound, prefix: BND }\n"
        "items:\n  - {id: BND-001, type: bound, text: Hello}\n",
    )
    mapping = _write_mapping(tmp_path, PREFIX_MAPPING)
    assert _cli_revise(tmp_path, mapping) == 0
    text = path.read_text(encoding="utf-8")
    assert "id: LIM-001" in text
    assert "prefix: LIM" in text
    assert "BND" not in text


def test_cli_revise_rewrites_prefix_in_markdown_flow_defaults_block(tmp_path, capsys):
    """Markdown supports a flow `defaults:` as its first fenced block; today
    the block-style id renames but the flow `prefix: BND` is left behind."""
    path = _project(
        tmp_path, "i.md",
        "---\ndefaults: { type: bound, prefix: BND }\n---\n---\nid: BND-001\ntext: Hello\n---\n",
    )
    mapping = _write_mapping(tmp_path, PREFIX_MAPPING)
    assert _cli_revise(tmp_path, mapping) == 0
    text = path.read_text(encoding="utf-8")
    assert "prefix: LIM" in text
    assert "id: LIM-001" in text
    assert "BND" not in text


def test_cli_revise_renames_id_in_markdown_flow_front_matter(tmp_path, capsys):
    """Markdown supports a flow mapping as an item's front matter (the first
    fenced block parses as any YAML mapping). Today the prefix rename refuses:
    the key-mint pass inserts `key:` *before* the `{...}` line, producing
    invalid YAML that the reload-and-verify step rolls back. Fixed behavior:
    the key and the id both land inside the braces, file stays valid."""
    path = _project(
        tmp_path, "i.md",
        "---\n{id: BND-001, type: bound, text: Hello}\n---\n",
    )
    mapping = _write_mapping(tmp_path, PREFIX_MAPPING)
    assert _cli_revise(tmp_path, mapping) == 0
    text = path.read_text(encoding="utf-8")
    assert "id: LIM-001" in text
    assert "BND-001" not in text


# ------------------------------------------------------------------ types:
#
# A plain CLI `types:` rename never succeeds (revise doesn't edit the schema,
# so verification always rolls it back -- the block control below refuses with
# "unknown type"). The bug is that flow spellings don't even reach that
# rewrite: they report "nothing to do -- mapping doesn't apply to this
# project" and exit 0. Fixed behavior for the CLI tests: flow spellings
# behave like the block control -- the rewrite is attempted and verification
# refuses -- never "nothing to do".


TYPE_MAPPING = "types:\n  bound: constraint\n"


def test_cli_revise_types_rename_reaches_flow_defaults(tmp_path, capsys):
    _project(
        tmp_path, "i.yaml",
        "defaults: { type: bound, prefix: BND }\n"
        "items:\n  - id: BND-001\n    text: Hello\n",
    )
    mapping = _write_mapping(tmp_path, TYPE_MAPPING)
    status = _cli_revise(tmp_path, mapping)
    out = capsys.readouterr()
    assert "nothing to do" not in out.out
    assert status != 0
    assert "unknown type 'constraint'" in out.err


def test_cli_revise_types_rename_reaches_flow_item_type(tmp_path, capsys):
    _project(
        tmp_path, "i.yaml",
        "defaults:\n  prefix: BND\n"
        "items:\n  - {id: BND-001, type: bound, text: Hello}\n",
    )
    mapping = _write_mapping(tmp_path, TYPE_MAPPING)
    status = _cli_revise(tmp_path, mapping)
    out = capsys.readouterr()
    assert "nothing to do" not in out.out
    assert status != 0
    assert "unknown type 'constraint'" in out.err


def test_cli_revise_types_rename_reaches_flow_section_marker(tmp_path, capsys):
    _project(
        tmp_path, "i.yaml",
        "items:\n  - {section: bound}\n  - {id: BND-001, type: bound, text: Hello}\n",
    )
    mapping = _write_mapping(tmp_path, TYPE_MAPPING)
    status = _cli_revise(tmp_path, mapping)
    out = capsys.readouterr()
    assert "nothing to do" not in out.out
    assert status != 0
    assert "unknown type 'constraint'" in out.err


def test_cli_revise_types_rename_reaches_markdown_flow_front_matter(tmp_path, capsys):
    _project(
        tmp_path, "i.md",
        "---\n{id: BND-001, type: bound, text: Hello}\n---\n",
    )
    mapping = _write_mapping(tmp_path, TYPE_MAPPING)
    status = _cli_revise(tmp_path, mapping)
    out = capsys.readouterr()
    assert "nothing to do" not in out.out
    assert status != 0
    assert "unknown type 'constraint'" in out.err


# ------------------------------------------------------- types: end-to-end
#
# The only way a `types:` rename can actually land is a caller that moves the
# schema with it (mutate_config -- what `standard upgrade` uses, see
# test_revise.py's block-style equivalent). These assert the rename completes
# through that path with the values written in flow style.


def _bump_schema(config_path):
    schema_path = os.path.join(os.path.dirname(config_path), "refdes-schema.yaml")
    with open(schema_path, encoding="utf-8") as fh:
        text = fh.read()
    with open(schema_path, "w", encoding="utf-8") as fh:
        fh.write(text.replace("bound:", "constraint:"))


def test_revise_rewrites_type_inside_flow_defaults_end_to_end(tmp_path):
    _project(
        tmp_path, "i.yaml",
        "defaults: { type: bound, prefix: BND }\n"
        "items:\n  - id: BND-001\n    text: Hello\n",
    )
    result = revise.apply(
        str(tmp_path), revise.Mapping(types={"bound": "constraint"}),
        mutate_config=_bump_schema,
    )
    assert result.ok, result.errors
    text = (tmp_path / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "type: constraint" in text
    assert "bound" not in text


def test_revise_rewrites_type_inside_flow_item_mapping_end_to_end(tmp_path):
    _project(
        tmp_path, "i.yaml",
        "defaults:\n  prefix: BND\n"
        "items:\n  - {id: BND-001, type: bound, text: Hello}\n",
    )
    result = revise.apply(
        str(tmp_path), revise.Mapping(types={"bound": "constraint"}),
        mutate_config=_bump_schema,
    )
    assert result.ok, result.errors
    text = (tmp_path / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "type: constraint" in text
    assert "bound" not in text


def test_revise_rewrites_section_inside_flow_marker_end_to_end(tmp_path):
    _project(
        tmp_path, "i.yaml",
        "items:\n  - {section: bound}\n  - {id: BND-001, type: bound, text: Hello}\n",
    )
    result = revise.apply(
        str(tmp_path), revise.Mapping(types={"bound": "constraint"}),
        mutate_config=_bump_schema,
    )
    assert result.ok, result.errors
    text = (tmp_path / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "section: constraint" in text
    assert "bound" not in text
