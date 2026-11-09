"""Finding F16-2 of the run-16 user-sim: an id-less thread tip is not savable.

A thread tip that carries an artifact `key:` and NO `id:` is exactly the tip
`links.composite_for` writes no composite for (src/refdes/links.py:319: a
composite is `DISPLAY-ID@key` -- it needs both halves), so
`POST /api/item/<ref>/continue` refuses it (`serve/edit.py`'s `_continue_locked`
at the `composite_for` call: "…carries no artifact key, so no DISPLAY-ID@key
composite can be written for it…"). Two halves of the same lie:

* the PANE handed the browser a save context for that tip anyway --
  `_pane_save_context` gated on the key alone, so the panel carried
  `data-refdes-tip-key`/`data-refdes-revision` for a save the endpoint can
  only ever refuse. The fix: the gate names a context only for a tip a save
  can be written for -- key AND id -- and an id-less tip's ticks stay
  preview-only through the path W5b.4c's markup already has (a panel with no
  key/revision is preview-only and says so, tick-pane.js `panelFromRows`);
* the REFUSAL's subject was the tip's display id, which an id-less tip does
  not have, so the message rendered with an empty subject ("refused:  carries
  no artifact key" -- the double space IS the empty id). The fix: an id-less
  tip is named by the only identity it carries, its key.

The controls that keep both fixes honest: a tip WITH an id in the same cold
project keeps its save context and its 200 -- the absence in the first test
is the missing id, not a pane that names nothing, and the key in the second
is the label, not a refusal that grew teeth.

The keys are `keys.mint()`-real (the corruption lint refuses an authored
malformed one the moment a save writes it), and the project is served COLD
(no writable load): bare `follows:` stays unfrozen and the tip's id absence
is real -- the state the finding was seen in.
"""

from __future__ import annotations

import hashlib
import re

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes import keys as keys_mod
from refdes.serve.server import EditorApp

TIP_KEY_ATTR = "data-refdes-tip-key"
REVISION_ATTR = "data-refdes-revision"

# Thread A (the F16-2 shape): a forked-free thread whose tip carries a key
# and no `id:` -- the pane labels it by key (threads.entry_label).
THREAD_IDLESS = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - key: {key}\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model the copper temperature., state: open}\n"
)

# Thread B (the control, same project, same cold load): the same shape with
# an id-bearing, keyed tip.
THREAD_KEYED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-101\n"
    "    summary: Rail work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-102\n"
    "    key: {key}\n"
    "    summary: Rail work continues.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-101\n"
    "    tasks:\n"
    "      - {id: T-rail, text: Settle the rail budget., state: open}\n"
)

PANEL_TAG = re.compile(r'<div class="refdes-taskpane-panel"[^>]*>')
ATTR_PAIR = re.compile(r'([\w-]+)="([^"]*)"')
TIP_ATTR = re.compile(r'data-refdes-tip="([^"]*)"')


