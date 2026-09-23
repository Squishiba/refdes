Status: **Architecture decided (2026-09-23)** — Jared answered all five
questions in §7; each is recorded below as decided, not an option under
continued review. Implementation (W1–W4, §8) has not started.

# Thread workbench: a live authoring pane for working notes

## 1. Problem

Threads are the genre refdes built for *process* — the live record of how a
design came about. Living notes made the genre safe to work in: an entry stays
editable until a `follows:` edge captures it, and even then an edit is a
visible marker, never a lock (`docs/design/living-notes.md`: "Do not make an
entry permanently uneditable"). And living-notes ratified the framing outright:
**"Treat source files as the product; treat the site as one projection."**

What was never built is the *view* that framing implies for authoring. Today
every semantic fact about an entry — what an image query resolves to, what a
calc variable evaluates to, what the thread currently concludes, whether a link
resolves — is visible only after a build, in a different surface. The authoring
loop is edit → build → go look over there. Two concrete frictions:

- **Images are queries, not paths.** A local `src` is searched across
  `site.assets` directories, errors on ambiguity or absence, is content-hashed,
  and is rewritten at build (`docs/markdown.md`, "Images and other local
  files"). While authoring, the document does not yet know which file it means
  — so no editor can show the picture, and the failure modes (dangling,
  ambiguous) surface only as build errors.
- **Values are name-only in prose.** A calc block renders its own table of
  expression → result, and a dotted reference (`DEC-PWR-001.V_in`) binds a
  name (`docs/math.md`), but prose that cites a variable cannot show its
  value. The build computes the number and then refuses to show it where the
  number is being *used*.

The result: the one entry type designed to be worked on continually is
authored with the affordances of a finished document. It reads as a draft for
a presentation, not as a workbench.

## 2. Proposal

A **workbench view** inside `refdes serve`: a single-item projection, pinned
to the entry under work (typically a thread tip), rebuilt when the project
changes, carrying **additive author decorations** the published site does not
show.

This is not a new storage model, not a new renderer, not a new document genre.
The thread tip *is* the worksheet genre; this is the missing projection of it.

The machinery is mostly already shipped. Verified in source (not run in this
session — the `refdes` console entry point was not importable here):

- `refdes serve` already serves a preview "rebuilt into an OS temp directory,
  never `_site/`" and "edits made outside the browser are picked up by
  polling" (`src/refdes/cli.py`, `serve` parser description).
- `serve/preview.py` renders each rebuild into a fresh generation directory
  and swaps it in atomically — a rebuild loop that never shows a half-written
  site already exists.
- `serve/state.py` runs a `Poller` (1 s interval, `serve/server.py`) over
  project inputs; `serve/api.py` does a "full rebuild after save" (see the
  comment at the `POST /api/item/<ref>/edit` handler). The design's rebuild
  baseline is a ~1 s full build (`serve/filters.py` docstring note).
- `refdes index` already calls the build pipeline *without* rendering HTML and
  exports coverage, calculated values, checks, links, and diagnostics
  (`docs/design/living-notes.md` §"The model in one page"; `src/refdes/cli.py`).
  The headless semantic projection exists; the workbench consumes it.
- The **decoration precedent** exists: the "Edit" toolbar is injected into the
  HTTP response only, "never written into the rendered files"
  (`src/refdes/serve/__init__.py` docstring). Overlays that strip at publish
  are already house convention.
- The folded thread panel is already rendered: any item in a thread gains a
  **Thread** section with the "currently concludes" fold, per-field values
  attributed to the entry they came from, and an explicit forked-thread state
  (`docs/design/threads.md`, Phase 3b).

## 3. The contract (non-negotiable)

Three clauses, in order of priority:

1. **Same semantics.** Every fact the pane shows comes from the built
   in-memory snapshot via the existing Python pipeline. No second Markdown
   dialect, no JavaScript calc evaluator, no client-side link resolver — the
   browser-editor architecture decision stands ("Python remains the only
   implementation", `docs/design/browser-editor.md`). `serve/filters.py`
   states the rule for the editor already: "answers come from the **built**
   project in the in-memory snapshot, never from a file scan." The pane
   inherits it.
2. **Smaller scope.** The pane renders one entry plus its dependency frontier:
   its calc blocks evaluated, its images resolved by the real asset search,
   its links resolved to titles, its thread's folded state. Not the site —
   the item's neighborhood. Note this is an *optimization goal*, not a v1
   requirement: v1 may decorate the existing full preview and pin the view to
   one item (§8, W1).
3. **Additive decoration only.** The difference between pane and published
   page must be overlays that strip cleanly — never a different interpretation
   of the same source. The pane may show *more* than the site; it must never
   *disagree* with the build about what anything means. If pane and site can
   diverge on meaning, the pane becomes a second compiler wearing a viewer's
   clothes, and the edit → build → view chasm reopens in a new costume.

**One pane, both couplings (decided 2026-09-23, §7.3 × §7.5).** Because the
workbench is a *mode of the item's own `/preview/` page* — a URL that exists
independently of `/edit/` — it is inherently usable standing alone next to an
external editor (Jared writes prose in VS Code today), and equally reachable
as a link from `/edit/` once that is the primary authoring surface. There is
no standalone-vs-integrated fork to build: one implementation serves both
couplings, and neither editor is a dependency of the other.

## 4. Invariants

- **Rendering never captures.** Living-notes: "no snapshot is created by
  `render_site()`, a `--dry-run`, or any `--no-write` run." A watch loop that
  re-renders on every save is a render, forever capture-inert. This must be
  structural (the pane reuses the no-write path), not luck.
- **The pane is read-only.** Files remain the source of truth; edits go
  through files or `/edit/` exactly as before. The pane is a projection, never
  the writable surface.
- **Never touches `_site/`.** Inherited from `serve/preview.py`; the workbench
  is the same generation-swap mechanism.
- **Security inherited unchanged.** Loopback-only, per-launch token gates
  reads and writes (`serve/security.py`). The pane adds no new surface.

## 5. Decoration set

Candidates, each an overlay per §3.3:

| # | Decoration | Source of truth | Notes |
|---|---|---|---|
| D1 | **Calc values inline** — evaluated result rendered beside each `{{value}}`/dotted reference in prose, name as attribution | calc evaluator, already expanded to `DISPLAY-ID@key` | Decided §7.1: pane-only overlay; publishing live numbers on the site is a separate, later decision |
| D2 | **Image provenance** — resolved source path + content hash on hover; ambiguity/absence as an inline squiggle at the `![]()` | the asset-search the build already runs | Turns the two image failure modes into author-time signals |
| D3 | **Inline diagnostics** — build diagnostics for this entry (unit errors, dead links, image ambiguity) mapped to file:line and rendered in place | the build's diagnostic list, already file:line-shaped | The single highest-friction reducer |
| D4 | **Thread panel pinned** — the folded "currently concludes" panel (threads.md Phase 3b) fixed at the top of the pane, fork warnings prominent | `chains.py` fold, already built and memoized | This is the "see what's actually going on" content mid-thread |
| D5 | **Edited-after-captured marker** | living-notes history comparison | Makes the capture boundary visible exactly where it matters |

## 6. Why this is not "become Calcpad" / not IDE creep

Calcpad's liveness is bought with document-local semantics: nothing has to be
resolved against a project, so an editor can render everything inline for
free. Refdes' whole value is project-wide semantics — images as queries,
cross-item calc references, checks, coverage, sealed history. Liveness for
those can only come from a serve-side projection run by the one true
implementation. That is precisely what this proposes, and the contract (§3)
plus the invariants (§4) are what keep it from sliding into a second editor
runtime to maintain. Every decoration must answer to: *which existing Python
mechanism produces this, and how does it strip at publish?*

## 7. Questions — decided (Jared, 2026-09-23)

1. **Inline values in prose: pane-only, or first-class?**
   **Decided: pane-only for now.** D1 is an overlay the site never shows.
   Publishing live numbers to the rendered site is deferred as a separate,
   later decision — it is not implied or pre-committed by anything here.
2. **Scope: thread tips only, or any item?**
   **Decided: any item.** The mechanism is item-scoped; thread tips are the
   killer app, not the boundary. A `log` head, a `decision` under revision,
   and a part record all benefit from D2/D3.
3. **Coupling to an editor.**
   **Decided: both.** Jared writes prose directly in VS Code today (that is
   what exists), and intends to author through the browser `/edit/` UI once it
   is built out; the pane must be usable alongside either. This resolves via
   §7.5 rather than forking: the workbench is a mode of the item's own
   `/preview/` page with its own URL, independent of `/edit/` — standalone
   next to an external editor today, linkable from `/edit/` later, one
   implementation either way. See the note under §3.
4. **Latency budget.**
   **Decided: ~1 s full rebuild is fine for v1**, but cheap, obvious wins are
   picked up opportunistically *during* W1–W3, not parked in a deferred
   phase — see the reframed W4 in §8. Explicit constraint: do not invent
   speculative optimizations; if nothing cheap is visible while implementing
   W1–W3, say so plainly rather than manufacturing a change.
5. **URL surface.**
   **Decided: a mode of the existing `/preview/` page** for the item — one URL
   per item, `?workbench=1` or a toggle — not a new `/workbench/<ref>` route.
   D1–D5 decorate the real page, not a parallel template.

## 8. Phasing

- **W1 — pin.** Preview already rebuilds on change and swaps generations
  atomically; add "open this item's preview page" from `/edit/` and
  auto-reload on revision change. No decorations. Mostly glue.
- **W2 — squiggles.** D3 diagnostics mapped into the page + D2 image
  provenance. Both read data the build already produces.
- **W3 — values.** D1 inline calc values (pane-only per §7.1) and a
  show-values toggle on calc tables.
- **W4 — speed (folded in, not deferred-as-a-phase).** Per §7.4: cheap,
  obvious wins — e.g. avoiding redundant work already visible in the build
  path — get folded into W1–W3 as they are encountered. A dedicated
  incremental/single-item rebuild effort stays deferred unless the ~1 s
  ceiling is actually felt. No speculative optimizations: if nothing cheap is
  visible while implementing W1–W3, that is the finding, stated plainly.

Each phase is independently shippable and independently verifiable against the
contract: for every rendered fact, name the Python mechanism that produced it.

## 9. What this document does not propose

- No new item type, no scratch genre (the thread tip already is one).
- No new storage, no database, no editor-owned truth.
- No client-side semantics of any kind.
- No change to capture, sealing, coverage, or check semantics.
- No change to what the published site renders.
