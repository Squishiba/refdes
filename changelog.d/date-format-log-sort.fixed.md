- **Design-log dates are validated and sorted chronologically rather than as raw
  strings.** A project may set `date_format:` in `refdes-project.yaml` using
  `YYYY`, `MM`, and `DD` once each; strict `YYYY-MM-DD` is the default. The
  configured separator is canonical in diagnostics, while `-`, `/`, and `.`
  are accepted interchangeably in item values. A date in the wrong order or an
  impossible calendar date is now a hard build error instead of being silently
  accepted and potentially misordered.
