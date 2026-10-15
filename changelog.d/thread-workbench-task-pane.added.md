- Item pages of a threaded log now carry a read-only floating task pane
  (thread workbench W5a, `docs/design/thread-workbench.md` §7a), in the
  `refdes serve` preview and on the published site alike: one tab per open
  tip (a fork is never shown as one merged list), the tip's task list with
  the `viewing LOG-007 · tasks as of tip LOG-012` note on older entries,
  the verdict line, and a collapsed *Derived (auto clears when fixed)*
  section. Every task, verdict and derived line is `refdes thread`'s own
  wording from the same headless projection, rendered at build time; the
  `viewing …` note above is the pane's own text, which that command never
  prints. The pane computes and writes nothing.
  The toggle and pane start `hidden` — with JavaScript disabled they never
  appear — and a project with no `follows:` edge anywhere publishes exactly
  the pages it published before, byte for byte.
