"""calc `source("path", "key")` end to end (docs/design/calc-sources.md, finding 26).

Fetch pins each used key in the citation lockfile; check/build evaluate from
that lockfile only. Sabotage-style, like test_calc_cross_ref_hash.py: every
claim is paired with the mutation that would falsify it.
"""

from __future__ import annotations

import os

import pytest
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
CSV = "key,value,note\nrail_load,1.85,mW budget\neff,0.93,datasheet\nother,7,x\n"
CALC = '```calc\nP = source("analysis/budget.csv", "rail_load") | W\n```\n'


def _item(item_id: str, body: str = CALC, cite: str = "analysis/budget.csv") -> str:
    front = f"id: {item_id}\ntype: decision\n"
    if cite:
        front += f"citations:\n  - path: {cite}\n"
    return f"---\n{front}---\n\n{body}"


def _write(root, files: dict[str, str]) -> None:
    items = root / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")


def _setup(tmp_path, csv: str = CSV, items: dict[str, str] | None = None):
    write_project_config(tmp_path, CONFIG)
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "budget.csv").write_text(csv, encoding="utf-8", newline="")
    _write(tmp_path, items if items is not None else {"a.md": _item("DEC-001")})
    return str(tmp_path / "refdes-project.yaml")


def _fetch(config, *extra):
    return cli_mod.main(["-c", config, "fetch", *extra])


def _project(config, write: bool = True, **build_kwargs):
    project = load_project(config_path=config)
    parse.load_items(project)
    if keys.mint_missing(project, write=write):
        project.items = {}
        project.items_by_id = {}
        project.pending = []
        parse.load_items(project)
    links.expand_missing_calc_refs(project, write=write)
    build_mod.build(project, **build_kwargs)
    return project


def _lock(tmp_path):
    text = (tmp_path / ".refdes" / "citations.yaml").read_text("utf-8")
    return yaml.safe_load(text)["citations"]


def _errors(project):
    return [d.message for d in project.errors]


def _warnings(project):
    return [d.message for d in project.warnings]


def _rewrite_csv(tmp_path, text):
    (tmp_path / "analysis" / "budget.csv").write_text(text, encoding="utf-8", newline="")


# ---------------------------------------------------------------- 1: selection


def test_csv_source_selects_same_row_value_by_exact_key_through_fetch(tmp_path, capsys):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    out = capsys.readouterr().out
    assert "extracted analysis/budget.csv rail_load = 1.85" in out
    record = _lock(tmp_path)["analysis/budget.csv"]
    assert record["values"] == {"rail_load": {"reader": "csv", "value": "1.85"}}
    p = _project(config)
    assert not p.errors, _errors(p)
    assert p.item_by_id("DEC-001").calc_values["P"] == "1.85 W"
    # Reordering rows in the file changes nothing about the selected value.
    _rewrite_csv(tmp_path, "key,value,note\nother,7,x\neff,0.93,d\nrail_load,1.85,m\n")
    assert _fetch(config, "--update") == 0
    assert _project(config).item_by_id("DEC-001").calc_values["P"] == "1.85 W"


# ---------------------------------------------------------------- 8: authorization


def test_source_requires_same_item_local_citation_and_explicit_annotation(tmp_path, capsys):
    config = _setup(tmp_path, items={
        "a.md": _item("DEC-001"),
        # cites the file, but no unit
        "b.md": _item("DEC-002", '```calc\nQ = source("analysis/budget.csv", "eff")\n```\n'),
        # no citation of its own -- DEC-001's does not authorize it
        "c.md": _item("DEC-003", CALC, cite=""),
        # a remote citation is not a source
        "d.md": _item("DEC-004",
                      '```calc\nR = source("https://example.com/x.csv", "k") | W\n```\n',
                      cite="https://example.com/x.csv"),
    })
    assert _fetch(config) == 1
    err = capsys.readouterr().err
    assert "DEC-003" in err and "does not cite" in err
    assert "DEC-004" in err and "remote citation" in err
    p = _project(config)
    text = "\n".join(_errors(p))
    assert "needs an explicit unit" in text
    assert "does not cite" in text
    assert "remote citation" in text
    assert "P" not in p.item_by_id("DEC-003").calc_values
    assert "Q" not in p.item_by_id("DEC-002").calc_values


