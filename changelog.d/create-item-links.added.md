Links at creation. `POST /api/items/create` gains a `links` field: an object
mapping a declared link verb to the one or more targets it should carry, so
authoring "a test that verifies these two requirements" is one request instead
of a create plus one `add_link` edit per link (the create form could set scalar
fields and nothing else, which made every link a second round trip). It is
`amends:` generalised, not a second mechanism: `serve/edit.py` resolves each
verb under the same per-project write lock, against the same read-only snapshot
the item text is planned from -- the verb must be declared by the type, each
target must exist and be of a type the verb accepts, and what is written is
always `links.composite_for`'s `DISPLAY-ID@key`, never the spelling the client
sent. A target may be named by display id, surrogate key, or a composite the
client already resolved as far as it could, in which case the key half is what
resolves and a composite naming no key is refused rather than trusted. Each
verb becomes one line in the flow-sequence spelling the standard's own items
write (`verifies: [REQ-001@…, REQ-002@…]`), appended through the existing
`link_lines` seam, so the resolved links are in the item's very first write and
all three destination shapes -- YAML list file, multi-item Markdown file, new
single-item Markdown file -- carry them without any destination-specific code.
Anything that does not resolve refuses the whole creation with nothing written:
an undeclared verb (naming the verbs the type does declare), a target of the
wrong type (naming the types the verb accepts), a target that is not in the
project, a target carrying no artifact key (which would drop the identity the
link is for), the same target named twice -- compared on what the refs resolve
to, so `REQ-001`, its bare key and `REQ-001@key` are one target asked for twice,
which is what `add_link` already refuses on an existing item -- and the same
verb requested twice, once as `amends:` and once inside `links:`. A request with
no `links` is byte-for-byte what it was before.
Malformed `links` -- not an object, an empty target list, a target that is not a
string -- is a 400 at the HTTP edge, the same shape/meaning split as `fields`:
what could not be a request is the route's, what does not resolve is the
service's 422.
