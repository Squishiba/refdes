- **A `type: decision` item in a project pinned to `hardware@3` now says
  what to do about it.** `decision` was retired into the merged `log` type,
  and a project pinned to `hardware@3` *by hand* (the default `refdes init`
  shape of the release that shipped v3 with `decision` in it) is the one
  shape the migration chain cannot reach: `refdes standard upgrade --to 3`
  refuses it, because it is already at `hardware@3`. Such a project used to
  get a bare `unknown type 'decision'.` on every item; it now gets the merge
  named — `type: log`, `title:` → `summary:`, `records:` → `follows:`, the
  fields and links that moved onto `log` — the reason the upgrade refuses,
  and the page in the standard-library docs that describes it. The four types
  the retired `design-debate` preset provided (`debate`, `option`, `claim`,
  `position`) get the same treatment: the preset is named, the two remedies
  (plain `log` items linked by `follows:`/`supersedes:`, or the four types
  declared in your own `refdes-schema.yaml`) with it. Like the `constraint` →
  `bound` hint this sits next to, the advice fires only in a schema that
  actually has the `log` type.
