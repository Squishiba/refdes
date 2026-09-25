# HASH_FORMAT 5: image bytes enter the content hash

Jared's decision on `docs/design/editor-image-upload.md` §15.6 (the doc's own
recommendation was "no, not yet"; the decision overrides it): **approved** —
the bytes of the images an item references become part of its content hash, so
a changed image is loud for sealed/captured entries instead of silent.

Precedents followed exactly: HASH_FORMAT 4 (finding 35 + finding 26,
`build.py:1404-1424`, `_calc_refs_hash_value` / `_source_inputs_hash_value`,
`hash_payload_builder`), `docs/design/calc-sources.md` §9, and the rule at
`history.py:37` — *a hash-format bump must never make an item look edited*.

## 1. What enters the hash

New payload key `images`, present **only** when the item's body references at
least one local image **and** the payload is being built under format ≥ 5.

- **Value:** a sorted, de-duplicated list of `[rel, digest]` pairs — one per
  distinct resolved image. `rel` is the project-root-relative source path
  (forward slashes, the same spelling `project.assets` uses); `digest` is the
  first 16 hex chars of the file's sha256 — the *same* digest
  `_process_images`/`_hashed_leaf` already splice into output filenames
  (`build.py:2137, 2255-2260`), so a hash contribution is human-comparable
  with the published asset leaf.
- **Order:** sorted by `rel`, deduplicated — *not* document order. The same
  file referenced twice contributes once (precedent: `source_values` is
  sorted/deduped, `_source_inputs_hash_value`). Document order adds nothing:
  moving a reference within the body already moves the whitespace-normalized
  body text in the payload.
- **Unresolved src** (file missing) and **ambiguous bare src** (two matches on
  the `site.assets:` search path): contribute `[raw_src, None]`. Deterministic
  and distinct from any real pair; both cases are already build errors at
  render time (`_process_images` / `_search_image_src`, `build.py:2147-2198`),
  so the hash only has to not crash and not collide — the exact posture of a
  `None` calc-ref value (`_calc_refs_hash_value`) and `!unresolved:` links.
  Unresolved and ambiguous hash identically; acceptable because both stop the
  build anyway.
- **URL-scheme srcs** (`http:`, `//`, `data:`) contribute nothing — same skip
  as `_process_images` (`_URL_SCHEME_RE`, `build.py:80`).
- **Resolution mirrors `_process_images` exactly:** relative to the item's own
  source-file directory first (always wins); only a bare filename (no `/`)
  that failed there falls through to the `site.assets:` search; two matches →
  the `None` sentinel.
- **Scan source:** `item.body` raw markdown, parsed with the *same*
  markdown-it configuration `render_bodies` uses (`gfm-like`, `html: False`,
  `build.py:2550`) and the `image` tokens' `src` attribute extracted — not a
  second regex. This guarantees the hash pass and the render pass see the
  same set of images for free: code fences and inline code contribute no image
  tokens, raw `<img>` in source is escaped text (html disabled) and correctly
  contributes nothing, and markdown-it's destination rules (`<…>`, quoted
  titles) are handled by the parser rather than re-invented.
- **Scope:** item bodies only. Fields never go through `_process_images`
  (only `render_bodies` at `build.py:2581` and pages at `:2612`), pages have
  no content hash, and imported items keep the hash their upstream project
  computed (`compute_hashes` iterates `local_items` only). All unchanged by
  this bump; pages' images stay silent (no seal/baseline exists for a page to
  be loud about).
- **`on_change`:** `images` is contributed only inside the
  `body_mode == INVALIDATE` branch of `_hash_payload` — a body that is
  `log`/`ignore` for hash purposes drags no images into the payload.
- **I/O:** `compute_hashes` runs *before* `render_bodies` in `build()`
  (`build.py:2718` vs `:2734`), so the hash pass cannot read
  `project.assets`/`image_results` — they are empty at that point. The hash
  pass reads image bytes itself, with a per-build digest cache keyed by `rel`
  inside the `hash_payload_builder` closure so a multiply-referenced file is
  read once. `project.assets` and `image_results` are not touched (their
  population timing stays exactly as today).

## 2. Where in the payload / how the gate works

- `_hash_payload` gains an `image_inputs` callback parameter beside
  `calc_refs`/`source_inputs` (`build.py:1427`): when not `None`, it is called
  once per item and a non-`None` result lands as `payload["images"]`.
