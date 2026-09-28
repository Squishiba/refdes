- `AGENTS.md` no longer claims the surrogate-key corruption lint,
  `refdes keys adopt`, the display-half refresh-on-rename, and the
  `revise.py`/`former_ids.py` cleanup are "still design only" -- all four
  shipped (the lint in `keys.malformed_key_message()`/`keys.validate()` and
  `build.resolve_links`, adopt in `cli.cmd_keys_adopt` over `adopt.py`, the
  refresh in `links._planned_target`, and the cleanup leaving no
  `_rewrite_reference_ids`/`_relabel_ledger`/`_restore_ledger` or
  burned-prefix check behind, with `_rename_prefix` kept on purpose as the
  id/prefix-line helper). The paragraph now says the keys design is fully
  landed and points at `docs/design/keys.md`'s implementation-status
  paragraph as the record; the `Item.links` vs `Item.resolved_links`
  warning it carries is unchanged.
