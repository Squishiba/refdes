- Design-doc status lines corrected to match what has shipped:
  `docs/design/candidate-parts.md` records all five phases as landed
  (`{{compare}}`, status-keyed `check_severity`, the `rejected` component
  status, and `refdes new --list` plus the dead-`defaults:` warning);
  `docs/design/named-calc-blocks.md` records all five phases as landed;
  `docs/design/thread-workbench.md` records W1 and W2 as landed with W3 in
  progress; and `docs/design/browser-editor.md` no longer claims the
  repository has no test CI -- `.github/workflows/tests.yml` runs pytest and
  the E9,F ruff gate on ubuntu and windows.