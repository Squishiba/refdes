- Figure references now resolve inside log entry bodies on the design log
  page. A figure defined with `{id="..."}` in a log entry's body gets its
  "Figure N" caption number, and a `[[fig:...]]` reference to it renders as
  a resolved link, the same as on item, document, and page outputs —
  previously both markers were left unresolved and the reader saw an empty
  spot and an invisible span.
