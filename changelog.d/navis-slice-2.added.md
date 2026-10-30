# Navis slice 2: key minting on the writable load

A keyless `<!--navi: text-->` marker gets its 11-character key the same
way an item gets its surrogate key: on the next writable command, at the
marker's exact position in the author's own file, announced on stderr and
counted in the load's write notice. `--no-write` mints nothing, a project
with no markers is byte-identical to before (verified by differential
build), a second writable run writes no bytes, and duplicate marker texts
get distinct keys. A declared key is never rewritten and never repaired:
one that fails key validation is reported as corrupt input (the
`keys.malformed_key_message` posture for item keys, now also for marker
keys), and minting mints around it.

Minting is exact-provenance or nothing: a marker whose bytes cannot be
located losslessly in the item's own source file (a list file's `body:`
scalar; a file that changed under the parse) refuses the mint with a
`NAVI_MINT_REFUSED` warning and leaves every byte untouched. Keys are a
fresh namespace, minted unique against the project's declared marker keys.

`refdes navis ls` now shows each key's 6-character prefix; `show` accepts
a 6-to-10-character key prefix as a selector (unique match; an ambiguous
one names its candidates, exit 2).

The cost is the design's disclosed one (§7.2): minting edits the body, so
an `invalidate` body's content hash changes with the minted key (an
`ignore` body's does not), and a sealed `append-only` entry answers the
writable build with the documented "modified since it was sealed — run
`refdes build --reseal`" error.
