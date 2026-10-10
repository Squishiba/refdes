"""Shared fixtures data, constants, and build helpers used by more than one test module.

Split out of the original monolithic tests/test_refdes.py. Anything used by a
single test module lives in that module instead -- this file is only for the
genuinely shared surface.
"""

from __future__ import annotations

import os

from refdes import build as build_mod
from refdes import parse, render
from refdes.schema import load_project

REPO = os.path.join(os.path.dirname(__file__), "..")


# -------------------------------------------------------------------- on_change


def _project():
    project = load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


# ----------------------------------------------------------------- coverage


COVERAGE_SCHEMA = """\
site: {title: "Coverage Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
on_change: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    label: Decision
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [proposed, accepted, on_hold], default: proposed, on_change: invalidate }
    links:
      satisfies: [requirement]
    satisfying_statuses: [accepted]
    body: { on_change: invalidate }
"""


COVERAGE_ITEMS = {
    "req-a.md": """\
---
id: REQ-A-001
type: requirement
text: Needs a settled decision.
---
""",
    "dec-a.md": """\
---
id: DEC-A-001
type: decision
title: Settled choice.
status: accepted
satisfies: [REQ-A-001]
---
""",
    "req-b.md": """\
---
id: REQ-B-001
type: requirement
text: Only claimed so far.
---
""",
    "dec-b.md": """\
---
id: DEC-B-001
type: decision
title: Not settled yet.
status: on_hold
satisfies: [REQ-B-001]
---
""",
}


def _build_and_render(root):
    project = load_project(start=str(root))
    parse.load_items(project)
    build_mod.build(project)
    return render.render_site(project)


# --------------------------------------------- bare-numeric expand-and-freeze (finding 8 Part 1)

NUMERIC_HINT_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n"
)


