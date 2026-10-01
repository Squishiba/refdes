# `refdes fetch` against real remote URLs — a user-shaped exercise

The one area `user-sim-release-gate-run3.md` §5 item 1 left open, because run
2 recorded "no network egress from the sandbox" and could not reach it. Egress
is available; this is the first run to exercise a real remote `fetch`.

**Method.** Documented surfaces only — `docs/markdown.md`'s "citing a datasheet"
section, `docs/cli-reference.md`'s `refdes fetch` section and its exit-code
table, `refdes fetch --help`, `refdes check --help`, `refdes build --help` —
then real HTTP. Reported version `refdes 0.5.0`; branch `remote-fetch-exercise`
off current `main` (`53e9e7b`). The `refdes` on `PATH` is a broken editable
install, so every command ran through `.scratch/rd`, a one-line wrapper
(`PYTHONPATH=<worktree>/src python -m refdes.cli …`) — the same local artefact
run 3 recorded, not counted as a product finding.

**Nothing under `src/`, `tests/` or `docs/` was modified.** All test projects
live under `.scratch/rf/`, one `cp -r` of a pristine project per scenario, no
`git` inside any of them. This report adds one file.

**Remote hosts used, a handful of requests each, no loops and no parallelism:**
`www.ti.com` (two symlink datasheets, one deliberately-nonexistent part number),
`arxiv.org` (one HEAD probe), `httpbin.org` (`/status/404`, `/status/500`,
`/redirect-to`), `example.com` (one request, as a non-PDF content type). Every
failure-shape that needed a controllable origin — redirect chain, 404-after-pin,
non-PDF, oversized, stalled body, mid-body disconnect, chunked encoding, `ETag`
— ran against a throwaway `http.server` on `127.0.0.1` under
`.scratch/rf/srv/origin.py`, so no external host took a single synthetic
request. Local servers were all stopped at the end.

---

## 0. Headline summary

**The happy path is genuinely good, and the failure paths are mostly honest.**
Eleven of the twelve behaviours this exercise set out to check behaved as
documented, several of them carefully enough to be worth naming as worked-clean
below: pinning records `sha256` + `bytes` + `fetched` and nothing else; a plain
re-fetch is byte-idempotent and makes no network request at all; redirects are
followed transparently in both directions; a `--update` against a now-404
upstream **keeps the old pin** rather than dropping it; the exit-code table is
true in all four rows that name `fetch`; and `--require-citations` escalates
exactly the two soft rows the docs say it escalates and nothing else.

**One finding is worth a maintainer's attention and is not about `fetch` at
all: the docs promise `.refdes/copies/` and `.refdes/schema.json` are
gitignored, and nothing in the product makes them so.** A project created by
`refdes init` — the documented first step, and the one
`docs/getting-started.md` walks a newcomer through — has a `.gitignore`
containing exactly one line, for `.vscode/settings.json`. A kept 6 MB TI
datasheet and a 1696-line generated schema are both stageable, and I staged
them. That is **F1**, medium, and it is a one-line fix in the same function
`init` already uses for `.vscode/settings.json`.

**The rest are documentation gaps, not behaviour bugs.** The interesting ones:
the `check --refresh` escape hatch that run 3 §5 item 1 hoped for exists and
works, but it is the *only* thing that notices a wrong pinned hash for a
**hash-only** citation — `check`, `build`, `audit` and
`build --require-citations` all report a hand-corrupted remote pin as
`ok hash-only` (**F2**, medium); `fetch` has a 30-second socket timeout and
**no size cap whatsoever**, neither documented (**F3**, low); a network failure
during `check --refresh` is a *warning* with exit 0 even though the same
condition is `exit 1` everywhere else (**F4**, low); a malformed
`.refdes/citations.yaml` is a raw `ValueError` traceback out of both `fetch`
and `check` (**F5**, low, but it is the only remaining traceback I found in
this area and run 3 filed the same class as N1).

Nothing in this run rose above medium. Every finding below was reproduced at
least twice.

---

## 1. Scenario 1 — pinning a real vendor datasheet

`.scratch/rf/`, one component citing `https://www.ti.com/lit/ds/symlink/tps62913.pdf`
with `rev: E`, `page: "14"`, `part_number: TPS62913`, `keep_copy: false`.

```
$ refdes fetch
(minted 1 key(s) while loading)
fetched  https://www.ti.com/lit/ds/symlink/tps62913.pdf  sha256=6b27cbc00d3d...  hash-only
1 citation(s) processed, 0 failed
exit 0
```

Real, in 5.9 s. `.refdes/citations.yaml`, in full:

```yaml
citations:
  https://www.ti.com/lit/ds/symlink/tps62913.pdf:
    bytes: 6003120
    fetched: '2026-10-01T08:09:17Z'
    kept_copy: false
    sha256: 6b27cbc00d3de5f5b838cbab15a37c5b136b835e43fdaf98bac290015b862bc5
```

`sha256=6b27cbc00d3de5f5b838cbab15a37c5b136b835e43fdaf98bac290015b862bc5`
`6003120` bytes — matching run 3 §0's incidental note, so the pin is stable
across runs and across sessions. That is the single most important property
this exercise could have checked and it holds.

**What gets recorded, and what does not.** `sha256`, `bytes`, `fetched`
(whole-second UTC), `kept_copy` — exactly the four fields
`docs/cli-reference.md:1530` says the lockfile holds, and nothing else. With a
`section:` present, `sections:` and `sections_sha256:` appear too (§4 of the
brief, below).

**`rev:` is not inferred, and nothing claims it is.** The citation's authored
`rev: E` is untouched by `fetch` — it is prose the human wrote, `fetch` does not
read it, does not compare it, and does not record it in the lockfile. Neither
`Last-Modified` nor `ETag` is recorded, inferred, or sent back. I confirmed the
last part with an origin that advertises both and honours `If-None-Match`:

```
--- GET /x.pdf
Accept-Encoding: identity
Host: 127.0.0.1:8932
User-Agent: refdes/fetch
Connection: close
```

No `If-None-Match`, no `If-Modified-Since`, no `Accept: application/pdf`. So
every `--update` and every `check --refresh` re-downloads the whole body even
when the server could answer `304` in one line. `User-Agent: refdes/fetch` is
set, which is the right thing to do to a vendor CDN, and
`Accept-Encoding: identity` means the hash is over the bytes on the wire with
no transparent gzip — the right call for a content-addressed pin. I searched
`docs/` for "Last-Modified", "ETag", "conditional" and "inferred" and found
nothing, so this is **not** a docs mismatch; it is an unclaimed gap and I am
recording it as F3's neighbour rather than as a defect. `bytes` is recorded
but never checked against anything on the way back in.

