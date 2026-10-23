"""F13-1: the inline-calc release gate fails closed on an unreadable history
store, and now *says so*.

The rule (``lifecycle._rule_inline_calc_results``) already fails closed when
the history store cannot be read and a stale inline-calc span is in play --
it refuses to read a frozen-text exemption out of a store it cannot open. The
bug was that the blocked-release output never named the cause: a previously
captured-exempt item just turned up in the offender list with no explanation,
reading to the author as "my capture expired" -- the opposite of the truth.

These tests pin the required output (docs/math.md, docs/lifecycle.md): when
and only when the store is unreadable AND a stale span is in play, the rule's
failure output gains ONE leading line naming the store, of the form

    stale inline-calc gate: cannot read the history store <path> (<error text>) -- failing closed

where ``<path>`` is the store relative to the project root (``.refdes/history``)
and ``<error text>`` is ``str(exc)``. The offenders, exit codes, and which
items fail are unchanged; a readable store (or no stale span) prints nothing
new.

The unreadable store is simulated by monkeypatching ``history.capture_index``
to raise ``OSError`` -- not ``chmod`` (unreliable as root / on Windows).
"""

from __future__ import annotations

import os

from conftest import write_project_config

from refdes import build as build_mod
from refdes import history, keys, lifecycle
from refdes.schema import load_project

# Relative store path, from history.HISTORY_DIR (os.path.join on this OS).
STORE_REL = os.path.join(".refdes", "history")
ERR_TEXT = "simulated store failure"


def _cause_line() -> str:
    """The one line the rule must prepend: exact contract form."""
    return (
        "stale inline-calc gate: cannot read the history store "
        f"{STORE_REL} ({ERR_TEXT}) -- failing closed"
    )


IC_CONFIG = (
    "site: { title: IC, out: _site }\n"
    "types: { decision: { prefix: DEC, fields: {} } }\n"
)

# Stored 4.52 V, computes 4.436 V: outside the stored literal's half-place
# window -- the canonical stale span (same fixture as test_lifecycle.py).
IC_STALE_BODY = "The divider gives `Vout := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 4.52 V`.\n"
IC_FRESH_BODY = "The divider gives `Vout := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 4.436 V`.\n"


def _rebuild(tmp_path):
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    from refdes import parse

    parse.load_items(project)
    keys.mint_missing(project)
    build_mod.build(project)
    return project


def _one_stale_project(tmp_path):
    """One editable, unsealed item with a stale inline-calc span."""
    write_project_config(tmp_path, IC_CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n{IC_STALE_BODY}", encoding="utf-8"
    )
    _rebuild(tmp_path)  # key-minting rewrite: line numbers match disk
    return _rebuild(tmp_path)


def _two_stale_project(tmp_path):
    """Two editable, unsealed items each with a stale inline-calc span, so the
    rule has two offenders to adjudicate at once."""
    write_project_config(tmp_path, IC_CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n{IC_STALE_BODY}", encoding="utf-8"
    )
    (items / "dec2.md").write_text(
        f"---\nid: DEC-002\ntype: decision\n---\n\n{IC_STALE_BODY}", encoding="utf-8"
    )
    _rebuild(tmp_path)
    return _rebuild(tmp_path)


def _fresh_project(tmp_path):
    """No stale span at all (the rule has nothing to adjudicate)."""
    write_project_config(tmp_path, IC_CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n{IC_FRESH_BODY}", encoding="utf-8"
    )
    _rebuild(tmp_path)
    return _rebuild(tmp_path)


def _dec_span_line(tmp_path):
    text = (tmp_path / "items" / "dec.md").read_text(encoding="utf-8").splitlines()
    return next(i for i, ln in enumerate(text, start=1) if "Vout :=" in ln)


def _break_store(monkeypatch):
    """Make the history store unreadable: capture_index raises OSError."""

    def boom(project):
        raise OSError(ERR_TEXT)

    monkeypatch.setattr(history, "capture_index", boom)


def test_unreadable_store_with_stale_span_names_the_store(tmp_path, monkeypatch):
    """Unreadable store + a stale span: the gate fails closed AND the rule's
    output gains exactly one leading line naming the store (relative path +
    error text), with the offender still listed after it."""
    project = _one_stale_project(tmp_path)
    _break_store(monkeypatch)

    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    rule = results["inline_calc_results"]
    assert rule.enabled is True
    assert rule.status == "FAIL"

    # The named-store line is the FIRST entry of the rule's output.
    assert rule.offenders[0] == _cause_line()
    assert STORE_REL in rule.offenders[0]
    assert ERR_TEXT in rule.offenders[0]

    # The offender itself is unchanged, listed after the cause line.
    line = _dec_span_line(tmp_path)
    assert rule.offenders[1:] == [f"DEC-001: inline calc Vout (items/dec.md:{line})"]

    # Exit codes / which items fail are unchanged: the release is blocked.
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))


def test_unreadable_store_with_stale_span_names_the_store_on_cli_release(
    tmp_path, monkeypatch, capsys
):
    """The named-store line reaches the ``refdes release`` FAIL detail that
    the author reads -- the same channel as every other rule's offenders."""
    from refdes import cli as cli_mod

    project = _one_stale_project(tmp_path)
    _break_store(monkeypatch)
    cfg = str(tmp_path / "refdes-project.yaml")

    assert cli_mod.main(["-c", cfg, "release", "rel-a"]) == 1
    err = capsys.readouterr().err
    assert "FAIL     inline_calc_results" in err  # the FAIL row is this rule
    assert "cannot read the history store" in err
    assert STORE_REL in err
    assert ERR_TEXT in err
    assert "failing closed" in err
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))


def test_unreadable_store_without_stale_span_passes_and_prints_nothing_new(
    tmp_path, monkeypatch
):
    """Control: a broken store is not a global gate. With no stale span to
    adjudicate the rule passes and prints NOTHING new (no store line)."""
    project = _fresh_project(tmp_path)
    assert not any(d.code == "inline_calc_stale" for d in project.warnings)
    _break_store(monkeypatch)

    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    rule = results["inline_calc_results"]
    assert rule.status == "pass"
    assert rule.offenders == []
    joined = "\n".join(rule.offenders)
    assert "cannot read the history store" not in joined
    assert lifecycle.stamp(project, kind="release", name="rel-a").status == "stamped"


def test_readable_store_emits_no_named_store_line(tmp_path):
    """Control: a readable store. The rule fails on the stale span as today
    (one offender), and NO named-store line is printed anywhere."""
    project = _one_stale_project(tmp_path)

    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    rule = results["inline_calc_results"]
    assert rule.status == "FAIL"
    line = _dec_span_line(tmp_path)
    assert rule.offenders == [f"DEC-001: inline calc Vout (items/dec.md:{line})"]
    joined = "\n".join(rule.offenders)
    assert "cannot read the history store" not in joined
    assert "failing closed" not in joined


def test_named_store_line_appears_once_with_multiple_offenders(tmp_path, monkeypatch):
    """The named-store line is ONE per rule run, not one per offender: two
    stale spans produce two offenders behind a single store line."""
    project = _two_stale_project(tmp_path)
    _break_store(monkeypatch)

    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    rule = results["inline_calc_results"]
    assert rule.status == "FAIL"

    cause = _cause_line()
    named = [o for o in rule.offenders if o == cause]
    assert len(named) == 1
    assert rule.offenders[0] == cause

    line = _dec_span_line(tmp_path)
    assert rule.offenders[1:] == [
        f"DEC-001: inline calc Vout (items/dec.md:{line})",
        f"DEC-002: inline calc Vout (items/dec2.md:{line})",
    ]
