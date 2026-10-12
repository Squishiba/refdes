"""Thread workbench W5a: the floating task pane on the PUBLISHED site page.

docs/design/thread-workbench.md §7a (decided, read-only half — sub-decision
6): the static site gets the same pane the serve preview shows, and the pane
computes nothing — every fact comes from `threads.threads_projection`, the
same object the index payload's `threads` key carries and `refdes thread`
renders, placed into the page server-side (§3: "the pane computes NOTHING").
So these are rendered-HTML tests in the `test_threads_render.py` house style.

Clauses pinned:

* the pane is a *client* of the projection — assertions are `refdes thread`'s
  own lines, never a second rendering of them;
* read-only: the glyph is TEXT, no `<input>` in any pane, and no token,
  form or write control anywhere in `_site/` (browser-editor.md's rule for
  published output);
* progressive enhancement (§7a 6): pane and toggle start `hidden`, the page
  reads fully without them, the toggle never appears without the script;
* "pages without a thread get no pane (absent, not empty)" and "the site
  stays byte-identical for projects with no threads" — total absence of the
  pane's markers, assets and tags.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import history as history_mod
from refdes import keys as keys_mod
from refdes import pages as pages_mod
from refdes import parse, render, task_pane, threads
from refdes.schema import load_project

CONFIG = "site: { title: Task Pane, out: _site }\nstandard: { base: hardware, version: 3 }\n"

OPEN_THERMAL = "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
DONE_INPUT = "      - {id: T-input-range, text: Check the 36 V input case., state: done}\n"

# One tip, tasks, a concluding verdict with an open task remaining, and a
# requirement the thread addresses but nobody verified — one thread that
# exercises the note, the verdict line, the task rows and one derived kind.
ONE_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    f"{OPEN_THERMAL}"
    f"{DONE_INPUT}"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
    "    addresses: REQ-001\n"
    "  - id: REQ-001\n"
    "    type: requirement\n"
    "    title: Idle current budget\n"
    "    status: active\n"
    "    body: The idle rail must stay under 10 uA.\n"
    "  - id: LOG-006\n"
    "    type: log\n"
    "    summary: A lone entry with no thread.\n"
    "    date: 2026-09-06\n"
)

# A real fork: one head, two open tips, each tip with its own nearest list.
# §7a sub-decision 3 (living-notes §5 rule 4) forbid showing a union.
FORK = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    f"{OPEN_THERMAL}"
    "  - id: LOG-002\n"
    "    summary: Thermal branch.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
    "  - id: LOG-003\n"
    "    summary: Decoupling branch.\n"
    "    date: 2026-09-03\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-decoupling, text: Recheck decoupling near U14., state: open}\n"
)

# A merge whose two parents refuse: different statuses and different task
# lists at the same distance. Neither fold may pick a winner, and the pane
# says so in the CLI's own words (§5 rule 3's posture).
REFUSED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Head.\n"
    "    date: 2026-09-01\n"
    "  - id: LOG-002\n"
    "    summary: Accepted parent.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
    "    tasks: [{id: T-a, text: Parent A task., state: open}]\n"
    "  - id: LOG-003\n"
    "    summary: Proposed parent.\n"
    "    date: 2026-09-03\n"
    "    follows: LOG-001\n"
    "    status: proposed\n"
    "    tasks: [{id: T-b, text: Parent B task., state: open}]\n"
    "  - id: LOG-004\n"
    "    summary: Merged, refuses both folds.\n"
    "    date: 2026-09-04\n"
    "    follows: [LOG-002, LOG-003]\n"
)

# A thread whose authored rows include explicitly-null `id`/`text` (PR #197
# review round 2, B2): `refdes thread` renders those as `?`/empty via `or`,
# and the pane must not print the literal "None".
NULLS = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Null-shaped rows.\n"
    "    date: 2026-08-01\n"
    "    tasks:\n"
    "      - {id: null, text: null, state: open}\n"
    "  - id: LOG-002\n"
    "    summary: Silent continuation.\n"
    "    date: 2026-08-02\n"
    "    follows: LOG-001\n"
)

# A `done` row carrying an authored `open_since:` (PR #197 review round 2,
# B4): the projection's `dict(row)` carries it through, and the CLI prints
# the age line only for OPEN rows -- so must the pane.
DONE_WITH_AGE = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: One finished, one open.\n"
    "    date: 2026-08-01\n"
    "    tasks:\n"
    "      - {id: T-stale, text: Finished long ago., state: done, open_since: {entry: LOG-000, date: 2026-07-01}}\n"
    "      - {id: T-live, text: Still open., state: open}\n"
    "  - id: LOG-002\n"
    "    summary: Silent continuation.\n"
    "    date: 2026-08-02\n"
    "    follows: LOG-001\n"
)

# Two independent threads in ONE project (PR #197 review round 2, B5b):
# each entry's pane must be its OWN thread's pane.
TWO_THREADS = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: First thread head.\n"
    "    date: 2026-08-01\n"
    "    tasks: [{id: T-first, text: First thread task., state: open}]\n"
    "  - id: LOG-002\n"
    "    summary: First thread tip.\n"
    "    date: 2026-08-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
    "  - id: LOG-003\n"
    "    summary: Second thread head.\n"
    "    date: 2026-08-03\n"
    "    tasks: [{id: T-second, text: Second thread task., state: open}]\n"
    "  - id: LOG-004\n"
    "    summary: Second thread tip.\n"
    "    date: 2026-08-04\n"
    "    follows: LOG-003\n"
    "    status: proposed\n"
)

NO_THREADS = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Not a thread, never was.\n"
    "    date: 2026-09-01\n"
    "  - id: LOG-002\n"
    "    summary: Neither is this.\n"
    "    date: 2026-09-02\n"
)

# Nobody ever declared a task list anywhere (PR #197 review S1: the pane
# must render each posture string `refdes thread` prints).
UNDECLARED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Head, no tasks.\n"
    "    date: 2026-08-01\n"
    "  - id: LOG-002\n"
    "    summary: Continuation, no tasks.\n"
    "    date: 2026-08-02\n"
    "    follows: LOG-001\n"
)

# The tip declares the explicit empty list: the `cleared` posture.
CLEARED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Work list.\n"
    "    date: 2026-08-01\n"
    "    tasks: [{id: T-old, text: Older task., state: open}]\n"
    "  - id: LOG-002\n"
    "    summary: Everything closed.\n"
    "    date: 2026-08-02\n"
    "    follows: LOG-001\n"
    "    tasks: []\n"
)

# One valid row beside one row that is not even a mapping (PR #197 review
# B1): the count rides the heading and the VALID ROW STILL PRINTS. The
# malformed row is a validation error like everywhere else in the tool --
# reported, and the projection drops it -- so this fixture renders with
# errors on purpose.
MALFORMED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Mixed list.\n"
    "    date: 2026-08-01\n"
    "    tasks:\n"
    "      - {id: T-measure, text: Measure the rail., state: open}\n"
    "      - not even a mapping\n"
    "  - id: LOG-002\n"
    "    summary: Silent continuation.\n"
    "    date: 2026-08-02\n"
    "    follows: LOG-001\n"
)

ALL_MALFORMED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Nothing usable.\n"
    "    date: 2026-08-01\n"
    "    tasks:\n"
    "      - not even a mapping\n"
    "  - id: LOG-002\n"
    "    summary: Silent continuation.\n"
    "    date: 2026-08-02\n"
    "    follows: LOG-001\n"
)


def _render(tmp_path, items_yaml, with_pages=False, allow_errors=False):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    if with_pages:
        pages = tmp_path / "pages"
        pages.mkdir(exist_ok=True)
        (pages / "about.md").write_text(
            "---\ntitle: About\n---\n\nJust prose, no items.\n", encoding="utf-8"
        )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys_mod.mint_missing(project)
    build_mod.build(project)
    out = render.render_site(project)
    if not allow_errors:
        assert not project.errors, [d.message for d in project.errors]
    return project, out


def _page(out, name):
    with open(os.path.join(out, f"{name}.html"), encoding="utf-8") as fh:
        return fh.read()


def pane(html: str) -> str:
    """The pane's own markup, or "" when the page carries no pane."""
    start = html.find('<aside class="refdes-taskpane"')
    if start < 0:
        return ""
    return html[start : html.find("</aside>", start)]


