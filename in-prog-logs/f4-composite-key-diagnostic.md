# F4 — the upstream-key diagnostic never says the composite in *your* file was tool-written

Source: `in-prog-logs/user-sim-release-gate-run2.md` §"### F4".

> The message is well-written and, in the single-project case run 1 examined,
> right. In the import case it sends the downstream author upstream to fix
> something they cannot see, and never mentions the far likelier local cause:
> the composite in *their* file was written by a tool run, not by them …
> Worth a "this composite was written by refdes during a load, not by hand —
> see `docs/multi-board.md`" clause.

Status: **finished**. Clause added to the `live.external` branch of
`build._unknown_key_message`, verified by reproducing the whole two-project
scenario against the real CLI.

## 1. The branch, and what it is for

`src/refdes/build.py:484-524` `_unknown_key_message()` has three shapes:

1. bare key, no live target (`if not separator`);
2. composite whose label matches nothing live (`live is None`);
3. composite whose label *does* name a live item — and inside it, two exits:
   `live.external` (the target came from an import) → "restore its original
   key upstream", and local → the `refdes keys restore` recipe.

Only exit 3a changes here. The other three stay byte-identical — the local
exit is pinned by exact-equality assertions
(`tests/test_keys_restore.py::_message` builds the whole string and compares
with `==`), so anything that touched it would fail loudly.

## 2. Which doc to point at — read, then confirmed by running

- `docs/multi-board.md`, "What imported items can and cannot do": *"Their
  artifact also carries each durable surrogate key: a writable downstream load
  expands a bare link to `DISPLAY-ID@key`, and an upstream display-ID rename
  refreshes its display half while the key keeps the target fixed."* That is
  the import-side statement of composite-on-load, so it is the page a
  downstream author needs. **Chosen.**
- `docs/links.md` §"Structured link targets: composite form and automatic
  refresh" is the general (single-project) page — right topic, wrong audience
  for an import error.
- `docs/design/keys.md` is the authoritative design doc and is what
  `keys.py:773` / `links.py:526,963,1157` already point at for
  expansion-not-yet-run info. Kept as the pointer for those messages; not
  used here, because this error is about the *import* relationship.
- `docs/troubleshooting.md:148-183` documents this exact diagnostic family and
  already says "If the target is imported, restore the key in its upstream
  project and regenerate the imported artifact" — updated to match the new
  wording (§5).

One stale thing noticed while reading, **not touched**: `docs/design/keys.md`
line ~116 still lists "Imports have no key to expand into … `imports.py`'s
payload doesn't carry a `key` field today" as an open gap. `imports.py:64-101`
reads `key` from the artifact and `imports.py:118-121` indexes the item under
it, and the repro below shows a downstream composite being written against an
imported key. That bullet is out of date; correcting the design doc's status
prose is a separate change.

## 3. Before — reproduced, not assumed

`.scratch/f4/repro_f4.py` builds two real projects under `.scratch/f4/work/`
(`upstream` with `IFC-CAN-001`, `downstream` importing
`../upstream/_site/items.json` with `DEC-A-001 constrained_by: [IFC-CAN-001]`)
and drives them through `refdes.cli.main` from this worktree's `src` (the
installed console script is an editable install pointing at a *different*
worktree — `__editable__.refdes-0.5.0.pth` →
`…/help-text-gaps-f3-f5/src` — so `refdes` on PATH is broken here; everything
below ran through `.scratch/f4/rcli.py`, which puts this worktree's `src` first
on `sys.path`).

Step 2 is the finding's BUG 1, visible in the output: a plain `refdes check`
in the downstream project rewrote its own item file —

```
$ refdes check   -> exit 0
(minted 1 key(s) and rewrote 1 reference(s) while loading)
---
key: jkzsm5x6k2s
id: DEC-A-001
constrained_by: [IFC-CAN-001@hfcfwy6kxy4]
```

Step 3 drops the upstream `key:` line (the bad merge) and rebuilds upstream:
`(minted 1 key(s) while loading)`, artifact key now `71vt2cfhfrh`.

Step 4, downstream `refdes check` — exit 1, verbatim:

```
ERROR   items/decisions/pins.md:2 [DEC-A-001] — constrained_by points at key
'hfcfwy6kxy4' (labelled IFC-CAN-001), which no item declares. A live item
labelled IFC-CAN-001 declares key '71vt2cfhfrh'. Its key may have been lost and
regenerated, or the label may now name a different item. The label is not used
as a fallback. Check git history to confirm identity. If it is the same item,
restore its original key upstream.
```

Byte-for-byte the message quoted in the finding. Nothing about the composite
being a tool artifact.

Two notes from the run: the first attempt at the repro failed to trigger the
error because the `key:` line the upstream load writes is `- key: …` inside a
YAML list entry, so a `startswith("key:")` filter left it in place — the key
never changed and step 4 passed clean. Rewriting the file from its pre-mint
text is what actually loses the key. Second: the composite on disk is *not*
rewritten by the failing run — the error is reported, the file is left alone.

## 4. The change

`src/refdes/build.py`, the `live.external` exit:

```python
    if live.external:
        return message + (
            "If it is the same item, restore its original key upstream. This "
            "composite reference was written into your file by refdes on a "
            "load, not typed by hand — see docs/multi-board.md."
        )
```

Why these words: it names the thing the author is looking at (a composite they
don't remember writing), says who wrote it and when (refdes, on a load —
`check` included, which is the command that feels read-only), and points at
the page that explains the import relationship. It does not repeat the key or
the label, both already in the sentence before it.

