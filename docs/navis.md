# Navis — flying notes

A **Navi** is one flying note: a short reminder you pin inside an item's
body, collected across the whole project into one list you can read,
archive, and restore. This guide is the user-facing tour — the marker
grammar in full lives in
[markdown — Navis markers](markdown.md#navis-markers), the flags in
[CLI reference](cli-reference.md#refdes-navis-ls-all-show-archive-restore),
and the panel in [output formats](output.md#the-navis-panel). Every
command and response below was run on a throwaway project and is quoted as
it printed (the narrative runs on one project, keys `4jp6qysbahb` /
`3fm1dgvv6p3`; the keyless- and no-Navis checks ran on their own).

## What a Navi is

One line in an item body:

```markdown
intro
<!--navi: Model worst-case copper temperature.-->
```

It is an HTML comment, so the published page **consumes** it: the marker's
bytes never appear in the rendered item text, its list-page summary, its
tree entry, or a hover preview. Write it by hand, or press the **Navi**
button in [the browser editor](browser-editor.md#refdes-buttons), which
inserts one with `text` selected (and wraps a selection with it).

You write it **keyless**. The next writable command mints an 11-character
key into the marker, at its exact position in your file, and announces it
on stderr:

```console
$ refdes navis ls
navis: minted key 4jp6qy (4jp6qysbahb) into NOTE-001 (items/note-a.md)
navis: minted key 3fm1dg (3fm1dgvv6p3) into NOTE-002 (items/note-b.md)
(minted 2 key(s) and minted 2 navi key(s) while loading)
2 Navis:
  1. 4jp6qy Model worst-case copper temperature.  NOTE-001 (items/note-a.md:9)
  2. 3fm1dg Recheck decoupling near U14.  NOTE-002 (items/note-b.md:9)
```

The file now reads `<!--navi:4jp6qysbahb Model worst-case copper
temperature.-->`. The key is the Navi's stable name: it is how you select
one, how the archive record is named, and how a hand-restored marker
re-links. `--no-write` mints nothing and keeps markers keyless.

A marker is inert — a plain comment, not a Navi — exactly where the page's
Markdown renderer says it is literal text: inside a fenced code block, an
indented code block, an inline code span, or an open HTML comment. The full
rules (the strict grammar, the malformed-marker warnings, the line-spanning
case, removal being structural) are in
[markdown — Navis markers](markdown.md#navis-markers); this guide does not
repeat them.

## The CLI

`refdes navis <verb>` reads the one project-wide list. The verbs:

| Verb | Shows / does |
|---|---|
| `ls` | The **active** Navis — markers with no archive record — numbered, in file-then-line order |
| `all` | The **Show-all**: the active rows, then the archived rows labelled `[archived]` |
| `show <selector>` | One Navi in full: text, key, source, and (if archived) the record's snapshot |
| `archive <selector>` | Write the Navi's gzip record; it leaves the active list |
| `restore <selector>` | Delete the record; the marker (if present) is active again |

Every verb resolves a **selector** the same way, in this order:

1. the **full 11-character key** (matched first, so an all-digit key is a
   selector, not an ordinal);
2. a unique **6-to-10-character key prefix**;
3. the **number** in the `all` listing (active first) — `ls` prints the
   same numbers on its active rows.

```console
$ refdes navis show 4jp6qysbahb      # full key
Navi: Model worst-case copper temperature.
  key: 4jp6qysbahb
  source: NOTE-001 (items/note-a.md:9)

$ refdes navis show 4jp6qy           # unique 6-char prefix — same Navi
Navi: Model worst-case copper temperature.
  key: 4jp6qysbahb
  source: NOTE-001 (items/note-a.md:9)

$ refdes navis show 2                # the `all` number
Navi: Recheck decoupling near U14.
  key: 3fm1dgvv6p3
  source: NOTE-002 (items/note-b.md:9)
```

An ordinal addresses the list *as it is now*, so archiving row 1 renumbers
the rest; the key is the stable name.

**`ls` vs `all`.** `ls` is the working list (active only); `all` is
`ls` plus the archived rows, and with nothing archived it says so:

```console
$ refdes navis all
2 Navis (active), 0 archived:
  1. 4jp6qy Model worst-case copper temperature.  NOTE-001 (items/note-a.md:9)
  2. 3fm1dg Recheck decoupling near U14.  NOTE-002 (items/note-b.md:9)
  archived: none
```

**Exit codes** (observed on the runs shown here and in
[Archiving](#archiving-and-restoring)):

| Code | When |
|---|---|
| `0` | Success — including a project with no Navis (`ls`/`all` print `no Navis: …`) |
| `1` | An items file failed to load (the listing still prints), or an archived Navi whose marker is gone (orphan) and you asked to `restore` it |
| `2` | A refusal: the selector names nothing, an ambiguous prefix, `restore` of something not archived, a keyless marker, an editor transaction in flight, or `--no-write` on `archive`/`restore` |

The refusals, each run (the ambiguous one uses a third Navi,
`4jp6qym9s3j`, hand-built to share note-a's first six characters so the
prefix `4jp6qy` matches two keys — real prefix collisions are rare, six
of eleven characters, and this one carries a valid check character, so the
run below prints no key warning):

```console
$ refdes navis show 99                     # names nothing
no Navi '99': `refdes navis all` numbers them 1..2; a selector is a number, a full key, or a key prefix   # exit 2

$ refdes navis show 4jp6qy                 # prefix matches two keys
navi key prefix '4jp6qy' is ambiguous:
  4jp6qysbahb  Model worst-case copper temperature.  (items/note-a.md:9)
  4jp6qym9s3j  A colliding prefix reminder.  (items/note-c.md:9)                                            # exit 2

$ refdes navis restore 3fm1dg              # this Navi is active
navis restore: Navi 3fm1dg (3fm1dgvv6p3) is not archived -- nothing to restore                              # exit 2

$ refdes navis archive 1                   # a keyless marker, in a flow-style YAML list file
ERROR   items/items.yaml:1 — could not write key t1kjvxk7ayd back into the source: key cannot be added to this flow-style list; rewrite it in block style (one `- id:` entry per line)
navis archive: this Navi has no key -- keys are minted by the next writable command, and this
marker's body is one refdes will not mint into (see the mint warnings above), so it cannot be archived     # exit 2

$ refdes --no-write navis archive 4jp6qysbahb
--no-write: archive writes the .refdes/navis/ archive store; refusing to run it under --no-write. Drop --no-write to run it for real.   # exit 2
```

A keyless marker cannot be archived because the record is named by its key;
`show` flags it on its key line (`key: (keyless -- the next writable
command mints a key)`). Mint refuses a body whose bytes it cannot locate
losslessly — the flow-style list file above, a plain scalar, a folded `>`
scalar, a shared body — and prints a per-file line naming the fix (the
`ERROR` line above) *before* the refusal. A marker in the
editor-transaction window is refused by the whole command, as it is for
every writable command.

## Archiving and restoring

Archiving a Navi writes **one gzip record** under `.refdes/navis/`, named
by the Navi's key, and nothing else. The marker stays in your file — the
item is **byte-identical**:

```console
$ sha256sum items/note-a.md
3170ed419f3dd1dc7492ab8d004a8bf1a4fdbd8a4633dea29d2fe0d7380ca358  items/note-a.md
$ refdes navis archive 4jp6qysbahb
navis archive: archived Navi 4jp6qy (4jp6qysbahb): 'Model worst-case copper temperature.'  NOTE-001 (items/note-a.md:9)
$ sha256sum items/note-a.md
3170ed419f3dd1dc7492ab8d004a8bf1a4fdbd8a4633dea29d2fe0d7380ca358  items/note-a.md
```

The record is the **snapshot** — the text at the moment you archived, its
source, keys, and a stamp (`archived_at`). `archive` writes only under
`.refdes/navis/`; no body, content hash, seal, or history content changes.
`show` on an archived Navi prints that snapshot:

```console
$ refdes navis show 4jp6qysbahb
Navi: Model worst-case copper temperature.
  key: 4jp6qysbahb
  source: NOTE-001 (items/note-a.md:9)
  archived: yes -- restore with `refdes navis restore`
  archived: snapshot: Model worst-case copper temperature.  (at 2026-11-05T02:48:18Z)
```

**You edited the marker text afterwards.** The snapshot is the archive, not
a live view — it is never re-stamped. The list shows the live text; `show`
shows both and notes the drift, and a restore will show the *current* text:

```console
$ refdes navis show 4jp6qysbahb
Navi: Model worst-case copper temp (rev 2).
  …
  archived: snapshot: Model worst-case copper temperature.  (at 2026-11-05T02:48:18Z)
  archived: marker text has changed since archived -- the live text above is what a restore shows
```

**You deleted the marker.** The record now has no marker — an **orphan**.
`all` labels it `marker not found`, and `restore` refuses (exit 1): writing
a marker back would edit a body. Once a project has an orphan, **every**
command prints this line on stderr first; the two blocks below quote the
complete output, warning included:

```console
$ refdes navis all
WARNING .refdes/navis/3fm1dgvv6p3.yaml.gz:9 — navis.archived_orphan: Navi 3fm1dgvv6p3 is archived with no marker found at its stored source (items/note-b.md:9) -- the marker was hand-deleted or moved out of scope. Show-all reveals it by snapshot; restore refuses (§9) -- hand-restore the marker to re-pair them by key
1 Navis (active), 1 archived:
  1. 4jp6qy Model worst-case copper temperature.  NOTE-001 (items/note-a.md:9)
  2. 3fm1dg Recheck decoupling near U14.  marker not found (items/note-b.md:9) [archived]

$ refdes navis restore 3fm1dgvv6p3
WARNING .refdes/navis/3fm1dgvv6p3.yaml.gz:9 — navis.archived_orphan: Navi 3fm1dgvv6p3 is archived with no marker found at its stored source (items/note-b.md:9) -- the marker was hand-deleted or moved out of scope. Show-all reveals it by snapshot; restore refuses (§9) -- hand-restore the marker to re-pair them by key
navis.archived_orphan: Navi 3fm1dg (3fm1dgvv6p3) is archived at items/note-b.md:9 with marker
not found -- restore refuses (there is no marker to reactivate; writing one would edit a body,
design §9). Hand-restore the marker and the pair re-links by key.                                           # exit 1
```

Hand-restore the marker (`<!--navi:3fm1dgvv6p3 …-->`) and the two re-pair
by key. A `restore` of a live archived Navi removes the record and the
marker is active again showing its current text; `--no-write` refuses both
verbs.

## The published-site panel

A project that has Navis gets a small, read-only **`Navis (n)`** pill fixed
to the **top-right** of every page. It opens over the active list (each
row: the 6-character key, a link to the source item, the text), with a
**Show all** disclosure adding the archived rows. The restore control is
rendered **disabled** and names the command that acts — the site is
read-only:

```html
<button type="button" class="refdes-navis-restore" disabled
        title="the published site is read-only — run: refdes navis restore 4jp6qy">Restore</button>
```

A project with **no** Navis publishes no panel, no `navis.css` asset, and
no `<link>` — byte-identical to a project predating Navis. The panel's
placement, its data riding the page with no fetch, its no-JavaScript
`<details>`, and its print-hidden behaviour are documented in
[output formats — The Navis panel](output.md#the-navis-panel).

Under `refdes serve` the same panel grows actions over the API below —
see [the served preview panel](#the-served-preview-panel). The **published**
page (the build's `_site/`) keeps the read-only panel above; the actions
live only in the served preview.

## The served preview panel

`refdes serve` renders the page at `/preview/`. On a **writable** server
(any `refdes serve` not started with `--no-write`) the panel gains actions
over the serve API below. A **keyed active** row grows an **Archive**
button; a **keyed archived** row under **Show all** has its **Restore**
enabled (it ships disabled on the published page). A click posts the row's
full key to `/api/navis/archive` (or `/api/navis/restore`), the server
rebuilds the preview before the response lands, and the page reloads onto
the current list.

- A **keyless** row shows **no button**: the served load is side-effect-free
  and mints no key, and a keyless marker has no identity to address — so a
  writable `refdes navis` command must mint the key first. Markers in bodies
  refdes will not mint into (a flow-style YAML list `body:`, say) stay
  keyless and can never be archived; see [The CLI](#the-cli).
- An **orphan** (archived, marker deleted) keeps **Restore disabled**, with
  the hint "Marker not found -- hand-restore the marker, then it re-links by
  key": the server refuses it (design §9), as the CLI does.

A server started as `refdes --no-write serve` is read-only: its panel serves
and lists (`GET /api/navis` → `200`), and a click returns the server's
refusal (`POST /api/navis/archive` → `403`) —

```json
{"kind": "refused", "error": "this server was started with --no-write: navis archive and restore are disabled"}
```

— and every action button disables for the rest of that page. On a writable
server the same `archive` returns `200` `{"kind": "ok", "verb": "archive",
"key": …, "changed": true}` and the list's `counts.active` drops.

## In the editor

The browser editor has its own Navis panel: a fixed **Navis (n)** toggle at
the **top-right** opens the active list; **Show all** adds the archived
rows; a keyed active row carries **Archive**, a keyed archived row
**Restore**; an orphan keeps Restore disabled with the hand-restore hint; a
keyless row has no button; a failed action shows the server's message
inline; and a `403` from a `--no-write` server locks the panel's actions for
the rest of the editing session. The full row model, the refresh behaviour,
and the browser-verification notes live in
[browser editor — Navis panel](browser-editor.md#navis-panel); this guide
does not repeat them. The one difference from the preview panel above: an
action there reloads the page, an action here keeps the panel open and
refreshes in place — so an open item draft with unsaved edits outlives the
action (observed in Chromium and Firefox on 2026-11-05, not a guarantee).

## The serve API

`refdes serve` exposes the same list to tool builders over its loopback,
token-gated API (see [CLI reference — `refdes serve`](cli-reference.md#refdes-serve)
for the token). Every request carries the launch token in the
**`X-Refdes-Token`** header; a `POST` additionally needs a matching
`Origin`. All responses below were captured from a `refdes serve --port
8780` on the same three-Navi project as the CLI examples above (so the
`4jp6qy` prefix is the same ambiguity).

**Read the list.**

```console
$ curl -H "X-Refdes-Token: <token>" http://127.0.0.1:8780/api/navis
{
  "navis": [
    {"key": "4jp6qysbahb", "key6": "4jp6qy",
     "text": "Model worst-case copper temperature.",
     "item": "NOTE-001", "href": "note-001.html",
     "file": "items/note-a.md", "line": 9,
     "archived": false, "changed": false, "orphan": false},
    { "key": "3fm1dgvv6p3", "key6": "3fm1dg", "…": "…" },
    { "key": "4jp6qym9s3j", "key6": "4jp6qy", "…": "…" }
  ],
  "counts": {"active": 3, "archived": 0}
}
```

Each row carries the full `key` and `key6`, the `text` (a live row's text;
an archived row's snapshot), the `item` id and its `href` (both `null` for
an orphan), the `file`/`line`, and the `archived` / `changed` / `orphan`
flags. `counts` splits active from archived. A request without the token
is `403`.

**Write one.** `POST /api/navis/archive` and `/api/navis/restore` take a
JSON body `{"navi": <selector>}` — the selector is the full key, a unique
prefix, its `all` ordinal (a JSON string or number), and resolves exactly
as the CLI's does. A successful write rebuilds the preview before the
response lands.

| Status | `kind` | Meaning (each run) |
|---|---|---|
| `200` | `ok` | Performed (`changed: true`) or already in that state (`changed: false`); body adds `verb` and `key` |
| `400` | `bad_request` | The body is not a JSON object, `navi` is missing, `null`, blank, or not a string/number |
| `403` | `refused` | The server runs `--no-write` — checked first, so even a bad body gets the refusal |
| `404` | `not_found` | The selector names no Navi |
| `409` | `ambiguous` | A prefix matches several; body adds `candidates` (`key`, `text`, `file`, `line`) |
| `409` | `conflict` | A state refusal; body adds `reason` — `not_archived`, `keyless`, `orphan`, `journal_pending` |
| `500` | `error` | A store write failed; body adds `error` |

```console
$ curl -X POST -H "X-Refdes-Token: <token>" -H "Origin: http://127.0.0.1:8780" \
       -H "Content-Type: application/json" -d '{"navi": "4jp6qysbahb"}' \
       http://127.0.0.1:8780/api/navis/archive
{"kind":"ok","verb":"archive","key":"4jp6qysbahb","changed":true}          # 200

$ curl -X POST -H "X-Refdes-Token: <token>" -H "Origin: http://127.0.0.1:8780" \
       -H "Content-Type: application/json" -d '{"navi": "4jp6qy"}' \
       http://127.0.0.1:8780/api/navis/archive
{"kind":"ambiguous","error":"navi key prefix '4jp6qy' is ambiguous: name one of its candidates",
 "candidates":[{"key":"4jp6qym9s3j","…":"…"},{"key":"4jp6qysbahb","…":"…"}]}   # 409

$ curl -X POST -H "X-Refdes-Token: <token>" -H "Origin: http://127.0.0.1:8780" \
       -H "Content-Type: application/json" -d '{"navi": "3fm1dgvv6p3"}' \
       http://127.0.0.1:8780/api/navis/restore
{"kind":"conflict","reason":"not_archived","error":"this Navi is not archived -- nothing to restore"}  # 409
```

**Mint keys.** `POST /api/navis/mint` takes a JSON object body — the mint is
project-wide, so `{}` is the whole request and extra keys are ignored. It
writes a minted key into every keyless live marker (the CLI's
`navis.mint_keys` decides every mint: exact provenance or refuse, so a
marker whose bytes cannot be located exactly — a list file's `body:` scalar,
a file edited after the served snapshot — stays keyless, counted in
`still_keyless` beside the markers the call minted). A successful mint
rebuilds the preview before the response lands. Captured from a writable
`refdes serve --port 8815` on a two-Navi project:

```console
$ curl -X POST -H "X-Refdes-Token: <token>" -H "Origin: http://127.0.0.1:8815" \
       -H "Content-Type: application/json" -d '{}' \
       http://127.0.0.1:8815/api/navis/mint
{"kind":"ok","changed":true,
 "minted":[{"key":"xw5kbykt82k","key6":"xw5kby","item":"NOTE-001","file":"items/note-a.md"},
           {"key":"ne1tnta9n8t","key6":"ne1tnt","item":"NOTE-002","file":"items/note-b.md"}],
 "still_keyless":0}
```

The same POST again answers `{"kind":"ok","changed":false,"minted":[],
"still_keyless":0}` (the mint is idempotent), and on a `--no-write` server it
answers `403 {"kind":"refused","error":"this server was started with
--no-write: navis mint is disabled"}` (observed on port 8816).
