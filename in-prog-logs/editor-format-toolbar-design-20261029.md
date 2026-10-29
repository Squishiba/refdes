# Design: browser-editor formatting bar, refdes-specific buttons, and an editor font setting

Date: 2026-10-29
Status: DESIGN — docs-only PR, no code shipped here.
Owner request (Jared): give the body editor "fonts and markdown
formatting insertion, like how making a post works on forums", plus
refdes-specific insertion buttons. The font setting is explicitly its own
separate configuration; it is not part of the formatting bar.

This document is written against `main` at `f94a503` plus the in-review
live-calc PR #388 (`pr388` branch, head `a18bd7d`). Every factual claim
names the file (and line, or the command run) it was verified against
during this session, per `AGENTS.md`. Where a claim could not be verified
by running it, the text says so.

---

## A. Verified baseline (what the editor is today)

All line numbers below were read in this session; `main` is `f94a503`
(`git log --oneline -3`), clean worktree at
`/home/jorb/.paseo/worktrees/16msma8v/docs-editor-toolbar-design`.

### The body editor is one `<textarea>` with insertion helpers

- `createEditor` (src/refdes/serve/static/editor.js:12) builds the edit
  form. The body is a plain `textarea.body-edit` (rows=12) created in
  `bodyControl`, with `data-edit-key="body"` (editor.js:190-212) so
  `applyControl` (src/refdes/serve/static/update.js:20-52) carries the
  node — and its focus/caret — across full re-renders.
- The textarea's only live wiring is `area.addEventListener("input",
  writeBody)` (editor.js:209), where `writeBody` calls `setDraftBody` +
  `refreshStatus` (editor.js:203-207). `area._refdesCommit = writeBody`
  (editor.js:210) is the **official commit hook** for programmatic
  mutations that deliberately do not fire an `input` event.
- Mounting: `item.js` calls `bodyControl` and appends the pickers under
  the textarea (src/refdes/serve/static/item.js:176-190). When the body
  is not editable, `bodyControl` returns `null` and the pane shows
  `pre.body-text` + a reason badge (item.js:177-179) — the bar design
  below hangs off exactly this seam.
- **The create form has no body field at all** — `create.js` builds
  fields only (grep for `body` in create.js finds none). The bar and font
  setting are item-edit-form features.

### Existing insertion helpers (the pattern to follow)

- `insertIntoBody` (editor.js:102-118): paragraph-aware insertion — pads
  open/close blank lines, then mutates `area.value` by splice,
  `setSelectionRange`, `focus()`, and `area._refdesCommit()`
  (editor.js:116). **It does not use `execCommand`**, so today's image
  insertion is not one clean native Ctrl+Z step, and no `input` event
  fires (the commit hook is called directly).
- `insertSourceLine` (editor.js:123-159): the server-composed source line
  is inserted inside the last/nearest ` ``` ` fence; `setDraftBody` +
  `addDraftPin` (editor.js:150-151). Accept-and-save saves immediately
  (editor.js:161-166).
- **Image picker** (src/refdes/serve/static/images.js): rows come from
  `GET /api/images`; the inserted line is **server-composed**
  (`image_markdown`, src/refdes/serve/api.py:1487, set on rows at
  api.py:1545-1546 as `row.markdown`), so the client never guesses
  markdown shape. Rows can be `insertable:false` with a visible reason
  (images.js:71-76). Upload POSTs to `/api/assets` and inserts
  `![stem](url)` (images.js:208).
- **Source picker** (src/refdes/serve/static/sourcepicker.js):
  server-composed calc lines, accepted into a calc fence.
- **Link picker** (src/refdes/serve/static/links.js): candidates from
  `GET /api/items` (`links.js:44-47`, `PICKER_LIMIT = 5000`), filtered to
  the schema-declared link targets (links.js:56-61). It creates **draft
  link ops, not body text** — this is a picker UI we can reuse for a
  `[[ID]]` body reference, not a body insertion helper.

### Drafts, save, re-render

- Drafts live in a memory Map mirrored to `sessionStorage` under
  `refdes.draft.v1.<handle>` (`drafts.js:9`); a corrupt mirror is
  preserved, not overwritten (`drafts.js:86-110`). `setDraftBody`
  (drafts.js:243-248) persists through the storage mirror
  (`drafts.js:187-194`).
