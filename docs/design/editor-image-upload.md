Status: proposed (drafted 2026-09-25) — a design spec, not a decision. It picks
up the one deferred item of `docs/design/browser-editor.md` that was left open
with no design behind it (§1). Every open question in §15 carries a
recommendation, and each recommendation is the default if Jared lets it stand
unanswered. §16 records what was considered and rejected. Nothing here is
implemented, and §2's claims about current behaviour were each checked against
the code or a run, with the citation at the claim.

Update: §15.1 is answered — Jared decided on 2026-09-25 that images are build
inputs, and that slice is implemented: `serve.state.project_inputs` walks
every `site.assets:` directory into the watched set and the revision.
Sections 2, 8, 12, 14 and 16 carry notes where the decision superseded them.

Update: §15.8 is answered too — Jared decided on 2026-09-26: no copy, in
either direction. Bringing in bytes from outside the project is upload (§5–§7),
which always writes into the project; there is no "leave it where it is"
mode for a truly external file, since `build.py` has no way to resolve a
path outside the project tree and doing so would break the build on any
other machine or in CI. And picking an *existing* project image that lives in
a directory other than the current item's own was considered — the toggle
would be "duplicate the bytes into my directory" vs "reference it in place" —
and rejected too: it doesn't buy anything the existing bare-name
`site.assets:` search doesn't already give you, and it adds a choice an
author has to understand for no real gain. So Phase 0's picker (§17) needs no
copy logic at all: it always references an image wherever it already lives.

Update: §15.6 is answered too — Jared decided on 2026-09-25 to take the
`HASH_FORMAT` bump, and it is in: format 5 folds each referenced image's
content digest into its owner's content hash, so a swapped image breaks a
seal loudly (§2, §10, §15.6; plan in `in-prog-logs/hash-images.md`).
The upload feature itself is still unimplemented.

Update: **Phase 0 has shipped** (2026-09-25) — the picker, alone and
independently, as §17's row 0 scopes it. `GET /api/images?item=<handle>`
(`serve/api.py` `_images`) lists the images under the declared `site.assets:`
directories, using the same walk `state.asset_files` watches and
`build.collect_static_assets` publishes, and returns for each the exact
reference to insert, relative to that item's own source file;
`serve/static/images.js` lists them, filters them, and inserts one into the
body draft through the existing `setDraftBody` path, so the ordinary Save
posts an ordinary `set_body`. No upload, no `POST /api/assets`, no Phase 1 or
later. Pinned by `tests/test_serve_images.py` and the static checks in
`tests/test_serve_static.py`.

Two things §2 and §16.10 turned out to make easy, verified by running rather
than reading: the thumbnail needs **no new read endpoint** at all — a file
under a declared asset directory is identity-mapped in `project.assets` by
`collect_static_assets`, so the build's own `assets/<rel>` path is already
served by the existing `/preview/` surface under the session cookie, and the
picker just uses the build's answer — and a filename markdown would
percent-encode (a space, a non-ASCII character) is not referenceable by any
spelling today, because the build resolves the *rendered* `src` without
decoding it, so the picker reports those rows as not insertable rather than
handing over text the save would refuse.

# Image upload in the browser editor, and what a binary conflict is

## 1. The deferred item

`docs/design/browser-editor.md` deferred image upload twice and never designed
it. In "Deferred": "Uploading or managing image files. The body editor can
reference existing project files in the first version; upload is a later
capability" (`docs/design/browser-editor.md:70-71`). In "Later": "Image
upload/copy and binary conflict policy" (`docs/design/browser-editor.md:1072`).
The reason given at design time was a list of problems rather than answers
(`docs/design/browser-editor.md:419-422`):

> upload introduces destination choice, overwrite handling, binary conflicts,
> extension/MIME policy, and git status changes unrelated to the item
> transaction (`docs/design/browser-editor.md:419-422`)

Five named problems, none resolved. This document resolves them, and finds a
sixth that the original list missed: an upload is not a local operation. A new
file can break the build of a document the author never opened (§9), and it can
change what a sealed entry shows without breaking its seal (§10). Those two are
why this is a design question and not a form field.

## 2. What exists today

Everything below was verified against the current tree by reading the cited
lines, or by running the code.

**Images are queries with a pinned first choice.** A local `<img src>` resolves
relative to its own source file, is copied into `_site/assets/`, and its leaf
gains a content hash (`docs/markdown.md:93-110`, `build.py:2137`
`_hashed_leaf`, `build.py:2202` `_process_images`). A `src` with no separator
that fails that lookup is then searched across the declared `site.assets:`
directories (`build.py:2147` `_search_image_src`), and two matches is a build
error naming every candidate (`build.py:2183`) — never a tie-break. The
relative lookup runs first and always wins (`docs/markdown.md:139`).