def test_source_dimensionless_unit_form_and_duplicate_name(tmp_path):
    config = _setup(tmp_path, items={"a.md": _item(
        "DEC-001",
        '```calc\neff = source("analysis/budget.csv", "eff") | 1\n'
        'eff = source("analysis/budget.csv", "eff") | 1\n```\n',
    )})
    assert _fetch(config) == 0
    p = _project(config)
    assert p.item_by_id("DEC-001").calc_values["eff"] == "0.93"
    assert any("assigned twice" in e for e in _errors(p))


def test_source_is_not_callable_in_an_expression_or_equation(tmp_path):
    config = _setup(tmp_path, items={"a.md": _item(
        "DEC-001", '```calc\nP = 2 * source("analysis/budget.csv", "eff") | 1\n```\n')})
    _fetch(config)
    p = _project(config)
    assert any("whole right-hand side" in e for e in _errors(p))
    from refdes import calc

    with pytest.raises(calc.CalcError, match="source"):
        calc.validate_equations({"f": calc.Equation("f", ["x"], "x * source('a.csv', 'k')")})
    with pytest.raises(calc.CalcError, match="reserved"):
        calc.validate_equations({"source": calc.Equation("source", ["x"], "x")})


def test_source_tolerance_on_right_hand_side(tmp_path):
    config = _setup(tmp_path, items={"a.md": _item(
        "DEC-001", '```calc\neff = source("analysis/budget.csv", "eff") ± 2 % | 1\n```\n')})
    assert _fetch(config) == 0
    p = _project(config)
    assert not p.errors, _errors(p)
    line = p.item_by_id("DEC-001").calcs[0]
    assert line.result == "0.93" and line.bounds


def test_source_key_may_contain_a_hash_sign(tmp_path):
    config = _setup(tmp_path, csv="key,value\nrow#3,4.5\n", items={"a.md": _item(
        "DEC-001", '```calc\nx = source("analysis/budget.csv", "row#3") | 1  # note\n```\n')})
    assert _fetch(config) == 0
    assert _project(config).item_by_id("DEC-001").calc_values["x"] == "4.5"


# ------------------------------------------------------------- 9: lock only


def test_source_build_uses_locked_value_without_opening_reader_file(tmp_path, monkeypatch):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    from refdes import sources

    def boom(*a, **k):
        raise AssertionError("a reader ran during build")

    monkeypatch.setattr(sources.CsvReader, "extract", boom)
    p = _project(config)
    assert p.item_by_id("DEC-001").calc_values["P"] == "1.85 W"
    # Deleting the file is the existing 'cited file missing' error -- but the
    # value still comes from the lock, never from the (absent) file.
    os.remove(tmp_path / "analysis" / "budget.csv")
    p = _project(config)
    assert p.item_by_id("DEC-001").calc_values["P"] == "1.85 W"
    assert any("does not exist" in e for e in _errors(p))


def test_unfetched_source_errors_naming_the_command(tmp_path):
    config = _setup(tmp_path)
    p = _project(config)
    assert any(
        "has no locked value" in e and "refdes fetch --path analysis/budget.csv" in e
        for e in _errors(p)
    )
    assert "P" not in p.item_by_id("DEC-001").calc_values


# ------------------------------------------------------------- 10-13: fetch matrix


