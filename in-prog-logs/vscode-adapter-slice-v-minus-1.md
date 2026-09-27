# Slice V−1 — make the VS Code shell alive (activation marker rename)

Task: `docs/design/editor-vscode-adapter.md` §8, "Slice V−1 — make the shell
alive (a bug fix, not a feature)". Branch `fix/vscode-adapter-activation`.
Status: **finished** — committed (`82f1140`), pushed, PR opened:
https://github.com/Squishiba/refdes/pull/58. CI green on all three jobs —
`gh pr checks 58 --repo Squishiba/refdes --watch`: ubuntu-latest pass 3m39s,
ubuntu-latest / py3.13 pass 2m43s, windows-latest pass 6m7s.

## The bug, as the design doc states it

`docs/design/editor-vscode-adapter.md:98-111` (§2.3): `findRoot()` walks up
looking for `refdes.yaml` and `activationEvents` is
`["workspaceContains:**/refdes.yaml"]`, but `refdes.yaml` is retired
(`AGENTS.md` "The project config is two files; `refdes.yaml` is retired";
`src/refdes/schema.py:47` `LEGACY_CONFIG_NAME = "refdes.yaml"`; the walk rule
at `src/refdes/schema.py:341`). So as shipped the extension never activates in
a current project, and §8 calls the rename Slice V−1: "`findRoot` and
`activationEvents` point at `refdes-project.yaml` (`extension.js:44`,
`package.json:27`); the warning text follows (`extension.js:423`); README
setup follows."

## Changes made

`editors/vscode/extension.js`

- `:39` docstring — `/** Walk up from a path looking for refdes-project.yaml. */`
- `:44` — `if (fs.existsSync(path.join(dir, "refdes-project.yaml"))) return dir;`
- `:423` — `vscode.window.showWarningMessage("Refdes: no refdes-project.yaml found.");`

`editors/vscode/package.json`

- `:27` — `"activationEvents": ["workspaceContains:**/refdes-project.yaml"],`

`editors/vscode/README.md` (the "README setup follows" part of §8)

- `:16` — "Then open any folder containing a `refdes-project.yaml`. The
  extension activates on its own."
- `:128` (Developing section) — "Open a folder containing a
  `refdes-project.yaml` in that window."

`changelog.d/calc-project-equations.added.md`

- `:2` — "`equations:` block in `refdes.yaml`" → "`refdes-project.yaml`".
  Found by the repo-wide grep the task asked for. Verified the claim, not just
  the name: `src/refdes/calc.py:330` documents an equation as "declared in
  `refdes-project.yaml`'s `equations:`", and `docs/math.md:393` says the same,
  so the fragment was pointing users at a retired file.

## Verification

- `grep -rn "refdes\.yaml" editors/vscode` → no matches (exit 1). All five
  occurrences that were there (`extension.js:39,44,423`, `package.json:27`,
  `README.md:16,128` — six lines, five sites plus the docstring) are renamed.
- `node --check editors/vscode/extension.js` → parses OK.
- `python -m json.tool editors/vscode/package.json` → valid JSON;
  `activationEvents` reads `["workspaceContains:**/refdes-project.yaml"]`.
- Test suite: `editors/vscode/` has **no** JS test suite — `package.json` has
  no `scripts` and no `devDependencies` keys (`grep -n "scripts\|devDependencies"
  editors/vscode/package.json` → no matches), and there are no `.js` test files
  in the directory (`ls editors/vscode` → LICENSE, README.md, extension.js,
  icon.png, package.json, syntaxes/). That matches the design doc's own note at
  `docs/design/editor-vscode-adapter.md:558-561` ("There is no JS test harness
  in the repo today"). So the JS change is verified by parse + grep only.
- Python suite run anyway (`python -m pytest -q`, repo root) since a changelog
  fragment in `changelog.d/` was touched and `tests/test_docs_examples.py`
  exists: **2456 passed, 2 skipped in 159.38s**. No Python source changed, so
  this is a no-regression check rather than a test of the fix.

## Follow-up recommended, not done here

`docs/design/editor-vscode-adapter.md:575-579` names
`test_extension_activates_on_current_project_marker` — a pytest assertion that
`package.json`'s `activationEvents` and `extension.js`'s `findRoot` name
`refdes-project.yaml` and neither names the retired name. That test does not
exist in `tests/` (`grep -rln "activationEvents\|findRoot\|editors/vscode"
tests` → no matches), so this fix currently has no automated guard. It is
listed in the design doc's §7.2 test plan alongside the V0 `ServeClient`
tests, and the task scoped this change to the rename, so it was left out; it
is cheap and worth landing with V0 (or alone).

## Other `refdes.yaml` references found repo-wide, and why they were left

`grep -rn "refdes\.yaml" . --exclude-dir=.git` also hits these. Each was
checked and deliberately **not** changed:

- `src/refdes/schema.py:5,47,55,341` — the legacy-name constant and the
  retirement error text. Intentional; this is the code that *rejects* the old
  name.
- `tests/test_config_split.py:104,113,124,126,129` and `tests/conftest.py:38`,
  `tests/test_schema_json.py:208` — tests asserting the retirement error, and
  comments describing the split. Intentional.
- `docs/troubleshooting.md:13,21` — quotes the retirement error and tells the
  user to delete `refdes.yaml`. Intentional.
- `CHANGELOG.md:634,635,669,752,861,871,920` — released history. Not rewritten.
- `changelog.d/config-split-two-files.breaking.md:1,10,12,14,16` — the fragment
  that *announces* the retirement. Intentional.
- `docs/design/standard-library.md`, `docs/design/lifecycle.md`,
  `docs/design/backlog.md` — design documents describing the pre-split world
  they were written in; rewriting them rewrites design history, and
  `backlog.md:929` explicitly says "`refdes.yaml` is retired".
- `items/*.yaml` (7 comment lines: `components/power.yaml:7`,
  `constraints/thermal.yaml:7`, `tests/power.yaml:6`, `requirements/power.yaml:10`,
  `board-b/requirements.yaml:2`, `board-a/log.yaml:12`,
  `decisions/dec-pwr-001-regulator-topology.md:10`) — stale comments in the
  sample project pointing at the `boards:` registry, which now lives in
  `refdes-project.yaml`. Genuinely stale, but unrelated to the VS Code
  adapter, and `items/` content is what the build/hash/seal tests read, so
  touching it is a separate change with its own verification. Left for a
  follow-up; noted here so it is not lost.
- `in-prog-logs/*.md` — historical logs of the sessions that did the split.
- `docs/design/editor-vscode-adapter.md:99,101,109,470,578` — the design doc
  describing this very bug. Left as-is: §2.3 is a description of the shipped
  defect, and rewriting it would erase the thing Slice V−1 fixes.

## Difficulties

None material. The only judgement call was how far the "don't leave a fourth
instance behind" instruction reaches: it is scoped to `editors/vscode/` (where
the README was the fourth and fifth site), and beyond that directory each hit
was verified as either intentional legacy handling / history, or a genuinely
stale reference outside this slice's blast radius (the `items/` comments, the
`calc-project-equations` fragment — the latter fixed because it is a pending
user-facing changelog bullet naming a file that no longer exists).

## Not done (out of scope, by instruction)

Slice V0 (hover facts from `GET /api/item/<ref>`, CodeLens "Open in editor",
`ServeClient`, status bar states) — untouched. No server code touched.
