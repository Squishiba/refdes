- `refdes serve` preview rebuilds and repeat `refdes build` runs no longer
  pay the Jinja template compiles on every render: one Environment is now
  reused per process (keyed to the template directory and its compile
  options, with auto-reload kept, so an edited template recompiles on the
  next render exactly as before). Measured on a 200-item generated site with
  the preview manager (load ~8, median of 5): rebuild 450 ms -> 100 ms
  (12 template compiles -> 0 after the first render). Output is
  byte-identical (repo site, docs-site, and the generated site, diffed tree
  against the pre-change build).