def test_fetch_extracts_missing_value_from_matching_existing_pin(tmp_path, capsys):
    config = _setup(tmp_path, items={"a.md": _item(
        "DEC-001", '```calc\nA = source("analysis/budget.csv", "eff") | 1\n```\n')})
    assert _fetch(config) == 0
    sha = _lock(tmp_path)["analysis/budget.csv"]["sha256"]
    _write(tmp_path, {"a.md": _item(
        "DEC-001",
        '```calc\nA = source("analysis/budget.csv", "eff") | 1\n'
        'B = source("analysis/budget.csv", "rail_load") | W\n```\n')})
    capsys.readouterr()
    assert _fetch(config) == 0  # no --update needed
    assert "extracted analysis/budget.csv rail_load = 1.85" in capsys.readouterr().out
    record = _lock(tmp_path)["analysis/budget.csv"]
    assert record["sha256"] == sha
    assert set(record["values"]) == {"eff", "rail_load"}
    assert _project(config).item_by_id("DEC-001").calc_values["B"] == "1.85 W"


def test_fetch_refuses_missing_extraction_when_file_hash_changed_without_update(
    tmp_path, capsys
):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    before = _lock(tmp_path)
    _rewrite_csv(tmp_path, CSV.replace("1.85", "2.3"))
    _write(tmp_path, {"a.md": _item(
        "DEC-001", CALC + '```calc\nB = source("analysis/budget.csv", "eff") | 1\n```\n')})
    capsys.readouterr()
    assert _fetch(config) == 1
    err = capsys.readouterr().err
    assert "never extracted" in err
    assert "refdes fetch --update --path analysis/budget.csv" in err
    assert _lock(tmp_path) == before  # never the old hash over new bytes


def test_fetch_update_reports_value_diff_and_updates_hash_and_values_atomically(
    tmp_path, capsys
):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    old_sha = _lock(tmp_path)["analysis/budget.csv"]["sha256"]
    _rewrite_csv(tmp_path, CSV.replace("1.85", "2.3"))
    capsys.readouterr()
    assert _fetch(config) == 0  # plain fetch: skipped, locked value kept
    out = capsys.readouterr().out
    assert "skipped" in out and "locked source values are kept" in out
    assert _lock(tmp_path)["analysis/budget.csv"]["values"]["rail_load"]["value"] == "1.85"
    assert _fetch(config, "--update") == 0
    out = capsys.readouterr().out
    assert "analysis/budget.csv: rail_load: 1.85 -> 2.3" in out
    record = _lock(tmp_path)["analysis/budget.csv"]
    assert record["sha256"] != old_sha
    assert record["values"]["rail_load"]["value"] == "2.3"
    assert _project(config).item_by_id("DEC-001").calc_values["P"] == "2.3 W"


def test_fetch_update_preserves_previous_record_when_named_key_vanishes(tmp_path, capsys):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    before = _lock(tmp_path)
    _rewrite_csv(tmp_path, "key,value\nnot_it,1\n")
    capsys.readouterr()
    assert _fetch(config, "--update") == 1
    assert "no row has the key 'rail_load'" in capsys.readouterr().err
    assert _lock(tmp_path) == before  # neither the hash nor the values moved
    for bad in ("key,value\nrail_load,1\nrail_load,1\n", "key,value\nrail_load,1 W\n"):
        _rewrite_csv(tmp_path, bad)
        assert _fetch(config, "--update") == 1
        assert _lock(tmp_path) == before
    capsys.readouterr()


def test_first_pin_with_failing_key_writes_no_record(tmp_path):
    config = _setup(tmp_path, csv="key,value\nnope,1\n")
    assert _fetch(config) == 1
    assert not (tmp_path / ".refdes" / "citations.yaml").exists()


def test_fetch_update_warns_on_exact_1000x_change_but_still_records(tmp_path, capsys):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    _rewrite_csv(tmp_path, CSV.replace("1.85", "1850"))
    capsys.readouterr()
    assert _fetch(config, "--update") == 0
    captured = capsys.readouterr()
    assert "factor of 1000" in captured.err and "1.85 -> 1850" in captured.err
    assert _lock(tmp_path)["analysis/budget.csv"]["values"]["rail_load"]["value"] == "1850"
    # An ordinary change (1850 -> 3) is not advisory.
    _rewrite_csv(tmp_path, CSV.replace("1.85", "3"))
    _fetch(config, "--update")
    assert "factor of 1000" not in capsys.readouterr().err