**Is a re-fetch idempotent? Yes, exactly.** Second and third plain runs:

```
$ refdes fetch
skipped  https://www.ti.com/lit/ds/symlink/tps62913.pdf  sha256=6b27cbc00d3d...  hash-only
1 citation(s) processed, 0 failed
exit 0
```

0.37 s — no network request at all, confirmed against the origin's own access
log. The lockfile is **byte-identical** across two further runs (`diff` clean),
so the `fetched:` timestamp is *not* churned by a skip. That is the detail that
matters for a committed file: a `fetch` in a pre-commit hook cannot produce a
diff.

`--update` is the one that rewrites `fetched:` — which is the honest meaning of
the field, and matches `docs/lifecycle.md:331`'s "not even `stamped_at`
rewritten" being about a different file.

---

## 2. Scenario 2 — redirects, then 404s

### Redirects: followed silently, in both directions, correctly

A local origin serving `/redir` (301 → `/a.pdf`) and `/redir2` (302 → `/redir`):

```
$ refdes fetch
fetched  http://127.0.0.1:8931/redir2  sha256=cef3b030a937...  kept
1 citation(s) processed, 0 failed
exit 0
```

Two hops, transparently, and the lockfile is keyed on the **cited** URL, not the
final one — which is right, because the lockfile's key is what
`--path`/`--item` match against:

```yaml
citations:
  http://127.0.0.1:8931/redir2:
    bytes: 193
    fetched: '2026-10-01T08:12:23Z'
    kept_copy: true
    sha256: cef3b030a93763cb836367821d6d398a276b6844b783f9e1b8f8bfca4d22e637
```

The kept copy is named from the *cited* URL's extension too, so a
`symlink`-style URL ending in `.pdf` gets a `.pdf` blob and an extensionless
redirect target gets an extensionless one — a real ti.com symlink URL, the case
this scenario is actually about, keeps its `.pdf`.

The real thing, cross-scheme:

```
$ refdes fetch          # http://www.ti.com/lit/ds/symlink/tps62130.pdf
fetched  http://www.ti.com/lit/ds/symlink/tps62130.pdf  sha256=f9b1af285622...  hash-only
exit 0
```

ti.com answers `http://` with a redirect to `https://` and a real 2.5 MB PDF,
and refdes pins it without comment. **The final URL after a redirect is never
recorded.** Not a bug — the cited URL is the identity — but worth knowing if you
ever go looking for "where did this actually come from".

### 404 on a never-pinned citation

Two real ti.com 404s, plus a real ti.com 200 in the same run:

```
$ refdes fetch
FAILED  https://www.ti.com/lit/ds/symlink/tps99999nonexistent.pdf  HTTP Error 404: Not Found
(minted 2 key(s) while loading)
fetched  http://www.ti.com/lit/ds/symlink/tps62130.pdf  sha256=f9b1af285622...  hash-only
2 citation(s) processed, 1 failed
exit 1
```

One bad citation does not stop the good ones. `audit` sorts it correctly:

```
Citations:
  http://www.ti.com/lit/ds/symlink/tps62130.pdf
    ok             hash-only  cited by CMP-PWR-002
  https://www.ti.com/lit/ds/symlink/tps99999nonexistent.pdf
    unpinned       no pin     cited by CMP-PWR-001
```

`unpinned  no pin` is exactly the pair `docs/cli-reference.md:546` promises —
the two columns agree rather than contradicting.

**One diagnostic-stream detail worth recording.** `FAILED` goes to **stderr**,
the `fetched`/`skipped` lines and the summary line to **stdout**, so
`refdes fetch > log` captures the successes and loses every failure:

```
$ refdes fetch 2>/dev/null
(minted 1 key(s) while loading)
1 citation(s) processed, 1 failed
$ refdes fetch 1>/dev/null
FAILED  https://www.ti.com/lit/ds/symlink/tps99999nope.pdf  HTTP Error 404: Not Found
```

That matches the convention `docs/cli-reference.md:104` states for `check`
("Errors go to stderr, warnings to stdout"), so it is consistent rather than
wrong — but `fetch`'s own section (`docs/cli-reference.md:345-410`) never says
it, and the `FAILED` line is not the word "error" a reader would grep. Low.

### 404 on a *previously pinned* citation — the case run 3 asked for

The important one, and it behaves correctly in the direction that matters. Pin
against an origin serving `/a.pdf`, then make the origin answer 404:

```
$ refdes fetch                          # pinned, origin alive
fetched  http://127.0.0.1:8931/a.pdf  sha256=38ab6aa4e368...  kept
1 citation(s) processed, 0 failed

$ touch files/hide-a                    # upstream now 404s

$ refdes fetch                          # no --update
skipped  http://127.0.0.1:8931/a.pdf  sha256=38ab6aa4e368...  kept
1 citation(s) processed, 0 failed

$ refdes fetch --update                 # asked to re-pin, upstream gone
FAILED  http://127.0.0.1:8931/a.pdf  HTTP Error 404: Not Found
1 citation(s) processed, 1 failed
exit 1
```

And after that failure the lockfile and the kept copy are **untouched** —
`sha256: 38ab6aa4e368…`, `bytes: 193`, and the blob still on disk. That is the
behaviour the whole design rests on: a failed fetch cannot silently un-pin a
datasheet or leave a citation in a state where `check` cannot explain itself.
Same for a redirect target going 404 mid-chain, and same for a connection that
dies mid-body (below). This is the single best-behaved thing in the area.

`check` afterwards is green — correctly, since the pinned bytes are still here
and still hash right:

```
$ refdes check
1 items, 0 errors, 0 warnings
exit 0
```

### Other statuses, from a real host and from local origins

| Condition | Verbatim | Exit |
|---|---|---|
| 500 (real host) | `FAILED  https://httpbin.org/status/500  HTTP Error 500: INTERNAL SERVER ERROR` | 1 |
| 404 on a redirect target, after pinning | `FAILED  http://127.0.0.1:8931/redir2  HTTP Error 404: Not Found` | 1 |
| infinite 302 loop | `FAILED  http://127.0.0.1:8934/loop  HTTP Error 302: The HTTP server returned a redirect error that would lead to an infinite loop.`<br>`The last 30x error message was:`<br>`Found` | 1 |
| 301 → 302 → 200 chain | `fetched  http://127.0.0.1:8931/redir2  sha256=cef3b030a937...  kept` | 0 |
| chunked `Transfer-Encoding`, no `Content-Length` | `fetched  http://127.0.0.1:8936/c.pdf  sha256=2c640cbd4027...  hash-only` | 0 |
| mid-body disconnect (1000 of 400000 bytes) | `FAILED  http://127.0.0.1:8935/x.pdf  IncompleteRead(136533 bytes read, 273067 more expected)` | 1 |
| `?version=2&cachebust=abc` query string | pinned, keyed on the full query, `.pdf` extension preserved from the path | 0 |

