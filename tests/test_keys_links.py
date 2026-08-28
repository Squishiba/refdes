"""keys layer 2: hashing + links -- and: hash-format migration.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import yaml

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import lifecycle, parse, seal
from refdes import links as links_mod
from refdes.schema import load_project

# ---------------------------------------------------- keys layer 2: hashing + links
#
# docs/design/keys.md §5 (link targets hashed as resolved keys, with the
# baseline/seal hash-format migration) and the expand-and-freeze half of §3
# (bare display id -> `DISPLAY-ID@key` composite, and resolution reading only
# the part after '@'). Deliberately excludes the corruption lint (§6) and
# revise.py/former_ids.py -- neither is touched by this layer.

LINKS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  refines: { inverse: refined_by, label: Refines }\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    label: Requirement\n"
    "    fields:\n"
    "      text: { type: text, required: true }\n"
    "    links:\n"
    "      refines: [requirement]\n"
)


def _links_project(tmp_path, items_yaml):
    (tmp_path / "refdes.yaml").write_text(LINKS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _keyed_links_project(tmp_path, items_yaml):
    """A _links_project that already has keys minted (links still bare) --
    the starting state most of this section's tests want, since expansion
    and hashing both need a target's key to exist first."""
    root = _links_project(tmp_path, items_yaml)
    config = str(root / "refdes.yaml")
    project = load_project(config_path=config)
    parse.load_items(project)
    keys_mod.mint_missing(project)
    return root


def test_resolve_link_target_bare_and_composite_forms(tmp_path):
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Target.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    target = project.items["REQ-001"]
    by_key = {target.key: target}

    assert build_mod.resolve_link_target(by_key, project, "REQ-001") is target
    assert build_mod.resolve_link_target(by_key, project, f"REQ-001@{target.key}") is target
    # The composite's key is what resolution trusts -- a mismatched display
    # half is irrelevant, not even consulted as a fallback.
    assert build_mod.resolve_link_target(by_key, project, f"WRONG-LABEL@{target.key}") is target


def test_resolve_link_target_unknown_key_does_not_fall_back_to_display_text(tmp_path):
    """§3: "An unknown key is an error, and the display half is deliberately
    not used as a fallback" -- proven directly, not just asserted."""
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Target.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    by_key = {project.items["REQ-001"].key: project.items["REQ-001"]}

    assert build_mod.resolve_link_target(by_key, project, "REQ-001@notarealkey") is None


def test_hash_is_neutral_to_renaming_a_linked_items_display_id(tmp_path):
    """docs/design/keys.md §5's central claim, verified empirically rather
    than asserted: once a target has a key and the reference to it is
    composite text, renaming the target's display id must not change the
    hash of anything that links to it.

    The composite reference is hand-authored here, deliberately, rather
    than produced by links.expand_missing() (links.py's own module) --
    §5's hashing change has to stand on its own, independent of §3's link
    rewriting, since these two pieces are meant to be reviewable and
    revertible independently (they land as separate commits). The full,
    end-to-end version of this same proof -- an actually-authored bare
    reference, expanded by the tool, then the target renamed -- lives in
    the links section further down, once links.py exists to produce it.
    """
    root = _links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Target.\n"
        "  - id: REQ-002\n    text: Source.\n    refines: [REQ-001]\n",
    )
    config = str(root / "refdes.yaml")
    project = load_project(config_path=config)
    parse.load_items(project)
    keys_mod.mint_missing(project)
    target_key = project.items["REQ-001"].key
    assert target_key

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    composite = text.replace("refines: [REQ-001]", f"refines: [REQ-001@{target_key}]")
    assert composite != text
    (root / "items" / "r.yaml").write_text(composite, encoding="utf-8")

    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False)
    hash_before = project.items["REQ-002"].content_hash
    assert hash_before  # sanity: a hash was actually computed

    renamed = composite.replace("id: REQ-001\n", "id: REQ-999\n")
    assert renamed != composite
    (root / "items" / "r.yaml").write_text(renamed, encoding="utf-8")

    project2 = load_project(config_path=config)
    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False)
    hash_after = project2.items["REQ-002"].content_hash

    assert hash_after == hash_before


