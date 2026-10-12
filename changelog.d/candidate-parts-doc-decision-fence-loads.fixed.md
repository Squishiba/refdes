- Docs: `docs/design/candidate-parts.md` §7.3's fence now shows a loadable
  item file. Relabelled `markdown` by the #188 follow-ups, it still opened
  straight on `id:` with no leading delimiter, so the whole-file example it
  presents -- front matter, `---`, body prose -- is one the loader refuses:
  pasted into a project as authored, `refdes check` reported
  `items/power/decision.md:1 — no YAML front-matter (file must start with
  '---')` (reproduced in a scratch project built from the §7 fences). With
  the opening `---` restored, the whole worked example -- §7.1's bounds
  (wrapped into the mapping form a list file on disk must have), §7.2's
  candidates as-authored, and this decision as-authored -- checks with exit
  0 after `refdes fetch`, and the decision's `selects:` silences exactly the
  "nothing selects it" warning §7.4 says it silences. `tests/
  test_candidate_parts_doc.py` now extracts that fence too and runs it
  through `parse.parse_markdown_file`.
- Docs: §6.1's second yaml block -- one component entry after the winner's
  `status:` edit -- is now named for what it is: a fragment of the file's
  `items:` list, not a whole file (it is a bare top-level sequence, which no
  list file on disk may be). Same paragraph's `parse.py:601-627` citation had
  drifted off the code it named (that range is now `_resolve_section_marker`);
  it names `parse_list_file` and what it does instead. §6.4's skeleton is now
  labelled as the abridged sketch it is: everything through `- id:` is what
  `refdes new component --list` prints (verified by running it), while below
  that the real output lists every field the type declares with its `#`
  hints and comments the optionals out -- `part_number:` bare in the sketch,
  `# part_number:  # text` in the output.
