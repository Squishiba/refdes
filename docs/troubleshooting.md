# Troubleshooting

Every diagnostic leads with `file:line`, so most of these point straight at the
problem. Errors fail the build; warnings do not.

## Items and fields

**`no refdes-project.yaml found in ... or any parent directory`**
You are not inside a project — `refdes-project.yaml` is the project marker,
and commands search upward from the current directory for it. `cd` into one,
or pass `-c path/to/refdes-project.yaml`.

**`refdes.yaml is retired. Split it into the two files it became: ...`**
Your project still carries the old single-file config, which the loader now
refuses rather than reading quietly. Move every project setting — `site:`,
`id:`, `boards:`, `workspaces:`, `units:`, `history:`, `standard:`,
`equations:`, `imports:`, and the process settings like `sigfigs:` and
`release_gate:` — into `refdes-project.yaml`, and move any
`types:`/`link_types:`/`sets:` into the optional `refdes-schema.yaml`
(omit that file entirely if your whole vocabulary comes from the standard).
Then delete `refdes.yaml` — nothing is read from it any more, so a key left
behind is a setting that silently stops applying.

**`item has no 'type'`**
Add `type:` to the item, or to `defaults:` in the list file.

**`unknown type 'requirment'. Did you mean 'requirement'?`**
Typo, or a type the merged schema doesn't declare — neither the bundled
standard (with any presets) nor your own `refdes-schema.yaml` defines it.

**`no YAML front-matter (file must start with '---')`**
A `.md` file under `items/` needs front-matter. If it is not an item, move it out
of `items/`.

