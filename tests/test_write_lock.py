"""Process-level coverage for Tier-A project writes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import write_project_config

from refdes import cli

CONFIG = """\
site: {title: Lock test}
id: {width: 3}
types:
  requirement:
    prefix: REQ
    fields:
      text: {type: text, required: true}
"""

WORKER = """\
import os, sys, time
from refdes import ids, textio
from refdes.schema import load_project
from refdes.write_lock import project_write_lock

root, worker = sys.argv[1], int(sys.argv[2])
project = load_project(config_path=os.path.join(root, 'refdes-project.yaml'))
for index in range(20):
    with project_write_lock(root):
        ledger = ids.load_ledger(project)
        number = int(ledger['burned'].get('REQ', 0)) + 1
        item_id = f'REQ-{number:03d}'
        path = os.path.join(root, 'items', f'{worker}-{index}.yaml')
        textio.atomic_write_text(path, f'items:\\n  - type: requirement\\n    id: {item_id}\\n    text: worker {worker}\\n')
        ids.reserve_id(project, item_id)
"""


def _project(root: Path) -> Path:
    write_project_config(root, CONFIG)
    (root / "items").mkdir()
    return root / "refdes-project.yaml"


def test_two_processes_reserve_without_loss(tmp_path):
    _project(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", WORKER, str(tmp_path), str(worker)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        for worker in range(2)
    ]
    for process in processes:
        _out, err = process.communicate(timeout=60)
        assert process.returncode == 0, err

    files = sorted((tmp_path / "items").glob("*.yaml"))
    item_ids = [yaml.safe_load(path.read_text())["items"][0]["id"] for path in files]
    ledger = yaml.safe_load((tmp_path / ".refdes" / "ids.yaml").read_text())
    assert len(files) == len(item_ids) == len(set(item_ids)) == 40
    assert len(ledger["allocated"]) == 40


def test_one_command_writes_several_items_without_relocking(tmp_path):
    config = _project(tmp_path)
    for index in range(4):
        (tmp_path / "items" / f"{index}.yaml").write_text(
            "items:\n  - type: requirement\n    text: pending\n", encoding="utf-8"
        )
    assert cli.main(["-c", str(config), "id"]) == 0
    ledger = yaml.safe_load((tmp_path / ".refdes" / "ids.yaml").read_text())
    assert len(ledger["allocated"]) == 4


@pytest.mark.parametrize("no_write", [False, True])
def test_read_only_tree_leaves_no_lock(tmp_path, no_write):
    config = _project(tmp_path)
    (tmp_path / "items" / "one.yaml").write_text(
        "items:\n  - type: requirement\n    text: pending\n", encoding="utf-8"
    )
    for path in (config, tmp_path / "refdes-schema.yaml", tmp_path / "items" / "one.yaml"):
        path.chmod(0o444)
    (tmp_path / "items").chmod(0o555)
    tmp_path.chmod(0o555)
    try:
        args = [sys.executable, "-m", "refdes", "-c", str(config)]
        if no_write:
            args.append("--no-write")
        result = subprocess.run(
            [*args, "check"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
            timeout=30,
        )
        assert result.returncode in (0, 1), result.stderr
        assert "Traceback" not in result.stderr
        assert not (tmp_path / ".refdes-write.lock").exists()
        assert not (tmp_path / ".refdes").exists()
    finally:
        tmp_path.chmod(0o755)
        (tmp_path / "items").chmod(0o755)
        for path in (config, tmp_path / "refdes-schema.yaml", tmp_path / "items" / "one.yaml"):
            path.chmod(0o644)


def test_read_only_root_with_writable_items_refuses_without_writing(tmp_path, capsys):
    config = _project(tmp_path)
    item = tmp_path / "items" / "one.yaml"
    item.write_text("items:\n  - type: requirement\n    text: pending\n", encoding="utf-8")
    before = item.read_bytes()
    tmp_path.chmod(0o555)
    try:
        assert cli.main(["-c", str(config), "id"]) == 2
        assert "root is read-only while a child is writable" in capsys.readouterr().err
        assert item.read_bytes() == before
        assert not (tmp_path / ".refdes-write.lock").exists()
    finally:
        tmp_path.chmod(0o755)
