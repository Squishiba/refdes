- **`refdes check` now rejects corrupt surrogate-key identity at its source:**
  keys must be exactly 11 lowercase Crockford-base32 characters with the
  correct check character; duplicate keys name both claiming items and source
  locations; and a composite link whose well-formed key no item declares is an
  error even when its readable label still matches a live item. Malformed link
  keys are reported as corruption with instructions to restore them from git,
  not misreported as deleted targets.
