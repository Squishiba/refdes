---
defaults:
  type: decision
  prefix: DEC-B
  owner: J. Bin
---
key: 0ytcjcwycvy
id: DEC-B-001
title: Reuse Board A's regulator topology
status: accepted
date: 2026-04-02
satisfies: [REQ-B-PWR-001@bv170ga0xfk]
---

Board B draws less current than Board A off the same rail, so DEC-PWR-001's
synchronous buck choice carries over unmodified rather than being re-derived.

---
key: t8818c96yb8
id: DEC-B-002
title: Separate enclosure thermal budget, not yet accepted
status: proposed
date: 2026-04-02
---

Board B shares Board A's enclosure but not its airflow path. Whether
CON-THM-001 applies unmodified, or Board B needs its own constraint, is open.
