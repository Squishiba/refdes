# A flow-style YAML list file now names why the key cannot be minted

A list file whose whole list is a flow sequence — `items: [{id: NOTE-001,
title: Flow, body: "..."}]` — has no line the minted `key:` can be written
into. The mint kept it an ERROR (an item with no key may not persist), but
the bare `could not write key ... back into the source` message gave no
way out; the same refusal on the markdown side has always named its shape.
The YAML message now reads `key cannot be added to this flow-style list;
rewrite it in block style (one `- id:` entry per line)`, matching the
front-matter wording. The bytes are untouched in every such run, and the
flow-map-inside-a-block-list shape (`- {id: ..., ...}` on one line, key
minted inside the braces) is unchanged.
