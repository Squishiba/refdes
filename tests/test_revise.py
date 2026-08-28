"""revise (finding 12) -- and: revise: compound prefixes (finding 10).

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
import yaml
from helpers import REPO, _build_at

from refdes import build as build_mod
from refdes import lifecycle, parse, revise, seal, standards
from refdes.schema import load_project

# ------------------------------------------------------------ revise (finding 12)

REVISE_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
)


@pytest.fixture
def revise_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(REVISE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-001\n    label: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_renames_a_prefix_standalone_no_schema_change_needed(tmp_path):
    """Core, plain `revise`, no mutate_config: a prefix rename never depends
    on the schema at all (prefixes aren't type-checked), so this is the one
    rename category that always works standalone -- confirmed here, then
    the field/type cases (which do need the schema to move too) get their
    own tests below via mutate_config."""
    (tmp_path / "refdes.yaml").write_text(REVISE_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(prefixes={"BND": "LIM"})
    result = revise.apply(str(tmp_path), mapping)
    assert result.ok, result.errors
    assert result.changed_files == ["items/i.yaml"]
    assert result.id_changes == {"BND-001": "LIM-001"}
    text = (tmp_path / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "prefix: LIM" in text
    assert "id: LIM-001" in text


def test_revise_renames_type_and_prefix_atomically_with_schema_via_mutate_config(tmp_path):
    """Type and prefix renames need the schema to move with the data --
    plain revise doesn't touch refdes.yaml, but a caller-supplied
    mutate_config (what standards.py's upgrade chain uses) can make the two
    move together as one verified operation."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  constraint: { prefix: CON, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON\n"
        "items:\n  - id: CON-001\n    text: Board power density\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(types={"constraint": "bound"}, prefixes={"CON": "BND"})

    def bump(config_path):
        with open(config_path, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("constraint:", "bound:").replace(
            "constraint, prefix: CON", "bound, prefix: BND"
        )
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write(text)

    result = revise.apply(str(tmp_path), mapping, mutate_config=bump)
    assert result.ok, result.errors
    assert result.id_changes == {"CON-001": "BND-001"}
    text = (tmp_path / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "type: bound" in text
    assert "prefix: BND" in text
    assert "id: BND-001" in text


def test_revise_refuses_and_rolls_back_a_required_field_rename_without_schema_update(revise_project):
    """A required-field rename where the schema hasn't moved is refused, not
    silently applied -- the safety net this whole engine exists for. The
    file is byte-identical afterward: refused all the way back, not
    partially applied."""
    before = (revise_project / "items" / "i.yaml").read_text(encoding="utf-8")
    mapping = revise.Mapping(fields={"bound": {"label": "text"}})
    # This project's schema already says `text:` (not `label:`), so before
    # even rewriting anything, the *current* file (still saying `label:`)
    # already conflicts with the schema -- refused up front.
    result = revise.apply(str(revise_project), mapping)
    assert not result.ok
    after = (revise_project / "items" / "i.yaml").read_text(encoding="utf-8")
    assert after == before


VIOLATING_SCHEMA = (
    "site: { title: T, out: _site }\n"
    'link_types:\n  constrained_by: { inverse: constrains, label: "Constrained by" }\n'
    "types:\n"
    "  constraint:\n"
    "    prefix: CON\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      checks: { type: checks }\n"
    "    links:\n"
    "      constrained_by: [constraint]\n"
    "    body: {}\n"
)


@pytest.fixture
def violating_project(tmp_path):
    """A project whose build fails on a *check* -- the design does not meet a
    declared limit -- and on nothing else. The tool working, not failing."""
    (tmp_path / "refdes.yaml").write_text(VIOLATING_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n"
        "  - id: CON-THM-001\n    text: Board power density\n"
        '    limit: "<= 0.15 W/in^2"\n',
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-THM-001]\n"
        "checks:\n"
        "  - value: P_dens\n"
        "    against: CON-THM-001\n"
        "---\n\n"
        "```calc\nP_dens : W/in^2 = 0.2366 W/in^2\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_failing_check_does_not_block_a_rename(violating_project):
    """A decision currently violating a bound is a normal, often long-lived
    state -- this repository's own sample project ships one deliberately, as
    the teaching example on the front page of the docs. Refusing every
    vocabulary migration until it is resolved made `revise` and `standard
    upgrade` unusable on exactly the projects most likely to need them, and
    protected nothing: a rename moves the arithmetic and the limit together,
    so it cannot change a check's verdict."""
    project = _build_at(violating_project)
    assert any(d.code == "check_violation" for d in project.errors), [
        str(d) for d in project.errors
    ]

    result = revise.apply(str(violating_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert result.ok, result.errors
    assert result.id_changes == {"CON-THM-001": "BND-THM-001"}
    assert "id: BND-THM-001" in (
        violating_project / "items" / "con.yaml"
    ).read_text(encoding="utf-8")


def test_a_content_error_still_blocks_a_rename(violating_project):
    """The rule the refusal exists for is unchanged: a hash change caused by
    the rename must not be able to hide behind a document that doesn't
    validate. A dangling link is exactly that, and still refuses."""
    (violating_project / "items" / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-THM-999]\n"
        "---\n",
        encoding="utf-8",
    )
    result = revise.apply(str(violating_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert not result.ok
    assert any("existing build errors" in e for e in result.errors), result.errors
    assert "id: CON-THM-001" in (
        violating_project / "items" / "con.yaml"
    ).read_text(encoding="utf-8")


def test_a_missing_required_field_still_blocks_a_rename(violating_project):
    """The other half of the same rule: a schema the data no longer satisfies
    is a content problem, not a finding about the design."""
    (violating_project / "items" / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n  - id: CON-THM-001\n    text: No limit on this one.\n",
        encoding="utf-8",
    )
    result = revise.apply(str(violating_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert not result.ok
    assert any("existing build errors" in e for e in result.errors), result.errors


def test_standard_upgrade_runs_on_a_project_with_a_failing_check(tmp_path):
    """The end-to-end version of the same thing, through the bundled
    standard's own chain rather than a hand-written mapping."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n"
        "id: { width: 3, ledger: .refdes/ids.yaml }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "b.yaml").write_text(
        "items:\n  - id: CON-001\n    type: constraint\n    title: Board power density\n"
        '    limit: "<= 0.15 W/in^2"\n    status: active\n',
        encoding="utf-8",
    )
    (tmp_path / "items" / "d.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Regulator\nstatus: accepted\n"
        "constrained_by: [CON-001]\nchecks:\n  - value: P_dens\n    against: CON-001\n---\n\n"
        "```calc\nP_dens : W/in^2 = 0.2366 W/in^2\n```\n",
        encoding="utf-8",
    )
    steps = revise.apply_standard_upgrade(str(tmp_path), 2)
    assert [(s.from_version, s.to_version) for s in steps] == [(1, 2)]
    assert steps[0].result.ok, steps[0].result.errors
    assert steps[0].result.id_changes == {"CON-001": "BND-001"}
    assert "version: 2" in (tmp_path / "refdes.yaml").read_text(encoding="utf-8")


def test_revise_refuses_ambiguous_target_already_in_use(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  bound: { prefix: BND, fields: { label: { type: text }, text: { type: text } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults: { type: bound, prefix: BND }\n"
        "items:\n  - id: BND-001\n    label: x\n    text: y\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(fields={"bound": {"label": "text"}})
    result = revise.apply(str(tmp_path), mapping)
    assert not result.ok
    assert any("already exists" in e for e in result.errors)


def test_revise_refuses_a_self_contradictory_mapping():
    """Two different old names both wanting the same new name -- caught
    without even needing a project, since the mapping contradicts itself."""
    project = load_project(config_path=os.path.join(REPO, "refdes.yaml"))
    mapping = revise.Mapping(prefixes={"REQ": "R", "RSK": "R"})
    errors = revise.check_ambiguous(project, mapping)
    assert any("collides" in e for e in errors)


def _label_schema(tmp_path) -> None:
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  bound:\n"
        "    prefix: BND\n"
        "    fields:\n"
        "      label: { type: text, required: true }\n"
        "      limit: { type: limit, required: true }\n",
        encoding="utf-8",
    )


def _bump_label_field_to_text(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace(
        "label: { type: text, required: true }", "text:  { type: text, required: true }"
    )
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture
def label_project(tmp_path):
    """Schema and item file agree on `label:` -- the state a real project is
    actually in before a rename, unlike revise_project above (deliberately
    pre-broken, for the refusal test)."""
    _label_schema(tmp_path)
    items = tmp_path / "items"
    items.mkdir()
    (items / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-001\n    label: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_carries_baseline_hash_forward(label_project):
    """The core promise: a cosmetic rename must not make an untouched
    baseline suddenly report every item as 'changed'."""
    project = load_project(config_path=str(label_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors
    old_hash = project.items["BND-001"].content_hash
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"

    mapping = revise.Mapping(fields={"bound": {"label": "text"}})
    result = revise.apply(str(label_project), mapping, mutate_config=_bump_label_field_to_text)
    assert result.ok, result.errors
    assert result.baselines_updated == ["rev-a"]

    project2 = load_project(config_path=str(label_project / "refdes.yaml"))
    baseline = lifecycle.load_baseline(project2, "rev-a")
    new_hash = baseline.items["BND-001"]["hash"]
    assert new_hash != old_hash

    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False, accept_board_move=False)
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == []
    assert diff.added == []
    assert diff.removed == []


def _log_schema(tmp_path) -> None:
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    fields:\n"
        "      summary: { type: text, required: true }\n",
        encoding="utf-8",
    )


def _bump_summary_field_to_note(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace(
        "summary: { type: text, required: true }", "note:    { type: text, required: true }"
    )
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture
def log_project(tmp_path):
    _log_schema(tmp_path)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(
        "defaults:\n  type: log\n  prefix: LOG\n"
        "items:\n  - id: LOG-001\n    summary: First entry.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_carries_seal_hash_forward(log_project):
    """seal.py's append-only comparison is driven by the same content_hash
    a rename touches, and a mismatch there is a hard build ERROR, not a
    diff -- the caveat finding 12 flagged beyond what the finding itself
    stated. A cosmetic field rename on a sealed log entry must not turn a
    clean build into a seal-violation failure."""
    project = load_project(config_path=str(log_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=True)
    assert not project.errors
    old_hash = seal.load_seals(project, board="")["LOG-001"]

    mapping = revise.Mapping(fields={"log": {"summary": "note"}})
    result = revise.apply(str(log_project), mapping, mutate_config=_bump_summary_field_to_note)
    assert result.ok, result.errors
    assert result.seals_updated == ["(base)"]

    reloaded_seals = seal.load_seals(
        load_project(config_path=str(log_project / "refdes.yaml")), board=""
    )
    assert reloaded_seals.keys() == {"LOG-001"}
    assert reloaded_seals["LOG-001"] != old_hash

    project2 = load_project(config_path=str(log_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False, accept_board_move=False)
    assert not project2.errors
    assert project2.seal_violations == []


def test_plain_revise_ignores_a_baselines_missing_standard_field(label_project):
    """Plain revise (no standard_transition -- there's no chain, so no
    ambiguity about which baseline started where) matches purely by hash:
    a baseline written before the standard: field existed (or, as here, a
    hand-rolled project with no bundled standard at all) still gets carried
    forward. The chained, standard-upgrade case where a missing standard:
    genuinely has to be skipped is tested separately, where the ambiguity
    is real."""
    project = load_project(config_path=str(label_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    baseline_path = lifecycle.baseline_path(project, "rev-a")
    text = open(baseline_path, encoding="utf-8").read()
    assert "standard:" not in text  # nothing to record: no bundled standard pinned

    mapping = revise.Mapping(fields={"bound": {"label": "text"}})
    result = revise.apply(str(label_project), mapping, mutate_config=_bump_label_field_to_text)
    assert result.ok, result.errors
    assert result.baselines_updated == ["rev-a"]
    assert result.baselines_skipped_no_standard == []


def _write_fake_versioned_standard(root, versions, migrations=None):
    """`<root>/fake/v<N>/base.yaml` for each version in `versions` (a dict of
    version number -> base.yaml document), plus `<root>/fake/v<N>/migration.yaml`
    for each version number present in `migrations` -- a synthetic multi-
    version standard, isolated from the real bundled `hardware` standard, for
    tests that need to drive `revise.apply_standard_upgrade` through more
    than one version step."""
    for version, doc in versions.items():
        version_dir = os.path.join(str(root), "fake", f"v{version}")
        os.makedirs(version_dir, exist_ok=True)
        with open(os.path.join(version_dir, "base.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh)
    for version, doc in (migrations or {}).items():
        version_dir = os.path.join(str(root), "fake", f"v{version}")
        os.makedirs(version_dir, exist_ok=True)
        with open(os.path.join(version_dir, "migration.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh)


def test_standard_upgrade_skips_a_baseline_with_no_recorded_standard(tmp_path, monkeypatch):
    """The chained case, where skipping is the real, needed behavior: a
    baseline written before Baseline.standard existed (simulated here by
    stamping normally, then stripping the field back out) has nowhere
    recorded to say which version its hashes started at, so a multi-version
    chain must not guess -- it's left alone, reported as skipped, rather
    than silently matched against whichever version happens to be current."""
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path / "std"))
    monkeypatch.setattr(standards, "_KNOWN_BASES", ("fake",))
    _write_fake_versioned_standard(
        tmp_path / "std",
        {
            1: {"types": {"widget": {"prefix": "WID", "fields": {"title": {"type": "text", "required": True}}}}},
            2: {"types": {"widget": {"prefix": "WID", "fields": {"text": {"type": "text", "required": True}}}}},
        },
        migrations={2: {"fields": {"widget": {"title": "text"}}}},
    )

    project_root = tmp_path / "proj"
    (project_root / "items").mkdir(parents=True)
    (project_root / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\nstandard: { base: fake, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (project_root / "items" / "i.yaml").write_text(
        "defaults:\n  type: widget\n  prefix: WID\n"
        "items:\n  - id: WID-001\n    title: A widget.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(project_root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    # Strip the standard: field back out, simulating a baseline stamped
    # before it existed.
    baseline_path = lifecycle.baseline_path(project, "rev-a")
    with open(baseline_path, encoding="utf-8") as fh:
        stripped = "\n".join(ln for ln in fh.read().splitlines() if not ln.startswith(("standard:", "  base:", "  version:")))
    with open(baseline_path, "w", encoding="utf-8") as fh:
        fh.write(stripped + "\n")
    reloaded = lifecycle.load_baseline(project, "rev-a")
    assert reloaded.standard is None

    steps = revise.apply_standard_upgrade(str(project_root), 2)
    assert len(steps) == 1
    assert steps[0].result.ok, steps[0].result.errors
    assert steps[0].result.baselines_skipped_no_standard == ["rev-a"]
    assert steps[0].result.baselines_updated == []


def test_apply_standard_upgrade_chains_multiple_versions(tmp_path, monkeypatch):
    """v1 -> v4 works by chaining each version's own delta in order -- one
    apply() call per version step (extension 2), never a single merged
    jump straight from v1's schema to v4's.

    Against a synthetic bundle, and it must stay that way: the real
    `hardware` bundle has exactly one step (v1 -> v2), so it cannot exercise
    chaining at all, and it will only ever grow one step at a time. This test
    and the two around it are where the chain's ordering guarantees live --
    including the adversarial case below, where a later version reuses a name
    an earlier one freed. Do not rewrite them against the real bundle."""
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path / "std"))
    monkeypatch.setattr(standards, "_KNOWN_BASES", ("fake",))
    _write_fake_versioned_standard(
        tmp_path / "std",
        {
            1: {"types": {"widget": {"prefix": "WID", "fields": {"a": {"type": "text", "required": True}}}}},
            2: {"types": {"widget": {"prefix": "WID", "fields": {"b": {"type": "text", "required": True}}}}},
            3: {"types": {"widget": {"prefix": "WID", "fields": {"c": {"type": "text", "required": True}}}}},
            4: {"types": {"widget": {"prefix": "WID", "fields": {"d": {"type": "text", "required": True}}}}},
        },
        migrations={
            2: {"fields": {"widget": {"a": "b"}}},
            3: {"fields": {"widget": {"b": "c"}}},
            4: {"fields": {"widget": {"c": "d"}}},
        },
    )
    project_root = tmp_path / "proj"
    (project_root / "items").mkdir(parents=True)
    (project_root / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\nstandard: { base: fake, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (project_root / "items" / "i.yaml").write_text(
        "defaults:\n  type: widget\n  prefix: WID\n"
        "items:\n  - id: WID-001\n    a: Original value.\n",
        encoding="utf-8",
    )

    steps = revise.apply_standard_upgrade(str(project_root), 4)
    assert [(s.from_version, s.to_version) for s in steps] == [(1, 2), (2, 3), (3, 4)]
    assert all(s.result.ok for s in steps), [s.result.errors for s in steps]

    text = (project_root / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "d: Original value." in text
    assert "a:" not in text and "b:" not in text and "c:" not in text

    final_project = load_project(config_path=str(project_root / "refdes.yaml"))
    assert final_project.standard_version == 4


def test_apply_standard_upgrade_reused_field_name_across_versions(tmp_path, monkeypatch):
    """v2 renames title -> text; v3 independently renames notes -> title,
    reusing the name v2 just freed up. Chaining each step fully in order
    (never collapsing into one merged mapping) is what keeps this from
    colliding: by the time v3's own rename runs, nothing in the project is
    named `title` any more, so `notes -> title` lands cleanly and each
    original value ends up under the right final key, not swapped or lost."""
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path / "std"))
    monkeypatch.setattr(standards, "_KNOWN_BASES", ("fake",))
    _write_fake_versioned_standard(
        tmp_path / "std",
        {
            1: {"types": {"widget": {"prefix": "WID", "fields": {
                "title": {"type": "text", "required": True},
                "notes": {"type": "text", "required": True},
            }}}},
            2: {"types": {"widget": {"prefix": "WID", "fields": {
                "text": {"type": "text", "required": True},
                "notes": {"type": "text", "required": True},
            }}}},
            3: {"types": {"widget": {"prefix": "WID", "fields": {
                "text": {"type": "text", "required": True},
                "title": {"type": "text", "required": True},
            }}}},
        },
        migrations={
            2: {"fields": {"widget": {"title": "text"}}},
            3: {"fields": {"widget": {"notes": "title"}}},
        },
    )
    project_root = tmp_path / "proj"
    (project_root / "items").mkdir(parents=True)
    (project_root / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\nstandard: { base: fake, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (project_root / "items" / "i.yaml").write_text(
        "defaults:\n  type: widget\n  prefix: WID\n"
        "items:\n  - id: WID-001\n    title: Title value.\n    notes: Notes value.\n",
        encoding="utf-8",
    )

    steps = revise.apply_standard_upgrade(str(project_root), 3)
    assert len(steps) == 2
    assert all(s.result.ok for s in steps), [s.result.errors for s in steps]

    text = (project_root / "items" / "i.yaml").read_text(encoding="utf-8")
    assert "text: Title value." in text
    assert "title: Notes value." in text

    final_project = load_project(config_path=str(project_root / "refdes.yaml"))
    parse.load_items(final_project)
    build_mod.build(final_project, seal_write=False, reseal=False, accept_board_move=False)
    assert not final_project.errors


# ------------------------------------ revise: compound prefixes (finding 10)

COMPOUND_PREFIX_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  constrained_by: { inverse: constrains, label: \"Constrained by\" }\n"
    "types:\n"
    "  constraint:\n"
    "    prefix: CON\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      checks: { type: checks }\n"
    "    links:\n"
    "      constrained_by: [constraint]\n"
)


@pytest.fixture
def compound_prefix_project(tmp_path):
    """Mirrors this project's own convention: a `constraint` item using a
    compound prefix (`CON-THM`, base `CON` plus a board token) that a
    `decision` elsewhere references both through a `links:` field and a
    `checks:` entry, plus a prose mention that must never be rewritten."""
    (tmp_path / "refdes.yaml").write_text(COMPOUND_PREFIX_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n"
        "  - id: CON-THM-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-THM-001]\n"
        "checks:\n"
        "  - value: P_dens\n"
        "    against: CON-THM-001\n"
        "---\n\n"
        "The thermal budget in CON-THM-001 drives this choice.\n\n"
        "```calc\nP_dens : W/in^2 = 0.1 W/in^2\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_renames_a_compound_prefix_built_on_the_renamed_base(compound_prefix_project):
    """`ids.split_id`'s `PREFIX-NNN` shape treats a board-token-suffixed
    prefix (`CON-THM`) as one atomic string, so a bare dict lookup against
    `mapping.prefixes` (`{CON: BND}`) would silently miss it -- this project's
    own `refdes.yaml` documents exactly this convention (`REQ-PWR`, `CON-THM`,
    `DEC-PWR`, `TST-PWR`). Confirms the item's own `prefix:`/`id:` move.
    Prefix-only mapping, deliberately: renaming `types:` needs the schema to
    move with it (see `mutate_config`, covered by its own dedicated test
    above), which is orthogonal to what this is testing."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    assert result.id_changes == {"CON-THM-001": "BND-THM-001"}
    text = (compound_prefix_project / "items" / "con.yaml").read_text(encoding="utf-8")
    assert "prefix: BND-THM" in text
    assert "id: BND-THM-001" in text


def test_revise_does_not_rename_an_unrelated_prefix_sharing_a_letters(tmp_path):
    """`CONFIG` must never match a `CON` rename -- the required separator is
    the hyphen itself, not just the leading letters."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  widget: { prefix: CONFIG, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: widget\n  prefix: CONFIG\n"
        "items:\n  - id: CONFIG-001\n    text: Untouched.\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(tmp_path), mapping)
    assert result.ok, result.errors
    assert result.changed_files == []
    assert result.id_changes == {}


def test_revise_rewrites_a_link_value_and_a_checks_against_value(compound_prefix_project):
    """The item's own id relabeling (previous test) is only half of a real
    prefix rename -- every *other* item's structured reference to it
    (`constrained_by: [...]`, `checks: - against: ...`) must move too, or the
    rewritten project is left with dangling references (caught, and refused,
    before this fix existed -- see the commit message). A clean reload+build
    confirms it: nothing in the schema changed (prefix-only mapping), so a
    project that still validates end to end is proof every reference now
    agrees with the renamed id."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    text = (compound_prefix_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "constrained_by: [BND-THM-001]" in text
    assert "against: BND-THM-001" in text

    project = load_project(config_path=str(compound_prefix_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors


def test_revise_leaves_a_prose_mention_of_the_renamed_id_untouched(compound_prefix_project):
    """Only structured references move -- an id mentioned in body prose is
    never rewritten, the same posture `_rewrite_fields_and_links` already
    takes for field/link key renames."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    text = (compound_prefix_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "The thermal budget in CON-THM-001 drives this choice." in text


BLOCK_STYLE_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  constrained_by: { inverse: constrains, label: \"Constrained by\" }\n"
    "  addresses: { inverse: addressed_by, label: \"Addresses\" }\n"
    "types:\n"
    "  constraint:\n"
    "    prefix: CON\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "    links:\n"
    "      constrained_by: [constraint]\n"
    "  log:\n"
    "    prefix: LOG\n"
    "    fields:\n"
    "      summary: { type: text, required: true }\n"
    "    links:\n"
    "      addresses: [constraint]\n"
)


@pytest.fixture
def block_style_project(tmp_path):
    """The same references `compound_prefix_project` writes in flow style,
    written in the other legal YAML spelling instead: a bare key with
    `- TARGET` entries under it, in both a Markdown item and a list file."""
    (tmp_path / "refdes.yaml").write_text(BLOCK_STYLE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n"
        "  - id: CON-THM-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by:\n"
        "  - CON-THM-001\n"
        "---\n\n"
        "Prose mentioning CON-THM-001.\n",
        encoding="utf-8",
    )
    (items / "log.yaml").write_text(
        "defaults:\n  type: log\n  prefix: LOG\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Thermal review\n    addresses:\n      - CON-THM-001\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revise_rewrites_a_block_style_link_target_list(block_style_project):
    """Only flow-style values (`key: [A, B]`) had ever run through this
    engine. A block-style list -- the idiomatic spelling, and what a
    reference to a renamed id looks like in most real files -- was skipped,
    which did not leave those references merely untouched: the rewritten
    project then had a dangling link target, so the whole operation refused
    and rolled back, reporting the symptom ("constrained_by points at
    'CON-THM-001', which does not exist") and nothing about the cause."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(block_style_project), mapping)
    assert result.ok, result.errors
    assert result.id_changes == {"CON-THM-001": "BND-THM-001"}

    dec = (block_style_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "constrained_by:\n  - BND-THM-001\n" in dec
    log = (block_style_project / "items" / "log.yaml").read_text(encoding="utf-8")
    assert "addresses:\n      - BND-THM-001\n" in log

    project = load_project(config_path=str(block_style_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors, [str(d) for d in project.errors]


def test_block_sequence_rewrite_stops_before_the_next_item(block_style_project):
    """The walk down a block sequence must not run past the item it belongs
    to and into the next one's own lines."""
    (block_style_project / "items" / "log.yaml").write_text(
        "defaults:\n  type: log\n  prefix: LOG\n"
        "items:\n"
        "  - id: LOG-001\n    summary: First\n    addresses:\n      - CON-THM-001\n"
        "  - id: LOG-002\n    summary: Second\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(block_style_project), mapping)
    assert result.ok, result.errors
    log = (block_style_project / "items" / "log.yaml").read_text(encoding="utf-8")
    assert "      - BND-THM-001\n" in log
    assert "  - id: LOG-002\n" in log


def test_revise_reports_prose_left_pointing_at_a_renamed_id(compound_prefix_project):
    """Prose is deliberately never rewritten (see the test above), but leaving
    it alone *silently* is the wrong other half: a bare id that used to
    autolink renders as dead plain text afterward, and the command still
    reports success. The engine now names every line it did not touch and can
    no longer resolve."""
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    assert any(
        "items/dec.md" in ref and "CON-THM-001 -> BND-THM-001" in ref
        for ref in result.stale_references
    ), result.stale_references


def test_a_prose_id_that_still_resolves_is_not_reported_as_stale(tmp_path):
    """A mention that still resolves -- here through the renamed item's own
    `former_ids:` -- is not stale and must not be reported."""
    (tmp_path / "refdes.yaml").write_text(COMPOUND_PREFIX_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON-THM\n"
        "items:\n"
        "  - id: CON-THM-002\n    former_ids: [CON-THM-001]\n"
        "    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-THM-002]\n"
        "---\n\n"
        "Prose mentioning CON-THM-001, which still resolves.\n",
        encoding="utf-8",
    )
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(tmp_path), mapping)
    assert result.ok, result.errors
    assert result.stale_references == []


def test_revise_relabels_a_compound_prefix_in_the_id_ledger(compound_prefix_project):
    (compound_prefix_project / ".refdes").mkdir()
    (compound_prefix_project / ".refdes" / "ids.yaml").write_text(
        "burned:\n  CON-THM: 1\nallocated: []\n", encoding="utf-8"
    )
    mapping = revise.Mapping(prefixes={"CON": "BND"})
    result = revise.apply(str(compound_prefix_project), mapping)
    assert result.ok, result.errors
    ledger_text = (compound_prefix_project / ".refdes" / "ids.yaml").read_text(encoding="utf-8")
    assert "BND-THM: 1" in ledger_text
    assert "CON-THM" not in ledger_text
