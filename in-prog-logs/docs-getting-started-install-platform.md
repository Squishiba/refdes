# getting-started Install section is Windows-first (user-sim L7)

Task: `docs/getting-started.md` §Install led with a Windows-only command, with
the POSIX correction only in the prose after it. Fix so a reader can't run the
first command shown and hit a platform-mismatch error without already knowing
which platform they're on. Docs only.

## Verified before editing

- `grep -rn "Scripts/python" docs README.md AGENTS.md` in this worktree:
  `docs/getting-started.md:11` (the install block), `:16` (the fallback line),
  plus `README.md:24` and `README.md:391` (out of scope, see Notes).
- Source of the finding: `in-prog-logs/user-sim-release-gate-run1.md`, "L7 —
  the install snippet is Windows-first" (line 484). Line numbers in that log
  matched what's in the file today.
- Fence-language conventions in `docs/*.md`, counted over all pages: `yaml`
  (153), `bash` (47), `markdown` (17), `calc` (13), `json` (5), `console` (3),
  `csv` (1) — no Windows-flavoured fence anywhere. The new Windows block is
  fenced `bat`; `blocks.py`'s `_RAW_FENCE_RE` comment (line 49) states fenced
  blocks accept "any language tag", and the docs build does no highlighting
  step that could reject it, so an untagged-elsewhere tag is safe.
- `python docs-site/gen_examples.py --check` is the only docs-content CI gate
  found (`.github/workflows/docs.yml`, per
  `in-prog-logs/docs-ci-examples-check.md`) and it targets
  `docs/schema-reference.md` / `docs/vocabulary.md` only, so this page is not
  generated and nothing regenerates over the edit.

## What changed

`docs/getting-started.md` §Install only:

- The single mixed block (`python -m venv .venv` + the Windows pip line) is now
  a venv block on its own, followed by two platform-labelled install blocks —
  "Linux and macOS:" with `./.venv/bin/python -m pip install -e .`, and
  "Windows (PowerShell):" with `.\.venv\Scripts\python.exe -m pip install -e .`.
  A lead-in sentence says the venv interpreter path differs by platform and to
  use the one matching your machine, so neither block reads as "the" default.
- The fallback line repeated the Windows path. It now names both:
  `./.venv/bin/python -m refdes.cli` on Linux and macOS,
  `.\.venv\Scripts\python.exe -m refdes.cli` on Windows.

Chosen over leading with POSIX alone: the primary developer's environment is
Windows (`AGENTS.md` and this session's memory lean that way) and the repo's
own docs give no POSIX-first precedent, so showing both without a default is
the option that can't be wrong about the reader.

## Verification

- Re-read the section after the edit; the two blocks and the fallback line are
  as described, and the rest of the page (headings, the `refdes init` yaml, the
  walkthrough, the documented build output) is byte-identical — `git diff` is
  confined to the Install section.
- `grep -n "Scripts/python" docs/getting-started.md` now returns only the two
  Windows-labelled occurrences, each adjacent to its POSIX twin.
- No source or test changes, so no suite run was warranted; nothing in
  `tests/` asserts on this page's text (the docs-content gate is the
  `gen_examples.py --check` noted above, which doesn't cover it).

## Notes / not done

- `README.md:24` (`python -m venv .venv && ./.venv/Scripts/python.exe -m pip
  install -e .`) and `README.md:391` (the pytest invocation) have the identical
  Windows-first problem. Left alone: the task scoped this to
  `docs/getting-started.md`, and the README's install line is a one-liner that
  would want the same two-block treatment (or a note) decided consistently with
  it. Worth a follow-up pass over the README.
- Changelog fragment added: `changelog.d/docs-getting-started-install-platform.fixed.md`
  — precedent is this session's other pure-wording docs fixes
  (`docs-getting-started-prose.fixed.md`, `docs-coverage-prose.fixed.md`), so
  docs wording does get a fragment here.

Status: done.
