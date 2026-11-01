"""The refdes-row skeletons the format bar inserts (slice 2, design §H-4).

The bar's inline-span and calc-fence skeletons are DECIDED to fail the build
on purpose: "the author cannot forget to fill it in". That decision is only
true while the inserted strings are the measured strings, so this file pins
them from ONE place -- the constants exported by the real served
``formatbar.js`` -- and runs THOSE strings through the real loader/build, the
real save gate, and the real calc-preview route. Changing a skeleton string
in the JS changes what the build messages below must say, and the pins move
together; changing one alone fails.

Measured messages (design §H-4, re-measured on this tree):
- span `` `name := 0 | V` `` -> ``inline calc name := 0 | V: stored result
  missing; write '= <quantity>'`` (ERROR at the item's source line),
- fence ```` ```calc / name = expr | V / ``` ```` -> ``calc 'name': unknown
  name 'expr'`` (ERROR at the item's source line).
Postures: build = ``loader.load_readonly`` (the oracle of
``test_serve_calc_preview.py``); save gate and panel row =
``serve_support.Client`` on a live ``EditorApp``.
"""

from __future__ import annotations

import os
import re

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import loader
from refdes.serve.server import EditorApp

STATIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "refdes",
    "serve",
    "static",
)

SPAN_MESSAGE = "inline calc name := 0 | V: stored result missing; write '= <quantity>'"
FENCE_MESSAGE = "calc 'name': unknown name 'expr'"

SCHEMA = """\
site:
  title: "Skeleton pin"
id:
  width: 3
types:
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
"""

DECS = """\
defaults: { type: decision }
items:
  - id: DEC-001
    title: Use the buck regulator.
    body: |
      Baseline prose.
"""


