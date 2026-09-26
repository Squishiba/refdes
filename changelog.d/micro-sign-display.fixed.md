- A micro value's rendered unit no longer depends on the interpreter. `60 uA` in
  a calc rendered as `60 µA` on Python 3.11 and `60 μA` on 3.13 from the same
  source tree: the two micro prefixes are different code points that look
  identical, and the units library picks the character itself — pint spells its
  micro prefix U+00B5 up to 0.25 and U+03BC from 0.26 on, which is also the
  first pint release installable on Python 3.12+. Refdes now prints U+00B5 MICRO
  SIGN everywhere a unit is displayed: computed values, the `{{compare}}` table's
  cells, and the calc errors that name a unit, so a build is the same bytes on
  every machine and a page cannot print `µA` in a table and `μA` in the error
  beneath it. Input is unchanged — `u`, `µ` and `μ` are all still accepted as the
  micro prefix, and `docs/math.md` "Writing units" now says so.
