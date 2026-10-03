- `refdes check` now refuses a `decision.options:` entry that is not a
  mapping. `options:` written as a list of plain strings passed `check` with
  `1 items, 0 errors, 0 warnings` and exit 0, and then `refdes build` died
  inside the render with `jinja2.exceptions.UndefinedError: 'str object' has
  no attribute 'get'` at exit 1: the options-considered panel reads
  `opt.get('name')`, `opt.get('verdict')` and `opt.get('because')` off each
  entry, which is the shape `refdes schema` declares for the field -- an array
  of objects with `name`, `verdict` and `because`, `additionalProperties:
  false`, no required key. Each non-mapping entry is now one error on the
  item, naming the field and showing a valid option
  (`build.validate_items`), in the same posture as a non-mapping `checks:`
  entry (`run_checks`) and a scalar `options:` (`parse._reject_scalar_collection`),
  both of which already refused their own mistake and are unchanged. A
  mapping with only a `name:` stays valid, since the panel defaults the other
  two. Both panels also skip a non-mapping entry, so a build that has
  diagnosed the problem prints the diagnostic and exits 1 rather than a
  Jinja2 traceback.
