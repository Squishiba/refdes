- `docs/workspaces.md` warns about the shared board/workspace name namespace
  where the registries are introduced, not three sections later. The collision
  is refused at load with a good message — `'power' is declared as both a board
  and a workspace — boards and workspaces share one namespace for generated
  report names (e.g. coverage-power.html); rename one of them`, exit 2,
  confirmed by running `refdes check` against a project declaring `power` twice
  (`src/refdes/schema.py:742-751`) — but the page only mentioned it in the last
  paragraph of "Overriding the derived value", which a reader reaches only after
  writing both blocks and hitting the error. The new "Workspace names share one
  namespace with board names" subsection sits directly under "Declaring
  workspaces", quotes the real error text and exit code, names the five report
  filenames that collide (`coverage-`, `document-`, `log-`, `references-`,
  `summary-` — the per-board and per-workspace loops at
  `src/refdes/render.py:1124-1265`, both keyed by the registry key), and says
  what does *not* dodge it: `path:` renames the `items/` segment, while the
  namespace that collides is the key. The duplicate paragraph in the override
  section is gone. A test pins the coupling — it triggers the real `SchemaError`
  and requires the doc to name `coverage-power.html` and to appear before the
  "The two-level layout" section, so neither the reason nor its position can
  drift silently (`tests/test_workspaces.py`).
