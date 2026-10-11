- The `edited after captured` warning's `amends:` remedy is now scoped to
  where the project's own schema makes it legal. The warning names the remedy
  for every captured item, but `amends` is a verb a type declares for
  correcting entries of the types its link targets list -- under
  `hardware@3` only `log` may be pointed at -- and `refdes history capture`
  takes any keyed item. So a captured `requirement`, `bound`, `test` or
  `component` edited after capture was told to append an entry with
  `amends: [REQ-001]`, and doing exactly that failed the build: `amends may
  point at log, but REQ-001 is a requirement`. Gating on `append_only` alone
  left the same class of over-reach one notch narrower: an append-only type
  whose own declaration carries no `amends` verb (a project overlay replaces
  a type's links wholesale, so even an overlay's `log` can be in this shape)
  still got the sentence, where following it is a silently-dropped
  `unknown field 'amends'` warning. The sentence is now emitted only when
  some declared type's `amends` link may point at the entry's type.
  Everywhere else the warning records the mismatch and says a deliberate edit
  needs nothing done about it -- an editable type, or an append-only one
  without the verb -- and an entry whose type the schema does not declare is
  not called editable either, just unknown. Trigger logic, level and exit
  code are untouched. `docs/troubleshooting.md`'s `## The design log` entry
  and the README's sample warning were updated to match.
