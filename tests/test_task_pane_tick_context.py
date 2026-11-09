"""Thread workbench W5b.4a contract: the pane carries its save context.

Plan §4 W5b.4 (docs/design/thread-workbench-w5b-plan.md:313) opens with
"the save button posts the W5b.2 request with the revision the pane was
rendered at". W5b.4a is the server-side half of that one sentence, landed
before the draft module exists: the interactive preview pane names both
halves of the save identity on each tip's panel --

    <div class="refdes-taskpane-panel" data-refdes-panel="1"
         data-refdes-tip-key="<the tip item's key>"
         data-refdes-revision="<the file revision the save compares>">

so a W5b.4 draft can never have to guess which thread it belongs to (the
key) or which bytes the save will be compared against (the revision).

`data-refdes-tip-key` is the tip item's artifact `key` (docs/design/keys.md):
stable across renames, which is exactly why the display id in the existing
`data-refdes-tip` is not enough for a draft that outlives a reload.

`data-refdes-revision` is EXACTLY what the save compares. `serve.edit.file_revision`
is sha256 of the file's bytes (src/refdes/serve/edit.py:314), and
`continue_thread` compares the sha256 of the TIP item's source file
(`_item_path(before, tip)` at edit.py:2457, hashed at :2524) -- not the
viewed entry's file, not anything computed in the pane model. That is the
distinction this file is written to keep: the markup must carry the tip's
file revision, so a draft built from the markup and posted to
`POST /api/item/<ref>/continue` gets `Applied` while the file stands and
`Conflict` the moment ANYONE moves it -- pinned as a live round trip, not
as a spelling check.

The seam stays serve-response-only, the W5b.3 rule (R3/Q9): `refdes build`
and the preview generation on disk carry neither attribute, and the pane on
disk stays byte-identical to what build wrote. A tip with no key renders the
read-only glyph rows -- W5b.3 gave it no checkboxes, so there is no save
context to name. `--no-write` is pinned conservative exactly as W5b.3 pinned
it: no controls, and so no context, while its writable twin ships all three.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import time

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes import cli as cli_mod
from refdes import parse
from refdes.schema import load_project
from refdes.serve import edit as edit_mod
from refdes.serve.server import EditorApp

TIP_KEY_ATTR = "data-refdes-tip-key"
REVISION_ATTR = "data-refdes-revision"
TICK_MODULE = "taskpane-ticks.js"

# A one-tip thread: LOG-001 is the head, LOG-002 the tip whose file every
# save against this thread compares (all entries live in items/log.yaml).
ONE_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model the copper temperature., state: open}\n"
    "      - {id: T-input-range, text: Check the 36 V input case., state: done}\n"
)

# A real fork ACROSS TWO FILES: each tip lives in its own file, so each
# panel's revision must be its own file's -- an implementation that hashed
# the viewed entry's file (or one file for all panels) passes a single-file
# fixture and fails this one.
FORK_HEAD = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-002\n"
    "    summary: Thermal branch.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-thermal, text: Model the copper temperature., state: open}\n"
)
FORK_SIDE = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-003\n"
    "    summary: Decoupling branch.\n"
    "    date: 2026-09-03\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-decoupling, text: Recheck decoupling near U14., state: open}\n"
)

# An authored key (no writable load has run, so nothing minted a clean one):
# the value flows from YAML straight into the panel attribute, and the
# template's autoescaping is the only thing between it and the DOM.
HOSTILE = 'evil"><script>alert(1)</script>'
HOSTILE_KEY = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-002\n"
    f"    key: '{HOSTILE}'\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model the copper temperature., state: open}\n"
)

# A fork with one AUTHORED-KEY tip and one keyless tip, served cold (no
# writable load, so bare `follows:` stays unfrozen and the fork stands):
# the pane decorates the keyed tip's panel and names nothing on the
# keyless one, in the SAME response.
KEYED_TIP_KEY = "abc123keyed"
KEYED_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-002\n"
    f"    key: {KEYED_TIP_KEY}\n"
    "    summary: Thermal branch.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-thermal, text: Model the copper temperature., state: open}\n"
)
KEYLESS_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-003\n"
    "    summary: Decoupling branch.\n"
    "    date: 2026-09-03\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-decoupling, text: Recheck decoupling near U14., state: open}\n"
)

PANEL_TAG = re.compile(r'<div class="refdes-taskpane-panel"[^>]*>')
ATTR_PAIR = re.compile(r'([\w-]+)="([^"]*)"')
TIP_ATTR = re.compile(r'data-refdes-tip="([^"]*)"')


def _write_files(root, files):
    """The project, written as bytes (R1: no text-mode write of a fixture)."""
    write_project_config(
        root,
        "site: { title: Tick Context, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = root / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_bytes(text.encode("utf-8"))
    return str(root / "refdes-project.yaml")


def _warm(root, files):
    """Write the project, then ONE ordinary writable load: that is what
    mints every item's key (docs/design/keys.md), the state a real project
    is in by the time anyone serves it."""
    config = _write_files(root, files)
    assert cli_mod.main(["-c", config, "check"]) == 0
    return config


def _warm_served(root):
    return _warm(root, {"log.yaml": ONE_TIP})


def _fork(root):
    """FORK_HEAD/FORK_SIDE, warmed and de-chained: a writable load freezes
    each new `follows:` to the target's current tip, which turns the fork
    into LOG-001 -> LOG-002 -> LOG-003. Rewriting the second new edge to
    name the HEAD's key restores the fork -- the de-chain of
    test_task_pane_ticks.py::_write_fork_serve, across two files."""
    config = _warm(root, {"log.yaml": FORK_HEAD, "branch.yaml": FORK_SIDE})
    head_text = (root / "items" / "log.yaml").read_bytes().decode("utf-8")
    (head_key,) = re.findall(r"- key: (\S+)\n    id: LOG-001", head_text)
    branch_path = root / "items" / "branch.yaml"
    text = branch_path.read_bytes().decode("utf-8")
    text = re.sub(
        r"follows: LOG-\d+@\S+",
        f"follows: LOG-001@{head_key}",
        text,
        count=1,
    )
    branch_path.write_bytes(text.encode("utf-8"))
    return config


def _serve(config, read_only=False):
    app = EditorApp(config, poll_interval=0.05, read_only=read_only)
    app.start()
    try:
        yield app, Client(app)
    finally:
        app.stop()


@pytest.fixture
def served_warm(tmp_path_factory):
    yield from _serve(_warm_served(tmp_path_factory.mktemp("warm")))


@pytest.fixture
def served_fork(tmp_path):
    yield from _serve(_fork(tmp_path))


@pytest.fixture
def served_no_write(tmp_path_factory):
    yield from _serve(_warm_served(tmp_path_factory.mktemp("no-write")), read_only=True)


def _page_of(app, item_id: str) -> str:
    return app.state.snapshot.project.item_by_id(item_id).slug + ".html"


def _body(client, app, item_id: str) -> str:
    status, _h, body = client.page(f"/preview/{_page_of(app, item_id)}")
    assert status == 200
    return body.decode("utf-8")


def pane(html_text: str) -> str:
    """The pane's own markup, or "" when the page carries no pane (the
    `test_task_pane.py` extractor, same marker)."""
    start = html_text.find('<aside class="refdes-taskpane"')
    if start < 0:
        return ""
    return html_text[start : html_text.find("</aside>", start)]


def _panels(markup: str) -> list[dict]:
    """Every tip panel in `markup` as {attrs, slice}: the panel tag's
    attributes, and the pane markup that belongs to it (up to the next
    panel, the last one running to the end of the pane)."""
    tags = list(PANEL_TAG.finditer(markup))
    panels = []
    for i, tag in enumerate(tags):
        end = tags[i + 1].start() if i + 1 < len(tags) else len(markup)
        panels.append(
            {
                "attrs": dict(ATTR_PAIR.findall(tag.group(0))),
                "slice": markup[tag.start() : end],
            }
        )
    return panels


def _sha(path: str) -> str:
    """The revision, computed HERE and independently of any refdes helper:
    sha256 of the file's bytes, the definition `file_revision` documents."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _tip_file(project, tip_id: str) -> str:
    """The tip item's source file, spelled the way `_item_path` spells it
    (src/refdes/serve/edit.py:992): the root-joined source_file."""
    item = project.item_by_id(tip_id)
    assert item is not None and item.source_file
    return os.path.join(project.root, item.source_file.replace("/", os.sep))


