"""`refdes fetch` must not lose a lockfile `values:` key it did not write, silently.

`in-prog-logs/inline-calc-integration-probe-20261106.md` F1: hand-inserting
`Q: {reader: csv, value: '9.0'}` next to the real pin `V` in
`.refdes/citations.yaml`, then running `refdes fetch --path datasheet.csv
--update`, rewrites the row with only `V` -- no report line, `check` stays
clean, the author's key is gone.

The DECISION this file pins, stated in full in `in-prog-logs/fetch-values-
preserve.md`: the pruning of a key no `source()` span references is deliberate
and documented, so it stays.

* `citations.py:2347-2351` -- `_refresh_pinned_sources` pops the whole `values`
  map when `not keys`, with the comment "nothing cites a key from this file any
  more".
* `citations.py:2421-2424` -- `stage_source_pins`' docstring names "the
  whole-map replacement `_refresh_pinned_sources` does" as *correct* "for a
  fetch that walked every body in the project".
* `docs/design/calc-sources.md:534-538` -- a fetch "must collect all local
  `source()` uses ... then read each file once", staging extraction and
  replacing "that path's record"; the command matrix at :558 says `--update`
  replaces "file hash and all values".

What is NOT documented anywhere, and is the actual defect, is the silence: a
key the run removes is never named. So these tests pin the least destructive
consistent behaviour -- the removal is REPORTED, naming the file and the key,
while the record keeps holding exactly the keys in use. Under the rejected
alternative (keep unreferenced keys), the assertions marked `KEEP-FLIPS` are
the ones that change; the report assertions stand either way.

The report's exact wording is the implementer's. The contract asserted here is
what the probe found missing: one line per removed key, naming BOTH the
citation path and the key, on a run that still exits 0. `DROP_MARKER` is the
one word assumed.
"""

from __future__ import annotations

import hashlib
import re

import yaml
from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys, links, parse
from refdes.schema import load_project

CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      citations: { type: citations, on_change: invalidate }\n"
)
CSV = "key,value\nV,5.0\n"
CSV_MOVED = "key,value\nV,6.0\n"
PATH = "datasheet.csv"
ITEM = (
    "---\n"
    "id: DEC-001\n"
    "type: decision\n"
    f"citations:\n  - path: {PATH}\n"
    "---\n"
    "\n"
    '```calc\nV = source("datasheet.csv", "V") | V\n```\n'
)
# The hand-inserted key the probe used: well-formed (so the lockfile stays
# readable and `check` says nothing about it) and named by no `source()` span.
ORPHAN_KEY = "Q"
ORPHAN_VALUE = "9.0"
DROP_MARKER = "dropped"


def _setup(tmp_path) -> str:
    config = str(write_project_config(tmp_path, CONFIG))
    (tmp_path / PATH).write_text(CSV, encoding="utf-8", newline="")
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "a.md").write_text(ITEM, encoding="utf-8", newline="")
    return config


def _lockfile(tmp_path):
    return tmp_path / ".refdes" / "citations.yaml"


def _raw(tmp_path) -> str:
    # read_bytes, not read_text: every assertion below is about exact bytes,
    # and the lockfile is written LF-only on every platform (textio.write_text).
    return _lockfile(tmp_path).read_bytes().decode("utf-8")


def _record(tmp_path) -> dict:
    return yaml.safe_load(_raw(tmp_path))["citations"][PATH]


def _insert_orphan(tmp_path, key: str = ORPHAN_KEY, value: str = ORPHAN_VALUE) -> None:
    """Add `key` to the record's `values:` map, in the file's own format, next to
    the pin `fetch` wrote. Text-level on purpose: the point is a key the tool
    wrote next to a key it did not."""
    raw = _raw(tmp_path)
    needle = "    values:\n"
    assert needle in raw, raw
    block = f"      {key}:\n        reader: csv\n        value: '{value}'\n"
    _lockfile(tmp_path).write_bytes(raw.replace(needle, needle + block, 1).encode("utf-8"))


def _strip_fetched(raw: str) -> str:
    """The lockfile text without the `fetched:` lines, which every write
    legitimately re-stamps."""
    return "".join(
        line for line in raw.splitlines(keepends=True) if not line.startswith("    fetched: ")
    )


def _fetch(config, *extra) -> int:
    return cli_mod.main(["-c", config, "fetch", *extra])


def _out(capsys) -> str:
    """Everything the last command printed. One readouterr per capture: the
    second call on the same buffer returns empty."""
    captured = capsys.readouterr()
    return captured.out + captured.err


def _drop_lines(output: str, path: str = PATH, key: str = ORPHAN_KEY) -> list[str]:
    """Report lines naming both the cited file and the removed key."""
    named_key = re.compile(rf"(?<![\w.-]){re.escape(key)}\b")
    return [
        line
        for line in output.splitlines()
        if path in line and named_key.search(line) and DROP_MARKER in line.lower()
    ]


def _project(config):
    project = load_project(config_path=config)
    parse.load_items(project)
    if keys.mint_missing(project, write=True):
        project.items = {}
        project.items_by_id = {}
        project.pending = []
        parse.load_items(project)
    links.expand_missing_calc_refs(project, write=True)
    build_mod.build(project, seal_write=False)
    return project


def _write_csv(tmp_path, text: str) -> str:
    (tmp_path / PATH).write_text(text, encoding="utf-8", newline="")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------- the report


