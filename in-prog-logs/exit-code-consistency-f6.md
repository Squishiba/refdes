# Exit-code consistency, F6 — "no such thing" exit codes

Source: `in-prog-logs/user-sim-release-gate-run2.md` §2 F6.

> `fetch --item NOPE-1` → exit **1**. `history capture NOPE-001` → exit **2**.
> Both are "the id you gave me does not exist" … `docs/cli-reference.md:13`
> reserves `2` for configuration errors.

Status: **finished** — no exit code changed; the docs were the wrong part.
Details below.

## 1. What the docs actually commit to

`docs/cli-reference.md:13`:

> Exit codes: `0` success, `1` errors found, `2` configuration error (including
> `--no-write` refusal).

`docs/design/lifecycle.md:676-683` restates the same convention for the
`revision`/`release` pair and adds the third case:

> `0` success, `1` diagnostic failure, `2` `SchemaError` …
> `2` — `SchemaError`: bad `release_gate:` config, **or an invalid name** (§2).

So the repo's own rule for "the name you passed is not usable" is **exit 2** —
but only for the commands that say so. The same file that F6 cites already
documents the two `history` cases explicitly:

- `docs/cli-reference.md:1236-1242` — `history capture` on an id that is neither
  a display id nor a surrogate key: "refused with **exit 2** and nothing
  written", with `refdes history capture NOPE-999` as the literal example.
- `docs/cli-reference.md:1241-1245` — `history redact` on a target that names no
  item and is not a 64-hex digest: "refused with **exit 2**".

and it documents the opposite choice, also explicitly, for four other commands:

- `:542` — `new <unknown type>` "exits 1 with a did-you-mean suggestion".
- `:603` — `schema --graph <unknown TYPE>` "exits 1".
- `:1029-1034` — `former-ids propose --baseline NAME` that names nothing, and no
  baseline stamped at all: "both cases **exit 1**".
- `:1154-1155` — `keys restore`: "a refused restoration **exits 1**".

