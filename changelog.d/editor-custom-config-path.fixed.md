- Serve: `refdes -c custom-project.yaml serve` now lets the editor write.
  Reads loaded the configured file, but `POST /api/item/<ref>/edit` and
  `POST /api/items/create` rebuilt `refdes-project.yaml` beside the project
  root from the root alone, so on a project whose settings file has any other
  name every save refused 422 with `the project did not load:
  FileNotFoundError`. The launch's own config path now travels with it: the
  write handlers take it as a parameter, the API passes the path the state
  loaded from, and the watcher's input set names the configured file (the
  `refdes-schema.yaml` overlay keeps its fixed name, as the loader resolves
  it), so revision checks, post-save revalidation, and the poller's reload
  all cover the bytes the model is built from. A project on the default
  marker behaves exactly as before.
