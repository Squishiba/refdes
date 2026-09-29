- A speculative design for deterministic item search, scoped to
  `docs/design/item-search-hover.md`. **No code, no command, no endpoint, and
  no behaviour change** — the document's own status header says so, and its
  §8 lists every part as still design only. It records a proposal for a
  `refdes search` command, a read-only `GET /api/search` route, and a hover
  that surfaces candidates when an author types a self-question into an item
  body, with no model anywhere in the loop.
- Its substantive finding is negative, and is the reason it is worth reading:
  the `?`-in-prose trigger the idea rested on was checked against this
  repository's real content and found **zero** instances in `items/` and
  **zero** in `CHANGELOG.md`, with one genuine self-posed question in 1.3 MB
  of `in-prog-logs/` — a register this repository does not use. The document
  therefore recommends the opposite order from the one proposed: build the
  search, defer the trigger, and take the editor surface as a
  `Refdes: Search items` command before a hover.
- It also records that the repository has **no search infrastructure at all** —
  no `refdes search`, no full-text index, no `serve` route — and that the three
  substring matchers that do exist (`refdes ls`, `GET /api/items?q=`, and the
  browser editor's link filter) already disagree about whether a display id is
  searched. No matcher is unified by this change; `docs/design/item-search-hover.md`
  §6 Q3 proposes that as adjacent scope.