def _fresh_project(app):
    """The project as a fresh read-only load sees it: the keys the mint
    wrote, without borrowing the server's live model."""
    project = load_project(config_path=str(app.state.config_path))
    parse.load_items(project)
    return project


def _walk_text(root: str):
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as fh:
                yield os.path.relpath(path, root).replace("\\", "/"), fh.read().decode(
                    "utf-8", errors="replace"
                )


# ---------------------------------------------------- the context IS the save's

def test_the_served_panel_names_the_tips_key_and_the_file_revision(served_warm):
    """W5b.4a's spelling, on every page of the thread: the panel carries
    the tip item's minted key and the sha256 of the tip item's file,
    computed here from bytes -- and the pair is response-only, so the
    generation on disk stays the published bytes (R3)."""
    app, client = served_warm
    project = _fresh_project(app)
    tip_path = _tip_file(project, "LOG-002")
    expected_key = project.item_by_id("LOG-002").key
    expected_rev = _sha(tip_path)
    assert expected_key and expected_rev  # the mint ran: the fixture is warm
    for item_id in ("LOG-001", "LOG-002"):  # the tip's panel on both pages (Q4)
        (panel,) = _panels(pane(_body(client, app, item_id)))
        assert panel["attrs"][TIP_KEY_ATTR] == expected_key
        assert panel["attrs"][REVISION_ATTR] == expected_rev
        # The attr rides every tickable row's checkbox (W5b.3 pins that), so
        # the panel IS its tip means: every value names it, and only it.
        assert set(TIP_ATTR.findall(panel["slice"])) == {"LOG-002"}
    with open(os.path.join(app.preview.current, "log-002.html"), encoding="utf-8") as fh:
        disk = pane(fh.read())
    assert TIP_KEY_ATTR not in disk  # response-only: the disk half of the R3 pair
    assert REVISION_ATTR not in disk


