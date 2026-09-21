New `refdes history` command group (living notes phase H4):

- `refdes history capture <item>` captures the item's current semantic
  snapshot into `.refdes/history/` as a manual `captured` event and
  announces it (`captured LOG-A-011: manual capture`). It says
  "captured", never "final": the item stays editable and a later edit is
  the same `edited after captured` warning any other capture gives.
  Idempotent — a second run writes nothing and announces nothing. An
  explicit capture carries `occurred_at`; the automatic `follows:`
  capture deliberately does not.
- `refdes history redact <item-or-object> --confirm` removes matching
  history objects and events and writes one auditable `redaction` event
  naming what was removed by digest and event id only — never repeating
  its content — and prints the Git/clones/published-copies warning in its
  own output. Without `--confirm` it refuses (exit 2) and writes nothing.
  Redaction events are never themselves redaction targets; a snapshot
  another event still references survives until the last one goes.
- `refdes history migrate-seals [--capture-current]` reads the legacy
  seal files (`.refdes/log-seal*.yaml`) and writes one `legacy-seal`
  marker event per record — recorded hash only; original content was not
  captured — leaving the seal files untouched. `--capture-current` also
  captures current content, as a clearly dated `migrated-current` event
  (never labelled seal-time text), for sealed items whose live content
  still matches the recorded hash.

All three refuse under `--no-write` through `_refuse_no_write()` rather
than pretending they wrote something.
