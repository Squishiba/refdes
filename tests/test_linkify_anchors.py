"""The page linkifier must not re-link text that is already inside an anchor.

`{{tree}}` renders `tree.render_tree_html`'s markup, and that markup is *already
linked* -- it is the same HTML `tree.html` shows, where every item id is the
text of an `<a class="ref">`. The page linkifier then swept over the whole page,
found those ids again, and wrapped them a second time:

    <a class="ref" href="grp-001.html" data-ref="<a class="ref" href="grp-001.html"
    data-ref="GRP-001">GRP-001</a></a>

An anchor start tag inside another anchor start tag: `data-ref` carries a
fragment of markup, a stray `ref` attribute appears, and the row is no longer the
markup the tree page shows. `_linkify` already refused to touch `<pre>` and
`<code>` for exactly this reason -- code is already-marked-up text too -- and
already avoided re-sweeping its own replacement HTML; an `<a>` region is the same
rule under another name.

A tag-depth scan does not catch this, which is part of why it survived: the
inner `>` closes the outer tag first, so the inner `<a` never registers as a
nested element. The regex below is the check that does see it.

The other half of the contract is what must *not* change. An id inside an item
title -- `<span class="muted">Top-level requirement, satisfied by REQ-001.</span>`
-- is ordinary page text the linkifier has always linked, anchor or no anchor,
and a fix that skipped too much would lose it. Both halves are asserted here.
"""

from __future__ import annotations

import os
import re

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import render
from refdes import tree as tree_mod

# An `<a` appearing before the tag it started in has closed: markup inside markup.
NESTED_ANCHOR = re.compile(r"<a\b[^>]*<a\b", re.IGNORECASE)

CONFIG = """\
site: {title: "Nested anchors", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
boards:
  power: {label: "Power"}
link_types:
  part_of: { inverse: contains, label: "Part of" }
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
      schematic_page: { type: text }
    links:
      part_of: [group]
      satisfies: [requirement]
  group:
    prefix: GRP
    coverable: false
    fields:
      title: { type: text, required: true }
    links:
      part_of: [group]
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
      status: { type: enum, choices: [proposed, accepted], default: proposed }
    links:
      part_of: [group]
"""

BASE_ITEMS = {
    "grp.md": """\
---
id: GRP-001
type: group
title: Power group.
---
""",
    "power/req-001.md": """\
---
id: REQ-001
type: requirement
text: Input voltage range.
schematic_page: "12"
board: power
part_of: [GRP-001]
satisfies: [REQ-003]
---

```calc
v = 3.3 V
```
""",
    "power/req-002.md": """\
---
id: REQ-002
type: requirement
text: Second requirement.
schematic_page: "7"
board: power
part_of: [GRP-001]
---
""",
    "req-003.md": """\
---
id: REQ-003
type: requirement
text: Top-level requirement.
schematic_page: "1"
---

Prose in an item body: [[REQ-001]] and bare REQ-002.
""",
    "dec-001.md": """\
---
id: DEC-001
type: decision
title: Buck topology.
status: accepted
part_of: [GRP-001]
---
""",
}

# One page carrying every generated block plus prose that must keep linking: an
# explicit reference, a bare id, a fragment reference, a missing reference, a
# page link, and an id inside inline code that must stay unlinked.
PAGE = """\
# Overview

Prose: [[REQ-001]], bare REQ-002, [[REQ-001#text]], a reference to nothing
([[REQ-404]]), a [page link](details.md), and an id in code that stays put:
`REQ-002`.

## Tree

{{tree}}

## Index

{{index by="status" type="decision"}}

{{index by="schematic_page" type="requirement"}}

## Cascade

{{cascade from="REQ-001" direction="both"}}

## Compare

{{compare type="decision"}}
"""

DETAILS = "# Details\n\nMentions REQ-003 and [[DEC-001]].\n"


