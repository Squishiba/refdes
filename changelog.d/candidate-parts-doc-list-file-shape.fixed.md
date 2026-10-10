- Docs: the list-file examples in `docs/design/candidate-parts.md` — the
  layout §6.1 recommends, the `refdes new --list` skeleton §6.4 prints, and
  the §7.2 worked-example `items/power/candidates.yaml` — were written as
  `defaults:` plus a bare top-level sequence. A list file is a mapping with
  a `defaults:` and an `items:` key (`parse_list_file`; that is also the
  shape `docs/authoring.md` shows and `scaffold.new_list_text` emits), and
  the sketched shape is not even valid YAML: each example failed
  `refdes check` with `invalid YAML … expected <block end>, but found '-'`
  at exit 1, so the recommended layout and the skeleton the flag generates
  were files no project could load. The three examples now use the mapping
  form, and §7.2's per-entry `---`-then-fenced-`calc` spelling became the
  list-file body it describes — a `body: |` block scalar carrying the calc
  block (docs/authoring.md §Bodies in list files). Pinned by
  `tests/test_candidate_parts_doc.py`.
