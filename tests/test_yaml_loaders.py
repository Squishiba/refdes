"""YAML diagnostics and real loaders retain their pre-libyaml failure behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import write_project_config
from helpers import COVERAGE_SCHEMA

from refdes import boards, citations, ids, keys, lifecycle, parse, seal, standards
from refdes.parse import _PurePythonLineLoader, _yaml_error_report
from refdes.schema import SCHEMA_NAME, SchemaError, load_project

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
    """Clean-main probe: the item/config loaders still raise YAMLError; the
    .refdes store loaders wrap it in their own error class naming the file.

    The store half of this pin changed with review #209's class fix (the
    history object store's raw reads were the trigger): an unparseable store
    file is now a SchemaError (manifest, ledger, baseline) or the seal
    module's own corrupt-file ValueError, each naming the path. A raw
    YAMLError -- let alone a UnicodeDecodeError, which is not even a
    YAMLError -- escaped as a traceback out of every command that read the
    file. The lockfile's LockfileError was the earlier instance of the same
    fix (see `tests/test_lockfile_corruption.py`); the adoption marker stays
    the deliberate swallow: unreadable means not adopted."""
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))

    _write_malformed(Path(boards.manifest_path(project)))
    with pytest.raises(SchemaError, match="membership manifest file does not parse"):
        boards.load_manifest(project)

    _write_malformed(Path(seal.seal_path(project)))
    with pytest.raises(ValueError, match="seal file does not parse"):
        seal.load_seals(project)

    _write_malformed(Path(ids.ledger_path(project)))
    with pytest.raises(SchemaError, match="id ledger file does not parse"):
        ids.load_ledger(project)

    _write_malformed(Path(citations.lockfile_path(project)))
    with pytest.raises(citations.LockfileError) as lockfile_error:
        citations.load_lockfile(project)
    assert citations.LOCKFILE in str(lockfile_error.value)
    assert "is not valid YAML" in str(lockfile_error.value)

    _write_malformed(Path(lifecycle.baseline_path(project, "probe")))
    with pytest.raises(SchemaError, match="baseline file does not parse"):
        lifecycle.load_baseline(project, "probe")

    _write_malformed(Path(keys.adoption_marker_path(project)))
    assert keys.is_adopted(project) is False


def test_store_files_name_a_non_utf8_file_instead_of_a_traceback(tmp_path):
    """Review #209's class beyond history.py: one stray byte in a store file
    escaped as a raw UnicodeDecodeError -- not a YAMLError (so the lockfile's
    existing wrap missed it too) and not an OSError -- and crashed every
    command that read the file with a traceback naming nothing. Each store
    loader now raises its own error class with the path and the kind of file;
    the adoption marker keeps its deliberate swallow (is_adopted False),
    which is also why adopt's own marker read has its own refusal."""
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))

    def _corrupt(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff")

    _corrupt(Path(boards.manifest_path(project)))
    with pytest.raises(SchemaError, match="membership manifest file is not valid UTF-8") as exc_info:
        boards.load_manifest(project)
    assert "boards.yaml" in str(exc_info.value)

    _corrupt(Path(seal.seal_path(project)))
    with pytest.raises(ValueError, match="seal file is not valid UTF-8") as exc_info:
        seal.load_seals(project)
    assert "log-seal.yaml" in str(exc_info.value)

    _corrupt(Path(ids.ledger_path(project)))
    with pytest.raises(SchemaError, match="id ledger file is not valid UTF-8") as exc_info:
        ids.load_ledger(project)
    assert "ids.yaml" in str(exc_info.value)

    _corrupt(Path(citations.lockfile_path(project)))
    with pytest.raises(citations.LockfileError, match="is not valid UTF-8") as exc_info:
        citations.load_lockfile(project)
    assert citations.LOCKFILE in str(exc_info.value)

    _corrupt(Path(lifecycle.baseline_path(project, "probe")))
    with pytest.raises(SchemaError, match="baseline file is not valid UTF-8") as exc_info:
        lifecycle.load_baseline(project, "probe")
    assert "probe.yaml" in str(exc_info.value)

    _corrupt(Path(keys.adoption_marker_path(project)))
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