The `IncompleteRead` case is the one run 3 §5 item 1 specifically wanted
("`missing_kept_copies` when a keep-copy download fails halfway"). It is
answered by a stronger property than the one asked for: **the lockfile is not
written at all**, and neither is `.refdes/copies/`. A fetch that dies halfway
leaves no trace, so the next `fetch` starts clean rather than inheriting a
half-record.

---

## 3. Scenario 3 — content changed since pinning (the user-visible equivalent)

The brief's method: pin a URL, then edit the recorded hash to a wrong value. I
used a value that survives YAML as a string (`dead` + 60 zeros), and a second
project where I used 64 zeros — which YAML parses as the **integer `0`**. Both
are in the findings below, for different reasons.

A **hash-only** remote citation, wrong recorded hash:

```
$ refdes check
1 items, 0 errors, 1 warnings
exit 0                       # (the one warning is an unrelated selected-component note)

$ refdes build
1 items, 0 errors, 1 warnings
site written to .scratch/rfetch/_site
exit 0

$ refdes build --require-citations
1 items, 0 errors, 1 warnings
site written to .scratch/rfetch/_site
exit 0

$ refdes audit
Citations:
  https://www.ti.com/lit/ds/symlink/tps62913.pdf
    ok             hash-only  cited by CMP-PWR-001
```

