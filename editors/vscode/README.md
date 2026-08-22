# Refdes for VS Code

Live diagnostics, ID completion, hover previews, go-to-definition, and inline calc
results for [Refdes](https://github.com/Squishiba/refdes) projects — reference
documentation for hardware design decisions.

## Setup

This extension is a thin client over the `refdes` command line tool, so **install
that first**:

```
pip install refdes
```

Then open any folder containing a `refdes.yaml`. The extension activates on its own.

If `refdes` is not on your `PATH` — for instance it lives in a project virtualenv —
point the setting at it:

```json
{
  "refdes.command": ".venv/Scripts/python.exe -m refdes.cli"
}
```

A status bar item appears once the project loads. If it never shows up, the
extension could not run the CLI; check the setting above.

## What it does

**Inline calc results.** Evaluated values appear greyed at the end of each line in
a `calc` block, updating on save:

```calc
V_out            = 3.3 V                          → 3.3 V
P_diss  : W      = V_out * I_load * (1/eff - 1)   → 0.2981 W
P_dens  : W/in^2 = P_diss / A_board               → 0.2366 W/in²
```

Values with tolerance show their bounds; a failed line shows the error inline.
Toggle with **Refdes: Toggle inline calc results**.

**Diagnostics.** Errors and warnings appear as squiggles and in the Problems panel,
refreshed on save. Includes everything the CLI reports — unit mismatches, failing
checks, broken links, unverified requirements, append-only violations.

**Completion.** Type two or more uppercase letters, or `[[`, to get item IDs with
their titles. Matching isn't limited to the id and title: the file an item is
declared in and its board (when the project has boards) are also part of what
gets matched, so typing `power` narrows the dropdown to items declared in
`power.yaml`, or on the `power` board, even before you remember how its id
starts. After a field name like `status:`, you get that field's allowed
values from the schema. At the start of a front-matter line, once the current
item's `type:` is known from context, you get that type's own field and link
key names — the same data, just a second way of using it, and the piece that
closes the gap `.yaml`'s `yaml.schemas` completion (below) can't reach for
`.md` files.

**Schema completion for `.yaml` list files.** This extension declares
`redhat.vscode-yaml` as a dependency and `refdes init` writes
`.vscode/settings.json` pointing `yaml.schemas` at `.refdes/schema.json` —
together they give full IntelliSense (required fields, `additionalProperties:
false` catching a typo the moment it's typed, hover documentation) for
`items/**/*.yaml`. This does **not** currently work for `.md` front matter —
an upstream vscode-yaml limitation, not a refdes gap — which is what the
field/link key completion above exists to cover in the meantime. See [editor
support](https://github.com/Squishiba/refdes/blob/main/docs/standard-library.md#editor-support-json-schema-emission)
for the full story.

**Hover.** Hover any ID for its type, title, key fields, coverage stage, and any
failing checks.

**Go to definition.** <kbd>F12</kbd> or ctrl-click an ID to jump to where it is
defined, including inside a list file or a multi-item markdown file (several
`---`-fenced items sharing one `.md` file, optionally under a leading
`defaults:` block).

**Syntax highlighting** for `calc` blocks in both markdown and YAML bodies —
variables, units, unit assertions, numbers, functions, and tolerances.

**Commands** (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>):

| Command | Does |
|---|---|
| Refdes: Build site | `refdes build --keep-going` |
| Refdes: Check | `refdes check` |
| Refdes: Allocate missing IDs | `refdes id` |
| Refdes: Open built site | Opens `_site/index.html` |
| Refdes: Refresh index | Re-reads the project |
| Refdes: Toggle inline calc results | Show/hide the inline values |

A status bar item shows item count and error count; click it to run a check.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `refdes.command` | `refdes` | How to invoke the CLI |
| `refdes.checkOnSave` | `true` | Re-index and publish diagnostics on save |
| `refdes.showCalcResults` | `true` | Inline calc values |

## How it works

Everything comes from one call to `refdes index --compact`, which emits the
whole project as JSON — items, fields, links, source locations, calc results,
coverage, and diagnostics — without rendering the site. The extension has no parser
of its own, so it cannot drift from the real tool.

The one exception is the TextMate grammar, which necessarily re-implements the unit
lexer. If highlighting and the parser ever disagree, the parser is right.

## Not yet

- **Live preview pane.** "Open built site" opens the built HTML in a browser. A
  proper in-editor webview with auto-refresh is the obvious next step.
- **Diagnostics as you type.** Currently on save; live would need debounced runs
  against unsaved buffers.
- **Snippets** for new requirements, decisions, and log entries, inserted directly
  in the editor. `refdes new <type>` covers the same need today from the CLI —
  `refdes new decision > items/power/dec-005.md` — generated from the identical
  resolved schema, just not yet wired into VS Code's own snippet/IntelliSense UI.

## Developing

No build step — it is plain JavaScript. Open `editors/vscode/` in VS Code and press
<kbd>F5</kbd>; a second window opens with the extension loaded. Open a folder
containing a `refdes.yaml` in that window.

## Licence

MIT.
