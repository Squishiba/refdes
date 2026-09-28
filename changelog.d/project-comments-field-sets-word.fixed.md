- Docs: the header comments in `refdes-project.yaml` and `refdes-schema.yaml`
  still described the project's own schema overlay as holding
  `types:`/`link_types:`/`field_sets:`. That key was renamed to `sets:` when
  sets widened beyond fields, and a `field_sets:` written into a project
  overlay is now a hard error that names the replacement, so the comments
  described a key the project's own files would reject. Both now read `sets:`,
  matching `AGENTS.md`. Comments only — no behaviour change, and released
  standard bundles (`hardware` v1, v2) keep `field_sets:` as frozen.
