# Task: record §11 decisions in docs/design/named-calc-blocks.md (2026-09-24)

Decisions-recording only — no implementation, per the task.

## What was done

- Merged origin/main first (already up to date; branched
  `ao/refdes-154/named-calc-blocks-decided` from it).
- Status line: `proposed` → **Architecture decided (2026-09-24)**, calling out
  that §11.5 (`name=` → `id=`) is the one recommendation not taken as written.
- §11 retitled "Questions — decided (Jared, 2026-09-24)" in the
  thread-workbench.md §7 house style; each of the ten questions now reads
  **Decided: …** with the confirmation wording from Jared's answers. §11.5 and
  §11.6 carry the fuller rationale (Jared's "calc blocks behave like items"
  quote; the bulk-import reasoning that was given when he asked why).
- The `name=` → `id=` rename (decision 5) applied document-wide: the Decision
  recap (A), §3.1 syntax example, §3.3 grammar (`attribute = "id=" …`) plus a
  new §3.3 bullet recording why the key itself changes, §3.4's error examples
  (the old `naem=` misspelling example became `name="losses"` — the
  earlier-draft key, now an unknown attribute, which doubles as the migration
  note), §2's silent-acceptance examples, all §7 error/warning messages, the
  §8 worked example fences, and the §10 test descriptions.
- Deliberately NOT touched: calc *value* names (`P_diss`, `V_in`, §4 in
  general), the `#calc:` fragment prefix, and the HTML anchors
  `id="calc-<name>"` / `id="calc-losses"` (already `id`, unrelated).
- §13 phasing header checked — it never referenced `name=`, no change needed.

## Verification

- `grep 'name="'` over the doc: only the two intentional historical mentions
  (§3.4's unknown-attribute example, §11.5's question text) remain.
- `python -m pytest -q`: 2045 passed.

Status: finished. PR opened against main, not merged (per instructions).
