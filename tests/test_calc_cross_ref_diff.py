"""The baseline diff names the upstream value that moved (finding 35, chunk 3).

A dependent whose own text never changed is `changed` because a referenced
value moved; the diff must say which reference and from/to what -- and say
nothing invented when the baseline recorded no reference values.
"""

from __future__ import annotations

from test_calc_cross_ref_hash import DOWN, UP, _build, _edit, _item

from refdes import lifecycle


def _stamped(tmp_path):
    p1 = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V ± 5%")),
        "b.md": _item("DEC-002", DOWN),
    })
    assert not p1.errors
    outcome = lifecycle.stamp(p1, kind="revision", name="rev-a")
    assert outcome.status == "stamped"
    return lifecycle.load_baseline(p1, "rev-a")


def test_baseline_records_referenced_values(tmp_path):
    baseline = _stamped(tmp_path)
    (b_entry,) = [e for e in baseline.items.values() if "calc_refs" in e]
    (ref, text), = b_entry["calc_refs"].items()
    assert ref.endswith(".V_in") and "@" not in ref
    assert text.startswith("12 V")
    # An item with no reference records nothing extra: no key at all.
    assert sum("calc_refs" in e for e in baseline.items.values()) == 1


def test_diff_names_the_moved_reference_with_old_and_new(tmp_path):
    baseline = _stamped(tmp_path)
    _edit(tmp_path, "a.md", "12 V ± 5%", "11.4 V ± 5%")
    p2 = _build(tmp_path, {})
    diff = lifecycle.diff_against(p2, baseline, write=False)
    assert "DEC-002" in diff.changed
    (line,) = diff.moved_refs["DEC-002"]
    assert line.startswith("referenced DEC-001.V_in: 12 V")
    assert "-> 11.4 V" in line
    assert "DEC-001" not in diff.moved_refs  # its own edit, not a reference


def test_diff_does_not_invent_a_move_after_upstream_display_rename(tmp_path):
    baseline = _stamped(tmp_path)
    _edit(tmp_path, "a.md", "id: DEC-001", "id: DEC-777")
    p2 = _build(tmp_path, {})
    diff = lifecycle.diff_against(p2, baseline, write=False)
    assert "DEC-002" not in diff.changed
    assert diff.moved_refs == {}


def test_diff_is_silent_for_a_baseline_without_recorded_refs(tmp_path):
    baseline = _stamped(tmp_path)
    for entry in baseline.items.values():
        entry.pop("calc_refs", None)
    _edit(tmp_path, "a.md", "12 V ± 5%", "11.4 V ± 5%")
    p2 = _build(tmp_path, {})
    diff = lifecycle.diff_against(p2, baseline, write=False)
    assert "DEC-002" in diff.changed
    assert diff.moved_refs == {}


def test_a_newly_added_reference_is_the_items_own_edit(tmp_path):
    p1 = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V")),
        "b.md": _item("DEC-002", "```calc\nQ = 1 A\n```\n"),
    })
    lifecycle.stamp(p1, kind="revision", name="rev-a")
    baseline = lifecycle.load_baseline(p1, "rev-a")
    _edit(tmp_path, "b.md", "Q = 1 A", "V_in = DEC-001.V_in")
    p2 = _build(tmp_path, {})
    diff = lifecycle.diff_against(p2, baseline, write=False)
    assert "DEC-002" in diff.changed
    assert diff.moved_refs == {}
