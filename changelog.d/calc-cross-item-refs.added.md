A calc block can now read another item's value by name:
`V_in = DEC-PWR-001.V_in`, optionally with the pipe unit
(`V_in = DEC-PWR-001.V_in | V`). The reference is a real dependency: calcs
evaluate in dependency order across items, the target is stored expanded as a
`DISPLAY-ID@key` composite and refreshed on rename by the same rule as every
other structured reference, and units and tolerances flow through untouched.
A missing item, a missing name, or a target whose own calc failed is a loud
error at the referring line — never a silent default — and a cycle between
items is an error naming the full path (`calc reference cycle: a -> b -> a`).
The rendered calc table and the index export show the reference readably.
References into imported items are refused with a message. See docs/math.md.
