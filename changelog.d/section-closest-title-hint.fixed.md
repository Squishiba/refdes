- `section:` that names no outline entry now suggests the title the author
  meant, in more of the ways a person actually gets it wrong. Finding P2 of
  `in-prog-logs/pdf-picker-exercise.md` (low): the "closest outline titles" the
  `FAILED` line has always promised came from `difflib.get_close_matches` at its
  default 0.6 cutoff, which is calibrated for typos of similar length and is
  **silent on a truncated title** — the near-miss a person makes retyping a
  heading out of a datasheet's table of contents. Against that report's
  8-entry outline, `Therma`, `Electrical` and `Ordering` are prefixes of real
  entries and got **no** suggestion at all (0.480, 0.556 and 0.571 against
  `Mechanical Data`'s 0.800), while `Mechanical` got one. The same threshold
  also produced the wrong answer: `Regulatory Information` suggested
  `'Thermal Information'` **first**, because 0.683 > 0.625 for the correct
  `'Regulatory'`. The hint is now ranked by how the mistake was most likely
  made — the same title differing only in case, then one that is a prefix of the
  other, then one contained in the other, and only then difflib's spelling
  similarity — so a near-miss of the same length cannot outrank an exact
  wording apart from case. All three empty cases now name their entry, and
  `Regulatory Information` names `'Regulatory'` first. Still a hint: matching
  stays exact and case-sensitive, so nothing here resolves a title that did not
  match, and at most five titles are named, as before. `docs/markdown.md` now
  says which order they come in and that the closest one is never resolved for
  you.