## 5. Docs kept in step

- `docs/troubleshooting.md`: the entry for this diagnostic now says the
  composite half of the pair is tool-written and quotes the external-target
  ending as it actually reads.
- `docs/multi-board.md`: the pointer has to land, so the import section now
  says outright that the composite lands in *your* files, that a load wrote
  it, and that losing the upstream key surfaces as an error in your build.

## 6. Tests

`tests/test_keys_restore.py::test_imported_key_ownership_and_upstream_diagnostic`
already covers this exit (it asserts `"restore its original key upstream" in
message` and `"refdes keys restore" not in message`). Extended it, and added
`test_external_lost_key_diagnostic_says_the_composite_is_tool_written`, which
pins the new clause, its doc pointer, and — the part that matters — that the
*local* exit does **not** gain it, so the two branches can't drift into each
other.

## 7. The clause, as it actually prints

Same scenario, after the change — downstream `refdes check`, exit 1:

```
ERROR   items/decisions/pins.md:2 [DEC-A-001] — constrained_by points at key
'j5k5jerj8vd' (labelled IFC-CAN-001), which no item declares. A live item
labelled IFC-CAN-001 declares key 'tfyz9d52dnb'. Its key may have been lost and
regenerated, or the label may now name a different item. The label is not used
as a fallback. Check git history to confirm identity. If it is the same item,
restore its original key upstream. This composite reference was written into
your file by refdes on a load, not typed by hand — see docs/multi-board.md.
```

`_unknown_key_message` is shared by three call sites (`resolve_links`,
`run_checks`, calc references — build.py:573, 1070, 1417), so
`.scratch/f4/probe_other_call_sites.py` drove all three in one project. All
three print correctly, and the local branch is untouched:

| Reference | Target | Ending printed |
|---|---|---|
| `constrained_by:` | imported `IFC-CAN-001` | `… restore its original key upstream. This composite reference was written into your file by refdes on a load, not typed by hand — see docs/multi-board.md.` |
| `checks: [{value: I, against: …}]` | same imported item | identical ending |
| calc reference `DEC-A-002@zzzzzzzzzzz.I` | **local** item | `… run \`refdes keys restore DEC-A-002@zzzzzzzzzzz --dry-run\`, then repeat without --dry-run …` — no import clause |

## 8. Verification, run by run

Ran (not read):

- `.scratch/f4/repro_f4.py` — two real projects, real `refdes.cli.main`, before
  the change: reproduced the finding's message byte-for-byte (§3). After the
  change: the new clause prints in the real error output (§7). Exit 1 both times.
- `.scratch/f4/probe_other_call_sites.py` — the three call sites above, in one
  real `refdes check` run.
- `pytest tests/test_keys_restore.py -k "imported_key_ownership or external_lost_key"`
  → **2 passed**.
- The same two tests with the clause temporarily replaced by a stub string →
  **2 failed**, so both genuinely pin the new text rather than passing anyway.
  (Stub reverted; `git diff` confirms the shipped wording.)
- `pytest tests/` → **2852 passed, 2 skipped in 202.84s** (`-p no:randomly`).
  (An earlier draft of this log said 2796 — read off a partial wake-up before
  the run's last line landed. 2852 is the finished run's own output.) Nothing else asserts this
  message: the only other tests touching it compare against `_message()`, which
  builds the *local* string, and those still pass unchanged.
- `ruff check src/refdes/build.py tests/test_keys_restore.py --select I,F,E501`
  → 12 findings, all pre-existing and all on lines this change does not touch
  (`build.py:3,353,360,2258,2631,2851`; `test_keys_restore.py:67,104,176,343,346,349`).
  None in the added lines.

Read, not run:

- `docs/multi-board.md`'s import section as the pointer target (§2) — read, and
  its claim about composite-on-load independently confirmed by the repro, which
  writes `IFC-CAN-001@<key>` into the downstream file.
- `docs/design/keys.md`'s stale "Imports have no key to expand into" bullet
  (§2) — read only; the repro contradicts it, but correcting design-doc status
  prose is left to its own change.
- The `DOCS_URL` note in `cli.py:35-42` (a repo-relative `docs/…` path does not
  resolve for a wheel install). Kept the repo-relative form anyway, because
  every neighbouring key diagnostic already uses it (`keys.py:773`,
  `links.py:526,963,1157`) and `configcheck.py:102` points at
  `docs/multi-board.md` the same way. Flagging it as a known inconsistency in
  the convention rather than changing it here.

## 9. Files

- `src/refdes/build.py` — the `live.external` exit of `_unknown_key_message`.
- `tests/test_keys_restore.py` — extended
  `test_imported_key_ownership_and_upstream_diagnostic`; new
  `test_external_lost_key_diagnostic_names_the_composite_as_tool_written`.
- `docs/multi-board.md`, `docs/troubleshooting.md` — kept in step with the text.
- `changelog.d/external-lost-key-composite-provenance.fixed.md`.
- `.scratch/f4/` — `rcli.py`, `repro_f4.py`, `probe_other_call_sites.py`,
  `probe_schema.py` (left in place per AGENTS.md).

Not done, deliberately: the BUG 1 fix itself (suppressing load-time expansion of
references into imported items, or at least not doing it under a command that
feels read-only). This change makes the resulting error legible; it does not
stop the write.
