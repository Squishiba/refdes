"""Threads Phase 3b: rendering a thread on its entries' pages.

docs/design/threads.md §8's "Rendering" row: a chain view reusing the log
timeline rendering, plus a "currently concludes" panel sourced from the
chain fold. The panel shows verdict fields only (decided 2026-09-14): the
thread's folded value of each decision-style field some entry declares
(`status`, `rationale`, `options`, `checks`) and its folded `satisfies`,
`selects`, `constrained_by` links — each attributed to the entry the value
came from. Narrative fields (`date`, `author`, `summary`, body) stay in the
timeline, never in the panel.

The schema here declares `follows:` by hand — `hardware@3` does not declare
it yet (that's the standard-layer phase) — so every project in this file is
the "any project whose schema declares it" case §7 describes.
"""

from __future__ import annotations

import os

from conftest import write_project_config

from refdes import build as build_mod
from refdes import chains, keys as keys_mod, parse, render
from refdes.schema import load_project

THREAD_SCHEMA = """\
site: { title: Thread Render, out: _site }
id: { width: 3, ledger: .refdes/ids.yaml }
link_types:
  follows: { inverse: followed_by, label: Follows }
  satisfies: { inverse: satisfied_by, label: Satisfies }
  selects: { inverse: selected_by, label: Selects }
  constrained_by: { inverse: constrains, label: Constrained by }
types:
  log:
    prefix: LOG
    label: Log entry
    plural: Log entries
    fields:
      date: { type: date }
      summary: { type: text, required: true }
      author: { type: person }
      status: { type: enum, choices: [proposed, accepted, on_hold] }
      rationale: { type: text }
      options: { type: options }
      checks: { type: checks }
    links:
      follows: [log]
      satisfies: [requirement]
      selects: [component]
      constrained_by: [bound]
  requirement:
    prefix: REQ
    label: Requirement
    plural: Requirements
    fields:
      summary: { type: text }
  component:
    prefix: CMP
    label: Component
    plural: Components
    fields:
      summary: { type: text }
  bound:
    prefix: BND
    label: Bound
    plural: Bounds
    fields:
      summary: { type: text }
"""

REFS = (
    "defaults: { type: requirement }\n"
    "items:\n"
    "  - id: REQ-001\n    summary: The rail regulation requirement.\n"
    "  - id: REQ-002\n    summary: The thermal requirement.\n"
)


