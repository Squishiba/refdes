# Browser editor — Slice 0 + Slice 1 (chunks 1-3)

Task: docs/design/browser-editor.md (authoritative; not relitigated). Slice 0,
then Slice 1 chunks (1) `refdes serve`, (2) read side, (3) source patcher +
field/body edit with draft/refuse-and-diff. Stop after (3). No Slice 2/3.
Branch ao/refdes-122/root, no push/merge.

## Slice 0 — side-effect-free load with overlay  (done)
- New `src/refdes/loader.py`: `load_tree(config, require_ids, write, overlay)`
  is the old `cli._load` pipeline moved verbatim (cli._load now delegates);
  `load_readonly(config, overlay)` = load_tree(write=False) + build(seal_write=False).
- `Project.source_overlay` (model.py) + `parse.read_source/overlay_key` :
  parse reads overlaid text instead of disk; an overlay-only path under items/
  joins `source_files`. Overlay + write=True raises (write-back addresses real
  files by line).
- tests/test_no_write.py: load_readonly byte-identical tree, overlay shows
  candidate w/o disk change, overlay-only new file, overlay+write refused.
- Note: overlay keys are `normcase(abspath)`, so on Windows an overlay-only new
  file's relpath is lower-cased. Harmless for reading; revisit for Slice 3.

## Chunk 1 — `refdes serve` (done)
Package `src/refdes/serve/`: `security.py` (token, Host/Origin, CSP, safe path
segments), `state.py` (inputs, content revision, stat->hash polling, git
advisory, Poller w/ 2-tick debounce), `preview.py` (temp-dir generations,
prune_stale by marker mtime), `server.py` (stdlib ThreadingHTTPServer on
127.0.0.1:0), `api.py` (only `/api/revision` so far), `static/` (index.html,
app.js, api.js, style.css, bar.css), wired in via `cli.cmd_serve` and
package-data `serve/static/*`.
Decisions made inside the doc's frame (not new design calls):
- Token transport: the doc says header on API and Jupyter-style startup URL.
  Preview/editor pages are plain navigations and cannot carry a header, so the
  launch URL sets a SameSite=Strict HttpOnly cookie (doc mentions a session
  cookie) and 302s to the token-free URL; the editor shell embeds the token in
  a <meta> for its fetches. `/api/` accepts ONLY the header (cookie alone = 403).
- Cookie name includes the port (cookies are not port-isolated).
- Revision hash inputs: both config files, item sources, pages/*.md,
  .refdes/*.{yaml,yml,json} except schema.json, import artifacts. Hashed before
  AND after each model build (retry x3) so revision never labels a newer model.
- Failed rebuild keeps last good model, sets load_error, snapshot stays stale.
- No test CI / Node here: JS could not be linted or run; verified by serving
  the files and by HTTP tests only (browser smoke test at end of chunk 3).
Tests: test_serve_security (37), test_serve_state (10), test_serve_cli (2),
test_no_write editor GET/preview/rebuild byte-identity. Full suite: 1443 pass.
Difficulty: my shell heredocs mangled backslash escapes twice; used Edit/Write.

## Chunk 2 — read-side API + editor shell (done)
Merged origin/main first (twice: living-notes history.py, then hardware@3
sets refactor; no conflicts with this work).

- `serve/filters.py`: the filtered query over the *built* snapshot. Params:
  type, board, workspace, tag, file, stage, check, blocked(yes/no),
  links_to, linked_from, missing_verb, q, limit. Single value per param,
  AND-combined; matching follows `refdes ls` where it has an equivalent
  (tag/q substring, file slash-normalized exact). Semantics I fixed where
  the doc is silent (design calls, logged per instruction):
  * `stage` only counts coverable items (a non-coverable item has no stage,
    not "open"); `check` rolls up none/pass/fail/unknown like items.json;
    `blocked` = has a declared blocked_by edge (any chain depth).
  * `links_to`/`linked_from` name a target (display id or key) and match
    resolved links/backlinks under any verb; `missing_verb` = type declares
    the verb, item has no resolved target for it.
  * Facet counts are cross-filtered (a facet's counts ignore only its own
    filter) — the honest number for a sidebar. `facet_totals` reports each
    facet's matched total.
  * Bad values (stage=banana, unresolved links_to, limit out of range) are
    400s, never an empty list. Unknown params ignored (forward-compat).
- `serve/api.py`: `/api/items` (rows carry `handle` = the project.items dict
  key, so keyless/provisional items stay addressable) and `/api/item/<ref>`
  (fields, body, links both directions, coverage, checks, attributed
  diagnostics, sealed/append_only, preview page name). Ref accepted: dict
  key, display id, or surrogate key. `is_sealed` reads `.refdes/` seal
  files only — verified byte-identity.
- Shell UI (`serve/static/`): index.html is now sidebar|list|detail;
  new filters.js (URL<->state, facet buttons with counts), list.js, item.js
  (read-only view + preview iframe); app.js is a hash router
  (`#/items?filters`, `#/items/<handle>?filters`) that refetches on
  `refdes:rebuilt`. Plain ES modules, no inline script, no framework; the
  JS renders API fields only. style.css extended.
- Tests: tests/test_serve_api.py (52: every filter alone and combined,
  cross-filtered counts, URL round-trip, 400s, item view incl. handle
  addressing + diagnostics + seal state, token/Host/Origin/405 gating).
  serve_support.py gained `make_filter_project` (two boards, two workspaces,
  five files, verified/satisfied/open, pass+fail checks, a blocked decision,
  a missing-verb decision). test_no_write's editor GET test now hits every
  new route (7 filtered lists + every item view by handle and by id) and
  still asserts the tree byte-identical.
- Full suite: 1564 passed (after merging main). ruff clean on touched files.
- Not verified in a real browser (no Node here, same caveat as chunk 1):
  the JS is served with correct MIME and CSP, and every payload it renders
  is exercised by the API tests; interaction smoke is deferred to chunk 3's
  end-to-end pass.
- No write path, no editing controls, no source patching — chunk 3.
