Status: **proposed** (drafted 2026-09-27); **Slice P-A landed 2026-09-27** (§12).
The service reads PDF pages — `sources.page_candidates()` (pypdf visitor
extraction, row grouping, the CSV reader's own numeric grammar, named caps), the
import-gated `pdf` reader, and one read endpoint — and the page view, the confirm
step and accept are still design only, as is everything they decide. This
document is still a design spec, not a decision, and it is the PDF-flavored
sibling of `docs/design/editor-source-picker.md` and settles the editor half of
the requirement recorded in `docs/design/calc-sources.md` §1 ("New, raised by
Jared on 2026-09-21: a picker for values in a PDF datasheet"), which is the
primary source for what was already agreed about this feature's shape: show the
value in context on the page, list every candidate in a table row, pre-select
nothing, record what the author confirmed, fail visibly on unreadable pages.
Every open question in §10 carries a recommendation. It is cross-referenced
from `docs/design/calc-sources.md` §1 and from
`editor-source-picker.md` §8 ("PDF datasheet values"), and it inherits that
document's confirm-before-accept contract (§3), its one-operation accept (§4),
its one-reader-in-Python rule (§5), and its path-confinement invariants (§6)
unchanged — this document does not re-litigate any of them, it applies them to
a PDF.

**What landing P-A settled, and where to look for it.** The document left four
things to the code, and the code fixed them; the design intent is unchanged and
these are the readings it was ambiguous about:

- **The endpoint** is one route, `GET /api/item/<ref>/sources/page?path=&page=`
  (§2.2's "A new endpoint"): the page as positioned text, its runs grouped into
  rows, and every number in them as a candidate. `page` is optional; without it
  the page is the one the citation names (§2.2), read out of the lockfile and
  used only while it belongs to the bytes now pinned, exactly as the rendered
  link uses it. §12's plural "the page/candidate read endpoints" is that route
  plus `GET /api/item/<ref>/sources`, which now lists a cited PDF with
  `browse: "pages"` and the page to open at (§2.1's "page-mode marker").
- **The caps** (§4, §10 Q7) are named in `sources.py` beside `MAX_LIST_ROWS`:
  `MAX_PDF_BYTES` 32 MiB, `MAX_PAGE_CANDIDATES` 200, and `MAX_PAGE_SPANS` 1000.
  The span cap *reports* a too-dense page and shows none of it; the candidate cap
  stops the page and names what it did not read, which is the CSV row cap's
  posture. The row tolerance is half a font size, derived from the size rather
  than being a constant.
- **The quote** a value is recorded by (§6) is the row's tokens joined by one
  space, verbatim, and the row's identity for re-location is its non-numeric
  tokens (`PageRow.labels`), matched exactly and case-sensitively. §6's
  illustrative quote shows comma separators, which is the panel's rendering of a
  row rather than a spelling; P-C should record the space-joined form, since
  re-location matches the token sequence and the join has to be fixed before
  anything is written to a lockfile.
- **A PDF is not a keyed source file.** `PdfReader` deliberately does not
  implement `extract()`: a `source()` line naming a PDF says so out loud rather
  than pinning a number nobody confirmed (that is §6's quoted-row re-location,
  Slice P-C), and `/sources/entries?path=…pdf` answers that a PDF has no key
  column instead of returning an empty table. A cited `.pdf` therefore reaches
  `GET /api/item/<ref>/sources` as a browsable file and a remote one only when
  the fetch kept the bytes (§10 Q4 option A, the kept copy read and checked
  against its pinned sha256).
- **The extra's floor moved to pypdf 6.19**, for the reason in §2's dependency
  paragraph, and the reader refuses a page whose runs all sit on the page origin
  — the old symptom — with the installed version quoted and the fix named,
  rather than drawing a page in the corner.


# Editor PDF datasheet picker

## 1. Problem

`source()` has shipped, and so has the read-only CSV picker service behind it
(`editor-source-picker.md` §11, Slice A landed 2026-09-25). What neither
covers is the case Jared raised on 2026-09-21: most of the numbers an author
actually wants do not live in a committed CSV. They live in a datasheet —
a PDF — and getting one into a calc block today means:

- open the PDF in a viewer outside the editor;
- find the page, by memory or by scrolling a 40-page document;
- read the number off a table with min/typ/max columns, several plausible
  numbers per row;
- type it into the item, where it becomes an untraceable literal; or type a
  `source("…", "…")` pair that has no CSV to name it.

The failure mode is the one `calc-sources.md` §1 already names: **a silent
plausible-but-wrong number** — mA read as A (the 1000x trap), or the min
column where the typ column was meant. Hand-copying from a datasheet table is
exactly the human act that produces those, and nothing downstream notices:
the literal is well-formed, the calc evaluates, the number looks fine.

The CSV picker's problem framing (`editor-source-picker.md` §1) was about two
invisible strings the author had to type byte-exact. The PDF case has the
same friction plus a harder one: the value itself has to be *found and read*
by a human inside a rendered document. Jared's requirement, recorded verbatim
in `calc-sources.md` §1 and `browser-editor.md` ("PDF datasheet values"): the
picker **tries** to extract the number, then **asks the author to verify it
is correct before accepting** — the value shown *in context* (the highlighted
cell/line on the rendered page, not the bare number), every candidate in a
table row listed, nothing pre-selected, the confirmed quote and value
recorded so a reviewer can re-verify, and a visible "could not read this
page" when extraction fails or is ambiguous — never a guess.

The CSV picker exists partly so this slice does not have to invent a
confirmation posture: §3's panel already refuses to accept on the author's
behalf, and the PDF picker arrives as one more source type behind it
(`calc-sources.md` §1, Sequencing), not as a new interaction to relearn.

## 2. Proposal

One more reader in the registry, three more read endpoints, and one widened
pick — reusing, not replacing, everything the CSV picker built.

1. **The same file list gains PDFs.** `GET /api/item/<ref>/sources`
   (`serve/sources.py` `files_payload`) dispatches through
   `sources.reader_for()`; registering a `pdf` reader makes a cited `.pdf`
   appear with `reader: "pdf"` and a page-mode marker instead of the CSV
   "no source reader for this file type" refusal. Only PDFs whose bytes are
   actually on disk are browsable — a local `path:` citation (the file is the
   artifact, `docs/markdown.md` "Citing a datasheet") or a remote citation
   with `keep_copy: true` (the kept copy under `.refdes/copies/`,
   `citations.kept_copy_path()`). A hash-only remote datasheet — the common
   posture, since datasheets are copyrighted — has no bytes to read and is
   reported as such, visibly, not silently (§6, §10 Q4).
2. **Picking a PDF opens a page, not a row list.** The picker opens at the
   page the item's citation already names — `page:` directly, or the page the
   lockfile resolved for a `section:` (the `sections` map `resolve_sections()`
   writes, `citations.py`; `docs/markdown.md` "Citing a section by name") —
   with prev/next navigation. A new endpoint returns the page as
   **positioned text**: every extracted text run with its coordinates, plus
   the numeric candidates grouped into rows (§4). The browser receives parsed
   data; it never parses a PDF (§7).
3. **Picking a candidate opens the same confirm step**, with the PDF-specific
   context added: the highlighted line on the page view, the row's other
   tokens, the guessed column header labelled as a guess, the quoted row text
   that will be recorded, the pinned value beside the live one, the composed
   calc line, and the unit field with no default. Nothing is pre-selected;
   Accept is disabled until the unit is filled — the panel contract of
   `editor-source-picker.md` §3, unchanged.
4. **Accept is the same operation.** Not a second accept: the widened
   `POST /api/item/<ref>/edit` of `editor-source-picker.md` §4 (Slice B),
   extended to a PDF pick. The request carries `{path, page, row, token
   index, key, unit, name}` — never a value — and the server re-extracts the
   number from the PDF bytes itself, inside the operation, exactly as the CSV
   accept pins "the value the reader read, not the value the browser sent."

```
Insert source value → [file] ─┬─ csv → [key]    → [confirm: row, context, unit] → Accept
                              └─ pdf → [page] → [candidate] → [confirm: line, quote, unit] ─┘
                                                              body draft + lockfile ──────────┘  (one op)
```

**The dependency, stated plainly.** `browser-editor.md` calls this "the
heaviest dependency the editor has", and that sentence is worth keeping in
view. This design's answer is that the *Python* dependency is already paid:
`pypdf` is an optional extra (`pyproject.toml`, `pdf = ["pypdf>=6.19"]`),
imported lazily at exactly one place (`citations._import_pypdf()`), already
used to read a PDF's outline at fetch time. The picker adds **no new mandatory
dependency and no new optional one**: it reuses `refdes[pdf]`, and without it
the picker offers no PDFs and shows the existing install hint. The one thing
landing it did move is that extra's **floor**, from 4.0 to 6.19: before 6.19
pypdf's `visitor_text` handed every run it inserted a space in front of a
*zeroed* text matrix, so most of a datasheet table's cells came back on the
page's bottom-left corner and no row could be placed — a page drawn in the
corner is a wrong answer wearing a working shape. A version floor on an extra
that is already optional is not a new dependency, and `section:` resolution
works on any of them. What would be heavy — vendoring pdf.js for faithful page
rendering, or a server-side rasterizer — is deliberately deferred (§5, §10
Q1), and the v1 page view costs nothing to install.

## 3. The confirm step, PDF flavor

The CSV confirm step verifies *meaning*, not *reading* — a CSV row either
matches the key exactly or is not offered (`editor-source-picker.md` §3). The
PDF step is where the harder half of Jared's rule actually bites: extraction
*can* be ambiguous, and the panel is where the author resolves it. The panel
shows, in the same order as the CSV panel shows its facts:

| Shown | Source | Why it is on the panel |
|---|---|---|
| The candidate token, verbatim | extractor | the identity being committed |
| The page, highlighted, in the page view | extractor + renderer | "in context, not the bare number" — the agreed rule |
| The whole row's text, verbatim, with the token marked | extractor | this is where "VOUT, 12 V in, half load" tells them they picked the right row |
| Every other numeric token in that row, each selectable | extractor | the min/typ/max rule: several candidates means a list, never a pick |
| Column header guess per candidate, labelled *guess* | extractor (§4) | which column am I looking at is the question the 1000x trap hides behind |
| The quoted row text that will be recorded | server | what a reviewer will re-verify against (§6) |
| Pinned value for this key, and `changed` when the file disagrees | lockfile + extractor | the drift the build warns about, visible before the commit |
| The composed calc line, monospace, uneditable here | server | the browser never learns the grammar (`editor-source-picker.md` §7) |
| Unit field, empty, no placeholder default | author | a datasheet row says "mA" in prose; the declaration still owns the unit (`calc-sources.md` §6) |
| Variable name and source key, proposed, editable | server proposal + author | §7 |

Nothing is pre-selected — including when there is exactly one numeric token on
the page. The single-candidate case still shows the confirm step; the author
still clicks Accept. That is the agreed rule ("Nothing is pre-selected:
accepting is a deliberate step, never automatic"), and the one-candidate case
is precisely where an automatic accept would train the author to stop reading
the panel.

**Visible failure is a panel state, not an error page.** A page with no
extractable text (a scanned datasheet, a figure-only page) answers with
"could not read this page — no extractable text (this looks like a
scanned/image-only PDF; OCR is out of scope)" and offers nothing. A page
whose extraction yields zero numeric candidates says so. Neither is ever a
guessed number, and neither is a traceback — the same posture as the outline
resolver's failure table in `docs/markdown.md`.

## 4. Finding a candidate value on a page

Text extraction with coordinates, via the pypdf dependency that already
exists, server-side. The browser never sees the PDF; it sees JSON.

**Extraction.** `pypdf`'s `page.extract_text(visitor_text=callback)` yields
each text run with its text and text-matrix position (and font size),
independent of layout mode — this is the "PDF text-and-coordinates library"
capability `calc-sources.md` §1 said the feature needs, and it is inside the
extra the project already declares. A new `PdfReader`-backed module function
(for prose: `sources.page_candidates(path, page)`) turns the runs into:

- **Rows.** Runs grouped by vertical overlap, tolerance derived from font
  size — a datasheet table row is a y-band, and this is how it is detected.
  No table-line/vector-graphics parsing: datasheet tables are usually just
  aligned text, and the row grouping is what makes "the row's other columns"
  (§3) possible.
- **Tokens.** Runs split on whitespace and ordered by x within the row.
- **Numeric candidates.** A token is a candidate iff it satisfies the
  **existing ASCII decimal grammar** — `sources.parse_decimal()`
  (`sources.py:137`), the same function the CSV reader uses, so the picker
  cannot offer a number `fetch` would refuse. `100 mW` is not one token in an
  extracted PDF anyway; when the extraction yields `100` followed by `mA`,
  the `mA` is row context shown on the panel, and the unit remains the
  author's declaration (`calc-sources.md` §6 — the reader supplies no unit).
- **Column header guess.** For a candidate, the token in the row above whose
  x-range overlaps the candidate's, if any. Labelled *guess* everywhere it
  appears — it is presentation for recognition (which column is TYP?), not a
  fact the lockfile records. If it is wrong, the author is looking at the
  highlighted row anyway.

**The min/typ/max rule is mechanical.** All candidates in the row the author
is viewing are listed, each with its header guess, and none is chosen. The
agreed rule becomes a property of the data structure rather than a policy the
UI has to remember.

**Bounds.** PDFs are bigger than CSVs, so the caps are named where the file
is read (the `MAX_LIST_ROWS`/`MAX_LIST_BYTES` posture, `sources.py:172-173`):
a byte cap on the PDF itself (proposed 32 MiB — a 40-page datasheet is a few
MB; the number is §10 Q7's), a per-page candidate cap (proposed 200, named
when hit), and a cap on the positioned-text spans returned (a page with more
text than the cap is reported as too dense to browse rather than truncated
into a lie).

**Coordinates belong to the bytes they were read out of.** This is the
`sections_sha256` rule from `docs/markdown.md` ("A page belongs to the bytes
it was read out of") applied to a new kind of derived fact: every page, row,
and coordinate the picker reports was extracted from the bytes currently
pinned, and a pick is only valid against those bytes. Accept operates under
fetch's existing non-`--update` policy, identical to the CSV accept
(`editor-source-picker.md` §4): hash matches the pin → extract; no record at
all → pin and extract in one write; file changed since the pin → refuse with
the existing "run `refdes fetch --update --path …`" direction, verbatim.

## 5. What the browser shows: positioned text, not a rendered page

The agreed rule says "the highlighted cell/line on the rendered page". The
honest question is what "rendered" has to cost, and `calc-sources.md` §1
already priced the two obvious answers: vendoring pdf.js ("large") or
server-side image rendering. Three options, stated with their real costs:

| Option | What the author sees | Cost |
|---|---|---|
| **A. Positioned text (recommended for v1).** The server sends the page's extracted text runs with coordinates; the browser draws them as absolutely-positioned spans in a fixed-aspect box, and the candidate's row is highlighted. | A text reconstruction of the page — correct layout and relative position, no fonts, no graphics, no images. The row and its neighbors are legible; the page is recognizably *that page*. | Zero new dependencies (pypdf is already there); no PDF bytes leave the process at all (§6); pure JSON, fully testable against the existing HTTP-test posture. |
| B. Vendor pdf.js. Faithful page render, text layer, highlight overlay. | The actual page. | The heaviest dependency the editor has, exactly as `browser-editor.md` says — hundreds of KB of vendored JS plus its worker. It fits "no Node build step" (plain ES modules packaged in the wheel, `browser-editor.md`) but not "the editor stays light". It also means serving raw PDF bytes to the browser (§6), a genuinely new response surface. |
| C. Server-side rasterization (poppler/`pdftoppm`, `pdf2image`). Page images. | The actual page, as bitmaps. | A **system binary outside pip** — breaks the wheel-only install story harder than any Python dependency would, and adds a deployment dependency the project has no precedent for. Rejected outright, recorded here so it is not re-proposed. |

**Recommendation: A for v1, with B as an explicit later upgrade, and C never
(§10 Q1).** The rule's substance is *context, not the bare number* — the
author must see the row inside its neighborhood and confirm the highlight is
on the right line. A positioned-text reconstruction satisfies that at zero
install cost. Where it fails honestly: a datasheet figure with a number drawn
into it, or a scanned page — and both fail visibly ("no extractable text" /
"no candidates on this page"), which is the agreed posture. If A turns out to
be too crude in real use, B is a contained upgrade: same endpoints, same
payloads, the page view swaps implementations, and the PDF-bytes-serving
surface (§6) gets designed when there is demonstrated need rather than
speculatively.

## 6. Accept: reuse Slice B, record the quote, re-locate by text

**There is no second accept.** Checked at drafting time:
`serve/sources.py` has `propose_payload` (Slice A) and no accept; the git log
has Slice A (#49) and nothing wider. The write mechanism is
`editor-source-picker.md` §4's widened `POST /api/item/<ref>/edit` — body op
plus lockfile pin as one operation inside the existing write lock, with the
gate, the rollback, and the "browser never sends a value" rule. The PDF
picker's accept is that operation with a different reader behind it, and it
lands **after** Slice B (§12), because inventing a parallel write path for PDF
would break the editor's "no handler writes a file on the side" invariant
that §4 exists to preserve.

**What a PDF source key is, and how it survives a re-pin.** `source()` needs
a durable key, and a PDF has no named keys — which is why `calc-sources.md`
§3 rejected positional selection for CSV. The proposal is the same trick the
`section:` feature already uses for page numbers: **a human-meaningful name,
re-resolved against the document at fetch time, failing loudly when it no
longer resolves.** The author names the key (the server proposes one, §7);
the lockfile records, under the existing `values:` shape
(`calc-sources.md` §5), the provenance the agreed rules demand:

```yaml
citations:
  datasheets/tps62913.pdf:
    sha256: 9f3a…
    values:
      tps62913_half_load_eff:
        reader: pdf
        value: "0.93"
        page: 14
        quoted: "VOUT Efficiency, VOUT=3.3 V, 12 V in, half load, — , 0.93 , —"
        token: 2   # the 2nd numeric token of the quoted row
```

Re-extraction on `fetch --update` (and inside accept, against the
already-matching pin) does not trust coordinates: it finds the row whose
**non-numeric tokens match the quoted row's non-numeric tokens exactly**
(normalized whitespace, case-sensitive — the outline matcher's exactness
posture, `citations._norm`/`match_outline_title`), then takes the numeric
token at the recorded index. Zero matching rows → a `gone`-class error in the
`KIND_GONE` idiom: *"the text you confirmed no longer exists in this revision
(was page 14)"*. Two matching rows → an ambiguity error naming both pages,
never a pick. The value itself changing (0.93 → 0.95 in a new datasheet rev)
is exactly what this tolerates — the row's identity is its labels, not its
numbers — and the change surfaces as the existing loud drift diff,
`0.93 -> 0.95`-style, with `fetch --update` as the acceptance gate
(`calc-sources.md` Q2, decided 2026-09-21).

`quoted` is the full row text as confirmed, so a reviewer can re-verify by
eye, and `page` is recorded for display — but neither is trusted as the
lookup key, because a datasheet revision moves content between pages, and a
page number from another revision is a wrong link, not a near miss
(`docs/markdown.md`). Coordinates from the picker session are presentation
and die with the session; only the quoted row and the token index are
recorded.

**The composed line** is `name = source("datasheets/tps62913.pdf", "key") |
unit`, composed server-side and round-tripped through `parse_source_call`
exactly as `propose_payload` does today — the grammar is unchanged, which is
what "one more source type behind the same picker" means concretely. The
unit field starts empty and Accept stays disabled until it is filled; the
datasheet saying "mA" beside the number is context, never a default.

## 7. Reuse, not reinvention

Everything this sits on, with the thing it replaces:

| Existing capability | Where | What the picker reuses it for |
|---|---|---|
| Lazy pypdf import + install hint | `citations._import_pypdf()`, `citations.py:247-257`; `PDF_EXTRA_ERROR` | the editor's PDF availability check — one import site stays one import site; a server without `refdes[pdf]` shows the existing hint and offers no PDFs |
| Outline reading and title matching | `outline_titles()`, `match_outline_title()`, `resolve_sections()`, `SectionError` kinds (`citations.py`) | opening the picker at the cited page: a `section:` citation's resolved page comes from the lockfile `sections` map the fetch already wrote; the picker never re-resolves, it reads what `resolve_sections` recorded — and the failure kinds (`no_outline`, `gone`, …) are the vocabulary the panel already has words for |
| "A page belongs to the bytes it was read out of" (`sections_sha256`) | `docs/markdown.md`; lockfile | §4's rule that coordinates and quotes are valid only against the pinned sha256 — a precedent, not a new policy |
| The ASCII decimal grammar | `sources.parse_decimal()` (`sources.py:137`) | candidate recognition — the picker cannot offer a number `fetch` would refuse, same as the CSV picker cannot offer a row it would refuse |
| The reader registry and protocol | `sources.reader_for()`, `SourceReader`, optional `list_entries` (`sources.py:112, 458-484`) | the pdf reader registers on `.pdf` and is dispatched the same way; a capability it does not implement is an error, never a silent empty list |
| Path authorization | `citations.authorize_source_path()`; `serve/sources.py` `_authorise`/`_reader`/`SourceRefusal` | every PDF request passes the same call fetch and evaluation make — one rule, now four callers |
| The `label=` discipline | `serve/sources.py` `_listing` docstring | every string the PDF extractor produces is built from the project-relative label, so no absolute path can leak from a pypdf message either |
| Live-file diagnostic precedent | `_source_drift()` (`citations.py:687-699`) | browsing the live PDF for a deciding human is the same diagnostic-only category; the pinned value remains the only value a build evaluates |
| Slice B's accept (§4) | `editor-source-picker.md` | the entire write path: gate, lockfile transaction, rollback, `--no-write` 403, sealed-item refusal |
| The confirm panel contract | `editor-source-picker.md` §3 | unit with no default, nothing pre-selected, server-composed line, insertion through `setDraftBody` |

What is genuinely new is small: pypdf text-with-coordinates extraction and row
grouping, the quoted-row re-location rule (§6), and the page view (§5).

## 8. Path confinement and security

The invariants of `editor-source-picker.md` §6 apply unchanged, plus one that
is PDF-specific. None of it trusts the client.

- **Only a file this item cites.** Every request names an item, and the path
  goes through `citations.authorize_source_path()` — the same call, the same
  message, now shared by fetch, evaluation, the CSV picker, and this picker.
  Canonicalization is inherited from `citations.classify()`: absolute paths,
  backslashes, URL schemes, `..` escapes, and symlinks out of the root are
  already refused there.
- **Only a file with a registered reader, and only bytes that exist locally.**
  Dispatch is `reader_for()`; the pdf reader registers on `.pdf` only when
  pypdf imports (the lazy-import posture preserved). A hash-only remote
  citation has no bytes in the process's reach and is refused with a named
  reason — the picker does not fetch anything over the network to browse it
  (the editor does no network I/O; fetching stays a CLI act).
- **No absolute server path leaves the process, in any string.** The `label=`
  discipline extends to the new extractor: pypdf's own exception messages are
  wrapped and re-raised with the project-relative label, exactly as
  `outline_titles()` already wraps pypdf errors with `KIND_UNREADABLE`.
- **Bounded.** Byte cap, per-page candidate cap, and span cap, enforced where
  the file is read (§4), named when hit.
- **No generic file-read endpoint.** Under option A, **no PDF bytes leave the
  process at all** — responses are JSON of extracted text, coordinates, and
  numbers, project-relative paths only (the `shown()` posture). This is a
  real argument for A beyond weight (§5, §10 Q1): option B would add the
  editor's first endpoint that streams the bytes of a project file, and that
  endpoint needs its own design when there is demonstrated need.
- **Inherited posture, unchanged:** launch token required on reads, Host and
  Origin checks, `--no-write` refuses Accept with the existing message while
  browsing stays allowed, sealed and imported items can be read but not
  accepted into (`editor-source-picker.md` §9 Q6, decided A).

## 9. Non-goals

- **OCR of scanned or image-only PDFs.** Out of v1 and out of the near
  future: it is a new heavyweight dependency class (tesseract or a model),
  its failure mode is a confidently wrong digit — the exact class this
  feature exists to prevent — and the agreed rule already defines the
  correct behavior instead: fail visibly, "could not read this page".
- **The accept/write mechanism itself.** The PDF picker does not design a
  second accept. It reuses `editor-source-picker.md` §4's one-operation
  accept (Slice B, designed, **not yet landed** as of this drafting —
  `serve/sources.py` has `propose_payload` and no accept). If Slice B has
  landed by the time this is built, reuse it as-is; if it has not, this slice
  waits, it does not fork.
- **Full-fidelity page rendering (pdf.js) and server-side rasterization.**
  §5: deferred upgrade and rejected outright, respectively.
- **Reading numbers out of figures, charts, or vector drawings.** Text
  extraction only. A number drawn into a schematic figure is not extractable
  and is not guessed.
- **`fetch --update` from the browser; editing, creating, or writing back to
  a PDF; uploading PDFs.** Re-accepting a changed datasheet stays a terminal
  act with a printed diff (`editor-source-picker.md` §8); a source file is
  read-only to the editor in every direction.
- **Writing `page:`/`section:` into a citation from the picker.** Citations
  are a collection field and the patcher writes scalar spans only
  (`NON_SCALAR_FIELD_TYPES`, `serve/edit.py:546`); Jared decided the same
  question against for the CSV picker (2026-09-26,
  `editor-source-picker.md` §9 Q2). The picker *reads* the citation's page
  and section to navigate; it never writes them. The citations row editor,
  when it lands, is the enabler for both pickers equally.
- **Unit inference from adjacent text.** An `mA` token next to the candidate
  is context on the panel, never a pre-filled unit (`calc-sources.md` §6).
- **xlsx, EDA readers, cross-item source reuse, formula evaluation in the
  browser.** Decided elsewhere; nothing here reopens them.

## 10. Open questions for Jared

Recommendations are mine; the questions are yours.

1. **Page view: positioned text, or pay for pdf.js?**
   - **A. Positioned text for v1 (recommended).** §5. Zero new dependencies,
     no PDF bytes leave the process, and it satisfies "context, not the bare
     number". Its coarseness is honest and its failures are visible.
   - B. Vendor pdf.js now: the real page, at the cost of the heaviest
     dependency the editor has plus a new byte-serving endpoint.
   - *Why it matters:* this is the sentence in `browser-editor.md` about cost
     becoming a decision. A is reversible toward B; B is hard to walk back
     once authors depend on faithful rendering.
2. **Is the quoted-row anchor the right durable identity for a PDF source
   value?**
   - **A. Author-named key + quoted row + numeric-token index, re-located by
     exact text match at fetch (recommended).** §6. It is the `section:`
     pattern applied to a row: human-meaningful, exact, fails loudly
     (`gone`/`ambiguous`), tolerates the value changing (which is the drift
     we want to see) and the page moving (which is what revisions do).
   - B. Positional key (page + coordinates). Rejected on its face —
     `calc-sources.md` §3 rejected positions for CSV for the same reason.
   - C. No `source()` for PDFs in v1: accept writes a plain literal plus a
     provenance-bearing citation entry. Rejected against the agreed rules —
     "the calc-sources lockfile pins the number, so a changed PDF raises the
     loud drift warning" requires a lockfile value, and a literal has no
     drift story at all.
3. **Who names the source key?**
   - **A. Server proposes from the row's leading text tokens (slugified),
     author edits, same as the CSV variable-name flow (recommended).**
   - B. Author types it from scratch. One more typed string, in the one
     feature whose premise is not typing things.
4. **Hash-only remote datasheets — the common case for a TI URL citation —
   have no bytes to browse. Correct response?**
   - **A. Refuse visibly with the reason and the fix (recommended):** "no
     local copy of this PDF's bytes; cite a local `path:` PDF or set
     `keep_copy: true` and re-fetch." The editor performs no network I/O.
   - B. Fetch the remote bytes on demand for browsing. Rejected: it makes
     the editor a network client, browses bytes that are not the pinned
     bytes, and quietly re-opens the question of what a pin means.
5. **Should the column-header guess (which column is TYP?) be shown at all?**
   - **A. Show it, labelled *guess*, never recorded (recommended).** It
     addresses the min/typ/max confusion the agreed rules name, and the
     author is looking at the highlighted row to confirm it anyway.
   - B. Omit it: an unrecorded guess on a confirm panel risks anchoring.
6. **Sequencing against the CSV picker's own slices.**
   - **A. (recommended)** P-A (§12) may land any time after CSV Slice A —
     it is read-only and shares its confinement tests' shape. PDF accept
     (P-C) blocks on CSV Slice B unconditionally. The panel work (P-B)
     should land with or after CSV Slice C so there is one confirm panel,
     not two diverging ones.
   - B. Strictly serialize everything after Slice C. Simpler ordering, and
     it delays the read-only half that carries none of the risk.
7. **The caps.** Proposed: 32 MiB per PDF, 200 candidates per page, and a
   span cap that reports a too-dense page rather than truncating it.
   - **A. These, as named constants in `sources.py` beside `MAX_LIST_ROWS`
     (recommended).** Numbers are guesses; the rule (bounded, named when
     hit) is not.

## 11. Named tests

Acceptance criteria, in the style of `calc-sources.md` §10 and
`editor-source-picker.md` §10. Server tests go through the real HTTP surface
with a real fixture project and fixture PDFs (a text PDF with a min/typ/max
table, a no-outline PDF, a no-text PDF, a two-rows-identical PDF); static
tests assert the wiring.

Extraction (`sources` / pdf reader):

- `test_page_candidates_returns_numeric_tokens_with_coordinates_and_rows`
- `test_page_candidates_uses_the_same_numeric_grammar_as_parse_decimal` —
  the `100 mW` / `1,000` / non-ASCII-digit set yields no candidates or row
  context, never a selectable token.
- `test_a_page_with_no_extractable_text_reports_could_not_read_not_zero_guesses`
- `test_a_table_row_with_min_typ_max_lists_every_candidate_and_selects_none`
- `test_the_column_header_guess_is_labelled_a_guess_and_is_not_recorded`
- `test_candidate_extraction_caps_an_oversized_pdf_and_names_the_limit`

Endpoints:

- `test_the_picker_lists_a_cited_local_pdf_and_a_keep_copy_remote_one`
- `test_the_picker_refuses_a_hash_only_remote_citation_with_the_keep_copy_hint`
- `test_the_picker_refuses_a_pdf_the_item_does_not_cite` — including one
  cited by a different item.
- `test_the_picker_refuses_an_absolute_path_and_a_path_that_escapes_the_root`
- `test_without_the_pdf_extra_the_picker_offers_no_pdfs_and_shows_the_install_hint`
  — monkeypatched import failure, the `PDF_EXTRA_ERROR` wording verbatim.
- `test_the_page_view_opens_at_the_cited_page_and_at_the_resolved_section_page`
- `test_no_pdf_bytes_and_no_absolute_server_path_appear_in_any_response` —
  every response is JSON; a pypdf failure message carries only the
  project-relative label.
- `test_the_picker_requires_the_launch_token_on_pdf_reads`

Re-location and accept (all riding the Slice B operation):

- `test_accept_pins_the_value_the_extractor_read_not_the_value_the_browser_sent`
- `test_accept_records_page_quoted_row_and_token_index_under_the_existing_values_shape`
- `test_fetch_update_relocates_a_confirmed_value_by_quoted_row_when_the_page_moves`
- `test_fetch_update_reports_gone_when_the_quoted_row_no_longer_matches` —
  the `KIND_GONE` idiom, old page named, old locked value preserved.
- `test_fetch_update_errors_on_two_rows_matching_the_quote_and_never_picks`
- `test_a_changed_value_in_the_quoted_row_surfaces_as_the_loud_drift_diff` —
  `0.93 -> 0.95`, build keeps the pinned number (`calc-sources.md` Q2).
- `test_accept_refuses_a_changed_pdf_and_directs_fetch_update`
- `test_a_refused_pdf_accept_leaves_the_item_and_the_lockfile_byte_identical`
  — the `snapshot_tree` posture over both files.
- `test_a_no_write_server_browses_pdfs_and_refuses_accept`

UI, static:

- `test_the_pdf_page_view_parses_no_pdf_in_the_browser` — no served JS module
  touches PDF structure; the page's only data is the positioned-text payload.
- `test_the_pdf_confirm_step_reuses_the_csv_confirm_panel_and_its_empty_unit_field`
- `test_nothing_is_preselected_even_when_the_page_has_exactly_one_candidate`
- `test_the_pdf_pick_inserts_through_the_existing_draft_mechanism` —
  `setDraftBody`, the Slice B op, no new op name.

End to end:

- `test_a_picked_datasheet_value_saves_and_resolves_without_a_cli_step` —
  pick on page 14, confirm, accept, the served calc table shows the value.
- `test_a_picked_datasheet_value_survives_a_rebuild_and_drifts_when_the_pdf_changes`

## 12. Phasing

Mirrors `editor-source-picker.md` §11 exactly: read-only service first, then
the panel, then the write — and the write is shared, not forked.

**Slice P-A — the service reads PDFs. LANDED 2026-09-27.**
`sources.page_candidates()` (pypdf visitor extraction, row grouping, candidate
grammar reuse, caps), the `pdf` reader registration (extension-gated,
import-gated), the page read endpoint, opening at the cited `page:`/`section:`
from the lockfile, and the extraction + endpoint tests. No UI, no writes.
Independently useful (the same API a future CLI `refdes sources pdf-page` sits
on) and it is where the confinement rules get re-proven for a new file type.
May land any time after CSV Slice A (§10 Q6) — it did.

**Slice P-B — the page view and confirm step.** The positioned-text view,
candidate list with header guesses, the visible-failure states, and the
confirm panel extended to a PDF pick — reusing the CSV panel's contract
(§3), which means it lands with or after CSV Slice C so one panel serves both
(§10 Q6).

**Slice P-C — accept.** The pdf reader's `extract()` implementing quoted-row
re-location (§6), riding Slice B's widened edit op unchanged. **Blocked on
CSV Slice B by design**: this slice adds a reader, not a write path.

**Later.** pdf.js faithful rendering, if positioned text proves too crude
(§5, §10 Q1). The citations row editor (shared enabler,
`editor-source-picker.md` §8). OCR stays out long enough to prove it is not
missed.
