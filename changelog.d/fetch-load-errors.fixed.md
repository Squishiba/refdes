- `refdes fetch` on a project with an items file that fails to parse now
  prints the load errors, exits 1, and its summary says how many load errors
  there were and that citations in files that failed to load were not
  processed — it no longer reports success while silently skipping every
  citation in the unparsed file. Citations in files that did load are still
  fetched and pinned exactly as before.