# Fix preview-data JSON script-context injection

`json.dumps` does not escape `<` or `>`, and `base.html.j2:60` embeds the
previews payload verbatim (`| safe`) into a `<script id="preview-data">`
element. An item title like `T</script><script>alert(1)</script>` therefore
emitted a literal `</script>` inside the element — the HTML parser closed the
script there and the remainder of the title became live markup.

## What I did

1. Verified the bug before touching anything:
   `python -c "import json; print(json.dumps({'t': 'a</script><script>alert(1)</script>'}))"`
   → the `<` and `>` come through unescaped, confirming the breakout vector.
   Also confirmed the payload actually reaches the page raw by building a
   project with the evil title and reading the rendered `index.html`.
2. `src/refdes/render.py`: after `json.dumps(previews, ensure_ascii=False)`,
   replaced `<` with `\u003c` and `>` with `\u003e`, with a comment explaining
   why it is done at dump time rather than in the template (`| safe` on
   base.html.j2:60 is required — autoescaping the quotes would break
   `JSON.parse(dataEl.textContent)` in app.js, and these escapes are valid
   JSON string escapes so the decoded value is unchanged). Used `"\\u003c"`
   (backslash-escaped) in the replace so the literal six-character escape
   lands in the JSON, not the `<` character itself.
3. `tests/test_render_assets.py`: new `test_preview_data_escapes_script_close`
   in the rendering module. Builds a COVERAGE_SCHEMA project whose decision
   item is titled `T</script><script>alert(1)</script>`, renders, and asserts:
   - `"</script><script>" not in html` — the breakout sequence is gone,
   - `"\\u003c" in payload_text` — the escaped form is in the payload, and
   - `json.loads(payload_text)["DEC-A-001"]["title"] == EVIL_TITLE` — the
     payload round-trips exactly, proving serialize-time escaping did not
     corrupt the data.

## Difficulties

- The obvious trap: in Python source, `"\u003c"` *is* the `<` character, so
  the replacement string had to be `"\\u003c"` (or a raw string). A quick
  `python -c` round-trip check confirmed the escaping and the `json.loads`
  decode before the test was written.
- The task's line numbers (render.py:623-624, 296+) were from an older main;
  after the ff-only sync the dump lives at 629-630. Same code, just shifted.

## Verification

- `python -m pytest tests/ -q` → 663 passed, 0 failed (662 baseline + 1 new).
- Revert gate: with render.py restored to the `json.dumps(...)`-only version,
  the new test FAILS — pytest shows the literal
  `title": "T</script><script>alert(1)</script>"` inside the preview-data
  payload in `index.html`. With the fix back in place it passes again.
- `git status --short` → exactly src/refdes/render.py, tests/test_render_assets.py,
  in-prog-logs/fix-previews-json.md.

Committed locally as `render: escape < and > in the preview-data JSON payload`.
Not pushed, no PR.

## Status

Finished.