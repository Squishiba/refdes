# Troubleshooting

Every diagnostic leads with `file:line`, so most of these point straight at the
problem. Errors fail the build; warnings do not.

## Items and fields

**`no refdes.yaml found in ... or any parent directory`**
You are not inside a project. `cd` into one, or pass `-c path/to/refdes.yaml`.

**`item has no 'type'`**
Add `type:` to the item, or to `defaults:` in the list file.

**`unknown type 'requirment'. Did you mean 'requirement'?`**
Typo, or a type not declared in `refdes.yaml`.

**`no YAML front-matter (file must start with '---')`**
A `.md` file under `items/` needs front-matter. If it is not an item, move it out
of `items/`.

**`unknown field 'sorce'. Did you mean 'source'?`**
A warning. The value is kept but not validated. Fix the spelling or declare the
field in the schema.

**`missing required field 'text'`**
The schema marks it `required: true`. Note requirements use `text`, decisions and
constraints use `title`.

**`status: 'in-review' is not one of ['draft', 'open', 'accepted', 'retired']`**
Use one of the declared `choices`, or add yours to the schema.

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
Typo in the id, or in the `prefix:` — fix whichever one is wrong. Never
auto-corrected: it's the string every link and the ledger are keyed on.

## Links

**`satisfies points at 'REQ-PWR-009', which does not exist`**
Typo, deleted item, or a failed import. Check the import errors first — they
cascade.

**`satisfies may point at ['requirement'], but BND-THM-001 is a bound`**
Wrong link type. A decision `satisfies` requirements and is `constrained_by`
bounds.

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

**Every log entry reports as modified after a rebase or line-ending change.**
The hash covers content, with whitespace normalised, so this should not happen from
reformatting alone. If it does, check that `.refdes/log-seal.yaml` was committed
and not regenerated on a machine with different content.

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