# ------------------------------------------------------------- Q2: loud drift


def test_changed_source_file_warns_loudly_and_keeps_locked_value(tmp_path, capsys):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    _rewrite_csv(tmp_path, CSV.replace("1.85", "2.3"))
    p = _project(config)
    assert not p.errors, _errors(p)  # a warning, never an error
    assert p.item_by_id("DEC-001").calc_values["P"] == "1.85 W"  # locked, not the file
    msg = next(w for w in _warnings(p) if "SOURCE FILE CHANGED" in w)
    for part in ("analysis/budget.csv", "'rail_load'", "locked 1.85", "file now 2.3",
                 "refdes fetch --update --path analysis/budget.csv", "DEC-001"):
        assert part in msg, (part, msg)
    # Visible on the rendered item, too.
    assert "file now 2.3" in p.item_by_id("DEC-001").calcs[0].source_drift
    page = tmp_path / "_site" / "items" / "DEC-001.html"
    if page.exists():
        assert "calc-source-drift" in page.read_text("utf-8")
    # The generic 'has changed' note is replaced, not duplicated.
    assert not any(w.startswith("local citation") for w in _warnings(p))
    # --update is the acceptance gate; afterwards the warning is gone.
    assert _fetch(config, "--update") == 0
    p = _project(config)
    assert not any("SOURCE FILE CHANGED" in w for w in _warnings(p))
    assert p.item_by_id("DEC-001").calc_values["P"] == "2.3 W"
    capsys.readouterr()


def test_changed_source_file_is_an_error_under_require_citations(tmp_path):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    _rewrite_csv(tmp_path, CSV.replace("1.85", "2.3"))
    _project(config)  # mint keys so the next build is the one under test
    p = _project(config, require_citations=True)
    assert any("SOURCE FILE CHANGED" in e for e in _errors(p))
    assert p.item_by_id("DEC-001").calc_values["P"] == "1.85 W"  # still the locked value


def test_source_drift_when_file_no_longer_supplies_the_key(tmp_path):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    _rewrite_csv(tmp_path, "key,value\nzzz,1\n")
    p = _project(config)
    msg = next(w for w in _warnings(p) if "SOURCE FILE CHANGED" in w)
    assert "can no longer supply it" in msg and "locked 1.85" in msg
    assert p.item_by_id("DEC-001").calc_values["P"] == "1.85 W"


def test_unchanged_value_in_changed_file_still_warns_but_says_unchanged(tmp_path):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    _rewrite_csv(tmp_path, CSV.replace("other,7", "other,8"))
    p = _project(config)
    msg = next(w for w in _warnings(p) if "SOURCE FILE CHANGED" in w)
    assert "this value is unchanged" in msg


# ------------------------------------------------------------- 14/15: hash


def _hash(config):
    return _project(config).item_by_id("DEC-001").content_hash


def test_source_value_hash_changes_when_locked_value_changes(tmp_path):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    h1 = _hash(config)
    _rewrite_csv(tmp_path, CSV.replace("1.85", "2.3"))
    assert _hash(config) == h1, "drift alone must not move the hash"
    assert _fetch(config, "--update") == 0
    h2 = _hash(config)
    assert h2 != h1  # identical item text, accepted update moved the value
    # ...and an unrelated value in the same source file does not.
    _rewrite_csv(tmp_path, CSV.replace("1.85", "2.3").replace("other,7", "other,9"))
    assert _fetch(config, "--update") == 0
    assert _hash(config) == h2


