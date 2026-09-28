# Fix stale claims in two pending changelog fragments

Task: a correctness pass on two pending `changelog.d/` fragments that would
publish false facts at release time, per
`in-prog-logs/release-readiness-audit.md` §4.3 and §4.4. Both fragments existed
unchanged; each was re-verified against the code before editing.

**Status: finished.** Both fragments corrected, committed, pushed, PR opened.

## 1. `changelog.d/docs-update.added.md` — the "currently 3" hash format

Verified first: `src/refdes/build.py:1468` reads `HASH_FORMAT = 5`, so the
bullet's "(`hash_format`, currently 3)" was two formats behind. Confirmed the
other pending fragments are the ones that carry the intermediate steps, so
folding them all yields a correct 2 → 3 → 4 → 5 progression with exactly one
entry wrongly asserting a present-tense "currently 3":

- `changelog.d/checks-against-keys.fixed.md:3` — `hash_format: 3`
- `changelog.d/calc-sources-hash.changed.md:2` — part of `hash_format` 4
- `changelog.d/calc-cross-item-refs-hash.changed.md:2` — `hash_format` 4
- `changelog.d/image-bytes-hash.changed.md:1` — `HASH_FORMAT` is 5

**Fix:** rewrote that one bullet to describe the versioning *mechanism* — that
every stored hash records the format it was computed under, so the rules can
change without invalidating all existing hashes — with no hardcoded number that
can drift before the fragment folds. The fragment's other eleven bullets are
untouched.

I kept the rest of the bullet's claims but re-verified them rather than
assuming, since I was rewriting the sentence around them:

- "automatic migration for provably unchanged entries" — `src/refdes/keys.py`
  (`migrate_hash_format`, the `1 <= hash_format < build_mod.HASH_FORMAT`
  fallback at line 268) and `src/refdes/lifecycle.py:388-400`.
- "`uncomparable` reported by `refdes keys adopt`" — `src/refdes/adopt.py:240`
  and `:262` carry the counts into the adopt report, and
  `src/refdes/cli.py:1062-1072` prints them. True; kept.

## 2. `changelog.d/docs-audit-lifecycle-batch.fixed.md` — the `docs/output.md` bullet

Verified first: the last bullet claimed `docs/output.md` still carries an
unloadable `site.tokens` example ("a bare `--accent` beside `light:`/`dark:`
… Not fixed here"). That is no longer true. `docs/output.md:33-38` now shows a
single legal flat form:

```yaml
site:
  theme: paper
  tokens:
    --accent: "#b3541e"      # both palettes
```

and the prose at `docs/output.md:44-46` states the rule the broken example
violated ("A bare `--token` pair applies to both palettes; a `light:` or `dark:`
heading targets one, and a `tokens:` block that uses those headings may contain
only them — mixing a bare pair in with them is a load-time error").
`docs/schema-reference.md:64-70` shows the same flat form plus the two-heading
form as separate legal examples.

**Fix: removed the bullet, rather than rewording it to "already fixed".** The
reason is duplication, not just falsehood: the fix is *already claimed by a
sibling pending fragment* — `changelog.d/docs-audit-batch1.fixed.md:13` reads
"Docs: the `site.tokens:` example in `output.md` and in `themes.md` mixed a
bare `--token: value` pair with `light:`/`dark:` headings. That combination is
refused at load … Both examples were split, and the rule is now stated." Since
both fragments are pending, rewording this one to "already fixed" would report
the same `output.md` correction twice in the folded changelog. Deleting it
leaves exactly one accurate entry for the fix. The fragment's other eight
bullets are untouched.

`git log -S'# both palettes' -- docs/output.md` and the same search on
`docs/schema-reference.md` both return `c472aa2` (the two-palettes theming
commit), i.e. the correction predates this audit and is not a pending edit.

## Noted, deliberately not touched (out of scope)

- `docs-audit-batch1.fixed.md:13` says both examples "were split". The
  `output.md` one is now a single flat bare-pair example rather than a split
  pair, so "split" is loose wording — but the example is legal and the rule is
  stated, so the claim is not false. Flagging only; this task fixes the two
  fragments named above and does not widen.
- `CHANGELOG.md:144` still folds `HASH_FORMAT = 2` (noted in audit §4.3). That
  is a folded historical entry, correct in its own context, not a false fact.

## No new fragment for this task

This task *is* a changelog-fragment fix. Its only user-visible effect is on the
folded changelog's own accuracy, and a fragment announcing "two pending
fragments no longer lie" would add a line a user cannot act on while creating
exactly the kind of self-referential noise this pass removes. So the reasoning
is recorded here instead, per the AGENTS.md instruction to log work in
`in-prog-logs/`.

## Verification run

- `git diff --stat` — 2 files, 2 insertions, 2 deletions, both in
  `changelog.d/`.
- Read both fragments back in full after editing; no other bullet changed.
