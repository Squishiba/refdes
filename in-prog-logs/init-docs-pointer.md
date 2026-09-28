# Fix: `refdes init`'s docs pointer (user-sim run 1, L1)

## The task

`src/refdes/cli.py:795` (pre-fix) printed, as part of `refdes init`'s output:

```
candidate parts live in items/<board>/candidates.yaml -- docs/parts.md#candidate-parts-the-recommended-layout
```

The claim in the user-simulation report (`in-prog-logs/user-sim-release-gate-run1.md`
§L1) is that this is dangling: `init` generates no `docs/`, and a wheel carries
no docs at all. I was told to verify both halves myself before changing anything.

## Verification (both halves confirmed)

**1. `init` creates no `docs/`.** Ran `refdes init` in a scratch dir. Only
`refdes-project.yaml` and `.vscode/settings.json` are written. Nothing else.

**2. A real wheel carries zero `.md` files and no `docs/`.** Built one exactly
as `AGENTS.md`'s temp convention prescribes:

```
pip wheel --no-deps -w .scratch/wheelcheck .   ->  refdes-0.5.0-py3-none-any.whl (568K, 98 entries)
```

Listing the archive: `.md files: []`, `docs entries: []`, top level is
`['refdes', 'refdes-0.5.0.dist-info']`. Same numbers the reporting worker got.

## Why the pointer was never going to resolve — checked for a missing piece

The brief asked me to look for evidence that shipping docs was the *intent* and
just needed a config line. There is none:

- `pyproject.toml:73-74` — `[tool.setuptools.packages.find] where = ["src"]`.
  The src layout only.
- `pyproject.toml:81-82` — `[tool.setuptools.package-data]` lists
  `templates/*.j2`, `templates/assets/*`, `standards/**/*.yaml`,
  `serve/static/*`. Templates/standards/site-assets are called out
  *deliberately* in the comment above them ("Templates and site assets are code
  here"). Docs are not mentioned anywhere in it.
- No `MANIFEST.in`, no `setup.py`, no `setup.cfg`. `pyproject.toml` is the only
  packaging config in the repo, and none of it reaches for `docs/`.

So there is no half-finished config waiting to be completed. The docs were
never on the path to being packaged, which is the normal and sensible state of
affairs — they are a 1.6M / 47-file directory, and `docs-site/` already exists
to *render* them as a site.

## What does resolve: the published site

`docs/design/backlog.md` finding 1 records that `docs-site/` is built and
deployed to GitHub Pages by `.github/workflows/docs.yml`, and that Pages is
live (`gh api` reported `html_url: https://squishiba.github.io/refdes/`,
`status: built`, verified 2026-09-27).

I did not take that on trust. Fetched the real thing:

- `https://squishiba.github.io/refdes/parts.html` returns 200 and its "On this
  page" list contains **Candidate parts: the recommended layout**, with the
  same body text as `docs/parts.md` §"Candidate parts: the recommended layout".
- The rendered heading id is `id="candidate-parts-the-recommended-layout"` —
  **byte-identical to the anchor the old message already used.**

So the fix is purely the URL prefix. The anchor that was already correct stays
correct.

## Direction taken: correct the pointer, do not ship `docs/` in the wheel

Adding 1.6M of markdown to a 568K wheel so that a path resolves only *inside a
git checkout* would be backwards — it would fix the checkout user (who already
had it) and still not help a wheel user reading a bare `docs/parts.md` with no
`docs/` directory around it. The published site is the one form of the
reference that works for everyone, and it is already built and deployed. So:
point at the site.

Concretely:

- `src/refdes/cli.py` — added a `DOCS_URL = "https://squishiba.github.io/refdes"`
  module constant, with a comment recording the packaging reason above (so the
  next person doesn't "simplify" it back to a relative path), and the init
  message now interpolates it. A named constant rather than an inline literal
  because the test pins against it and it is the single place to change if the
  site ever moves.
- `pyproject.toml` — `Documentation` was
  `https://github.com/Squishiba/refdes/tree/main/docs`, a GitHub tree view.
  Now the published site. It did resolve before, so this is an improvement
  rather than a fix, but it is the same pointer in the same metadata and
  leaving the two disagreeing would be odd.
- `tests/test_scaffold.py` — new
  `test_cli_init_points_at_the_published_docs_site_not_a_repo_relative_path`.
  Asserts `docs/parts.md` is absent from init's output, asserts the full
  site URL + anchor is present, and asserts `not (tmp_path / "docs").exists()`
  so the premise stays honest if init ever starts generating a docs directory.

I checked the new test is a real pin rather than a vacuous one: reverted the
message to the old string and re-ran — it fails on the `docs/parts.md not in
out` assertion. Restored after. Also confirmed `refdes` is not installed in the
test venv, so pytest resolves the package from this worktree's `src/` and the
test really exercised the edited code.

## Changelog

`changelog.d/init-docs-pointer.fixed.md`.

## Left alone deliberately (worth a follow-up, not this commit)

`grep`ping the source for user-facing text mentioning `docs/` turns up two more
of the same class, in `src/refdes/serve/upload.py:334` and `:420`, both naming
`docs/design/editor-image-upload.md` to a user in an error message. Same
problem. I did not touch them: `AGENTS.md` scopes a pass to one file or one
command, and they are in a different subsystem from `init`.

Worth noting for whoever does that pass — the design docs *are* on the published
site too (the live nav lists "Surrogate keys", "Backlog", "Editor PDF datasheet
picker" and so on), so `DOCS_URL` will serve them as well. But it probably
should not live in `cli.py` once a second module needs it; a neutral
project-metadata module would be the better home, and moving it is a cleaner
commit than introducing it twice.

## Not run

No lint gate was run: `AGENTS.md` records that `ruff check .` does not pass
clean (~99 pre-existing findings) and is not a valid completion gate. The two
files touched are `cli.py` (three lines of a module constant and one f-string)
and `test_scaffold.py`. `tests/test_scaffold.py` and `tests/test_no_write.py`
pass (70 passed).
