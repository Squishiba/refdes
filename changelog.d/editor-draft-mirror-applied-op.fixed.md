- The browser editor's draft mirror can no longer survive an applied save
  op as still-pending. A multi-op save posts one op at a time; each 200
  response dropped that op from the in-memory draft, but the draft was
  persisted one step *earlier* (while recording the new revision), so the
  sessionStorage mirror kept holding the already-applied op and was never
  re-written after the drop. A tab reload restored the mirror as the
  pending draft: a field edit that had already landed on disk came back as
  an unsaved change (status "unsaved", re-postable by Save). Partial saves
  -- a later op refused (422) or colliding (409) -- were the reachable
  path; the full mirror and memory only agreed again after a complete
  save cleared the draft. The drop and the revision update are now one
  step in `drafts.js` (`dropAppliedOp`, replacing `setDraftRevision`)
  that persists once, after the draft no longer holds the applied op, so
  the mirror only ever contains what memory still considers pending.
