- **Breaking:** the bundled standard library ships `hardware@3`, and
  `refdes init` now pins new projects to it — v0.5.0's `init` wrote
  `refdes.yaml` with `standard: {base: hardware, version: 2}`; this
  release's writes `refdes-project.yaml` with `version: 3` (verified by
  running `refdes init` on a fresh directory). A new project therefore
  starts on the v3 vocabulary: one `body:` for prose (see the companion
  fragment on the `text:`/`method:` fold), `drop_in` for interchangeable
  parts, the merged `log` type (`decision` is retired), and no presets —
  `standard.add-preset` against a v3 pin reports
  `hardware@3 (available: [])`. Nothing changes for an existing project
  on its own: `hardware@1`/`@2` keep their frozen bytes, and the pin is
  what promises that; a v2 project sees v3 only when its author runs
  `refdes standard upgrade --to 3`. A project that hand-edits
  `standard.version:` to 3 without upgrading its content fails the
  build — the standard's own renames (`equivalent:` on a component,
  `text:` as a required field) are errors under v3, not warnings.
  See [upgrading from 0.5.0](upgrading.md) for the ordered path.
