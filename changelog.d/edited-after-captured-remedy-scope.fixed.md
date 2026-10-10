- The `edited after captured` warning's `amends:` remedy is now scoped to the
  entries it is legal for. The warning names the remedy for every captured
  item, but `amends` is a verb an append-only type declares for correcting
  its own entries -- under `hardware@3` it may point only at `log` -- and
  `refdes history capture` takes any keyed item. So a captured `requirement`,
  `bound`, `test` or `component` edited after capture was told to append an
  entry with `amends: [REQ-001]`, and doing exactly that failed the build:
  `amends may point at log, but REQ-001 is a requirement`. For an editable
  type the warning now says the deliberate edit needs nothing done about it
  and links the same page as before; an append-only entry still gets the
  `amends:` sentence. Trigger logic, level and exit code are untouched.
  `docs/troubleshooting.md`'s `## The design log` entry was updated to match.
