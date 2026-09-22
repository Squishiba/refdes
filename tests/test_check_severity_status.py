"""Status-dependent `check_severity` (docs/design/candidate-parts.md §4).

The severity engine: schema.py load-time validation of the mapping form,
build._severity_for per-item resolution, and the per-item release gate
(lifecycle._rule_info_check_failures). The scalar form must stay
byte-identical (§4.6); the mapping form selects by the item's `status`
(§4.2), must be exhaustive or declare `default:` (§4.4), and moves the
`info_check_failures` gate per item (§4.5).
"""

from __future__ import annotations

import pathlib

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import lifecycle, render
from refdes.model import DIAGNOSTIC_LEVELS
from refdes.schema import SchemaError, load_project

# ---------------------------------------------------------------- fixtures

MAPPING_SCHEMA = """\
site: {title: "Severity Mapping Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
types:
  constraint:
    prefix: CON
    label: Constraint
    fields:
      title: { type: text, required: true, on_change: invalidate }
      limit: { type: limit, required: true, on_change: invalidate }
    body: { on_change: invalidate }
  part:
    prefix: PRT
    label: Part
    check_severity:
      candidate: info      # a candidate failing a criterion is the finding
      selected: error      # the part you actually chose must pass
      rejected: info       # history, not a defect
    fields:
      title: { type: text, required: true, on_change: invalidate }
      status:
        type: enum
        choices: [candidate, selected, rejected]
        default: candidate
        on_change: invalidate
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    label: Decision
    fields:
      title: { type: text, required: true, on_change: invalidate }
    body: { on_change: invalidate }
"""


def _load(tmp_path, schema: str):
    write_project_config(tmp_path, schema)
    return load_project(config_path=str(tmp_path / "refdes-project.yaml"))


def _err(tmp_path, schema: str) -> str:
    with pytest.raises(SchemaError) as exc:
        _load(tmp_path, schema)
    return str(exc.value)


def _mapping_project(tmp_path, *, status="candidate", checks_extra="", sub=""):
    """One `part` item with a failing check against CON-IO-004 (0.697 A vs
    <= 600 mA), in the given status, built at tmp_path (or its `sub` /
    subdirectory, so one test can build the same project twice)."""
    root = tmp_path / sub if sub else tmp_path
    root.mkdir(parents=True, exist_ok=True)
    write_project_config(root, MAPPING_SCHEMA)
    items = root / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults: { type: constraint }\n"
        "items:\n"
        "  - id: CON-IO-004\n"
        "    title: Input current budget\n"
        '    limit: "<= 600 mA"\n',
        encoding="utf-8",
    )
    (items / "prt.md").write_text(
        "---\n"
        "id: PRT-IO-001\n"
        "type: part\n"
        "title: Part under evaluation\n"
        f"status: {status}\n"
        "checks:\n"
        "  - value: CLIM\n"
        "    against: CON-IO-004\n"
        f"{checks_extra}"
        "---\n\n"
        "```calc\nCLIM = 0.697 A | A\n```\n",
        encoding="utf-8",
    )
    return _build_at(root)


# ------------------------------------------------- §4.6 scalar unchanged


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("presets", [[], ["design-debate"]])
def test_scalar_severity_unchanged(tmp_path, version, presets):
    """Resolved-schema oracle over every bundled standard: every resolved
    check_severity is the same scalar it was before the mapping existed (§4.6)
    -- with one deliberate exception. hardware@3's `component` ships the status
    mapping `{candidate: info, selected: error, rejected: info, obsolete: info}`
    (candidate-parts.md §5.4), pinned exactly here; everything else must stay a
    scalar. Any other type resolving to a mapping is an accidental one this
    test exists to catch."""
    preset_yaml = "".join(f"    - {p}\n" for p in presets)
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        f"standard:\n  base: hardware\n  version: {version}\n"
        + (f"  presets:\n{preset_yaml}" if presets else ""),
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    for name, spec in project.types.items():
        if version == 3 and name == "component":
            assert spec.check_severity == {
                "candidate": "info",
                "selected": "error",
                "rejected": "info",
                "obsolete": "info",
            }, "hardware@3 component is the one known mapping (candidate-parts.md §5.4)"
            assert set(spec.check_severity.values()) <= set(DIAGNOSTIC_LEVELS)
            continue
        assert not isinstance(spec.check_severity, dict), (
            f"hardware@{version} type {name} resolved to a mapping"
        )
        assert spec.check_severity in DIAGNOSTIC_LEVELS
    if presets:
        # The one scalar that was never the default: design-debate's option.
        assert project.types["option"].check_severity == "info"


# ------------------------------------------------- §4.2 mapping resolution


def test_mapping_selects_by_status(tmp_path):
    """Same failing check: info on a candidate, error on a selected part.
    The build verdict (errors vs not) is what the exit code keys off."""
    project = _mapping_project(tmp_path, status="candidate")
    check = project.item_by_id("PRT-IO-001").checks[0]
    assert check.ok is False  # the verdict never moves (docs/checks.md)
    assert not project.errors
    assert any("CLIM violates CON-IO-004" in d.message for d in project.infos)

    project = _mapping_project(tmp_path, status="selected", sub="selected")
    assert project.item_by_id("PRT-IO-001").checks[0].ok is False
    assert any("CLIM violates CON-IO-004" in d.message for d in project.errors)
    assert not project.infos


