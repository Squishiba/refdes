- The project tree now treats a type that declares `extends: group` as a
  group: its `part_of` members expand under the subtype's own node -- inside
  board branches and when cycle promotion makes the subtype a forest root --
  exactly as they do under a plain `group` (docs/design/extends.md). A
  project without a subtype of `group` renders exactly as before.