def _render(tmp_path, items_yaml, refs=REFS):
    write_project_config(tmp_path, THREAD_SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    (items / "reqs.yaml").write_text(refs, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys_mod.mint_missing(project)
    build_mod.build(project)
    out = render.render_site(project)
    return project, out


def _page(out, name):
    with open(os.path.join(out, f"{name}.html"), encoding="utf-8") as fh:
        return fh.read()


def panel(html: str) -> str:
    """The "currently concludes" panel's own markup, or "" when absent."""
    start = html.find('<div class="thread-concludes">')
    if start < 0:
        return ""
    end = html.find('<ol class="timeline thread-timeline">', start)
    return html[start:end if end > 0 else len(html)]


def timeline(html: str) -> str:
    """The thread timeline's own markup, or "" when absent."""
    start = html.find('<ol class="timeline thread-timeline">')
    if start < 0:
        return ""
    end = html.find("</ol>", start)
    return html[start:end]


# A three-entry linear thread: LOG-001 declares status, LOG-002 is silent on
# it, LOG-003 declares satisfies without restating status.
LINEAR = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    date: 2026-04-01\n    summary: Chose the topology.\n"
    "    author: A. Na\n    status: accepted\n"
    "  - id: LOG-002\n    date: 2026-04-02\n    summary: Bench notes.\n"
    "    author: B. Ob\n    follows: [LOG-001]\n"
    "  - id: LOG-003\n    date: 2026-04-03\n    summary: Concluded.\n"
    "    author: A. Na\n    follows: [LOG-002]\n    satisfies: [REQ-001]\n"
)


def test_panel_shows_status_from_the_latest_declaring_entry(tmp_path):
    """The value comes from the latest entry that declared it, attributed to
    that entry — and a silent later entry does not clear it (LOG-002 and
    LOG-003 never restate `status`)."""
    _project, out = _render(tmp_path, LINEAR)
    body = panel(_page(out, "log-002"))
    assert "status" in body and "accepted" in body
    # Attributed to LOG-001, the entry that declared it — not to the page's
    # own entry, which never declared anything.
    assert 'href="log-001.html"' in body
    assert 'href="log-002.html"' not in body


def test_a_silent_later_entry_does_not_clear_the_folded_value(tmp_path):
    _project, out = _render(tmp_path, LINEAR)
    for page in ("log-001", "log-002", "log-003"):
        body = panel(_page(out, page))
        assert "accepted" in body, page


def test_panel_shows_satisfies_from_the_nearest_declaring_entry(tmp_path):
    """The link fold walks to the nearest entry declaring that link name and
    attributes the targets to it."""
    _project, out = _render(tmp_path, LINEAR)
    body = panel(_page(out, "log-002"))
    assert "satisfies" in body and "REQ-001" in body
    assert 'href="log-003.html"' in body  # LOG-003 is the declaring entry


def test_narrative_fields_are_not_in_the_panel(tmp_path):
    """date/author/summary stay in the timeline; the panel is verdicts only."""
    _project, out = _render(tmp_path, LINEAR)
    body = panel(_page(out, "log-002"))
    assert body  # a panel exists on a thread page
    for narrative in ("2026-04-01", "2026-04-02", "A. Na", "B. Ob", "Bench notes"):
        assert narrative not in body


def test_forked_thread_panel_says_so_names_the_tips_and_folds_nothing(tmp_path):
    _project, out = _render(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    date: 2026-04-01\n    summary: Head.\n    status: accepted\n"
        "  - id: LOG-002\n    date: 2026-04-02\n    summary: Branch A.\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    date: 2026-04-03\n    summary: Branch B.\n    follows: [LOG-001]\n",
    )
    body = panel(_page(out, "log-001"))
    assert "forked" in body
    assert 'href="log-002.html"' in body and 'href="log-003.html"' in body
    # No folded values while forked — not even the head's own declaration.
    assert "accepted" not in body
    assert "<dl>" not in body


def test_timeline_lists_every_thread_entry_in_date_order_with_current_marked(tmp_path):
    """Including an id-less entry, which links by its key and shows a
    readable label."""
    project, out = _render(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-002\n    date: 2026-04-02\n    summary: Second.\n    follows: [LOG-001]\n"
        "  - id: LOG-001\n    date: 2026-04-01\n    summary: First.\n"
        "  - date: 2026-04-03\n    summary: Id-less third.\n    follows: [LOG-002]\n",
    )
    key = next(i.key for i in project.items.values() if not i.id)
    body = timeline(_page(out, "log-002"))
    positions = [
        body.find(needle)
        for needle in ('href="log-001.html"', 'href="log-002.html"', f'href="{key}.html"')
    ]
    assert -1 not in positions and positions == sorted(positions)
    assert "Id-less third." in body
    # The current page's own entry is marked, and only it.
    assert body.count("tl-current") == 1
    current = body.split('class="tl-entry tl-current"')[1]
    assert 'href="log-002.html"' in current.split('class="tl-entry')[0]


def test_an_id_less_entry_with_no_summary_is_labelled_by_key(tmp_path):
    project, out = _render(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    date: 2026-04-01\n    summary: First.\n"
        "  - date: 2026-04-02\n    follows: [LOG-001]\n",
    )
    key = next(i.key for i in project.items.values() if not i.id)
    body = timeline(_page(out, "log-001"))
    assert f'href="{key}.html"' in body
    assert f"entry {key}" in body


def test_an_item_not_in_a_thread_renders_no_thread_section(tmp_path):
    _project, out = _render(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    date: 2026-04-01\n    summary: A lone entry.\n"
        "  - id: LOG-002\n    date: 2026-04-02\n    summary: Another lone entry.\n",
    )
    for page in ("log-001", "log-002"):
        html = _page(out, page)
        assert '<section class="thread">' not in html
        assert panel(html) == "" and timeline(html) == ""


# ------------------------------------------------------- chain helper additions


def test_resolve_current_with_source_attributes_the_source_entry(tmp_path):
    project, _out = _render(tmp_path, LINEAR)
    value, source = chains.resolve_current_with_source(
        project, project.item_by_id("LOG-002"), "status"
    )
    assert value == "accepted"
    assert source is project.item_by_id("LOG-001")


def test_resolve_current_link_with_source_returns_targets_and_source(tmp_path):
    project, _out = _render(tmp_path, LINEAR)
    targets, source = chains.resolve_current_link_with_source(
        project, project.item_by_id("LOG-001"), "satisfies"
    )
    assert [i.id for i in targets] == ["REQ-001"]
    assert source is project.item_by_id("LOG-003")


def test_thread_entries_walks_both_directions_in_date_order(tmp_path):
    project, _out = _render(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-003\n    date: 2026-04-03\n    summary: Third.\n    follows: [LOG-002]\n"
        "  - id: LOG-001\n    date: 2026-04-01\n    summary: First.\n"
        "  - id: LOG-002\n    date: 2026-04-02\n    summary: Second.\n    follows: [LOG-001]\n",
    )
    entries = chains.thread_entries(project, project.item_by_id("LOG-002"))
    assert [i.id for i in entries] == ["LOG-001", "LOG-002", "LOG-003"]


def test_thread_entries_of_a_lone_item_is_just_it(tmp_path):
    project, _out = _render(
        tmp_path,
        "defaults: { type: log }\nitems:\n  - id: LOG-001\n    date: 2026-04-01\n    summary: Lone.\n",
    )
    entries = chains.thread_entries(project, project.item_by_id("LOG-001"))
    assert [i.id for i in entries] == ["LOG-001"]
