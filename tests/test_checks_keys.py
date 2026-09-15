"""`checks: [{value, against}]` composite-key rename safety.

Closes the disclosed gap docs/design/backlog.md's "Surrogate keys --
remaining layers" section and docs/design/keys.md both flag: `against:`
resolved as a bare display id, not covered by links.expand_missing(), and
not rename-safe. This makes it behave exactly like a structured link target
(docs/design/keys.md §3) -- same `DISPLAY-ID@key` expansion, same refresh-
on-rename rules, same Layer 1/3 diagnostics, same key-reduction for hashing.
"""

from __future__ import annotations

import yaml
from conftest import write_project_config

from refdes import adopt as adopt_mod
from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import lifecycle, seal
from refdes import parse
from refdes.schema import load_project

CHECKS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    label: Bound\n"
    "    fields:\n"
    "      text: { type: text, required: true }\n"
    "      limit: { type: limit, required: true, on_change: invalidate }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    label: Decision\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      checks: { type: checks, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)


def _checks_project(
    tmp_path,
    bounds_yaml,
    decision_front_matter,
    calc_block="I_total = 5 A",
    decision_name="dec.md",
):
    write_project_config(tmp_path, CHECKS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "bounds.yaml").write_text(bounds_yaml, encoding="utf-8")
    (items / decision_name).write_text(
        "---\n" + decision_front_matter + "---\n\n"
        f"```calc\n{calc_block}\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def _built(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def _loaded(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    return project


_ONE_BOUND = (
    "defaults: { type: bound }\n"
    "items:\n  - id: BND-001\n    text: Target.\n    limit: \"<= 10 A\"\n"
)

_BLOCK_CHECKS = (
    "id: DEC-001\ntype: decision\ntitle: Uses the bound.\n"
    "checks:\n  - value: I_total\n    against: BND-001\n"
)

_FLOW_CHECKS = (
    "id: DEC-001\ntype: decision\ntitle: Uses the bound.\n"
    "checks:\n  - {value: I_total, against: BND-001}\n"
)


# ------------------------------------------------------------- expansion


def test_bare_against_expands_to_composite_on_writable_load(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")

    assert cli_mod.main(["-c", config, "check"]) == 0

    project = _loaded(root)
    target_key = project.item_by_id("BND-001").key
    assert target_key

    text = (root / "items" / "dec.md").read_text(encoding="utf-8")
    assert f"against: BND-001@{target_key}" in text


def test_no_write_leaves_against_bare(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")
    before = (root / "items" / "dec.md").read_text(encoding="utf-8")
    assert "against: BND-001\n" in before

    assert cli_mod.main(["-c", config, "--no-write", "check"]) == 0

    after = (root / "items" / "dec.md").read_text(encoding="utf-8")
    assert before == after


def test_expand_missing_checks_rewrites_flow_style_entry(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _FLOW_CHECKS)
    config = str(root / "refdes-project.yaml")

    assert cli_mod.main(["-c", config, "check"]) == 0

    project = _loaded(root)
    target_key = project.item_by_id("BND-001").key
    text = (root / "items" / "dec.md").read_text(encoding="utf-8")
    assert f"{{value: I_total, against: BND-001@{target_key}}}" in text


# --------------------------------------------------------------- refresh


def _expand_then_rename_bound(root, old_id="BND-001", new_id="BND-099"):
    config = str(root / "refdes-project.yaml")
    project = _loaded(root)
    target_key = project.item_by_id(old_id).key
    assert cli_mod.main(["-c", config, "check"]) == 0

    path = root / "items" / "bounds.yaml"
    text = path.read_text(encoding="utf-8")
    renamed = text.replace(f"id: {old_id}\n", f"id: {new_id}\n")
    assert renamed != text
    path.write_text(renamed, encoding="utf-8")
    return config, target_key


def test_rename_refreshes_against_in_block_shape_key_unchanged(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config, target_key = _expand_then_rename_bound(root)

    assert cli_mod.main(["-c", config, "check"]) == 0
    refreshed = (root / "items" / "dec.md").read_text(encoding="utf-8")
    assert f"against: BND-099@{target_key}" in refreshed
    assert "against: BND-001@" not in refreshed


def test_rename_refreshes_against_in_flow_shape_key_unchanged(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _FLOW_CHECKS)
    config, target_key = _expand_then_rename_bound(root)

    assert cli_mod.main(["-c", config, "check"]) == 0
    refreshed = (root / "items" / "dec.md").read_text(encoding="utf-8")
    assert f"BND-099@{target_key}" in refreshed
    assert "BND-001@" not in refreshed


def test_no_write_leaves_stale_against_composite_unchanged(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config, target_key = _expand_then_rename_bound(root)
    before = (root / "items" / "dec.md").read_bytes()

    assert cli_mod.main(["-c", config, "--no-write", "check"]) == 0
    assert (root / "items" / "dec.md").read_bytes() == before
    assert f"against: BND-001@{target_key}" in before.decode()


# ---------------------------------------------------- hash stability


def test_rename_of_target_does_not_change_checking_items_content_hash(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0  # expand to composite

    before = _built(root)
    hash_before = before.item_by_id("DEC-001").content_hash
    assert hash_before

    path = root / "items" / "bounds.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("id: BND-001\n", "id: BND-099\n"), encoding="utf-8")
    assert cli_mod.main(["-c", config, "check"]) == 0  # refresh label

    after = _built(root)
    hash_after = after.item_by_id("DEC-001").content_hash
    assert hash_after == hash_before


def test_sabotage_hash_reduction_would_fail_without_it(tmp_path):
    """Direct proof the reduction is load-bearing: hashing the raw
    `against:` composite text (the pre-format-3 behaviour) DOES churn on a
    rename -- so the format-3 payload had better not do that."""
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0

    project = _loaded(root)
    dec = project.item_by_id("DEC-001")
    bnd = project.item_by_id("BND-001")
    raw_checks = dec.fields["checks"]
    assert raw_checks[0]["against"] == f"BND-001@{bnd.key}"

    path = root / "items" / "bounds.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("id: BND-001\n", "id: BND-099\n"), encoding="utf-8")
    cli_mod.main(["-c", config, "check"])

    project2 = _loaded(root)
    raw_checks_after = project2.item_by_id("DEC-001").fields["checks"]
    # The raw text on disk DID change (the label refreshed) -- proving that
    # hashing it verbatim, instead of reducing it to the key, would churn.
    assert raw_checks_after[0]["against"] != raw_checks[0]["against"]


# --------------------------------------------------- refresh-guard warning


def test_stale_label_naming_a_different_live_item_warns_and_leaves_file_unchanged(
    tmp_path, capsys
):
    bounds = (
        "defaults: { type: bound }\n"
        "items:\n"
        "  - id: BND-003\n    text: Actual keyed target.\n    limit: \"<= 10 A\"\n"
        "  - id: BND-001\n    text: Different live item.\n    limit: \"<= 1 A\"\n"
    )
    root = _checks_project(tmp_path, bounds, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")

    # Point the check at BND-003 and expand it there first.
    dec_path = root / "items" / "dec.md"
    text = dec_path.read_text(encoding="utf-8")
    dec_path.write_text(text.replace("against: BND-001", "against: BND-003"), encoding="utf-8")
    assert cli_mod.main(["-c", config, "check"]) == 0

    project = _loaded(root)
    target_key = project.item_by_id("BND-003").key
    current = dec_path.read_text(encoding="utf-8")
    stale = current.replace(f"against: BND-003@{target_key}", f"against: BND-001@{target_key}")
    assert stale != current
    dec_path.write_text(stale, encoding="utf-8")
    before = dec_path.read_bytes()

    assert cli_mod.main(["-c", config, "check"]) == 0
    output = capsys.readouterr().out
    assert dec_path.read_bytes() == before
    assert "WARNING" in output
    assert "[DEC-001]" in output
    assert f"'BND-001@{target_key}'" in output
    assert "that key is BND-003" in output
    assert "BND-001 is a different live item" in output
    assert "Refusing to refresh the label" in output


# ------------------------------------------------------- Layer 1 / Layer 3


def test_malformed_key_in_against_reports_layer1(tmp_path):
    bounds = _ONE_BOUND
    checks = (
        "id: DEC-001\ntype: decision\ntitle: Uses the bound.\n"
        "checks:\n  - value: I_total\n    against: BND-001@k2p9w3x1r7\n"
    )
    root = _checks_project(tmp_path, bounds, checks)
    project = _built(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "key 'k2p9w3x1r7' in check against target (labelled BND-001) is malformed" in message
    assert "expected exactly 11 characters" in message
    assert "which no item declares" not in message


def test_unknown_key_in_against_reports_layer3_no_display_id_fallback(tmp_path):
    bounds = _ONE_BOUND
    checks = (
        "id: DEC-001\ntype: decision\ntitle: Uses the bound.\n"
        "checks:\n  - value: I_total\n    against: BND-001@k2p9w3x1r7s\n"
    )
    root = _checks_project(tmp_path, bounds, checks)
    project = _built(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "check against key 'k2p9w3x1r7s' (labelled BND-001), which no item declares" in message
    assert "label may be stale; the key is what resolves" in message


# ----------------------------------------------------- evaluation through a composite


def test_check_passes_through_a_composite_against(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0  # expand
    project = _built(root)
    assert not project.errors
    check = project.item_by_id("DEC-001").checks[0]
    assert check.ok is True
    assert check.against == "BND-001"


def test_check_violation_reported_through_a_composite_against(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS, calc_block="I_total = 50 A")
    config = str(root / "refdes-project.yaml")
    cli_mod.main(["-c", config, "check"])  # expand -- a failing check still exits 1
    project = _built(root)
    assert any("violates BND-001" in d.message for d in project.errors)
    check = project.item_by_id("DEC-001").checks[0]
    assert check.ok is False
    assert check.against == "BND-001"  # current display id, not the raw composite


def test_check_against_display_id_refreshes_after_rename_in_rendering(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config, _target_key = _expand_then_rename_bound(root)
    cli_mod.main(["-c", config, "check"])  # refresh label on disk

    project = _built(root)
    check = project.item_by_id("DEC-001").checks[0]
    assert check.against == "BND-099"


# --------------------------------------------------------------- keys adopt


def test_keys_adopt_expands_against_references_and_reports(tmp_path, capsys):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)

    result = adopt_mod.apply(str(root))
    assert result.ok, result.errors
    assert result.checks_expanded == 1

    project = _loaded(root)
    target_key = project.item_by_id("BND-001").key
    text = (root / "items" / "dec.md").read_text(encoding="utf-8")
    assert f"against: BND-001@{target_key}" in text


def test_keys_adopt_cli_prints_checks_expanded_line(tmp_path, capsys):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")

    assert cli_mod.main(["-c", config, "keys", "adopt"]) == 0
    output = capsys.readouterr().out
    assert "expanded 1 check reference(s) to composite form" in output


# --------------------------------------------- hash-format-2 -> 3 migration
#
# HASH_FORMAT moved to 3 (docs/design/keys.md §5, 2026-09-14): a
# format-2-stamped baseline/seal for an item whose checks: already resolve
# through a composite carries forward silently when the item is unchanged,
# and is left alone, reported uncomparable, when it isn't.


def _write_baseline(root, name, items):
    path = root / ".refdes" / "baselines" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "kind": "revision", "name": name, "stamped_at": "2026-01-01T00:00:00Z",
        "stamped_by": "tester", "refdes_version": "0.0.0-test", "items": items,
    }
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def _format2_entry(project, item_id):
    item = project.item_by_id(item_id)
    return {
        "hash": build_mod.hash_for_format(item, project, 2),
        "type": item.type,
        "title": item.title,
        "hash_format": 2,
    }


def test_format2_baseline_with_checks_against_carries_forward_when_unchanged(tmp_path):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0  # expand against to composite

    project = _built(root)
    _write_baseline(root, "rev-a", {"DEC-001": _format2_entry(project, "DEC-001")})

    baseline = lifecycle.load_baseline(project, "rev-a")
    assert baseline.items["DEC-001"]["hash_format"] == 2

    report = lifecycle.migrate_hash_format(project, baseline, write=True)
    assert report.carried == ["DEC-001"]
    assert report.uncomparable == []
    assert baseline.items["DEC-001"]["hash"] == project.item_by_id("DEC-001").content_hash
    assert baseline.items["DEC-001"]["hash_format"] == build_mod.HASH_FORMAT

    reloaded = lifecycle.load_baseline(project, "rev-a")
    assert reloaded.items["DEC-001"]["hash_format"] == build_mod.HASH_FORMAT
    assert reloaded.items["DEC-001"]["hash"] == project.item_by_id("DEC-001").content_hash


def test_format2_baseline_with_checks_against_edited_item_is_uncomparable_not_upgraded(
    tmp_path,
):
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0

    project = _built(root)
    stale_entry = _format2_entry(project, "DEC-001")

    dec_path = root / "items" / "dec.md"
    text = dec_path.read_text(encoding="utf-8")
    dec_path.write_text(text.replace("I_total = 5 A", "I_total = 6 A"), encoding="utf-8")
    project2 = _built(root)

    _write_baseline(root, "rev-b", {"DEC-001": stale_entry})
    baseline = lifecycle.load_baseline(project2, "rev-b")
    before = dict(baseline.items["DEC-001"])

    report = lifecycle.migrate_hash_format(project2, baseline, write=True)
    assert report.carried == []
    assert report.uncomparable == ["DEC-001"]
    assert baseline.items["DEC-001"] == before  # untouched, not rewritten

    reloaded = lifecycle.load_baseline(project2, "rev-b")
    assert reloaded.items["DEC-001"]["hash_format"] == 2  # file itself untouched too


def test_format2_baseline_stamped_bare_then_expanded_still_carries_to_3(tmp_path):
    """The real historical order of events, not the self-consistent shortcut
    the two tests above take: format 2 existed before `checks:` composites
    did, so every format-2 stamp was necessarily made against *bare*
    `against:` text. Only afterward does a writable load expand it to a
    composite -- a pure syntax upgrade, no content change. Reconstructing
    the format-2 hash from the now-composite source has to still match what
    was stamped from the then-bare source, or an untouched item is wrongly
    reported uncomparable instead of carried forward."""
    root = _checks_project(tmp_path, _ONE_BOUND, _BLOCK_CHECKS)
    config = str(root / "refdes-project.yaml")

    project = _built(root)
    assert "@" not in project.item_by_id("DEC-001").fields["checks"][0]["against"]
    _write_baseline(root, "rev-a", {"DEC-001": _format2_entry(project, "DEC-001")})

    assert cli_mod.main(["-c", config, "check"]) == 0  # expand against: to composite
    project2 = _built(root)
    assert "@" in project2.item_by_id("DEC-001").fields["checks"][0]["against"]

    baseline = lifecycle.load_baseline(project2, "rev-a")
    report = lifecycle.migrate_hash_format(project2, baseline, write=True)
    assert report.carried == ["DEC-001"]
    assert report.uncomparable == []
    assert baseline.items["DEC-001"]["hash"] == project2.item_by_id("DEC-001").content_hash
    assert baseline.items["DEC-001"]["hash_format"] == build_mod.HASH_FORMAT


_SEAL_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n    label: Bound\n"
    "    fields:\n"
    "      text: { type: text, required: true }\n"
    "      limit: { type: limit, required: true, on_change: invalidate }\n"
    "  log:\n"
    "    prefix: LOG\n    label: Log\n    append_only: true\n"
    "    fields:\n"
    "      summary: { type: text, required: true }\n"
    "      checks: { type: checks, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)


def _seal_project(tmp_path, calc_block="I_total = 5 A"):
    write_project_config(tmp_path, _SEAL_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bounds.yaml").write_text(
        "defaults: { type: bound }\n"
        "items:\n  - id: BND-001\n    text: Target.\n    limit: \"<= 10 A\"\n",
        encoding="utf-8",
    )
    (items / "log.md").write_text(
        "---\nid: LOG-001\ntype: log\nsummary: An entry.\n"
        "checks:\n  - value: I_total\n    against: BND-001\n---\n\n"
        f"```calc\n{calc_block}\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def test_format2_seal_with_checks_against_carries_forward_when_unchanged(tmp_path):
    root = _seal_project(tmp_path)
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0  # expand against to composite

    project = _loaded(root)
    build_mod.build(project, seal_write=False, reseal=False)
    format2_hash = build_mod.hash_for_format(project.item_by_id("LOG-001"), project, 2)
    seal.save_seals(
        project, {"LOG-001": {"hash": format2_hash, "hash_format": 2}}
    )

    project2 = _loaded(root)
    build_mod.build(project2, seal_write=True, reseal=False)
    assert "LOG-001" not in project2.seal_violations
    stored = seal.load_seals(project2)["LOG-001"]
    assert stored["hash"] == project2.item_by_id("LOG-001").content_hash
    assert stored["hash_format"] == build_mod.HASH_FORMAT
    assert not any("resealed" in d.message for d in project2.warnings)


def test_format2_seal_with_checks_against_edited_item_is_caught_not_upgraded(tmp_path):
    root = _seal_project(tmp_path)
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0  # expand against to composite

    project = _loaded(root)
    build_mod.build(project, seal_write=False, reseal=False)
    format2_hash = build_mod.hash_for_format(project.item_by_id("LOG-001"), project, 2)
    seal.save_seals(
        project, {"LOG-001": {"hash": format2_hash, "hash_format": 2}}
    )

    log_path = root / "items" / "log.md"
    text = log_path.read_text(encoding="utf-8")
    log_path.write_text(text.replace("summary: An entry.", "summary: Edited."), encoding="utf-8")

    project2 = _loaded(root)
    build_mod.build(project2, seal_write=True, reseal=False)
    assert "LOG-001" in project2.seal_violations
    stored = seal.load_seals(project2)["LOG-001"]
    assert stored["hash"] == format2_hash  # left exactly as sealed, not laundered
    assert stored["hash_format"] == 2


def test_format2_seal_key_keyed_stamped_bare_then_expanded_still_verifies(tmp_path):
    """Same real-order-of-events scenario as the baseline test above, for a
    key-keyed seal entry: sealed while `against:` was still bare (the only
    way a format-2 seal could ever have been sealed), then a writable load
    expands it to a composite with no content change. Verification must
    still pass."""
    root = _seal_project(tmp_path)
    config = str(root / "refdes-project.yaml")

    project = _loaded(root)
    build_mod.build(project, seal_write=False, reseal=False)
    assert "@" not in project.item_by_id("LOG-001").fields["checks"][0]["against"]
    format2_hash = build_mod.hash_for_format(project.item_by_id("LOG-001"), project, 2)
    seal.save_seals(project, {"LOG-001": {"hash": format2_hash, "hash_format": 2}})

    assert cli_mod.main(["-c", config, "check"]) == 0  # expand against: to composite

    project2 = _loaded(root)
    build_mod.build(project2, seal_write=True, reseal=False)
    assert "LOG-001" not in project2.seal_violations
    stored = seal.load_seals(project2)["LOG-001"]
    assert stored["hash"] == project2.item_by_id("LOG-001").content_hash
    assert stored["hash_format"] == build_mod.HASH_FORMAT


def test_format2_seal_legacy_scalar_stamped_bare_then_expanded_still_verifies(tmp_path):
    """Same scenario again, for a legacy scalar seal (no format marker at
    all -- _matches_sealed_hash must find the match by trying formats
    newest-to-oldest, same as the key-keyed case above)."""
    root = _seal_project(tmp_path)
    config = str(root / "refdes-project.yaml")

    project = _loaded(root)
    build_mod.build(project, seal_write=False, reseal=False)
    format2_hash = build_mod.hash_for_format(project.item_by_id("LOG-001"), project, 2)
    seal.save_seals(project, {"LOG-001": format2_hash})

    assert cli_mod.main(["-c", config, "check"]) == 0  # expand against: to composite

    project2 = _loaded(root)
    build_mod.build(project2, seal_write=True, reseal=False)
    assert "LOG-001" not in project2.seal_violations


# ------------------------------------------------------------ sabotage note
#
# The carry-forward guard (lifecycle.migrate_hash_format / seal._matches_
# sealed_hash / keys.plan_surrogate_storage, all through keys.hash_in_format)
# was sabotage-tested by hand while writing the two tests above: forcing the
# comparison to always report a match (as if the guard were deleted) turned
# test_format2_baseline_with_checks_against_edited_item_is_uncomparable_not_upgraded
# and test_format2_seal_with_checks_against_edited_item_is_caught_not_upgraded
# from pass to fail -- the edited entry got silently upgraded and the seal
# violation vanished -- which is exactly the "launder an edit" failure this
# guard exists to prevent. Restored before landing; not left as a permanent
# fault-injection test since there's no stable seam to sabotage without
# duplicating the guard's own logic here.


# ------------------------------------------- `checks:` inherited from defaults:
#
# A `checks:` written once in a file's `defaults:` block has a single physical
# spelling shared by every item that inherits it -- exactly the shape
# `links.plan_expansion()` already handles for an inherited link. Its
# `against:` is expanded and refreshed there, once, and stays rename-safe for
# every inheriting item (docs/design/keys.md §3).
#
# The list-file items below carry no calc block, so `run_checks` reports its
# own "no calc value named" error on them; these assertions are about the
# source text and the parsed target, so the exit code is not asserted.

_DEFAULTS_LIST = (
    "defaults:\n"
    "  type: decision\n"
    "  checks:\n"
    "    - value: I_total\n"
    "      against: BND-001\n"
    "items:\n"
    "  - id: DEC-001\n    title: First.\n"
    "  - id: DEC-002\n    title: Second.\n"
)


def _defaults_project(tmp_path, decs_yaml=_DEFAULTS_LIST, bounds=None):
    write_project_config(tmp_path, CHECKS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bounds.yaml").write_text(bounds or _ONE_BOUND, encoding="utf-8")
    (items / "decs.yaml").write_text(decs_yaml, encoding="utf-8")
    return tmp_path


def test_defaults_inherited_checks_expand_once_in_the_defaults_block(tmp_path):
    root = _defaults_project(tmp_path)
    config = str(root / "refdes-project.yaml")
    cli_mod.main(["-c", config, "check"])

    project = _loaded(root)
    key = project.item_by_id("BND-001").key
    assert key

    text = (root / "items" / "decs.yaml").read_text(encoding="utf-8")
    assert text.count(f"against: BND-001@{key}") == 1  # once, in defaults:
    assert "against: BND-001\n" not in text

    built = _built(root)
    for dec_id in ("DEC-001", "DEC-002"):
        item = built.item_by_id(dec_id)
        assert item.fields["checks"][0]["against"] == f"BND-001@{key}"
        assert item.checks[0].against == "BND-001"  # resolves by key
    assert not [d for d in built.errors if "does not exist" in d.message]


def test_defaults_inherited_checks_rename_refreshes_once_and_hashes_hold(tmp_path):
    root = _defaults_project(tmp_path)
    config = str(root / "refdes-project.yaml")
    cli_mod.main(["-c", config, "check"])  # expand

    before = _built(root)
    key = before.item_by_id("BND-001").key
    hashes = {i: before.item_by_id(i).content_hash for i in ("DEC-001", "DEC-002")}
    assert all(hashes.values())

    path = root / "items" / "bounds.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("id: BND-001\n", "id: BND-099\n"), encoding="utf-8")
    cli_mod.main(["-c", config, "check"])  # refresh the label

    refreshed = (root / "items" / "decs.yaml").read_text(encoding="utf-8")
    assert refreshed.count(f"against: BND-099@{key}") == 1
    assert "BND-001@" not in refreshed

    after = _built(root)
    for dec_id, digest in hashes.items():
        assert after.item_by_id(dec_id).content_hash == digest


def test_no_write_leaves_defaults_inherited_checks_bare(tmp_path):
    root = _defaults_project(tmp_path)
    config = str(root / "refdes-project.yaml")
    before = (root / "items" / "decs.yaml").read_bytes()

    cli_mod.main(["-c", config, "--no-write", "check"])

    assert (root / "items" / "decs.yaml").read_bytes() == before


def test_item_overriding_checks_is_rewritten_in_its_own_span(tmp_path):
    """The override keeps its own span: the defaults rewrite must not touch
    it, and its own rewrite must not touch the defaults block."""
    decs = (
        "defaults:\n"
        "  type: decision\n"
        "  checks:\n"
        "    - value: I_total\n      against: BND-001\n"
        "items:\n"
        "  - id: DEC-001\n    title: Inherits.\n"
        "  - id: DEC-002\n    title: Overrides.\n"
        "    checks:\n      - value: I_total\n        against: BND-002\n"
    )
    bounds = (
        "defaults: { type: bound }\n"
        "items:\n"
        "  - id: BND-001\n    text: First.\n    limit: \"<= 10 A\"\n"
        "  - id: BND-002\n    text: Second.\n    limit: \"<= 5 A\"\n"
    )
    root = _defaults_project(tmp_path, decs, bounds=bounds)
    config = str(root / "refdes-project.yaml")
    cli_mod.main(["-c", config, "check"])

    project = _loaded(root)
    key1 = project.item_by_id("BND-001").key
    key2 = project.item_by_id("BND-002").key
    text = (root / "items" / "decs.yaml").read_text(encoding="utf-8")
    assert f"against: BND-001@{key1}" in text
    assert f"against: BND-002@{key2}" in text
    assert "against: BND-001\n" not in text and "against: BND-002\n" not in text

    assert project.item_by_id("DEC-001").fields["checks"][0]["against"] == f"BND-001@{key1}"
    assert project.item_by_id("DEC-002").fields["checks"][0]["against"] == f"BND-002@{key2}"


def test_sabotage_disabling_the_defaults_group_leaves_the_block_bare(tmp_path, monkeypatch):
    """Fault injection for the defaults-group rewrite: with an item never
    reported as inheriting its `checks:`, the shared spelling falls back to
    each item's own span -- which holds no `against:` line at all -- and
    nothing is written. That is exactly the pre-fix behaviour, so the tests
    above are load-bearing on this branch and not incidental."""
    from refdes import links as links_mod

    monkeypatch.setattr(links_mod, "_checks_inherited", lambda item: False)
    root = _defaults_project(tmp_path)
    config = str(root / "refdes-project.yaml")
    cli_mod.main(["-c", config, "check"])  # mints keys; must not expand

    path = root / "items" / "decs.yaml"
    assert "against: BND-001\n" in path.read_text(encoding="utf-8")
    before = path.read_bytes()

    cli_mod.main(["-c", config, "check"])

    assert path.read_bytes() == before


def test_markdown_defaults_block_checks_expand_and_refresh(tmp_path):
    """Markdown's leading `defaults:` block supports `checks:` the same way
    (parse_markdown_file merges it under every item, inherited_fields and
    defaults_line included), so it gets the same treatment."""
    root = _checks_project(
        tmp_path,
        _ONE_BOUND,
        "defaults:\n"
        "  type: decision\n"
        "  checks:\n"
        "    - value: I_total\n      against: BND-001\n"
        "---\n\n"
        "---\nid: DEC-001\ntitle: First.\n",
        decision_name="decs.md",
    )
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0

    project = _loaded(root)
    key = project.item_by_id("BND-001").key
    text = (root / "items" / "decs.md").read_text(encoding="utf-8")
    assert text.count(f"against: BND-001@{key}") == 1

    path = root / "items" / "bounds.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("id: BND-001\n", "id: BND-099\n"),
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", config, "check"]) == 0
    refreshed = (root / "items" / "decs.md").read_text(encoding="utf-8")
    assert f"against: BND-099@{key}" in refreshed and "BND-001@" not in refreshed
