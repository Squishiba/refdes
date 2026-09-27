# Task: design spec — VS Code custom-editor adapter over the same application services

Date: 2026-09-27. Branch: `design/vscode-editor-adapter`. Docs-only: no changes
to `src/`, `tests/`, or `editors/vscode/`.

## What was asked

Design the one Later item of `docs/design/browser-editor.md` that had no design
behind it ("VS Code custom-editor adapter over the same application services",
`browser-editor.md:1100`). Hard constraint from that document: Python stays the
only implementation of every semantic; VS Code is a new *client* of the shipped
server, not a reimplementation. Deliver `docs/design/editor-vscode-adapter.md`
in the header style of `editor-image-upload.md` / `editor-source-picker.md`, and
point the Later line at it.

## What I read first (all of it, not excerpts)

- `docs/design/browser-editor.md` — all 1291 lines. The parts that bind this
  proposal: "Python remains the only implementation…" (`:13-16`), Process
  boundary (`:592-596`), Option C's verdict and its "narrow CLI/RPC bridge"
  sentence (`:202-219`), Drafts (`:763-780`), conflict refusal and the
  never-merge rule (`:786-800`), Security incl. the token rules (`:930-972`),
  Phasing (`:1038-1070`), Decisions (`:1242-1250`).
- `src/refdes/serve/api.py` (840 lines) — the exact route table and the
  Applied/Conflict/Refused/Invalid → 200/409/422/422(/403) mapping.
- `src/refdes/serve/edit.py` (first 220 lines) — `EditRequest`, the four result
  dataclasses, `write_lock_for` (per-process), `file_revision` (sha256 of the
  file), and the seven-step order in the module docstring.
- `src/refdes/serve/security.py`, `server.py`, `state.py`, `preview.py` — token
  header vs cookie, `origin_ok`'s Host/Origin agreement rule, `EDITOR_CSP`'s
  `frame-ancestors 'none'`, the poller, the per-build preview render.
- `src/refdes/cli.py:230-249` (`cmd_serve` prints the launch URL as its first
  stdout line, flushed) and the `serve`/global flags at `:1349-1382`.
- `editors/vscode/` in full: `extension.js` (536), `package.json` (94),
  `README.md` (132), `LICENSE`, `icon.png`, `syntaxes/calc.injection.json`,
  `.vscodeignore`, `.vscode/launch.json`. That is the complete inventory.
- `tests/serve_support.py` and `tests/test_serve_editor_e2e.py` — to copy the
  project's "drive a live server, hash the tree, skip loudly" test posture into
  §7 rather than invent one.
- VS Code's own docs (webview API guide, custom editor API guide) for what a
  custom editor actually owns: `CustomTextEditorProvider` uses VS Code's
  `TextDocument` as the model and expresses changes through
  `WorkspaceEdit`/`applyEdit`; `CustomReadonlyEditorProvider` skips save/undo;
  webviews are "resource heavy… use sparingly"; webviews cannot touch the VS
  Code API and only message-pass.

## Findings worth recording

1. **The shipped extension does not activate on a current project.**
   `findRoot()` looks for `refdes.yaml` (`extension.js:44`) and
   `activationEvents` is `workspaceContains:**/refdes.yaml`
   (`package.json:27`), but `refdes.yaml` is retired
   (`src/refdes/schema.py:5`, `:47`, `:341`; `serve/edit.py:63`). So "the VS
   Code extension is the natural second client" is true of its architecture and
   false of its runtime behaviour today. Recorded as §2.3 and made Slice V−1.
   I did not fix it — the task says propose, do not implement.
2. **The process question was already answered** (`browser-editor.md:592-596`),
   so §3.1 does not re-derive it: one long-lived `refdes serve` per project,
   extension as ordinary HTTP client. Per-operation Python subprocesses are
   ruled out by that sentence *and* by `write_lock_for` being per-process.
3. **The token question has a zero-server-change answer.** `cmd_serve` prints
   the launch URL, token included, as its first flushed stdout line
   (`cli.py:236`), so an extension that spawns `serve --no-open` can parse it;
   and pasting that URL is the fallback for a server the author started. Token
   file, extension-supplied token, and persisting it in SecretStorage are all
   rejected in §3.2 with reasons.
4. **The hardest real problem is not the token, it is two write paths.** A
   writable `CustomTextEditorProvider` puts VS Code's dirty `TextDocument` next
   to the server's disk-hash `expected_revision`; the server cannot see the
   dirty buffer, so its conflict check passes and a later VS Code save silently
   eats the API's patch — exactly the failure `browser-editor.md:796-800`
   refuses to build a merge for. That finding is what orders the phasing
   (read-only first, custom editor outside the horizon) and it is §3.5.
5. **`EDITOR_CSP` already refuses the lazy answer.** `frame-ancestors 'none'`
   (`security.py:70-83`) means "just iframe `/edit/` in a webview" is blocked by
   shipped code, not by taste. §9.2 records it.
6. **Deviation flagged, not hidden:** Option C promised a "narrow CLI/RPC
   bridge" (`:215-218`). I propose HTTP instead, say why (the bridge sentence
   predates `serve/api.py`; a second transport is itself new server behaviour),
   and put it in front of Jared as Q1 rather than quietly contradicting the doc.

## Choices made in the spec

- Read-only hover + one deep link as Slice V0 — the smallest thing that proves
  the token and process-lifecycle story against the real server.
- Three UI shapes named with the real tradeoff (providers / sidebar webview
  view / custom editor), and the tradeoff stated as "a webview is a second UI;
  a custom editor is a second write path".
- §4 is a table of every semantics → its Python owner → the route that exposes
  it, so "must not reimplement" is checkable rather than aspirational; two of
  the §7 tests enforce it mechanically (no `applyEdit`/`fs.writeFile` in the
  extension source; hover facts must equal the API's).
- Tests are Python-first so CI actually runs them, with the Node-driven ones
  skipping loudly rather than silently.

## Verification

- `pytest -q -x` and `ruff check --select E9,F src tests` with
  `/home/jorb/work/venv-refdes` — results recorded in the PR conversation.
- Every line-number citation in the new doc was re-checked against the files
  after drafting (several were corrected: `browser-editor.md:13-16`, `:561-562`,
  `:796-800`, `:968-972`; `security.py:52-54/:56-66/:70-83`; `server.py:388/402/510/514`;
  `state.py:279-290/:291-311`; `api.py:82/100/161/201/325/454/646`;
  `edit.py:16-37/:25-26/:63`; README `:109-110/:113-116`).

## Status

Finished. `docs/design/editor-vscode-adapter.md` written; the Later line in
`docs/design/browser-editor.md` now points at it. No code touched. Awaiting
Jared on §6 Q1–Q8; each carries a recommendation, so any unanswered one stands
as the default.
