# refdes — agent instructions

This project has a self-describing tool: use it to verify claims instead of
recalling them. Confident-but-wrong output has happened here before — treat
that as the default risk, not the exception.

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
