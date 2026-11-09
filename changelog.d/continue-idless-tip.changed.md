- A thread tip needs an `id:` to be continued. The preview's task pane names
  no save context (no `data-refdes-tip-key`/`data-refdes-revision`) for a tip
  that carries an artifact key but no `id:` — the endpoint can write no
  `follows:` composite without both halves — so its ticks stay preview-only
  and the pane says so. `POST /api/item/<ref>/continue`'s refusal for such a
  tip now names it by its key (the old text rendered an empty subject:
  `refused:  carries no artifact key`). A tip with an `id:` is unchanged:
  same save context, same applied save.