plus exit 2 for `revise` on a mapping file that is not on disk ("like any other
configuration error", `:746-753`), for `standard add-preset`/`remove-preset` on
an unusable name (`:627-629`), and for `init`'s name checks (`:520-522`).

## 2. Before — every "named thing not found" site, measured

`.scratch/f6/probe.py`, `.scratch/f6/probe2.py`, `.scratch/f6/probe3.py` run the
real `refdes.cli.main()` against throwaway projects under `.scratch/f6/`. Codes
below are measured, not read off the source.

| Command | Code | Message (first line) | Documented? |
|---|---|---|---|
| `fetch --item NOPE-1` | 1 | `error: no item 'NOPE-1' in this project` | no |
| `fetch --item LOG-001` (exists, no citations) | 1 | `error: item 'LOG-001' declares no citations` | no |
| `fetch --path nosuch.pdf` | 1 | `error: no citation in this project cites 'nosuch.pdf'` | no |
| `history capture NOPE-001` | 2 | `error: no item 'NOPE-001' in this project (…)` | **yes — 2** |
| `history redact NOPE-001 --confirm` | 2 | `error: no item or history object 'NOPE-001' …` | **yes — 2** |
| `history redact LOG-001` (no `--confirm`) | 2 | refusal + Git caveat | **yes — 2** |
| `history redact REQ-001 --confirm` (nothing captured) | 0 | `no history objects or events matched …` | **yes — 0** |
| `history migrate-seals` (no seal files) | 0 | `no legacy seal files found; nothing to migrate` | **yes — 0** |
| `new nosuchtype` | 1 | `unknown type 'nosuchtype'.` | **yes — 1** |
| `schema --graph nosuchtype` | 1 | `unknown type 'nosuchtype'; this project's types are: …` | **yes — 1** |
| `former-ids propose --baseline nosuchbase` | 1 | `error: no baseline named 'nosuchbase'` | **yes — 1** |
| `former-ids propose --confirm NOPE-001` | 1 | `error: no baseline stamped yet …` | **yes — 1** |
| `keys restore LOG-001@zzzzzzzzzzz` | 1 | `refused:` | **yes — 1** |
| `standard add-preset nosuchpreset` | 2 | `configuration error: preset 'nosuchpreset' does not exist for hardware@3 …` | **yes — 2** |
| `standard remove-preset nosuchpreset` | 2 | `configuration error: preset 'nosuchpreset' is not currently selected …` | **yes — 2** |
| `init --standard nosuchstd` | 2 | `configuration error: standard.base must be one of hardware …` | **yes — 2** |
| `init --standard none --preset design-debate` | 2 | `configuration error: presets require a base standard …` | **yes — 2** |
| `revise nope.yaml` | 2 | `error: no such mapping file: nope.yaml` | **yes — 2** |
| `standard upgrade --to 1` (already at/past) | 2 | `configuration error: project is already at …` | **yes — 2** |
| `revision 'bad name!'` | 2 | `configuration error: 'bad name!' is not a valid revision/release name …` | **yes — 2** |
| `check --board nosuchboard` | 1 | `ERROR <project> — --board 'nosuchboard' is not a board declared …` | no |
| `check --workspace nosuchws` | 1 | same shape | no |
| `build --reseal nosuchboard` | 1 | same shape | no |
| `ls --board nosuchboard` | 0 | `no items match` | no |

Cross-check of the neighbouring documented claims (all hold): `index` on a file
that fails to parse → 0 (`:204-206`), `ls` → 1 (`:235`), `audit` → 1 (`:387`),
`check` → 1.

**Every documented exit code in the repo matches the code.** The one place the
code and the docs disagree is the one F6 does *not* cite: `docs/cli-reference.md`
never states what `fetch` returns for an unknown `--item`/`--path`.

## 3. Which sites I changed, and which I left alone

**Left alone — `history capture` / `history redact` (exit 2).** The report's
premise is that `docs/cli-reference.md:13` makes 2 wrong here. It does not: the
same document states these two cases as exit 2 in as many words, with
`NOPE-999` as the worked example, and states the write-nothing guarantee
alongside them. Flipping them to 1 would break a documented contract for no
documented gain — exactly the "do not restandardize what the docs already commit
to" line. The report read line 13 and not the two sections that qualify it.

**Left alone — `fetch --item` / `fetch --path` (exit 1).** Undocumented, so
nothing is violated — and the documented convention does not decide it either.
It cannot be derived from "2 = configuration error", because the repo documents
*both* answers for the same shape of mistake: `history capture NOPE-999` (a
lookup in the project) is 2, while `former-ids propose --baseline nosuchbase`
(a lookup in the project) is 1. There is no principle in the docs that picks one
for `fetch`. Per the task's own rule — flag an ambiguous case rather than invent
one — the code stays as it is. It is also pinned by an existing test,
`tests/test_citations.py::test_cli_fetch_unknown_item_returns_nonzero`, which
asserts `== 1`; that is a deliberate, if undocumented, commitment, and
overriding it needs a maintainer decision, not a docs-reading agent's guess.

**Left alone — `check --board` / `--workspace` / `build --reseal` (exit 1).**
These report through `project.error()`, so they land in `_report()`'s "errors
found" count and print as a normal `ERROR <project> — …` diagnostic. Exit 1 is
the only code available to a diagnostic, and these *are* diagnostics: they go
through the same channel as every other build error. Different mechanism from
`fetch`/`history`, and arguably the most defensible of the lot.

**Left alone — `ls --board nosuchboard` (exit 0).** "no items match" is a
listing result, not a name-resolution failure; `ls` has no notion of validating
its filters, and neither the docs nor any test claims otherwise. Changing it
would be a feature change, not a consistency fix. Flagged below.

**Changed — the docs.** `docs/cli-reference.md` was the wrong artifact: line 13
promised a two-way split that the per-command sections do not honour, and the
`fetch` section said nothing at all about the case F6 hit. Both are now
described as they actually behave, verified by running the commands above.

## 4. Flagged, not fixed

1. **`fetch --item` / `--path` on a name that does not resolve.** Undocumented
   and underdetermined by the convention. Two defensible resolutions, and the
   repo's docs support each of them for a *different* command:
   (a) leave 1, matching `former-ids propose --baseline`, `new`, `schema
   --graph`, and the existing test; (b) move to 2, matching the nearest sibling
   by message shape (`history capture`: `error: no item 'X' in this project`)
   and `revise`'s "like any other configuration error". I took neither. If a
   maintainer picks (b), the change is one `return 2` in `cmd_fetch` plus the
   existing test in `tests/test_citations.py`, and it is a breaking change for
   any script that branches on `fetch`'s code.
2. **The convention itself.** "2 = configuration error" does not cover "an
   argument names something that does not exist", and the repo has been deciding
   that case per command since `history` landed. If a single rule is wanted, the
   natural one is "a name that fails to resolve *before* the project is
   consulted → 2; a name that fails to resolve *in* the project → 1" — but that
   rule would move `history capture`/`redact` from 2 to 1, contradicting their
   documented behaviour, so it is a deliberate restandardization and not this
   task's to make.
3. **`ls --board nosuchboard` exits 0.** A typo'd board and an empty board are
   indistinguishable. Worth its own report, out of scope here.

## 5. Tests

`tests/test_exit_codes.py` — new. Pins the code for every row of the table above
that the docs commit to, so none of them can drift silently, including the two
cases F6 cites (`fetch` → 1, `history capture` → 2) and the already-correct ones
(`new` → 1, `schema --graph` → 1, `revise` → 2, `standard add-preset` → 2,
`former-ids propose --baseline` → 1, `history redact` without `--confirm` → 2,
`history redact` with nothing captured → 0, `history migrate-seals` with no
seals → 0, `revision` invalid name → 2). Each test names the doc line it pins.
The pre-existing `history` tests asserted only `!= 0` for the unknown-id case;
they are untouched — the new file is where the exact code gets pinned.

## 6. Verification

- `pytest tests/` — **2781 passed, 2 skipped** in 197s, including the 18 new
  tests in `tests/test_exit_codes.py` (all passed on the first run, i.e. every
  code asserted there is the code the code already produced).
- `pytest tests/test_docs_examples.py tests/test_standard_docs_complete.py` —
  8 passed, so the docs edits do not trip the docs-consistency tests.
- `ruff check src/refdes/cli.py --select I,F` — clean. `src/refdes/cli.py` is
  not touched by this change at all.
- `ruff check tests/test_exit_codes.py --select I,F,E501` reports one `I001`
  for the `pytest` / `conftest` / `refdes` import block. `tests/test_history_commands.py`
  reports the identical `I001` on the identical block shape, so the new file
  matches the convention every other test module in the repo uses; ruff is not
  run over `tests/` here.
- Before/after exit codes: **identical**, by construction — the change is docs +
  tests. Re-measured after the change with `.scratch/f6/probe.py`; every row of
  the table in §2 reproduced with the same code, including the two F6 cites
  (`fetch --item NOPE-1` → 1, `history capture NOPE-001` → 2).

## 7. What a maintainer still has to decide

Nothing here is settled by this change; it is made visible instead of left
implicit. The open question is §4.1 — whether `fetch`'s unknown-name `1` is the
choice or an oversight. If it is an oversight, the fix is one `return 2` in
`cmd_fetch`'s `except citations_mod.CitationError` arm plus updating
`tests/test_citations.py::test_cli_fetch_unknown_item_returns_nonzero` and the
three `fetch` tests here, and it is a breaking change worth a
`.breaking.md` fragment. If instead a single rule is wanted across the tool
(§4.2), that moves `history capture`/`redact` and needs `docs/cli-reference.md`
rewritten in the same commit, since those two are documented as they are today.
