# Task: docs/navis.md — the Navis user guide

## What I did

Wrote the first user-facing guide for Navis (flying notes), `docs/navis.md`,
covering five areas: what a Navi is, the CLI, archiving/restoring, the
published-site panel, and the `serve` API. Added it to `docs/index.md`
(guides table), a cross-link from `docs/markdown.md` (Navis markers), one
from `docs/cli-reference.md` (the navis section), and a
`changelog.d/navis-user-guide.added.md` fragment (matching the #406
browser-editor guide precedent: docs pages do get an `added` fragment).

Branch `docs/navis-guide`, branched from main at 968a15a.

## Verification approach

Per the repo rules, every command/response/hash in the guide was run on a
throwaway project (`.scratch/navis-guide/`), not recalled. Two scratch
projects: `proj` (full CLI matrix, all exit codes) and `demo` (clean,
canonical — the keys/text quoted in the guide are `demo`'s: `4jp6qysbahb`,
`3fm1dgvv6p3`).

- CLI: `ls`/`all`/`show`/`archive`/`restore`, all three selectors (full key,
  6-char prefix, ordinal), exit codes 0/1/2.
- Refusals: not-found, ambiguous prefix, restore-not-archived, keyless,
  `--no-write`, journal — each its own message.
- Byte-identity: `sha256sum` of the item before/after `archive` is identical
  (`3170ed41…`); archive writes only `.refdes/navis/<key>.yaml.gz`.
- States: snapshot, edited-marker ("marker text has changed"), orphan
  (marker deleted -> `restore` refuses, exit 1).
- Serve: `refdes serve --port 8780` + curl. GET `/api/navis` (rows + counts,
  403 without token); POST archive/restore with `X-Refdes-Token` + matching
  `Origin` (POST requires Origin, reads do not). Every status verified live
  except 500 (a store write failure, not triggerable): 200 ok/changed, 400
  bad_request, 403 refused (`--no-write`, gate-first), 404 not_found, 409
  ambiguous (candidates) / conflict (reason not_archived). Server stopped by
  PID.
- Site panel: built the site; `navis.css` link + `refdes-navis` details
  present for a Navis project, absent (no css, no panel) for a no-Navis
  project. Panel is fixed top-right (navis.css), Restore button disabled with
  the CLI hint.

## Scope discipline

Only features on main today. Did NOT document the preview-page Navi buttons
or the editor Navis panel (other slices in flight). Linked to
markdown.md#navis-markers for the marker rules rather than repeating them;
linked to output.md#the-navis-panel for the panel.

## Status

Guide, nav, cross-links, changelog fragment, and this log are written.
Docs tests (`test_docs_anchors.py`) need to run. Paused before the full
suite per the profiler request (docs-only, so the full suite is not
required by the task anyway).

## Notes for a reviewer

- The console blocks quote `demo` output with a per-run mint key, so re-running
  on a fresh project mints different keys; the shapes/messages are exact.
- The serve API section quotes a real port-8780 run; the 500 `error` row is
  documented from the `navis_write._render` status map, not a live run.

## Review round 1

Jared's re-run found two accuracy nits against the page's "quoted as it
printed" promise; fixed in one commit, all re-run on the throwaway projects:
N1 — the two orphan blocks now quote the complete output including the
`WARNING .refdes/navis/<key>.yaml.gz:9 — navis.archived_orphan: …` line that
every command prints once an orphan exists. N2 — the ambiguous CLI and serve
examples used a hand-typed key (`4jp6qy00000`) that trips the malformed-key
lint; replaced with a hand-built VALID key sharing the `4jp6qy` prefix
(`4jp6qym9s3j`, correct Damm check char), so those runs print no key warning,
plus one sentence noting the collision is constructed and rare. N3 —
re-ran every block: the keyless block now quotes the real `ERROR … flow-style
list …` line that precedes its refusal (the guide's own "see the mint warnings
above" refers to it), and the serve count/keys were updated to the three-Navi
project the ambiguity needs.