def test_the_markup_revision_is_the_revision_the_continue_endpoint_compares(served_warm):
    """The load-bearing test: a draft built ONLY from the markup's revision
    posts and applies; an unrelated edit to the same file (nothing the pane
    shows changed) moves the file; replaying with the markup's stale revision
    is a 409 Conflict whose current_revision is the file's new sha256. This
    is why the attribute exists: a W5b.4 draft built from it can never miss
    a move the server will catch."""
    app, client = served_warm
    (panel,) = _panels(pane(_body(client, app, "LOG-002")))
    rev0 = panel["attrs"][REVISION_ATTR]
    status, payload = client.api_post(
        "/api/item/LOG-002/continue",
        {"ticks": [["T-thermal-model", "done"]], "expected_revision": rev0},
    )
    assert status == 200 and payload["kind"] == "applied", payload
    root = app.state.snapshot.project.root
    log_path = os.path.join(root, "items", "log.yaml")
    assert payload["revision"] == _sha(log_path)
    # An unrelated author edits a DIFFERENT item in the same file: the pane
    # shows nothing new, and the tip's file revision moves.
    applied = edit_mod.apply_edit(
        root,
        edit_mod.EditRequest(
            who="other-author",
            ref="LOG-001",
            op=edit_mod.SetField("summary", "Power work list, reworded."),
            expected_revision=_sha(log_path),
        ),
        config_path=str(app.state.config_path),
    )
    assert isinstance(applied, edit_mod.Applied), applied.message
    moved = _sha(log_path)
    assert moved != rev0
    # The same stale revision, replayed with a tick that is legal at the
    # CURRENT tip (the first save's continuation carried T-thermal-model as
    # done, and done -> open is Q6-legal) -- the tick is valid, so the only
    # thing the endpoint can refuse on is the revision it compares: 409.
    status2, payload2 = client.api_post(
        "/api/item/LOG-002/continue",
        {"ticks": [["T-thermal-model", "open"]], "expected_revision": rev0},
    )
    assert status2 == 409, payload2
    assert payload2["kind"] == "conflict"
    assert payload2["expected_revision"] == rev0
    assert payload2["current_revision"] == moved
    # Nothing was written: the file holds the ONE continuation from the
    # applied save, not a second one.
    with open(log_path, "rb") as fh:
        text = fh.read().decode("utf-8")
    assert text.count("id: LOG-003") == 1