**`invalid YAML front-matter: ...`** on a line partway down a `.md` file
A [multi-item markdown file](authoring.md#several-items-in-one-file) reads every
`---`-fenced block that opens with a `key:` line as an item. This is one of those
blocks failing to parse — the line number points inside it. Until it parses, that
item is not in the project at all.

**`duplicate key 'id' in one mapping (lines 14 and 17) -- YAML keeps the last, ...`**
One mapping spells the same key twice. YAML resolves that silently by keeping the
last value, so the value on the earlier line is already gone by the time anything
reads the file — and when the repeated key is `id:`, the item the earlier one
named is not in the model at all, with no diagnostic of its own. The message names
the file, the line of *each* occurrence, the key, and the id the entry ended up
with (`'REQ-PWR-002' is dropped for 'REQ-PWR-003'`). The commonest cause is a list
entry that lost its `- ` marker:

```yaml
items:
  - key: mxmyj98dagm
    id: REQ-PWR-002
    body: The 3V3 rail shall supply 1.2 A continuous.

    id: REQ-PWR-003
    body: Converter efficiency shall exceed 90 % at half load.
```

REQ-PWR-003's own opening `  - key: <key>` line was deleted, taking the `- `
with it, so its fields merged into the entry above: one mapping, two `id:`
lines, and REQ-PWR-002 gone from the project. The same thing happens to any two
keys an entry shares — two `body:` lines lose the first body from every rendered
page.

A repeat inside a `defaults:` block is reported as such, since a value lost there
is inherited by every item in the file. A one-line flow mapping reports both
occurrences as `twice on line 3`, and a key written three times reports each line
once.
**Remedy:** put the `- ` back on its own line above `id:` (or delete one of the
two lines, if the entry was a copy rather than a merge). Until it is fixed, that
file is left exactly as written — no key is minted into it and no reference is
rewritten, so the shape you have to fix is still there to look at.

**`refdes-project.yaml: duplicate key 'site' in one mapping (lines 1 and 14) -- YAML keeps the last, ...`**
The same rule in a config file, and here what a repeat costs is a whole block
rather than one field. A second `site:` block silently replaced the first — exit
0, no diagnostic, and the project rendered under the title nobody remembered
deleting. `refdes-schema.yaml` is covered the same way, where a `types:` block
written twice takes every field the first block declared out of the merged
schema. The message is the item-file one above, unchanged, and it carries the
line of *each* occurrence — the only configuration error that does, because a
repeat is the one config problem whose whole diagnosis is two line numbers:

```
configuration error: refdes-project.yaml: duplicate key 'site' in one mapping
(lines 1 and 14) -- YAML keeps the last, so the value on line 1 is lost. Usually
a hand-merge or a copied block left two spellings of one setting: keep the one
you meant and delete the other. See ...
```

Nested repeats count too — two `title:` lines inside one `site:` block, two
`presets:` lines inside `standard:` — and every repeat in the file is named in
the one error. A `revise` mapping file gets the same check: there a repeat drops
one of the two renames the file asked for and applies the other, which is worse
than dropping both.
**Remedy:** delete one of the two blocks (or merge what both were setting into
the one you keep). Until it is fixed, no command loads the project at all — this
is a configuration error, exit 2, before a single item is parsed — and the
commands that write the config (`refdes standard add-preset`) refuse too, rather
than appending to a block the loader is not reading.

**`unknown field 'sorce' on requirement -- did you mean the field 'source'?`**
A build error. The key is close enough to a declared field that a typo is the
only reading, and a misspelled name means the value never reached the field —
nor the report that field feeds (`part_number` → the parts index). Fix the
spelling. An unknown field with nothing close to it is only a warning
(`unknown field 'thermal_model' on component.`) and its value is kept: that is
the forward-compatible case, where there is no typo to correct.

**`missing required field 'title'`**
The schema marks it `required: true`. In the bundled standard, `decision`,
`test`, and `component` use `title`. `requirement` and `bound` have no
required field at all under **hardware@3** -- their content lives in the
markdown `body:`, which is required but enforced as a *warning*, so a stub
can exist while it is still being drafted:

```
WARNING items/reqs.yaml:7 [REQ-PWR-001] — body: is empty -- title: is an
        optional short label, not a substitute for the content itself.
```

The older `missing required field 'text'` message belongs to hardware@2,
where `requirement`/`bound` had a required `text:` field. Under hardware@3
writing `text:` gets the rename diagnostic below instead.

**`status: 'in-review' is not one of draft, active, retired`**
Use one of the declared `choices`, or add yours to the schema.

**`unknown type 'constraint' -- it is now 'bound' in hardware@2 ...`**
The `hardware@2` rename. Either put `standard.version:` back where it was and
run `refdes standard upgrade --to 2` (which rewrites the items and their ids
for you), or rename by hand — the prefix moved from `CON` to `BND` too, and
`title:` became `text:` in the same version. See [the standard
library](standard-library.md#the-versions-shipped-so-far).

**`'constraint.title' is now 'constraint.text' -- rename this key ...`**
The same rename's field half, which you'll see on a hand-rolled schema that
declares a `constraint` type wanting `text:`. Its value is used for `text:`
in that build so the item doesn't also report a missing required field.

## IDs

**`item has no id — run 'refdes id' to allocate one`**
Expected for new items. Run `refdes id`.

**`duplicate id 'REQ-PWR-004' (also defined at ...)`**
Usually two branches allocating in parallel. Renumber the younger one — safe only
if it has not been baselined. Commit `.refdes/ids.yaml` to prevent this.

**`could not write id back into the source`**
The list entry is not in the expected `- key: value` shape. Add the `id:` by hand.

**`id: is an unquoted number -- YAML reads a leading zero as octal ...`**
Quote it: `id: "042"`, not `id: 042`. Unquoted, YAML may silently read it as a
different number — quoting is required even without a leading zero, since
there's no way to tell after the fact which numbers would have been affected.
See [choosing your own number](ids.md#choosing-your-own-number).

**`id: 042 would expand to 'CAN-042', but that number is already used or was
burned by an earlier item ...`**
Pick a higher number, or leave `id:` blank and let `refdes id` choose one.

**`id 'CNA-001' does not match this item's prefix 'CAN' (from defaults:)`**
Usually a typo in the id or in `prefix:`. This warning never auto-corrects
either value; surrogate keys keep it from blocking the build.

## Surrogate keys

**`key 'k7f3m2q9x4' is malformed: expected exactly 11 characters`** /
**`key 'k7f3m2q9x4l' is malformed: contains a character outside the key alphabet`** /
**`key 'k7f3m2q9x4c' is malformed: check character mismatch`**
All three continue with the same sentence: `A key is written by refdes and never
edited by hand, so this line has been corrupted — restore it from git rather than
guessing.` A check-character mismatch appends `(Expected check character 'a'.)`.
Inside a link target the message names the link instead of the item —
`key 'k7f3m2q9x4c' in refines target (labelled REQ-PWR-002) is malformed: ...`.
The key line in the source file has been corrupted: a hand edit, a merge
conflict, an encoding change. `refdes` writes that line, and it is never edited
by hand.
**Remedy:** restore the line from git (`git checkout -- <file>`).

**`key 'k7f3m2q9x4a' on REQ-PWR-004 (local items/requirements/power.yaml:12) is already used by REQ-PWR-007 (local items/requirements/power.yaml:19)`**
Two items claim the same surrogate key, and a key is unique by construction. A
key line got duplicated: copy-paste, a merge conflict, a botched edit.
**Remedy:** keep the key on the *original* — the item that was there first, which
is the one existing references and recorded history mean, so the copy is
normally the newer item. Two ways to tell, either is enough:

```bash
git log -S'key: k7f3m2q9x4a' --oneline --reverse   # the oldest commit that wrote the key is the original's
```

…or, if the key appears in a [baseline](lifecycle.md), a seal file or a
membership manifest, whichever of the two display ids it is recorded under is
the original — `refdes audit` shows the stamp and the id it recorded.

Then delete the `key:` line from the copy (leaving its `id:` as the entry's
first field) and rebuild: a fresh key is minted for it. Deleting the key from
the *original* instead is the trap — every inbound reference moves to the copy,
`refdes check` reports `0 errors` and exits 0, and a release will stamp a
baseline over the mis-pointed references.

**`key changed since baseline 'rev-b': was 'k7f3m2q9x4a', now 'm9n2b5v8c1w'. A key never changes legitimately.`**
An item's surrogate key no longer matches what the latest baseline recorded, so
the `key:` line was edited or replaced.
**Remedy:** restore the old key from git; if the item genuinely is a new one,
delete the `key:` line and let it be re-minted, and give it a new display `id:`.

**`key deleted since baseline 'rev-b': was 'k7f3m2q9x4a', now no key is declared.`**
An item that had a key at baseline time no longer declares one. The message goes
on to say where the old key is still recorded (`The old key is recorded for
REQ-PWR-002 in baseline 'rev-b'.`), and adds a note when two records disagree
about it.
**Remedy:** restore the old key from git; if the item genuinely is a new one,
delete the `key:` line (if any) and let it be re-minted, and give it a new
display `id:`.

**`older baseline 'rev-a' references key 'k7f3m2q9x4a' for REQ-PWR-002, which no current item declares. The item may have been deleted legitimately; this is audit information, not a build error.`**
An older baseline — not the latest — names a key that no live item has. The build
is fine; `refdes audit` lists it so you can confirm the deletion was deliberate.
**Remedy:** if the item was deleted on purpose, nothing to do. If it was
renamed, ensure its `former_ids:` records the old display id.

**`refines points at key 'k7f3m2q9x4a' (labelled REQ-PWR-002), which no item declares. ...`** /
**`check against key 'k7f3m2q9x4a' (labelled REQ-PWR-002), which no item declares. ...`**
A structured link, a `checks: against:` entry, or a cross-item calc reference
points at a surrogate key that no live item declares. Resolution uses the key;
the display label is never a fallback. The target may have been deleted, or its
key lost or changed. When the label names a live item, the diagnostic reports
that item's current key (or that it has none):

`A live item labelled REQ-PWR-002 declares key '...'. Its key may have been lost and regenerated, or the label may now name a different item.`

Losing a `key:` line can cause a writable load to mint a replacement if no
baseline, seal, or adopted membership record remembers the original. Inbound
composite references still carry the original key and then fail to resolve.
Two shapes of the same report. A key still bare drops the label clause —
`refines points at key 'k7f3m2q9x4a', which no item declares. ...` — while a
bare display id that resolves to nothing gets the ordinary `... points at
'REQ-PWR-002', which does not exist`.
**Remedy:** check git history to confirm whether this is the original item.
If it is, restore its **original** key, preserving its references and history:

```bash
refdes keys restore REQ-PWR-002@k7f3m2q9x4a --dry-run
refdes keys restore REQ-PWR-002@k7f3m2q9x4a
```

Use the actual original key from your project's history/reference. Supply
multiple `DISPLAY-ID@ORIGINAL-KEY` arguments if several keys were lost. The
command validates the proposed project before writing; see
[`keys restore`](cli-reference.md#refdes-keys-restore) for refusals.

`keys restore` also refuses when the baseline remembers the key and that record
does not describe the item you are putting it on — the shape you get when the
original item was deleted and an unrelated one was created under its display id:

`refusing to move key 'k7f3m2q9x4a' onto REQ-PWR-002: baseline 'rev-a' records that key under 'REQ-PWR-002' with different content -- title: ...; content hash: ... . ... If this really is the item that key belonged to -- the same item, edited since that baseline was stamped -- pass --force. If it is not, give the item a new display id so it is not mistaken for the old one; a fresh key is minted for it then.`

Read that as the question the display id cannot answer for you, answered by the
record: *is this the same item?* **Remedy:** if it is the same item, edited since
the stamp, rerun with `--force`. If it is genuinely a different item, give it a
new display `id:` (then the dangling references should be removed or re-pointed,
not restored). The command volunteers nothing beyond what is in the message, so
git history is still the first thing to check.

An **imported** target is the one case `keys restore` cannot reach, and the
report says so by ending differently — no command, and a note about the
reference itself:

`If it is the same item, restore its original key upstream. This composite reference was written into your file by refdes on a load, not typed by hand — see https://squishiba.github.io/refdes/multi-board.html.`

Nothing hand-edited that composite: the load that expanded a bare link you did
write is what turned it into `DISPLAY-ID@key`, which is why the error can name a
file whose only change since it last built was a title. Restore the key in the
upstream project and regenerate the imported artifact, or accept the new key and
re-point the reference. See [multiple boards](multi-board.md).

If the target was deliberately deleted, remove the reference. If the label now
names a different item, confirm the intended target before changing the
reference. Minting another key cannot restore the old identity, and
`keys adopt` continues to refuse unresolved references.

## Links

**`satisfies points at 'REQ-PWR-009', which does not exist`**
Typo, deleted item, a failed import, or an item renamed by hand. Check the
import errors first — they cascade.

The rename case is the one with no obvious next step, because the reference is
still **bare**. A `DISPLAY-ID@key` composite follows a renamed item (the key
half is the identity); a bare reference resolves by display id, so nothing
carries it across — and by then none of the recovery commands apply, because no
key was ever involved:

- `refdes keys restore` — nothing was lost but a label.
- `refdes former-ids` / `former_ids:` — **does not reach a structured link.**
  `former_ids:` resolves *prose* references; a structured link still needs a
  live display id or key. Verified: recording `former_ids: [REQ-PWR-001]` onto
  the renamed item leaves this error exactly as it was.
- `refdes revise` — maps `types:`/`fields:`/`links:`/`prefixes:`/`citation_keys:`,
  not individual ids, so it cannot rename a single item. It is the tool for a
  prefix-wide rename, and it expands bare references *first* so they follow. An
  `ids:` mapping handed to it is refused by name, with that pointed at here.

**Remedy:** write the item's new display id into the reference. The next
writable load expands it to `NEW-ID@key` and the build is clean.

**`constrained_by may point at bound, but REQ-PWR-002 is a requirement`**
Wrong link type. `constrained_by` is reserved for the limit-bearing case —
a `bound` and `checks:` actually involved — and only ever targets `bound`.
To point at a requirement instead, use `satisfies` (decision/component,
also reaches `bound`) or `governed_by`/`refines` (requirement) — see
[`governed_by` vs. `refines` vs.
`constrained_by`](links.md#governed_by-vs-refines-vs-constrained_by).

**A reference in prose did not become a link.**
Bare IDs only link when they resolve. A near miss like `REQ-PWR-2` instead of
`REQ-PWR-002` silently stays plain text — use `[[REQ-PWR-002]]`, which warns when
unresolved.

### Hand-renaming an item is safe — get one writable load in first

A hand edit of an item's `id:` is **not** what breaks references. What breaks
them is hand-editing an `id:` while a reference to it is still bare, which
means no writable load has run since you wrote that reference — `--no-write`
suppresses both key minting and expansion, so a project checked only under
`--no-write` is in exactly that state.

So run any `refdes check` **without** `--no-write` before you rename, and the
references follow the rename on their own:

```yaml
# written:            refines: [REQ-001]
# after refdes check  refines: [REQ-001@51rkcxhdsfc]
# hand-edit the target: id: REQ-001 -> id: REQ-009
# after refdes check  refines: [REQ-009@51rkcxhdsfc]   <- followed, key unchanged
```

```
$ refdes check
(rewrote 1 reference(s) while loading)
WARNING <project> — 2 item(s) with no coverage — see coverage.html
2 items, 0 errors, 1 warnings
```

(The coverage warning is the two-item project's own, not part of the rename: it
is here because the block is what the command prints, in full.)

Recording the retired id as `former_ids:` for external citations is a separate
step, and a prefix-wide rename is what
[`refdes revise`](cli-reference.md#refdes-revise-mapping-file) is for —
see [renumbering](ids.md#renumbering-former-ids).

## Math

**`cannot add V and A — the units do not match`**
Real dimensional error. There is no way to make this produce a number.

**`unknown unit 'wat'`**
Misspelled unit, or a variable used where a unit was expected — juxtaposition is
not multiplication, so `2 x` is read as "2 of unit x". Write `2 * x`.

**``  `1.2 A` reads 'A' as a unit, but a variable of that name is also defined ``**
A warning. The unit reading wins. Write `1.2 [A]` to silence it, or rename the
variable if you meant to multiply. Common with `A`, `C`, `L`, `R`, `T`.

**`declared as W but the expression evaluates to V/A`**
A [unit assertion](math.md) caught the algebra drifting. Usually a `/` that should
be a `*`.

**`unknown function 'sin'`**
Available: `sqrt`, `abs`, `min`, `max`, `exp`, `ln`, `log10`. Trigonometry is not
implemented.

**`division by a value whose tolerance range includes zero`**
The denominator's interval spans zero. Narrow the tolerance or restructure.

**`only one ± tolerance is allowed per assignment`**
Split it across two lines.

**Units display oddly (`2 J` for a torque).**
`N·m` and `J` are dimensionally identical. Pin it: `tq = ... | N*m`.

**`calc fence: unknown attribute 'name' -- a calc fence accepts id="..."; write id="losses".`**
A calc fence's info string has exactly one attribute, `id="..."`. `name=` was an
earlier draft's spelling. The fix is in the message: write `id="losses"`.

**`calc fence: 'losses' is not an attribute -- attributes are key="value"; write id="losses".`**
Two mistakes get this message: a bare word after ```` ```calc ````
(```` ```calc losses ````) and an unquoted value (```` ```calc id=losses ````).
Attributes are `key="value"`, and a string value is double-quoted. Write
`id="losses"`.

**`calc fence: block name 'Losses' must match [a-z][a-z0-9_-]* -- write 'losses'.`**
Block names are lowercase-hyphen, 1–40 characters — the citation-id and
figure-id shape, not the symbol-shaped calc value names. The message's
suggestion is the fix: `Losses`, `1losses`, and `losses!` all become `losses`.
See [naming a calc block](math.md#naming-a-calc-block).

**`calc block 'losses' is named twice in this item -- first at line 8, again at line 12. A block name can only be used once per item (values already share one item-wide scope); ...`**
Two fences in one item carry the same `id="..."`. Block names are unique per
item, because the values inside the blocks already share one item-wide scope —
the name would disambiguate nothing. Rename one of the blocks ("rename one of
them, e.g. 'losses' -> 'losses_2'"), in both item and page references to it.
The same name in two different items is fine.

**`[[DEC-PWR-001#calc:loess]]: DEC-PWR-001 has no calc block named 'loess' (it names: losses).`**
A `[[…#calc:name]]` fragment in prose named a block the target doesn't have;
the warning lists the names it does. Like any unresolved `[[…]]`, this is a
**warning**, not an error — the build succeeds, and the reference stays in the
text, rendered as an unresolved link. Use one of the listed names. If the
target's blocks are all unnamed, the warning says so and names the fix — add
`id="..."` to the fence; a target with no calc blocks says that instead.

## Checks

**`check refers to 'P_dens', which no calc block defines`**
Name mismatch, or the calc line that defines it failed — fix that error first.

**`check against BND-THM-001, which declares no limit`**
The target needs a `limit` field.

**`check against 'BND-PWR-404', which does not exist`**
The same three explanations as a dangling `satisfies`/`refines` above — typo,
deleted item, or an item renamed while this `against:` was still bare — and the
same remedy. `against:` names a target exactly as a structured link does: a
`DISPLAY-ID@key` composite follows a rename, a bare one does not, and one
writable `refdes check` is what makes it a composite. Write the item's new
display id into `against:` and the next writable load expands it to
`NEW-ID@key`.

**`P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2`**
Not a tool problem. The design does not meet the bound. Change the design,
change the bound, or record in the [design log](design-log.md) that you know.

## The design log

The two sealed-entry errors below come only from a `sealing: build` type —
`log` under `hardware@1`/`hardware@2`, or a project that sets it. The bundled
`hardware@3` `log` is
[history-backed](design-log.md#history-backed-types-sealing-history) and
reports the warnings after them instead.

**`LOG-A-003 is append-only and has been modified since it was sealed`**
Working as designed. Append a new entry with `amends: [LOG-A-003]`. If the edit is
genuinely deliberate, `refdes build --reseal` — it is recorded in
`refdes audit` forever.

**`LOG-A-003 is append-only and was sealed, but no item with that id is in the
project any more`**
The entry was deleted rather than amended. Restore it and append a correction
that `amends` it, or — if the removal really is deliberate — `refdes build
--reseal`, which drops the orphaned seal. If the item was renumbered rather
than removed, record the old id in its replacement's
[`former_ids:`](ids.md#renumbering-former-ids) and this stops firing.

**`LOG-A-003: edited after captured -- current semantic content differs from
the snapshot in captured event <id>`**
A warning, never an error: the entry was captured into `.refdes/history/` and
has been edited since. If the edit was a correction, revert it and append an
entry that `amends` this one; otherwise there is nothing to do.

**`LOG-A-001 has a legacy seal record in .refdes/log-seal-board-a.yaml ... but
is no longer in the project`**
A warning, never an error: an entry that a seal file from before
history-backing mentions was deleted. The record holds a hash only, so restore
the entry from version control if the removal was not deliberate.

**Every log entry reports as modified after a rebase or line-ending change.**
The hash covers content, with whitespace normalised, so this should not happen from
reformatting alone. If it does, check that `.refdes/log-seal.yaml` was committed
and not regenerated on a machine with different content.

**`.refdes/schema.json was older than refdes-project.yaml -- not refreshed (--no-write).`**
The editor-completion schema is regenerated by the commands that load the project,
but `--no-write` suppresses that write. Run without `--no-write` to refresh it; the
same check on a writable pass says `-- refreshed. If your editor's completion
looked stale, it should catch up now.`

## Imports

**`import 'platform': no artifact at ...`**
Build the upstream project first; `items.json` only exists after a build.

**`import 'platform' is pinned to version '2026.3' but the artifact declares '2026.4'`**
Either rebuild upstream at the pinned version or update the pin deliberately.
Expect cascading "does not exist" errors until this is fixed.

**`import 'platform' defines 'IFC-CAN-001', which already exists`**
An ID collision across projects. Give each project its own prefix namespace.

**`... has type 'interface', which this project's schema does not declare`**
A warning. The item renders unvalidated. Add the type to your schema to silence it.

## Citations

**`items/….md:N — citations[0]: page: '2-4' is not a page number -- page: must
be a positive integer, counted from 1.`**
`page:` is one page of the *PDF*, counted from 1 — the same number the rendered
`#page=` fragment opens — so a value that is not one is a declaration error
(refused at load, before any file is opened, at the same severity as a
malformed `section:`). Two of the shapes are not typos the author can see,
because they believe they have cited something:

- **A range** (`2-4`, `2 – 4`). One citation entry names one page, so a span has
  no representation: cite the pages you mean as one entry per page on the same
  `path:`, and each gets its own row and its own `#page=` link. `section:` is
  *not* the alternative — a section title resolves to the one page its heading
  starts on; it is the citation for a heading that moves between revisions.
- **A printed page number** (`xiv`, `iv`, `eight`). A book's front matter is
  numbered in roman numerals, which is where `xiv` usually comes from, and a
  datasheet's own printed page number is a different number from the PDF's.
  Count the PDF's own sheets from 1.

The rest (`0`, `-1`, `1.5`, `9 9`) say what to do in the sentence itself, so
those messages carry no remedy of their own. This is also the one *breaking*
change in the `page:` delta: a `page:` that used to pass now fails, and it is
the only new failure an upgrading project meets. See
[citing a datasheet](markdown.md#citing-a-datasheet).

**`.refdes/citations.yaml:N — unresolved merge conflict: '<<<<<<< HEAD' on line N`**
Two branches both ran `refdes fetch` into this committed file and the merge was
never finished by hand. Each side's `sha256` values are of bytes fetched on a
different day, so neither side is wrong — which is what makes picking one
silently risky. Take one with `git checkout --ours .refdes/citations.yaml` (or
`--theirs`) and commit, or edit the file by hand. `refdes fetch --update`
afterwards regenerates every entry, which re-downloads each cited document:
refdes sends no conditional request, so re-pinning is never free.

**`.refdes/citations.yaml:N — is not valid YAML: …`**
The file does not parse. It is written only by `refdes fetch` and its own header
says never to hand-edit it, so `git checkout -- .refdes/citations.yaml` is
almost always the whole fix.

**`.refdes/citations.yaml:N — citations: is a list, not a mapping of cited path
to that path's record`**
The shape a bad merge resolution leaves: one side's block pasted under the
other's, or a hand edit that dropped the `path: record` nesting. Every key is a
URL or a project-relative file; every value is what `refdes fetch` pinned for it.

**`.refdes/citations.yaml:N — the entry for '…' has sha256 …, which is not a
64-character lowercase hex digest`**
`refdes fetch` records exactly a `hashlib.sha256().hexdigest()` and never edits
it afterwards, so this line was changed by hand or resolved wrongly in a merge.
Note the two shapes that look identical and are not: a *wrong but well-formed*
digest is not reported here at all — nothing offline can tell it from a correct
one, which is what `refdes check --refresh` is for. Only a digest that could not
have come out of a fetch is an error. (An all-digit digest unquoted reads as an
integer, which is one of these; `refdes fetch` quotes those itself.)

**`.refdes/citations.yaml:N — the entry for '…' has no sha256`**
A record missing a field `refdes fetch` always writes. Restore the file, or write
the record out again.

**`.refdes/citations.yaml:N — the entry for '…' has page_count 'eight'`**
`refdes fetch` records a whole number of pages, counted from the bytes it was
pinning. A count that is not a number reads as *no count* to the page check, so
it drops that check silently rather than failing: the same reason the two shapes
that look alike are told apart above. `page_count: 0` is not this error — that is
what a document with no pages in it is recorded as. A record with no
`page_count:` and no `page_count_error:` is not this error either: it claims
nothing about its pages (see [citing a datasheet](markdown.md#citing-a-datasheet))
and the next `refdes fetch` records the count.

**`.refdes/citations.yaml:N — the entry for '…' has both page_count and page_count_error`**
Those are opposites — a count, and the reason there is none — and `refdes fetch`
writes one or the other, never both. Keep the one that is true of these bytes;
the other is a leftover from a merge, and the count wins on every read, so a
stale reason beside it would never be shown to anyone again.

**`.refdes/citations.yaml:N — duplicate key '…' in one mapping (lines N and M)`**
YAML resolves a repeated key to the *last* one and says nothing, so this is the
one shape here that loses a pin **silently**: the file reads as though only one
of the two records was ever pinned, and nothing downstream can notice, because
loading is where the repeat is lost. `refdes fetch` rewrites the whole file from
the mapping it loaded, so the record that lost would simply never be written
back. It is also the shape a bad merge leaves when two branches each pinned the
same document and the resolution pasted both blocks in. Take one block, by hand
or with `git checkout`, and keep the one you mean. (Two identical blocks report
"nothing is lost here" instead — a repeat is still a mistake, but the message
does not claim a record was lost when it was not.)

**`error: .refdes/citations.yaml:N — …` from `refdes fetch`**
`fetch` refuses on a lockfile it cannot read and leaves it **byte-identical**.
That is deliberate: `fetch` rewrites the whole lockfile from the records it
just fetched, so going ahead on one it could not parse would replace every pin
it could not read with a fresh one — and nothing in the tree would say so
afterwards. Fix the file (or delete it, and re-pin) rather than trying to fetch
past it. Every other command reports the same problem as an ordinary error and
exits `1`; none of them reports your citations as unpinned, because it did not
read the file.

**`<project> — could not refresh https://…: <urlopen error [Errno 111] Connection
refused>` from `refdes check --refresh`**
One pinned citation could not be re-fetched, so no comparison was made for it and
the run **exits 1**. It is not drift — drift is a finding, this is a check that
did not happen — and the wording of the second line says which of the two you are
looking at: `N pinned citation(s) could not be refreshed, so upstream drift was
NOT verified`. What to do depends on the cause, and the two are not the same
problem:

- **The origin is gone or the network is down** (connection refused, DNS failure,
  timeout, TLS failure). Wait, or run it somewhere with network. Passing
  `--allow-unreachable` says out loud that you accept an unverified source and
  want the exit code to reflect only real findings — which is the right choice on
  a laptop and the wrong one in a drift guard, because a deleted datasheet then
  passes exactly as a dead network does.
- **The origin answered, and the answer is an error** (`HTTP Error 404`, `500`).
  A 404 on a datasheet that was once pinned almost always means the vendor moved
  or withdrew the file: re-point the citation and `refdes fetch --path <url>`, or
  retire it. The same shape appears for `refdes fetch`, which also reports it as a
  failed citation rather than a changed one.

A partially reachable project reports each unreachable url separately and still
checks and reports every url that answered, so the summary line's error count is
the number of citations to re-check, not the number of citations in the project.
See [`check --refresh`](cli-reference.md#refdes-check).

## Output

**The site looks unstyled.**
`assets/` did not copy, or you opened the HTML from the wrong directory. Serve with
`python -m http.server -d _site 8000`.

**Hover previews do nothing.**
JavaScript is disabled, or `assets/app.js` is missing. Links still work either way.

**A local `![...]()` image src is a build error.**
It does not resolve to a real file relative to your source file's own
directory. That is deliberate — a resolving src is copied into `_site/assets/`
automatically, so a broken one is worth stopping the build over. See [images
and other local files](markdown.md#images-and-other-local-files).

**A `[text](file.pdf)` link 404s in the built site even though the source file
exists.**
Expected — only `<img src>` goes through the resolve-and-copy pipeline; a
plain link's `href` is emitted unchanged. Either declare an opt-in
`site.assets:` directory and point the link at `assets/...`, or — for a
datasheet specifically — use a structured [citation](markdown.md#citing-a-datasheet)
instead of a bare link.

**`UnicodeEncodeError` in a Windows terminal.**
The CLI reconfigures stdout to UTF-8, but if you pipe through another tool set
`PYTHONIOENCODING=utf-8`.

## Getting more detail

`refdes audit` shows suppressed fields, item overrides, resealed entries, and
imports. `_site/items.json` carries every diagnostic under `diagnostics`, with the
same file, line, and item as the console output.
