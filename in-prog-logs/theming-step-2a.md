# Theming step 2a — `site: theme:` and `site: tokens:`

Date: 2026-09-21. Authority: `docs/design/backlog.md` finding 34, sections 1–6
and "Recommendation and v1 scope". Step 1 (the token layer) was already landed.
Merged `origin/main` first: already up to date, no conflicts.

## What landed

**`src/refdes/theme.py` (new).** The whole theme model in one place:

- `default_tokens()` reads the built-in token list *out of*
  `templates/assets/style.css` — every custom property declared in a plain
  `:root` block. So "the default theme is today's look" is true by
  construction, not by a copy that can drift. The
  `prefers-color-scheme: dark` block is deliberately excluded (see Decisions).
- `BUILTIN_THEMES` ships `default` only, with zero overrides. Step 2b adds the
  rest of the gallery.
- `validate_theme_name()` — an unknown `site: theme:` is an error naming the
  themes that exist, with a difflib did-you-mean. Never a silent fallback.
- `validate_token_overrides()` — keys must match `TOKEN_NAME_RE` *and* be in
  the built-in list (unknown → "is not a design token. Did you mean
  '--accent'?"); values go through `validate_token_value()`.
- `validate_token_value()` is the injection boundary: the value is written
  verbatim into a generated stylesheet, so `; { } < > @ \ /* */ url(
  javascript: expression(` , control characters, empty and >200-char values are
  all refused.
- `SEMANTIC_BAND_TOKENS` (`--good/--bad/--warn/--claim`) — refused outright in
  2a, with a message that says why (verdict colours) and points at 2b.
- `resolve()` merges theme-then-project over the default, emitting only
  overrides; `render_theme_css()` writes one `:root` block in the built-in
  token order.

**Config.** `SITE_KEYS` gained `theme` and `tokens` (configcheck.py), and
`BlockChecker.site()` validates both through theme.py, re-raising in the same
"refdes-project.yaml: ..." voice as every other settings diagnostic.
`model.Project` gained `theme` / `theme_tokens`; `schema.load_project` wires
them. Verified through the real CLI: every refusal is
`configuration error: refdes-project.yaml: ...` with exit 2, not a traceback.

**Rendering.** `render._write_theme_css()` writes `assets/theme.css` when — and
only when — there are overrides, adds it to `written`, and `base.html.j2` links
it after `assets/style.css` behind `{% if theme_css %}`. Both asset paths (the
empty-project early return and the normal tail) call it. `theme.css` was also
added to `_copy_project_assets`' reserved set, so a `site.assets:` directory of
that name is a build error instead of a clobber.

## Verification

- `python -m pytest -q` → **1632 passed** (was 1594 before; +38 new).
- `ruff check <touched files> --select E9,F` → clean.
- `tests/test_theme.py` sabotage coverage: unknown theme name, theme typo with
  hint, unknown token, token typo with hint, bare `accent` without dashes,
  non-mapping `tokens:`, 13 parametrised injection values
  (`url(javascript:alert(1))`, `red; body { display: none }`, `}`, `red }`,
  `{`, `/*`, `*/`, `@import url(...)`, `@import evil.css`,
  `</style><script>...`, `expression(alert(1))`, backslash-newline, tab/newline),
  empty and oversized values, all four band tokens, merge semantics,
  theme-over-theme precedence, and the build-side checks.
- **Byte-identity proof**: `tests/fixtures/no_theme_build_hashes.json` holds
  sha256 of every file of a built `COVERAGE_SCHEMA` fixture project, captured
  from `origin/main` *before* any of this code existed (and confirmed
  reproducible across two temp dirs). `test_no_theme_build_is_byte_identical_to_the_pinned_output`
  rebuilds that project and compares the whole tree. It passes.
- End-to-end CLI probe: build with `--accent` override → `assets/theme.css`
  present, linked after `style.css`, listed in `.refdes-manifest.json`; rebuild
  with the theme removed → file gone, manifest entry gone, `<link>` gone.

## Decisions and open items

1. **Dark mode.** A theme override lands in one plain `:root` emitted after
   `style.css`, so it wins over the `prefers-color-scheme: dark` block too —
   i.e. an override applies to *both* palettes. The finding's §4 recommendation
   ("keep the media query refdes's, a theme declares light tokens plus dark
   tokens under two documented headings") implies a two-section theme format,
   which is a format decision 2a does not need to make: with only `default`
   shipping, there is no theme author yet. Flagged for 2b: if themes get a dark
   section, `--bg`-style overrides need to say which palette they mean.
2. **Band tokens in `site: tokens:` too.** The task text says "refusing a theme
   that sets those four"; I applied the same refusal to `site: tokens:`, since
   otherwise the direct override path is looser than the named-theme path it
   layers on top of. 2b replaces both with the band check.
3. **Layout-changing themes / remote URLs / project CSS files** are refused by
   the format itself: there is no `site: css:` key (unknown key → error), no
   file or URL in the format, and no selector syntax. Nothing to implement
   beyond the value/name validation; documented as refused.
4. **Not done (2b, by scope):** contrast checking, extra built-in themes, the
   docs-site gallery, editor theming.

## Files

- new `src/refdes/theme.py`, `tests/test_theme.py`,
  `tests/fixtures/no_theme_build_hashes.json`
- edited `src/refdes/configcheck.py`, `src/refdes/model.py`, `src/refdes/schema.py`,
  `src/refdes/render.py`, `src/refdes/templates/base.html.j2`
- docs: `docs/schema-reference.md` (`site` table + a `site.theme`/`site.tokens`
  subsection), `docs/output.md` (new "Theming" section + the `assets/theme.css`
  row)
- `changelog.d/theming-site-theme-tokens.added.md`
- scratch: `.scratch/snap.py` (hash capture), `.scratch/theme_cli_probe.py`,
  `.scratch/theme-probe/`

## Post-merge re-verification

`origin/main` moved to `3e65b60` (editor source patcher: `src/refdes/patcher.py`
+ `tests/test_patcher.py`) mid-task. Merged it in — clean, no overlapping files
with theming — and re-ran everything on the merged tree:

- `python -m pytest -q` → **1747 passed** (1632 theming-era + the 115 new
  patcher tests).
- `ruff check <touched files> --select E9,F` → clean.

## Follow-up: the byte-identity test and CRLF checkouts

Jared landed 2a (`1b9d654`/`5191df6`) and reported
`test_no_theme_build_is_byte_identical_to_the_pinned_output` failing in his
checkout: `core.autocrlf=true` there materializes `assets/app.js` with CRLF, the
build copies static assets byte-for-byte, and the pinned hash was captured from
an LF working copy.

His prescribed fix — fold `\r\n` → `\n` in each built file before hashing, keep
the fixture — does not work as stated, and the reason is worth writing down. The
fixture is not uniformly LF. Generated pages are written in text mode, so on the
Windows machine that captured them they are CRLF, and their pinned hashes are
CRLF hashes; only the copied assets were LF. Measured, not assumed:

```
index.html                 crlf_in_file=True  fixture_matches=raw
items.json                 crlf_in_file=True  fixture_matches=raw
.refdes-manifest.json      crlf_in_file=True  fixture_matches=raw
assets/app.js              crlf_in_file=False fixture_matches=raw
assets/style.css           crlf_in_file=False fixture_matches=raw
```

So folding the built tree to LF fixes the assets and breaks the other fifteen
files — which is exactly what the first attempt did here: 15 files differing,
test red. Since the fixture must stay as captured, the comparison has to accept
the *content* rather than one encoding of it.

**Fix**: `_digests(path)` returns the sha256 of a built file's content under
each line-ending convention — as-is, folded to LF, expanded to CRLF — and a file
matches when its pinned hash is one of them. Binaries (extension set
`BINARY_EXTENSIONS`) are compared raw only, so a changed PNG byte cannot pass as
a line ending. Fixture untouched; the assertion is now two — same file set, then
no hash mismatches — so a missing or extra output file still fails loudly.

**Proof** (`.scratch/crlf_proof2.py`, output verified):

- baseline: 0 missing, 0 mismatched.
- `assets/app.js` rewritten with CRLF (the reported condition): raw hash changes,
  **0 mismatched** — test still passes.
- generated `index.html` / `items.json` / `.refdes-manifest.json` folded to LF (a
  POSIX run): raw hashes change, **0 mismatched**.
- sabotage one non-line-ending byte of `assets/app.js`: **mismatched =
  ['assets/app.js']** — the check still bites.

`python -m pytest -q` → **1747 passed**; `ruff check tests/test_theme.py --select
E9,F` → clean.

Not pushed, not merged back — left for Jared to review and land.
