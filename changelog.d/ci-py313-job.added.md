- The test suite now runs on Python 3.13 as well as 3.11. Each job installs
  the project normally (`pip install -e ".[dev]"`), so pip resolves the newest
  dependencies that interpreter can take, and those sets are not the same
  version: `60 uA` in a calc rendered as `60 µA` on 3.11 and `60 μA` on 3.13
  from the same source tree, because pint 0.26 -- the first pint installable
  on 3.12+ -- spells its micro prefix U+03BC GREEK SMALL LETTER MU where 0.25
  spelled it U+00B5 MICRO SIGN, and it is the interpreter that decides which
  pint gets installed. `pyproject.toml`'s classifiers have claimed 3.11
  through 3.13 for a while and only one of them was ever executed. The new job
  is ubuntu-only and the existing 3.11 job is unchanged on both OSes, so this
  costs one runner rather than three.