**A picker was in v1 and does not exist.** `docs/design/browser-editor.md:1109`
lists "Existing images by picker; no upload" among what v1 must deliver. There
is no picker: a search of `src/refdes/serve/static/` for `image`, `asset`,
`figure`, or `insert` finds nothing. The body control is a plain textarea with
no insertion helper of any kind. So the boundary drawn at `:419-422` was never
actually crossed in either direction — upload is absent, and so is the thing
that was supposed to stand in for it. *(Updated 2026-09-25: the second half is
no longer true. Phase 0 landed — `serve/static/images.js` and
`GET /api/images`; the body control now has an insertion helper, and the
upload half of the boundary is still uncrossed.)*

**The delta gate already refuses a dangling image, and nothing can pre-stage
one.** A body edit whose text references a file that is not on disk is blocked
today. Running `apply_edit` with `SetBody("![curve](figures/curve.png)")`
against a project with no such file returns `Invalid: blocked: the edit would
leave 1 error(s): image src 'figures/curve.png' does not exist`, and the file on
disk is unchanged. The obvious workaround — put the image in the in-memory
overlay so the candidate build resolves it — is not available: `source_overlay`
is `dict[str, str]` (`model.py:730`), `parse.read_source` reads text
(`parse.py:799`), and `_is_source_name` only admits `.md`, `.yaml`, `.yml`
(`parse.py:812`). An overlay entry naming a `.png` path is inert: the same
candidate build still reports the image missing and `project.assets` stays
empty. **The bytes must be on disk before any body edit referencing them can
pass the gate.** That single fact fixes the ordering of every design below.

**Images are semantic inputs.** *(Updated 2026-09-25: this is what §15.1
settled, and the slice that changed it is in.)* `serve.state.project_inputs`
returns the two config files, item sources, page `.md` files, `.refdes/`
state, imported artifacts, **and every file under a declared `site.assets:`
directory** (`serve/state.py`, `_asset_files`). The asset-directory walk is
the whole set rather than the referenced subset, because resolution is a query
over those directories (§9.1 and §9.2 are the consequences of that for
uploads). Two consequences, both load-bearing:

- an image change moves the revision token, so a body save can detect that an
  image it references was swapped under it; and
- `refresh()` compares signatures over those same paths, so **adding,
  replacing, or deleting an image rebuilds the preview** with no intervening
  body save. A file outside every declared asset directory is still not an
  input, and the per-tick cost stays a `(mtime, size)` stat until something
  actually differs.

**The write path has the right primitives already.** `apply_edit` is the one
entry point, and a refusal is a value, not an exception
(`serve/edit.py:1-20`). `_atomic_replace` writes a same-directory temp, fsyncs,
`os.replace`s, re-reads, and compares bytes (`serve/edit.py:475`).
`_atomic_create` does the same and then `os.link`s, which **fails rather than
replace** (`serve/edit.py:941-973`) — a create-must-not-exist write, already
written, already used for new item files. `_rollback` restores the previous
bytes or unlinks a file that did not exist before (`serve/edit.py:975-986`).
What is missing is the journal: the module docstring says "the design's
transaction model, minus the journal, which is a later slice"
(`serve/edit.py:12-13`), so a two-file operation is recoverable-in-principle but
not recoverable today.

**The HTTP gate is JSON-only, 1 MiB.** `/api/` requires the launch token, then
for POST an `Origin` match, then `Content-Type` exactly `application/json` or
415, then a `Content-Length` present and ≤ `MAX_BODY_BYTES = 1 MiB` or 411/413
(`serve/server.py:497-519`, `serve/server.py:36`). The limit is checked against
the header before any byte is read.

**CSP already permits a local preview, and the preview already serves binaries.**
The editor's CSP is `img-src 'self' data:` (`serve/security.py:70-82`), so a
`FileReader` data-URL preview of a picked file works in the editor shell today
with no change. The preview surface serves any file below the current generation
with `mimetypes.guess_type` and `PREVIEW_CSP` (`serve/server.py:436-453`), gated
by the session cookie rather than the header — which matters because an `<img>`
tag cannot send a header. No new read endpoint is needed to show an uploaded
image, and the design's ban on a generic file-read endpoint
(`docs/design/browser-editor.md:938-940`) stays intact.

**Two precedents for writing bytes into a project.** `citations.py` already
writes binary blobs into a project at `.refdes/copies/<sha256><ext>`
(`citations.py:63`), gitignored (`.gitignore:27`) because those bytes are
someone else's copyrighted datasheet. And `citations.case_mismatch`
(`citations.py:185-207`) already detects a path that exists only
case-insensitively — "a path that builds on this machine and vanishes in a
Linux CI checkout". Both are directly reusable here.

**A seal does not cover image bytes.** The hash payload carries fields and the
normalized body text (`build.py:1427-1490`); the body text contains the
`![alt](path)` string, not the bytes it points at. Replacing the file behind a
sealed entry's image changes what that sealed record displays and leaves the
seal verifying. **Update (2026-09-25, §15.6 decided):** no longer true —
`HASH_FORMAT` 5 puts each referenced image's content digest into its owner's
content hash, so swapping the bytes behind a sealed entry's image now breaks
the seal loudly. `is_sealed` (`seal.py:199`) is the predicate; `apply_edit`
already refuses a sealed item under the lock (`serve/edit.py:233`).

## 3. Proposal in one page

Six decisions, and the interesting ones are 4 and 5.

