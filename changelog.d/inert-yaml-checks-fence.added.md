- **A ` ```yaml ` fence in an item's body that declares one of its own type's
  fields is now a warning.** Writing `checks:` as a fenced yaml block in the
  body — the shape `docs/checks.md` used to show beside the ` ```calc ` fence —
  renders as literal text and the check silently never runs; `refdes check`
  reported 0 errors. The build now warns at the fence, names the inert key,
  and says to move it into the front matter. A yaml fence of example code with
  no such key stays silent.