def _numeric_hint_project(tmp_path, items_yaml):
    # Local import: conftest imports this module at module level, so importing
    # conftest back at module level here would be a cycle. By call time pytest
    # has fully loaded conftest, so this resolves cleanly.
    from conftest import write_project_config

    write_project_config(tmp_path, NUMERIC_HINT_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _build_at(root):
    project = load_project(start=str(root))
    parse.load_items(project)
    build_mod.build(project)
    return project


# ------------------------------------------------------------------------ boards

BOARD_CONFIG = """\
site:
  title: "Board test"
  out: _site
id:
  width: 3
boards:
  board-a:
    label: "Board A"
    token: A
  board-b:
    label: "Board B"
    token: B
types:
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true }
"""


# ------------------------------------------------------------------ per-board seals

SEALED_BOARD_CONFIG = """\
site:
  title: "Seal test"
  out: _site
id:
  width: 3
boards:
  board-a:
    label: "Board A"
  board-b:
    label: "Board B"
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

# The same shape with no `boards:` registry at all -- the case where `audit`'s
# reseal section used to print `[unboarded]`.
SEALED_FLAT_CONFIG = """\
site:
  title: "Seal test"
  out: _site
id:
  width: 3
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""


CHECK_SEVERITY_SCHEMA = """\
site: {title: "Check Severity Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
on_change: {default: invalidate}
units: {preferred: []}
types:
  constraint:
    prefix: CON
    label: Constraint
    fields:
      title: { type: text, required: true, on_change: invalidate }
      limit: { type: limit, required: true, on_change: invalidate }
    body: { on_change: invalidate }
  option:
    prefix: OPT
    label: Option
    check_severity: info
    fields:
      title: { type: text, required: true, on_change: invalidate }
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    label: Decision
    fields:
      title: { type: text, required: true, on_change: invalidate }
    body: { on_change: invalidate }
"""


def _check_severity_project(tmp_path, *, item_type, item_id, prefix, checks_extra=""):
    """One item of `item_type`, with a failing check against CON-IO-004."""
    # Local import: conftest imports this module at module level, so importing
    # conftest back at module level here would be a cycle. By call time pytest
    # has fully loaded conftest, so this resolves cleanly.
    from conftest import write_project_config

    write_project_config(tmp_path, CHECK_SEVERITY_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults: { type: constraint }\n"
        "items:\n"
        "  - id: CON-IO-004\n"
        "    title: Input current budget\n"
        '    limit: "<= 600 mA"\n',
        encoding="utf-8",
    )
    (items / f"{prefix.lower()}.md").write_text(
        "---\n"
        f"id: {item_id}\n"
        f"type: {item_type}\n"
        "title: Candidate under evaluation\n"
        "checks:\n"
        "  - value: CLIM\n"
        "    against: CON-IO-004\n"
        f"{checks_extra}"
        "---\n\n"
        "```calc\nCLIM = 0.697 A | A\n```\n",
        encoding="utf-8",
    )
    return _build_at(tmp_path)


# ------------------------------------------------------------------ lifecycle

LIFECYCLE_SCHEMA = """\
site: { title: "Lifecycle test", out: _site }
id: { width: 3 }
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text:   { type: text, required: true }
      status: { type: enum, choices: [draft, active, retired], default: draft }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
  component:
    prefix: CMP
    fields:
      title:      { type: text, required: true }
      datasheets: { type: citations }
"""


LIFECYCLE_ITEMS = (
    "defaults: { type: requirement }\n"
    "items:\n"
    "  - id: REQ-001\n    text: Uncovered active requirement.\n    status: active\n"
    "  - id: REQ-002\n    text: Draft requirement, exempt from the coverage rules.\n"
    "    status: draft\n"
)


LIFECYCLE_COMPONENT = (
    "defaults: { type: component }\n"
    "items:\n"
    "  - id: CMP-001\n    title: Cites an unfetched datasheet.\n"
    "    datasheets:\n      - path: https://example.com/datasheet.pdf\n"
)


def _lc_build(root):
    project = load_project(start=str(root))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    return project


def _pin_lifecycle_citation(root) -> None:
    (root / ".refdes").mkdir(exist_ok=True)
    (root / ".refdes" / "citations.yaml").write_text(
        "citations:\n"
        "  https://example.com/datasheet.pdf:\n"
        "    sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n",
        encoding="utf-8",
    )


# ------------------------------------------------------------------- real PDFs
#
# The PDF reader's tests need *real* PDF bytes, because the thing under test is
# what pypdf makes of a page: a stub would only prove that this module can read
# its own dict. So the fixture is a real, minimal PDF -- a catalog, a page tree,
# one Type1 base font, and one content stream per page, with a correct xref
# table -- written here rather than pulled in as a binary fixture, so a test can
# say "a table row at y=640 with these three numbers" and have the page really
# contain it. `tests/test_citation_sections.py` needs only bookmarks, which
# pypdf's own writer builds more conveniently, so it keeps using that.

PAGE_WIDTH = 612
PAGE_HEIGHT = 792


def pdf_escape(text: str) -> str:
    """`text` as a PDF literal string's body."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def pdf_run(x: float, y: float, text: str, size: float = 9.0) -> str:
    """One positioned text run, as a content-stream fragment.

    A separate `BT`/`ET` per run is deliberate: pypdf's `visitor_text` reports
    each of these as its own run with its own text matrix, which is the shape a
    datasheet's table cells arrive in and the shape row grouping has to cope
    with. Real producers also emit several runs per line and several lines per
    `BT` block, and the tests cover both.
    """
    return (
        f"BT /F1 {size:g} Tf 1 0 0 1 {x:g} {y:g} Tm ({pdf_escape(text)}) Tj ET\n"
    )


def pdf_page(*runs: str) -> str:
    """A page's content stream: the runs, in the order they are painted."""
    return "".join(runs)


def pdf_bytes(*pages: str) -> bytes:
    """A real PDF file, one content stream per page, as bytes.

    Letter-size, Helvetica, no compression, no object streams -- the smallest
    thing pypdf will read that still has real pages, real fonts and real text
    operators, which is all the extraction path looks at.
    """
    contents = [page if isinstance(page, str) else "".join(page) for page in pages]
    objects: dict[int, bytes] = {}
    page_ids = []
    next_id = 4
    for _ in contents:
        page_ids.append((next_id, next_id + 1))
        next_id += 2
    kids = " ".join(f"{pid} 0 R" for pid, _contents in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(contents)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for index, (page_id, content_id) in enumerate(page_ids):
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode()
        stream = contents[index].encode("latin-1", "replace")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"endstream"
        )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    start = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode()
    out += b"0000000000 65535 f \n"
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\n"
        f"startxref\n{start}\n%%EOF\n"
    ).encode()
    return bytes(out)