def test_update_reports_the_values_key_it_removes(tmp_path, capsys):
    """F1 verbatim: `fetch --update` removes the hand-inserted key AND says so."""
    config = _setup(tmp_path)
    assert _fetch(config, "--path", PATH) == 0
    capsys.readouterr()
    _insert_orphan(tmp_path)

    assert _fetch(config, "--path", PATH, "--update") == 0
    out = _out(capsys)
    assert _drop_lines(out), f"no report line named {PATH} {ORPHAN_KEY}; got:\n{out}"
    # The record keeps exactly the keys a span references -- the documented
    # shape (module docstring). KEEP-FLIPS: under "keep unreferenced keys",
    # this is the assertion that changes; the one above does not.
    assert set(_record(tmp_path)["values"]) == {"V"}


def test_plain_fetch_reports_the_values_key_it_removes(tmp_path, capsys):
    """The no-`--update` half prunes too (`_refresh_pinned_sources`), so it
    has to say so as well: a plain fetch is the command the docs tell an
    author to run, and it is the one that eats their key."""
    config = _setup(tmp_path)
    assert _fetch(config, "--path", PATH) == 0
    capsys.readouterr()
    _insert_orphan(tmp_path)

    assert _fetch(config, "--path", PATH) == 0
    out = _out(capsys)
    assert _drop_lines(out), f"no report line named {PATH} {ORPHAN_KEY}; got:\n{out}"
    assert set(_record(tmp_path)["values"]) == {"V"}  # KEEP-FLIPS


def test_update_refreshes_the_recognised_pin_and_reports_the_orphan(tmp_path, capsys):
    """No regression of the normal update: the pin a span DOES reference is
    refreshed to the changed bytes, its diff line still printed, and the
    unrelated key's removal is reported in the same run."""
    config = _setup(tmp_path)
    assert _fetch(config, "--path", PATH) == 0
    _insert_orphan(tmp_path)
    capsys.readouterr()

    digest = _write_csv(tmp_path, CSV_MOVED)
    assert _fetch(config, "--path", PATH, "--update") == 0
    out = _out(capsys)
    record = _record(tmp_path)
    assert record["values"]["V"] == {"reader": "csv", "value": "6.0"}
    assert record["sha256"] == digest
    assert f"{PATH}: V: 5.0 -> 6.0" in out
    assert _drop_lines(out), f"no report line named {PATH} {ORPHAN_KEY}; got:\n{out}"
    assert set(record["values"]) == {"V"}  # KEEP-FLIPS


def test_plain_fetch_changes_only_what_it_reports(tmp_path, capsys):
    """A plain fetch that eats a key must not also move anything else: with
    the file's bytes unchanged, the recognised pin's entry is byte-identical,
    and the only removals are the ones the run named."""
    config = _setup(tmp_path)
    assert _fetch(config, "--path", PATH) == 0
    _insert_orphan(tmp_path)
    before = _raw(tmp_path)
    capsys.readouterr()

    assert _fetch(config, "--path", PATH) == 0
    out = _out(capsys)
    after = _raw(tmp_path)
    orphan_block = (
        f"      {ORPHAN_KEY}:\n        reader: csv\n        value: '{ORPHAN_VALUE}'\n"
    )
    assert _strip_fetched(before).replace(orphan_block, "") == _strip_fetched(after)
    assert _drop_lines(out), f"no report line named {PATH} {ORPHAN_KEY}; got:\n{out}"


def test_check_stays_clean_with_the_extra_key_present_and_after_the_drop(
    tmp_path, capsys
):
    """The report is a report, not a finding: `check` is clean while the
    hand-inserted key sits in the lockfile (it is inert -- nothing reads a key
    no span names), clean again after the reported removal, and the span keeps
    computing from the pin."""
    config = _setup(tmp_path)
    assert _fetch(config, "--path", PATH) == 0
    _insert_orphan(tmp_path)

    assert cli_mod.main(["-c", config, "check"]) == 0
    assert "0 errors" in capsys.readouterr().out
    capsys.readouterr()

    assert _fetch(config, "--path", PATH, "--update") == 0
    out = _out(capsys)
    assert _drop_lines(out), f"no report line named {PATH} {ORPHAN_KEY}; got:\n{out}"

    assert cli_mod.main(["-c", config, "check"]) == 0
    assert "0 errors" in capsys.readouterr().out
    # The span still computes from the pin (rendered at the project's sigfigs).
    assert _project(config).item_by_id("DEC-001").calc_values["V"] == "5 V"


def test_update_twice_reports_the_removal_once(tmp_path, capsys):
    """Idempotence: the second `--update` has no key left to remove, so it
    must not report one, and it must not move the row again."""
    config = _setup(tmp_path)
    assert _fetch(config, "--path", PATH) == 0
    _insert_orphan(tmp_path)
    capsys.readouterr()

    assert _fetch(config, "--path", PATH, "--update") == 0
    first = _out(capsys)
    assert _drop_lines(first), f"no report line named {PATH} {ORPHAN_KEY}; got:\n{first}"
    after_first = _strip_fetched(_raw(tmp_path))
    capsys.readouterr()

    assert _fetch(config, "--path", PATH, "--update") == 0
    second = _out(capsys)
    assert not _drop_lines(second), f"second run reported a removal it did not make: {second}"
    assert _strip_fetched(_raw(tmp_path)) == after_first
