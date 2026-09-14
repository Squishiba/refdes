date-format-fix progress

- Sync: `git merge --ff-only main` succeeded with `Already up to date.` before any edits.
- Grounding: confirmed all three log sort sites in `src/refdes/render.py` sort `str(date)` lexicographically (`_document_sections`, `_log_entries`, and `summary_payload`).
- Grounding: confirmed `src/refdes/build.py::validate_items` validates enum, limit, and citations field types but has no date branch. Repository search found no date-field parsing, coercion, format validation, or `date_format` setting; the only datetime usage creates unrelated ISO timestamps in citations/lifecycle code.
- Setting path: `src/refdes/schema.py::_validate_settings` resolves project-level defaults into `Project`; `docs/schema-reference.md` is the existing complete reference for `refdes-project.yaml` settings.
- Changelog category decision: use `fixed`, because the user-visible defect is silently incorrect chronological log order. `date_format:` is the mechanism that fixes that defect and makes previously ambiguous/non-conforming data fail loudly.

Status: implementation in progress.

Implementation and automated verification

- Added `src/refdes/dates.py`: validates placeholder order and parses strict calendar dates with Python's `datetime.date`; values accept one consistent `-`, `/`, or `.` separator.
- Added `Project.date_format`, default resolution and schema validation in `src/refdes/schema.py`, hard `type: date` validation in `src/refdes/build.py`, and parsed-date sort keys at all three `src/refdes/render.py` sites. Missing/malformed values sort last rather than crashing render.
- Added project-setting, validation, impossible-date-message, and actual rendered-order coverage in `tests/test_project_settings.py`. The render test checks `log.html` and `document.html` oldest-first and `summary.html` newest-first from deliberately out-of-order `MM/DD/YYYY` source entries.
- Focused suite: `python -m pytest tests/test_project_settings.py -q` -> `30 passed in 3.31s`.
- Full suite: `python -m pytest tests/ -q` -> `696 passed in 23.48s`.

Hand-check transcript

Scratch project settings:

    site:
      title: Date format hand check
      out: _site
    date_format: DD.MM.YYYY
    standard:
      base: hardware
      version: 3
      presets: []

Scratch source, intentionally newest first:

    items:
      - id: LOG-001
        type: log
        date: "25.01.2026"
        summary: January 2026 entry
      - id: LOG-002
        type: log
        date: "01.02.2025"
        summary: February 2025 entry

The globally installed `refdes` launcher initially loaded the older installed package and correctly exposed that it was not exercising this worktree:

    $ refdes -c C:/Users/Jared/AppData/Local/Temp/refdes-date-format-hand-check/refdes-project.yaml build --dry-run
    configuration error: refdes-project.yaml: unknown setting 'date_format'.

Re-running that same real CLI entry point with this worktree's `src` on `PYTHONPATH` exercised the changed code:

    $ PYTHONPATH=C:/Users/Jared/.ao/data/worktrees/refdes/refdes-8/src refdes -c C:/Users/Jared/AppData/Local/Temp/refdes-date-format-hand-check/refdes-project.yaml build --dry-run
    2 items, 0 errors, 0 warnings
    site written to C:\\Users\\Jared\\AppData\\Local\\Temp\\refdes-date-format-hand-check\\_site (dry run, not sealed)

Rendered `_site/log.html` order:

    <li class="tl-entry" id="log-002">
      <span class="tl-date">01.02.2025</span>
      ... data-ref="LOG-002" ...
    <li class="tl-entry" id="log-001">
      <span class="tl-date">25.01.2026</span>
      ... data-ref="LOG-001" ...

This confirms the required `25.01.2026` entry builds through the local CLI and renders after the earlier `01.02.2025` entry despite the reverse source order.

Final verification after removing formatter-only churn and reapplying the scoped edits:

- `python -m pytest tests/ -q` -> `696 passed in 26.87s`.
- The local-source CLI hand-check repeated successfully: `2 items, 0 errors, 0 warnings`; `_site/log.html` again placed `LOG-002` (`01.02.2025`) before `LOG-001` (`25.01.2026`).
- Scratch project removed after verification.
- Scoped essential lint for the new parser and changed tests passed. A broader import-sort check still reports the pre-existing compact `from .model import (...)` style in `src/refdes/build.py`; it was left unchanged to avoid unrelated formatting churn.

Status: implementation, automated verification, hand-check, and cleanup complete; commit pending.
