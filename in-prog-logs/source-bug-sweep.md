# Source-bug cleanup sweep (session refdes-179)

One commit per bug, each with a test that fails on the unfixed code. Branch
`ao/refdes-179/source-bug-sweep`, one PR at the end, not merged here.

Bugs in scope:
1. `former_ids.propose` keyed path: baseline entry looked up by surrogate key
   against a display-id-keyed map, so `old_title` always printed empty.
2. `refdes revise nope.yaml` -> unhandled `FileNotFoundError` traceback
   instead of the exit-2 configuration error the exit-code table promises.
3. `revise` does not validate a link rename's target verb (type/field renames
   are validated both ways; link renames are not).
4. global `--no-write --help` text omits `calc-rewrite`.
5. `refdes id --dry-run` claims it writes nothing but load mints `key:` lines.
   Investigate; fix only if small and safe, else write up options.
6. `calc-rewrite` refuses the tolerance line `check` points it at.

Not to fix (report only): `history migrate-seals` marker ids for deleted
sealed items.

Docs fixes: `docs/standard-library.md` item-type count (twice) + the v3 group
type; `AGENTS.md` says `field_sets:` where the key is now `sets:`.

## Progress

- Branch cut from `ao/refdes-179/root` at 7f4b561 (origin/main already merged).
