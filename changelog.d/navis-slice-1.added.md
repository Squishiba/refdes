# Navis slice 1: grammar, body scan, model, read-only CLI

A Navi is one flying note: a hand-authored single-line
`<!--navi: text-->` comment in an item body. Slice 1 of the design
(in-prog-logs/navis-design-20261025.md) lands the closed grammar, the body
scan into `Item.navis`, malformed-marker warning diagnostics, the top-level
`navis` key of the `index` payload (absent-key convention), and the
read-only `refdes navis ls|all|show` CLI. Keys are minted, archived, and
surfaced in site panels by later slices; nothing here writes a key.

Markers are consumed from published item HTML (their bytes never appear in
the rendered page), and inert occurrences — inside fenced code, indented
code, inline code spans, and open HTML comments — are left exactly as
written. The scan mutates no `Item.body` and enters no hash, seal, or
history input: `refdes check`, `refdes index`, and `refdes build` are
byte-identical against the previous release on projects with no Navis, and
on a project with Navis the only deltas are the marker consumption, the
`navis` payload key, and the malformed-marker warnings.
