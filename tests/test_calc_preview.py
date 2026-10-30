"""The live editor's read-only calc preview pass: `build.preview_inline_spans`
(in-prog-logs/inline-calc-live-editor-design-20261020.md §3.4, slice A/B1).

The route is the pass's only caller, so the unit tests are the contract:
status/message parity with the real build (the panel teaches `refdes check`'s
vocabulary, never a second one), `computed` at the project's sigfigs, ranges
in `body_text` coordinates, the 200-span cap, the fields bag's consumed
posture (the edited item's own field refs read the draft overlaid on the
saved fields; cross-item refs read saved), and -- the property the whole
read-only design rests on -- the pass leaves the project, every item, and
the disk untouched.
The fidelity pin is the oracle test: the same text through
`loader.load_readonly(overlay=...)` (a real full build) must report exactly
what the narrow pass reported.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import build as build_mod
from refdes import inline_calc, parse
from refdes.schema import load_project

CONFIG = (
    "site: { title: T, out: _site }\n"
    "sigfigs: 4\n"
    "types:\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      citations: { type: citations, on_change: invalidate }\n"
    "  req:\n"
    "    prefix: REQ\n"
    "    fields: {}\n"
)
CSV = "key,value,note\nrail_load,1.85,mW budget\n"

# One line with an ok span, a stale span and a half-typed span (no result
# slot) -- the panel's three live states.
OK_STALE = (
    "Rail `Vout := 2.218 V * 2 = 4.436 V` stale `Vbad := 2 V * 2 = 5 V` "
    "half `Vhalf := 3 V *`\n"
)


def _setup(tmp_path, *, config=CONFIG, dec_body="Baseline.\n", dec_cite=False):
    write_project_config(tmp_path, config)
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "budget.csv").write_text(CSV, encoding="utf-8", newline="")
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    cite = "citations:\n  - path: analysis/budget.csv\n" if dec_cite else ""
    (items / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n{cite}---\n\n{dec_body}", encoding="utf-8"
    )
    (items / "src.md").write_text(
        "---\nid: REQ-001\ntype: req\n---\n\n```calc\nV_in = 5.1 V\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def _build(tmp_path, **kw):
    _setup(tmp_path, **kw)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def _dec(project):
    return next(item for item in project.local_items if item.id == "DEC-001")


def _preview(project, text, **kw):
    return build_mod.preview_inline_spans(project, _dec(project), text, **kw)


def _inline_diags(project, item_id="DEC-001"):
    return [
        (d.level, d.message)
        for d in project.diagnostics
        if d.item_id == item_id and d.message.startswith("inline calc")
    ]


# ------------------------------------------------------- the status contract


def test_ok_stale_and_missing_result_rows(tmp_path):
    rows = _preview(_build(tmp_path), OK_STALE)
    assert rows == [
        {
            "line": 0, "start": 6, "end": 35, "result_start": 28, "result_end": 35,
            "name": "Vout", "status": "ok", "computed": "4.436 V", "message": "",
        },
        {
            "line": 0, "start": 44, "end": 65, "result_start": 62, "result_end": 65,
            "name": "Vbad", "status": "stale", "computed": "4 V",
            "message": "inline calc Vbad: stored result says 5 V, now computes 4 V",
        },
        {
            "line": 0, "start": 73, "end": 87,
            "name": "Vhalf := 3 V *", "status": "error", "computed": "",
            "message": "inline calc Vhalf := 3 V *: stored result missing; write '= <quantity>'",
        },
    ]
    # A span with no parseable result slot has no result range at all: the
    # browser's auto-fill/Fill are then unavailable for it (§3.3).
    assert "result_start" not in rows[2] and "result_end" not in rows[2]


def test_status_and_messages_are_what_the_real_build_reports(tmp_path):
    # The fidelity pin at unit level: run the same draft text through the
    # real build (written to disk) and compare diagnostics verbatim.
    text = (
        OK_STALE
        + "Cross `Vref := REQ-001.V_in = 5.1 V`\n"
        + 'Src `P := source("analysis/budget.csv", "rail_load") | W = 1.85 W`\n'
    )
    rows = _preview(_build(tmp_path), text)
    (tmp_path / "items" / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n{text}", encoding="utf-8"
    )
    built = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(built)
    build_mod.build(built)
    assert [r["message"] for r in rows if r["message"]] == [
        message for _level, message in _inline_diags(built)
    ]
    # Evaluated ok/stale spans land in the build's own calc_values.
    calc_values = _dec(built).calc_values
    assert calc_values["Vout"] == "4.436 V"
    assert calc_values["Vbad"] == "4 V"
    assert calc_values["Vref"] == "5.1 V"
    assert [r["status"] for r in rows] == ["ok", "stale", "error", "ok", "error"]


def test_computed_text_uses_project_sigfigs(tmp_path):
    # The preview's `computed` is `format_value(value, project.sigfigs)`:
    # the same span computes `4.44 V` in a 3-sigfig project and `4.436 V`
    # in the default 4. The stored literal's precision window (0.005 about
    # `4.44`) admits 4.436 in both -- the §3.5 ok-within-window posture --
    # so only `computed` can prove the project's sigfigs is the one used.
    project = _build(tmp_path, config=CONFIG.replace("sigfigs: 4", "sigfigs: 3"))
    rows = _preview(project, "`Vout := 2.218 V * 2 = 4.44 V`\n")
    assert rows[0]["status"] == "ok"
    assert rows[0]["computed"] == "4.44 V"
    default = _build(tmp_path)
    rows = _preview(default, "`Vout := 2.218 V * 2 = 4.44 V`\n")
    assert rows[0]["computed"] == "4.436 V"
    assert rows[0]["status"] == "ok"


# ---------------------------------------------------------------- positions


def test_ranges_are_body_coordinates_after_fences_and_tab_delimiters(tmp_path):
    # A fence on the path shifts the span's body line; the span's RHS is a
    # fence name (so a preview that skipped fences could not evaluate it);
    # the result separator is tab-flanked.
    text = (
        "intro\n"
        "```calc\n"
        "K = 2 V\n"
        "```\n"
        "Span `Vout := K * 2 =\t4 V` tail\n"
    )
    rows = _preview(_build(tmp_path), text)
    assert len(rows) == 1
    row = rows[0]
    line = text.splitlines()[4]
    assert (row["line"], row["start"], row["end"]) == (4, 6, 25)
    assert line[row["start"]:row["end"]] == "Vout := K * 2 =\t4 V"
    assert line[row["result_start"]:row["result_end"]] == "4 V"
    assert row["status"] == "ok" and row["computed"] == "4 V"


def test_two_spans_on_one_line_get_their_own_ranges(tmp_path):
    text = "`A := 1 V = 1 V` mid `B := 2 V = 2 V`\n"
    rows = _preview(_build(tmp_path), text)
    line = text.splitlines()[0]
    ranges = inline_calc.code_span_ranges(line)
    assert [(r["start"], r["end"]) for r in rows] == ranges
    assert [r["name"] for r in rows] == ["A", "B"]
    for row in rows:
        assert line[row["start"]:row["end"]].strip().startswith(row["name"])
        assert line[row["result_start"]:row["result_end"]] == row["computed"]


# ------------------------------------------------------------ live errors


def test_duplicate_name_fires_live(tmp_path):
    # Same item, same name: the fence assigns `I`, the span re-assigns it.
    # The build reports this as an inline calc error; the panel must show
    # it while the author types, not only at save.
    text = "```calc\nI = 2 A\n```\nDup `I := 3 A = 3 A`\n"
    rows = _preview(_build(tmp_path), text)
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["line"] == 3
    assert "'I' is assigned twice" in rows[0]["message"]


def test_dup_name_line_numbers_are_body_relative(tmp_path):
    # The one message divergence from the build, pinned (review, slice A):
    # the build embeds FILE line numbers (front matter offsets them), the
    # preview embeds BODY-relative ones -- the panel's coordinate space.
    # Everything else about the message is verbatim, including the fix
    # suggestion, so only the numbers may differ.
    text = "```calc\nI = 2 A\n```\nDup `I := 3 A = 3 A`\n"
    rows = _preview(_build(tmp_path), text)
    assert len(rows) == 1 and rows[0]["status"] == "error"
    assert "first at line 2, again at line 4" in rows[0]["message"]
    (tmp_path / "items" / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n{text}", encoding="utf-8"
    )
    built = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(built)
    build_mod.build(built)
    build_messages = [
        d.message
        for d in built.diagnostics
        if d.item_id == "DEC-001" and "assigned twice" in d.message
    ]
    assert len(build_messages) == 1
    # front matter (6 lines) shifts every number by 5: same message, file
    # coordinates.
    assert build_messages[0] == rows[0]["message"].replace("line 2", "line 7").replace(
        "line 4", "line 9"
    )
    assert "first at line 7, again at line 9" in build_messages[0]


def test_build_warnings_are_not_surfaced(tmp_path):
    # The row schema is three-status: `evaluate_block` warnings (here the
    # unit-collision warning the build reports as an `inline calc` WARNING)
    # are deliberately not surfaced by the preview -- the span is fine to
    # evaluate, and the save/build diagnostics own warnings.
    text = "Collision `A := 0.5 A * 2 = 1 A` tail\n"
    rows = _preview(_build(tmp_path), text)
    assert rows[0]["status"] == "ok"
    assert rows[0]["computed"] == "1 A"
    assert rows[0]["message"] == ""
    (tmp_path / "items" / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n{text}", encoding="utf-8"
    )
    built = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(built)
    build_mod.build(built)
    warnings = [
        d.message
        for d in built.diagnostics
        if d.item_id == "DEC-001" and d.level == "warning" and "reads 'A' as a unit" in d.message
    ]
    assert len(warnings) == 1


def test_cross_item_reference_evaluates_from_the_snapshot(tmp_path):
    rows = _preview(_build(tmp_path), "`Vref := REQ-001.V_in = 5.1 V`\n")
    assert rows[0]["status"] == "ok"
    assert rows[0]["computed"] == "5.1 V"


def test_source_refusal_message_is_the_builds(tmp_path):
    rows = _preview(
        _build(tmp_path), '`P := source("analysis/budget.csv", "rail_load") | W = 1.85 W`\n'
    )
    assert rows[0]["status"] == "error"
    assert "does not cite" in rows[0]["message"]
    assert rows[0]["message"].startswith("inline calc P: source(")


def test_source_cited_but_unpinned_carries_the_fetch_advice(tmp_path):
    project = _build(tmp_path, dec_cite=True)
    rows = _preview(
        project, '`P := source("analysis/budget.csv", "rail_load") | W = 1.85 W`\n'
    )
    assert rows[0]["status"] == "error"
    assert "has no locked value" in rows[0]["message"]
    assert "refdes fetch --path analysis/budget.csv" in rows[0]["message"]


# -------------------------------------------------------------- the guards


def test_cap_stops_at_span_limit(tmp_path):
    text = "".join(f"`A{i} := 1 V = 1 V`\n" for i in range(201))
    rows = _preview(_build(tmp_path), text)
    assert build_mod.PREVIEW_SPAN_LIMIT == 200
    assert len(rows) == 200
    assert rows[0]["name"] == "A0" and rows[-1]["name"] == "A199"


def test_fields_bag_carries_no_effect_for_this_fixture(tmp_path):
    # This fixture's DEC-001 declares no fields: every bag key is undeclared,
    # so the consumed bag changes nothing here (the unit layer accepts any
    # value shape -- the scalar rule is the ROUTE's, tested in
    # test_serve_calc_preview.py). The bag's real effect lives in the
    # field-reference section below.
    project = _build(tmp_path)
    rows = _preview(project, OK_STALE)
    assert _preview(project, OK_STALE, fields={}) == rows
    assert _preview(project, OK_STALE, fields={"anything": 5, "n": None}) == rows


# -------------------------------------------------- the draft field bag (G1)
#
# Design §3.2/§3.3 (in-prog-logs/inline-calc-live-editor-design-20261020.md):
# a span of the EDITED item that names its own field (`DEC-001.$rds_on`)
# reads the draft bag overlaid on the saved fields -- the unsaved edit is
# what the panel must compute with. Cross-item `$` references keep reading
# the saved target. Error vocabulary is the build's verbatim (empty field,
# non-quantity, unit assertion, non-identifier name with the declared-fields
# listing); the differential test below pins the agreement with `check`.

FIELD_CONFIG = (
    "site: { title: T, out: _site }\n"
    "sigfigs: 4\n"
    "types:\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      rds_on: { type: text }\n"
    "      limit: { type: text }\n"
    "      V_in: { type: text }\n"
    "      blank: { type: text }\n"
    "      tags: { type: list }\n"
    "      rds-on: { type: text }\n"
    "  req:\n"
    "    prefix: REQ\n"
    "    fields:\n"
    "      V_in: { type: text }\n"
    "      limit: { type: text }\n"
)


def _setup_fields(tmp_path):
    """DEC-001 saves `rds_on: 18 mohm`, `limit: 5 V` (blank/V_in/tags/rds-on
    declared, unsaved). REQ-001 saves `V_in: 3.3 V` AND fences a calc
    `V_in = 5.1 V` -- the collision target for the bare-reference case."""
    write_project_config(tmp_path, FIELD_CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\nrds_on: 18 mohm\nlimit: 5 V\n"
        "---\n\nBaseline.\n",
        encoding="utf-8",
    )
    (items / "req.md").write_text(
        "---\nid: REQ-001\ntype: req\nV_in: 3.3 V\n---\n\n"
        "```calc\nV_in = 5.1 V\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def _preview_dec(project, text, **kw):
    item = next(i for i in project.local_items if i.id == "DEC-001")
    return build_mod.preview_inline_spans(project, item, text, **kw)


def test_own_field_ref_reads_the_draft_bag(tmp_path):
    project = _setup_fields(tmp_path)
    text = "Draught `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"
    assert _preview_dec(project, text)[0]["status"] == "ok"
    rows = _preview_dec(project, text, fields={"rds_on": "20 mohm"})
    assert rows[0]["status"] == "stale"
    assert rows[0]["computed"] == "20 m\u03a9"
    assert rows[0]["message"] == (
        "inline calc Rds: stored result says 18 mohm, now computes 20 m\u03a9"
    )


def test_draft_only_value_feeds_a_blank_field(tmp_path):
    # `blank` is declared and unsaved: the saved item gives the empty-field
    # error; the draft value feeds the span.
    project = _setup_fields(tmp_path)
    text = "Fill `B := DEC-001.$blank | V = 3 V`\n"
    saved = _preview_dec(project, text)
    assert saved[0]["status"] == "error"
    assert "is empty -- give it a quantity" in saved[0]["message"]
    rows = _preview_dec(project, text, fields={"blank": "3 V"})
    assert rows[0]["status"] == "ok"
    assert rows[0]["computed"] == "3 V"


def test_cleared_in_the_draft_is_the_empty_error(tmp_path):
    # The form writes "" for a cleared input: overlaying it over a SAVED
    # value must give the same empty-field error a saved-empty item reports
    # (the differential test pins the check parity).
    project = _setup_fields(tmp_path)
    text = "Cleared `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"
    rows = _preview_dec(project, text, fields={"rds_on": ""})
    assert rows[0]["status"] == "error"
    assert "'rds_on' is empty -- give it a quantity" in rows[0]["message"]
    rows = _preview_dec(project, text, fields={"rds_on": "   "})
    assert "is empty -- give it a quantity" in rows[0]["message"]


def test_non_quantity_draft_field_names_the_field(tmp_path):
    project = _setup_fields(tmp_path)
    text = "Text `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"
    rows = _preview_dec(project, text, fields={"rds_on": "approved"})
    assert rows[0]["status"] == "error"
    assert "'rds_on' is 'approved', not a quantity" in rows[0]["message"]


def test_unit_assertion_against_a_draft_field(tmp_path):
    project = _setup_fields(tmp_path)
    text = "Unit `L := DEC-001.$limit | V = 5 V`\n"
    rows = _preview_dec(project, text, fields={"limit": "18 mohm"})
    assert rows[0]["status"] == "error"
    assert "declared as V" in rows[0]["message"]


def test_hyphenated_field_error_lists_declared_fields(tmp_path):
    # The preview must carry the declared-fields listing the check pass
    # appends (calc.FIELD_FIELDS_KEY): same suffix, identifier-style names
    # only, sorted.
    project = _setup_fields(tmp_path)
    text = "Hyphen `R := DEC-001.$rds-on | mohm = 18 mohm`\n"
    rows = _preview_dec(project, text)
    assert rows[0]["status"] == "error"
    assert "cannot be referenced with $" in rows[0]["message"]
    assert "the item type declares: V_in, blank, limit, rds_on, tags" in (
        rows[0]["message"]
    )


def test_cross_item_field_ref_reads_the_saved_target(tmp_path):
    # The bag is the EDITED item's fields: REQ-001.$V_in keeps reading the
    # saved REQ-001 even when the bag carries a same-named key.
    project = _setup_fields(tmp_path)
    text = "Cross `V := REQ-001.$V_in | V = 3.3 V`\n"
    rows = _preview_dec(project, text, fields={"V_in": "99 V"})
    assert rows[0]["status"] == "ok"
    assert rows[0]["computed"] == "3.3 V"


def test_collision_reference_computes_the_calc_value(tmp_path):
    # REQ-001 has a calc V_in (5.1 V) AND a field V_in (3.3 V): the bare
    # reference reads the calc value; the collision WARNING is not surfaced
    # by the three-status row (the check pass agrees on the VALUE -- the
    # differential test pins that, and shows the WARNING there).
    project = _setup_fields(tmp_path)
    text = "Coll `V := REQ-001.V_in = 5.1 V`\n"
    rows = _preview_dec(project, text, fields={"V_in": "7.7 V"})
    assert rows[0]["status"] == "ok"
    assert rows[0]["computed"] == "5.1 V"
    assert rows[0]["message"] == ""


def test_undeclared_bag_keys_are_ignored(tmp_path):
    project = _setup_fields(tmp_path)
    text = "Rail `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"
    assert _preview_dec(project, text, fields={"nope": "5 V", "id": "X"}) == (
        _preview_dec(project, text)
    )


def test_bag_does_not_mutate_the_project(tmp_path):
    project = _setup_fields(tmp_path)
    dec = next(i for i in project.local_items if i.id == "DEC-001")
    saved_fields = dict(dec.fields)
    diags_before = list(project.diagnostics)
    text = "Draught `Rds := DEC-001.$rds_on | mohm = 20 mohm`\n"
    for _ in range(3):
        _preview_dec(
            project, text, fields={"rds_on": "20 mohm", "blank": "1 V"}
        )
    assert dec.fields == saved_fields
    assert project.diagnostics == diags_before


# The matrix: (draft bag, one-span body). Preview-with-bag vs. the same
# fields SAVED to disk and built -- the §3.3/§6.5 parity claim.
DIFFERENTIAL = [
    ({"rds_on": "20 mohm"}, "Draught `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"),
    ({"blank": "3 V"}, "Fill `B := DEC-001.$blank | V = 3 V`\n"),
    ({"rds_on": ""}, "Cleared `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"),
    ({"rds_on": "   "}, "Ws `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"),
    ({"rds_on": "approved"}, "Text `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"),
    ({"limit": "18 mohm"}, "Unit `L := DEC-001.$limit | V = 5 V`\n"),
    ({}, "Hyphen `R := DEC-001.$rds-on | mohm = 18 mohm`\n"),
    ({"V_in": "99 V"}, "Cross `V := REQ-001.$V_in | V = 3.3 V`\n"),
    ({"V_in": "7.7 V"}, "Coll `V := REQ-001.V_in = 5.1 V`\n"),
    ({"nope": "5 V"}, "Rail `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"),
    ({"rds_on": "1e999 mohm"}, "Big `Rds := DEC-001.$rds_on | mohm = 18 mohm`\n"),
]


def test_preview_with_bag_equals_check_after_saving_the_same_fields(tmp_path):
    # G1's parity claim, per case and per row: an ok row's `computed` IS the
    # built item's calc value verbatim; a stale row's message is the build's
    # WARNING verbatim; an error row's message is the build's ERROR verbatim.
    # The collision WARNING stays the build's (three-status rows, pinned
    # above), and the collision row is an ok row here -- agreeing on value.
    for index, (bag, text) in enumerate(DIFFERENTIAL):
        root = tmp_path / f"case{index}"
        root.mkdir()
        project = _setup_fields(root)
        rows = _preview_dec(project, text, fields=bag)
        assert len(rows) == 1, (bag, text, rows)
        row = rows[0]

        saved = {"rds_on": "18 mohm", "limit": "5 V"} | bag
        lines = ["id: DEC-001", "type: decision"]
        for name in ("rds_on", "limit", "V_in", "blank", "rds-on"):
            if name in saved:
                value = str(saved[name])
                lines.append(f"{name}: {value}" if value.strip() else f"{name}:")
        (root / "items" / "dec.md").write_text(
            "---\n" + "\n".join(lines) + "\n---\n\n" + text, encoding="utf-8"
        )
        built = load_project(config_path=str(root / "refdes-project.yaml"))
        parse.load_items(built)
        build_mod.build(built)
        dec = next(i for i in built.local_items if i.id == "DEC-001")
        label_diags = [
            (d.level, d.message)
            for d in built.diagnostics
            if d.item_id == "DEC-001"
            and d.message.startswith(f"inline calc {row['name']}: ")
        ]
        if row["status"] == "ok":
            assert dec.calc_values.get(row["name"]) == row["computed"], (
                bag, text, row, label_diags
            )
            assert [
                m for lvl, m in label_diags if lvl == "error"
            ] == [], (bag, text, row, label_diags)
        else:
            expected = "error" if row["status"] == "error" else "warning"
            assert (expected, row["message"]) in label_diags, (
                bag, text, row, label_diags
            )


# ----------------------------------------------------------- read-only

def _state(project):
    items = tuple(
        (
            item.id,
            tuple(
                sorted(
                    (name, str(value))
                    for name, value in (getattr(item, "_env", {}) or {}).items()
                )
            ),
            tuple(sorted(item.calc_values.items())),
            len(item.calcs),
            tuple(getattr(item, "_source_uses", [])),
            getattr(item, "_calc_failed", None),
        )
        for item in project.local_items
    )
    diags = tuple((d.level, d.message, d.file, d.line, d.item_id) for d in project.diagnostics)
    lock = getattr(project, "_source_lock", "<none>")
    return items, diags, lock


def test_preview_mutates_nothing(tmp_path):
    # The §5 posture: a snapshot of every mutable per-item surface (env
    # names AND values, calc_values, calcs, source uses, failure flag), the
    # diagnostics list and the memoised lockfile, compared before and after
    # ten preview calls that exercise every live state at once.
    project = _build(tmp_path, dec_cite=True)
    text = (
        OK_STALE
        + "Cross `Vref := REQ-001.V_in = 5.1 V`\n"
        + "```calc\nK = 2 V\n```\n"
        + '`P := source("analysis/budget.csv", "rail_load") | W = 1.85 W`\n'
        + "Dup `K := 3 V = 3 V`\n"
    )
    files_before = {
        path.name: path.read_bytes()
        for path in (tmp_path / "items").glob("*")
    }
    before = _state(project)
    for _ in range(10):
        rows = _preview(project, text)
    assert _state(project) == before
    assert {path.name: path.read_bytes() for path in (tmp_path / "items").glob("*")} == files_before
    assert len(rows) == 6  # the pass ran every time -- and changed nothing