1. **(A) Destination** (§4) — the item's own source directory by default, an
   explicit project-relative override always available, and never a
   `site.assets:` directory unless the author names it.
2. **(B) Naming** (§5) — the author's filename, sanitized to a single safe
   segment. Collisions refuse; nothing is silently renamed, suffixed, or
   overwritten. Identical bytes already at the target are a no-op write.
3. **(C) Limits** (§6) — sniff the bytes, not the extension and not the
   client's `Content-Type`. PNG, JPEG, GIF, WebP in v1; SVG refused.
   8 MiB per file, checked against `Content-Length` before reading.
4. **(D) The reference is inserted by the client into the draft, and the upload
   never touches a body** (§7). Upload returns a path; the ordinary Save writes
   the text. Upload-then-save ordering is not a preference, it is forced by the
   gate (§2).
5. **(E) A binary conflict is three different things** (§8, §9): the bytes at the
   destination moved (`expected_hash`, the binary `expected_revision`), the leaf
   name now being ambiguous on the search path, and the new file capturing an
   existing bare-name reference. The last two are conflicts against *other
   documents*, and both are computable before the write.
6. **(F) One new endpoint, same gate** (§11) — `POST /api/assets`, raw bytes,
   token + `Origin` + Host as every other mutation. No multipart.

## 4. Where the bytes land

**Recommended default: the directory of the item's own source file.** Uploading
`curve.png` while editing `items/decisions/dec-001.md` lands
`items/decisions/curve.png`, and the inserted reference is `![…](curve.png)`.

Three reasons, in order of weight.

- **It is the one destination whose reference can never drift.** The relative
  lookup runs first and always wins (`docs/markdown.md:139`), so a
  beside-the-source file is immune to the ambiguity error and to whatever
  directories `site.assets:` happens to declare now or later. `docs/markdown.md`
  already tells authors this: "If you want the reference pinned so it can never
  drift, write the relative path" (`docs/markdown.md:163-166`).
- **It cannot collide with the template's own asset names.**
  `_copy_project_assets` refuses a project asset whose destination top-level
  name is one the template owns (`style.css`, `app.js`, `theme.css`)
  (`render.py:747-774`). That guard exists because `site.assets:` destinations
  are mirrored from the asset directory's own name; a default inside the item
  tree keeps the collision far away rather than relying on the guard.
- **It is where the author would have put it by hand.** `docs/markdown.md:99-102`
  describes `items/decisions/figures/pattern.png` as the common case.

An explicit override is always available: any project-relative directory that
passes the same segment checks as every other path in the editor
(`security.safe_relative_parts`, `serve/security.py:106` — no `..`, no
backslash, no drive or ADS colon, no NUL, no reserved Windows device name),
resolved with real-path containment so a symlinked directory cannot point out of
the project (`citations.classify` does exactly this at `citations.py:175-181`).

Two destinations are refused outright:

- **Anything under `.refdes/`.** That directory is refdes's own state, and
  `.refdes/copies/` is gitignored precisely because those bytes are not the
  project's to publish (`citations.py:63`, `.gitignore:27`). An uploaded image
  is the author's own content and belongs in the tracked tree, where a review
  sees it.
- **A `site.assets:` directory, unless the author names it explicitly.** The
  default must not be there, because writing into a declared search directory is
  the one thing that can break someone else's document (§9.1). When an author
  does name one — a real project layout, `figures/` shared across items — the
  upload runs the §9 checks first and refuses on what it finds.

Files inside `items/` are inert to the parser: `_is_source_name` admits only
`.md`, `.yaml`, `.yml` (`parse.py:812`), so an image in the item tree never
becomes an item and never moves the revision (§2).

## 5. Naming and collision

**The name is the author's filename, reduced to one safe segment.** The client
sends a name; the server takes its basename, applies `safe_relative_parts` to
that single segment, and refuses if it fails. A client-supplied path is never
joined to anything — the destination directory comes from the request's `dest`
parameter, validated separately, so a `name` of `../../x.png` is a refusal
rather than a normalization puzzle.

**Collisions refuse. Nothing is renamed for the author.** Three cases, three
answers:

| On-disk state | Result |
|---|---|
| Target absent | Write. |
| Target present, bytes identical (sha256 equal) | **No write.** Return the existing path and hash; the client inserts the reference anyway. Re-dropping the same file is idempotent, not a conflict. |
| Target present, bytes differ | **Refuse.** Name the existing path, its size and hash, and offer the two real choices: replace it (§8) or pick another name. |

