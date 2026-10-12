- **The key-pinning wording for links is renamed from `freeze`/`frozen` to
  `anchor`/`anchored` (vocabulary P4).** A bare `follows:` reference now
  "anchors" to the thread's current tip on the first writable load — the link
  stops floating on a display id and names the target's permanent key; nothing
  about it is immutable, which is what the old word wrongly suggested. Renamed:
  the `refdes keys adopt` report lines (`would freeze`/`froze N follows
  reference(s)` are now `would anchor`/`anchored N follows reference(s)`), its
  refusal ("could not anchor N local follows reference(s)"), the sealed-entry
  warning ("... because anchoring would change its hash"), and the code names
  behind them (`plan_follows_anchor`, `anchor_follows`, `FollowsAnchorPlan`,
  `chains.build_graph(anchored_only=...)`, `AdoptionResult.anchored_follows`).
  Nothing on disk changes: `.refdes/keys-adopted.yaml` never carried the
  count, item files and baselines/seals keep the same `DISPLAY-ID@key`
  composites, and the renamed field was an in-memory result plus printed text
  that nothing in this repo (editor sources included) consumes. The unrelated
  `frozen`s keep the old word: released standards and baselined ids are
  frozen (immutability), and image search still freezes a resolved path.
