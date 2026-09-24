The browser editor no longer drops focus and the caret when a rebuild lands
mid-edit. A revision-triggered re-render of the item already on screen keeps
the old view up while the fresh one is fetched, then carries its field
controls and body textarea into the new view by field identity (a stable
`data-edit-key` on each control): a carried-over control is re-bound to the
fresh editor instance and its value updated in place only when it differs,
and focus with the selection range is restored into the same logical field
afterwards. A control whose field is no longer editable is dropped, as
before.
