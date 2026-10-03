- `refdes check --help` no longer claims that an entry which has never been
  built "has no append-only protection at all". That was written when every
  append-only type was `sealing: build`, and it is false of the bundled
  `hardware@3` `log`: it is `sealing: history` (`base.yaml:298`), so it is
  never sealed, which makes "has never been built" true of every one of its
  entries and the sentence read as "your log has no protection". The help now
  splits the two sealings and names the thing that does protect a
  history-backed entry -- the snapshot `refdes history capture` writes into
  `.refdes/history/` -- with the honest corollary that an entry that has never
  been captured has no protection of its own. `build --help`'s `--reseal`
  description was updated for this in the same delta; this was the sentence
  that was missed. No behaviour change.
