# Fix stale surrogate-keys status paragraph in AGENTS.md

Task: `AGENTS.md`'s "Current state, briefly" bullet claimed the corruption
lint, `refdes keys adopt`, the display-half refresh-on-rename, and any
`revise.py`/`former_ids.py` change were "still design only". Re-verify each
claim independently, then correct the paragraph; changelog fragment; commit,
push, PR.

Status: **finished.**

## Verification (each claim checked against the tree, not the prompt)

Working tree clean at start (`git status --short` empty), branch
`spotty-pony` at `bda7ab5`.

1. **Corruption lint — shipped.**
   - `src/refdes/keys.py:117` `malformed_key_message()` returns the Layer-1
     diagnostic (length, alphabet, then check character; the message tells
     you to restore from git rather than guess).
   - Wired in two places: `keys.validate()` (`keys.py:162`) reports a
     malformed *declared* key, and `build.resolve_links` (`build.py:531`,
     and again at `build.py:1366`) reports a malformed key inside a
     composite link target, labelled with the link name and readable half.
   - `keys_mod.validate(project)` is called from `build.build()`
     (`build.py:2841`), and `cmd_check` calls
     `build_mod.build(project, seal_write=False, ...)` (`cli.py:178`), so
     `refdes check` does run it — matching
     `changelog.d/key-corruption-lint.added.md`.
   - Tests: `tests/test_keys.py:402,417,432,447,509` and
     `tests/test_checks_keys.py:280` assert the exact message text.

2. **`refdes keys adopt` — shipped.**
   - `cli.py:1012` `cmd_keys_adopt`, parser at `cli.py:1679-1689`
     (`adopt`, `--dry-run`), delegating to `adopt_mod.apply(...)` over
     `src/refdes/adopt.py`.
   - Ran the real help: `python -c "... sys.argv=['refdes','keys','adopt','--help'];
     from refdes.cli import main; main()"` printed
     `usage: refdes keys adopt [-h] [--dry-run]` with the transactional
     description. (The installed `refdes` console script in
     `~/work/venv-refdes` is broken — `ModuleNotFoundError: No module named
     'refdes'` — unrelated to this task, so I invoked the module from `src`
     instead.)
   - Tests: `tests/test_keys_adopt.py` (8 tests, incl. byte-for-byte
     rollback, idempotency, dry-writes-nothing).
   - Documented in `docs/cli-reference.md:1037`.

3. **Display-half refresh-on-rename — shipped.**
   - `src/refdes/links.py:461` `expand_missing()` — docstring "Expand bare
     link targets and refresh stale composite display halves" — planned by
     `plan_expansion()` and decided per target by `_planned_target()`
     (`links.py:322-364`): composite + key resolves + stale label → rewrite
     to `{resolved.id}@{key}`; if the stale label names a *different* live
     item it warns and refuses. `checks: against:` shares the same rule via
     `expand_missing_checks()` (`links.py:896`).
   - Wired into the writable load: `loader.py:115` / `:122` / `:129`.
   - Tests incl. `tests/test_keys_links.py:383`
     `test_rename_refreshes_flow_list_display_half_and_preserves_key`.

4. **`revise.py`/`former_ids.py` cleanup — shipped.**
   - `grep -n "_rewrite_reference_ids|_rewrite_block_sequence|_rewrite_id_tokens|_relabel_id|_relabel_ledger|_restore_ledger|burned"`
     over `src/refdes/revise.py` and `src/refdes/former_ids.py` → no
     matches (exit 1).
   - `_rename_prefix` survives at `revise.py:807`, used by
     `_rewrite_type_and_prefix_lines` (`:407`, `:413`), `_stale_mapped_names`
     (`:750`, `:758`) and `_affected_ids` (`:1058`) — the id/prefix-line
     helper, exactly the deviation `docs/design/keys.md` records.
   - `revise` now runs the key pipeline inside its own transaction
     (`_run_key_ensure` `revise.py:907`, `_simulate_key_ensure` `:967`,
     `_refresh_display_halves` `:1039`, `_bare_reference_blockers` `:1064`),
     and `former_ids.propose` returns key-proven candidates
     (`former_ids.py:73` `_baseline_carries_keys`, `:82` `_entry_for_relabel`).
   - Tests: `tests/test_revise.py` + `tests/test_former_ids.py` (68 passed).

Test runs (targeted, this task is docs-only):
`pytest -q tests/test_keys.py tests/test_keys_adopt.py tests/test_checks_keys.py`
→ 79 passed; `pytest -q tests/test_revise.py tests/test_former_ids.py` → 68
passed.

## Cross-check against how the shipped feature is described

- `CHANGELOG.md` `[Unreleased]`, layer-2 entry (~line 141) already says
  "Still design-only **at the time of this entry**: ... All four have since
  shipped", pointing at `changelog.d/key-corruption-lint.added.md`,
  `keys-adopt.added.md`, `key-label-refresh.added.md`,
  `revise-keys-cleanup.changed.md` — all four fragments are present in
  `changelog.d/`. The layer-1 entry (~line 205) likewise says "design-only
  at the time of this entry and since shipped".
- `docs/design/keys.md:17` implementation-status paragraph: §1, §2, §3, §5,
  §6 Layers 1-5 and §7 implemented; §4 "now implemented" with two named
  deviations (`_rename_prefix` survives, `Mapping.prefixes` stays). That is
  the record AGENTS.md should defer to, and the corrected wording does.
- Nothing in `docs/design/keys.md` is flagged design-only any more (grep for
  design-only / not implemented / deferred / out of scope → no hits). §8's
  "should the ledger survive?" is an open *policy* question whose
  recommendation — keep the ledger — is what the code does (`ids.py` still
  tracks burned numbers; `refdes id` still at `cli.py:452`/`:1511`), so I
  did not describe it as unshipped work and left it out of the paragraph.

## The edit

`AGENTS.md` bullet only: "partially landed" → "fully landed", the four
former design-only items named as implemented with the file/symbol that
implements each, and a pointer to the design doc's implementation-status
paragraph. The `Item.links` vs `Item.resolved_links` warning, its
`model.py` cross-reference, and every other bullet are untouched.

No difficulties beyond the broken console script noted above.
