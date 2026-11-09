- Docs: `docs/upgrading.md` step 1 (and its breaking-change table row) now
  say the retired-`refdes.yaml` "exit 2" is conditioned on the walk up from
  the current directory finding no `refdes-project.yaml` — a probe nested
  inside another refdes project loads the ancestor's project and exits 0
  with the old file unread — and give the one-line isolation test
  (`refdes -c refdes.yaml check`), all verified against the current build.
