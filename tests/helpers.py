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
    project = load_project(config_path=os.path.join(REPO, "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


# ----------------------------------------------------------------- coverage


COVERAGE_SCHEMA = """\
site: {title: "Coverage Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
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
    project = load_project(config_path=str(root / "refdes.yaml"))
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
    (tmp_path / "refdes.yaml").write_text(NUMERIC_HINT_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _build_at(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
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


CHECK_SEVERITY_SCHEMA = """\
site: {title: "Check Severity Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
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
    (tmp_path / "refdes.yaml").write_text(CHECK_SEVERITY_SCHEMA, encoding="utf-8")
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
        "```calc\nCLIM : A = 0.697 A\n```\n",
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
    "    datasheets:\n      - url: https://example.com/datasheet.pdf\n"
)


def _lc_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    return project


def _pin_lifecycle_citation(root) -> None:
    (root / ".refdes").mkdir(exist_ok=True)
    (root / ".refdes" / "citations.yaml").write_text(
        "citations:\n"
        "  https://example.com/datasheet.pdf:\n"
        "    sha256: deadbeef\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    vendored: false\n",
        encoding="utf-8",
    )


# ------------------------------------------------------------- generated blocks

BLOCKS_SCHEMA = """\
site: {title: "Blocks Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
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
history: {default: invalidate}
units: {preferred: []}
item_layout: workspace
workspaces:
  alpha: {label: Alpha}
  beta: {label: Beta}
boards:
  main: {label: Main}
link_types:
  equivalent: { inverse: equivalent, label: "Equivalent" }
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
      equivalent: [component]
      alternate:  [component]
    body: { on_change: invalidate }
"""


def _build_at_repo_schema():
    """A real project resolving the bundled hardware@2 standard, for
    refdes new / JSON schema tests that need its actual field shapes."""
    return load_project(config_path=os.path.join(REPO, "refdes.yaml"))
