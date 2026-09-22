Structured link editing in the browser editor (Slice 2). The patcher gains
`AddLink`/`RemoveLink` ops that edit all three source shapes a link list
takes today -- scalar, flow list, block list -- in place: a scalar widens to
a flow list keeping the original spelling, a block list grows at its own
indent, and the last target leaving deletes the verb entry. Comments in any
covered span refuse, same contract as `SetField`. The edit service resolves
the target under the write lock, validates it against the schema's declared
target types for the verb, and always writes the `DISPLAY-ID@key` composite
from `links.composite_for` -- a target with a null artifact key is refused,
never written as a bare id. `POST /api/item/<ref>/edit` accepts
`add_link`/`remove_link` with `{verb, target}`; `GET /api/item/<ref>` now
lists each editable verb with its allowed target types and current targets.
The editor UI grows a picker per verb -- current targets with remove/undo,
a filtered candidate list from the same `/api/items` API, adds and removes
riding the existing draft, save, revision, and conflict machinery.
