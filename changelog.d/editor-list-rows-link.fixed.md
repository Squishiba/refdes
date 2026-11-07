- Browser editor: clicking an item in the editor's item list now opens it.
  Each row of `/edit/#/items` is an anchor to `#/items/<handle>` carrying the
  current filter query, so the row (and keyboard Tab+Enter on it) navigates
  the detail pane to that item; previously the row's anchor was built but
  never attached, and rows were inert text.
