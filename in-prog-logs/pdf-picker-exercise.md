# PDF-picker exercise — citations into real PDFs, as a user

The gap `in-prog-logs/user-sim-release-gate-run3.md` §2 ("Not covered", last
bullet) and §5 item 2 named: **no run has put a real PDF through citation
resolution.** Run 3's own words: *"The `section:` path was exercised against a
plain-text local file and failed in exactly the shape `docs/markdown.md`
documents for 'pypdf can't parse the file', which is correct but is not the
same as exercising PDF resolution."* This is that run.

**Method, as in the prior three gates:** documented surfaces only — `docs/`,
`refdes <command> --help`, real CLI invocations, real HTTP against
`refdes serve`. Nothing under `src/`, `tests/` or `docs/` was modified. Reported
version `refdes 0.5.0`, HEAD `8d12680`. The `refdes` on `PATH` is a broken
editable install pointing at another worktree, so every command went through
`.scratch/refdes` (`PYTHONPATH=<this worktree>/src python -m refdes.cli …`).
No `git stash`, no `git add -A`, no `pkill`; each `serve` was started with
`--no-open --port N --token-file` and stopped by its own PID.

**The PDFs are mine and I wrote the file format by hand.** No PDF-writing
library is installed in this environment — `reportlab`, `pymupdf` and
`pdfminer` all fail to import, and per the brief I did **not** pip-install
anything. `pypdf 6.19.0` is present, but it is a *reader*; it cannot lay out
text. So `.scratch/pdffix/make_pdf.py` writes the PDF bytes directly: content
streams with `BT /F1 <size> Tf 1 0 0 1 <x> <y> Tm (…) Tj ET` per line (a
Helvetica Type1 base-14 font, WinAnsi), plus a real `/Outlines` tree with
`/First /Last /Count /Next /Prev` so the nesting is genuine. Every fixture was
verified with pypdf before use — `PdfReader(...).outline` walks as nested
lists and `get_destination_page_number` returns the pages I put there, and
`extract_text()` returns the text I wrote. Fixtures:

| File | What it is |
|---|---|
| `ds-main.pdf` | 8 pages, real text on every page, 8-entry nested outline (`Electrical Characteristics` → `Thermal Information`; `Application and Implementation` → `Layout Guidelines`), and a min/typ/max table on page 2 |
| `ds-notext.pdf` | same outline, pages 5–8 carry a real `/XObject` image and **zero** text runs (verified: `extract_text()` → `''`, `page.images` → `['/Im0']`) |
| `ds-nooutline.pdf` | real PDF, no `/Outlines` at all |
| `ds-garbage.pdf` | 40 bytes, `%PDF-1.7` header then junk |
| `ds-truncated.pdf` | the first half of `ds-main.pdf` — pypdf raises `PdfStreamError` |
| `ds-badoutline.pdf` | valid PDF whose `/Outlines /First` points at a nonexistent object |
| `ds-changed.pdf` | `ds-main.pdf` with page 2's efficiency row re-valued `0.930 → 0.950` (text changed, structure identical) |
| `ds-moved.pdf` | `ds-main.pdf` with a front-matter page inserted, so every section moves up one page |
| `ds-relabel.pdf` | the efficiency row's **labels** changed (`Efficiency,` → `Conversion ratio,`) with the same numbers |
| `ds-duprow.pdf` | the same quoted row duplicated verbatim on page 3 |
| `ds-nogone.pdf` | `ds-main.pdf` with `Ordering Information` dropped from the outline |
| `ds-short.pdf` | a 4-page revision — the pin for page 6 no longer exists |
| `ds-ws.pdf` | outline titles stored with an embedded newline, a leading tab and a trailing space |
| `ds-huge.pdf` | 33 MiB, to cross the 32 MiB byte cap |
| `ds-dense.pdf` / `ds-manynums.pdf` | 1001 text runs on one page / 182 numeric tokens, to cross the span and candidate caps |
| `ds-prose.pdf` | text but no digits at all |
| `ds-grammar.pdf` | `1,000` / `1_000` / `1e999999` / `12 %` / `.5` / `5.` probes |
| `ds-nonascii.pdf` | `½` and `²` (U+00BD, U+00B2) beside ASCII digits |

Remote paths were exercised against a local `python -m http.server` on
`127.0.0.1:8899` rather than the vendor URL, so the network leg is real HTTP
with a real `Content-Length` but no TLS and no redirects. That limitation is
recorded in §6.

---

## 0. Headline summary

**The section path is in genuinely good shape, and the page path is not
checked at all.** Six `section:` failure modes, six correct messages; a
`section:`-resolved page survives a re-pin, moves with the content, and
degrades honestly when its bytes stop matching. The text-layer extraction, the
candidate grammar, the quoted-row re-location, the browser picker and the
`pypdf`-missing fallback all behave as documented, several of them better than
I expected.

**The one real defect is that `page:` is a free-text string that nothing
validates, ever.** `page: "99"` on an 8-page PDF, `page: "0"`, and
`page: "eight"` all pass `check`, pass `build`, pass
`build --require-citations`, report `ok` in `audit`, and render a live
`#page=99` / `#page=0` / `#page=eight` fragment into the published HTML. That
is **P1** below. It is not a regression and it is not a surprise to the docs —
`docs/markdown.md:333` says outright that `page:` "is a number you looked up by
hand and re-check every revision" — but nothing anywhere in the tool notices
when the hand lookup was wrong, and the severity table has no row for it. The
`section:` path, which exists precisely to remove that manual re-check, has six
documented failure rows; the `page:` path has none, and the picker — the one
surface that *does* open the page — catches it and says so.

Three smaller findings, then: the "closest outline titles" hint is empty for
the most likely near-miss (**P2**), a missing local file at `fetch` time
reports a raw `FileNotFoundError` with an absolute path instead of the
documented message (**P3**), and one `source()` re-location failure message
embeds an absolute server path in a user-facing diagnostic (**P4**, low).

---

## 1. Findings, ranked

### P1 — `page:` is never validated: a page past the end of the document is reported `ok` and published as a dead link

**Severity: medium.** This is the one thing the whole feature is about. Every
other citation condition in `docs/markdown.md:439-446` has a severity row; a
`page:` that does not exist in the document has none, and no code path checks
it.

Three citations against `ds-main.pdf` (8 pages), one item:

```yaml
citations:
  - path: datasheets/ds-main.pdf
    page: "99"
  - path: datasheets/ds-main.pdf
    page: "0"
  - path: datasheets/ds-main.pdf
    page: "eight"
```

