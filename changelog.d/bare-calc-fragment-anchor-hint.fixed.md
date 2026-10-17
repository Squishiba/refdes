- `[[ID#calc]]` — the calc anchor with the name left off — is now hinted
  where it is reported (finding R9-F4 of the run-9 release-gate
  simulation). It was read as a field reference and warned "names field
  'calc', which type ... does not declare", which is true and does not say
  what to type: the anchor spelling is `[[ID#calc:<name>]]`. The warning
  now ends with "did you mean #calc:<name>?" — naming the blocks the target
  has when it has them, and pointing at `id="..."` on the fence when its
  blocks have none. An item that computes nothing gets no hint (there is no
  anchor for it to name), and every other field miss keeps its plain
  sentence. Level and posture are untouched: a fragment miss stays a warning
  that renders the reference's own text, never an error.