- `hash_payload_builder(project, hash_format)` sets
  `image_inputs = ... if hash_format >= 5 else None`.
- **Formats ≤ 4 are byte-identical to today** — the ≤4 builder paths gain no
  new inputs, so `hash_for_format(item, project, 4)` returns the pre-bump
  value even for an item that has images. This is the strong pin, in the
  style of `test_hash_format_stays_4`'s format-3-vs-4 identity.
- **An item with no images has the exact same payload under 5 as under 4** —
  no `images` key at all (precedent: `source_values` absent when no
  `source()` line, `test_calc_sources.py::test_item_without_source_has_no_source_values_in_its_hash_payload`).
  So the bump moves zero existing hashes: the "never make an item look
  edited" rule holds for every image-free item, and for image-bearing items
  it holds in the only sense available (see §3).
- `calc_hash_for` (the narrow stale-arithmetic probe) is untouched — it hashes
  calc block text, a deliberately different question
  (`calc-sources.md` §9 "Existing `calc_hash` remains source-text-only").
- The `HASH_FORMAT` comment block at `build.py:1404-1423` gains the 5 entry
  with the same "an item with none is unchanged" argument.

## 3. Seals, baselines, history — the seal-sensitive part

**The information-theoretic limit, stated plainly:** seals and baselines
recorded under format ≤ 4 never recorded image digests, so *no mechanism can*
detect an image change that happened before the first format-5 stamp/seal.
The bump makes image changes loud **from the first format-5 seal/stamp
onward**; changes made between an old seal and the bump are, and must be,
absorbed silently — any other choice would require the old records to contain
data they do not have, or would flag items for a definition move only, which
`history.py:37` and keys.md §5(c) forbid.

Walk-through of every consumer (all verified against the code):

- **Seal verify (`seal.verify` → `_matches_sealed_hash`, `seal.py:160-186`):**
  a seal entry records its `hash_format`. After the bump, an entry recorded at
  ≤ 4 is re-checked with `keys.hash_in_format(item, project, recorded_format)`
  — the ≤4 reconstruction, which ignores images and is unchanged — so an
  untouched-text sealed item still matches. **No existing seal breaks or looks
  edited, under `refdes check` (read-only) or a writable build.**
- **Seals whose image bytes changed since sealing:** the recorded-format check
  still matches (format ≤ 4 ignores images), so on the first *writable* build
  the seal is carried forward and upgraded to the current format-5
  `content_hash` (`seal.py:317-321` `_with_seal_hash(..., hash_format=5)`),
  absorbing the current image digests — grandfathered, per the limit above.
  From that upgrade on, an image byte change moves `content_hash` with the
  text untouched → `_matches_sealed_hash` fails → the existing
  "append-only and has been modified since it was sealed" error, `--reseal`
  remedy, and `project.seal_violations` exit-code path fire unchanged. *This
  is the loudness the decision asked for, and it needs no new seal machinery.*
- **Legacy scalar seals (no format marker):** `_matches_sealed_hash` tries
  `range(HASH_FORMAT, 0, -1)` — 5 first, then 4. For an image-bearing item the
  format-5 hash won't match a pre-bump seal, but the format-4 reconstruction
  will. `keys.plan_surrogate_storage`'s candidate list `(HASH_FORMAT, 2, 1)`
  has the same shape as today's `(4, 2, 1)`; scalar seals are pre-keys
  artifacts recorded under 1/2, so behavior is unchanged.
- **Baselines (`lifecycle.migrate_hash_format`, `lifecycle.py:344-420`):**
  entries recorded at ≤ 4 are re-checked under their recorded format (unchanged
  reconstruction) and carried forward to the format-5 hash exactly as the 2→3
  and 3→4 migrations did; genuinely-changed entries stay `uncomparable`.
  `stamp` runs the migration before comparing (`lifecycle.py:682`), `audit`/
  `diff_against` likewise (`lifecycle.py:879`) — so an image change that
  happened between a ≤4 stamp and the first format-5 build is absorbed by the
  carry-forward (same limit as seals), while an image change after a
  format-5 stamp shows as `changed` in `refdes audit` — loud, which is half
  the point of the bump.
- **History (`history.py`):** `semantic_digest` is deliberately independent of
  `build.HASH_FORMAT` (docstring line ~37) — it covers fields, raw links, and
  whitespace-collapsed body text. **Unchanged by this bump:** an image byte
  change does *not* trigger `edited-after-captured`, and history objects
  migrate only by an explicit history migration. Known gap, stated: history
  snapshots do not cover image bytes. Closing it is a `HISTORY_FORMAT`
  question with its own "prove semantic equivalence" migration rule and is
  explicitly out of scope here.
