- `refdes check --refresh` says once, not twice, that a pinned citation could
  not be re-fetched. With one unreachable url it printed two lines saying the
  same thing — the per-url line naming the url and the errno, and a summary
  saying that one citation could not be refreshed — and the summary's only
  non-repeated word was the number one, which the reader can count (run-5 gate
  finding F6). The remedy that used to live only in the summary now rides on
  the single line:

  ```
  WARNING <project> — could not refresh https://…/tps62913.pdf: <urlopen error
  [Errno 111] Connection refused> -- upstream drift was NOT verified for it --
  drop --allow-unreachable to fail the run on this instead
  ```

  With more than one unreachable url the count line stays, because it is the
  only place the count lives, and each url is still named exactly once. The
  same holds without `--allow-unreachable`, where both lines were errors.
  Nothing about the failure or the escape hatch is lost in either case, and no
  exit code changes: one unreachable citation still fails the run without the
  flag and still passes with it.
