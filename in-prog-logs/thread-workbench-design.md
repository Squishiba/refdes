# Thread workbench design doc

Task: draft `docs/design/thread-workbench.md` — a design proposal for a live
authoring pane ("workbench") for thread tips / working items, born out of a
design debate with Jared about why note-taking in refdes feels frictional
(notes feel like presentation drafts, not working material; images are
build-time queries you can't see while writing; calc values are name-only in
prose).

## Status

Finished. One new file: `docs/design/thread-workbench.md`. Branch
`ao/refdes-150/thread-workbench`. Not pushed, not PR'd (freeform task; Jared
reviews and lands, same as the living-notes phases).

## What landed

- Problem framing grounded in `living-notes.md` ("treat source files as the
  product; treat the site as one projection"; entries editable until captured)
  and `markdown.md` (images as searched/hashed/rewritten queries).
- Three-clause contract: same semantics (Python-only, per browser-editor),
  smaller scope (item + dependency frontier), additive decoration only
  (overlays strip at publish; precedent: the serve Edit toolbar is injected
  into the HTTP response only).
- Four invariants: rendering never captures; pane read-only; never touches
  `_site/`; security inherited.
- Decoration set D1–D5, phasing W1–W4, five open questions for Jared (biggest:
  whether inline values in prose are pane-only or first-class).

## Verification done

- All `serve/` claims verified by reading source: `cli.py` serve parser
  description (temp-dir preview, polling), `serve/preview.py` (generation
  swap), `serve/server.py` (Poller, 1 s), `serve/api.py` (full rebuild after
  save), `serve/filters.py` docstring ("answers come from the built project";
  ~1 s rebuild baseline), `serve/__init__.py` (toolbar injected into HTTP
  response only).
- NOT run: `refdes serve` itself — the installed `refdes` console entry point
  fails to import in this shell (`ModuleNotFoundError: No module named
  'refdes'`), so behavior claims are source-read, not executed. The doc says
  so explicitly in §2.

## 2026-09-23 pass — decisions recorded, PR

Jared answered all five §7 questions (recorded in the doc as decided,
2026-09-23): D1 pane-only (site publication deferred, not implied); scope any
item; coupling BOTH (resolves via §7.5 — workbench is a mode of the item's
own /preview/ page, one implementation serves VS Code-side and /edit/-side
use; explicit note added under §3); ~1 s rebuild fine for v1 with cheap wins
folded into W1–W3 opportunistically (W4 reframed accordingly; no speculative
optimizations); URL surface = `?workbench=1`-style mode, not a new route.
Status line now "Architecture decided (2026-09-23)".

Merge check: `git fetch origin` — `origin/main` is still `7544a38`, the exact
commit this branch was cut from; the merge is a no-op, no drift. All quoted
citations in §2 re-verified against source after the fetch (cli.py serve
description, filters.py ~1 s baseline note, api.py full-rebuild-after-save
comment, serve/__init__.py toolbar line, server.py Poller 1 s, preview.py
generation swap, living-notes quotes) — all still present; the doc cites
files + quoted strings, not line numbers, so nothing needed correcting.

Tests: `python -m pytest -q` → 2011 passed (176 s). No implementation of
W1–W4 started, per instruction.

## Difficulties

None material. `cd` is shell-whitelisted-out in this session; worked around by
relying on the fixed cwd (noted for future sessions — absolute paths only).