No silent `-1` suffix. A suffixed name is a guess about what the author meant,
and it lands in a committed file whose name they did not choose — the same
objection `_search_image_src` makes to first-match ("every such rule is
invisible to whoever reads the document", `docs/markdown.md:153-154`). A
*suggested* alternative name in the refusal is fine, because the author picks
it; a generated one applied without asking is not.

**Case-only collisions refuse too.** `curve.png` against an existing
`Curve.png` on Windows is a write that appears to succeed and then produces two
paths that a Linux checkout resolves differently. `citations.case_mismatch`
(`citations.py:185-207`) already answers "does this exist only
case-insensitively?" and is the check to reuse.

## 6. Size and type limits

**Type is decided by the bytes.** Read the first few bytes and match a
signature; the extension must agree with the signature, and the client's
`Content-Type` is ignored entirely — it is attacker-controlled text, and the
editor's own posture is "reject unexpected content types"
(`docs/design/browser-editor.md:941`).

| Accept | Signature |
|---|---|
| PNG | `89 50 4E 47 0D 0A 1A 0A` |
| JPEG | `FF D8 FF` |
| GIF | `47 49 46 38 37 61` / `47 49 46 39 61` |
| WebP | `RIFF????WEBP` |

**SVG is refused in v1**, and the reason is the CSP, not a file-type prejudice.
An SVG is an XML document that can carry script. It reaches a browser through
the preview surface, whose CSP is `default-src 'self'; script-src 'self'`
(`serve/security.py:85-95`) — no `'unsafe-inline'`, so an inline script in an
uploaded SVG does not execute. That is the *only* thing standing between an
uploaded SVG and a same-origin script, and a design that accepts a
script-capable format because a header happens to defang it is a design with one
misconfiguration in it. The other reason is that SVG has no size bound that
correlates with anything: a 40 MB text file is a legal SVG. §15.3 leaves
revisiting it open.

**Size: 8 MiB per file, recommended, checked before reading.** The existing
pattern is right — compare `Content-Length` to the cap and answer 413 without
reading a byte (`serve/server.py:511-513`). The upload route needs its own,
larger cap than the shared `MAX_BODY_BYTES` of 1 MiB (`serve/server.py:36`),
because a full-page schematic screenshot clears 1 MiB routinely. The cap is
enforced twice: against the header, and again against bytes actually read, so a
lying `Content-Length` does not buy an unbounded read.

No aggregate quota, no per-day budget, no image count limit. This server has one
author on loopback (§15.9).

## 7. How the reference gets into the body

**The upload endpoint writes bytes and returns a path. It does not touch any
item's body, and it is not the thing that inserts text.**

```
POST /api/assets?dest=items/decisions&name=curve.png   → 200
{ "rel": "items/decisions/curve.png",
  "from_source": "curve.png",
  "hash": "sha256:…",
  "bytes": 41218 }
```

The client takes `from_source` — `rel` rewritten relative to the item's source
file — and inserts `![curve](curve.png)` into the draft textarea at the caret.
The author edits the alt text, moves the line, or deletes it. The text reaches
disk through the ordinary `POST /api/item/<ref>/edit` `set_body`, through
`apply_edit`, with the ordinary `expected_revision` and the ordinary delta gate.

Why not have the server patch the body? Because the author's unsaved draft is
the current truth about that body, and it exists only in the browser. A
server-side insertion would either race that draft or have to be sent up with
the image — and sending it up with the image means validating a body that
references a file the candidate build cannot see (§2), which is exactly the
failure the gate reports. Splitting the two operations is not laziness about
transactions; it is the only ordering the existing gate admits.

**The ordering is therefore forced, and the spec says so out loud:** upload,
then insert, then save. A client that saves first gets a refusal that already
names the missing file, which is a correct and legible outcome.

**Alt text defaults to the filename stem** (`curve.png` → `![curve](…)`) and is
never left empty, because an empty `alt` is a silent accessibility failure and
the author is about to be able to see it. No `{width=… caption=… id=…}` suffix
is generated: figure ids are a project-wide unique namespace and a duplicate is
a build error, so auto-generating one is a way to introduce collisions the
author did not choose.

**Orphans are accepted, not cleaned up.** If the upload succeeds and the body
save never happens — the author cancels, the browser dies, the gate refuses for
an unrelated reason — an unreferenced file sits in the tree. It is invisible to
the build (nothing references it; `collect_static_assets` at `build.py:2622`
only bulk-copies declared asset directories, and a §4 default destination is
not one), visible in `git status`, and removable by hand. Auto-deleting it on a
failed save would mean the editor deleting files the author put there, which is
a strictly worse class of failure than a stray file in `git status` — and
without the journal (§2) there is no transaction to hang the deletion on
anyway. §15.5 leaves a later "unreferenced files" advisory open.

## 8. What "conflict" means for a binary

The editor's conflict model is content-hash based: the client holds a revision,
the server recomputes hashes of the semantic inputs under the write lock and
refuses on mismatch (`docs/design/browser-editor.md:776-798`,
`serve/edit.py:185` `file_revision`). Images are not in that set (§2), so they
need their own spelling of the same idea, and they need it at the upload
endpoint rather than the body endpoint.

**`expected_hash` is the binary `expected_revision`.** `sha256:` of the bytes
currently at the destination, or the empty string when the file does not exist.
A replace request carries it; the server takes the write lock, hashes the file
as it now is, and compares.

| Situation | Result |
|---|---|
| `expected_hash` matches the file on disk | Replace, atomically, via `_atomic_replace` (`serve/edit.py:475`), which re-reads and compares bytes after the write. |
| `expected_hash` does not match | **`Conflict`.** Nothing is written. |
| `expected_hash` empty, file exists | **`Conflict`** — the author asked to create; someone else got there first. |
| `expected_hash` present, file absent | **`Conflict`** — the file the author meant to replace is gone. |

**A binary conflict carries no diff.** The text conflict returns a unified diff
and offers keep-mine / keep-theirs / copy-by-hand
(`docs/design/browser-editor.md:776-798`). A diff of two PNGs is noise. The
binary conflict returns the facts an author can actually compare — path, size,
mtime, both hashes, and the count of items that reference it (§9.3) — and two
actions: **replace** (re-issue with the hash just returned) or **use the
existing file** (write nothing, insert the reference to what is already there).
There is no merge, for exactly the reason the text model refuses one: it would
produce a thing that looks fine and means something neither author wrote.

**Why images are in the revision token.** *(Superseded: §15.1 decided the
opposite on 2026-09-25, and `project_inputs` now walks the `site.assets:`
directories. What follows is the reasoning as drafted, kept because §9 and §10
still depend on the facts it names.)* Adding every image to `project_inputs`
means one image edit invalidates every open form in the project, and puts
megabytes of binary into the content hash. The hash is not computed on every
poll tick — the tick compares a `(mtime, size)` signature first and only
re-hashes when that differs (`serve/state.py`) — so the per-tick cost of the
decision is a stat per watched file. What the decision buys is the two
consequences of the old gap reversed: an external swap of an image now moves
the revision, and an upload rebuilds the preview without an intervening body
save. The body's own text is still what a save is checked against, and the
image's identity is still checked where the image is written.

## 9. The two conflicts against other documents

This is the part the original deferral did not see, and it is the reason the
feature needs a design.

### 9.1 An upload can make an unrelated document ambiguous

`docs/markdown.md:162-165` states it plainly: "adding a second file with the
same name under a declared directory turns an existing, unmodified document's
image into the ambiguity error above — which is the point of erroring rather
than picking." Uploading `curve.png` into a second `site.assets:` directory
does not conflict with anything the author is editing. It breaks
`items/decisions/dec-001.md`, which referenced a bare `curve.png` that resolved
unambiguously until this minute, and whose build now fails with
`build.py:2183`'s error.

**Check before writing:** for the proposed leaf name, walk every declared
`site.assets:` directory (`project.asset_dirs`, `model.py:762`) as
`_search_image_src` does. If the leaf already exists in a *different* declared
directory than the destination, refuse, naming both paths and the rule.

### 9.2 An upload can capture an existing bare-name reference

The relative lookup always wins (`docs/markdown.md:139`). So uploading
`curve.png` into `items/decisions/` silently re-points
`![x](curve.png)` written in `items/decisions/dec-001.md` — a reference that
until now resolved from `figures/curve.png` on the search path. Nothing errors.
The document now shows a different picture than it did. That is precisely the
failure `_search_image_src` was written to prevent: "quietly resolved to a
different `diagram.png` than the one meant" (`build.py:2162-2165`), and it is the
same pattern `docs/design/backlog.md:2040-2041` rejects as "permanent meaning
derived from mutable ambient context".

**Check before writing:** the last build records every per-item image resolution
as `{src, ok, rel, dest}` on `Project.image_results` (`model.py:771`, populated
by `_process_images`). Scan it for a reference whose `src` is a bare filename
equal to the proposed leaf, whose owning source file sits in the proposed
destination directory, and whose resolved `rel` is *not* that directory. That is
a capture. Refuse, naming the item and what its image currently resolves to.

### 9.3 Replacing a file changes what other items show

Replacing `curve.png` is not only an edit to the item currently open in the
form. Every item whose body references that path renders the new picture.
`Project.image_results` gives the reverse mapping for free — it is the same
record §9.2 scans.

**Recommendation:** a replace names every item that references the file in its
`Conflict` payload, and the confirmation says so. Not a refusal — an author who
re-shoots a diagram expects every document using it to change — but the editor
must not let them discover the blast radius afterwards. If any referencing item
is sealed, this becomes a refusal instead (§10).

## 10. Sealed entries

Two separate problems, and they get different answers.

**Uploading for a sealed item: refuse up front.** The body edit that would
reference the image is refused by `apply_edit` under the lock
(`serve/edit.py:233`, `seal.is_sealed`). Writing the image first and the
reference never would produce a guaranteed orphan attached to an item that can
never take it. So the upload request carries the item it is for, and a sealed
target is refused before any byte is written — the same posture as "the mutation
endpoint repeats the check under the write lock"
(`docs/design/browser-editor.md:899-900`).

**Replacing a file a sealed entry references: refuse, and this is the sharp
one.** A seal hashes fields and normalized body text (`build.py:1427-1490`).
The body text contains `![alt](path)` — the *path*, not the bytes. So replacing
the file behind a sealed entry's image changes what that sealed record shows
while its hash still verifies. The audit trail says the entry is untouched, and
the entry now displays a different picture.

That is not a hypothetical the editor creates — a hand edit to the file on disk
does the same thing today, silently. But an editor that offers a "Replace image"
button is a tool that *helps* someone do it, and an append-only record whose
illustration can be swapped out from under it is not append-only in any sense
worth the word.

**Recommendation:** refuse to replace or delete any file referenced by a sealed
entry, from the editor, with a message saying why and naming the sealed item.
Refuse to *create* a file at a path a sealed entry references (that is the §9.2
capture case with a seal on it). Whether the same check belongs in `refdes
build` — turning the silent hand-edit case into a loud one — is a bigger
question with a hash-format cost attached, and §15.6 leaves it to Jared.
**Decided (2026-09-25):** Jared approved the build side — `HASH_FORMAT` 5
makes the silent hand-edit case loud; see §15.6.

## 11. Transport and the security surface

**One new endpoint, behind the existing gate.** `POST /api/assets`, routed in
`api.handle` (`serve/api.py:27-46`) alongside the other mutations, and therefore
automatically behind the launch-token check, the `Origin` check, and the Host
check that `_api` applies before routing anything (`serve/server.py:497-504`).
A `--no-write` server refuses it exactly as it refuses edits
(`serve/api.py:270`).

**Raw bytes, not JSON, not multipart.** `Content-Type: application/octet-stream`
with the metadata in query parameters (`dest`, `name`, `expected_hash`), and the
bytes as the body. This needs one new branch in `_api`'s content-type check,
which currently answers 415 to everything that is not `application/json`
(`serve/server.py:505-507`) — a branch that accepts exactly one additional
literal and still refuses everything else.

- **Multipart is rejected** (§16.2): the standard library has no multipart
  parser for a request body, and hand-rolling one for the one endpoint that
  accepts untrusted binary is the wrong place to take that risk.
- **Base64 inside JSON is rejected** (§16.3): it needs no new content type, but
  it inflates every upload by a third, and it means the shared 1 MiB
  `MAX_BODY_BYTES` caps an image at roughly 750 KB of real content — or the
  shared cap gets raised for everything, which is worse.

**What the endpoint may and may not do.** It writes one file, at a path built
from a validated destination directory and a validated single-segment name,
inside the project root with real-path containment (`citations.py:175-181` is
the model). It does not create directories beyond one level below an existing
directory, does not follow a symlinked destination, does not delete anything, and
does not touch any `.md` or `.yaml` file. The design's standing ban on a generic
file-read, command, or plugin surface is unchanged
(`docs/design/browser-editor.md:938-940`).

**Serving the result needs nothing new.** Before upload, the browser previews the
picked file as a `data:` URL, which the editor's CSP already allows
(`img-src 'self' data:`, `serve/security.py:74`). After a rebuild, the file is
served from the preview generation at `/preview/assets/…` under the session
cookie (`serve/server.py:436-453`) — no token in a URL, which matters because an
`<img>` src cannot carry a header, and the token never appears in a log line.
`X-Content-Type-Options: nosniff` is already on every response
(`serve/security.py:97-103`), which is what stops an uploaded file being
reinterpreted as something executable by the browser.

## 12. Preview freshness after an upload

*Updated 2026-09-25:* images are in `project_inputs` now (§15.1), so the
poller notices an uploaded file on its own and rebuilds. Forcing the rebuild
from the endpoint is still the right call: the poll is debounced across two
ticks (`serve/state.py`, `Poller`), and an author who uploads and immediately
looks at the preview should not be staring at the generation from before the
upload. Keep the explicit rebuild — a `force` flag on `refresh()`, or a direct
call into `serve.preview.PreviewManager.render` (`serve/preview.py:77`) — and
treat the poller as the backstop for files the editor did not write.

The subsequent body save rebuilds anyway through the normal save path, so the
forced rebuild is only for the window between upload and save — which is exactly
the window in which the author decides whether the file they just dropped is the
one they meant.

## 13. Git

An upload is a new tracked file in the working tree, and `git status` shows it.
That was one of the original objections (`docs/design/browser-editor.md:420`),
and it is the weakest of the five: the objection is true of item creation too,
which shipped. The distinction that matters is *which* files are gitignored, and
the project already draws it correctly — `.refdes/copies/` is ignored because
those bytes are someone else's copyrighted datasheet (`citations.py:63`,
`.gitignore:27`), while an uploaded image is the author's own content and belongs
in the review. §4's refusal to write under `.refdes/` is that line, enforced.