def panel(html: str, index: int) -> str:
    """One tab panel's own markup (T2, PR #197 review: not a slice that
    stops at the first `</div>` -- it runs to the next panel, the derived
    section, or the aside's end, whatever comes first). B5c (review round
    2): the old marker cut at the NEXT panel's `data-refdes-panel="`, which
    sits inside that panel's own opening tag, so panel 1's slice leaked the
    next panel's `<div ...>` tag; the cut is the next `<div` instead. It
    assumes a panel's markup contains no nested <div> of its own."""
    marker = f'id="refdes-taskpane-panel-{index}"'
    marker_at = html.find(marker)
    assert marker_at >= 0, marker
    start = html.rfind("<div", 0, marker_at)
    after_open = html.find(">", marker_at) + 1
    ends = [
        at
        for at in (
            html.find("<div", after_open),
            html.find("<details", after_open),
            html.find("</aside>", after_open),
        )
        if at != -1
    ]
    return html[start : min(ends)]


def tree_of(root: str) -> dict:
    files = {}
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace("\\", "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


# ------------------------------------------------------- present / absent


def test_a_threaded_items_page_carries_the_pane(tmp_path):
    _project, out = _render(tmp_path, ONE_TIP)
    page = _page(out, "log-001")
    body = pane(page)
    assert body  # no pane would mean ""
    assert 'data-refdes-taskpane="LOG-001"' in body
    # §7a 6: the toggle is on the page, `hidden` until the script reveals
    # it — with JavaScript off neither toggle nor pane ever appears.
    assert (
        '<button type="button" class="refdes-taskpane-toggle"'
        ' id="refdes-taskpane-toggle" aria-controls="refdes-taskpane"'
        ' aria-expanded="false" hidden>Tasks</button>' in page
    )
    first_line_end = body.find("\n")
    assert first_line_end != -1, "pane body is a single line"
    assert "hidden" in body[:first_line_end]
    # C1 (PR #197 review round 2): the heading is the threads.py constant,
    # not a string the template re-types.
    assert threads.TASK_HEADING_TIP in body


def test_a_page_without_a_thread_gets_no_pane_at_all(tmp_path):
    _project, out = _render(tmp_path, ONE_TIP, with_pages=True)
    for name in ("log-006", "about", "index"):
        html = _page(out, name)
        assert "refdes-taskpane" not in html, name  # absent, not empty
        assert pane(html) == "", name


# ------------------------------------------- §7a (1): the tip's list, noted


def test_an_older_entry_shows_the_tips_list_with_the_note(tmp_path):
    _project, out = _render(tmp_path, ONE_TIP)
    body = pane(_page(out, "log-001"))
    assert "viewing LOG-001 · tasks as of tip LOG-002" in body
    assert "Tasks at tip:" in body
    assert "T-thermal-model" in body


def test_the_tips_own_page_shows_the_list_without_the_note(tmp_path):
    _project, out = _render(tmp_path, ONE_TIP)
    body = pane(_page(out, "log-002"))
    assert "viewing" not in body
    assert "T-thermal-model" in body


# -------------------------------------------------- §7a (3): fork, never union


def test_a_fork_gets_one_tab_per_open_tip(tmp_path):
    _project, out = _render(tmp_path, FORK)
    page = _page(out, "log-001")
    body = pane(page)
    assert body.count('role="tab"') == 2
    assert body.count('role="tabpanel"') == 2
    assert ">LOG-002</button>" in body and ">LOG-003</button>" in body
    # C1 (PR #197 review round 2): the per-tip heading is threads.py's
    # spelling (`task_heading`'s forked form), not the template's.
    assert threads.task_heading("LOG-002", single_tip=False) in body
    assert threads.task_heading("LOG-003", single_tip=False) in body
    assert threads.TASK_HEADING_TIP not in body  # the single tip heading never lies here


def test_the_fork_tabs_never_union(tmp_path):
    _project, out = _render(tmp_path, FORK)
    page = _page(out, "log-001")
    first, second = panel(page, 1), panel(page, 2)
    # LOG-002's branch inherits the head's list; LOG-003's branch replaced
    # it. Each panel shows exactly its own nearest list — nothing else.
    assert "T-thermal-model" in first and "T-decoupling" not in first
    assert "T-decoupling" in second and "T-thermal-model" not in second
    # Only the first panel is visible at rest; the switch is show/hide.
    assert "hidden" in second
    assert "hidden" not in first


# ------------------------------------------------ §5 rule 3 in the pane


def test_a_refused_fold_says_so_in_the_cli_words(tmp_path):
    _project, out = _render(tmp_path, REFUSED)
    body = pane(_page(out, "log-004"))
    assert threads.verdict_conflicting_line(threads.VERDICT_CONFLICTING) in body
    assert f"Tasks at tip: {threads.TASK_POSTURE_AMBIGUOUS}" in body
    # and it refuses to invent a winner either way
    assert "T-a" not in body and "T-b" not in body


# ------------------------- PR #197 review B1: the count never hides the rows


def test_malformed_rows_are_counted_and_the_valid_rows_still_print(tmp_path):
    """`refdes thread` prints a partly-malformed list as the count on the
    heading AND the valid rows under it; the pane must print the same
    (review B1: the count once replaced the whole list here)."""
    _project, out = _render(tmp_path, MALFORMED, allow_errors=True)
    body = pane(_page(out, "log-001"))
    assert f"Tasks at tip: {threads.task_malformed_note(1)}" in body
    assert "T-measure" in body
    assert "Measure the rail." in body
    assert "[ ]" in body  # the valid row keeps its glyph
    # the tip's page shows the identical block (same thread, one tip)
    assert f"Tasks at tip: {threads.task_malformed_note(1)}" in pane(_page(out, "log-002"))


def test_a_fully_malformed_list_keeps_the_heading_and_note_but_no_empty_ul(
    tmp_path,
):
    """Round-5 nit: with EVERY authored row malformed there is nothing to
    list — the pane keeps the heading and its count (the count is the whole
    story) and renders no empty <ul> where the rows would have gone."""
    _project, out = _render(tmp_path, ALL_MALFORMED, allow_errors=True)
    body = pane(_page(out, "log-001"))
    assert f"Tasks at tip: {threads.task_malformed_note(1)}" in body
    assert "refdes-taskpane-tasks" not in body  # the list class is absent...
    assert "<li>" not in body  # ...and so is any list item anywhere in the pane


# ------------------------------------------------ task rows, CLI parity


def test_task_rows_carry_the_cli_facts_as_text(tmp_path):
    _project, out = _render(tmp_path, ONE_TIP)
    body = pane(_page(out, "log-002"))
    assert "[ ]" in body and "[x]" in body  # the glyph, as text
    assert "T-thermal-model" in body
    assert "Model worst-case copper temperature." in body
    assert "(open since LOG-001, 2026-08-30)" in body
    # absolute only: no relative span without the CLI's --as-of (§5 rule 3)
    assert "day" not in body


def test_the_verdict_line_is_the_shared_composers_line(tmp_path):
    """B3 (PR #197 review round 2): the page's Verdict line is the one
    composer's output for the projection's own verdict dict — not a literal
    re-typed into the test, which could drift from the code unnoticed."""
    project, out = _render(tmp_path, ONE_TIP)
    branch = threads.threads_projection(project)[0]["branches"][0]
    open_count = sum(
        1 for row in branch["tasks"]["rows"] if row["state"] == "open"
    )
    line = threads.verdict_line(branch["verdict"], open_count)
    body = pane(_page(out, "log-002"))
    assert line in body
    assert line.startswith("Verdict: accepted (")  # the fixture still says accepted


# ---------------- PR #197 review S1: every posture string, from one spelling


def test_the_undeclared_posture_renders_exactly_threads_spelling(tmp_path):
    _project, out = _render(tmp_path, UNDECLARED)
    body = pane(_page(out, "log-002"))
    assert f"Tasks at tip: {threads.TASK_POSTURE_UNDECLARED}" in body


def test_the_cleared_posture_renders_exactly_threads_spelling(tmp_path):
    _project, out = _render(tmp_path, CLEARED)
    body = pane(_page(out, "log-002"))
    assert (
        f"Tasks at tip: {threads.task_posture_cleared('LOG-002')}" in body
    )
    assert "T-old" not in body  # cleared is not "the older list, faded"


# ------------------------------ §7a (4): derived, collapsed, labelled, plain


def test_the_derived_section_is_collapsed_labelled_and_uncheckable(tmp_path):
    _project, out = _render(tmp_path, ONE_TIP)
    body = pane(_page(out, "log-002"))
    open_at, close_at = body.find("<details"), body.find(">", body.find("<details"))
    tag = body[open_at : close_at + 1]
    assert tag == '<details class="refdes-taskpane-derived">'  # no `open`: collapsed
    assert "<summary>" + threads.DERIVED_HEADING + "</summary>" in body
    assert "<h3>Coverage</h3>" in body
    assert "REQ-001  unverified" in body
    # labelled as derived and read-only: nothing inside can be ticked.
    assert "<input" not in body
    derived = body[body.find("<details") :]
    assert "[ ]" not in derived and "[x]" not in derived


def test_derived_groups_use_the_one_shared_kind_order():
    rows = [
        {"kind": "citation", "ref": "CMP-001", "problem": "unpinned"},
        {"kind": "check", "ref": "LOG-002", "value": "P_diss", "against": "BND-001",
         "detail": "", "stale": False},
        {"kind": "blocked", "ref": "DEC-002", "path": [], "root": "DEC-001",
         "root_status": "proposed", "stale": False},
        {"kind": "coverage", "ref": "REQ-001", "problem": "unverified"},
    ]
    groups = task_pane._derived_groups(rows)
    assert [g["heading"] for g in groups] == [
        threads.DERIVED_GROUP_HEADINGS[kind]
        for kind in ("coverage", "blocked", "check", "citation")
    ]
    # the one order #194 aligns with, spelled once (§7a 4) -- and the order
    # is the table: adding a kind to HEADINGS puts it in ORDER at once
    # (PR #197 review S3, the one-table posture).
    assert threads.DERIVED_GROUP_ORDER == tuple(threads.DERIVED_GROUP_HEADINGS)
    assert groups[1]["rows"] == ["DEC-002  by DEC-001 (proposed)"]
    assert groups[2]["rows"] == ["LOG-002  P_diss violates BND-001"]


def test_an_unregistered_derived_kind_fails_loudly():
    """S3 (PR #197 review): the pane filters rows by group membership, so a
    kind the projection can emit but the table cannot group would silently
    vanish from every page. It raises, naming the kind, instead."""
    with pytest.raises(ValueError, match="audit"):
        task_pane._derived_groups([
            {"kind": "coverage", "ref": "REQ-001", "problem": "unverified"},
            {"kind": "audit", "ref": "AUD-001", "problem": "something new"},
        ])


# ------------------------------------------ §7a (6): progressive enhancement


def test_the_page_reads_fully_without_the_pane(tmp_path):
    """JavaScript off: pane and toggle never appear (both start `hidden`,
    only taskpane.js reveals the toggle), and everything the item itself
    says is outside the pane and before it in the document."""
    _project, out = _render(tmp_path, ONE_TIP)
    page = _page(out, "log-002")
    article_end = page.find("</article>")
    aside_start = page.find('<aside class="refdes-taskpane"')
    assert 0 < article_end < aside_start  # nothing of the item is inside it
    assert "Thermal modelling accepted." in page[:article_end]
    toggle = page.find('id="refdes-taskpane-toggle"')
    assert 0 < toggle
    assert "hidden" in page[toggle : page.find(">", toggle)]
    assert "hidden" in page[aside_start : page.find(">", aside_start)]
    assert '<script src="assets/taskpane.js" defer></script>' in page


# ------------------------------------------------------ _site/ stays plain


FORBIDDEN = ("X-Refdes-Token", "refdes-token", "?token=", "/api/", "<form", "fetch(")


def test_the_site_carries_no_editor_control_or_token(tmp_path):
    """browser-editor.md: "No editor control, token, or write API is
    emitted into `_site/`." The task pane is enhancement within that rule:
    walk every published byte."""
    _project, out = _render(tmp_path, FORK, with_pages=True)
    for dirpath, _dirs, names in os.walk(out):
        for name in names:
            path = os.path.join(dirpath, name)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for needle in FORBIDDEN:
                assert needle not in text, (os.path.relpath(path, out), needle)
    # and no `<input>` inside any pane the site emits (the sidenav's
    # checkbox is pre-existing chrome, outside the aside)
    for name in ("log-001", "log-002", "log-003"):
        assert "<input" not in pane(_page(out, name))


# ------------------------------------------------------- rendering never writes


def test_rendering_the_pane_writes_nothing_into_the_project(tmp_path):
    """§4's "rendering never captures", at the pane's own touch path: a
    full build already ran, so the only bytes a pane-bearing render may
    write are under `_site/`."""
    project, out = _render(tmp_path, ONE_TIP)
    project_root = str(tmp_path)

    def outside():
        return {
            rel: digest
            for rel, digest in tree_of(project_root).items()
            if not rel.startswith("_site/")
        }

    before = outside()
    render.render_site(project, draft=True)  # the serve-preview posture
    assert outside() == before
    # B5d (PR #197 review round 2): not `assert out` -- a truthy path string
    # proves nothing. The draft render DID happen (the page tree inside
    # `_site/` is real and carries the pane again).
    inside = {
        rel: digest
        for rel, digest in tree_of(out).items()
        if rel.endswith(".html")
    }
    assert inside, "the draft render produced no page at all"
    assert 'data-refdes-taskpane="LOG-001"' in _page(out, "log-002")


# ------------------------------------------------- no-threads byte-identity


def test_a_project_with_no_threads_publishes_exactly_what_it_did_before(
    tmp_path, monkeypatch
):
    """§7a's promise ("absent, not empty"): with no `follows:` edge
    anywhere the pane changes not one published byte. Pinned three ways:
    the markers are absent everywhere; a monkeypatch that forces a pane
    onto the same project DOES change bytes (so absence is the feature,
    not a dead path); and re-rendering the real project reproduces the
    first tree to the byte."""
    project, out = _render(tmp_path, NO_THREADS, with_pages=True)
    honest = tree_of(out)
    assert not any("taskpane" in rel for rel in honest)
    for rel in honest:
        if rel.endswith(".html"):
            with open(os.path.join(out, rel), encoding="utf-8") as fh:
                assert "taskpane" not in fh.read(), rel

    fake = {
        "ref": "LOG-001",
        "viewing": "LOG-001",
        "forked": False,
        "tabs": [],
        "derived": [],
        "derived_heading": threads.DERIVED_HEADING,
    }
    monkeypatch.setattr(task_pane, "panes_by_entry", lambda views: {"LOG-001": fake})
    live = tree_of(render.render_site(project))
    assert live != honest

    monkeypatch.undo()
    assert tree_of(render.render_site(project)) == honest


# ------- PR #197 review E1 / round-5 P4: store read once, projection once


def test_one_site_render_reads_the_store_and_projects_once(tmp_path, monkeypatch):
    """The pane's projection used to read `history.capture_index` beside
    items.json's own read, so a `render_site` parsed the event store twice
    (review E1) — and even with ONE read hoisted, the projection itself
    still ran twice: once for the panes, once inside `items_json`
    (round-5 P4). Both are hoisted in `render_site` now and the very same
    objects handed to both consumers: exactly one store read and exactly
    one projection, byte-identical output asserted by the golden theme
    test being green all the same."""
    project, _out = _render(tmp_path, ONE_TIP)  # keys/built state ready
    reads: list = []
    projections: list = []
    real_capture = history_mod.capture_index
    real_projection = threads.threads_projection

    def counting_capture(p):
        result = real_capture(p)
        reads.append(result)
        return result

    def counting_projection(*args, **kwargs):
        result = real_projection(*args, **kwargs)
        projections.append(result)
        return result

    monkeypatch.setattr(history_mod, "capture_index", counting_capture)
    monkeypatch.setattr(threads, "threads_projection", counting_projection)
    render.render_site(project)
    assert len(reads) == 1
    assert len(projections) == 1


def test_a_pages_only_render_never_reads_the_capture_store(tmp_path, monkeypatch):
    """C6 (PR #197 review round 2): the hoisted read moved below the point
    where it can matter -- a project with no items has no thread, no pane
    and no `items.json`, so its render must not touch the event store at
    all (the pre-round-2 hoist read it even on the no-items early return)."""

    def never(_project):
        raise AssertionError("the no-items render read the capture store")

    monkeypatch.setattr(history_mod, "capture_index", never)
    write_project_config(tmp_path, CONFIG)
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "about.md").write_text(
        "---\ntitle: About\n---\n\nJust prose, no items.\n", encoding="utf-8"
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    pages_mod.load_pages(project)
    out = render.render_site(project)
    assert not project.errors, [d.message for d in project.errors]
    # the render really ran (and never touched the store -- `never` above)
    with open(os.path.join(out, "about.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert "About" in html
    assert "taskpane" not in html  # no items => no pane, still


# ------------------ PR #197 review B3: a keyboard-reachable tablist


def test_fork_tab_markup_is_a_roving_tablist(tmp_path):
    """The markup half of the ARIA tabs pattern: exactly one stop (the
    selected tab has no tabindex=-1, the others do); `taskpane.js` moves
    the stop with arrow keys (checked in the node harness — no browser
    here)."""
    _project, out = _render(tmp_path, FORK)
    body = pane(_page(out, "log-001"))
    first = body[body.find('id="refdes-taskpane-tab-1"') :]
    first = first[: first.find("</button>")]
    assert 'aria-selected="true"' in first and "tabindex" not in first
    second = body[body.find('id="refdes-taskpane-tab-2"') :]
    second = second[: second.find("</button>")]
    assert 'aria-selected="false"' in second and 'tabindex="-1"' in second


# ------------------ PR #197 review B2: static sites keep the 16px place


def test_the_published_pane_css_never_mentions_the_serve_bar(tmp_path):
    """The bar offset is response-only (it lives in `serve/static/bar.css`
    and bar.css is never part of `_site/`); the published `taskpane.css`
    must keep the toggle at its own 16px bottom-right place."""
    _project, out = _render(tmp_path, ONE_TIP)
    with open(os.path.join(out, "assets", "taskpane.css"), encoding="utf-8") as fh:
        css = fh.read()
    assert "bottom: var(--space-16);" in css
    assert "50px" not in css and "refdes-serve-bar" not in css
    for name in ("log-001", "log-002", "index"):
        assert "bar.css" not in _page(out, name)


# ================= PR #197 review round 2 =================

# The two kinds `refdes work`'s whole-project block carries that a THREAD's
# derived block never does — and that this pane therefore has no wording for
# (PR #197 review B1). They are in the shared group table, which is exactly
# why the old table-membership guard let them through to a bare KeyError.
FORK_ROW = {"kind": "fork", "ref": "LOG-001", "tips": ["LOG-002", "LOG-003"]}
VERDICT_ROW = {
    "kind": "verdict",
    "ref": "LOG-002",
    "status": "proposed",
    "thread": "LOG-001",
}


def test_a_fork_row_raises_the_named_error_not_a_keyerror():
    with pytest.raises(ValueError, match="fork"):
        task_pane._derived_row(dict(FORK_ROW))
    with pytest.raises(ValueError, match="fork"):
        task_pane._derived_groups([dict(FORK_ROW)])


def test_a_verdict_row_raises_the_named_error_not_a_keyerror():
    with pytest.raises(ValueError, match="verdict"):
        task_pane._derived_row(dict(VERDICT_ROW))
    with pytest.raises(ValueError, match="verdict"):
        task_pane._derived_groups([dict(VERDICT_ROW)])


def test_the_unrenderable_kind_message_names_everything_to_teach():
    """B1: the old message told the reader to add the kind to the headings
    table, which was FALSE -- the pane's own row renderer needs an arm too.
    The message now names both places."""
    with pytest.raises(ValueError) as caught:
        task_pane._derived_groups([dict(FORK_ROW), dict(VERDICT_ROW)])
    message = str(caught.value)
    assert "fork" in message and "verdict" in message
    assert "task_pane._derived_row" in message
    assert "threads.DERIVED_GROUP_HEADINGS" in message


def test_the_pane_and_the_cli_compose_the_same_derived_line():
    """P2 (PR #197 review round 5): the pane and `refdes thread`/`refdes
    work` spell a derived row's detail through ONE composer,
    `threads.derived_detail` (the B3 `verdict_line` posture) — this pins
    that the pane's line IS the CLI's `ref  detail` for every kind the
    pane renders (the CLI's own line adds only block indentation, in
    `cli._derived_lines`). Re-spelling the wording on either surface
    fails this test; drifting it silently cannot."""
    rows = [
        {"kind": "coverage", "ref": "REQ-001", "problem": "uncovered"},
        {"kind": "blocked", "ref": "LOG-011", "root": "CMP-001",
         "root_status": "candidate", "stale": False},
        {"kind": "blocked", "ref": "LOG-012", "root": "CMP-002",
         "root_status": "draft", "stale": True},
        {"kind": "check", "ref": "LOG-010", "value": "P_diss",
         "against": "BND-001"},
        {"kind": "citation", "ref": "LOG-012", "problem": "unpinned"},
    ]
    for row in rows:
        assert task_pane._derived_row(row) == (
            f"{row['ref']}  {cli_mod._derived_detail(row)}"
        )


def test_explicit_null_id_and_text_render_as_query_and_empty(tmp_path):
    """B2: `cli._task_row_lines` renders an explicitly-null `id`/`text` with
    `or` (validation owns the error); the pane's `.get(key, default)` printed
    the literal "None" instead."""
    _project, out = _render(tmp_path, NULLS)
    body = pane(_page(out, "log-002"))
    start = body.find("<li>", body.find("refdes-taskpane-tasks"))
    li = body[start : body.find("</li>", start)]
    assert ">?<" in li  # the null id renders as `?`, like the CLI's
    assert "None" not in li  # never the literal "None"
    assert "(open since LOG-001, 2026-08-01)" in li  # the open row keeps its age


def test_the_age_line_never_marks_a_finished_row(tmp_path):
    """B4: an authored `open_since:` on a `done` row survives the
    projection's `dict(row)`; the CLI prints the age only for open rows and
    so must the pane."""
    _project, out = _render(tmp_path, DONE_WITH_AGE)
    body = pane(_page(out, "log-002"))

    def row_of(needle: str) -> str:
        start = body.rfind("<li>", 0, body.find(needle))
        return body[start : body.find("</li>", start)]

    stale = row_of("T-stale")
    assert "[x]" in stale  # it is the done row...
    assert "open since" not in stale  # ...and it shows no age line
    live = row_of("T-live")
    assert "(open since LOG-001, 2026-08-01)" in live  # the open row keeps its own


def test_a_fork_tips_own_page_gives_that_tab_no_note(tmp_path):
    """§7a sub-decision 1 (review B5a): the note names what the pane is
    looking AT; on a tip's own page that tab's list IS the current one, even
    on a forked thread where the OTHER tab is the one away from home."""
    _project, out = _render(tmp_path, FORK)
    page = _page(out, "log-002")
    first, second = panel(page, 1), panel(page, 2)
    # B5c: the slice ENDS at the next panel's `<div`, so nothing of that
    # other panel -- not even its opening tag -- is inside this one.
    assert "refdes-taskpane-panel-2" not in first
    assert "Tasks at LOG-002:" in first
    assert "viewing" not in first  # tip == viewing: nothing to disclaim
    assert "Tasks at LOG-003:" in second
    assert "viewing LOG-002 · tasks as of tip LOG-003" in second


def test_two_threads_in_one_project_get_their_own_panes(tmp_path):
    """B5b: `panes_by_entry` keys one pane per thread MEMBER of every thread
    -- a second thread must not steal or dilute the first one's pane."""
    project, out = _render(tmp_path, TWO_THREADS)
    views = task_pane.thread_views(project)
    assert [view["ref"] for view in views] == ["LOG-001", "LOG-003"]
    panes = task_pane.panes_by_entry(views)
    assert sorted(panes) == ["LOG-001", "LOG-002", "LOG-003", "LOG-004"]
    assert panes["LOG-001"]["ref"] == "LOG-001"  # first thread's members...
    assert panes["LOG-002"]["ref"] == "LOG-001"
    assert panes["LOG-003"]["ref"] == "LOG-003"  # ...second thread's members
    assert panes["LOG-004"]["ref"] == "LOG-003"
    first = pane(_page(out, "log-001"))
    second = pane(_page(out, "log-004"))
    assert "T-first" in first and "T-second" not in first
    assert "T-second" in second and "T-first" not in second


def test_a_single_tip_page_declares_no_tab_roles(tmp_path):
    """C2: with no tablist above them, `role="tabpanel"` named a tab that
    does not exist; the role (and its back-reference) belong to forks only."""
    _project, out = _render(tmp_path, ONE_TIP)
    body = pane(_page(out, "log-002"))
    assert 'role="tablist"' not in body and 'role="tabpanel"' not in body


def test_a_forked_panel_is_labelled_by_its_own_tab(tmp_path):
    _project, out = _render(tmp_path, FORK)
    body = pane(_page(out, "log-001"))
    for index in ("1", "2"):
        marker = f'id="refdes-taskpane-panel-{index}"'
        tag = body[body.rfind("<div", 0, body.find(marker)) : body.find(">", body.find(marker)) + 1]
        assert 'role="tabpanel"' in tag
        assert f'aria-labelledby="refdes-taskpane-tab-{index}"' in tag


def test_the_shared_glyph_mapping_is_read_only():
    """C5: `cli._THREAD_GLYPHS` IS `threads.TASK_GLYPHS`; a mutable shared
    dict would let a bug on one surface rewrite the other's printed bytes."""
    with pytest.raises(TypeError):
        threads.TASK_GLYPHS["open"] = "[X]"


def test_the_shared_derived_heading_mapping_is_read_only():
    """K2: `cli.THREAD_DERIVED_GROUP_HEADINGS` IS
    `threads.DERIVED_GROUP_HEADINGS`; the same one-object aliasing as the
    glyphs, so the same read-only guarantee."""
    assert cli_mod.THREAD_DERIVED_GROUP_HEADINGS is threads.DERIVED_GROUP_HEADINGS
    with pytest.raises(TypeError):
        threads.DERIVED_GROUP_HEADINGS["coverage"] = "Covered"


def test_taskpane_js_is_syntactically_valid():
    """K7 (PR #197 review): `node --check` on the shipped script. CI's
    test job installs no node (tests.yml runs setup-python only), so this
    skips when node is not on PATH — it bites on dev machines and wherever
    node exists."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src",
        "refdes",
        "templates",
        "taskpane",
        "taskpane.js",
    )
    result = subprocess.run(
        [node, "--check", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_the_pane_glyphs_dropped_and_unknown_row_states_as_threads_spell_them():
    """K-round-3 nit: the pane rows for a dropped task and an unknown-state
    task carry the shared glyphs — `[-]` and `[?]` — and an unknown row state
    still gets its row, not a silent drop."""
    block = task_pane._task_block(
        {
            "state": "declared",
            "rows": [
                {"id": "T-a", "text": "First.", "state": "open"},
                {"id": "T-b", "text": "Second.", "state": "dropped"},
                {"id": "T-c", "text": "Third.", "state": "wibble"},
            ],
        }
    )
    assert [row["glyph"] for row in block["rows"]] == [
        threads.TASK_GLYPHS["open"],
        threads.TASK_GLYPHS["dropped"],
        threads.TASK_GLYPH_UNKNOWN,
    ]
    assert [row["id"] for row in block["rows"]] == ["T-a", "T-b", "T-c"]


def test_an_unknown_task_block_state_is_said_not_rendered_as_declared():
    """K-round-3 nit: `tasks["state"]` outside the four the projection emits
    raises a named error (like an unrenderable derived kind) instead of
    falling through to the `declared` list shape."""
    with pytest.raises(ValueError) as caught:
        task_pane._task_block({"state": "wibble", "rows": []})
    message = str(caught.value)
    assert "'wibble'" in message
    assert "task pane cannot render task-block state" in message
