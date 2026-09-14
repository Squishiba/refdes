# backlog-32-dates — record finding 32 in docs/design/backlog.md

## Task

Record finding 32 ("log entries sort by raw string, not by date, so mixed
date formats silently produce a wrong chronological order") as the next entry
in `docs/design/backlog.md`, matching the internal-review section's voice
(findings 29–31) and finding 25's conversation-decision markers. Edit only
`docs/design/backlog.md` plus this log; no code, no tests, no CHANGELOG.

## Claims verified against the tree (all measured, not copied)

- Three sort sites with key `(str(i.fields.get("date", "")), i.id)`:
  `src/refdes/render.py:82` (inside `_document_sections`, `items.sort`),
  `src/refdes/render.py:118` (inside `_log_entries`, `sorted(...)`),
  `src/refdes/render.py:249` (inside `summary_payload`, `sorted(..., reverse=True)`).
- Zero date parsing/coercion/format validation: no `strptime`, no `isodate`,
  no date-value handling in `src/refdes/schema.py` / `src/refdes/parse.py` /
  `src/refdes/model.py`. `FieldSpec` built at `schema.py:518-526` records
  `type:` as declared, never touches values. The per-type value validation in
  `build.validate_items()` (`build.py:135-183`) dispatches on `enum`
  (`build.py:157`), `limit` (`build.py:166`), and `citations` (`build.py:171`)
  — no `date` branch at all. `type: date` fields (standards
  `hardware/v3/base.yaml:102,174,246` — `last_reviewed`, `decision.date`,
  `log.date`) accept any string today.
- ISO is what the docs/items already use: `docs/authoring.md:45`
  (`date: 2026-03-16`), `docs/design-log.md:24`, `docs/getting-started.md:150`,
  `docs/lifecycle.md:109`, `items/board-a/log.yaml:29`.
- Python-verified string sorts: `'03/16/2026' < '01/05/2026'` is FALSE
  (both MM/DD/YYYY sort January first — chronologically correct, no mis-sort),
  so the task's literal example was wrong as written. `'03/16/2026' <
  '2026-01-05'` is TRUE ('0' < '2' at the first character): a March entry
  written MM/DD/YYYY sorts ahead of a chronologically earlier January entry
  written ISO — the actual mixed-format mis-sort. ISO strings sort
  chronologically (`'2025-12-31' < '2026-01-05' < '2026-03-02' < '2026-03-16'`).
  The recorded example uses this corrected, verified pair and rationale
  ('0' < '2'), deviating from the task's literal example because the literal
  one does not reproduce a mis-sort.
- `date_format:` appears nowhere in the tree (recursive search over
  `*.py/*.md/*.yaml/*.yml/*.txt/*.json`, excluding `.git`) — Status:
  outstanding is truthful.
- Validation-site precedent: `_validate_settings()` at `schema.py:100`;
  unknown settings refused via `_KNOWN_SETTINGS` (`schema.py:68`,
  check at `schema.py:107-119`). Shape precedent in `refdes-project.yaml`:
  `units:` 28-36, `history:` 24-26, `id:` 20-22.
- Suitability rule re-read (`backlog.md:39-84`): loud-failure criterion
  (build refuses to complete), sharp mechanical acceptance test, settled
  design. Verdict recorded: **(not decided — my read): suitable** — the
  current failure is the "reports success while doing nothing" class, but the
  spec's negative test (non-conforming date = hard build error) makes it
  loud, and the five decisions settle the design.

## Edit

- Section header "## Internal review, findings 29–31" → "29–32".
- Entry 32 appended after finding 31 (before the `---` that separates the
  surrogate-keys section): Source line matching 29–31 exactly, two verified
  body paragraphs, five **Decision — ...** paragraphs each with the
  "(Not in the finding — recorded from conversation.)" marker (finding 25's
  pattern; "not from the document" clause omitted because this is internal
  review, not a GitHub attachment), **Status: outstanding**, and a
  **Local model (not decided — my read): suitable** verdict.

## Verification

- `git status --short` shows only `docs/design/backlog.md` and
  `in-prog-logs/backlog-32-dates.md`.
- Every file:line reference in the entry was re-checked against the tree
  (listed above).
- `python -m pytest tests/ -q` — unchanged vs. base (no code touched); count
  in commit report.

## Status

Finished locally; not pushed.