- Save (editor.js:231-265): ops are sent one at a time with
  `expected_revision`; `saveAll` **snapshots `pendingOps()` once**
  (editor.js:251) and `clearDraft()` on success (editor.js:252).
  Consequence, verified by reading the flow: **an insertion that lands
  after the snapshot is silently dropped** — `clearDraft` wipes it and
  the post-save re-render rewrites the textarea to the server value
  (editor.js:201-202). Any toolbar must therefore be inert while a save
  is in flight. PR #388 supplies the shared accessor for this
  (`saving` flag + `isSaving()` in the pr388 editor.js).
- 409 → full conflict pane with mine/theirs/copy affordances
  (editor.js:260, 287-322); 422 → field errors block the save
  (editor.js:240-244).

### The live-calc panel (PR #388, in review) — the contract the bar shares

`live-calc.js` (387 lines on the `pr388` branch; read in full from
`git show pr388:src/refdes/serve/static/live-calc.js`) attaches to the
**same textarea**. Verified contract, from that file and
`in-prog-logs/inline-calc-live-editor-design-20261020.md` §3.5-§3.8
(lines 463-714):

- Recompute on `input`/`blur`/`focus`, debounced 400 ms
  (`DEBOUNCE_MS`, live-calc.js:16).
- Auto-fill of `= result` writes via
  `document.execCommand("insertText")` ("Case A", live-calc.js:315),
  last-to-first, only while the textarea is focused; a caret inside the
  result range (inclusive) or a selection overlapping it skips the write
  (`selectionSkips`, live-calc.js:259-265).
- If `insertText` returns false/throws ("Case B"), it splices
  `area.value`, calls `_refdesCommit()`, and **does not dispatch
  `input`** (live-calc.js:325-333); once proven broken, auto-fill stands
  down for the session via sessionStorage
  `refdes.live-calc.fallback` (live-calc.js:23).
- The auto-fill toggle is **localStorage** `refdes.live-calc.autofill`
  (live-calc.js:17) — per-user browser preference, chosen over
  project config for documented reasons (design §6.1, lines 866-966):
  it is a UI preference, `refdes-project.yaml` holds shared project
  facts, and the editor has no per-user identity.
- Auto-fill is gated on `isSaving()` (live-calc.js:185,236,270) —
  precisely the save-race above.

The formatting bar inherits all of this: its inserts are ordinary
typing, and it must not fight the panel.

### Security and CSP (measured, not recalled)

- The editor shell is served under `EDITOR_CSP`
  (src/refdes/serve/security.py:71-79): `default-src 'none';
  script-src 'self'; style-src 'self'; img-src 'self' data:;
  connect-src 'self'; frame-src 'self'; base-uri 'none'; ...`.
- **Measured in this session** with headless Chromium 153.0.8010.52
  (`/usr/bin/chromium --headless --dump-dom` on
  `.scratch/editor-toolbar-design/csp/probe.html`, same-origin http):
  under `style-src 'self'`, **CSSOM writes from scripts apply**
  (`el.style.fontFamily = ...`, `el.style.setProperty('--x', ...)`)
  while **injected `<style>` elements are silently blocked**. So the
  font setting must apply through CSSOM on the element (custom
  properties), and the design below is CSP-neutral: it changes no
  header, injects no style element, no inline handler.
- `tests/test_serve_static.py` enforces this textually over every
  served file: no inline handlers, no `eval`/`new Function`,
  every import resolves, modules parse as ES2020 (lines 33-116). Any
  new module must satisfy it.

### Config surface for a font setting

- Project settings live in `refdes-project.yaml`;
  `_KNOWN_SETTINGS` is a whitelist in src/refdes/schema.py:65-73 and an
  unknown key is a config error naming the block path
  (schema.py:774-782). Nested validation is in
  src/refdes/configcheck.py (`validate_settings`). Adding an
  `editor:` block means: schema.py whitelist + configcheck validation
  + docs/schema-reference.md + schema tests. There is **no editor
  settings block today**; `site:` is site presentation (title/pages/
  theme/tokens → build output, schema.py:1087-1094), not the editor.
- The editor has **zero localStorage usage on `main`** (grep of
  src/refdes/serve/static/) — localStorage arrives with #388
  (`refdes.live-calc.autofill`), which establishes the precedent and
  the key-naming convention.

### Body-syntax ground truth (docs/markdown.md, docs/math.md)

