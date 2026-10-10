"""Hardware@3 phase 4a: a verdict is an ordinary history-backed log entry."""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import cli, parse, revise
from refdes.schema import SchemaError, load_project


def _project(root, version=3):
    write_project_config(
        root,
        f"site: {{ title: Decision merge }}\nstandard: {{ base: hardware, version: {version} }}\n",
    )
    (root / "items").mkdir(exist_ok=True)
    return root / "refdes-project.yaml"


def test_v3_merged_log_keeps_verdict_and_narrative_fields(tmp_path):
    _project(tmp_path)
    project = load_project(start=str(tmp_path))
    assert "decision" not in project.types
    log = project.types["log"]
    assert log.append_only and log.sealing == "history"
    assert log.legacy_prefixes == ["DEC"]
    assert log.satisfying_statuses == ["accepted"]
    assert log.check_severity == "error"
    assert log.fields["date"].required is False
    assert log.fields["summary"].required is True
    assert log.fields["status"].default is None
    assert {"status", "rationale", "options", "checks", "citations", "author"} <= set(
        log.fields
    )
    assert log.links["follows"] == ["log"]
    assert log.links["satisfies"] == ["requirement", "bound"]
    assert log.links["supersedes"] == ["log"]
    assert "records" not in log.links
    assert "recorded_by" not in project.link_types


def test_existing_date_less_decision_upgrades_without_inventing_status(tmp_path):
    config = _project(tmp_path, version=2)
    item_file = tmp_path / "items" / "decision.yaml"
    item_file.write_text(
        "defaults: { type: decision, prefix: DEC }\n"
        "items:\n"
        "  - id: DEC-001\n"
        "    title: Regulator choice\n",
        encoding="utf-8",
    )

    steps = revise.apply_standard_upgrade(str(tmp_path), 3)
    assert len(steps) == 1 and steps[0].result.ok, steps
    text = item_file.read_text(encoding="utf-8")
    assert "defaults: { type: log, prefix: DEC }" in text
    assert "id: DEC-001" in text
    assert "summary: Regulator choice" in text
    assert "date:" not in text and "status:" not in text

    project = load_project(config_path=str(config))
    parse.load_items(project)
    assert project.item_by_id("DEC-001").type == "log"
    assert cli.main(["-c", str(config), "--no-write", "check"]) == 0


def test_old_records_edges_upgrade_to_follows_links(tmp_path):
    """A v2 `records:` edge becomes a `follows:` link, not an `item:` citation.

    The citation spelling is bare-id data nothing maintains: it breaks on
    the target's first rename and refuses the composite `ID@key` form
    (PR #176 review). `follows:` is the one log-to-log link the merged
    schema declares, and structured links are what the surrogate-key
    machinery keeps current -- asserted below by letting a writable load
    freeze the migrated edge like any authored one.
    """
    config = _project(tmp_path, version=2)
    path = tmp_path / "items" / "thread.yaml"
    path.write_text(
        "items:\n"
        "  - id: DEC-001\n    type: decision\n    title: Regulator choice\n"
        "  - id: LOG-001\n    type: log\n    date: 2026-10-01\n"
        "    summary: Recorded choice\n    records: [DEC-001]\n",
        encoding="utf-8",
    )
    steps = revise.apply_standard_upgrade(str(tmp_path), 3)
    assert len(steps) == 1 and steps[0].result.ok, steps
    text = path.read_text(encoding="utf-8")
    assert "recorded_by:" not in text and "records:" not in text
    assert "follows: [DEC-001]" in text
    assert "- item:" not in text
    assert cli.main(["-c", str(config), "--no-write", "check"]) == 0

    # The migrated edge is under the key machinery: the next writable load
    # freezes it to `DEC-001@key` and captures the predecessor's snapshot,
    # exactly as it does for an authored `follows:`.
    assert cli.main(["-c", str(config), "check"]) == 0
    text = path.read_text(encoding="utf-8")
    assert "follows: [DEC-001@" in text
    assert len(list((tmp_path / ".refdes" / "history" / "events").glob("*.yaml"))) == 1


