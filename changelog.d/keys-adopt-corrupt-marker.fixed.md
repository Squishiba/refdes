- A YAML-corrupt `.refdes/keys-adopted.yaml` (valid UTF-8 that does not
  parse, e.g. a truncated `adopted: [`) is no longer silently overwritten
  by `refdes keys adopt` at exit 0 -- it was read as "not adopted" and
  clobbered with the fresh marker. The command now refuses with the file
  named and says to repair it by hand or delete it, and leaves the file
  untouched, as promised when the non-UTF-8 half was fixed.