def test_hash_is_neutral_to_expanding_a_bare_link_into_composite_form(tmp_path):
    """The companion claim, isolated from the rename above: rewriting a bare
    reference to its composite form is, by itself, a pure no-op for hashing
    -- build.compute_hashes already resolves a target to its key whether the
    on-disk text is bare or composite (_link_hash_token), so the syntax
    change alone must never touch a hash."""
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Target.\n"
        "  - id: REQ-002\n    text: Source.\n    refines: [REQ-001]\n",
    )
    config = str(root / "refdes.yaml")

    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False)
    hash_before = project.items["REQ-002"].content_hash
    text_before = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "REQ-001@" not in text_before  # still bare

    written = links_mod.expand_missing(project)
    assert written
    text_after = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "REQ-001@" in text_after

    project2 = load_project(config_path=config)
    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False)
    hash_after = project2.items["REQ-002"].content_hash

    assert hash_after == hash_before


def test_expand_missing_rewrites_same_line_list_and_freezes_it(tmp_path):
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Target.\n"
        "  - id: REQ-002\n    text: Source.\n    refines: [REQ-001]\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)

    written = links_mod.expand_missing(project)
    assert len(written) == 1
    item, link_name, old, new = written[0]
    assert item.id == "REQ-002"
    assert link_name == "refines"
    assert old == "REQ-001"
    assert new.startswith("REQ-001@")
    assert item.links["refines"] == [new]  # updated in memory too, not just on disk

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert f"refines: [{new}]" in text

    # Frozen: a second pass finds nothing left to expand, and never touches
    # the composite it already wrote.
    project2 = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project2)
    assert links_mod.expand_missing(project2) == []
    assert (root / "items" / "r.yaml").read_text(encoding="utf-8") == text


def test_expand_missing_rewrites_block_style_sequence(tmp_path):
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Target.\n"
        "  - id: REQ-002\n    text: Source.\n    refines:\n      - REQ-001\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)

    written = links_mod.expand_missing(project)
    assert len(written) == 1
    _item, _link_name, _old, new = written[0]

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert f"- {new}" in text
    assert "- REQ-001\n" not in text  # the bare line is gone, not duplicated

    reparsed = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(reparsed)
    assert reparsed.items["REQ-002"].links["refines"] == [new]


def test_expand_missing_rewrites_markdown_front_matter(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "link_types:\n  refines: { inverse: refined_by, label: Refines }\n"
        "types:\n"
        "  decision:\n"
        "    prefix: DEC\n    label: Decision\n"
        "    fields:\n      title: { type: text, required: true }\n"
        "    links:\n      refines: [decision]\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "a.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Target.\n---\n", encoding="utf-8"
    )
    (tmp_path / "items" / "b.md").write_text(
        "---\nid: DEC-002\ntype: decision\ntitle: Source.\nrefines: [DEC-001]\n---\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes.yaml")
    project = load_project(config_path=config)
    parse.load_items(project)
    keys_mod.mint_missing(project)
    project = load_project(config_path=config)
    parse.load_items(project)

    written = links_mod.expand_missing(project)
    assert len(written) == 1
    _item, _link_name, _old, new = written[0]

    text = (tmp_path / "items" / "b.md").read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert f"refines: [{new}]" in front_matter

    reparsed = load_project(config_path=config)
    parse.load_items(reparsed)
    assert reparsed.items["DEC-002"].links["refines"] == [new]


def test_expand_missing_skips_flow_style_entries(tmp_path):
    """A known, honestly-scoped gap (links.py's own module docstring and
    _rewrite_item_links's): a flow-style list entry is never matched by the
    key-name-opens-the-line pattern expansion depends on, so it stays bare.
    §2's resolution rule keeps it fully working regardless."""
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Target.\n"
        "  - {id: REQ-002, text: Source., refines: [REQ-001]}\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)

    assert links_mod.expand_missing(project) == []
    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "REQ-001@" not in text
    assert "refines: [REQ-001]" in text

    # Still fully usable -- the bare reference still resolves.
    build_mod.build(project, seal_write=False, reseal=False)
    assert not project.errors