```
$ .scratch/refdes fetch
(minted 1 key(s) while loading)
fetched  datasheets/ds-main.pdf  sha256=b595f7bdb5a8...  hash-only
1 citation(s) processed, 0 failed
exit=0

$ .scratch/refdes check
1 items, 0 errors, 0 warnings
exit=0

$ .scratch/refdes check -v
1 items, 0 errors, 0 warnings, 0 info

$ .scratch/refdes build
1 items, 0 errors, 0 warnings
exit=0

$ .scratch/refdes build --require-citations
1 items, 0 errors, 0 warnings
exit=0

$ .scratch/refdes audit | grep -A3 Citations
Citations:
  datasheets/ds-main.pdf
    ok             hash-only  cited by CMP-PWR-001
```

And the built page (`_site/cmp-pwr-001.html`, citations table), verbatim:

```html
<a href="assets/citations/b595f7bdb5a852cb1da8b220eaf638ecd936b413c84673ad41bfbdf9677720c8.pdf#page=99">datasheets/ds-main.pdf</a>
…
<a href="assets/citations/b595f7bdb5a852cb1da8b220eaf638ecd936b413c84673ad41bfbdf9677720c8.pdf#page=0">datasheets/ds-main.pdf</a>
…
<a href="assets/citations/b595f7bdb5a852cb1da8b220eaf638ecd936b413c84673ad41bfbdf9677720c8.pdf#page=eight">datasheets/ds-main.pdf</a>
```

Every row carries `<span class="pill pill-pass">ok</span>` and a populated
Page column. `#page=99` in a PDF viewer is the last page or an error dialog;
`#page=0` is page 1 in most viewers and nothing at all in others; `#page=eight`
is a dead fragment no viewer understands. So a build that passes CI publishes
three broken links and labels them green.

**What the docs claim.** `docs/markdown.md:333`: "`page:` is a number you
looked up by hand and re-check every revision." That is an honest statement of
the posture, and it is why this is medium and not high. But the same page
documents the *whole* severity table for citations (`:439-446`, six rows) and
none of them covers this, and `docs/markdown.md:382-383` argues the principle
out loud for `section:` — "a page number from another revision is a wrong
link, not a near miss" — while an authored `page:` gets none of that
protection. `docs/output.md:414` defines `state: "ok"` as "Resolved — hash on
file", which is literally true and materially misleading here: the hash is
fine, the page is not.

**Where the check already exists and is simply not on this path.** The picker
*does* validate a page against the document, and says so precisely:

```
$ curl -s -H "X-Refdes-Token: $TOK" \
    "http://127.0.0.1:8741/api/item/CMP-PWR-001/sources/page?path=datasheets/ds-main.pdf&page=99"
{"kind":"refused","ok":false,"error":"datasheets/ds-main.pdf: page 99 is not in this document -- it has 8 page(s)","reason":"…"}
HTTP 422
```

`src/refdes/sources.py:811` builds that string. The same endpoint validates
`page=0` and `page=abc` as a query-parameter error:

```
$ curl … "…/sources/page?path=datasheets/ds-main.pdf&page=0"
{"error":"page must be a positive integer: ?page=<a page number>"}
HTTP 400
$ curl … "…/sources/page?path=datasheets/ds-main.pdf&page=abc"
{"error":"page must be a positive integer: ?page=<a page number>"}
HTTP 400
```

So the grammar `page:` needs is already written, already tested, and already
used — on the browse path, which is the path a user only reaches *after* the
build has already published the wrong link. The picker also degrades well
rather than 500ing: with `page: "99"` pinned, `GET /api/item/<ref>/sources`
reports `open_page: 99` and the page endpoint answers `page 1`, `prev: null`,
`open_at: {"from": "default"}`, with the reason carried in `cited.detail`:

```
"cited": {"page": "99", "section": "", "detail": "the page this citation names could not be opened: datasheets/ds-main.pdf: page 99 is not in this document -- it has 8 page(s) -- browsing page 1"}
```

Fix shape, smallest version: the two conditions the picker already enforces
are the two worth enforcing at pin time, and `refdes fetch` is the only
command that has the bytes. A `page:` that is not ASCII digits is a
declaration error (the schema types it as a plain `string` —
`src/refdes/schema_json.py:87` — so `page: eight` is schema-valid today, and
`serve/api.py:383` and `serve/sources.py:844` both already have the exact
`isascii() and isdigit()` test). A `page:` past the end needs the page count,
which `fetch` has and `check`/`build` do not — and it does not have to be a
new severity row to be honest: a `WARNING … — page 99 is not in this document
-- it has 8 page(s)`, escalating under `--require-citations` with the rest,
fits the table's existing shape and the `sections_sha256` precedent. Worth
being explicit that this is **not** claiming `check` should open the PDF: that
would break the hermetic-build promise at `docs/markdown.md:348-350` and
`docs/cli-reference.md:352-353`, and I would not want it.

A narrower variant is worth naming because it is the same bug with a nastier
shape: a **re-pin that shortens the document**. `page: "6"` pinned against the
8-page `ds-main.pdf`, then the file replaced by `ds-short.pdf` (4 pages) and
`refdes fetch --update` run:

```
$ .scratch/refdes fetch --update --path datasheets/ds-short.pdf
fetched  datasheets/ds-short.pdf  sha256=fe8cfc080a4c...  hash-only
1 citation(s) processed, 0 failed
$ .scratch/refdes check
1 items, 0 errors, 0 warnings
$ .scratch/refdes build --require-citations
1 items, 0 errors, 0 warnings
$ grep -o '#page=[0-9]*' _site/cmp-pwr-001.html
#page=6
```

`fetch --update` re-hashed the file, learned it is now four pages long, and
published a link to page 6 of it. This is precisely the "a page number from
another revision is a wrong link" case, and it is the one place where the tool
*had* the information in hand at the moment of the decision and did not use it.

### P2 — the "closest outline titles" hint is empty for the most likely near-miss

**Severity: low.** `docs/markdown.md:367` promises, for a title that is not in
the outline, `no outline entry titled '…'`, **"plus the closest titles it did
find"**. The hint uses `difflib.get_close_matches` at its default 0.6 cutoff
(`src/refdes/citations.py:350`), which is calibrated for typos of similar
length and is silent for a *truncated* title — the near-miss a person actually
makes when retyping a heading from a datasheet's table of contents.

Against `ds-main.pdf`'s 8-entry outline:

```
section: 'Therma'                      -> no outline entry titled 'Therma'
section: 'Electrical'                  -> no outline entry titled 'Electrical'
section: 'Ordering'                    -> no outline entry titled 'Ordering'
section: 'Mechanical'                  -> no outline entry titled 'Mechanical'; closest outline titles: 'Mechanical Data'
section: 'Thermal Informatio'          -> … closest outline titles: 'Thermal Information', 'Ordering Information'
section: 'Application and Implementatio' -> … closest outline titles: 'Application and Implementation'
section: 'Regulatory Information'      -> … closest: 'Thermal Information', 'Regulatory', 'Ordering Information'
```

