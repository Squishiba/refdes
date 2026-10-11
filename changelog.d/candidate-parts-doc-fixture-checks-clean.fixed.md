- Docs: `docs/design/candidate-parts.md` §7.2's fixture now checks clean.
  Each `source("datasheets/<part>.csv", ...)` line named a CSV no `citations:`
  entry cited, and a `source()` may only name a path the *same item* cites
  (`citations.authorize_source_path`, docs/design/calc-sources.md §1), so
  `refdes check` on a project built from the fences reported one error per
  source line (6, reproduced) plus its cascades. The three items now each
  cite their own CSV, and `keep_copy: true` is off the local datasheet PDF --
  on a local path it is itself reported as "meaningless -- a local file is
  already local". A scratch project built verbatim from the §7 fences now
  checks with exit 0 and zero errors after `refdes fetch` (the §7.2 prose
  names that step). Two smaller honesty fixes in the same file: §7.3's fence
  is labelled `markdown`, not `yaml` (it contains a bare `---` separator and
  body prose -- `yaml.safe_load` on it raises ComposerError), and the §6.4
  skeleton doc-test -- whose docstring claimed it pinned "the same shape
  `scaffold.new_list_text` actually emits" without ever calling the
  generator -- now makes that comparison at the level it is true (both parse
  as the `defaults:` + `items:` mapping form, the `defaults:` blocks are
  equal, and the generated text itself loads), with the docstring saying what
  is deliberately not compared (the sketch drops the generator's per-field
  hint comments and shows one optional field bare).