No git operation is performed by the upload endpoint: no stage, no commit, no
`git add`. Git identity stays advisory and content stays the conflict proof
(`docs/design/browser-editor.md:786-790`).

## 14. Failure modes and named tests

`tests/test_serve_upload.py`

| Test | Pins |
|---|---|
| `test_upload_lands_beside_the_source_file` | Default destination is the item's source directory; returned `from_source` is the bare leaf. |
| `test_upload_override_destination_is_validated` | `dest` outside the root, containing `..`, backslash, drive colon, ADS, a reserved device name, or a symlink escape → 400, nothing written. |
| `test_upload_refuses_dotrefdes_destination` | `.refdes/` and anything below it → refused. |
| `test_identical_bytes_are_not_a_conflict` | Re-uploading the same bytes writes nothing, returns the existing hash, and is not a `Conflict`. |
| `test_different_bytes_at_target_refuse_without_replace` | A present target with different bytes → refusal naming path, size, hash; file unchanged. |
| `test_case_only_collision_refuses` | `curve.png` against existing `Curve.png` refuses on a case-insensitive filesystem (`case_mismatch` reuse). |
| `test_type_is_sniffed_not_trusted` | A `.png` name over JPEG bytes, a `.svg`, a `.php`, an extension-less file, and a correct-signature file with a lying `Content-Type` — the first two refuse, the sniff wins over the header. |
| `test_oversize_is_413_before_the_body_is_read` | A `Content-Length` over the asset cap is refused with no bytes read, mirroring `serve/server.py:511-513`; a lying `Content-Length` is caught on read. |
| `test_upload_never_writes_a_body` | After any upload outcome, every `.md`/`.yaml` in the project is byte-identical. |
| `test_body_edit_before_upload_is_blocked_by_the_gate` | `set_body` referencing a not-yet-uploaded file → `Invalid` naming the missing src, source unchanged (pins today's behaviour as a contract). |
| `test_upload_then_body_edit_saves` | The forced ordering: upload, then `set_body` with the returned `from_source`, succeeds and the asset appears in `project.assets`. |
| `test_sealed_item_refuses_upload_before_any_write` | A sealed target item → refusal, and the destination file does not exist afterwards. |
| `test_replacing_a_file_a_sealed_item_references_refuses` | §10's sharp case, with the sealed item named in the message. |
| `test_upload_that_would_create_ambiguity_refuses` | A leaf already present in another declared `site.assets:` dir → refusal naming both paths, before the write. |
| `test_upload_that_would_capture_a_bare_reference_refuses` | §9.2: a bare `curve.png` in a sibling document resolving elsewhere → refusal naming that document and its current resolution. |
| `test_replace_reports_every_referencing_item` | Two items reference the file; the `Conflict` payload names both. |
| `test_upload_moves_the_revision` | An upload changes the project revision and rebuilds the preview (§15.1's decision, pinned by `tests/test_serve_state.py` for the hand-written case; the endpoint case lands with Phase 1). |
| `test_upload_forces_a_preview_rebuild` | The new asset is present in the current generation without an intervening body save. |
| `test_upload_requires_token_and_origin` | Missing token → 403; cross-origin → 403; `--no-write` → 403. |
| `test_upload_content_type_allowlist` | `application/octet-stream` accepted; `multipart/form-data`, `text/plain`, and a missing `Content-Type` → 415. |
| `test_atomic_replace_rolls_back_on_verify_mismatch` | A replace whose re-read differs restores the original bytes, via the existing `_atomic_replace` posture. |

`tests/test_docs_examples.py` gains nothing: no author-facing syntax changes
until the feature ships.

## 15. Open questions for Jared

Each carries a recommendation; unanswered means the recommendation stands.

1. **Do images stay out of the revision token?** — **DECIDED: no, they do not
   stay out** (Jared, 2026-09-25). Images are part of the build, so `refdes
   serve` watches them and folds them into the revision exactly like every
   other project input. `serve.state.project_inputs` now walks every declared
   `site.assets:` directory and includes every file under it — not only the
   files some body currently references, because adding a file can retire an
   absent or ambiguous resolution error and deleting one can raise it. Adding,
   replacing, or deleting such a file moves the revision and rebuilds the
   preview; a file outside every declared directory is still not an input.
   The cost the recommendation foresaw is accepted: an image edit invalidates
   open forms, and the poll's cheap `(mtime, size)` signature stage is what
   keeps the per-tick cost a stat rather than a re-read of the bytes. The
   upload endpoint's `expected_hash` still covers the replace-conflict case.
   §8 and §16.7 are superseded by this.

2. **Is the default destination the item's own directory?** — **Recommended:
   yes** (§4). The alternative — a project-wide `assets/` convention — invents a
   second notion of "declared asset directory" alongside `site.assets:`, which
   is the duplication `docs/design/vocabulary-review.md` exists to catch.

3. **SVG, ever?** — **Recommended: not in v1, and if ever, only with the CSP
   guarantee restated in the spec that accepts it** (§6). The counter-case is
   real: a schematic exported as SVG is sharper than a PNG and is what an
   engineer reaches for.

4. **Is 8 MiB the right cap?** — **Recommended: 8 MiB.** It admits a full-page
   schematic screenshot with room, and it is small enough that the worst case —
   a hundred uploads against a loopback server that one person can reach — is a
   slow afternoon rather than an outage.

5. **Orphans: leave them, or report them?** — **Recommended: leave them in v1,
   and add an unreferenced-asset advisory to `refdes check` later.** Deleting
   them from the editor is the one option that can destroy work.

6. **Should `refdes build` error when a sealed entry's image bytes changed?**
   — *Recommended: no, not yet* — **decided otherwise by Jared, 2026-09-25:
   bump.** `HASH_FORMAT` is now 5: every local image an item's body references
   contributes its resolved project-relative path and content digest to that
   item's content hash (`build._image_inputs_hash_value`, plan and
   migration analysis in `in-prog-logs/hash-images.md`, pins in
   `tests/test_image_hash.py`), so replacing the bytes behind a sealed entry's
   image now moves its `content_hash` with the text untouched and the existing
   modified-since-sealed error fires — the silent hand-edit case is loud.
   Image-free items hash exactly as before; formats ≤ 4 reconstruct without
   images, so existing seals and baselines carry forward and none looks
   edited; an image swap predating an entry's first format-5 seal/stamp is
   grandfathered silently, because the old record never stored a digest to
   compare against. Editor-side refusal (§10) stands and ships
   independently.

7. **Does a replace of a multiply-referenced file need a confirmation, or only
   a disclosure?** — **Recommended: disclosure in the `Conflict`, and the
   author's re-issue with the fresh hash *is* the confirmation** (§9.3). A
   second modal for the same fact is noise.

8. **Is the copy half of "upload/copy" in scope?** — **DECIDED: no, and not
   later either** (Jared, 2026-09-26). Both readings of "copy" were considered
   and rejected outright, not deferred: (a) copying external bytes in place
   without writing them into the project isn't buildable under this project's
   image-resolution model without a real architecture change, and isn't
   wanted; (b) duplicating an already-in-project image into the current
   item's own directory, as an alternative to referencing it where it already
   sits, was judged not worth the added choice. No toggle, in either
   direction — a picked image is always referenced wherever it lives.

9. **Any aggregate limit — count, total bytes, per-session?** — **Recommended:
   no.** One author, loopback, and the token gate already bounds the population
   to whoever started the server.

10. **Does the picker for existing images (§2: specified in v1, never built)
    ship with this, or before it?** — **Recommended: before it, as its own small
    slice.** It is the smaller half of the feature, it needs none of §8–§11, and
    it is the thing authors are missing today.

## 16. Options considered and rejected

1. **Upload straight into a `site.assets:` directory by default.** Rejected —
   it makes the §9.1 ambiguity break the *normal* outcome of a normal upload
   rather than an edge case.
2. **`multipart/form-data`.** Rejected — no standard-library parser, and a
   hand-rolled one is a poor fit for the endpoint that accepts untrusted bytes.
3. **Base64 in the JSON body.** Rejected — a third of the payload wasted, and
   either a 750 KB real cap or a raised global `MAX_BODY_BYTES`.
4. **Silent rename on collision (`curve-1.png`).** Rejected — a name the author
   did not choose, committed, and the same invisibility objection
   `docs/markdown.md:153-154` makes against first-match resolution.
5. **The server inserts the markdown into the body.** Rejected — the current
   body exists only in the browser as an unsaved draft, and a candidate build
   cannot resolve an image that is not on disk (§2).
6. **Extend the overlay to carry binary bytes so upload + body edit validate as
   one candidate.** Rejected for now — `source_overlay` is `dict[str, str]`
   (`model.py:730`) and every reader of it is text-mode; a parallel binary
   overlay is a second mechanism through the loader to save one round trip.
   Revisit if the two-step ordering ever proves genuinely painful in use.
7. **Keep images out of `project_inputs`.** Rejected — §15.1 decided the other
   way on 2026-09-25; images are watched inputs and are in the revision.
8. **Auto-delete an orphaned upload when the body save fails.** Rejected — §7.
9. **Accept SVG because the preview CSP defangs it.** Rejected — §6.
10. **A generic project file-read endpoint so the editor can show any file.**
    Rejected — `docs/design/browser-editor.md:938-940`, and unnecessary: the
    preview generation already serves the asset (§11).
11. **Content-addressed storage for uploads, like `.refdes/copies/`.** Rejected
    — that scheme exists for blobs the project must not rename or claim, and it
    is gitignored. An author's figure wants a name they chose, in a directory
    they chose, tracked.

## 17. Phasing

| Phase | Scope |
|---|---|
| **0. Picker** | The v1 item that never shipped (§2, §15.10): list existing project images, insert a relative reference into the draft. No upload, no new endpoint. Independently useful. **Shipped 2026-09-25.** |
| **1. Bytes** | `POST /api/assets`; content-type branch and asset cap in `_api`; sniff-based type allowlist; single-segment name validation; `_atomic_create` for new files; §5 collision table; forced preview rebuild. No §9 checks yet. |
| **2. Conflicts** | `expected_hash` and the replace path through `_atomic_replace`; §9.1 ambiguity check; §9.2 capture check over `Project.image_results`; §9.3 referencing-item disclosure. |
| **3. Seals** | §10: sealed-target refusal, sealed-referenced-file refusal. |
| **4. Client** | Drag-and-drop and file input, `data:` preview before upload, insertion into the draft with default alt text, the conflict dialog's binary variant. |
| **5. Docs** | `docs/markdown.md` upload section; `docs/design/browser-editor.md` Deferred/Later lists updated; §14's tests. |

Phase 1 alone is a usable feature with a known hole (an upload can break another
document), and the hole is exactly what Phase 2 exists to close — which is why
Phase 2 is not optional and why the phases are ordered this way rather than
shipping the client first.
