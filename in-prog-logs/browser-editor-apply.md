# Edit service: `serve.edit.apply_edit` (browser-editor slice)

Authority: `docs/design/browser-editor.md` — "Validation, conflicts, and
transactions", "Write-back fidelity", the permissions-seam section, and the
matching Decisions bullets. Implemented in `src/refdes/serve/edit.py`, pinned
by `tests/test_serve_edit.py` (21 tests). Pure Python: no HTTP, no UI.

`apply_edit(project_root, request)` returns one of four dataclasses —
`Applied | Conflict | Refused | Invalid` — each with `ok` and `message`. No
authoring outcome is an exception. Every non-`Applied` path is asserted in the
tests to leave `items/` and `.refdes/` byte-identical.

## Calls made where the design leaves room

1. **`expected_revision` is a per-FILE revision, not the project revision.**
   It is the sha256 hexdigest of the target file's bytes — the same spelling
   `serve.state.content_hashes` already publishes — because the thing that can
   go stale is the exact text the patch will be applied to, not the project as
   a whole. A client holding the project-wide `content_revision` cannot be
   checked against a file, and a project-wide revision would make every save
   conflict on any unrelated edit anywhere.

2. **The conflict diff is disk vs "disk with the requested op applied".**
   The design describes the conflict screen as *client draft vs disk*, but the
   server holds no draft: drafts live in the page until they save. So the diff
   returned is what the save *would* have written, expressed against what is on
   disk now — the closest honest rendering of "your change vs theirs" without a
   draft store. When a draft store lands, this is the seam to change. If the
   current text cannot even be planned against, the conflict carries an empty
   diff rather than an invented one.

3. **Sealed vs append-only.** The task brief said "refuse sealed/append-only
   items"; the design says an append-only item *not yet sealed* may be edited,
   and only a sealed one is immutable. Followed the design, and pinned both
   halves: `test_sealed_item_is_refused_and_untouched` and
   `test_append_only_item_without_a_seal_may_be_edited`. Flagging the
   discrepancy for the orchestrator.

4. **The delta gate excludes check violations.** A diagnostic with
   `code == CHECK_VIOLATION` is shown but never blocks, per "do not treat a
   computed check violation as source corruption".

5. **Diagnostic identity for the delta is `(level, code, item_id, file,
   message)` — line numbers excluded.** An edit that adds a line moves every
   diagnostic below it, and a moved diagnostic is not a new error. Diagnostics
   do not yet carry a field path (the design names enriching them as a
   prerequisite for the editor), so attributing a *pre-existing* error to the
   field or body being edited uses a message-text heuristic: a field error's
   message begins `"<field>: "` or quotes the field name; a body error mentions
   "body" or points at a line inside the item's body span. This is the weakest
   part of the gate and the first thing to replace when diagnostics grow a
   path.

6. **A ref that no longer resolves is `Refused`, not `Conflict`.** Staleness is
   checked against the item's file, so an item that has disappeared cannot be
   attributed to a file, and there is no span to diff. The refusal names that.

7. **One structural invariant is checked outside the diagnostic diff:** the
   edit must not change how many items the project has. That is the design's
   "unintended semantic change to another item" made cheap.

8. **No journal, no undo, no permissions enforcement.** The design's crash
   journal is a later slice; so is identity. `EditRequest.who` exists and is
   carried into every result so the check is one line in one place later.

## Found while testing: patcher refuses CRLF markdown bodies

`patcher.plan_patch` on a markdown item whose file uses CRLF returns a Refusal
— its own fidelity check compares the op's LF body against the patched file's
CRLF body and calls the faithful edit a mismatch. YAML field edits on CRLF
files are fine (pinned by `test_a_crlf_yaml_file_keeps_its_line_endings`).

The edit service forwards that refusal unchanged: a write it cannot prove is a
write it does not make (`test_a_crlf_markdown_body_is_refused_not_garbled`).
That means markdown body edits would fail in Jared's CRLF checkout, which is
worth fixing in `patcher._verify`/`_body_view` (normalize breaks before
comparing) — out of this slice's scope, so not touched here.

## Verification

- `python -m pytest -q` → 1769 passed.
- `python -m ruff check --select E9,F src/refdes/serve/edit.py tests/test_serve_edit.py` → clean.
- No changelog fragment: nothing user-visible yet (no HTTP/UI wiring).