`Therma`, `Electrical` and `Ordering` are prefixes of real outline entries and
get **no** suggestion, because a prefix of a long string scores below 0.6
(`'Electrical'` vs `'Electrical Characteristics'` is 0.556; `'Ordering'` vs
`'Ordering Information'` is 0.571 — I recomputed the ratios directly to
confirm the cutoff is the cause, not the ranking). `'Mechanical'` at 0.800 gets
one. So the hint appears exactly when it is least needed and vanishes exactly
when the author truncated rather than mistyped. The two documented near-miss
classes behave differently, and only one of them is documented.

The other half is worth a line because it is the same threshold producing the
*wrong* answer: `'Regulatory Information'` suggests `'Thermal Information'`
**first**, because 0.683 > 0.625 for the correct `'Regulatory'`. A prefix match
— `cited.startswith(probe)` or `probe.startswith(cited)` — would rank
`'Regulatory Information'` for `'Regulatory Information'` first and fix the
truncation case at the same time, for about three lines.

### P3 — a missing local file at `fetch` time reports a raw `FileNotFoundError` with an absolute path

**Severity: low.** `docs/markdown.md:329` promises "a cited file that doesn't
exist is an error, always", and at `check` that is exactly what happens. At
`refdes fetch` it is an unhandled `OSError` string, and it is the only
citation diagnostic in the whole surface that carries an absolute server path:

```
$ .scratch/refdes fetch
FAILED  datasheets/nope.pdf  [Errno 2] No such file or directory: '/home/jorb/.paseo/worktrees/16msma8v/pdf-picker-exercise/.scratch/run/t-abs/datasheets/nope.pdf'
(minted 1 key(s) while loading)
1 citation(s) processed, 1 failed
exit=1
```

Compare the same command one line away, for a file that exists but pypdf
cannot parse — the documented shape, with the project-relative label and no
traceback (`docs/markdown.md:370`):

```
FAILED  datasheets/ds-garbage.pdf: sections 'Application and Implementation' (cited by CMP-PWR-001): pypdf could not read the PDF: startxref not found
```

`check` on the same project is right, and names the remedy:

```
ERROR   items/parts/power.yaml:2 [CMP-PWR-001] — cited local file 'datasheets/nope.pdf' does not exist
```

So the condition is detected correctly, and the one place it is reported badly
is the command whose job is to report it. `docs/cli-reference.md:105` promises
that "Every diagnostic leads with `file:line`" — this one leads with neither a
`file:line` nor a project-relative path, and the missing `item id` is the other
half: every other `FAILED` line names its citers (`cited by CMP-PWR-001`).
Reusing the `check`-side message would fix all three, and
`authorize_source_path`/`classify` already produce a canonical relative path
for this case.

### P4 — one `source()` re-location message embeds an absolute server path

**Severity: low.** `docs/design/editor-source-picker.md:350` and
`docs/design/editor-pdf-picker.md:389` both promise the `shown()` posture:
"project-relative paths only". Over HTTP that promise **holds** — I checked
every response I got from a changed-file project for `/home/jorb` and the item
payload and the sources list were both clean. The leak is in the CLI's own
`check` warning, which embeds the absolute path of the project *file* inside
the message body:

```
$ .scratch/refdes check
WARNING <project> — SOURCE FILE CHANGED: 'datasheets/ds-main.pdf' no longer matches its pin, but the build is still using the LOCKED values, not the file -- 'efficiency_v_out': locked 0.930, but the file can no longer supply it (/home/jorb/.paseo/worktrees/16msma8v/pdf-picker-exercise/.scratch/run/t-gone2/datasheets/ds-main.pdf: key 'efficiency_v_out': gone -- the text you confirmed no longer exists in this revision (was page 2)) [used by CMP-PWR-001]. Review the change, then accept it with: refdes fetch --update --path datasheets/ds-main.pdf
```

The same shape appears in the `fetch --update` `FAILED` line for the
ambiguous-row case. Everywhere else in this report — every `section:`
diagnostic, the pypdf-unreadable message, the blob-missing message — the path
is the project-relative `datasheets/ds-main.pdf`. So this is one call site
composing an `OSError`'s `str()` where its siblings compose the label. It also
means the message differs between two machines for no reason, which is the
part that would show up in a pasted CI log.

---

## 2. `section:` resolution — the six documented failure modes, all exercised

`docs/markdown.md:364-372` is a seven-row table. I drove all seven. Every
message matches its documented wording, every one exits nonzero from `fetch`,
and every one names the path, the section and every citing item.

**1. No outline at all** (`ds-nooutline.pdf`):

```
FAILED  datasheets/ds-nooutline.pdf: sections 'Application and Implementation' (cited by CMP-PWR-001): this PDF has no outline (bookmarks); section: cannot be resolved -- cite page: instead
1 citation(s) processed, 1 failed
exit=1
```

**2. Title not in the outline** (`ds-main.pdf`): exactly the documented string,
with the promised hint, and the hint points at the right entry —
`application and implementation` (case near-miss) →
`closest outline titles: 'Application and Implementation'`; `4. Application
and Implementation` (numbering prefix) → same hint; `Layout Guideline` →
`'Layout Guidelines'`. A prefix far from any title (`4.1 Typical
application`, `Electrical`, `Thermal`) gets no hint, which is P2.

**3. Two entries with that title** (`ds-dup.pdf`, `Electrical Characteristics`
on pages 2 and 7):

```
FAILED  datasheets/ds-dup.pdf: section 'Electrical Characteristics' (cited by CMP-PWR-001): the outline has 2 entries titled 'Electrical Characteristics' (pages 2, 7) -- cite page: instead
```

Both pages named, and it refuses rather than taking the first — the documented
behaviour, and the right one.

**4. The extra isn't installed** — see §4.

**5. pypdf can't parse the file.** Three distinct unreadable files, three
distinct pypdf messages, no traceback in any of them, exactly as
`docs/markdown.md:370` promises:

```
FAILED  datasheets/ds-garbage.pdf: sections 'Application and Implementation' (cited by CMP-PWR-001): pypdf could not read the PDF: startxref not found
FAILED  datasheets/ds-truncated.pdf: sections 'Features' (cited by CMP-PWR-001): pypdf could not read the PDF: Stream has ended unexpectedly
FAILED  datasheets/ds-badoutline.pdf: sections 'Features' (cited by CMP-PWR-001): this PDF has no outline (bookmarks); section: cannot be resolved -- cite page: instead
```

