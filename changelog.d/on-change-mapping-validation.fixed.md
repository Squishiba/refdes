- An item's `on_change:` mapping form is now validated like its scalar
  form: `mode:` and every `fields:` value must be one of
  `invalidate, timeline, ignore`, and the mapping accepts no keys beside
  `mode:`, `fields:` and `reason:`. Previously a typo like `mode: timeine`
  loaded silently and the whole-item suppression just stopped applying,
  so body edits churned the content hash with no diagnostic. A bad entry
  is reported at load and dropped, not applied.