def test_the_next_preview_after_a_disk_edit_carries_the_new_revision(served_warm):
    """The revision is read at RENDER time: after the file moves on disk,
    the next served preview names the new sha256. A decoration that baked
    the revision into the preview generation (the preview dir IS a built
    site) is exactly what fails this."""
    app, client = served_warm
    (panel0,) = _panels(pane(_body(client, app, "LOG-002")))
    rev0 = panel0["attrs"][REVISION_ATTR]
    root = app.state.snapshot.project.root
    log_path = os.path.join(root, "items", "log.yaml")
    applied = edit_mod.apply_edit(
        root,
        edit_mod.EditRequest(
            who="other-author",
            ref="LOG-001",
            op=edit_mod.SetField("summary", "Power work list, reworded."),
            expected_revision=_sha(log_path),
        ),
        config_path=str(app.state.config_path),
    )
    assert isinstance(applied, edit_mod.Applied), applied.message
    target = _sha(log_path)
    assert target != rev0
    deadline = time.monotonic() + 30.0
    seen = None
    while time.monotonic() < deadline:
        (panel,) = _panels(pane(_body(client, app, "LOG-002")))
        seen = panel["attrs"].get(REVISION_ATTR)
        if seen == target:
            break
        time.sleep(0.05)
    assert seen == target, (
        f"the served preview kept naming revision {seen!r} after the file "
        f"moved to {target!r}"
    )


def test_a_forks_panels_name_their_own_tips_keys_and_file_revisions(served_fork):
    """§7a.3 with W5b.4a, across files: the head's page shows two panels;
    each names ITS tip's minted key and ITS tip's file revision. LOG-002
    lives in log.yaml and LOG-003 in branch.yaml, so a decoration that
    hashed one file for every panel (or the viewed entry's file -- the head
    shares LOG-002's file) fails the cross-check here."""
    app, client = served_fork
    project = _fresh_project(app)
    panels = _panels(pane(_body(client, app, "LOG-001")))
    assert len(panels) == 2, [panel["attrs"] for panel in panels]
    by_tip = {}
    for panel in panels:
        (tip,) = set(TIP_ATTR.findall(panel["slice"]))  # the panel IS its tip
        by_tip[tip] = panel
    assert set(by_tip) == {"LOG-002", "LOG-003"}
    for tip_id, panel in by_tip.items():
        tip = project.item_by_id(tip_id)
        assert tip.key, f"{tip_id} carries no key: the fixture is not warm"
        assert panel["attrs"][TIP_KEY_ATTR] == tip.key, tip_id
        assert panel["attrs"][REVISION_ATTR] == _sha(_tip_file(project, tip_id)), tip_id
    assert (
        by_tip["LOG-002"]["attrs"][REVISION_ATTR]
        != by_tip["LOG-003"]["attrs"][REVISION_ATTR]
    ), (
        "the two tips live in different files: equal panel revisions mean "
        "the decoration hashed one file for both panels"
    )


# ------------------------------------------- the seam: response-only, both pairs

def test_the_build_ships_no_context_while_the_served_pair_shows_it(tmp_path):
    """R3/Q9 for the new attributes, pinned as ONE pair: every byte of
    `refdes build` carries neither attribute (the site has no save, so it
    has no save context to name), the SAME project under serve keeps the
    pane on disk byte-identical to what build wrote, and the response pane
    carries both attributes. The pair keeps the guard honest: it would pass
    vacuously on a project whose pane never decorates."""
    config = _warm_served(tmp_path)
    assert cli_mod.main(["-c", config, "build"]) == 0
    out = os.path.join(str(tmp_path), "_site")
    seen = False
    for rel, text in _walk_text(out):
        assert TIP_KEY_ATTR not in text, rel
        assert REVISION_ATTR not in text, rel
        if rel == "log-002.html":
            seen = True
    assert seen, "the build wrote no item page: the walk proved nothing"
    # The W5b.3 pair's reading (test_task_pane_ticks.py, green on Windows):
    # BOTH sides are text-mode reads, so the pane comparison is immune to
    # the newline the platform writer chose -- every other byte must match.
    # (The walk above decodes bytes and is newline-sensitive; it checks
    # marker ABSENCE, a property the writer's newline choice cannot hide.)
    with open(os.path.join(out, "log-002.html"), encoding="utf-8") as fh:
        built_pane = pane(fh.read())
    assert built_pane  # the pane is there, plain
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        client = Client(app)
        with open(
            os.path.join(app.preview.current, "log-002.html"), encoding="utf-8"
        ) as fh:
            disk_pane = pane(fh.read())
        assert disk_pane == built_pane  # R3: the disk half of the pair
        page_pane = pane(_body(client, app, "LOG-002"))
        (panel,) = _panels(page_pane)
        assert panel["attrs"][TIP_KEY_ATTR] == _fresh_project(app).item_by_id("LOG-002").key
        assert panel["attrs"][REVISION_ATTR] == _sha(
            _tip_file(_fresh_project(app), "LOG-002")
        )
    finally:
        app.stop()


