- A corrupt `.refdes/keys-adopted.yaml` is no longer silently overwritten
  by `refdes keys adopt` at exit 0 -- a marker that does not decode, does
  not parse (e.g. a truncated `adopted: [`), is empty, or never declares
  `adopted:` true/false was read as "not adopted" and clobbered with the
  fresh marker. The command now refuses with the file named and says to
  repair it by hand or delete it, and leaves the file untouched -- the
  refusal `docs/troubleshooting.md` already promised for a corrupt marker.
  A well-formed `adopted: false` is not corrupt: it declares the state
  `keys adopt` exists to change, and adoption over it proceeds.