**All four say everything is fine.** That is F2, and it is *arguably correct* —
there is nothing on this machine to check a hash-only pin against, which is the
documented point of hash-only mode (`docs/markdown.md:426-429`: "pinned but not
kept (hash-only) is a complete mode on its own"). But `audit`'s `ok` is a
stronger word than the evidence supports, and `build --require-citations` is
documented as the strict mode. See F2.

The detector that does exist is `check --refresh`, and it is excellent:

```
$ refdes check --refresh
1 items, 0 errors, 0 warnings

1 citation(s) drifted from their pinned hash:
  https://www.ti.com/lit/ds/symlink/tps62913.pdf
    pinned    dead000000000000000000000000000000000000000000000000000000000000
    upstream  6b27cbc00d3de5f5b838cbab15a37c5b136b835e43fdaf98bac290015b862bc5
    cited by  CMP-PWR-001
exit 1
```

Line for line this matches `docs/cli-reference.md:133-141`'s sample block,
including the two-column `pinned`/`upstream` layout and the trailing
`cited by`. It is read-only: the lockfile and `.refdes/copies/` are byte-identical
across a `--refresh` run. And it correctly distinguishes drift from a failed
fetch — that distinction is **not** documented anywhere, see F4.

**A `keep_copy: true` citation with a wrong recorded hash** behaves differently,
and better, because there *is* something to check:

```
$ refdes check
WARNING items/components/power.yaml:2 [CMP-PWR-001] — local copy of https://… is missing at .refdes/copies/1111cbc0….pdf
1 items, 0 errors, 1 warnings
exit 0

$ refdes build --require-citations
ERROR   items/components/power.yaml:2 [CMP-PWR-001] — local copy of https://… is missing at .refdes/copies/1111cbc0….pdf
build completed with errors (use --keep-going to exit 0)
exit 1
```

Correct escalation (warning → error under `--require-citations`, as
`docs/markdown.md:444` says), and the content-addressed filename means a wrong
pin is *reported* as `cache_missing` rather than silently resolving to the wrong
blob — a genuinely good property. `fetch --update` then repairs it in one step.

**The kept blob itself corrupted** (a kept copy truncated to 1000 bytes, the
user-visible shape of a half-written keep):

```
$ refdes check
ERROR   items/components/power.yaml:2 [CMP-PWR-001] — local copy of https://www.ti.com/lit/ds/symlink/tps62913.pdf does not match its recorded hash (the copy is tampered or corrupt)
1 items, 1 errors, 0 warnings
exit 1

$ refdes audit
    hash_mismatch  kept       cited by CMP-PWR-001

$ refdes release rel-a
ERROR   … does not match its recorded hash …
1 items, 1 errors, 0 warnings
exit 1
```

`docs/markdown.md:447` calls this one "**error, always**" and it is: an error at
plain `check`, an error under `build`, an error that stops `release`. Exactly
as promised, and the sharpest severity in the whole severity table.

**Upstream genuinely changed** — pinned 193 bytes, origin's bytes edited,
`--update`:

```
$ refdes fetch --update
fetched  http://127.0.0.1:8931/a.pdf  sha256=38ab6aa4e368...  kept
1 citation(s) processed, 0 failed
```

New sha, new `bytes`, new `fetched:`, new blob on disk. The **old** blob stays
in `.refdes/copies/`:

```
$ ls .refdes/copies/
38ab6aa4e368….pdf
cef3b030a937….pdf
```

Nothing prunes it, nothing warns about it, and it is invisible to `check` and
`audit` (both report `ok kept`). Every `--update` against a changed document
leaks a full copy of the superseded datasheet, forever. Low severity, real, and
one line of fix or one line of docs either way. See F6.

---

## 4. Keep-copy (`.refdes/copies/`)

A successful keep, on the same real datasheet:

```
$ refdes fetch
fetched  https://www.ti.com/lit/ds/symlink/tps62913.pdf  sha256=6b27cbc00d3d...  kept
1 citation(s) processed, 0 failed

$ ls .refdes/copies/
6b27cbc00d3de5f5b838cbab15a37c5b136b835e43fdaf98bac290015b862bc5.pdf
```

Content-addressed by sha256 with the extension preserved from the URL, exactly
as `docs/markdown.md:428-429` describes. Lockfile gains `kept_copy: true`.
`check` is clean, `audit` says `ok  kept`, and the rendered citations table row
reads:

```
 | ok | https://www.ti.com/lit/ds/symlink/tps62913.pdf | CMP-PWR-001 | copied | 2026-10-01T08:11:25Z | 6b27cbc00d3d… |
```

which is the `pinned/kept`/`fetched`/`sha256` set `docs/output.md:296` promises.

**Deleting the copy** (`rm .refdes/copies/*.pdf`):

```
$ refdes check
WARNING items/components/power.yaml:2 [CMP-PWR-001] — local copy of https://www.ti.com/lit/ds/symlink/tps62913.pdf is missing at .refdes/copies/6b27cbc….pdf
1 items, 0 errors, 1 warnings
exit 0

$ refdes build --require-citations
ERROR   items/components/power.yaml:2 [CMP-PWR-001] — local copy of … is missing at …
build completed with errors (use --keep-going to exit 0)
exit 1

$ refdes audit
    cache_missing  kept       cited by CMP-PWR-001

$ refdes release rel-a
release 'rel-a' blocked -- not stamped:
  pass     draft_items
  pass     unpinned_citations
  FAIL     missing_kept_copies  CMP-PWR-001
  pass     uncovered_requirements
  skipped  unverified_requirements
  skipped  info_check_failures
  pass     unaccepted_board_moves
  pass     unaccepted_workspace_moves
exit 1
```

The whole chain is right: warning at `check` (soft, per
`docs/markdown.md:445`), error at `build --require-citations`, `cache_missing`
in `audit`, and the release gate's `missing_kept_copies` rule fires naming the
item — the rule `docs/lifecycle.md:52` describes. The one blemish is in the
audit row: **`pin` still reads `kept` while the blob is gone**. So the two
columns *do* contradict each other here, which `docs/cli-reference.md:546`
explicitly promises they never do ("The two columns are independent facts about
the same pin, so they never contradict each other"). Low severity, but it is a
direct contradiction of a sentence in the docs, and it is the sentence run 3's
L-e finding was about. See F7.

**Flipping `keep_copy: true` → `false` and re-pinning** updates the lockfile to
`kept_copy: false` and the site link switches to `hash-only`, but the 6 MB blob
**stays on disk**. Same class as F6.

**Inconsistent `keep_copy:` across two items citing one path** is caught, with
the exact wording `docs/markdown.md:431` promises:

```
$ refdes check
WARNING <project> — citation 'https://www.ti.com/lit/ds/symlink/tps62913.pdf' is cited with inconsistent keep_copy: flags across CMP-PWR-001, CMP-PWR-002 -- pick one so the keep-a-copy decision is unambiguous
2 items, 0 errors, 1 warnings
```

`fetch` picks `true` and keeps the copy. Sensible resolution of an ambiguous
declaration; the warning is the point.

### Section resolution, as a bonus (it is the only part of refdes that reads a PDF)

`pypdf` 6.19.0 is installed here. Against the real TI datasheet:

```
$ refdes fetch
FAILED  https://www.ti.com/lit/ds/symlink/tps62913.pdf: section 'Application and Implementation' (cited by CMP-PWR-001): no outline entry titled 'Application and Implementation'; closest outline titles: '8 Application and Implementation', '8.1 Application Information'
(minted 1 key(s) while loading)
fetched  https://www.ti.com/lit/ds/symlink/tps62913.pdf  sha256=6b27cbc00d3d...  kept
1 citation(s) processed, 1 failed
exit 1
```

**The pin still succeeded**, and the section failure is its own line and its own
non-zero exit — precisely the "a failed lookup does not undo the pin" rule at
`docs/markdown.md:374`. Matching exactly and case-sensitively, with the closest
titles offered, is `docs/markdown.md:352-354`.

```
$ refdes fetch          # section: '8 Application and Implementation' (the exact outline title)
fetched  https://www.ti.com/lit/ds/symlink/tps62913.pdf  sha256=6b27cbc00d3d...  kept
         section '8 Application and Implementation' -> page 22
1 citation(s) processed, 0 failed
exit 0
```

`sections:` + `sections_sha256:` recorded, `section_page: "22"` in
`index --compact`, and `index`'s notice on **stderr** so the JSON stays pipeable.

Also verified, and worth naming because it is the subtle one: **adding** a
`section:` to an already-pinned citation is resolved by a *plain* `fetch`, from
the bytes already on disk, with no network request — `skipped` on the pin line
and a `section … -> page 22` line underneath it, in 0.47 s. And a scoped
`fetch --update --item CMP-PWR-001` re-resolves sections belonging to an item
*outside* the scope (`8.1 Application Information`, cited by `CMP-PWR-002`) —
the asymmetry `docs/markdown.md:381-384` insists on, confirmed live.

A non-PDF with a `section:` is reported without a traceback, as
`docs/markdown.md:372` promises:

```
FAILED  http://127.0.0.1:8931/page.html: sections 'Anything' (cited by CMP-PWR-003): pypdf could not read the PDF: Stream has ended unexpectedly
```

…though pypdf's own two lines (`invalid pdf header: b'<html'`, `EOF marker not
found`) leak to stderr above it unprefixed. Cosmetic; see F8.

---

## 5. Scenario 5 — failure shapes

| Shape | Command | Verbatim | Exit |
|---|---|---|---|
| DNS failure | `refdes fetch` on `https://nonexistent-host-abc123.invalid/datasheet.pdf` | `FAILED  https://nonexistent-host-abc123.invalid/datasheet.pdf  <urlopen error [Errno -2] Name or service not known>` | 1 |
| Connection refused | `refdes fetch` on `http://127.0.0.1:9/x.pdf` | `FAILED  http://127.0.0.1:9/x.pdf  <urlopen error [Errno 111] Connection refused>` | 1 |
| Timeout | server sends 100 bytes then stalls | `FAILED  http://127.0.0.1:8933/stall  timed out` (at 30.4 s) | 1 |
| Non-PDF content type | `refdes fetch` on `https://example.com/` | `fetched  https://example.com/  sha256=7d3e61f8f627...  hash-only` — **pinned, no complaint** | 0 |
| Oversized | 26 MiB `application/octet-stream`, `keep_copy: false` | `fetched  http://127.0.0.1:8931/big.bin  sha256=6c77dcaff2b5...  hash-only`, `bytes: 27262976` | 0 |
| Oversized, kept | same, `keep_copy: true` | `fetched  … kept`, 27262976-byte blob written | 0 |

Four of six are honest. Two are gaps:

**The non-PDF content type is pinned as if it were a datasheet.** `refdes fetch`
on `https://example.com/` returned 713 bytes of HTML, hashed them, wrote
`sha256: 7d3e61f8f627…` into the lockfile, and reported `ok hash-only` in
`audit` — forever after, unless someone notices. Nothing in `fetch`'s path looks
at `Content-Type` or at the `%PDF-` magic number (I grepped: no `Content-Type`
string anywhere in `src/refdes/citations.py`). This is the shape of the most
realistic citation accident there is — a vendor 200s an HTML interstitial, a
captive portal, a login wall, and the pin records the wrong bytes with total
confidence. The `section:` path *does* notice, but only if a `section:` is
cited, and only at fetch time. See F3.

**There is no size cap, and the timeout is not documented.** `fetch_bytes`
(`src/refdes/citations.py:949`) is `urlopen(req, timeout=30.0).read()` — one
`read()` of the whole body into memory, no `Content-Length` check, no cap. The
26 MiB file went through in 0.49 s with no warning. I did **not** push this
further: a 2 GiB `Content-Length` would be `read()` into RAM in one gulp, and
`keep_copy: true` would then write it to disk too. The honest statement is that
refdes has no defence here at either layer, and I declined to fill the disk to
prove it. Note the contrast: `src/refdes/sources.py:525` sets
`MAX_PDF_BYTES = 32 << 20` for the *local* PDF-reading path, so the codebase
does know how to cap a read — the network path just does not use the idea.

The 30 s timeout is real and correct (a stalled body aborts at 30.4 s, no lockfile
written), and it is a **socket** timeout, not a wall-clock budget: an origin
trickling 8 bytes every 5 s completed successfully at **40.4 s**, which a
wall-clock cap would have refused. That is the better behaviour — a slow big
datasheet is not a failure — but it does mean a hostile origin can keep a
`fetch` running as long as it keeps sending a byte every 29 s. Neither the 30 s
figure nor its socket semantics appear in `fetch --help` or in `docs/`. Low.

---

## 6. Scenario 6 — exit codes against `docs/cli-reference.md`'s table

The table at `docs/cli-reference.md:16-31` has exactly one `fetch` row, plus the
`--no-write` paragraph at line 11. I ran every `fetch` case it names, plus the
neighbouring commands a script would branch on:

| Command | Docs claim | Got |
|---|---|---|
| `fetch --item NOPE-1` | `1` (table, line 27) | `1` — `error: no item 'NOPE-1' in this project` |
| `fetch --path <url nothing cites>` | `1` (table, line 27) | `1` — `error: no citation in this project cites '…'` |
| `fetch --item <item with no citations:>` | `1` (table, line 27) | `1` — `error: item 'CMP-PWR-009' declares no citations` |
| `--no-write fetch` | `2`, refuses to run (line 11) | `2` — `--no-write: fetch writes the .refdes/citations.yaml lockfile and .refdes/copies/; refusing to run it under --no-write. Drop --no-write to run it for real.` |
| `check --require-citations` | flag does not exist on `check` (F2 in run 3) | `2`, `unrecognized arguments` — consistent |
| `build --refresh` | `--refresh` is a `check` flag (line 109) | `2`, `unrecognized arguments` — consistent |
| `fetch` with a failed citation | not in the table | `1` |
| `fetch` with all citations pinned | `0` | `0` |

**Every documented code is right.** The `--no-write` refusal is a one-sentence
refusal naming both paths it would write and the way out, which is exactly the
shape run 3 praised for `serve`.

Two things a script would trip on and the table does not cover:

- `refdes fetch --no-write` (flag *after* the subcommand) is an argparse error,
  exit `2` — because `--no-write` is a global option. The documented refusal is
  `--no-write fetch`. Same code, but a script that greps for the refusal text
  finds nothing.
- A failed fetch is exit `1`, which the table's preamble warns is also "errors
  found". A CI job that wants to distinguish "the network is down" from "the
  project is broken" has to read stderr. Same shape run 3 recorded for
  `history capture` vs `fetch --item`; nothing new, but this is the first run to
  put a *network* failure on code `1`.

---

## 7. Findings, ranked

### F1 — nothing makes `.refdes/copies/` and `.refdes/schema.json` gitignored, in a project `refdes init` created

**Severity: medium.** This is the only finding with teeth, and it is not a
`fetch` bug — it is a promise the docs make three times that the product does not
keep, in the one project layout the docs walk a newcomer through.

The docs say, three times:

- `docs/cli-reference.md:1534` — "`.refdes/copies/` | **no, gitignored** |
  Kept local copies of datasheet bytes…"
- `docs/cli-reference.md:1533` — "`.refdes/schema.json` | **no, gitignored** |…"
- `docs/markdown.md:429` — "content-addressed at `.refdes/copies/<sha256><ext>`
  — **gitignored**, not git LFS, not committed"
- `docs/standard-library.md:298` — "`.refdes/schema.json` — **gitignored**, not
  committed"

What `refdes init` actually writes is a `.gitignore` with **one** line in it:

```
$ cd fresh && refdes init
wrote refdes-project.yaml
wrote .vscode/settings.json (gitignored -- the yaml.schemas path in it names one checkout)
$ cat .gitignore
# Written by `refdes init`. The yaml.schemas path in this file is an
# absolute path into one checkout, so a committed copy hands every other
# clone a schema that resolves to nothing -- silently, in both tools.
# Editor settings you mean to share belong in a file you write yourself.
.vscode/settings.json
```

`_ensure_vscode_settings_gitignored` (`src/refdes/scaffold.py:99`) is the only
`.gitignore` writer in the product, and it addresses exactly one path. Nothing
else in `src/refdes/` writes or appends to a project's `.gitignore` — I grepped
for `gitignore` across `src/refdes/*.py` and the hits are all this one function
plus prose.

Reproduced end to end in a fresh `init` project, one `keep_copy: true` remote
citation, `git init`, `git add -A`:

```
$ git status --short
A  .gitignore
A  .refdes/citations.yaml
A  .refdes/copies/38ab6aa4e368….pdf          <-- 6 MB of a copyrighted TI datasheet
A  .refdes/schema.json                        <-- 1696 lines of generated JSON
A  items/components/power.yaml
A  refdes-project.yaml

$ git check-ignore -v .refdes/copies/*.pdf
NOT IGNORED
$ git check-ignore -v .refdes/schema.json
schema.json NOT IGNORED
```

This repo's own `.gitignore` has a 10-line comment block explaining exactly why
`.refdes/copies/` must be ignored — "manufacturer datasheets are generally
copyrighted" — and a separate `**/.refdes/schema.json` line. That reasoning is
correct and it is **not** in the product. `docs/getting-started.md:75` is the
nearest thing to a promise, and it only covers `.vscode/settings.json` — which
is precisely the one that *is* handled, so a reader has no reason to suspect the
other two are missing.

The consequences are the two the docs themselves name: a 6 MB copyrighted PDF
and a generated file that "would silently disagree with the project config"
land in history. Neither is catastrophic. Both are the kind of thing that is
much cheaper to prevent at `init` time than to unpick later.

Fix shape: extend `_ensure_vscode_settings_gitignored` into a general
append-only helper and have `init` add `.refdes/copies/` and
`.refdes/schema.json` with a comment, reusing the existing
`_gitignore_addresses_*` pattern set and the `append_ending` rule so a CRLF
gitignore does not grow an LF island. That is the shape already in
`scaffold.py`; the work is two more literals. A weaker alternative is to soften
the four doc sentences to "`gitignore` these yourself", but the docs already
argue the *why* at length, so making the tool do it is the better half.

This is also worth a line in `init`'s output, in the style of run 3's L-a/L-b:
today `init` names the one file it gitignored and is silent about the two it
did not.

### F2 — a wrong pinned hash on a *hash-only* remote citation is invisible to `check`, `build`, `audit` and `build --require-citations`

**Severity: medium.** This is the answer to the brief's scenario 3, and the
honest answer is "only `check --refresh` notices, and nothing offline can".

Pin a real TI datasheet with `keep_copy: false`, then set the recorded sha256 to
a wrong value:

```
$ refdes check                      → 1 items, 0 errors, 1 warnings   exit 0
$ refdes build                      → 1 items, 0 errors, 1 warnings   exit 0
$ refdes build --require-citations  → 1 items, 0 errors, 1 warnings   exit 0
$ refdes audit
    ok             hash-only  cited by CMP-PWR-001
$ refdes check --refresh
1 citation(s) drifted from their pinned hash:
    pinned    dead000…
    upstream  6b27cb…
exit 1
```

The offline silence is *by design* — `docs/markdown.md:435` says verification is
"checked at every `build` and `check`, **offline**", and for a hash-only remote
citation there is nothing offline to check against. I am not calling the silence
a bug. Two things make it a finding:

1. **`audit`'s `ok` overstates it.** `docs/output.md:415` defines `ok` as
   "Resolved — hash on file, and kept locally if `keep_copy: true` was
   declared". For a hash-only remote citation *no hash is on file*; nothing was
   resolved and nothing was checked. `ok` next to `hash-only` reads as
   "verified", and `audit` is the command a release reviewer runs.
2. **`build --require-citations` does not escalate it**, though the severity
   table at `docs/markdown.md:437-448` is the section a reader would consult to
   learn what `--require-citations` buys, and the one row that is *always* an
   error — "The local blob's hash no longer matches its recorded sha256" — is
   worded so generally that it reads as covering this case. It does not: that
   row is about the local blob, which a hash-only citation does not have.

A hand-corrupted lockfile is not a realistic user error, but a *merge* is: two
branches that both ran `fetch` produce a conflict in a file
`docs/cli-reference.md:1530` tells you to commit, and the resolution a human
picks ("take one side") can be wrong with nothing downstream to say so. Also
worth noting the lockfile's own header says **"Never hand-edit the sha256."**
(`src/refdes/citations.py:441`) — which is advice, not enforcement, and this
exercise's simulation is exactly the thing that line warns against.

Fix shape, cheapest first: (a) add a third `audit` `state` — `unverifiable` —
for a remote hash-only pin, so `audit` stops saying `ok` about something it did
not check, and print a pointer to `refdes check --refresh`; (b) amend the
`docs/markdown.md:447` row to say "the **kept** blob's hash"; (c) consider
whether `--require-citations` should at minimum warn when every citation in the
project is unverifiable offline.

### F3 — no size cap and no content-type check anywhere in the fetch path

**Severity: low-medium.** Two related gaps, both about what `fetch` will accept.

`fetch_bytes` (`src/refdes/citations.py:949-954`) is:

```python
def fetch_bytes(url: str, timeout: float = 30.0) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "refdes/fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()
```

One `read()`, whole body, into memory. No `Content-Length` inspection, no cap,
no `Content-Type` check, no `%PDF-` sniff. Confirmed live: a 26 MiB
`application/octet-stream` pinned in 0.49 s with no warning and
`bytes: 27262976` recorded as though that were normal; `https://example.com/`
pinned as 713 bytes of HTML with `sha256: 7d3e61f8f627…` and reported
`ok hash-only` in `audit` thereafter.

The non-PDF case is the one with real user consequence: a vendor 200s an HTML
interstitial or a captive portal, and the wrong bytes are pinned with total
confidence and no diagnostic, forever. The severity table in
`docs/markdown.md:437-448` has no row for it either.

The size case has no consequence in this exercise — I stopped at 26 MiB, as the
brief asked, and declined to fill the disk. The finding is that there is nothing
to stop it, and the contrast with `src/refdes/sources.py:525`
(`MAX_PDF_BYTES = 32 << 20` for the local PDF path) shows the codebase already
has the idiom.

Fix shape: a `Content-Length` pre-check against a named cap (say 64 MiB) *and* a
streamed read that aborts past it, so a lying `Content-Length` does not help;
plus a content-type/`%PDF-` check that at minimum *warns* rather than pinning
silently. Whether a non-PDF should be refused outright is a judgement call —
citations can legitimately point at non-PDF documents — so a warning that names
the observed type and says "if this is not what you meant to cite, the pin is
wrong" is the safe shape. Both belong in the severity table.

### F4 — a network failure during `check --refresh` is a warning with exit 0, and the drift/failure distinction is undocumented

**Severity: low.** `check --refresh` is the drift scanner, and it treats the two
things that can go wrong very differently — correctly, and without saying so.

Pinned URL, upstream now 404:

```
$ refdes check --refresh
WARNING <project> — could not refresh http://127.0.0.1:8931/a.pdf: HTTP Error 404: Not Found
1 items, 0 errors, 1 warnings
exit 0
```

Same with the origin stopped: `WARNING <project> — could not refresh …: <urlopen
error [Errno 111] Connection refused>`, exit `0`. Whereas genuine drift exits
`1`. The code is deliberate and says so in the docstring
(`src/refdes/citations.py:1557-1560`: "A url that fails to fetch is reported as
a warning, not drift — drift means the bytes changed, not that the network
did"), and I agree with the reasoning: a laptop on a train should not report
drift.

But `docs/cli-reference.md:128-143` documents `--refresh` as "re-fetches each
pinned citation to a scratch buffer, compares hashes, and reports which items
cite anything that drifted" and then says "**Exits non-zero on drift, same as
on any other error.**" That last clause is the problem: a fetch failure *is* an
error by any ordinary reading, and it exits `0`. `docs/markdown.md:450-453`
has the same gap.

So a CI job running `refdes check --refresh` to guard against upstream datasheet
drift **goes green on total network failure**, and green on a datasheet that has
been deleted at the vendor. The `WARNING` line is the only signal, and a CI log
filter written against `ERROR` sees a pass. The exit code is a project decision
rather than a bug, so the cheap fix is documentation: say plainly that an
unreachable URL is a warning and exit `0`, name the line, and say that a drift
guard in CI therefore needs a separate reachability check (or that the warning
should be grepped). A better fix is an `--strict-refresh` that escalates
unreachable to an error, opt-in for CI, with the default left as-is.

### F5 — a malformed `.refdes/citations.yaml` is a raw `ValueError` traceback out of both `fetch` and `check`

**Severity: low.** Run 3's N1 was the same class: a green-looking workflow
producing a traceback. I found one left.

Replace the lockfile with a `citations:` key holding a list instead of a
mapping — the shape a bad merge or a bad hand-edit produces:

```
$ refdes fetch --update
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File ".../src/refdes/cli.py", line 2201, in main
    return args.func(args)
  File ".../src/refdes/cli.py", line 669, in cmd_fetch
    project, citations_mod.load_lockfile(project)
  File ".../src/refdes/citations.py", line 420, in load_lockfile
    return dict(data.get("citations") or {})
ValueError: dictionary update sequence element #0 has length 21; 2 is required
exit 1

$ refdes check
  ... same, via src/refdes/build.py:1335 in run_calcs ...
ValueError: dictionary update sequence element #0 has length 21; 2 is required
exit 1
```

`load_lockfile` (`src/refdes/citations.py:414-420`) assumes `citations:` is a
mapping and hands whatever it got to `dict()`. Compare the project's own config
loader, which is careful — `refdes check` on a `refdes-project.yaml` declaring
`standard.version: 99` gets
`configuration error: standard.version 99 does not exist for base 'hardware'
(available: ['v1', 'v2', 'v3'])` and exit `2` (verified). The lockfile is
machine-written and its own header says not to edit it, so the likelihood is
low; but it is a *committed* file (`docs/cli-reference.md:1530`), so a merge
conflict is a real route here, and the error message names an internal line
rather than the file the user has to fix.

Fix shape: catch `(ValueError, AttributeError, yaml.YAMLError)` in
`load_lockfile` and re-raise as the project's configuration-error channel naming
`.refdes/citations.yaml` and the expected shape, exit 2. Four lines.

### F6 — a superseded kept copy is never pruned, and flipping `keep_copy` off leaves the bytes

**Severity: low.** Two paths, one cause.

Pinned, upstream changed, `fetch --update`: the new blob is written and the old
one stays, silently, forever:

```
$ ls .refdes/copies/
38ab6aa4e368….pdf      <- current pin
cef3b030a937….pdf      <- superseded, invisible to check and audit
```

`check` and `audit` both report `ok kept`. Setting `keep_copy: false` and
re-pinning flips the lockfile to `kept_copy: false` and the site link to
`hash-only`, and leaves all 6 003 120 bytes of the TI datasheet in the working
tree. `docs/markdown.md:429` calls `.refdes/copies/` "content-addressed", which
is true, but says nothing about what happens to the old address. On a project
whose datasheets get revised — the entire reason `rev:` exists — this is a slow
disk leak of copyrighted bytes.

Not a correctness problem: content addressing means a stale blob can never be
mistaken for the current one, which is the property that matters. Fix shape is
either a prune pass in `fetch` (delete blobs under `.refdes/copies/` that no
live record names, after a successful write) or one sentence in the docs saying
they accumulate and how to clear them. The prune is the better half, and it
has the same "write only after the pin is durable" ordering the code already
respects for the local-file source-extraction path.

### F7 — `audit` prints `pin: kept` while the kept copy is missing, contradicting the docs' "never contradict each other"

**Severity: low.** Delete the blob:

```
$ refdes audit
Citations:
  https://www.ti.com/lit/ds/symlink/tps62913.pdf
    cache_missing  kept       cited by CMP-PWR-001
```

`cache_missing` is right. `kept` is not — the bytes are gone. And
`docs/cli-reference.md:546` says, of exactly these two columns: "The two columns
are independent facts about the same pin, so **they never contradict each
other**: an unpinned citation has no hash to be `hash-only` about, and says
`no pin`." The parenthetical explains the one case the author thought of
(unpinned) and the sentence is stated generally enough that a reader will rely on
it. It is the third state this pair can be in, and it is the one where they
disagree.

This is the same audit line run 3's L-e called out as *fixed* ("`audit` calls an
unpinned citation `hash-only`" — `unpinned  no pin` is indeed fixed, and holds).
This is the adjacent case it did not cover.

Fix shape: one line — when `state` is `cache_missing`, print `no copy` (or
blank) in the `pin` column instead of `kept`, since `pin` is documented as what
the *lockfile* holds and the lockfile's `kept_copy: true` is precisely what is
now lying.

### F8 — three small things, recorded once

- **`FAILED` lines go to stderr, `fetched`/`skipped`/summary to stdout, and
  `fetch`'s docs never say so.** `refdes fetch > log` captures every success and
  every failure count but no failure text. Consistent with
  `docs/cli-reference.md:104`'s convention for `check`; just undocumented for
  `fetch`, and the marker a script would grep for is the word `FAILED` rather
  than `ERROR`. *(§2)*
- **pypdf's own parse chatter leaks unprefixed.** On a `section:` against a
  non-PDF: `invalid pdf header: b'<html'` and `EOF marker not found` print to
  stderr *above* refdes's own well-formed `FAILED …` line. The line itself is
  right — `docs/markdown.md:372`'s "the file and pypdf's own message, never a
  traceback" — but the two extra lines have no prefix, so a log filter keyed on
  `FAILED`/`ERROR` sees three lines where there is one. *(§4)*
- **`fetch --no-write` after the subcommand** is an argparse error (exit 2)
  because `--no-write` is global; the documented refusal is `--no-write fetch`
  (also exit 2, with a proper sentence). Same code, so no table change needed,
  but a script grepping for the refusal text finds nothing. *(§6)*

---

## 8. What worked cleanly

Every item here was verified, not inferred.

- **The pin is stable and re-fetching is exactly idempotent.** Same datasheet,
  same `sha256` and `bytes` across this run and run 3's, three weeks of clock
  time apart in wall terms. A plain re-run prints `skipped`, makes **no network
  request** (confirmed in the origin's access log), takes 0.37 s, and leaves the
  lockfile **byte-identical** — no `fetched:` churn. A `fetch` in a pre-commit
  hook cannot produce a diff. That is the property everything else rests on and
  it holds cleanly.
- **`check --refresh` writes nothing.** Lockfile and `.refdes/copies/` both
  byte-identical across a run, as `docs/cli-reference.md:109` promises.
- **A failed fetch never damages a good pin.** `--update` against a 404, a
  connection refused mid-chain, a mid-body disconnect: in every case the old
  `sha256`, `bytes`, `kept_copy` and blob are exactly as they were. And a fetch
  that fails on its *only* citation writes no lockfile at all. This is the
  single most important failure property and it is correct in all six shapes I
  tried.
- **The severity ladder is exactly the documented one.** `keep_copy: true` with
  a deleted blob: warning at `check` (exit 0), error at
  `build --require-citations` (exit 1), `cache_missing` in `audit`, and
  `release` blocked by the `missing_kept_copies` rule naming the item. A
  *corrupt* blob (truncated to 1000 of 6 003 120 bytes) is an error at plain
  `check` — `docs/markdown.md:447`'s "**error, always**", and the sharpest
  promise in the table, kept.
- **The release gate fires on citation state, both ways.**
  `missing_kept_copies CMP-PWR-001` for a deleted blob;
  `unpinned_citations CMP-PWR-001` for a never-pinned 404. Both with exit 1 and
  the eight-rule listing `release --help` promises (run 3's F3).
- **Redirects just work**, in both directions and through a chain: local 302→301→200
  and a real `http://www.ti.com` → `https://` → 2.5 MB PDF. Keyed on the cited
  URL, with the URL's extension preserved for the kept-copy filename — which is
  what makes a real vendor "symlink" URL land as `<sha256>.pdf`.
- **The exit-code table is true in every row that names `fetch`.** All three
  refusals are exit `1` with a single legible line; `--no-write fetch` is exit
  `2` with a refusal that names both files it would write and the way out; the
  two flags that do not exist (`check --require-citations`, `build --refresh`)
  are argparse errors at exit `2`, consistent with what the docs now say.
- **One bad citation does not stop the good ones**, and `audit` sorts the
  results into a coherent table with two columns that agree (`unpinned`/`no pin`,
  `ok`/`hash-only`, `ok`/`kept`) in every state except the one F7 is about.
- **Content-addressing earns its keep.** A wrong pin with `keep_copy: true` is
  *reported* as `cache_missing` — a wrong hash cannot resolve to the wrong blob,
  because the filename is the hash. I tried to make it and could not.
- **`section:` resolution is the best-documented feature in the tool and matches
  its documentation line for line**, against a real vendor PDF: exact
  case-sensitive matching, "closest outline titles" on a miss, the pin surviving
  a failed lookup, its own `FAILED` line and its own non-zero exit, the
  `sections`/`sections_sha256` pair, `section_page` in `index --compact` with
  the notice on stderr so the JSON stays pipeable — plus the two subtle
  behaviours, both confirmed live: a **newly added** `section:` is resolved by a
  *plain* `fetch` from bytes already on disk with no network request, and a
  scoped `fetch --update --item A` re-resolves sections cited by item **B**.
- **Politeness is deliberate.** `User-Agent: refdes/fetch` and
  `Accept-Encoding: identity` are set on every request — the latter meaning the
  pinned hash is over the bytes on the wire, with no transparent gzip, which is
  the right call for a content-addressed pin. No HEAD-then-GET dance, no
  retries, one request per citation per run (confirmed in access logs).
- **The content type is never *silently mangled*.** Chunked
  `Transfer-Encoding` with no `Content-Length` pins correctly (`bytes: 35` for
  a 35-byte body), so a server that refuses to send a length is not a failure.
- **Time-varying content is handled without a config knob**, which is the right
  call: the 30 s socket timeout correctly refuses a stalled body (30.4 s, no
  lockfile written) while *accepting* a slow trickle that completes at 40.4 s.
  A wall-clock budget would have got that one wrong.

---

## 9. What I could not test, and why

- **A datasheet that is not a PDF, fetched and *used*.** I confirmed a non-PDF
  is pinned without complaint (F3), but I did not build a site around one and
  inspect the rendered link, so I am not claiming anything about what a
  published page does with it.
- **A genuinely >26 MiB download.** Stopped at 26 MiB per the brief. I can say
  there is no cap in the code path; I am **not** claiming what a multi-gigabyte
  body does to memory or the disk, because I did not run one.
- **Real `Last-Modified`/`ETag` conditional-request behaviour against a real
  CDN.** I used a local origin advertising both, which is enough to establish
  that refdes sends neither validator and records neither header — but no vendor
  CDN's real caching semantics were exercised.
- **`pypdf` missing.** `pypdf` 6.19.0 is installed, so the
  `pip install refdes[pdf]` row of `docs/markdown.md:371` is the one `section:`
  failure shape I did not reach. I did not uninstall it.
- **A PDF with a genuinely ambiguous duplicate outline title**, and the
  "title gone in a new revision under `--update`" line
  (`docs/markdown.md:370`) — both need a synthetic PDF with a crafted outline,
  which is more work than the payoff and belongs with the source-picker work run
  3 §5 item 2 already proposed.
- **Windows and macOS.** No line-ending or case-insensitivity exposure on the
  lockfile, which `src/refdes/citations.py:451-454` says is deliberately handled
  by writing through `textio`.
- **Anything requiring a browser or VS Code.** Not in scope, not available.
- **`refdes serve`'s source-picker accept path**, which is the second writer of
  `.refdes/citations.yaml` (`src/refdes/citations.py:427-433` says it must
  produce byte-identical formatting). Not exercised; noted because F5 and F6
  both touch that file and a fix should keep the two writers agreeing.

---

## Appendix — how to reproduce this run

All under `.scratch/rf/` in this worktree; nothing outside it was written, and
no `git` ran inside any test project.

```bash
# the wrapper (the refdes on PATH is a broken editable install)
.scratch/rd            # PYTHONPATH=<worktree>/src python -m refdes.cli "$@"

# pristine project:  .scratch/rf/rf-pristine   (refdes init + one component
#                     with one remote citation); each scenario is
#   rm -rf .scratch/rf/<name> && cp -r .scratch/rf/rf-pristine .scratch/rf/<name>

# controllable local origin (redirects, 404-after-pin, non-PDF, oversized,
# stalled body, mid-body disconnect, chunked encoding, ETag/Last-Modified)
.scratch/rf/srv/origin.py     # 127.0.0.1:8931, routes /a.pdf /redir /redir2
                              # /gone.pdf /page.html /big.bin /slow.pdf
                              # flip files/hide-a to make /a.pdf start 404ing
                              # touch files/allow-big to enable /big.bin
```

Project inventory under `.scratch/rf/`: `rf-pristine`, `rf` (the pin),
`rf-pristine`→`r404` (real ti.com 404 + real redirect), `rredir` (redirect chain,
then 404 after pin), `rfail` (DNS / refused / non-PDF), `rto` (socket timeout vs
trickle), `rto2` (hard stall), `rabort` (mid-body disconnect), `rchunk`,
`rloop2` (infinite redirect), `rq`/`rq2` (inconsistent `keep_copy`, query
strings), `rkeep`/`rflip`/`rsec`/`rsec2`/`rsec3`/`rscope` (keep-copy and section
resolution), `rgate` (deleted copy → gate), `rpart`/`rcorrupt`/`rsha` (truncated
and corrupt blobs), `rwrong`/`rfetch` (hand-edited hashes), `rdead` (404 after a
successful pin), `rstale` (upstream byte change), `rgi` (fresh `init` + `git
init`, for F1), `rbad` (malformed lockfile, F5), `rexit`/`rver` (exit codes),
`rnone` (no citations), `rinit`, `gitprobe`.