def test_mapping_default_covers_unlisted_status(tmp_path):
    """`default:` is the fallback for any status not listed (§4.3), and its
    value is validated like any other."""
    schema = MAPPING_SCHEMA.replace(
        "    check_severity:\n"
        "      candidate: info      # a candidate failing a criterion is the finding\n"
        "      selected: error      # the part you actually chose must pass\n"
        "      rejected: info       # history, not a defect\n",
        "    check_severity:\n      selected: error\n      default: warning\n",
    )
    write_project_config(tmp_path, schema)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    assert project.types["part"].check_severity == {
        "selected": "error",
        "default": "warning",
    }


# ------------------------------------------------- §4.3 load-time errors


def test_mapping_requires_status_field(tmp_path):
    schema = MAPPING_SCHEMA.replace(
        "  decision:\n    prefix: DEC\n    label: Decision\n",
        "  decision:\n    prefix: DEC\n    label: Decision\n"
        "    check_severity:\n      candidate: info\n",
    )
    message = _err(tmp_path, schema)
    assert (
        "types.decision.check_severity is a mapping but type 'decision' "
        "declares no 'status' field. Write check_severity: error, or declare "
        "status." in message
    )


def test_mapping_rejects_unknown_key(tmp_path):
    schema = MAPPING_SCHEMA.replace("      rejected: info", "      choosen: info")
    message = _err(tmp_path, schema)
    assert (
        "types.part.check_severity key 'choosen' is not a declared status. "
        "Declared choices: candidate, selected, rejected." in message
    )


def test_mapping_rejects_unknown_level(tmp_path):
    schema = MAPPING_SCHEMA.replace("      candidate: info", "      candidate: note")
    message = _err(tmp_path, schema)
    assert (
        "types.part.check_severity[candidate] must be one of "
        "['error', 'warning', 'info'], got 'note'" in message
    )


def test_mapping_requires_exhaustive_or_default(tmp_path):
    """A status the mapping does not cover, with no `default:`, is a load
    error naming the missing status -- never a silent `error` (§4.4, §11.8)."""
    schema = MAPPING_SCHEMA.replace("      rejected: info       # history, not a defect\n", "")
    message = _err(tmp_path, schema)
    assert (
        "types.part.check_severity does not cover status 'rejected'. "
        "Add it, or add default: <level>." in message
    )


def test_unevaluable_checks_stay_errors(tmp_path):
    """Only the ran-and-failed diagnostic moves (§4.2): a typo'd value name
    on a candidate is an error whatever the mapping says."""
    project = _mapping_project(
        tmp_path,
        status="candidate",
        checks_extra="  - value: CLIMM\n    against: CON-IO-004\n",
    )
    assert any("no calc block defines" in d.message for d in project.errors)


def test_badge_unaffected_by_severity(tmp_path):
    """The item page shows the fail pill at every severity -- severity
    governs diagnostics, never the verdict (§4.2)."""
    project = _mapping_project(tmp_path, status="candidate")
    assert not project.errors  # the failing check is an info here
    out = render.render_site(project)
    html = pathlib.Path(out, "prt-io-001.html").read_text(encoding="utf-8")
    assert 'class="pill pill-fail">fail</span>' in html


def test_extends_replaces_whole_definition(tmp_path):
    """extends:/overlay replacement is wholesale for check_severity, never a
    merge (§4.3): scalar child over mapping parent, mapping child over
    scalar parent."""
    schema = (
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  base_map:\n"
        "    prefix: BAM\n    label: Base Map\n    plural: Base Maps\n"
        "    check_severity:\n      candidate: info\n      selected: error\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n"
        "      status: { type: enum, choices: [candidate, selected], default: candidate }\n"
        "  child_scalar:\n"
        "    extends: base_map\n"
        "    prefix: CHS\n    label: Child Scalar\n    plural: Child Scalars\n"
        "    check_severity: error\n"
        "    fields:\n"
        "      extra: { type: text }\n"
        "  base_scalar:\n"
        "    prefix: BAS\n    label: Base Scalar\n    plural: Base Scalars\n"
        "    check_severity: error\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n"
        "      status: { type: enum, choices: [candidate, selected], default: candidate }\n"
        "  child_map:\n"
        "    extends: base_scalar\n"
        "    prefix: CHM\n    label: Child Map\n    plural: Child Maps\n"
        "    check_severity:\n      candidate: warning\n      selected: error\n"
        "    fields:\n"
        "      extra: { type: text }\n"
    )
    project = _load(tmp_path, schema)
    assert project.types["child_scalar"].check_severity == "error"
    assert project.types["child_map"].check_severity == {
        "candidate": "warning",
        "selected": "error",
    }


# ------------------------------------------------- §4.5 the release gate


def test_gate_follows_status_change(tmp_path):
    """A status change alone moves an item between the info_check_failures
    bucket and a build-blocking error (§4.5)."""
    project = _mapping_project(tmp_path, status="candidate")
    project.release_gate["info_check_failures"]["release"] = True
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["info_check_failures"].offenders == ["PRT-IO-001"]

    project = _mapping_project(tmp_path, status="selected", sub="selected")
    project.release_gate["info_check_failures"]["release"] = True
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    # No longer an info failure -- it is a build error now, and the gate
    # bucket is empty because the build itself already blocks.
    assert results["info_check_failures"].offenders == []
    assert project.errors