def test_a_no_write_server_offers_no_controls_and_no_context(served_no_write, tmp_path_factory):
    """--no-write, pinned conservative (the W5b.3 rule extended): the server
    refuses every write, so it names no key, no revision, ships no
    checkboxes and no module -- a save context for a save that 403s is the
    UI lying. The pair proves the flag is what refuses: a writable server
    on the same warm fixture ships controls, key and revision."""
    app, client = served_no_write
    page = _body(client, app, "LOG-002")
    body = pane(page)
    assert body  # the pane is there (Q9: the site's pane, read-only)
    assert "[ ]" in body  # the read-only glyph, as text
    assert "<input" not in body
    assert TIP_KEY_ATTR not in page
    assert REVISION_ATTR not in page
    assert TICK_MODULE not in page

    twin = _warm_served(tmp_path_factory.mktemp("no-write-twin"))
    writable = EditorApp(twin, poll_interval=0.05)
    writable.start()
    try:
        twin_page = _body(Client(writable), writable, "LOG-002")
        assert "<input" in pane(twin_page)
        assert TIP_KEY_ATTR in pane(twin_page)
        assert REVISION_ATTR in pane(twin_page)
    finally:
        writable.stop()


# ------------------------------------------------------ the values are data, not markup

def test_a_hostile_key_cannot_break_out_of_the_panel_attribute(tmp_path):
    """The key lands in an attribute straight from YAML (no writable load
    has rewritten this one -- keys are authored-legal text the loader
    reports and keeps). The template's autoescaping is the only barrier,
    so pin it on the attribute itself: the full value survives as data,
    and the page carries no live script and no raw quote-breakout."""
    config = _write_files(tmp_path, {"log.yaml": HOSTILE_KEY})
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        page = _body(Client(app), app, "LOG-002")
        (panel,) = _panels(pane(page))
        raw = panel["attrs"][TIP_KEY_ATTR]
        assert html.unescape(raw) == HOSTILE  # the whole authored value, as data
        assert '"><script>alert(1)' not in page  # no breakout: the raw quote is absent
        assert "<script>alert(1)" not in page
        # ...and the context's other half is real on the same panel: the
        # escaping test is not testing a pane that decorates for nothing.
        log_path = os.path.join(str(tmp_path), "items", "log.yaml")
        assert panel["attrs"][REVISION_ATTR] == _sha(log_path)
    finally:
        app.stop()


def test_a_tip_with_no_key_keeps_its_boxes_and_names_no_context(tmp_path):
    """The keyless tip (a project nobody has run a writable load on): the
    checkboxes stay EXACTLY as W5b.3 renders them -- the control is keyed
    by the tip's DISPLAY ID, and test_task_pane_ticks.py pins that box on
    plain-write (keyless) fixtures. W5b.4a names NO save context on its
    panel: no key, no revision. The tip carries no artifact key, so
    `continue_thread` can write no `follows:` composite for its
    continuation (its own refusal says so) -- a panel naming a save that
    can only 422 is the UI lying, and W5b.4c's save UI must refuse to
    draft a panel without both attributes. The keyed tip's panel in the
    SAME response carries both: the absence is the missing key, not a
    pane that skips its context."""
    config = _write_files(
        tmp_path, {"log.yaml": KEYED_TIP, "branch.yaml": KEYLESS_TIP}
    )
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        page = _body(Client(app), app, "LOG-001")  # the head: both tips' panels
        body = pane(page)
        assert body  # the pane is there, and the page is a 200
        panels = _panels(body)
        assert len(panels) == 2, [panel["attrs"] for panel in panels]
        by_tip = {}
        for panel in panels:
            (tip,) = set(TIP_ATTR.findall(panel["slice"]))  # the panel IS its tip
            by_tip[tip] = panel
        assert set(by_tip) == {"LOG-002", "LOG-003"}
        for panel in panels:  # W5b.3's boxes, on the keyless tip included
            assert "<input" in panel["slice"], by_tip
        keyed = by_tip["LOG-002"]["attrs"]
        assert keyed[TIP_KEY_ATTR] == KEYED_TIP_KEY
        log_path = os.path.join(str(tmp_path), "items", "log.yaml")
        assert keyed[REVISION_ATTR] == _sha(log_path)
        keyless = by_tip["LOG-003"]["attrs"]
        assert TIP_KEY_ATTR not in keyless
        assert REVISION_ATTR not in keyless
    finally:
        app.stop()
