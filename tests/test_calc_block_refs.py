"""`[[ID#calc:name]]` fragment references, Phase 2
(docs/design/named-calc-blocks.md §5.3, §7, §10).

A `#calc:` fragment is a `#field` fragment with a namespace prefix: it links to
one named calc block's table on the target's page, never inlines it, and a miss
is a warning -- never an error, because a broken prose link must not fail a
build (§11.9 decided).

Sabotage-style: each test names the mutation that would falsify it. The anchor
test fails if the href drifts off the id Phase 1 actually emits; the warning
tests fail if a miss goes quiet, gets promoted to an error, or loses the names
the target *does* have; the fig:/cite: test fails if the `#calc:` form is
handled differently from the `#field` form already there.
"""

from __future__ import annotations

import os

from conftest import write_project_config
from helpers import _build_and_render, _build_at

from refdes import cli as cli_mod

SCHEMA = """\
site: {title: "Calc Fragment Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
types:
  component:
    prefix: CMP
    fields:
      title:      { type: text, required: true }
      datasheets: { type: citations }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
"""

# DEC-001 is §8.1's item: two named blocks, declared in the order §7's warning
# lists them (`it names: losses, supply`), so the message can be asserted
# message-for-message. DEC-002 is the prose that points at one of them, and
# carries the figure the fig:/cite: tests hang a fragment on (a `[[fig:...]]`
# resolves only inside the document that declares it).
TWO_BLOCKS = """\
---
id: DEC-001
type: decision
title: 3V3 rail regulator topology
---

```calc id="losses"
P_diss = 3.3 V * 0.5 A | W
```

```calc id="supply"
V_out = 3.3 V
I_load = 0.5 A
```
"""

# Same item, one block, no name on the fence.
UNNAMED_BLOCK = """\
---
id: DEC-001
type: decision
title: 3V3 rail regulator topology
---

```calc
P_diss = 3.3 V * 0.5 A | W
```
"""

# Same id, nothing computed: neither §7 shape ("it names: ..." / "none is
# named") is true of this target.
NO_BLOCKS = """\
---
id: DEC-001
type: decision
title: A decision with no arithmetic
---

Prose only.
"""

CITATION_ITEM = """\
---
id: CMP-001
type: component
title: TPS62913.
datasheets:
  - path: https://example.com/ds.pdf
    rev: C
    id: ds-main
---
"""


def _project(tmp_path, dec_body, owner=TWO_BLOCKS):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "dec-001.md").write_text(owner, encoding="utf-8")
    (items / "cmp-001.md").write_text(CITATION_ITEM, encoding="utf-8")
    figures = items / "figures"
    figures.mkdir(exist_ok=True)
    (figures / "curve.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (items / "dec-002.md").write_text(
        "---\nid: DEC-002\ntype: decision\ntitle: Thermal re-check.\n---\n\n"
        f"{dec_body}\n\n"
        '![the curve](figures/curve.png){id="fig-curve" caption="Efficiency"}\n',
        encoding="utf-8",
    )
    return tmp_path


def _html(tmp_path, body, owner=TWO_BLOCKS) -> str:
    out = _build_and_render(_project(tmp_path, body, owner))
    return open(os.path.join(out, "dec-002.html"), encoding="utf-8").read()


def _site(tmp_path, body, owner=TWO_BLOCKS):
    """Build through the CLI so a test can assert the process exit code."""
    root = _project(tmp_path, body, owner)
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), "build"]), root


# ------------------------------------------------------------------- resolving


def test_calc_fragment_links_to_anchor(tmp_path):
    """§5.3: `[[DEC-001#calc:losses]]` links to the `#calc-losses` anchor
    Phase 1 puts on that block's table, on DEC-001's own page. Sabotage: an
    href spelled `#calc:losses`, `#losses`, or `#field-calc:losses` fails
    here, and so does a link that lands on the page with no fragment at all."""
    html = _html(tmp_path, "The dissipation argument is in [[DEC-001#calc:losses]].")
    assert 'href="dec-001.html#calc-losses"' in html
    assert ">DEC-001#calc:losses</a>" in html
    assert "[[DEC-001#calc:losses]]" not in html
    # Sabotage pair: the target page really carries that id.
    out = _build_and_render(_project(tmp_path, "Plain body."))
    target = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert '<table class="calc" id="calc-losses">' in target


def test_calc_fragment_custom_text(tmp_path):
    """`[[ID#calc:name|custom text]]` works like `[[ID#field|the MPN]]`.
    Sabotage: a label swallowed by the fragment group, or a fragment group
    that stops matching once a `|` follows, leaves the raw `[[...]]` on the
    page."""
    html = _html(
        tmp_path,
        "See [[DEC-001#calc:losses|DEC-001's losses calculation]] for the numbers.",
    )
    assert 'href="dec-001.html#calc-losses"' in html
    assert ">DEC-001's losses calculation</a>" in html
    assert "[[" not in html


def test_calc_fragment_never_inlines(tmp_path):
    """It links; it never inlines (§5.3, inherited whole from `#field`).
    Sabotage: a resolver that substituted the block's rows or its value into
    the referring sentence -- the divergence `docs/math.md` opens with."""
    html = _html(tmp_path, "See [[DEC-001#calc:losses]].")
    # DEC-001's row content must not appear on DEC-002's page at all, and the
    # reference must still be an inline link in its sentence, not a table.
    assert "P_diss" not in html
    sentence = html.split('<div class="body">')[1].split("</div>")[0]
    assert "<table" not in sentence
    assert 'href="dec-001.html#calc-losses"' in sentence


