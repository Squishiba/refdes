"""#184: a link verb may not be named like an engine-reserved front-matter key.

`on_change:` is the case that bit: front matter spells that key for the
engine, never for a link, so an item could never carry the verb. A scalar
target became a bogus change-policy error and the link was lost; a list
target was silently lost with a clean exit -- the worse half of the trap.
The whole reserved class (parse.RESERVED plus the overridable hint keys) is
guarded at load, not just that key.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes.schema import SchemaError, load_project

CONFIG = (
    "site: {title: T, out: _site}\n"
    "standard: { base: hardware, version: 3 }\n"
)

NOTE_TYPE = (
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      status: {type: enum, choices: [draft, live], default: draft}\n"
)


def _rejects(tmp_path, config: str, needle: str):
    write_project_config(tmp_path, config)
    try:
        load_project(start=str(tmp_path))
    except SchemaError as exc:
        assert needle in str(exc)
    else:
        raise AssertionError(f"config loaded; expected rejection of {needle!r}")


def test_verb_named_on_change_is_a_schema_error(tmp_path):
    _rejects(
        tmp_path,
        CONFIG
        + "link_types:\n  on_change: { inverse: changed_by }\n"
        + NOTE_TYPE
        + "    links:\n      on_change: [note]\n",
        "link_types.on_change: the link verb 'on_change' collides",
    )


def test_explicit_inverse_named_on_change_is_a_schema_error(tmp_path):
    _rejects(
        tmp_path,
        CONFIG + "link_types:\n  notes: { inverse: on_change }\n" + NOTE_TYPE,
        "link_types.notes.inverse: the link verb 'on_change' collides",
    )


def test_the_whole_reserved_class_is_guarded(tmp_path):
    for name in (
        "id",
        "type",
        "body",
        "former_ids",
        "key",
        "prefix",
        "board",
        "workspace",
    ):
        _rejects(
            tmp_path,
            CONFIG + f"link_types:\n  {name}: {{}}\n" + NOTE_TYPE,
            f"link_types.{name}: the link verb {name!r} collides",
        )


def test_an_ordinary_verb_still_loads(tmp_path):
    write_project_config(
        tmp_path,
        CONFIG + "link_types:\n  mentions: { inverse: mentioned_by }\n" + NOTE_TYPE,
    )
    project = load_project(start=str(tmp_path))
    assert not project.errors
    assert project.link_types["mentions"].inverse == "mentioned_by"