def js_export(name: str) -> str:
    """The value of `export const NAME = '...';` in formatbar.js, unescaped.
    This is the single source: the buttons and these pins read the same text."""
    with open(os.path.join(STATIC, "formatbar.js"), encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(
        rf"export const {name} = (['\"])((?:\\.|(?!\1).)*)\1;", text
    )
    assert match, f"formatbar.js must export the skeleton string {name}"
    return re.sub(
        r"\\(n|\\|'|`)",
        lambda m: {"n": "\n", "\\": "\\", "'": "'", "`": "`"}[m.group(1)],
        match.group(2),
    )


def body_yaml(body: str) -> str:
    indented = "".join("      " + line for line in body.splitlines(keepends=True))
    return (
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n"
        "    title: Use the buck regulator.\n"
        "    body: |\n" + indented
    )


def build_with_body(tmp_path, body: str):
    write_project_config(tmp_path, SCHEMA)
    (tmp_path / "items").mkdir(exist_ok=True)
    (tmp_path / "items" / "decs.yaml").write_text(
        body_yaml(body), encoding="utf-8", newline="\n"
    )
    project = loader.load_readonly(str(tmp_path / "refdes-project.yaml"))
    item = next(i for i in project.local_items if i.id == "DEC-001")
    diags = [
        d
        for d in project.diagnostics
        if d.item_id == "DEC-001" and d.level == "error"
    ]
    return project, item, diags


# ------------------------------------------------------- the pinned strings

def test_the_skeleton_strings_are_the_measured_ones():
    assert js_export("SPAN_SKELETON") == "`name := 0 | V`"
    assert js_export("FENCE_SKELETON") == "```calc\nname = expr | V\n```"
    assert js_export("FIGURE_SKELETON") == "[[fig:]]"
    assert js_export("VALUE_SKELETON") == "{{}}"
    assert js_export("NAVI_SKELETON") == "<!--navi: text-->"


# ---------------------------------------------------- the build messages

def test_the_span_skeleton_is_the_measured_build_error(tmp_path):
    _project, item, diags = build_with_body(tmp_path, js_export("SPAN_SKELETON") + "\n")
    assert [d.message for d in diags] == [SPAN_MESSAGE], diags
    assert diags[0].line == item.source_line
    assert diags[0].file == "items/decs.yaml"


def test_the_fence_skeleton_is_the_measured_build_error(tmp_path):
    _project, item, diags = build_with_body(
        tmp_path, js_export("FENCE_SKELETON") + "\n"
    )
    assert [d.message for d in diags] == [FENCE_MESSAGE], diags
    assert diags[0].line == item.source_line


def test_the_figure_and_value_skeletons_stay_below_error(tmp_path):
    # Design §C: unresolved figure refs and values are warnings, not errors
    # -- the safe skeletons. (Pinned as no-error: the gate blocks errors.)
    _project, _item, diags = build_with_body(
        tmp_path, "See " + js_export("FIGURE_SKELETON") + " value " + js_export("VALUE_SKELETON") + ".\n"
    )
    assert diags == []


def test_the_navi_skeleton_is_a_recognised_marker(tmp_path):
    # A Navi is one closed, single-line `<!--navi:...-->` comment (the
    # navis.py grammar): the bar's skeleton must reach the real parser as a
    # RECOGNISED keyless marker -- builds with no error, scanned into the
    # item's navis with an empty key (a read-only load mints nothing). A
    # string the grammar would not accept scans to nothing and fails here.
    _project, item, diags = build_with_body(
        tmp_path, js_export("NAVI_SKELETON") + "\n"
    )
    assert diags == [], diags
    assert [n.text for n in item.navis] == ["text"], item.navis
    assert [n.key for n in item.navis] == [""], item.navis


# -------------------------------------------------------- the save gate

@pytest.fixture
def served(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "decs.yaml").write_text(DECS, encoding="utf-8", newline="\n")
    app = EditorApp(str(tmp_path / "refdes-project.yaml"), poll_interval=60)
    app.start()
    try:
        yield app, Client(app), tmp_path
    finally:
        app.stop()


def save(client, root, text):
    _status, view = client.api_get("/api/item/DEC-001")
    return client.api_post(
        "/api/item/DEC-001/edit",
        {"op": "set_body", "text": text, "expected_revision": view["edit"]["file_revision"]},
    )


def test_the_span_skeleton_is_blocked_and_lands_nothing(served):
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = save(client, root, js_export("SPAN_SKELETON") + "\n")
    assert status == 422, payload
    assert payload["kind"] == "invalid"
    assert SPAN_MESSAGE in payload["message"]
    assert any(d["message"] == SPAN_MESSAGE for d in payload["diagnostics"])
    assert snapshot_tree(root) == before, "a blocked save touched the project"


def test_the_fence_skeleton_is_blocked_and_lands_nothing(served):
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = save(client, root, js_export("FENCE_SKELETON") + "\n")
    assert status == 422, payload
    assert payload["kind"] == "invalid"
    assert FENCE_MESSAGE in payload["message"]
    assert any(d["message"] == FENCE_MESSAGE for d in payload["diagnostics"])
    assert snapshot_tree(root) == before, "a blocked save touched the project"


def test_the_completed_span_saves(served):
    # The author's fix: a real `= <quantity>` clears the gate (design §H-4).
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = save(client, root, "`name := 2 V * 2 | V = 4 V`\n")
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert snapshot_tree(root) != before
    _status, view = client.api_get("/api/item/DEC-001")
    assert "2 V * 2" in view["body"]


# ------------------------------------------------------ the panel row

def test_the_span_skeleton_panel_row_has_no_result_slot(served):
    # Design §H-4: the row renders as an error chip with the fix message;
    # NO result_start/result_end keys -> no auto-fill, no Fill.
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = client.api_post(
        "/api/item/DEC-001/calc", {"text": js_export("SPAN_SKELETON") + "\n"}
    )
    assert status == 200, payload
    assert len(payload["spans"]) == 1
    row = payload["spans"][0]
    assert row["name"] == "name := 0 | V"
    assert row["status"] == "error"
    assert row["computed"] == ""
    assert row["message"] == SPAN_MESSAGE
    assert "result_start" not in row and "result_end" not in row, row
    assert snapshot_tree(root) == before, "a preview request wrote to the project"


def test_the_fence_skeleton_is_panel_silent(served):
    # Fences are panel-silent: the save-time 422 owns fences (design §C).
    _app, client, _root = served
    status, payload = client.api_post(
        "/api/item/DEC-001/calc", {"text": js_export("FENCE_SKELETON") + "\n"}
    )
    assert status == 200, payload
    assert payload["spans"] == []