pypdf's own low-level chatter (`Object 99 0 not defined.` / `EOF marker not
found`) does reach stderr ahead of the `FAILED` line on the malformed-outline
file. It is not a traceback and it does not stop the tool, so the documented
posture holds; it is worth knowing that a malformed outline produces two lines
of pypdf noise before the message that explains it.

**6. `--update` and the title is gone** (`ds-nogone.pdf`): verbatim as
documented, with the old page named —

```
FAILED  datasheets/ds-gone.pdf: section 'Ordering Information' (cited by CMP-PWR-001): the section you cited no longer exists in the new revision (was page 6)
```

and, on a second `--update` once the bytes have settled, the shape degrades
correctly to the no-match message with the hint (`closest outline titles:
'Thermal Information'`), because the lockfile's previous-page record only
applies to a re-pin.

**7. The local file moved since it was pinned, `--update` not given**
(`docs/markdown.md:372`) — the section is *not* re-resolved against moved
bytes, and it says so:

```
$ .scratch/refdes fetch            # file already changed on disk, no --update
skipped  datasheets/ds-main.pdf  sha256=…  hash-only
```

**Exactness and whitespace**, `docs/markdown.md:354-355` ("matched exactly and
case-sensitively, after whitespace is collapsed"):

| `section:` | result |
|---|---|
| `Application and Implementation` | → page 4 |
| `Application  and  Implementation` (double space) | → page 4 |
| ` Features ` (leading/trailing space) | → page 1 |
| `Electrical Characteristics` against `ds-ws.pdf`, whose stored title is `Electrical\nCharacteristics` | → page 2 |
| `Thermal Information` against `ds-ws.pdf`, stored as `\tThermal Information ` | → page 3 |
| `ElectricalCharacteristics` (no space) | no outline entry |
| `application and implementation` (case) | no outline entry + hint |
| ` electrical characteristics ` (case **and** space) | no outline entry + hint |

Case-sensitive, whitespace-collapsed on both sides, no fuzzy matching. Exactly
as documented. The nested outline resolves too: `ds-main.pdf`'s
`Layout Guidelines` is a child of `Application and Implementation` and resolves
to page 5, so the nesting is walked rather than flattened.

**A failed lookup does not undo the pin** (`docs/markdown.md:374-376`):
confirmed in every failure case — the `sha256` is written, the section is
dropped from the lockfile, and the record survives. Re-running `fetch` after a
successful fix adds the section to the *existing* record without re-downloading
(a `skipped` line plus `section 'Layout Guidelines' -> page 5`), which is the
behaviour `docs/cli-reference.md:386-390` describes.

---

## 3. `page:` vs `section:`, and the bytes rule

**They have to agree; `page:` wins** (`docs/markdown.md:393-396`), verified
with two citations on the same document, one agreeing and one not:

```
$ .scratch/refdes check
WARNING items/parts/power.yaml:2 [CMP-PWR-001] — citation to datasheets/ds-main.pdf gives page: '6' but section 'Application and Implementation' resolves to page 4; the explicit page: is used for the link -- fix one or the other
```

and the rendered fragments are `#page=6` and `#page=4` respectively — the
explicit page used for the link, the resolved one for the other row. The
warning names both numbers and the file. Correct as documented.

**"A page belongs to the bytes it was read out of"**
(`docs/markdown.md:378-383`, the `sections_sha256` rule). I hand-edited the
lockfile's `sections_sha256` to a different hash — the "record from before a
re-pin" case the docs name — and the rule fires exactly as written:

```
$ .scratch/refdes check
WARNING items/parts/power.yaml:2 [CMP-PWR-001] — section 'Application and Implementation' of datasheets/ds-main.pdf was resolved against different bytes than the ones now pinned; run 'refdes fetch --update --path datasheets/ds-main.pdf' to re-resolve it
```

and the built page drops the fragment entirely: before the edit, `#page=2` and
`#page=4`; after, only `#page=2` (the authored one) — the resolved page is
withheld, "linked with no page", which is the documented behaviour and the
right call.

**Re-pinning re-resolves every section for that path, including out-of-scope
items** (`docs/markdown.md:384-390`). Two items cite the same PDF, one
`--item`-scoped fetch, the new revision shifts every section up a page:

```
$ .scratch/refdes fetch --item CMP-PWR-001 --update
fetched  datasheets/ds-main.pdf  sha256=9e473d9bca4d...  hash-only
         section 'Features' -> page 2
         section 'Ordering Information' -> page 7
```

`Ordering Information` is cited by `CMP-SNS-001`, which is **not** in scope,
and it moved 6 → 7 anyway. The doc says "scoping a fetch narrows which paths
are re-pinned, it cannot narrow what re-pinning them means" — verified.

**A section that stops being cited stops being recorded**, and an authored
`page:` survives a re-pin untouched. Both confirmed; the second one is P1's
narrow variant.

---

## 4. The `pypdf`-missing fallback

Simulated without uninstalling anything, two ways.

**A) import raises.** A `pypdf.py` on `PYTHONPATH` ahead of site-packages that
raises `ImportError` on import:

```
$ .scratch/refdes-nopdf fetch
FAILED  datasheets/ds-main.pdf: sections 'Application and Implementation' (cited by CMP-PWR-001): section: needs the optional PDF extra: pip install refdes[pdf]
1 citation(s) processed, 1 failed
exit=1
```

Verbatim the documented string (`docs/markdown.md:369`). Exit 1, not a
traceback, and the pin still lands — a failed lookup does not undo the pin.

**B) the module is genuinely invisible.** The reader's availability probe is
`importlib.util.find_spec` (`src/refdes/sources.py:1165`), not `import`, so a
shim that only breaks `import` does not exercise the real gate. A
`sitecustomize.py` on `PYTHONPATH` that makes `find_spec("pypdf")` return
`None` and `import pypdf` raise `ModuleNotFoundError` does. Same user-visible
result on the CLI:

```
$ .scratch/refdes-nopdf fetch
FAILED  datasheets/ds-main.pdf: sections 'Application and Implementation' (cited by CMP-PWR-001): section: needs the optional PDF extra: pip install refdes[pdf]
1 citation(s) processed, 1 failed
exit=1
```

and the follow-on states, which are the ones a user actually hits. The
unresolved section degrades to the documented warning
(`docs/markdown.md:446`) and escalates under the gate:

```
$ .scratch/refdes-nopdf check
WARNING items/parts/power.yaml:2 [CMP-PWR-001] — section 'Application and Implementation' of datasheets/ds-main.pdf has no resolved page in the lockfile; run 'refdes fetch --path datasheets/ds-main.pdf' to resolve it
1 items, 0 errors, 1 warnings
exit=0

$ .scratch/refdes-nopdf build --require-citations
ERROR   items/parts/power.yaml:2 [CMP-PWR-001] — section 'Application and Implementation' of datasheets/ds-main.pdf has no resolved page in the lockfile; run 'refdes fetch --path datasheets/ds-main.pdf' to resolve it
1 items, 1 errors, 0 warnings
exit=1
```

That is the row of the table verbatim, including the "naming every cacher"
part (checked with three citers across two files: three `WARNING` lines, one
per citing item, each with its own `file:line`).

