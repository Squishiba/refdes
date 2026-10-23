- A page whose front matter fails to parse is reported once, at the file line
  of the problem. `refdes check` and `refdes build` printed the same
  `invalid page front-matter: …` warning twice per page — a writable run
  loads the pages twice, once in the load's image-freeze step (to scan page
  bodies for image references) and once in `build()` (to pick up freeze's
  disk rewrites) — and the warning named no line, quoting only YAML's
  front-matter-relative "line N, column M", which sends the reader to the
  wrong file line. The warning is now guarded per page on the project (the
  double load is intentional and cheap; the double report is not), and it
  names the file line the YAML problem mark lands on, falling back to the
  opening `---` fence's line when the error carries no mark. The message
  keeps the YAML context/problem wording with the marks' position part
  dropped. A page with valid front matter, or none, is unchanged.
