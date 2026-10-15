- `POST /api/items/create` now reads an empty `id` the way
  `GET /api/create/preview` always has -- as "not given" -- so a create
  body with `"id": ""` takes the next free id instead of answering 422
  (`'' is not shaped like a display id (a PREFIX-NNN form such as
  REQ-042)`). The two routes disagreed on the same empty string: the
  preview collapsed `?id=` to the auto plan while the POST handed it to
  `CreateRequest` as an explicit override, which made the one save that
  could not go through exactly the one the preview had just promised --
  an empty id box on the create form. A non-empty malformed id (`"   "`,
  `"not-an-id"`) is still refused, on both routes alike; the id layer's
  "explicit overrides are honoured verbatim or refused, never
  renumbered" posture is unchanged.