**The lockfile is not a hostage.** Fetch a project with the extra installed,
then take the extra away and run `check`/`build`: the already-resolved page
still renders.

```
$ .scratch/refdes-nopdf check
1 items, 0 errors, 0 warnings
$ grep -o '#page=[0-9]*' _site/cmp-pwr-001.html
#page=4
```

This is the hermetic-build promise holding under the one condition most likely
to break it, and it is worth recording as a clean result rather than leaving it
to be assumed.

**The editor's half of the fallback** (`docs/design/editor-pdf-picker.md:154`,
"without it the picker offers no PDFs and shows the existing install hint"):

```
$ curl -s -H "X-Refdes-Token: $TOK" "http://127.0.0.1:8753/api/item/CMP-PWR-001/sources"
{"item": "CMP-PWR-001", "files": [],
 "problems": [{"path": "datasheets/ds-main.pdf",
               "problem": "datasheets/ds-main.pdf: the pdf source reader needs the optional PDF extra: pip install refdes[pdf]"},
              {"path": "datasheets/ds-notext.pdf",
               "problem": "datasheets/ds-notext.pdf: the pdf source reader needs the optional PDF extra: pip install refdes[pdf]"}]}
```

No files offered, one problem per cited PDF, the same install sentence, and
the page endpoint 422s with it. It is not the CSV reader's "no source reader
for this file type", which is the failure mode the design doc explicitly
rejects. This matches the named test
`test_without_the_pdf_extra_the_picker_offers_no_pdfs_and_shows_the_hint`
(`tests/test_serve_pdf_sources.py:664`) — I read the test to check which
decision it gates, not to confirm my own result.

---

## 5. The browser source picker, over HTTP

Driven through `refdes serve --no-open --port N --token-file`, reading the
token from the file, all requests with `X-Refdes-Token` and writes with the
server's own `Origin`. Endpoints taken from the design docs
(`docs/design/editor-pdf-picker.md:29-35`,
`docs/design/editor-source-picker.md`), not from the source.

**Listing a cited PDF.** `GET /api/item/CMP-PWR-001/sources` on the local
`ds-main.pdf` with `page: "2"`:

```json
{"path": "datasheets/ds-main.pdf", "reader": "pdf", "browse": "pages",
 "open_page": 2, "state": "ok", "detail": "",
 "sha256": "b595f7bdb5a8…", "fetched": "2026-10-01T08:48:04Z", "pinned_values": {}}
```

`browse: "pages"` and `open_page` are the page-mode marker and the page to open
at, exactly as §12 describes. A `section:`-pinned citation opens at the
resolved page, and the response says where the page came from:

```json
"open_at": {"page": 6, "from": "section"}, "page": 6,
"cited": {"page": "", "section": "Ordering Information", "detail": ""}
```

`from: "page"`, `from: "section"`, `from: "requested"` and `from: "default"`
all appear, so the UI can say "opened from" honestly.

**A hash-only remote datasheet** is refused with the reason and the fix
(`§10 Q4 option A`): a remote citation with `keep_copy: true` browses
normally; the same URL hash-only is reported as such. I confirmed the keep-copy
one lists and browses, and the propose step refuses with the actual reason
rather than a generic one:

```
"accept_supported": false,
"accept_reason": "'http://127.0.0.1:8899/ds-remote.pdf' is a remote citation; source() reads only a repo-local file committed with the project"
```

and the same refusal on accept, with the project-relative path:

```json
{"kind":"refused","ok":false,
 "message":"refused: 'http://127.0.0.1:8899/ds-remote.pdf' is a remote citation; source() reads only a repo-local file committed with the project",
 "path":"items/parts/sensor.yaml"}
```

**Path confinement.** A PDF the item does not cite, including one cited by a
*different* item:

```
HTTP 422 {"kind":"refused","ok":false,
 "error":"CMP-PWR-001 does not cite 'datasheets/ds-notext.pdf'; add it to this item's citations: (a citation on another item does not authorize this one)"}
```

**No PDF bytes and no absolute path in any response.** I grepped every
response I collected from a project whose diagnostics contained an absolute
path, and the served payloads were clean — `GET /api/item/CMP-PWR-001` and
`GET /api/item/CMP-PWR-001/sources` both contained no `/home/jorb`. The
`shown()` posture holds over HTTP; P4 is the CLI-side leak, not this.

**What gets written back.** The picker never writes `page:`/`section:`
(`docs/design/editor-pdf-picker.md:420-426`, a stated non-goal), and that
holds: `edit.fields.citations` is `{"editable": false, "reason": "not a
scalar value: collections are not editable here"}` and a `set_field` on
`citations` is refused with `set_field takes a scalar value: collections and
null are not editable`. So the citation block in `items/parts/power.yaml` is
byte-identical after a pick; what the accept wrote was the body draft and the
lockfile:

```
body: |
  ```calc
  eta2 = source("datasheets/ds-main.pdf", "eff_min") | 1
  ```
```

plus, in `.refdes/citations.yaml`, the server's own read:

```yaml
values:
  eff_min:
    page: 2
    quoted: Efficiency, 3.3 V out, 0.910 0.930 0.940
    reader: pdf
    token: 1
    value: '0.910'
```

**"The browser never sends a value."** I sent one anyway — a `pin` carrying
`"value": "0.999"` for a token the file says is `0.910` — and the lockfile
recorded `0.910`. The client-supplied value was ignored, which is the §4
guarantee holding under an adversarial client. The response's `pinned` array
echoes what the server read.

**A stale pick is refused**, with the reason a browser can act on:

```
HTTP 422 {"kind":"refused","ok":false,
 "error":"this PDF changed since the page was read; reopen the page to review it"}
```

and on a file that changed since its pin, the accept refuses with the
`fetch --update` direction verbatim:

```
refused: datasheets/ds-main.pdf: the file has changed since it was pinned -- accepting 'conversion_ratio_v_out' from these bytes would pair the old hash with new ones. Review the change, then run 'refdes fetch --update --path datasheets/ds-main.pdf'
```

**Nothing is pre-selected, and the unit is never defaulted.** `propose` with
no unit:

```json
"unit": "", "units": ["1"], "line": null, "complete": false,
"reason": "the file supplies a bare number, so the unit is yours to declare -- there is no default; '1' means dimensionless"
```

and with `unit=1` the server composes the whole line
(`eta = source("datasheets/ds-main.pdf", "efficiency_v_out") | 1`) — the
browser never learns the grammar. Every candidate in a min/typ/max row is
offered and none is chosen: for the efficiency row the picker returns four
candidates (`3.3`, `0.910`, `0.930`, `0.940`) with per-candidate header
guesses, and the panel's own JS renders them as a button per candidate
(`sourcepicker.js`, `candidateList()`), so the min/typ/max rule is a property
of the data rather than a UI convention.

