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
`types:`/`link_types:`/`field_sets:` into the optional `refdes-schema.yaml`
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

**`unknown field 'sorce'. Did you mean 'source'?`**
A warning. The value is kept but not validated. Fix the spelling or declare the
field in the schema.

**`missing required field 'text'`**
The schema marks it `required: true`. In the bundled standard, `requirement` and
`bound` use `text`; `decision`, `test`, and `component` use `title`.

**`status: 'in-review' is not one of ['draft', 'active', 'retired']`**
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

**`key 'k7f3m2q9x4c' is malformed: expected exactly 11 characters`** /
**`key 'k7f3m2q9x4c' is malformed: contains a character outside the key alphabet`** /
**`key 'k7f3m2q9x4c' is malformed: check character mismatch (Expected check character 'a'.)`**
The key line in the source file has been corrupted (edited by hand, merge conflict,
or encoding issue). Keys are written by `refdes` and never edited by hand.
**Remedy:** restore the line from git (`git checkout -- <file>`).

**`key 'k7f3m2q9x4a' on REQ-PWR-004 (items/requirements/power.yaml:12) is already used by REQ-PWR-007 (items/requirements/power.yaml:19)`**
Two items share the same surrogate key — a line was duplicated (copy-paste,
merge conflict, or a botched edit). A key is unique by construction.
**Remedy:** delete the `key:` line from one of the items and rebuild — it will be
re-minted with a fresh key.

**`key changed since baseline 'rev-b': was 'k7f3m2q9x4a', now 'm9n2b5v8c1x'. A key never changes legitimately.`**
An item's surrogate key differs from what was recorded in the latest baseline.
This means the `key:` line was edited or replaced.
**Remedy:** restore the old key from git; if the item genuinely is a new one,
delete the `key:` line and let it be re-minted, and give it a new display `id:`
too.

**`key deleted since baseline 'rev-b': was 'k7f3m2q9x4a', now no key is declared. A key never disappears legitimately.`**
An item that had a key at baseline time no longer has one.
**Remedy:** restore the old key from git; if the item genuinely is a new one,
delete the `key:` line (if any) and let it be re-minted, and give it a new
display `id:` too.

**`older baseline 'rev-a' references key 'k7f3m2q9x4a' for REQ-PWR-002, which no current item declares. The item may have been deleted legitimately; this is audit information, not a build error.`**
An older baseline (not the latest) contains a key that no live item has. This
is informational — the item was likely deleted. `refdes audit` reports this so
you can verify it was intentional.
**Remedy:** if the item was deleted on purpose, nothing to do. If it was
renamed, ensure its `former_ids:` records the old display id.

**`refines points at key k7f3m2q9x4a (labelled REQ-PWR-002), which no item declares. The label may be stale; the key is what resolves. Either the target was deleted, or this reference predates it.`** /
**`check against key k7f3m2q9x4a, which no item declares. Either the target was deleted, or this reference predates it.`**
A structured link or `checks: against:` entry references a surrogate key that no live item has. The display label (if present) may be stale; the key is the immutable identity used for resolution. This happens when a target item was deleted, or the reference was written before the target existed.
**Remedy:** if the target was deleted, remove the link or `checks:` entry. If the target should exist, ensure it has a `key:` line (run a writable command to mint missing keys) and that the key matches.

## Links

**`satisfies points at 'REQ-PWR-009', which does not exist`**
Typo, deleted item, or a failed import. Check the import errors first — they
cascade.

**`constrained_by may point at ['bound'], but REQ-PWR-002 is a requirement`**
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
`N·m` and `J` are dimensionally identical. Pin it: `tq : N*m = ...`.

## Checks

**`check refers to 'P_dens', which no calc block defines`**
Name mismatch, or the calc line that defines it failed — fix that error first.

**`check against BND-THM-001, which declares no limit`**
The target needs a `limit` field.

**`P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2`**
Not a tool problem. The design does not meet the bound. Change the design,
change the bound, or record in the [design log](design-log.md) that you know.

## The design log

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

**Every log entry reports as modified after a rebase or line-ending change.**
The hash covers content, with whitespace normalised, so this should not happen from
reformatting alone. If it does, check that `.refdes/log-seal.yaml` was committed
and not regenerated on a machine with different content.

**`.refdes/schema.json was older than refdes-project.yaml -- not refreshed (--no-write).`**
The editor-completion schema is regenerated by every command that loads the
project, but `--no-write` suppresses that write. Run without `--no-write` to
refresh it.

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
