- The New Item form's "(file default)" placeholder option is inert. An
  `<option>` with no `value` attribute reports its text, so an untouched
  Board select sent `board: "(file default)"` in the create body -- a truthy
  value the form's own `if (select.value)` guard let through -- and the
  registry gate refused every creation on any project that declares boards
  (422 `board: '(file default)' is not declared`). The placeholder's value is
  now `''` and the registry options carry their keys explicitly, so "ask the
  file" means exactly that on Board and on the new Workspace select alike.
