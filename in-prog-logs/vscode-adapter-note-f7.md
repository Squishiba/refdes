# vscode-adapter-note-f7

Labelling the VS Code adapter's test-coverage gap in `editors/vscode/README.md`,
per F7 of `in-prog-logs/user-sim-release-gate-run2.md`.

Status: **finished.**

## What F7 claimed

Run 2's F7: the README describes activation, completion, diagnostics and the
serve panel as though they were verifiable features, but there is no headless
harness, no `.vscode-test` setup, and no note that verifying the surface
requires a real VS Code. Run 2's own coverage-gap list (item 3) says the same
thing from the other direction: "Until that exists, this surface is ungateable
and should be labelled as such in the README."

## Confirming the gap before writing it down

Ran, from the repo root:

```
$ find editors/vscode -iname "*test*"
$ find editors/vscode -type f -not -path "*/.git/*"
editors/vscode/extension.js
editors/vscode/icon.png
editors/vscode/LICENSE
editors/vscode/package.json
editors/vscode/README.md
editors/vscode/serveClient.js
editors/vscode/syntaxes/calc.injection.json
editors/vscode/.vscodeignore
editors/vscode/.vscode/launch.json
```

`find -iname "*test*"` returns nothing — zero paths. The full file list is nine
files, none of them a test.

```
$ grep -rn "vscode-test\|@vscode/test\|vscode\.test\|test-electron\|mocha.*vscode" \
    --include="*.json" --include="*.js" --include="*.md" --include="*.toml" \
    --include="*.yml" --include="*.yaml" .
```

Every hit is prose in a doc, not configuration:

- `editors/vscode/.vscodeignore:3` — the single hit inside the extension itself,
  and it is a *packaging* line listing `.vscode-test/` as something to exclude
  from a `.vsix`. The directory it names does not exist. It is a leftover
  expectation, not a harness.
- `docs/design/editor-vscode-adapter.md:72-73` — "` .vscodeignore` already
  lists `.vscode-test/` — the output directory of `@vscode/test-electron`. A
  test harness was anticipated and never built."
- `docs/design/editor-vscode-adapter.md:558` — "There is no JS test harness in
  the repo today (no `scripts`, no `devDependencies`; `.vscodeignore` merely
  anticipates `.vscode-test/`)."
- `in-prog-logs/user-sim-release-gate-run2.md:397,531` — F7's own text.

```
$ python3 -c "import json; print(json.load(open('editors/vscode/package.json'))['scripts'])"
{}
$ ... ['devDependencies']
None
```

No `scripts` key at all, no `devDependencies` key at all. The design doc's
§7.2 claim matches what I measured independently.

The gap is therefore real, and the design doc at
`docs/design/editor-vscode-adapter.md` is the existing record of it — but that
doc is a *proposal* that starts from "there is no harness", so a reader of the
README has no signal at all.

## What I changed

`editors/vscode/README.md` only, two sentences appended to the existing
**Developing** section (the README has no separate "Testing" section;
"Developing" is the section a person lands in when asking "how do I work on
this", so it is where a coverage gap belongs). I deliberately did not link to
`docs/design/editor-vscode-adapter.md` §7.2: that section lays out a proposed
pytest-over-`node` approach, and the brief was explicitly to state the gap
without inventing or promising a plan. A link would read as a commitment.

Placement, for the record: after the `<kbd>F5</kbd>` / Extension Development
Host paragraph, as the last thing before `## Licence`.

## Difficulty

None worth recording. The only judgement call was tone, re-read once after
placing it: the first draft said "unfortunately" and "sadly untested"-adjacent
phrasing that made it read as a complaint, so I cut those. It now states the
gap and stops, which matches how `docs/design/*.md` status headers and run 1 /
run 2 of the gate state their own limits.