# ------------------------------------------------------------- generated blocks

BLOCKS_SCHEMA = """\
site: {title: "Blocks Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
on_change: {default: invalidate}
units: {preferred: []}
boards:
  power: {label: Power}
  thermal: {label: Thermal}
link_types:
  satisfies:      { inverse: satisfied_by, label: "Satisfies" }
  constrained_by: { inverse: constrains,   label: "Constrained by" }
  verifies:       { inverse: verified_by,  label: "Verifies" }
  selects:        { inverse: selected_by,  label: "Selects", trace: false }
types:
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  constraint:
    prefix: CON
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    fields:
      title:          { type: text, required: true, on_change: invalidate }
      status:         { type: enum, choices: [proposed, accepted, on_hold], default: proposed, on_change: invalidate }
      schematic_page: { type: text, on_change: invalidate }
      tags:           { type: list, on_change: ignore }
      checks:         { type: checks, on_change: invalidate }
    links:
      satisfies:      [requirement]
      constrained_by: [constraint]
      selects:        [component]
    body: { on_change: invalidate }
  test:
    prefix: TST
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links:
      verifies: [requirement]
    body: { on_change: invalidate }
"""


BLOCKS_ITEMS = {
    "req-001.md": """\
---
id: REQ-001
type: requirement
text: Input voltage range.
---
""",
    "con-001.md": """\
---
id: CON-001
type: constraint
title: Thermal budget.
---
""",
    "cmp-001.md": """\
---
id: CMP-001
type: component
title: TPS62913.
---
""",
    "dec-001.md": """\
---
id: DEC-001
type: decision
title: Buck topology.
status: accepted
schematic_page: "12"
tags: [layout, review]
board: power
satisfies: [REQ-001]
constrained_by: [CON-001]
selects: [CMP-001]
---
""",
    "dec-002.md": """\
---
id: DEC-002
type: decision
title: Inductor choice.
status: proposed
schematic_page: "7"
tags: [review]
board: power
---
""",
    "dec-003.md": """\
---
id: DEC-003
type: decision
title: Enclosure material.
status: on_hold
schematic_page: "12"
board: thermal
---
""",
    "tst-001.md": """\
---
id: TST-001
type: test
title: Load regulation sweep.
verifies: [REQ-001]
---
""",
}


# ------------------------------------------------ parts indexing and equivalence

PARTS_SCHEMA = """\
site: {title: "Parts Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
on_change: {default: invalidate}
units: {preferred: []}
item_layout: workspace
workspaces:
  alpha: {label: Alpha}
  beta: {label: Beta}
boards:
  main: {label: Main}
link_types:
  drop_in:    { inverse: drop_in,    label: "Drop-in" }
  alternate:  { inverse: alternate,  label: "Alternate" }
types:
  component:
    prefix: CMP
    fields:
      title:       { type: text, required: true, on_change: invalidate }
      part_number: { type: text, on_change: invalidate }
      rationale:   { type: text, on_change: invalidate, required_when: {links: alternate} }
      datasheets:  { type: citations, on_change: invalidate }
    links:
      drop_in:    [component]
      alternate:  [component]
    body: { on_change: invalidate }
"""


def _build_at_repo_schema():
    """A real project resolving the bundled hardware@2 standard, for
    refdes new / JSON schema tests that need its actual field shapes."""
    return load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
