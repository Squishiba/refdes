# finding 38, chunk 1 — `doc:` as a recognised definition key

Status: finished. Committed on `ao/refdes-97/root`.

## What landed

- `configcheck.py`: `doc` added to `TYPE_KEYS`, `FIELD_KEYS` and
  `LINK_TYPE_KEYS` (a field-set entry is a field spec, so `FIELD_KEYS` covers
  it too). New `BlockChecker.definition` is the one check — a non-empty string
  or nothing at all — called from `field_spec`, `type_entry` and
  `link_types`. `BODY_KEYS` deliberately untouched: a body is not a vocabulary
  term in finding 38's list.
- `model.py`: `doc: str = ""` on `ItemType`, `FieldSpec` and `LinkType`.
  `""` means undeclared, so nothing has to special-case `None`.
- `schema.py`: `_doc_text` reads the resolved value into those three objects.
  It re-checks the same rule because the bundled standard and its presets do
  not go through `configcheck` (that validator is project-authored input only),
  and chunk 2 puts `doc:` into `base.yaml`.
- `schema_json.py`: `field_json_schema` emits `description` when a field has a
  definition; `_type_branch` emits one for the type; `link_json_schema` takes
  the verb's definition and puts it ahead of the `target: …` line that was
  already there. All three are conditional, so no key appears when there is no
  definition.
- `render.py` `items_json`: `doc` on the type entry and on each field entry,
  again only when declared.
- `editors/vscode/extension.js`: the field-name completion for `.md` front
  matter now sets `documentation` from the payload's `doc`. Key hovers in
  `.yaml` come from vscode-yaml reading `.refdes/schema.json`, which is why the
  JSON Schema `description` above is the load-bearing one.

## The byte-identical proof

Built the repo project and `docs-site/` from a clone of `main` and from this
tree, same input files, and hashed every output file:

- repo site + `items.json`: 41 files compared, 0 differ
- docs-site + `items.json`: 38 files compared, 0 differ
- `.refdes/schema.json` (`schema_json.build_schema`) for both projects:
  2 compared, 0 differ

Probe scripts are in `.scratch/` (`build_probe2.py`, `schema_dump.py`,
`hashcmp.py`), with `main` cloned to `.scratch/clone-main`.

## Not done (later chunks, on purpose)

No `doc:` text in `src/refdes/standards/hardware/v3/base.yaml`, no completeness
lint, no generator, no SVG. `git diff --stat` touches no file under
`src/refdes/standards/`, so it does not collide with the held
`ao/refdes-64/root` branch's 114-line edit of `base.yaml`.

## Note for whoever rebases

`ao/refdes-64/root` also edits `model.py`, `schema.py` and `render.py`; the
overlaps are in the same dataclass/constructor regions this chunk appends to,
so expect a trivial textual conflict there, not a semantic one.
