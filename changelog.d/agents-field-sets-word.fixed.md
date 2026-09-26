- Docs: `AGENTS.md` said `refdes-schema.yaml` holds the project's own
  `types:`/`link_types:`/`field_sets:` overlay. That key was renamed to
  `sets:` when sets widened beyond fields, and leaving `field_sets:` behind is
  now a hard error that names the replacement; the same paragraph already
  carries a note of that kind for a `types:` left in `refdes-project.yaml`, so
  it now reads `sets:` and says the same about the old name.
