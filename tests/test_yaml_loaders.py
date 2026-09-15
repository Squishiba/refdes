"""YAML diagnostics and real loaders retain their pre-libyaml failure behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import write_project_config
from helpers import COVERAGE_SCHEMA

from refdes import boards, citations, ids, keys, lifecycle, parse, seal, standards
from refdes.parse import _PurePythonLineLoader, _yaml_error_report
from refdes.schema import SCHEMA_NAME, load_project

MALFORMED = [
    ("tab indentation", "items:\n  - id: REQ-001\n\ttext: tabbed\n"),
    ("unclosed flow list", "items:\n  - id: REQ-001\n    text: [ unterminated\n"),
    (
        "unterminated double-quoted scalar",
        'items:\n  - id: REQ-001\n    text: "unterminated\n',
    ),
    ("bare > broken", "items:\n  - id: REQ-001\n    text: > broken\n"),
    ("bare >= 9 V", "items:\n  - id: REQ-001\n    limit: >= 9 V\n"),
    ("nested mapping", "items:\n  - id: REQ-001\n    text: a: b: c\n"),
    (
        "bad dedent",
        "items:\n  - id: REQ-001\n    text: fine\n   type: requirement\n",
    ),
]


def _pure_diagnostic(text: str) -> tuple[str, int]:
    with pytest.raises(yaml.YAMLError) as error:
        yaml.load(text, Loader=_PurePythonLineLoader)
    message, line = _yaml_error_report(error.value, text.split("\n"), offset=0)
    return f"invalid YAML: {message}", line


@pytest.mark.parametrize(("label", "text"), MALFORMED, ids=lambda case: case[0])
def test_real_list_loader_matches_pure_python_diagnostic(tmp_path, label, text):
    """The user-facing diagnostic, including PyYAML's caret excerpt, is exact."""
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(text, encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)

    expected = _pure_diagnostic(text)
    actual = [(diagnostic.message, diagnostic.line) for diagnostic in project.errors]
    assert "^" in expected[0], f"{label}: pure-Python diagnostic lost its caret excerpt"
    assert actual == [expected], f"{label}: real loader diagnostic differs from SafeLoader"


def _write_malformed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("a: [unterminated\n", encoding="utf-8")


def test_real_loaders_keep_main_malformed_yaml_behavior(tmp_path):
    """Clean-main probe: every loader raised YAMLError, except is_adopted=False."""
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))

    _write_malformed(Path(boards.manifest_path(project)))
    with pytest.raises(yaml.YAMLError):
        boards.load_manifest(project)

    _write_malformed(Path(seal.seal_path(project)))
    with pytest.raises(yaml.YAMLError):
        seal.load_seals(project)

    _write_malformed(Path(ids.ledger_path(project)))
    with pytest.raises(yaml.YAMLError):
        ids.load_ledger(project)

    _write_malformed(Path(citations.lockfile_path(project)))
    with pytest.raises(yaml.YAMLError):
        citations.load_lockfile(project)

    _write_malformed(Path(lifecycle.baseline_path(project, "probe")))
    with pytest.raises(yaml.YAMLError):
        lifecycle.load_baseline(project, "probe")

    _write_malformed(Path(keys.adoption_marker_path(project)))
    assert keys.is_adopted(project) is False

    settings = tmp_path / "bad-settings.yaml"
    _write_malformed(settings)
    with pytest.raises(yaml.YAMLError):
        load_project(config_path=str(settings))

    _write_malformed(tmp_path / SCHEMA_NAME)
    with pytest.raises(yaml.YAMLError):
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))

    standard = tmp_path / "bad-standard.yaml"
    _write_malformed(standard)
    with pytest.raises(yaml.YAMLError):
        standards._read_yaml(str(standard))
