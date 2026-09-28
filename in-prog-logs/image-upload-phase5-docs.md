# Image upload Phase 5 — Docs

- Read the image-upload design through §17 and checked the Phase 5 scope.
- Confirmed `docs/markdown.md` is the existing authoring reference for local
  images; it had no browser upload guidance.
- Verified the shipped behavior against `serve/static/images.js`,
  `serve/upload.py`, `serve/api.py`, and the upload test suite: supported image
  signatures/extensions, 8 MiB cap, raw-byte upload, no body write, collision
  confirmation, cross-document checks, sealed-item refusals, and refresh.
- All 21 named §14 upload tests are present in `tests/test_serve_upload.py`.
  Added a static docs regression check rather than duplicating those cases.
- Updated `docs/markdown.md`, the Deferred/Later entries in
  `docs/design/browser-editor.md`, and the stale §14 note in the design.
- `pytest -q tests/test_serve_static.py`: 49 passed.
- `pytest -q tests/test_serve_upload.py`: 104 passed, 1 skipped. The sandboxed
  attempt could not bind loopback; rerunning with approved loopback access passed.
- Status: docs and regression check complete; ready for commit and PR.
