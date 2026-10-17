- `refdes ls --workspace ''` and `refdes check --workspace ''` now refuse the
  empty value with `--workspace '' is not a workspace declared …` and exit 1,
  like any other name the `workspaces:` registry does not know. An empty
  value is falsy, so it used to disable the filter silently: `ls
  --workspace $WS` with `$WS` unset listed the whole project and exited 0.
  Unknown *names* are unchanged: `check` names them as registry errors, `ls`
  keeps answering with "no items match" (exit 0), its documented rule for
  every filter.
