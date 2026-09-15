# Load-time writes no longer corrupt flow-style Markdown front matter

A Markdown item whose front matter is a one-line flow mapping
(`{id: REQ-001, type: requirement, title: x}`) was destroyed on disk by any
writable load -- including plain `refdes check`: key minting inserted
`key: <minted>` as its own line *above* the braces, which is not valid YAML
next to a flow mapping, so every later load reported the file unparseable
("0 items, 1 error"). The insert now places the new pair inside the braces
(the way flow list entries were already handled) and refuses, with an error
naming the file and line, a flow mapping that does not close on its own line.
The same replace-or-refuse rule covers the `id:` and `former_ids:` write-backs
that share the helper.

As a general backstop, every load-time write (key minting, link/check
expansion, follows freeze) is now verified: a rewritten file that no longer
parses, or parses into fewer items than before, is restored to its exact
original bytes and reported as an error instead of being left broken on disk.