Verified by reading both files in this session; renderer probes run
against `MarkdownIt('gfm-like', {html: False, linkify: False})` (the
exact call in build.py, used in src/refdes/build.py:2694 — the preset
string and options confirmed in this session's probe):

- Inline/inline-ish: `**bold**`, `*italic*` (docs/markdown.md:10-12),
  `~~strike~~` (renders `<s>`), `` `code` ``, links `[text](url)`.
- Headings `#`..`######` (probe: `<h3>` renders), lists, blockquote,
  fenced code, GitHub tables (docs/markdown.md:29-36; probe:
  `<table>` renders).
- **Task-list checkboxes do NOT render** as checkboxes in this
  renderer (probe: `- [ ] open` → `<li>[ ] open</li>`). A task-list
  button would insert text that renders as literal `[ ]` — see
  non-goals.
- `---` is a horizontal rule; a bare `---` **followed by YAML keys and
  a closing `---`** splits a multi-item `.md` file
  (docs/markdown.md:24-27). Insertion must keep `---` separated by
  blank lines from YAML-key-shaped content.
- refdes syntax: `[[ID]]`, `[[ID|label]]` (docs/markdown.md:69-75),
  `[[fig:id]]` (figure references, markdown.md:274-278 — cross-item
  only in combined documents), `[[cite:id]]`, `[[ID#field]]`,
  `[[ID#calc:name]]`.
- Images are plain markdown: `![alt](path)` (markdown.md) — **not**
  `[[fig:id]]`; figure ids come from the `{id="..."}` suffix.
- Calc fence: ` ```calc ` with optional `id="name"`, name grammar
  `[a-z][a-z0-9_-]{0,39}` (docs/math.md:41-62), body lines
  `name = expr | unit` (math.md:8-19). Fence grammar is strict — a
  half-typed fence is a build **error**, so a fence skeleton must
  always leave fences balanced.
- Inline calc span: `` `name := expr | unit = result` `` (math.md
  §Inline calc; trigger: a single-backtick span containing a non-quoted
  `:=`; the text before `:=` must be a calc name). A triggered span
  that fails to parse is a build error; a stored block whose result is
  missing is the warning the live panel shows (math.md, design §3.7) —
  so the span skeleton has a real decision (open question Q4).
  `{{name}}` / `{{name | unit}}` are values (math.md:59-65);
  unresolved values stay as written with a warning
  (markdown.md:312-313) — a `{{}}` skeleton is safe to insert.
- Navi marker (PR #382, in review): `<!--navi:KEY text-->`, one line,
  `-->` forbidden in the text, keyless marker minted on the next
  writable load — **verified from in-prog-logs/navis-design-20261025.md
  §4, lines 100-127, 220-232** (marker grammar at line 109, author
  example `<!--navi: remember X-->` at 120).
- Raw HTML is disabled; HTML comments are inert in output
  (docs/math.md:381-384, docs/markdown.md).
- No `<form>` elements exist in the shell (grep), so button default
  `type=submit` is harmless today — the design mandates explicit
  `type="button"` anyway.
- **No keydown handlers exist anywhere in the editor JS** (grep
  `keydown|ctrlKey|metaKey` across src/refdes/serve/static/: no
  matches). Every shortcut below collides only with the browser, not
  the app.

### Editor docs state

`docs/browser-editor.md` **does not exist** (verified with ls/glob).
The design doc is `docs/design/browser-editor.md` (1341 lines);
"Editing and previewing bodies" (lines 424-448) describes the plain
textarea + insertion helpers, and "What v1 must deliver" item 5
(lines 1155+) lists the `[[ID]]`, `[[fig:id]]`, and calc-fence
insertion helpers as **still outstanding** — section C below is that
item, scoped.

---

## B. Formatting insertion bar

### Placement and mount

A `.format-bar` div mounted **inside `bodyControl`'s return path,
directly above the textarea** (editor.js:190-212 construction; mounted
by item.js:176-190). Choosing the `bodyControl` seam (not a sibling
widget) buys three baseline properties for free, each of which the bar
would otherwise have to re-implement:

1. `data-edit-key` re-render carry-over (update.js:20-52): the textarea
   node is reused across re-renders, so focus/caret survive and bar
   handlers operating on the captured `area` reference stay valid.
2. Read-only suppression: read-only `bodyControl` returns `null`
   (item.js:177-179) → **no bar, by construction, with no new
   condition** — the same guarantee #388's panel inherits.
3. The `_refdesCommit` hook (editor.js:210) is in scope.

New module `src/refdes/serve/static/formatbar.js`, plain ES module,
imported by `editor.js` only (test_serve_static's import graph check
keeps it honest). No CSP change, no new endpoint, no dependency on
#388's files.

### Insertion mechanics (the core rule)

One shared mutator, `applyEdit(area, start, end, text, selStart,
selEnd)`:

1. **Case A (preferred):** `area.focus()` (no-op if focused),
   `setSelectionRange(start, end)`, then
   `document.execCommand("insertText", false, text)`; if it returns
   true, set the resulting selection. Native undo covers the whole
   insertion as **one Ctrl+Z step**, and the native `input` event
   fires — so the draft commits through the normal `input` listener
   (editor.js:209) and #388's panel recomputes on its debounce
   (live-calc.js:356). This is the design's backbone, and the editor
   codebase's existing precedent for "one-step undo" insertions
   (insertIntoBody predates it; the bar adopts the live-calc pattern).
2. **Case B (fallback):** splice `area.value`, `setSelectionRange`,
   then **dispatch a synthetic `Event("input", {bubbles: true})`**.
   This is a deliberate refinement of live-calc's Case B (which calls
   `_refdesCommit` directly and skips `input`, live-calc.js:325-333):
   one dispatch drives the draft commit *and* the panel recompute, so
   Case B degrades gracefully instead of leaving the panel stale until
   the next keystroke.
3. Case-B detection shares **one session truth**: read the same
   sessionStorage key `refdes.live-calc.fallback` (live-calc.js:23)
   before first use; on own first failure set it and show a one-line
   note in the bar ("Undo may need more than one step in this
   browser."). One detection, one flag, honest naming (the key keeps
   its live-calc name; a comment in both files points at each other).

Hard rules:

- **Never mutate while a save is in flight.** Handlers check
  `isSaving()` (the accessor #388 adds to editor.js) and no-op.
  Rationale is mechanical, not stylistic: `saveAll` snapshots
  `pendingOps()` (editor.js:251) then `clearDraft()` on success
  (editor.js:252) — an insertion landing mid-save is silently
  destroyed (verified in §A).
- **Fence safety.** Every block insertion keeps ` ``` ` fences
  balanced by construction (block inserts are pushed to paragraph
  boundaries using `insertIntoBody`'s existing blank-line logic,
  editor.js:109-111, lifted to a shared helper; if the caret sits
  inside a fence, block ops insert **after** the fence's closing
  line, never inside).
- **Focus never leaves the textarea on mouse.** Every button gets a
  `mousedown` `preventDefault()` so the textarea keeps focus and
  selection — the forum behavior, and what makes Case A work on
  click. Keyboard activation (Enter/Space) moves focus to the
  button; handlers re-`focus()` the textarea after mutating.
- **a11y:** real `<button type="button">` elements (the shell has no
  `<form>`, verified §A; explicit type anyway), each with a
  non-empty `aria-label`, tab-reachable (bar precedes the textarea
  in DOM order), native Enter/Space activation. No `title`-only
  affordances.
- **Read-only:** mounts nothing — §B placement, above.

### Button set and exact insertion semantics

Notation: sel = current selection text; caret with empty sel is a
cursor. "Placeholder" means inserted template text left **selected**,
so typing replaces it (the forum convention Jared asked for). All
ops are Case A/B as above. Toggle-off is checked first: if the target
is already formatted, unwrap it and reselect the inner text.

**Core row (markdown formatting):**

| Button | Empty sel | With sel | Toggle-off |
|---|---|---|---|
| **Bold** | insert `**bold text**`, sel `bold text` | `**`+sel+`**`, sel inner | cursor inside a `**…**` pair on one line: expand to pair, strip markers |
| *Italic* | `*italic text*`, sel placeholder | `*`+sel+`*` | same, for `*…*` |
| ~~Strike~~ | `~~text~~`, sel placeholder | `~~`+sel+`~~` | same, for `~~…~~` |
| `code` | `` `code` ``, sel placeholder | wrap in single backticks | same |
| H (heading) | caret line cycles no→`# `→`## `→`### `→`#### `→`##### `→`###### `→no; caret stays at line content start | — (caret line only; multi-line = non-goal §G) | cycling through "no" is the toggle |
| • List | prefix caret line `- ` | prefix **each** sel line `- ` (forum convention) | strip leading `- ` / `* ` / `+ ` on every sel line |
| 1. List | prefix caret line `1. ` | prefix sel lines `1. `, `2. `, … in order | strip `^\s*\d+\.\s` per line |
| ❝ Quote | prefix caret line `> ` | prefix each sel line | strip `> ` per line |
| Link | insert `[link text](url)`, sel `url` (caret lands in the parens) | sel starts `http(s)://` → `[link text](sel)` sel placeholder; else → `[sel](url)` sel `url` | cursor inside `](…)`: unwrap to the link text |
| Table | insert `\| a \| b \|\n\|---\|---\|\n\|   \|   \|`, sel `a` | — | — |
| — (HR) | insert `---` as its own paragraph (blank-line padded) | — | — |

`---` insertion honors docs/markdown.md:24-27: the bar inserts a bare
rule separated by blank lines, and the docs note that a `.md` file
whose body has a bare `---` immediately before YAML-key lines and a
closing `---` later is parsed as an item split. Task-list buttons are
**out** — the project renderer emits literal `[ ]` (probe in §A), so
the button would insert visibly broken markup.

**refdes row (section C) sits in the same bar**, visually separated
(`.fmt-core` / `.fmt-refdes` groups), gated on the feature landing.

### Keyboard shortcuts (collision-audited)

App-side: zero existing keydown handlers (§A), so the only collisions
are browser-native, and they are per-platform:

| Key | Action | Browser collision (to verify in F.2) |
|---|---|---|
| Ctrl/Cmd+B | bold | Chrome: bookmarks-bar toggle — page-preventable, verify |
| Ctrl/Cmd+I | italic | Chrome: DevTools — reserved in some builds; bind, and **drop if the browser test shows it can't win** |
| Ctrl/Cmd+K | link | Chrome/FF: focus search/omnibox — page-preventable (Gmail precedent) |
| Alt+Shift+5 | strike | free (Word convention) |
| Ctrl/Cmd+Alt+C | code fence | free (Gmail code-block convention) |

Never bound: Ctrl+Z/Y/Shift+Z (the bar **depends** on native undo),
Ctrl+Shift+I/J/C and F12 (DevTools, reserved — not preventable),
Ctrl+T/N/W/L/J/Tab, Ctrl+1..9 (tab switching), Ctrl+Alt+letter
(Linux DE: VT switch, GNOME launcher), Ctrl+Alt+digit (desktop
switchers on some DEs). Heading/list/quote/table/HR are
button-only in v1 — fewer bindings, smaller collision surface, and
the button is the discoverable affordance. macOS Cmd variants map
the same. Handler attaches on the textarea (`keydown`), checks
`isSaving()`, `preventDefault()` on match. The shortcut table is a
`const SHORTCUTS` array in formatbar.js so the test harness can walk
it.

### Interaction with the live-calc panel (#388)

- Case A inserts fire `input` → the panel's 400 ms debounce re-runs;
  an insert that opens a calc fence inside a `...calc` block will show
  the panel's server-computed rows on the next debounce. No
  coordination needed beyond not mutating mid-save (rule above).
- The bar never touches result ranges; the panel's
  `selectionSkips` (live-calc.js:259-265) already protects an
  auto-fill racing an active selection.
- Note for the slice-1 review (verified, currently latent):
  `insertIntoBody` splices without firing `input` (editor.js:111-116),
  so today's image/calc-fence insertions do **not** retrigger the
  panel (fence lines are not inline spans, so the panel stays
  semantically correct; the snapshot guard (live-calc.js:236,329)
  discards any stale in-flight response). Slice 1 converts
  `insertIntoBody` to the shared mutator, which makes the whole editor
  input-event-clean in one stroke.

### Drafts

Nothing to design: Case A fires the normal `input` path →
`writeBody` → `setDraftBody` → the sessionStorage mirror
(drafts.js:243-248,187-194). Case B's synthetic `input` event lands
in the same listener. One draft, one save, one revision per click —
the same accounting every keystroke already has.

---

## C. refdes-specific buttons

The bar's refdes row. "Cheap" = skeleton insertion through the §B
mutator, no new endpoint. "Picker" = needs a selection UI (and where
it comes from). Syntax strings verified against docs/markdown.md and
docs/math.md (§A).

| Button | Inserts | Cost / source |
|---|---|---|
| Reference `[[ID]]` | `[[ID]]` at caret; with sel → `[[ID\|sel]]` (markdown.md:69-75) | Picker, cheap: popover list from `GET /api/items`, the same fetch + `PICKER_LIMIT` + filter-box code links.js already has (links.js:44-47); display ids (`row.id \|\| row.handle`) — **display half**, never `@key` composites (docs/design/keys.md; body refs are plain display ids). This is the v1 checklist item 5 helper (browser-editor.md:1155+). |
| Figure `[[fig:]]` | skeleton with caret inside the brackets; with sel, sel becomes the id | Cheap skeleton. A real picker would scan the body for image `{id="..."}` suffixes (client-side regex; cross-item figure refs only resolve in combined documents, markdown.md:274-278) — slice-2 follow-up, not v1. |
| Calc fence | ```` ```calc\n\n``` ```` caret on the empty inner line | Cheap. Skeleton is bare `calc` (legal per math.md:41-45; `id="name"` is optional and its grammar is strict, math.md:53-62 — the author types it). Fences stay balanced by construction. |
| Inline span | skeleton `` `name := expr | unit = result` ``, sel `name` | Cheap skeleton, **grammar decision**: a half-typed triggered span is a build **error** (math.md, §A); a valid example (`x := 1 V * 2 | V = 2 V`, sel `x`) keeps every intermediate state check/build-clean. Recommendation is the valid skeleton; open question Q4 keeps Jared's veto. |
| Value `{{name}}` | `{{}}` caret inside; with sel, sel becomes the name | Cheap. Unresolved names stay as written with a warning (markdown.md:312-313) — safe. A suggest-popover fed by the live-calc rows (which already carry `name`, live-calc.js:142) is the natural slice-3 upgrade. |
| Image | — | **No new picker**: the Images panel already exists below the textarea (images.js); a bar button that opens/focuses it reuses the server-composed lines (api.py:1487,1545-1546) and upload path. Building a second image UI is a non-goal. |
| Source | — | Same: focus the existing Sources panel (sourcepicker.js). Accept-and-save stays its own flow (editor.js:161-166). |
| Navi marker | `<!--navi: text-->`, sel `text` | Cheap, **conditional on the Navis grammar landing** (PR #382 in review; grammar verified §A from navis-design-20261025.md:109,120). Keyless-on-insert is exactly what the author types by hand (§7.2 minting); the one-line + no-`-->` constraint is on the author — the live comment diagnostics (build.py:1797-1803) catch violations. The bar reserves the slot; the button ships in a follow-up slice when #382 merges, not gated-into-slice-2. |
| `[[cite:id]]` | skeleton | Deferred (slice-3): citation ids live in item frontmatter; `/api/items` rows don't carry them (api.py list payload checked — no citations field), so a picker needs a small endpoint addition. A bare skeleton the author fills is a fine v1. |

Cheap skeleton (no picker, no endpoint): figure ref, calc fence,
inline span, `{{}}`, navi, cite. Picker (existing machinery): `[[ID]]`
(links.js fetch pattern). Reuse-existing: image, source.

---

## D. Editor font as its own setting

Deliberately **not** part of the formatting bar: different lifetime
(persistent preference, not per-insert), different owner (personal,
not project), different failure mode.

### What is configurable (v1)

- **Family**: a fixed set of three stacks, rendered as live samples
  in the popover: Mono (default, `monospace`), Sans (`system-ui,
  sans-serif`), Serif (`Georgia, serif`).
- **Size**: 11–20 px stepper (current 12 px), px unit (the shell is
  px-everywhere; style.css:65).
- **Line height**: three steps — compact 1.35 / normal 1.5
  (current) / loose 1.7.

No free-form font-family string in v1: the CSSOM path is CSP-safe
(§A probe), and an arbitrary string can only name locally installed
fonts (no network, per-property sanitizing by the CSS parser), so the
risk is cosmetic — but three stacks + size is the 90% case and keeps
the popover a popover. Open question Q2 if Jared wants his own stack.

### Where the setting lives: localStorage, not project config

Recommendation: **localStorage, per-user browser**, key
`refdes.editor.font`, JSON `{family, size, lineHeight}`, validated on
read (bad payload → defaults), storage failures degrade to
defaults in-memory (the live-calc fallback pattern).

Why not `refdes-project.yaml` (verified cost, §A): the `editor:`
block needs a `_KNOWN_SETTINGS` entry (schema.py:65-73) +
configcheck validation + docs/schema-reference.md + schema tests +
exposure to the editor through the revision payload + serve snapshot
plumbing — a full PR of project-wide surface for a preference that
is per-*person*. The project-config rationale is already written:
yaml settings are shared project facts reviewed in PRs; UI
preferences are per-user; the editor has no per-user identity
(inline-calc design §6.1, lines 866-966). The font is that same
shape. Open question Q1 asks Jared to confirm.

### How it applies (CSP-constrained, §A probe)

- `style.css` `.body-edit` (style.css:~65, today `font: 12px/1.5
  monospace`) becomes `font-family: var(--refdes-editor-font,
  monospace); font-size: var(--refdes-editor-size, 12px);
  line-height: var(--refdes-editor-line-height, 1.5);` — defaults
  reproduce today's values, so **first load is pixel-identical**.
- JS applies the stored values via
  `area.style.setProperty("--refdes-editor-...", ...)` on the textarea
  in `bodyControl` (every render; CSSOM writes are allowed under
  `style-src 'self'` and survive the re-render carry-over, §A).
  **No injected `<style>` element** (CSP-blocked, §A probe) and no
  CSP change.
- The custom properties are set on the **textarea element only**. The
  gear (aria-haspopup="dialog") opens a small popover in the bar:
  three family radio rows with live-styled samples, size stepper,
  line-height radio, Reset to defaults. Every change applies live
  (next paint) and persists immediately — a popover of forum
  preferences, not a settings page.

### What the font setting must NOT touch

- **Published site**: the editor CSS is `/edit/static`
  (server.py:~708 static serving); site templates/themes untouched.
- **Content hashes / body bytes**: the setting never writes into the
  draft (storage key is disjoint from `refdes.draft.v1.*`) — the save
  path is byte-identical.
- **The preview iframe** (the published site's rendering is the
  project's choice, not the author's), field inputs, list pane.
- **Draft schema**, live-calc, CSP (all verified untouched by
  construction: no new endpoint, no new header).

---

## E. Slices (small PRs, in order)

| Slice | PR | Contents | Depends on |
|---|---|---|---|
| 0 | this doc | design only | — |
| 1 | `editor-format-bar` | formatbar.js: shared Case A/B mutator, core row (bold/italic/strike/code/heading/list/numbered/quote/link/table/HR), shortcuts, a11y, read-only inert, isSaving gate; converts `insertIntoBody` to the shared mutator (fixes the latent §B panel gap); node-driven tests | **#388 merged** (shared textarea contract + `isSaving()` accessor; the file itself has no import dependency on live-calc.js) |
| 2 | `editor-refdes-buttons` | refdes row: `[[ID]]` picker (GET /api/items), calc-fence/inline-span/`{{}}` skeletons, image/source panel-focus buttons; tests | slice 1 |
| 3 | `editor-font-setting` | font popover, localStorage store, CSS custom properties, tests | nothing (can land parallel with 1-2) |
| 4 | `docs` | new user-facing `docs/browser-editor.md` (the editor has **no user doc** today — §A), index.md nav entry; update docs/design/browser-editor.md v1 item 5 → done; a formatting/font section in docs/markdown.md pointers | 1-3 landed |
| follow-up | `editor-navi-button` | the Navi marker button | **#382 merged** (grammar) + slice 2 |

Each of 1-3: module + tests + style.css, ~250-400 JS lines, ~150-300
test lines, no server change, no CSP change, no draft-schema change.
Slice 1 is the only one with an external dependency, and it is the
live-calc PR everyone is already waiting on.

---

## F. Test plan

### F.1 Node-driven tests (the `tests/test_editor_link_undo.py` posture)

Verified posture (read in this session): pytest spawns one node
process, a harness stubs the DOM (`FakeNode`), imports the **real
served modules** over file://, and drives them; `NODE_TIMEOUT_S =
120`. `tests/test_editor_format_bar.py` (slice 1) walks the real
formatbar.js with a `FakeTextarea` whose `execCommand` stub returns
true (Case A) / false (Case B), asserting:

- wrap / placeholder-selection / toggle-unwrap for every op; heading
  cycle order including H6→none; multi-line list/quote prefixing and
  prefix-strip on `- `/`* `; link URL-vs-text split.
- Case A: `execCommand` called exactly once per insertion (one undo
  step), caret/selection restored; Case B: splice, selection, and
  **exactly one synthetic `input` dispatch** (draft + panel both
  see it), session fallback key set and honored on next call.
- `isSaving()` → handler no-ops (value, selection, draft all
  unchanged); fence-balance invariant after every block op (count of
  ` ``` `-opening lines) and block-insert-after-fence when caret is
  inside one.
- read-only: `createEditor` early-return path (editor.js:45-53) → no
  bar in the tree.
- font store (slice 3, same harness + `FakeStorage`): JSON
  validation on read, defaults on corrupt payload,
  `setProperty`/custom-property application on the textarea,
  storage-throw degradation.
- `test_serve_static.py` keeps pinning the new module for free
  (imports resolve, no inline handlers, ES2020 parse) — add the bar
  to its "wired into the editor" checks (test_serve_static.py:118-128
  pattern).

### F.2 Real-browser checklist (the recipe is real, not a wish)

Environment verified this session: `/usr/bin/chromium` 153.0.8010.52
ran headless with `--dump-dom` successfully; node v22.23.3; an
existing recipe at `/home/jorb/work/refdes/.scratch/browser-smoke`.
Pattern: `npm i puppeteer-core` in a scratch dir (no browser download
— system chromium), `refdes serve` on a loopback port, drive the real
`/edit/` page from a local http origin (the token is on the page),
`NODE_TIMEOUT`-style guard.

Checklist (every §B/§D claim that code can't prove in jsdom-less
node):

- [ ] Ctrl+Z one step per insert (type text → click Bold → single
      Ctrl+Z restores pre-click text exactly).
- [ ] Ctrl+B/I/K: the formatting fires and **no** bookmarks bar /
      DevTools / omnibox steals it (drop any binding the browser
      wins in this column).
- [ ] focus stays on the textarea after a mouse click on a button
      (`document.activeElement`); Enter/Space activation returns
      focus to it.
- [ ] Case A proven in Chromium: `execCommand('insertText')` returns
      true on a focused textarea (live-calc runs on the same
      assumption; verify, don't assume).
- [ ] with the #388 panel running: insert a calc fence → panel shows
      the fence's rows on the next debounce; insert mid-save →
      nothing lands (and the bar visibly no-ops).
- [ ] font popover: family/size/line-height changes →
      `getComputedStyle(textarea)` updates, persists across reload
      + item switch; corrupt `refdes.editor.font` payload → editor
      works, defaults applied; preview iframe and a `refdes build`
      output are byte-identical with the font changed (the setting
      never leaves localStorage).
- [ ] CSP unmodified: no console CSP reports on a plain editing
      session (console listener via CDP).

---

## G. Non-goals

- WYSIWYG / rich-text / `contenteditable` (the textarea + insertion
  posture is the design, docs/design/browser-editor.md).
- Task-list checkboxes (renderer emits literal `[ ]` — §A probe; a
  button that inserts visibly broken markup is worse than no
  button).
- Multi-line heading operations, footnotes, definition lists, raw
  HTML, callouts (not in the renderer's supported set,
  docs/markdown.md).
- Fonts on the preview iframe / published site / preview pane;
  project-level font config (Q1 records the veto); free-form font
  stacks in v1 (Q2).
- A body field on the create form (there is none today, §A) —
  teaching the create form a body is its own design.
- A second image/source picker (reuse the existing panels).
- Shortcut coverage for lists/quote/table/HR (button-only, §B).
- Real-time collaborative editing.

---

## H. Open questions for Jared (recommendations first)

1. **Font scope.** Recommendation: localStorage per-user only (Q-cost
   in §D). Add an `editor:` block to `refdes-project.yaml` as a later
   project-wide default that localStorage overrides? (My read: not
   worth a schema PR for a personal preference, but the veto is
   yours.)
2. **Font families.** Three fixed stacks (mono/sans/serif) in v1,
   per §D — or do you want a free-form stack field?
3. **Ctrl+I italic.** Chrome may reserve it for DevTools on some
   builds. Recommendation: bind it, drop it if the F.2 checklist
   shows the browser wins.
4. **Inline-span skeleton.** Recommendation: insert a *valid* span
   (`x := 1 V * 2 | V = 2 V`) so the build never goes red on a fresh
   skeleton — vs a placeholder skeleton that reads as a TODO but
   fails `check`/`build` until fixed. Your call which failure mode
   is better for authors.
5. **`[[ID]]` picker scope.** Recommendation: all items + a filter
   box (the links.js convention, links.js:44-47). Pre-filtering to
   the item's board/workspace in v1?

---

## Progress log

2026-10-29: read the brief; verified the baseline against `main`
(f94a503) + pr388 (a18bd7d): editor.js/item.js/images.js/sourcepicker
.js/links.js/drafts.js/controls.js/update.js/create.js/style.css,
schema.py, api.py routes, security.py CSP (plus a headless-Chromium
probe that settled CSSOM-vs-`<style>` under `style-src 'self'`),
docs/markdown.md, docs/math.md, docs/design/browser-editor.md
(item 5 = this feature), inline-calc design §3.5-§3.8/§6.1,
navis-design §4/§7.2, the node-driven test posture, renderer
presets probed via markdown-it-py (gfm-like: tables/strike render,
task checkboxes do NOT), env (chromium/node/firefox cache), CSP +
`test_serve_static` constraints. No source/test changes (docs-only,
per brief). Work finished; the deliverable is this file; PR opened
with it.
