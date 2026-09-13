- **`refdes.yaml` is retired; a project's config is now two files.**
  `refdes-project.yaml` becomes the project marker and holds every project
  setting — everything it already held, plus `site:`, `id:`, `boards:`,
  `units:`, `history:`, `workspaces:`, `standard:`, `equations:` and `imports:`.
  `refdes-schema.yaml` is new and optional: it holds the project's own schema
  overlay (`types:`, `link_types:`, `field_sets:`) and nothing else, so most
  projects — the ones taking their whole vocabulary from the standard pinned by
  `standard:` — have no such file. The old split contradicted
  `refdes-project.yaml`'s own stated boundary in both directions, which is why
  `refdes.yaml` read as unclear: it held two unrelated jobs while a sibling
  claimed half of them.
- **What you must do:** split your `refdes.yaml` in two by top-level key —
  settings into `refdes-project.yaml`, any `types:`/`link_types:`/`field_sets:`
  into `refdes-schema.yaml` — then delete `refdes.yaml`. `refdes revise` cannot
  do this for you: it rewrites item files, not config layout. A project still
  carrying a `refdes.yaml` fails to load with an error naming both replacement
  files rather than being silently ignored or half-loaded, because a setting
  left behind in the retired file is a setting that quietly stops applying. The
  same guard runs the other way: a `types:` left in `refdes-project.yaml`, or a
  setting left in `refdes-schema.yaml`, is an error naming the file it belongs
  in.
