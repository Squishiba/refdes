- The captured-history semantic digest no longer covers a ```calc fence's
  `id="..."` label (finding R9-F2 of the run-9 release-gate simulation):
  naming a calc block — a label on the rendering, as `docs/math.md` calls
  it — of an entry already captured by a `follows:` edge no longer trips the
  `edited after captured` warning, and renaming one no longer trips it
  twice. The block's rows remain content: editing a row of a captured
  entry's named fence warns exactly as before. Items with no labelled calc
  fence digest byte-for-byte what they digested before, so no existing
  capture is invalidated by this change; an item captured *with* a labelled
  fence under the old digest gets one (warning-only, never build-failing)
  `edited after captured` line on the first build after upgrading, which a
  `refdes history capture` of the entry settles.
