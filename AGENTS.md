# refdes — agent instructions

This project has a self-describing tool: use it to verify claims instead of
recalling them. Confident-but-wrong output has happened here before — treat
that as the default risk, not the exception.

## Current state, briefly

- The bundled standard is at **`hardware@3`, itself unreleased** (see
  `CHANGELOG.md`'s `[Unreleased]` section and `src/refdes/standards/hardware/v3/`).
  Don't assume `hardware@2` behavior still holds, and don't cite `hardware@3`
  as shipped in a release — it isn't yet.
- **Surrogate keys (`docs/design/keys.md`) are partially landed.** Key
  minting, composite-link expansion (`DISPLAY-ID@key`), and hashing-on-key
  are implemented; the corruption lint, `refdes keys adopt`, the
  display-half refresh-on-rename, and any `revise.py`/`former_ids.py` change
  are still design only. Concretely: `Item.links` holds the raw, possibly
  composite target text (what hashing/write-back reads) — **anything that
  merely walks the link graph should read `Item.resolved_links` instead**
  (always-bare, always-current display ids), never raw `links` directly,
  or it will silently stop matching the moment a target is
  composite-expanded. See `model.py`'s `Item.links`/`resolved_links`
  docstrings.
- **`ruff check .` does NOT pass clean** — currently ~99 pre-existing
  findings, because the installed ruff's default rule set is broader than
  `pyproject.toml`'s `[tool.ruff]` comment assumes (that config only adds
  `I`/import-sorting on top of ruff's defaults; it was never meant to imply
  a clean baseline). A green `ruff check .` is not a valid completion gate
  today — scope any ruff-driven cleanup to the specific rule(s) and file(s)
  you're actually touching (e.g. `ruff check <files> --select <RULE>`), and
  don't try to silence unrelated pre-existing findings as a side effect.
- **Multiple sessions have historically worked this checkout concurrently.**
  Never `git stash` — a stash you can't be certain is redundant strands
  another session's in-flight work, and dropping one you didn't create can
  destroy it outright. Run `git status` before assuming the tree is yours;
  if it's dirty in a way you didn't cause, investigate before touching it.

## Before writing any claim about the schema (types, fields, link types, presets)

Run `refdes schema` (from a directory with a `refdes.yaml`) and check the JSON
output — not memory, not something read earlier in this same session. It's
faster and harder to get wrong than reading
`src/refdes/standards/hardware/v1/base.yaml` by eye.

## Before writing any claim about CLI behavior (flags, defaults, errors, exit codes)

Run the actual command, or `refdes <command> --help`. If something can't be
verified by running it, say so in the text instead of asserting it.

## Before writing a new docs page

Check `docs/` for an existing page on the same topic first (`ls docs/*.md`,
or grep for the topic). `docs/index.md`'s nav is the map of what's already
claimed to be documented — don't re-cover a topic that already has a page.

## Scope

One file or one command at a time. A request like "document everything not
yet covered" should become a sequence of single-topic passes, each verified
per the rules above — not one long unverified pass.

## Citing claims

When asserting a fact about behavior, name the file (and command, if you ran
one) you verified it against, so it's fast for a human to spot-check.
