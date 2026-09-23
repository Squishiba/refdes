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

## Difficulties

None material. `cd` is shell-whitelisted-out in this session; worked around by
relying on the fixed cwd (noted for future sessions — absolute paths only).