def test_expand_missing_skips_a_target_with_no_key_yet(tmp_path):
    """A target that hasn't been minted yet (e.g. --no-write skipped it, or
    write-back to that specific item failed) has nothing to expand into --
    the reference is left bare, not half-written or errored."""
    root = _links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Target.\n"
        "  - id: REQ-002\n    text: Source.\n    refines: [REQ-001]\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    assert project.items["REQ-001"].key == ""  # never minted in this test

    assert links_mod.expand_missing(project) == []
    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "refines: [REQ-001]" in text


def test_no_write_suppresses_link_expansion_and_reports_one_info_line(tmp_path):
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Target.\n"
        "  - id: REQ-002\n    text: Source.\n    refines: [REQ-001]\n",
    )
    config = str(root / "refdes.yaml")
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")

    status = cli_mod.main(["-c", config, "--no-write", "check", "--verbose"])
    assert status == 0
    after = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert before == after

    project = load_project(config_path=config)
    parse.load_items(project)
    written = links_mod.expand_missing(project, write=False)
    assert written == []
    info = [d for d in project.diagnostics if d.level == "info"]
    assert any("1 link reference has not been expanded" in d.message for d in info)
    assert any("--no-write" in d.message for d in info)


# ------------------------------------------------------------- hash-format migration


def _legacy_baseline_entry(project, item_id: str) -> dict:
    """The hash a hash_format-1 (pre-keys) stamp would have recorded for
    this item, right now -- built via build.legacy_hash_for so these tests
    don't hand-roll their own second implementation of the old format."""
    item = project.items[item_id]
    return {
        "hash": build_mod.legacy_hash_for(item, project),
        "type": item.type,
        "title": item.title,
    }


def _write_legacy_baseline(root, name: str, items: dict) -> None:
    """Hand-write a `.refdes/baselines/<name>.yaml` in the shape a stamp
    made before hash_format existed would have (no hash_format key on any
    entry) -- lifecycle.stamp() itself can't produce this shape any more, so
    these tests construct it directly to exercise the migration path."""
    path = root / ".refdes" / "baselines" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "kind": "revision", "name": name, "stamped_at": "2026-01-01T00:00:00Z",
        "stamped_by": "tester", "refdes_version": "0.0.0-test", "items": items,
    }
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def _built_links_project(root):
    config = str(root / "refdes.yaml")
    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def test_baseline_migration_carries_forward_an_unedited_entry(tmp_path):
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Unedited.\n",
    )
    project = _built_links_project(root)
    _write_legacy_baseline(root, "rev-a", {"REQ-001": _legacy_baseline_entry(project, "REQ-001")})

    baseline = lifecycle.load_baseline(project, "rev-a")
    assert "hash_format" not in baseline.items["REQ-001"]

    report = lifecycle.migrate_hash_format(project, baseline, write=True)
    assert report.carried == ["REQ-001"]
    assert report.uncomparable == []
    assert report.changed is True
    assert baseline.items["REQ-001"]["hash"] == project.items["REQ-001"].content_hash
    assert baseline.items["REQ-001"]["hash_format"] == build_mod.HASH_FORMAT

    # Persisted, not just mutated in memory.
    reloaded = lifecycle.load_baseline(project, "rev-a")
    assert reloaded.items["REQ-001"]["hash_format"] == build_mod.HASH_FORMAT
    assert reloaded.items["REQ-001"]["hash"] == project.items["REQ-001"].content_hash


