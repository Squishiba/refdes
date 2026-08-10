# Refdes for VS Code

Live diagnostics, ID completion, hover previews, go-to-definition, and inline calc
results for Refdes projects.

## Running it

No build step — it is plain JavaScript.

1. Open `editors/vscode/` in VS Code.
2. Press <kbd>F5</kbd>. A second window opens with the extension loaded.
3. In that window, open a folder containing a `refdes.yaml`.

If `refdes` is not on your PATH, point the setting at your virtualenv:

```json
{
  "refdes.command": ".venv/Scripts/python.exe -m refdes.cli"
}
```

To install it properly instead of debugging it: `npx vsce package` and then
**Extensions → … → Install from VSIX**.

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
their titles. After a field name like `status:`, you get that field's allowed
values from the schema.

**Hover.** Hover any ID for its type, title, key fields, coverage stage, and any
failing checks.

**Go to definition.** <kbd>F12</kbd> or ctrl-click an ID to jump to where it is
defined, including inside a list file.

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
- **Snippets** for new requirements, decisions, and log entries.