def _write_project(root, items) -> None:
    write_project_config(root, CONFIG)
    for relpath, text in items.items():
        path = os.path.join(str(root), "items", relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    pages = os.path.join(str(root), "pages")
    os.makedirs(pages, exist_ok=True)
    with open(os.path.join(pages, "overview.md"), "w", encoding="utf-8") as fh:
        fh.write(PAGE)
    with open(os.path.join(pages, "details.md"), "w", encoding="utf-8") as fh:
        fh.write(DETAILS)


@pytest.fixture
def nested_project(tmp_path):
    """A project whose item titles hold no ids, so the tree block's markup on the
    page can be compared byte for byte against the generator's own output."""
    _write_project(tmp_path, BASE_ITEMS)
    return tmp_path


@pytest.fixture
def title_id_project(tmp_path):
    """The same project with an id inside an item's `text:` -- which the tree
    shows as a title, in text that is not inside an anchor, and which the
    linkifier has always linked."""
    items = dict(BASE_ITEMS)
    items["req-003.md"] = items["req-003.md"].replace(
        "text: Top-level requirement.",
        "text: Top-level requirement, satisfied by REQ-001.",
    )
    _write_project(tmp_path, items)
    return tmp_path


def _build(root):
    project = _build_at(root)
    assert not project.errors, [d.message for d in project.errors]
    render.render_site(project)
    return project


def _read(root, name: str) -> str:
    with open(os.path.join(str(root), "_site", name), encoding="utf-8") as fh:
        return fh.read()


def _tree_region(html: str) -> str:
    """The `<ul class="tree">...</ul>` a page carries, matched by nesting depth
    rather than by a substring the tree's own contents could fake."""
    start = html.index('<ul class="tree">')
    depth = 0
    for match in re.finditer(r"<ul\b|</ul>", html[start:]):
        depth += 1 if match.group(0) == "<ul" else -1
        if depth == 0:
            return html[start : start + match.end()]
    raise AssertionError("unbalanced <ul> in the tree block")


ANY_REF_ANCHOR = re.compile(
    r'<a class="ref" href="[^"]*" data-ref="([A-Z][A-Z0-9-]*)">([^<]*)</a>'
)


# ------------------------------------------------------------- the tree block


def test_a_page_with_a_tree_block_has_no_anchor_inside_an_anchor(nested_project):
    _build(nested_project)
    html = _read(nested_project, "overview.html")
    assert '<ul class="tree">' in html, "the tree block did not render"
    nested = NESTED_ANCHOR.search(html)
    assert not nested, f"an <a> start tag inside another <a>: {nested.group(0)}"


def test_every_anchor_the_tree_page_shows_survives_verbatim(nested_project):
    """The block reuses `render_tree_html`, so every anchor that markup carries
    must reach the page unchanged -- the strongest statement available, since
    the page linkifier *does* legitimately add links of its own (bare ids the
    generator emitted as plain text, like the `(expanded under ...)` hint) and
    that is not what this fix is about."""
    project = _build(nested_project)
    expected = tree_mod.render_tree_html(
        project, board=None, workspace=None, open_depth=tree_mod.DEFAULT_DEPTH
    )
    region = _tree_region(_read(nested_project, "overview.html"))
    anchors = ANY_REF_ANCHOR.findall(expected)
    assert len(anchors) >= 4, f"the generator produced {len(anchors)} anchors"
    assert 'data-ref="<a' not in region, "a tree link was re-wrapped, not kept"
    for item_id, text in anchors:
        anchor = f'<a class="ref" href="{item_id.lower()}.html" data-ref="{item_id}">{text}</a>'
        assert anchor in region, f"the tree's own link to {item_id} was rewritten"


def test_every_reference_anchor_on_the_page_carries_a_bare_id(nested_project):
    """The re-wrap's own fingerprint: an anchor whose `data-ref` is a fragment of
    markup rather than an id. Cheaper to read than the nesting regex, and it
    fails for the same bug."""
    _build(nested_project)
    html = _read(nested_project, "overview.html")
    values = re.findall(r'data-ref="([^"]*)"', html)
    assert values, "no reference anchors on the page at all -- the build is wrong"
    for value in values:
        assert re.fullmatch(r"[A-Z][A-Z0-9-]*", value), f"data-ref is markup: {value!r}"


def test_each_tree_item_is_linked_exactly_once(nested_project):
    _build(nested_project)
    tree_html = _tree_region(_read(nested_project, "overview.html"))
    for item_id in ("GRP-001", "REQ-001", "REQ-002", "DEC-001"):
        anchor = (
            f'<a class="ref" href="{item_id.lower()}.html" '
            f'data-ref="{item_id}">{item_id}</a>'
        )
        assert anchor in tree_html, f"{item_id} lost its link in the tree"
    assert 'data-ref="<a' not in tree_html


def test_the_linked_ids_in_a_tree_row_survive(nested_project):
    """A fix that dropped the tree's own links instead of skipping the re-wrap
    would pass the nested-anchor check and lose the feature."""
    _build(nested_project)
    html = _read(nested_project, "overview.html")
    assert '<a class="ref" href="req-001.html" data-ref="REQ-001">REQ-001</a>' in html
    assert '<a class="ref" href="grp-001.html" data-ref="GRP-001">GRP-001</a>' in html


def test_an_id_in_an_item_title_is_still_linked(title_id_project):
    """The other half of the contract: text that is *not* inside an anchor is
    still the linkifier's business, tree block or not."""
    _build(title_id_project)
    html = _read(title_id_project, "overview.html")
    assert (
        '<span class="muted">Top-level requirement, satisfied by '
        '<a class="ref" href="req-001.html" data-ref="REQ-001">REQ-001</a>.'
        "</span>" in html
    )


# ------------------------------------------------- everything else is untouched


def test_prose_links_on_the_same_page_are_unchanged(nested_project):
    """Explicit, bare, fragment, missing, page and in-code -- one assertion each,
    so a fix that stops at the tree block cannot quietly stop at the first one."""
    _build(nested_project)
    html = _read(nested_project, "overview.html")
    assert '<a class="ref" href="req-001.html" data-ref="REQ-001">REQ-001</a>' in html
    assert '<a class="ref" href="req-002.html" data-ref="REQ-002">REQ-002</a>' in html
    assert (
        '<a class="ref" href="req-001.html#field-text" data-ref="REQ-001">'
        "REQ-001#text</a>" in html
    ), "a fragment reference must still resolve to the field anchor"
    assert (
        '<span class="ref ref-missing" title="unknown item">REQ-404</span>' in html
    ), "a reference to nothing must still be a red span, not a link"
    assert '<a href="details.html">page link</a>' in html
    assert "<code>REQ-002</code>" in html
    tail = html.split("<code>REQ-002</code>")[1]
    assert "REQ-002" not in tail[:200], "an id in code must stay out of the linkifier"


def test_the_index_block_still_links_its_ids(nested_project):
    _build(nested_project)
    html = _read(nested_project, "overview.html")
    index = html[html.index('<table class="index-table">') :]
    assert '<a class="ref" href="dec-001.html" data-ref="DEC-001">DEC-001</a>' in index
    assert '<a class="ref" href="req-002.html" data-ref="REQ-002">REQ-002</a>' in index


def test_the_cascade_block_still_links_its_ids(nested_project):
    _build(nested_project)
    html = _read(nested_project, "overview.html")
    cascade = html[html.index('<ul class="cascade">') :]
    assert '<a class="ref" href="req-003.html" data-ref="REQ-003">REQ-003</a>' in cascade
    assert '<a class="ref" href="grp-001.html" data-ref="GRP-001">GRP-001</a>' in cascade


def test_the_compare_block_still_links_its_ids(nested_project):
    _build(nested_project)
    html = _read(nested_project, "overview.html")
    compare = html[html.index("compare-table") :]
    assert '<a class="ref" href="dec-001.html" data-ref="DEC-001">DEC-001</a>' in compare
    assert 'class="compare-missing"' in compare


def test_an_item_body_still_links_its_own_references(nested_project):
    """Item bodies go through the same `_linkify`."""
    project = _build(nested_project)
    body = project.item_by_id("REQ-003").body_html
    assert '<a class="ref" href="req-001.html" data-ref="REQ-001">REQ-001</a>' in body
    assert '<a class="ref" href="req-002.html" data-ref="REQ-002">REQ-002</a>' in body


def test_the_tree_page_itself_is_unchanged(nested_project):
    """`tree.html` renders the same markup by another route, with no linkify pass
    over it at all."""
    _build(nested_project)
    html = _read(nested_project, "tree.html")
    assert '<a class="ref" href="req-001.html" data-ref="REQ-001">REQ-001</a>' in html
    assert not NESTED_ANCHOR.findall(html)


def test_no_page_in_the_built_site_has_a_nested_anchor(nested_project):
    _build(nested_project)
    site = os.path.join(str(nested_project), "_site")
    for name in sorted(os.listdir(site)):
        if not name.endswith(".html"):
            continue
        html = _read(nested_project, name)
        nested = NESTED_ANCHOR.search(html)
        assert not nested, f"{name} nests an anchor: {nested and nested.group(0)}"
