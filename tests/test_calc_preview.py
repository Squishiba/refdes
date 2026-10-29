"""The live editor's read-only calc preview pass: `build.preview_inline_spans`
(docs/design/inline-calc-live-editor-design.md §3.4, slice A/B1).

The route is the pass's only caller, so the unit tests are the contract:
status/message parity with the real build (the panel teaches `refdes check`'s
vocabulary, never a second one), `computed` at the project's sigfigs, ranges
in `body_text` coordinates, the 200-span cap, the fields bag's
accepted-and-unused posture, and -- the property the whole read-only design
rests on -- the pass leaves the project, every item, and the disk untouched.
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
DEC_MD = "items/dec.md"

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


def test_fields_bag_is_inert(tmp_path):
    # §3.4 accepted-and-unused, pinned until the field-reference slice (G1)
    # lands: the bag is carried, never consulted.
    project = _build(tmp_path)
    rows = _preview(project, OK_STALE)
    assert _preview(project, OK_STALE, fields={}) == rows
    assert _preview(project, OK_STALE, fields={"anything": 5, "n": None}) == rows


# ----------------------------------------------------------- read-only

def _state(project):
    items = tuple(
        (
            item.id,
            tuple(sorted(getattr(item, "_env", {}) or {})),
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
    # The §5 posture: env/diag snapshot of the project, compared before and
    # after ten preview calls that exercise every live state at once.
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