def test_field_fragments_still_resolve(tmp_path):
    """Regression on the mechanism this extends: a bare `#field` fragment must
    keep resolving exactly as before, and must not be read as a calc name.
    Sabotage: dispatching every fragment through the block-name lookup would
    warn on `#title` here."""
    html = _html(tmp_path, "See [[DEC-002#title]].")
    assert 'href="dec-002.html#field-title"' in html


# ------------------------------------------------------------------- the misses


def test_calc_fragment_unknown_name_warns(tmp_path):
    """§7's first warning, message for message: the names the item DOES have.
    Sabotage: a miss that goes silent, one that fails the build, or one that
    says only "no such block" without the names to fix it with."""
    root = _project(tmp_path, "See [[DEC-001#calc:loess]].")
    project = _build_at(root)
    msg = next(d.message for d in project.warnings if "loess" in d.message)
    assert msg == (
        "[[DEC-001#calc:loess]]: DEC-001 has no calc block named 'loess' "
        "(it names: losses, supply)."
    )
    # A warning, never an error (§11.9): the build still exits 0.
    code, _ = _site(tmp_path, "See [[DEC-001#calc:loess]].")
    assert code == 0
    # And the reference's own text stays visible, in red, with no anchor.
    html = _html(tmp_path, "See [[DEC-001#calc:loess]].")
    assert '<span class="ref ref-missing" title="unknown calc block">' in html
    assert ">DEC-001#calc:loess</span>" in html
    assert "#calc-loess" not in html
    assert "[[" not in html


def test_calc_fragment_on_unnamed_block_warns(tmp_path):
    """§7's second warning shape: the target has blocks, none named -- the fix
    is on the fence, not in the reference. Sabotage: reusing the first shape
    with an empty "(it names: )", or treating an unnamed block as no block."""
    root = _project(tmp_path, "See [[DEC-001#calc:losses]].", owner=UNNAMED_BLOCK)
    project = _build_at(root)
    msg = next(d.message for d in project.warnings if "calc:losses" in d.message)
    assert msg == (
        '[[DEC-001#calc:losses]]: DEC-001 has calc blocks but none is named '
        '-- add id="..." to its fence to make this link work.'
    )
    code, _ = _site(tmp_path, "See [[DEC-001#calc:losses]].", owner=UNNAMED_BLOCK)
    assert code == 0


def test_calc_fragment_on_item_with_no_blocks_warns(tmp_path):
    """Neither §7 shape is true of a target that computes nothing, and the
    reference must not go quiet either: same level, a fix that fits this
    target. Sabotage: an empty name list, or "none is named" on an item with
    no fences at all."""
    root = _project(tmp_path, "See [[DEC-001#calc:losses]].", owner=NO_BLOCKS)
    project = _build_at(root)
    msg = next(d.message for d in project.warnings if "calc:losses" in d.message)
    assert msg == (
        '[[DEC-001#calc:losses]]: DEC-001 has no calc blocks -- a #calc: '
        'fragment names a ```calc block given id="...", and this item computes '
        "nothing."
    )
    assert "it names:" not in msg


def test_calc_fragment_on_fig_or_cite_warns(tmp_path):
    """§5.3: a `#calc:` fragment on `[[fig:...]]`/`[[cite:...]]` stays the
    warning `#field` already produces there -- same message, same level, with
    only the fragment text differing. Sabotage: a `#calc:` branch that
    resolves against nothing, silently drops the fragment, or words the
    warning differently from the form beside it."""
    for envelope, fragment_free in (("fig:fig-curve", "title"), ("cite:ds-main", "page")):
        field_miss = _warnings(tmp_path, f"See [[{envelope}#{fragment_free}]].")
        calc_miss = _warnings(tmp_path, f"See [[{envelope}#calc:losses]].")
        assert len(field_miss) == 1, (envelope, field_miss)
        assert len(calc_miss) == 1, (envelope, calc_miss)
        assert calc_miss[0] == field_miss[0].replace(
            f"#{fragment_free}", "#calc:losses"
        )


def _warnings(tmp_path, body):
    project = _build_at(_project(tmp_path, body))
    return [d.message for d in project.warnings if "fragment" in d.message]


def test_unknown_fragment_namespace_warns(tmp_path):
    """`#blox:losses` is not a namespace this project has. Before the fragment
    group admitted a colon the whole reference failed to match and reached the
    page as literal text -- silence on a typo. Sabotage: resolving it as a
    field name, or leaving `[[...]]` on the page."""
    root = _project(tmp_path, "See [[DEC-001#blox:losses]].")
    project = _build_at(root)
    msg = next(d.message for d in project.warnings if "blox:losses" in d.message)
    assert "the only" not in msg  # not a lecture; one sentence naming both kinds
    assert "field name declared on 'decision'" in msg
    assert "calc:<name>" in msg
    html = _html(tmp_path, "See [[DEC-001#blox:losses]].")
    assert "[[" not in html
    assert "#calc-losses" not in html


def test_warning_is_attributed_like_a_field_miss(tmp_path):
    """The diagnostic is attributed to the referring item -- the same file,
    item and line a `#field` miss on the same line gets, because it goes
    through the same `project.warn` call. Sabotage: a warning with no file/line
    is a warning nobody can find, and one pointed at the *target* is a lie."""
    miss = _build_at(_project(tmp_path, "See [[DEC-001#calc:loess]]."))
    diag = next(d for d in miss.warnings if "loess" in d.message)
    assert (diag.file, diag.item_id) == ("items/dec-002.md", "DEC-002")
    field_miss = _build_at(_project(tmp_path, "See [[DEC-001#no_such_field]]."))
    fdiag = next(d for d in field_miss.warnings if "no_such_field" in d.message)
    assert (diag.file, diag.item_id, diag.line) == (
        fdiag.file, fdiag.item_id, fdiag.line
    )
