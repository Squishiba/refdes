- `refdes ls` no longer matches a non-string `tags:` element's stringified
  dict. #235 made a mapping-shaped element of a list field a load error, but
  the item still loads (with the error reported) and is listed, and the
  filter's tag read stringified it — so `ls --tag not-a-string` matched the
  item whose tag list contains `{name: not-a-string}`, and the free-text
  query matched the dict's repr too (run-7 finding F16, the residual of 6a
  B6). The filter's tag read now yields only strings: a non-string element is
  not a tag and matches nothing, the string tags around it keep matching, and
  the load error keeps reporting. The `serve` pages' tag filters share the
  lenient read and are deliberately left as they are; the command's own
  filter is the one the finding reported. Pinned in
  `tests/test_run7_f13_f14_f16.py`.
