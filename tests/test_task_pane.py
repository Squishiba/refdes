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

from conftest import write_project_config

from refdes import build as build_mod
from refdes import keys as keys_mod
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


def _render(tmp_path, items_yaml, with_pages=False):
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
    """One tab panel's own markup."""
    marker = f'id="refdes-taskpane-panel-{index}"'
    start = html.find(marker)
    assert start >= 0, marker
    start = html.rfind("<div", 0, start)
    return html[start : html.find("</div>", start)]


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
    assert "hidden" in body[: body.find("\n")]


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
    assert "Tasks at LOG-002:" in body and "Tasks at LOG-003:" in body
    assert "Tasks at tip:" not in body  # the single-tip heading never lies here


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
    assert "Verdict: conflicting" in body
    assert "Tasks at tip: task reconciliation required" in body
    # and it refuses to invent a winner either way
    assert "T-a" not in body and "T-b" not in body


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


def test_the_verdict_line_is_the_cli_line(tmp_path):
    _project, out = _render(tmp_path, ONE_TIP)
    body = pane(_page(out, "log-002"))
    assert (
        "Verdict: accepted (LOG-002, 2026-09-02), 1 open task remaining below"
        in body
    )


# ------------------------------ §7a (4): derived, collapsed, labelled, plain


def test_the_derived_section_is_collapsed_labelled_and_uncheckable(tmp_path):
    _project, out = _render(tmp_path, ONE_TIP)
    body = pane(_page(out, "log-002"))
    open_at, close_at = body.find("<details"), body.find(">", body.find("<details"))
    tag = body[open_at : close_at + 1]
    assert tag == '<details class="refdes-taskpane-derived">'  # no `open`: collapsed
    assert "<summary>Derived (auto clears when fixed)</summary>" in body
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
        "Coverage", "Blocked", "Failing checks", "Citations",
    ]
    # the one order #194 will align with, spelled once (§7a 4)
    assert threads.DERIVED_GROUP_ORDER == (
        "coverage", "verdict", "blocked", "check", "citation", "fork",
    )
    assert groups[1]["rows"] == ["DEC-002  by DEC-001 (proposed)"]
    assert groups[2]["rows"] == ["LOG-002  P_diss violates BND-001"]


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
    assert out


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