def _write_files(root, files):
    """The project, written as bytes (R1: no text-mode write of a fixture)."""
    write_project_config(
        root,
        "site: { title: Idless Tip, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = root / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_bytes(text.encode("utf-8"))
    return str(root / "refdes-project.yaml")


@pytest.fixture
def served(tmp_path):
    """Both threads, cold-served, with minted keys authored in. Yields
    (app, client, root, idless_key, keyed_key): the tests address the
    id-less tip by its key, its only spelling."""
    idless_key = keys_mod.mint()
    keyed_key = keys_mod.mint()
    config = _write_files(
        tmp_path,
        {
            # replace, not format: the YAML's flow mappings own `{}`
            "log-a.yaml": THREAD_IDLESS.replace("{key}", idless_key),
            "log-b.yaml": THREAD_KEYED.replace("{key}", keyed_key),
        },
    )
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        yield app, Client(app), tmp_path, idless_key, keyed_key
    finally:
        app.stop()


def _body(client, app, item_id: str) -> str:
    status, _h, body = client.page(
        f"/preview/{app.state.snapshot.project.item_by_id(item_id).slug}.html"
    )
    assert status == 200
    return body.decode("utf-8")


def pane(html_text: str) -> str:
    """The pane's own markup (the `test_task_pane.py` extractor, same marker)."""
    start = html_text.find('<aside class="refdes-taskpane"')
    if start < 0:
        return ""
    return html_text[start : html_text.find("</aside>", start)]


def _panel(markup: str) -> dict:
    """The single tip panel's attributes (each thread here is forked-free:
    exactly one panel per pane)."""
    (tag,) = PANEL_TAG.findall(markup)
    return dict(ATTR_PAIR.findall(tag))


def _sha(path) -> str:
    """sha256 of a file's bytes, computed here: the definition `file_revision`
    documents, independent of any refdes helper."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_an_id_less_tip_panel_carries_no_save_context(served):
    """The pane half of the finding. The id-less tip's panel keeps its
    checkboxes (the ticks are real; a panel without the save attributes is
    preview-only and says so through the existing `panelFromRows` path) and
    names NO key and NO revision. The control rides the same fixture: the
    id-bearing tip's page names BOTH, so the absence is the missing id and
    not a pane that decorates nothing."""
    app, client, root, idless_key, keyed_key = served
    body = pane(_body(client, app, "LOG-001"))
    assert body  # the pane is there, and the page is a 200
    assert set(TIP_ATTR.findall(body)) == {idless_key}  # the panel IS its tip
    assert "<input" in body  # the ticks stay (W5b.3's control, preview-only)
    panel = _panel(body)
    assert TIP_KEY_ATTR not in panel
    assert REVISION_ATTR not in panel
    control = _panel(pane(_body(client, app, "LOG-101")))
    assert control[TIP_KEY_ATTR] == keyed_key
    assert control[REVISION_ATTR] == _sha(root / "items" / "log-b.yaml")


def test_the_endpoints_refusal_for_the_id_less_tip_names_the_key(served):
    """The endpoint half of the finding, at the HTTP face: the save the pane
    used to offer is a 422 refusal, and its text names the tip by the key
    -- the only identity an id-less tip carries -- instead of rendering an
    empty subject (the old message opened on "refused:  ", the double space
    being the missing display id). The refusal leaves the bytes untouched."""
    app, client, root, idless_key, _keyed_key = served
    thread_file = root / "items" / "log-a.yaml"
    before = thread_file.read_bytes()
    status, payload = client.api_post(
        f"/api/item/{idless_key}/continue",
        {
            "ticks": [["T-thermal-model", "done"]],
            "expected_revision": _sha(thread_file),
        },
    )
    assert status == 422 and payload["kind"] == "refused", payload
    message = payload["message"]
    assert idless_key in message, message
    assert "carries no artifact key" in message, message
    assert not message.startswith("refused:  "), message
    assert payload["reason"] == message.removeprefix("refused: ")
    assert thread_file.read_bytes() == before


def test_an_id_bearing_tip_keeps_its_context_and_its_200(served):
    """The unchanged control at the endpoint: the id-bearing keyed tip's
    panel carries the pair, and posting with the markup's revision applies
    -- the continuation's `follows:` names the tip by its composite, which
    is precisely what the id-less tip cannot get."""
    app, client, root, _idless_key, keyed_key = served
    thread_file = root / "items" / "log-b.yaml"
    panel = _panel(pane(_body(client, app, "LOG-101")))
    revision = panel[REVISION_ATTR]
    assert panel[TIP_KEY_ATTR] == keyed_key
    status, payload = client.api_post(
        "/api/item/LOG-102/continue",
        {"ticks": [["T-rail", "done"]], "expected_revision": revision},
    )
    assert status == 200 and payload["kind"] == "applied", payload
    written = thread_file.read_bytes().decode("utf-8")
    assert f"follows: [LOG-102@{keyed_key}]" in written  # the composite, not a bare half
