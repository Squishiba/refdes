# User-simulation release gate — run 10 (12bbf6b..main as an author)

Report-only: no code/docs/test changes. All claims produced by running this
branch's code (`PYTHONPATH=<worktree>/src … python -m refdes.cli`, refdes
0.5.0, Python 3.13) in fresh projects under `.scratch/run10/`, each from
`refdes init` (hardware@3). One harness: `.scratch/rr <proj> <args…>` (cd's
inside the script); `RR_SRC=<dir>` repoints it at the pre-delta src from
`git archive 12bbf6b src | tar -x -C .scratch/old12bbf6b` (§3.1).

Delta src commits (`git log --oneline 12bbf6b..main -- src/`): 6d104be
(#323), 037d263 (#324, docs), 18c5d75 (#322).

## 0. Headline summary

#322 works on the shape it targets: fires at the fence's opening line, names
key(s) and type, and its remedy (move to front matter) verified end-to-end —
after the move the previously-silent check runs and reports the violation.
Fires for `yaml`/`yml`/`YAML`, fence attributes, `~~~yaml`, indented fences
in list items, two fences (each key at its own line), list-file `body:`, on
log/component/bound; silent for other types' fields, non-mapping, scalar,
unparseable fences. Gaps are all in "which keys count as the item's own":
**R10-F1** link verbs in a body fence are inert and silent (medium);
**R10-F2** `type:`/`id:` silent; **R10-F3** a fence inside a blockquote
renders as a real code block and is silent; **R10-F4** a yaml example inside
a ` ```text ` fence warns, with a nonsense remedy.

#323(a) is correct and actionable in every case tried (0/1/many named blocks,
unnamed fences, misspelt name, name from another item, two refs, a
component); the "add `id=`" chain verified to the end. **R10-F6**:
`[[ID#calc:]]` (colon, empty name) is silent dead text. **R10-F7** (nit):
the "add `id=`" hint fires for a fence that has one.

#323(b) holds on every live-edit case (rename/add/remove label silent; row
edit fires; prose fires; re-wrap silent; audit lists and drops). The upgrade
case breaks: an item captured with a **labelled** fence under pre-#323 code
reports `edited after captured` under main with no edit, and the remedy the
commit's own changelog names (`refdes history capture`) is refused —
**R10-F5 (medium)**, the release blocker of this run. Adjacent:
**R10-X1** `---` inside a fenced block splits the item (pre-existing).

## 1. #322 — the inert body-fence warning

Base (`checks:` as a body fence on a log, fence opens at line 10):
`WARNING items/pwr/LOG-PWR-001.md:10 [LOG-PWR-001] — a ```yaml fence in this
item's body declares 'checks' -- a field of type 'log'. … Move it into the
item's front matter …` — exit 0; the fenced check is inert (`eff = 0.85` vs
`>= 0.90` bound: 0 errors). Remedy verified: checks in front matter →
`ERROR … eff violates BND-THM-002: worst case 0.85 vs >= 0.90`, exit 1.

Spellings swept (19 items, one project): fires — ` ```yaml `, ` ```yml `,
` ```YAML `, ` ```yaml title="demo" `, ` ~~~yaml `, 2-space-indented fence
in a list item, 4-space-indented (markdown code block), two fences (two
warnings, each key at its own opener), one fence two keys (`'summary',
'status' … fields`, plural), `checks:` on a component, `limit:` on a bound
(plus its `missing required field` proof of inertness), list-file `body: |`
(warning at the item's source line). Silent — `part_number:` on a log
(other type), a list fence, a scalar fence, an unparseable fence.

`check` and `build` identical (same lines; exit 0 with warnings, 1 with
errors); `ls`/`index` do not validate (exit 0, silent). Warnings do not gate
`release` (project with 2 fence warnings: gate FAILs were draft_items /
uncovered_requirements, never the warnings).

**R10-F1 (medium): a body fence declaring a LINK verb is inert and silent.**
Repro (log item, body):

```markdown
```yaml
satisfies: [REQ-PWR-001]
```
```

`refdes check` → 0 warnings; `refdes index` → the item's `links: {}` (the
verb never landed, coverage silent). Expected: the same warning as `checks:`
— `refdes schema` lists `satisfies` in the log's properties and `refdes new
log` prints `# satisfies: []  # target: requirement, bound` as a
front-matter line, so every documented surface presents verbs and fields
uniformly, and a verb in a body fence is the identical trap. Saw: silence.
`declares_inert_keys` is keyed on `spec.fields` (src/refdes/build.py:350);
link verbs live outside it.

**R10-F2 (low): `type:`/`id:` in a body fence are inert and silent** (not in
`spec.fields` either). Low: docs/checks.md's front-matter example pasted as
a fence does warn — on `summary` and `checks` — naming two of the four inert
keys.

**R10-F3 (low): a fence inside a blockquote is inert and silent.** Repro:

```markdown
> ```yaml
> checks:
>   - value: eff
>     against: BND-THM-002
> ```
```

`refdes check` → 0 warnings; `refdes build` renders
`<blockquote><pre><code class="language-yaml">checks: …` — the R9-F1 trap
exactly. `_YAML_FENCE_RE` anchors at `^[ \t]*`, so the `> ` prefix
disqualifies the fence (src/refdes/build.py, #322). Quoting "the config you
meant to add" in a log body is a natural idiom.

**R10-F4 (low, false positive): yaml example code inside an outer fence
warns.** A documentation item with the example inside a ` ```text ` fence
(inner fence indented; markdown keeps it literal inside the outer one,
verified in the built page) gets `WARNING … declares 'status' -- a field of
type 'log' … Move it into the item's front matter` — the remedy is nonsense
for example code. The commit's "narrow by construction" covers fences
*without* a declared-field key, not example fences containing one.

## 2. #323(a) — the bare `#calc` fragment hint

Targets: LOG-A (block `losses`), LOG-B (`losses`+`heat`), LOG-C (two
unnamed fences), LOG-D (no calc), CMP-F2 (component, `burn`).

| Reference | Tail | Verdict |
|---|---|---|
| `[[LOG-A#calc]]` | `did you mean #calc:<name>? it names: losses.` | correct |
| `[[LOG-B#calc]]` | `it names: losses, heat.` | correct |
| `[[LOG-C#calc]]` | `add id="..." to a calc fence to give a block a name.` | correct |
| `[[LOG-D#calc]]` | plain field-miss, no hint | as documented |
| `[[CMP-F2#calc]]` | `it names: burn` | correct |
| two bare refs, one body | two hints, each naming its own target | correct |
| `[[LOG-A#calc:losses]]` | no warning; renders `href="log-a.html#calc-losses"`, anchor on target | good |
| `[[LOG-A#calc:losses2]]` | `has no calc block named 'losses2' (it names: losses).` | good |
| `[[LOG-A#calc:heat]]` (name from LOG-B) | names LOG-A's own blocks | correct |
| `[[LOG-A#calcs]]` | plain sentence, no hint | "every other field miss keeps its plain sentence" holds |
| `[[LOG-A#calc:]]` | **no warning**; page shows literal `see [[LOG-A#calc:]]` | R10-F6 |

Remedy chain end-to-end: add `id="first"` to a LOG-C fence → Z3's warning
updates to `it names: first` → `[[LOG-C#calc:first]]` resolves, 0 warnings.

**R10-F6 (low): `[[ID#calc:]]` (colon, name left off at the colon) is silent
dead text.** `#calc`, `#calcs`, and misspelt names all warn; the empty-name
form drops out of the link pattern entirely — the mid-edit author state
gets no nudge. Expected the bare-fragment hint, or a "fragment has no name".

**R10-F7 (nit): the "add `id=`" hint fires for a fence that has one.** A
target whose fence line is invalid (` ```calc id="burn" title="Burn-in" ` —
already a build ERROR naming the unknown attribute) is treated as unnamed,
so the hint says "add `id=\"...\"` to a calc fence". The fence error in the
same output names the real problem, so this is redundancy, not misdirection.

## 3. #323(b) — calc-fence labels out of the semantic digest

`c323`: LOG-OLD (prose + ` ```calc id="losses" `), captured with main's
`refdes history capture`. Each edit applied, `refdes check`, reverted:
rename label → silent; remove → silent; add back → silent; edit a row in
the fence → **fires** (rows stay content); add a prose word → **fires**;
re-wrap the captured sentence across lines, same words → silent.
`refdes audit` lists the item under "Entries edited after captured" and
drops it on revert. Warning under `check` and `build`, exit unmoved; the
`captured_edits` release gate is off by default (model.py:114).

### 3.1 R10-F5 (medium): the upgrade case — the changelog's remedy does not work

`e1`: one log with a **labelled** fence, captured by the **pre-#323** code
(`RR_SRC=.scratch/old12bbf6b/src refdes history capture LOG-E1`), then
main's code, author edits nothing:

```console
$ refdes check                # main's code
WARNING items/t/loge1.md:2 [LOG-E1] — LOG-E1: edited after captured -- current
semantic content differs from the snapshot in captured event 5b90b938-…. If
the edit was a correction, revert it and append a new entry with
`amends: [LOG-E1]` instead; otherwise there is nothing to do.
$ refdes audit
Entries edited after captured:
  LOG-E1  (captured event 5b90b938-…)
```

`build` fires it identically. The commit's changelog
(`changelog.d/calc-fence-label-not-semantic.changed.md`) anticipates this
—"an item captured *with* a labelled fence under the old digest gets one
(warning-only, never build-failing) `edited after captured` line on the
first build after upgrading, **which a `refdes history capture` of the entry
settles**". It does not. The author tries, in order:

- `refdes history capture LOG-E1` → `LOG-E1 is already captured; nothing was
  written` (cli.py:2617) — capture is one event per item (help +
  cli-reference.md:1990), so the digest refresh the upgrade needs is exactly
  the command that refuses. Warning persists.
- Remove the label (the obvious "make the text match" move) → persists (main
  hashes the unlabelled body against a digest that contains the label text).
  Restore it → persists. The warning's own advice ("revert it… otherwise
  there is nothing to do") is a dead end: there is no edit to revert.
- Only `refdes history redact LOG-E1 --confirm` clears it (verified: check
  → 0, audit → `(none)`) — by destroying the capture event, an irreversible,
  privacy-shaped hammer whose own output warns it "cannot remove data
  already committed to Git". Capture afterwards works and is quiet.

Reverse split is symmetric: a labelled item captured on **main** warns under
the **old** code's check (`f1`). Forward upgrades are clean: an item
captured pre-#323 with an **unlabelled** fence and labelled afterwards is
silent under main (`e2` — the case the fix was for), warning only under old
code. Expected: the changelog's stated remedy to clear the warning. Saw: a
permanent false warning for every project that captured a labelled calc
fence before upgrading, with no working documented fix; the byte-for-byte
digest guarantee covers unlabelled items only, which is exactly why
labelled captures break, and no docs page tells a project with labelled
captures to expect it.

## 4. Adjacent trips (outside the delta)

- **R10-X1 (medium, pre-existing): `---` inside a fenced code block splits a
  markdown item file.** Pasting docs/checks.md's front-matter example as a
  ` ```yaml ` fence in an item body (content `---\nid: LOG-PWR-001\n…\n---`)
  creates a *live second item* from the fenced text: `ERROR duplicate id
  'LOG-PWR-001'` and `ERROR … check refers to 'eff', which no calc block
  defines` (the fenced `checks:` became a real field; `refdes ls` lists the
  phantom). The splitter honours `---` at line starts inside fences
  (authoring.md's Sections rule, no fence exception). This defeats #322 for
  that shape: no inert-fence warning, and the "example" is live.
- docs/checks.md's "Declaring a check" now shows the front-matter shape and
  names the inert-fence trap — the R9-F1 origin story is closed.

## 5. Not covered

`serve`/editor flows; custom types via presets/overlays (a body fence
declaring a custom field should fire, same code path, unverified here);
keys-adopted projects; history sealing interactions.