**Reading a page** returns positioned text with coordinates, `page_box`
(MediaBox bounds), rows grouped by y, and `prev`/`next`:

```json
"spans": [{"text": "Supply current, no load    18 uA       21 uA       26 uA",
           "x": 60.0, "y": 635.0, "size": 10.0, "width": 280.0}, …],
"rows": [{"index": 6, "y": 620.0,
          "text": "Efficiency, 3.3 V out, 0.910 0.930 0.940",
          "labels": ["Efficiency,", "V", "out,"], "candidate_count": 4,
          "tokens": [{"text": "0.930", "value": "0.930", "numeric_index": 2,
                      "candidate": true, "header_guess": "21"}, …]}],
"page_box": [0.0, 0.0, 612.0, 792.0], "prev": 1, "next": 3
```

The coordinates I fed in (x=60, y=635 for that row) came back exactly, and the
row grouping put the two lines of my wrapped table row into two rows rather
than one — which is the "y-band" heuristic doing what it says.

**The numeric grammar is the CSV grammar.** Every hazard
`docs/design/editor-source-picker.md:242-243` lists for CSV, checked through
the PDF path on `ds-grammar.pdf`:

| token in the PDF | a candidate? | canonical |
|---|---|---|
| `1,000` | no | — |
| `1_000` | no | — |
| `1e999999` | no | — |
| `12` (from `12 %`) | yes | `12` |
| `-40` / `+7` | yes | `-40` / `7` |
| `.5` / `5.` | yes | `0.5` / `5` |
| `0.930` | yes | `0.930` |
| `½` / `²` | **no** | — |

Non-ASCII digits are not offered, even sitting beside offerable ASCII ones on
the same line. The picker cannot offer a number `fetch` would refuse, which is
the property §2 claims for it.

**Visible failure, never a guess** (`docs/design/editor-pdf-picker.md:193-199`).
An image-only page (`ds-notext.pdf` page 5 — a real `/XObject` image, zero
text runs):

```json
"spans": [], "rows": [], "span_count": 0, "candidate_count": 0,
"detail": "could not read page 5 -- no extractable text (this looks like a scanned or image-only PDF; OCR is out of scope)"
```

HTTP **200** with the failure in `detail` — a panel state, not an error page,
which is what the design asks for. A page with text but no digits
(`ds-prose.pdf`):

```
"detail": "page 1 has 3 text run(s) but no number that reads as a plain ASCII decimal, so there is nothing to choose here"
```

**The caps report rather than truncate**, all three, with the limits echoed:

```
ds-dense   (1001 runs):  "too_dense": true,
  "detail": "this page holds more than 1000 text runs, which is too dense to browse as positioned text -- nothing past the cap was read, so what is here is no part of the page"
ds-manynums (182 cand):  "truncated": true,
  "detail": "stopped at the 200-candidate cap; the rest of page 1 was not read, so it is in no count here"
ds-huge (33 MiB):        HTTP 422
  "datasheets/ds-huge.pdf: the file is 34603744 bytes and a page read refuses anything above 33554432 bytes (32 MiB) -- cite the datasheet revision you need, or a smaller document"
"limits": {"max_bytes": 33554432, "max_spans": 1000, "max_candidates": 200}
```

The three numbers are the ones §12 names, in the payload where the client can
show them. Note the span cap's wording is the honest one: "what is here is no
part of the page".

**A `section:` can resolve to a page the picker then cannot read.** On
`ds-notext.pdf`, `section: Layout Guidelines` resolves to page 5 at fetch time
(an outline is independent of page content), the build is green, and the
picker opens page 5 and says "could not read page 5". Two surfaces, two
different truths about the same page, both honest. Worth knowing rather than
fixing.

---

## 6. Text-layer extraction, and the source-value lifecycle

**Is there a quote/excerpt feature?** Yes, and it is a *lockfile* value rather
than a CLI one. A confirmed PDF row is recorded as `quoted:` plus a
zero-based `numeric_index` among the row's numeric tokens, and it is
re-located **by text, not by position** on every later read
(`docs/design/editor-pdf-picker.md:314-327`). There is no `refdes sources …`
command — I confirmed `refdes sources`, `refdes source-pick` and `refdes pdf`
are all `invalid choice`, exit 2 — so this is reachable only through the
editor, which is the documented shape.

I exercised the four documented re-location outcomes against a
hand-written `values:` record, then changed the PDF under it. All four are
correct, and the two failure modes refuse rather than pick:

| what changed in the new revision | `check` | `fetch --update` |
|---|---|---|
| the row's **number** changed (0.930 → 0.950), labels same | `locked 0.930, file now 0.950 (CHANGED)` | `source value changed  datasheets/ds-main.pdf: efficiency_v_out: 0.930 -> 0.950`, exit 0 |
| the row's **labels** changed (`Efficiency,` → `Conversion ratio,`) | `the file can no longer supply it (… gone -- the text you confirmed no longer exists in this revision (was page 2))` | `FAILED … gone -- the text you confirmed no longer exists in this revision (was page 2)`, exit 1, **lockfile unchanged** |
| the row **duplicated** verbatim on another page | `… ambiguous quoted row (page 2, row 6, page 3, row 7); never choosing between matching rows` | `FAILED … ambiguous quoted row (page 2, row 6, page 3, row 7)`, exit 1, lockfile unchanged |
| the row **moved** to another page, unchanged | `locked 0.930, file now 0.930 (this value is unchanged)` | re-located, `page` updated, author's `quote` retained |

The value-change case prints the `old -> new` diff `docs/design/calc-sources.md`
Q2 requires and gates it behind `--update`. The gone and ambiguous cases are
`KIND_GONE`-class refusals that name the old page (or both pages) and leave the
previous record byte-for-byte intact — the "never a guess" rule holding under
all three ways a document can move under you. The build keeps evaluating the
*locked* value throughout, and says so in the warning's own words: "the build
is still using the LOCKED values, not the file".

**A value the file cannot supply at all** is a distinct message with its own
remedy, and it is a good one:

```
FAILED  /…/datasheets/ds-main.pdf: key 'efficiency_v_out' has no confirmed quoted row -- choose a PDF candidate in the editor and confirm it first (the existing record for datasheets/ds-main.pdf is unchanged)
```

