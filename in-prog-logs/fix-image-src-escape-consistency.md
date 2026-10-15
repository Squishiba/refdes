# IMAGE-ASSET-002: image hash/render src agreement

Branch `fix/image-src-escape-consistency-20261015`, base 7e49a20 (current main
tip at claim time). Claimed in shared main `.scratch/PROGRESS.md` row
IMAGE-ASSET-002. Read-only finding:
`in-prog-logs/current-main-resweep-image-digests.tsv` row IMAGE-ASSET-002.

## Verified present on current main (2026-10-15)

Probe: `.scratch/img002_probe/` (`setup_probe.py` + `probe.py`), run with
`PYTHONPATH=$PWD/src` and asserting `refdes.__file__` is this worktree's src.
Project: one decision item, body `![board](a&b.png)`, real file
`items/a&b.png`. Output at base:

- build error: `image src 'a&amp;b.png' does not exist (no site.assets ...)`
  — the render pass resolves the HTML-escaped spelling;
- `project.assets` == {} — no published copy (`_site` published nothing);
- `_image_inputs_hash_value` → `[['items/a&b.png', 'c0d98f7d777f7213']]` —
  the hash pass resolves the raw spelling and hashes the real bytes.

The finding is present. The TSV's cited lines moved (hash read now
build.py:2222, render swap build.py:2819-2848, regex build.py:96); the
mechanism is unchanged.

## Root cause

The hash pass reads the markdown-it **token** src (`child.attrGet("src")`) —
the authored URL, mdurl-normalised. The render pass (`_process_images`)
scans the *rendered HTML* with `IMG_SRC_RE`, where markdown-it's attribute
escaper has rewritten `& < > "` to `&amp; &lt; &gt; &quot;`. Two spellings,
two resolutions, same image.

## Design: one canonical image-src interpretation

Canonical form = the markdown-it token src (the authored URL spelling, the
form the filesystem is named in). One shared pair in build.py:

- `image_src_from_html(escaped)` — decode exactly the four entities
  markdown-it's escaper emits, in reverse order, nothing wider. NOT
  `html.unescape`, which over-decodes `&not;`/`&#38;` and breaks the
  round-trip for filenames that literally contain `&amp;`.
- `image_src_to_html(canonical)` — markdown-it's own `escapeHtml`
  (imported, not re-typed) so the rewrite exit is the same escaper the
  render pass's input came from: `image_src_from_html(escapeHtml(x)) == x`.

Render pass: decode the regex-captured attr, then resolve/validate/record
on the canonical src — so the hash pass and the render pass feed the exact
same string to the shared resolvers (`_local_image_path`,
`_search_image_src`, `_URL_SCHEME_RE`), which stay untouched. The rewrite
re-escapes, so the published attr carries the spelling a browser decodes
back to the real asset filename. The hash pass reads the canonical form
directly (token attr) — zero change, so content hashes are bit-stable for
normal srcs.

Preserved by construction: URL scheme skip (checked on the canonical src,
same as the hash pass), percent-escapes untouched (`thermal%20curve.png`
still misses — the documented picker rule), path confinement untouched,
external-link srcs pass through byte-identically.

## Consumers of the src spelling (audited)

- `Project.image_results` record `src`: now canonical (was the escaped
  HTML spelling). upload.py `_capture_refusal` compares it to a filesystem
  leaf — canonical is the correct side; docstring there ("the src as
  written") now literally true.
- serve/server.py `_decorate_images`: reads the published HTML attr (escaped
  spelling) and compares to `image_results` src/dest — must canonicalise
  with `image_src_from_html` before the lookup.
- api.py `referenceable` picker filter: `&` names are now resolvable
  (token `a&b.png` == canonical == file); `quote(safe="/&")` keeps the
  conservative direction the docstring defines (accepted ⇒ resolvable).
- api.py docstring "resolves the rendered src without decoding it" — was
  already imprecise (it decodes mdurl's percent-escapes never, HTML
  entities now); reworded.

## Status

FINISHED. Changes:

- `src/refdes/build.py`: canonical src pair (`image_src_from_html` /
  `image_src_to_html`, the exact inverse of markdown-it's imported
  `escapeHtml`); render pass canonicalises before resolving and re-escapes
  the rewrite; hash pass reads the canonical token src unchanged (docstrings
  updated).
- `src/refdes/serve/server.py`: `_decorate_images` canonicalises the
  published attribute before matching `image_results`.
- `src/refdes/serve/api.py`: `referenceable` safe set gains `&`; docstring
  corrected (the build decodes HTML entities, never percent-escapes).
- tests: 6 new (4 in test_image_hash.py, 1 in
  test_serve_preview_decorations.py, 1 in test_serve_images.py), each
  verified red on the base export (`.scratch/base`, `git archive 7e49a20`)
  and green on the fix.
- `docs/markdown.md`: the authored-spelling rule stated; `CHANGELOG.md`
  entry under Unreleased/Fixed.

Suites: full suite 3870 passed / 2 skipped (`PYTHONPATH=$PWD/src python3
-m pytest tests`); scoped ruff on the six touched files shows 3 findings,
identical to the same 3 at base (pre-existing I001/RUF059/etc) — no new
findings.

## Overlap note (#220/#232, merged)

#220 (IMAGE-ASSET-001) edited the sort inside `_image_inputs_hash_value` —
this branch touches only that function's docstring, no conflict;
#232 (IMAGE-ASSET-006) confined `site.assets:` in the walk functions —
untouched here. Rebase risk is docstring adjacency in `build.py` only.
No changes were made to those branches.