def test_migrated_decision_keeps_its_dec_id_without_a_prefix_warning(tmp_path, capsys):
    """ids.validate_prefixes' legacy-prefix branch, behaviourally.

    A v2 decision with no explicit `prefix:` migrates to `type: log` with
    its DEC id intact; `legacy_prefixes: [DEC]` on the merged log type must
    keep `check` warning-free for it. Deleting the branch in ids.py (the
    only behavioural consumer of `legacy_prefixes`) otherwise ships green
    (PR #176 review). The control row proves the warning still fires for a
    prefix the type does not claim.
    """
    config = _project(tmp_path, version=2)
    (tmp_path / "items" / "decision.yaml").write_text(
        "items:\n"
        "  - id: DEC-001\n    type: decision\n    title: Regulator choice\n"
        "  - id: LOG-001\n    type: log\n    date: 2026-10-01\n"
        "    summary: A log entry\n"
        "  - id: FOO-001\n    type: log\n    date: 2026-10-02\n"
        "    summary: Wrongly prefixed\n",
        encoding="utf-8",
    )
    steps = revise.apply_standard_upgrade(str(tmp_path), 3)
    assert len(steps) == 1 and steps[0].result.ok, steps
    assert "id: DEC-001" in (tmp_path / "items" / "decision.yaml").read_text(
        encoding="utf-8"
    )

    capsys.readouterr()  # clear the upgrade's own output
    assert cli.main(["-c", str(config), "--no-write", "check"]) == 0
    out = capsys.readouterr().out
    # Exactly one prefix warning in the whole report, and it is the control
    # row's -- DEC-001's legacy prefix is honoured, not warned.
    assert out.count("does not match this item's prefix") == 1
    assert "FOO-001" in out


def test_item_citation_target_must_exist(tmp_path):
    config = _project(tmp_path)
    (tmp_path / "items" / "log.yaml").write_text(
        "items:\n  - id: LOG-001\n    type: log\n    summary: A note\n"
        "    citations:\n      - item: DEC-404\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(config))
    parse.load_items(project)
    from refdes import build
    build.build(project)
    assert any("item: 'DEC-404' does not exist" in d.message for d in project.errors)


def _cite_target(tmp_path, spelling):
    """One project whose `citations: - item:` names LOG-001 as `spelling`."""
    config = _project(tmp_path)
    (tmp_path / "items" / "log.yaml").write_text(
        "items:\n  - id: LOG-001\n    type: log\n    summary: The target\n"
        "  - id: LOG-002\n    type: log\n    summary: Cites it\n"
        f"    citations:\n      - item: {spelling}\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(config))
    parse.load_items(project)
    from refdes import keys
    keys.mint_missing(project)
    key = project.item_by_id("LOG-001").key
    return project, key


@pytest.mark.parametrize("form", ["composite", "bare-key"])
def test_item_citation_resolves_the_maintained_key_spellings(tmp_path, form):
    """`ID@key` and a bare key resolve like every other target spelling.

    PR #176 review: `validate_items` looked citations up with `item_by_id`,
    which is display-id only, so a citation written in the tool's own
    maintained composite form reported `item: 'LOG-001@1zn5skrv6k3' does not
    exist` for an item that was demonstrably there. Resolution now goes
    through `resolve_link_target`, the same helper links, `checks: against:`
    and cross-item calc references use.
    """
    project, key = _cite_target(tmp_path, "PLACEHOLDER")
    spelling = f"LOG-001@{key}" if form == "composite" else key
    project.item_by_id("LOG-002").fields["citations"] = [{"item": spelling}]
    from refdes import build
    build.build(project)
    assert not project.errors, [d.message for d in project.errors]


def test_item_citation_with_a_dead_key_reports_the_real_cause(tmp_path):
    """The composite failure mode names the key, not a missing item.

    Same review finding, other half: a composite whose key resolves to
    nothing used to be indistinguishable from an unknown id. It now takes
    the shared `_unknown_key_message` text, which says the key is what
    resolves, that the label may be stale, and that the display half is not
    used as a fallback -- with the remedy clause the bare-id message has
    never had, because a bare id has no key to lose.
    """
    project, _key = _cite_target(tmp_path, "PLACEHOLDER")
    project.item_by_id("LOG-002").fields["citations"] = [
        {"item": "LOG-001@aaaaaaaaaaa"}
    ]
    from refdes import build
    build.build(project)
    messages = [d.message for d in project.errors]
    assert len(messages) == 1, messages
    assert "does not exist" not in messages[0]
    assert "key 'aaaaaaaaaaa' (labelled LOG-001), which no item declares" in messages[0]
    assert "refdes keys restore" in messages[0]


def test_bundled_follows_freezes_and_captures_predecessor(tmp_path):
    config = _project(tmp_path)
    item_file = tmp_path / "items" / "log.yaml"
    item_file.write_text(
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Initial reasoning\n"
        "  - id: LOG-002\n    summary: Accepted result\n"
        "    status: accepted\n    follows: [LOG-001]\n",
        encoding="utf-8",
    )
    assert cli.main(["-c", str(config), "index", "--compact"]) == 0
    text = item_file.read_text(encoding="utf-8")
    assert "follows: [LOG-001@" in text
    assert len(list((tmp_path / ".refdes" / "history" / "events").glob("*.yaml"))) == 1


def test_v3_design_debate_preset_is_retired(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: Decision merge }\n"
        "standard: { base: hardware, version: 3, presets: [design-debate] }\n",
    )
    try:
        load_project(start=str(tmp_path))
    except SchemaError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("hardware@3 still exposes the retired preset")