def test_baseline_migration_reports_uncomparable_for_a_real_edit_without_rewriting(tmp_path):
    """§5(c): a format-1 entry that does NOT match the item's recomputed
    legacy hash genuinely changed since the stamp, for a reason unrelated to
    the format switch -- left alone, not guessed at."""
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Original.\n",
    )
    project = _built_links_project(root)
    stale_entry = _legacy_baseline_entry(project, "REQ-001")

    # Edit the item's content in the SOURCE file (not just in memory) after
    # the "stamp" -- a real, on-disk change since the baseline was recorded.
    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    text = text.replace("text: Original.", "text: Edited after the stamp.")
    (root / "items" / "r.yaml").write_text(text, encoding="utf-8")
    project2 = _built_links_project(root)

    _write_legacy_baseline(root, "rev-b", {"REQ-001": stale_entry})
    baseline = lifecycle.load_baseline(project2, "rev-b")
    before = dict(baseline.items["REQ-001"])

    report = lifecycle.migrate_hash_format(project2, baseline, write=True)
    assert report.carried == []
    assert report.uncomparable == ["REQ-001"]
    assert report.changed is False
    assert baseline.items["REQ-001"] == before  # untouched, not rewritten

    reloaded = lifecycle.load_baseline(project2, "rev-b")
    assert "hash_format" not in reloaded.items["REQ-001"]  # file itself untouched too


def test_diff_against_a_legacy_baseline_reports_unedited_items_as_unchanged(tmp_path):
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Unedited.\n",
    )
    project = _built_links_project(root)
    _write_legacy_baseline(root, "rev-a", {"REQ-001": _legacy_baseline_entry(project, "REQ-001")})

    baseline = lifecycle.load_baseline(project, "rev-a")
    diff = lifecycle.diff_against(project, baseline)
    assert diff.changed == []
    assert diff.added == []
    assert diff.unchanged_count == 1


def test_stamp_same_name_after_hash_format_change_is_unchanged_not_conflict(tmp_path):
    """The false "conflict" this migration exists to prevent: re-stamping an
    unedited project under a name a hash_format-1 baseline already used must
    report `unchanged`, not a spurious content conflict caused purely by the
    hash definition moving underneath it."""
    root = _keyed_links_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Unedited.\n",
    )
    project = _built_links_project(root)
    _write_legacy_baseline(root, "rev-a", {"REQ-001": _legacy_baseline_entry(project, "REQ-001")})

    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "unchanged"


def test_seal_migration_silently_upgrades_an_unedited_entry_and_still_catches_a_real_edit(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  log:\n    prefix: LOG\n    label: Log\n    append_only: true\n"
        "    fields:\n      summary: { type: text, required: true }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(
        "defaults: { type: log }\nitems:\n  - id: LOG-001\n    summary: First.\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes.yaml")
    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False)
    legacy_hash = build_mod.legacy_hash_for(project.items["LOG-001"], project)

    seal_path = tmp_path / ".refdes" / "log-seal.yaml"
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with open(seal_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"sealed": {"LOG-001": legacy_hash}}, fh)

    # Read-only: not a violation, but the file is untouched (write=False).
    project2 = load_project(config_path=config)
    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False)
    assert "LOG-001" not in project2.seal_violations
    assert seal.load_seals(project2)["LOG-001"] == legacy_hash

    # Write-enabled: silently upgraded in place, no warning (nothing was
    # actually edited -- only the hash definition moved).
    project3 = load_project(config_path=config)
    parse.load_items(project3)
    build_mod.build(project3, seal_write=True, reseal=False)
    assert "LOG-001" not in project3.seal_violations
    assert seal.load_seals(project3)["LOG-001"] == project3.items["LOG-001"].content_hash
    assert not any("resealed" in d.message for d in project3.warnings)

    # A real edit after the upgrade is still caught, exactly as before.
    text = (items / "log.yaml").read_text(encoding="utf-8")
    text = text.replace("summary: First.", "summary: Edited.")
    (items / "log.yaml").write_text(text, encoding="utf-8")
    project4 = load_project(config_path=config)
    parse.load_items(project4)
    build_mod.build(project4, seal_write=False, reseal=False)
    assert "LOG-001" in project4.seal_violations