(P4 applies to this line's shape too — leading absolute path.) And a `source()`
naming a key with no lockfile value at all is a build **error** with the
remedy, which is the gate that forces accept to be one operation:

```
ERROR   items/parts/power.yaml:2 [CMP-PWR-001] — calc 'eta': source('datasheets/ds-main.pdf', 'efficiency_v_out') has no locked value -- run 'refdes fetch --path datasheets/ds-main.pdf' to extract and pin it
```

---

## 7. The severity table and `--require-citations`, against a real PDF

`docs/markdown.md:439-446`, all six rows, each on a real PDF:

| Row | Setup | `check` | `build --require-citations` | Matches docs |
|---|---|---|---|---|
| No lockfile entry | fresh project, one local PDF cited | `INFO … has no fetched record; run 'refdes fetch --path …' to pin it` (hidden without `-v`) | `ERROR` same text, exit 1 | yes, including the `-v` gate |
| `keep_copy: true`, blob missing | remote PDF, blob deleted | `WARNING … local copy of … is missing at .refdes/copies/<sha>.pdf` | `ERROR`, exit 1 | yes |
| Blob hash no longer matches | one byte appended to the blob | `ERROR … does not match its recorded hash (the copy is tampered or corrupt)`, exit 1 | same, exit 1 | yes — never soft-failed |
| Cited local file doesn't exist | file moved aside | `ERROR … cited local file '…' does not exist`, exit 1 | same | yes, "error, always" |
| Local file changed since pinned | `ds-changed.pdf` over `ds-main.pdf` | `WARNING <project> — local citation '…' has changed since it was pinned … (cited by CMP-PWR-001, CMP-SNS-001, CMP-SNS-002)` | `ERROR`, exit 1 | yes, and it names **every** citer |
| `section:` with no resolved page | unresolved title / no outline / no extra | `WARNING … has no resolved page in the lockfile; run 'refdes fetch --path …' to resolve it` | `ERROR`, exit 1 | yes |

Two details worth naming. The `keep_copy` row is only reachable on a *remote*
citation — `keep_copy: true` on a local `path:` is refused at declaration
(`citations[0]: keep_copy: on local path '…' is meaningless -- a local file is
already local`, `ERROR`, exit 1), which is the honest reading of
`docs/markdown.md:325-326`. And the changed-file warning leads with
`<project>` rather than a `file:line`, which is a deliberate single-line-per-
file shape ("one diagnostic per file, naming every citer") rather than the
per-item shape of the others; `docs/cli-reference.md:105`'s "Every diagnostic
leads with `file:line`" is not literally true of it, and its own example
block on that page shows `WARNING <project> — …`, so the page is at least
self-consistent. Not counted as a finding.

**`--require-citations` with a page but no `rev:`** — the specific case
`user-sim-release-gate-run3.md` §5 item 2 asked for:

```
$ .scratch/refdes fetch
fetched  datasheets/ds-main.pdf  sha256=b595f7bdb5a8...  hash-only
1 citation(s) processed, 0 failed
$ .scratch/refdes check
1 items, 0 errors, 0 warnings
$ .scratch/refdes check -v
1 items, 0 errors, 0 warnings, 0 info
$ .scratch/refdes build --require-citations
1 items, 0 errors, 0 warnings
exit=0
$ .scratch/refdes audit | grep -A3 Citations
    ok             hash-only  cited by CMP-PWR-001
```

**Nothing is reported, at any severity, by any command.** And that is
*correct* as far as the documentation goes: `rev` is declared optional
everywhere it appears (`docs/markdown.md:292` "optionally a rev, page,
part_number, id"), the severity table has no row mentioning it, and `rev` is
carried but never compared against anything (`model.py:337` stores it,
`citations.py:487` reads it, and the only two consumers in the tree are the
two templates that print it into a table cell —
`src/refdes/templates/item.html.j2:191`, `document.html.j2:128`). The pin is
the sha256, so a missing `rev` costs a human a column in a review table and
nothing else. **The answer to run 3's question is "this case is inert, and
that is consistent with the docs"** — recorded so the next gate does not
re-ask it.

**The other flag shapes.** `refdes check --require-citations` is still an
`unrecognized arguments` exit 2, which run 3's F2 confirmed is now consistent
with the page. `refdes release` gates on `unpinned_citations` and
`missing_kept_copies` and both fire correctly against a real unpinned PDF
(`FAIL  unpinned_citations  CMP-PWR-001`, release blocked, exit 1; after
`refdes fetch` the same project passes all eight gates and stamps).

---

## 8. A PDF whose text changes between pins, with a page-pinned citation

The scenario as specified. `page: "2"` pinned against `ds-main.pdf`, then the
file regenerated with page 2's text altered (`ds-changed.pdf`: the efficiency
row's value changed, structure identical), and again with a *section:* on the
same file for comparison.

**What is reported** is the ordinary changed-file warning, and nothing about
the page:

```
$ .scratch/refdes check
WARNING <project> — local citation 'datasheets/ds-sec.yaml' has changed since it was pinned -- review the change, then run 'refdes fetch --update --path datasheets/ds-sec.yaml' (cited by CMP-PWR-001)
1 items, 0 errors, 1 warnings
exit=0

$ .scratch/refdes build --require-citations
ERROR   <project> — local citation 'datasheets/ds-sec.yaml' has changed since it was pinned -- review the change, then run 'refdes fetch --update --path datasheets/ds-sec.yaml' (cited by CMP-PWR-001)
exit=1
```

Then, after `refdes fetch --update`, silence:

```
$ .scratch/refdes fetch --update --path datasheets/ds-sec.yaml
fetched  datasheets/ds-sec.yaml  sha256=afdd6a077dcd...  hash-only
         section 'Electrical Characteristics' -> page 2
1 citation(s) processed, 0 failed
$ .scratch/refdes check
1 items, 0 errors, 0 warnings
```

**So: the honest answer is that the page-pinned citation is a promise the
tool cannot keep and does not check.** The `section:`-pinned citation on the
same file re-resolved against the new bytes and stayed correct. The
`page:`-pinned one was simply re-affirmed — the file changed, the hash moved,
the page number was carried across, and nobody compared "page 2 of the old
bytes" with "page 2 of the new bytes". Since `fetch --update` had the new
bytes open and pypdf loaded, it could have; since the page number is the
author's own decision (`docs/markdown.md:333`), arguably it should not have to.

This is the same defect as P1 seen from the other side, and I have kept it as
one finding rather than two. The sharpest statement of it is the four-page
case in §1: a re-pin that makes the pinned page *not exist* is accepted,
`check` is green, `build --require-citations` is green, and the site publishes
`#page=6` into a four-page document.

---

## 9. What worked cleanly

Worth recording precisely, because a gate that only lists defects is not
measuring the right thing.

- **All six `section:` failure modes, verbatim, exit 1, pin intact.** The
  documented table at `docs/markdown.md:364-372` is accurate — including
  "the closest titles it did find", "every page it is on", and "never a
  traceback" for an unparseable PDF. Three different unreadable files produce
  three different pypdf messages and no traceback in any.
- **Exactness is exact.** Case-sensitive, whitespace-collapsed on both sides,
  no fuzzy matching, ambiguity refused rather than resolved, nesting walked
  rather than flattened. `Application  and  Implementation` (double space) and
  `\tThermal Information ` (stored with a tab and a trailing space) both
  resolve; `ElectricalCharacteristics` does not. This is the part most likely
  to be quietly wrong and it is not.
- **The hermetic-build promise holds under every condition I could think of
  to break it.** `check` and `build` never opened a PDF, never touched the
  network, and produced identical results with pypdf entirely absent from the
  process (`find_spec` returning `None`) as with it installed — including
  rendering a `section:`-resolved page from the lockfile alone.
- **A failed section lookup does not undo the pin.** Six failures, six
  surviving `sha256` records, six dropped sections. And a fix on the next run
  adds the section to the existing record with a `skipped` line and no
  re-download.
- **The `sections_sha256` rule fires on a hand-edited lockfile** and withholds
  the page from the link rather than publishing a page from the wrong bytes.
- **Re-pinning is not scopeable.** `fetch --item CMP-PWR-001 --update`
  re-resolved an out-of-scope item's section too, which is the specific
  guarantee `docs/markdown.md:384-390` makes and the one most likely to be
  quietly violated.
- **The numeric grammar is one grammar.** `1,000`, `1_000`, `1e999999`, `½`
  and `²` are not candidates through the PDF path, exactly as through the CSV
  path. The picker cannot offer a number `fetch` would refuse.
- **Every cap reports rather than truncates**, with the limit in the payload,
  and the span cap's wording ("what is here is no part of the page") is the
  honest one.
- **"The browser never sends a value" survives an adversarial client.** I sent
  `value: "0.999"` for a token the file reads as `0.910`; the lockfile
  recorded `0.910`.
- **The quoted-row re-location is right in all four directions** — value
  changed, row moved, row gone, row ambiguous — with a printed `old -> new`
  diff for the first and a refusal that leaves the lockfile byte-identical
  for the last two.
- **Path confinement holds and the refusal explains itself**, including the
  case that matters most for a picker: a PDF cited by a *different* item is
  refused with "add it to this item's citations".
- **No PDF bytes and no absolute path in any HTTP response.** Checked on a
  project whose diagnostics did contain an absolute path.
- **Nothing is pre-selected and the unit is never defaulted** — `line: null`
  and `complete: false` until a unit is supplied, with the reason in the
  payload.
- **The `pypdf`-missing fallback has one sentence, and it is the right one**,
  on every surface: the CLI `FAILED` line, the picker's `problems` list, and
  the 422'd page endpoint all say `pip install refdes[pdf]` and none of them
  says "no source reader for this file type".
- **`--require-citations` covers all six soft rows and escalates none of the
  hard ones**, and `refdes release`'s gate fires on a real unpinned PDF.
- **The citations table's Detail column is the place a `section:` failure
  shows up in the rendered site**, which is a good place for it.

## 10. What I could not test, and why

- **A real vendor datasheet over the public internet.** Remote citations went
  through a local `python -m http.server` on `127.0.0.1:8899`: real HTTP, real
  `Content-Length`, real 404-free responses, but no TLS, no redirects, no
  `ETag`/`Last-Modified`, and no `keep_copy` fetch of a 6 MB file. Everything
  about *remote* citation handling that depends on the server's headers is
  untested here. (Run 3 recorded that egress exists in this sandbox, so a
  follow-up could close this with one real URL.)
- **pypdf older than 6.19.** The version floor (`pyproject.toml`'s
  `pypdf>=6.19`, and the reader's refusal for a page whose runs have no
  position — `src/refdes/sources.py:869-877`) could not be exercised: only
  6.19.0 is installed and I did not install anything. The message and its
  remedy are readable in the source; I am not claiming I saw it fire.
- **A genuinely scanned PDF.** `ds-notext.pdf`'s image-only pages carry a real
  4×4 `/XObject` image and zero text runs, which is what the reader keys on
  (`extract_text()` → `''`), but a 300 dpi raster of a real table is a
  different artifact and I had no way to make one.
- **A real browser.** The picker was driven through its HTTP API and its
  served JavaScript was read to confirm the panel's contract (no
  pre-selection, no default unit, server-composed line). The rendered page
  view, the row highlight and the confirm panel's *visual* behaviour were not
  seen in a browser, per the brief.
- **The `--no-write` picker path** and the sealed/imported-item accept
  refusals. Both are inherited from the existing edit operation rather than
  PDF-specific, and the brief's scope was PDF resolution; naming it as untested
  rather than assuming it.
- **Windows and macOS.** The `pypdf` shim, path canonicalization and the
  `--token-file` mode bits all have platform-specific edges; nothing here
  says anything about them.
- **Multi-page-per-row tables, rotated pages, and multi-column layouts.** My
  fixtures are single-column text at known coordinates. Row grouping on a
  genuine two-column datasheet table is the case the design is most careful
  about and the one my fixtures are least able to test.
- **Concurrent editing against `serve`.** Deliberately out of scope; another
  worker's, per run 3.

## 11. Suggested shape for a fix

In the order I would do them, all small:

1. **P1.** Two guards, both of which already exist elsewhere in the tree.
   `page:` that is not ASCII digits is a declaration error (the JSON Schema
   types it as a bare `string` at `src/refdes/schema_json.py:87`; the test
   `page.isascii() and page.isdigit()` is at `serve/api.py:383` and
   `serve/sources.py:844`). `page:` past the end of the document is a
   `fetch`-time warning escalating under `--require-citations`, using the
   message the picker already builds at `src/refdes/sources.py:811` — and
   `fetch` is the only command that has the bytes, so nothing about the
   hermetic-build promise changes. Add a row to the
   `docs/markdown.md:439-446` table for each, and a line to
   `docs/markdown.md:333` saying the page is checked at pin time and after a
   re-pin that changes the page count. Pin with a test: pin page 6, re-pin
   against a four-page revision, assert the diagnostic.
2. **P2.** Prefix-aware hints in `match_outline_title`
   (`src/refdes/citations.py:350`): rank a candidate whose text starts with the
   probe (or vice versa) above a same-length typo, which fixes both the empty
   hint for a truncated title and the `'Regulatory Information'` →
   `'Thermal Information'` misordering. One-line behavior change, one test.
3. **P3.** Route the missing-local-file case at fetch time through the same
   message `check` uses, with the project-relative path and the citing item
   ids, and catch it where the other `OSError` is caught rather than letting
   `str(exc)` become the diagnostic.
4. **P4.** Compose the project-relative label in the `source()` re-location
   message instead of the `OSError`'s own `str()`, matching every sibling
   citation diagnostic and the `shown()` posture the design docs state twice.
5. **Worth adding while the above is fresh:** a `rev` line in the severity
   table saying `rev` is documentation, not verification, and that the sha256
   is the pin. Run 3 asked whether a page without a `rev` should be an error;
   it should not, and the table currently just does not mention it, which reads
   as an oversight rather than a decision.
