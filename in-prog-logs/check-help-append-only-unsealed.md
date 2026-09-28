# `check --help`: say what "never creates seals" costs (F6)

Task: the user-simulation finding F6 in
`in-prog-logs/user-sim-release-gate-run1.md` — a `check`-first workflow gets an
append-only item zero immutability protection, and nothing tells the author
they are in that state. Documentation/help-text only; the behavior is correct
as designed.

## What was verified first

Reproduced F6 locally rather than trusting the report, with
`.scratch/f6_probe.py` (drives `refdes.cli.main` against a one-entry project in
`.scratch/f6-probe/`):

```
$ refdes check            # LOG-001 edited, never built
1 items, 0 errors, 0 warnings            [exit=0]
$ refdes check            # edited again
1 items, 0 errors, 0 warnings            [exit=0]
seal files: ['schema.json']              # no seal file exists at all
$ refdes build
1 items, 0 errors, 0 warnings            [exit=0]
seal files: ['log-seal.yaml', 'schema.json']
$ refdes check            # edited after the seal
ERROR   items/log/log.yaml:2 [LOG-001] — LOG-001 is append-only and has been
        modified since it was sealed. ...
1 items, 1 errors, 0 warnings            [exit=1]
```

So the gap is exactly as described: two clean `check` runs over two edits, and
the only reason the second edit was invisible is that there was no hash on
record to contradict it.

Read the surrounding `description=` text in `cli.py` (serve, revision, release,
fetch, init) for register before writing: declarative, no "note that", command
names in single quotes inside descriptions (the existing check description
already writes `'.refdes/schema.json'` that way), `--` for a dash.

## The change

Two places, deliberately not three.

1. **`src/refdes/cli.py`, the `check` subparser's `description=`** — one
   sentence, placed immediately after the clause it follows from ("verify (but
   never create or update) append-only seals"), so cause and consequence stay
   adjacent:

   > A seal exists only once 'build' has run over the entry, so an entry that
   > has never been built has no append-only protection at all, however many
   > clean runs of this command it has behind it.

   This is the finding's own suggested remedy ("a one-line note ... in
   `check --help`'s summary line") and it is the surface a check-first author
   actually reads.

2. **`docs/design-log.md`, the `## Append-only` section** — the existing
   sentence "`refdes check` verifies existing seals without creating new ones,
   so it is safe in CI" is the same fact with the same missing consequence, and
   "so it is safe in CI" is the phrase that reads as reassurance. Extended in
   place, worded differently from the help text (mechanism-first: no seal to
   pass or fail) rather than repeating it:

   > ... `refdes build` seals anything new it finds — which means an entry that
   > has never been through a build is not passing an append-only check: it has
   > no seal to pass or fail, and editing it fails nothing.

   Worth the second copy: `--help` reaches the operator running the command,
   `design-log.md` is where a reader forms the mental model of the mechanism,
   and the section already states "sealed on first build" two paragraphs up, so
   the inference is available there but still not drawn for them.

**Left alone:** `docs/cli-reference.md`'s `## refdes check` section, which also
states the fact ("verifies existing seals without creating new ones"). It is
the per-command option reference, it already links `design-log.md` for the
sealing mechanism, and a third copy of the same consequence is the duplication
the task warned against. If a reviewer prefers the docs surface over the
reader doc, that is the spot to move it to.

No source behavior touched: the edit is inside one string literal.

## Verification

- `refdes check --help` rendered for real (via
  `python -c "... from refdes.cli import main; main(['check','--help'])"` with
  this worktree's `src` first on `sys.path`, since the venv's `refdes` is an
  editable install pointing at `/home/jorb/work/refdes`, not this worktree) —
  the new sentence wraps cleanly at the default width and the rest of the
  description is unchanged:

  ```
  Validate the project without rendering a site: parse every item, resolve
  links, run calcs and checks, and verify (but never create or update) append-
  only seals and board-drift records. A seal exists only once 'build' has run
  over the entry, so an entry that has never been built has no append-only
  protection at all, however many clean runs of this command it has behind it.
  Exits non-zero on any error. Nothing of the project's own is written -- no
  site, no seal, no board or citation manifest, no baseline. The one exception
  is '.refdes/schema.json', the gitignored editor-completion schema every
  project-loading command refreshes.
  ```

- `pytest tests/test_no_write.py tests/test_seal.py -q` → 57 passed. No test
  pins `check`'s description text (grepped: `never create` appears only in
  `cli.py`; the only help-text-pinning tests are the `--no-write` ones in
  `test_no_write.py`).
- `ruff check src/refdes/cli.py --select E501,I` → 4 E501 findings, all
  pre-existing (lines 589, 696, 704, 1641); none in the edited block, which is
  wrapped under the 100-column limit.

## Status

Done. Changelog fragment: `changelog.d/check-help-unsealed-no-protection.fixed.md`
— precedent for a pure help-text wording fix is
`changelog.d/no-write-help-calc-rewrite.fixed.md`, and docs-prose-only
fragments (`docs-*.fixed.md`) are filed under `fixed` too.