def test_source_lock_timestamp_and_unreferenced_values_do_not_change_hash(tmp_path):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    h1 = _hash(config)
    lock = tmp_path / ".refdes" / "citations.yaml"
    data = yaml.safe_load(lock.read_text("utf-8"))
    rec = data["citations"]["analysis/budget.csv"]
    rec["fetched"] = "1999-01-01T00:00:00Z"
    rec["bytes"] = 1
    rec["values"]["unreferenced"] = {"reader": "csv", "value": "42"}
    lock.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert _hash(config) == h1


def test_item_without_source_has_no_source_values_in_its_hash_payload(tmp_path):
    """Hash-neutral: no source() line, no `source_values` key, so HASH_FORMAT 4
    hashes the item exactly as it did before finding 26 landed. Format stays 4."""
    config = _setup(tmp_path, items={"a.md": _item(
        "DEC-001", "```calc\nx = 2 A\n```\n", cite="")})
    project = _project(config)
    item = project.item_by_id("DEC-001")
    payload = build_mod.hash_payload_builder(project, build_mod.HASH_FORMAT)(
        item, project.types[item.type])
    assert "source_values" not in payload
    assert build_mod.HASH_FORMAT == 4


def test_source_value_reaches_the_payload_only_for_the_used_key(tmp_path):
    config = _setup(tmp_path)
    assert _fetch(config) == 0
    project = _project(config)
    item = project.item_by_id("DEC-001")
    payload = build_mod.hash_payload_builder(project, build_mod.HASH_FORMAT)(
        item, project.types[item.type])
    assert payload["source_values"] == [["analysis/budget.csv", "rail_load", "1.85"]]


# ------------------------------------------------------------- 16: no-write


def test_source_no_write_never_creates_or_updates_lockfile(tmp_path, capsys):
    config = _setup(tmp_path)
    _project(config)  # settle key minting so only the lockfile is in question
    lock = tmp_path / ".refdes" / "citations.yaml"
    assert not lock.exists()
    assert cli_mod.main(["-c", config, "--no-write", "fetch"]) == 2
    assert not lock.exists()
    assert cli_mod.main(["-c", config, "--no-write", "check"]) in (0, 1)
    assert not lock.exists()
    assert _fetch(config) == 0
    before = lock.read_bytes()
    _rewrite_csv(tmp_path, CSV.replace("1.85", "2.3"))
    assert cli_mod.main(["-c", config, "--no-write", "check"]) in (0, 1)
    assert cli_mod.main(["-c", config, "--no-write", "fetch", "--update"]) == 2
    assert lock.read_bytes() == before
    capsys.readouterr()


# ------------------------------------------------------------- 22: read-only


def test_source_reader_cannot_write_source_file(tmp_path):
    config = _setup(tmp_path)
    src = tmp_path / "analysis" / "budget.csv"
    before = src.read_bytes()
    assert _fetch(config) == 0
    assert _fetch(config, "--update") == 0
    assert src.read_bytes() == before


# ------------------------------------------------------------- units (section 6)


def test_source_declared_unit_labels_the_number_it_does_not_convert_it(tmp_path):
    """The 1000x trap made visible: 1850 in a milliwatt sheet under `| W` shows
    as 1850 W. Silently converting (or inferring mW) would hide the error."""
    config = _setup(tmp_path, csv="key,value\nrail_load,1850\n", items={"a.md": _item(
        "DEC-001",
        '```calc\nP = source("analysis/budget.csv", "rail_load") | W\n'
        'Q = source("analysis/budget.csv", "rail_load") | mW\n```\n')})
    assert _fetch(config) == 0
    p = _project(config)
    assert not p.errors, _errors(p)
    values = p.item_by_id("DEC-001").calc_values
    assert values["P"] == "1850 W"
    assert values["Q"] == "1850 mW"  # the declared unit is what is shown


def test_source_unknown_unit_is_an_error(tmp_path):
    config = _setup(tmp_path, items={"a.md": _item(
        "DEC-001", '```calc\nP = source("analysis/budget.csv", "eff") | florps\n```\n')})
    assert _fetch(config) == 0
    p = _project(config)
    assert any("unknown unit" in e for e in _errors(p))
