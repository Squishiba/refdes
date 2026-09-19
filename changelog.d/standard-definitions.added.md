- **Every term in the bundled `hardware@3` standard now defines itself.** Each
  type, field, link type and field-set entry in `base.yaml` and the
  `design-debate` preset carries a `doc:` line next to the declaration it
  defines — 71 definitions in total. They flow into the generated JSON Schema
  as `description` text, so an editor with yaml-language-server shows them as
  tooltips while you author, and they appear on the schema export. A new
  completeness lint (`tests/test_standard_docs_complete.py`) fails when a v3
  declaration lacks a definition — the bundled standard only: a project's own
  `refdes-schema.yaml` overlay is never required to define its terms.