- **`refdes history migrate-seals` (`history.py:839`):** markers are
  self-describing records of "recorded hash only" — they store the seal file,
  the recorded hash string, and its `hash_format` verbatim, and never
  recompute. Unaffected by the bump. `--capture-current` compares through
  `seal._matches_sealed_hash`, which matches old seals under their recorded
  format (see above), so migration proceeds for untouched-text items exactly
  as before.
- **Editor (`serve/`):** the revision token and `project_inputs` exclude
  images (`serve/state.py:38-80`) and the save gate is a *delta of error sets*
  (`serve/edit.py:29-31`), not a content-hash comparison — an image byte
  change produces no new errors, so editor saves are unaffected. The
  editor-side sealed-image refusals of `editor-image-upload.md` §10 remain
  separate, unbuilt work; this bump is the build-side half that §15.6
  approved.

## 4. Existing tests that pin the hash format (audit list for chunk 2)

- `tests/test_calc_block_hash.py::test_hash_format_stays_4` — asserts
  `HASH_FORMAT == 4` and format-3/4 payload identity. **The deliberate pin: it
  is designed to fail on a bump** ("a bump to 5, fails here"). Update to 5 and
  extend: format-4/5 payload identity for image-free items.
- `tests/test_calc_sources.py` — `HASH_FORMAT == 4` pin at ~:411 and
  `source_values` payload-shape assertions (~:372-425).
- `tests/test_calc_cross_ref_hash.py` — format-3 identity assertions (~:199).
- `tests/test_checks_keys.py`, `tests/test_keys.py`, `tests/test_keys_links.py`,
  `tests/test_seal.py`, `tests/test_revise.py`, `tests/test_history.py` —
  contain `hash_format`/`HASH_FORMAT` references; audit each for pinned
  numbers or literals when the bump lands.
- `tests/test_image_search.py`, `tests/test_render_assets.py` — image
  resolution/output behavior; must stay green untouched (the bump must not
  change any rendered byte or any `project.assets` entry).
- Only literal-hash pin found anywhere: `test_seal.py:100` uses
  `"0000000000000000"` as a *forged* hash, not a pinned digest — safe.

## 5. Chunk 2 test design (style of `test_calc_block_hash.py`)

Sabotage-paired, relationship-based; **no hardcoded hex literals** — expected
image digests are computed in-test with `hashlib` over the fixture bytes the
test itself wrote (`wb` mode, so line-ending independent; body text is
whitespace-collapsed in the payload anyway). Never pin raw byte hashes of
generated files.

1. `HASH_FORMAT == 5`; an item with no images: payload under 5 == payload
   under 4 == (for a calc-free item) under 3, and
   `content_hash == hash_for_format(item, project, 4)`.
2. Changing image bytes moves the owner's `content_hash` under format 5 while
   `hash_for_format(item, project, 4)` is unmoved — the format gate itself.
3. Payload shape: `images == [[rel, digest]]` with the digest computed in the
   test; same file twice → one entry; two files → sorted by rel; URL src →
   absent; missing file → `[src, None]` + the existing build error; ambiguous
   bare src → `[src, None]` + the existing ambiguity error.
4. Two items reference one image: both hashes move when its bytes change, a
   third item's does not.
5. Sealed item recorded under format 4: after the bump, `refdes check` reports
   no seal violation even if the image bytes changed (the grandfathering pin,
   pinned so the behavior is *owned*, not accidental); after a writable build
   upgrades the seal to format 5, changing the image bytes produces the
   modified-since-sealed error.
6. `calc_hash_for` unmoved by an image change; body `on_change: ignore` →
   no `images` key.

## 6. Chunk 3 docs

Grep targets already located: `docs/design/backlog.md`, `calc-sources.md`,
`editor-image-upload.md` (§10/§15.6 — record the decision), `living-notes*.md`,
`named-calc-blocks.md`; `docs/markdown.md` "Images and other local files"
(gains a sentence that image bytes are part of an item's content hash from
format 5, so sealed/baseline entries notice); changelog fragment
`image-bytes-hash.changed.md` (category `changed`) noting the bump, the
no-churn-for-image-free-items guarantee, and the grandfathering limit.
