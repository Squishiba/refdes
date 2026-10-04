- **`decision` is retired and the history-backed `log` absorbs it**
  (threads phase 4a, `docs/design/threads.md` §5). A verdict and a
  design-log entry are the same thing — a dated point on the project's
  timeline that records what happened and why — and the two types forced
  every decision to be authored twice: a `decision` item for the verdict,
  plus a `log` entry with a `records:` edge pointing at it. The merged
  `log` takes over `decision`'s vocabulary: `title:` becomes `summary:`,
  and `status`/`rationale`/`options`/`checks`, the
  `satisfies`/`constrained_by`/`selects`/`supersedes`/`blocked_by` links,
  `satisfying_statuses: [accepted]` and `check_severity: error` all move
  onto `log`. `date:` is optional and `status:` carries no default, so
  entries written before the merge keep their meaning;
  `legacy_prefixes: [DEC]` on the type keeps migrated items' DEC ids
  warning-free while new items mint `LOG` ids as always.
  `refdes standard upgrade --to 3` carries a v2 project across in the
  same refuse-and-roll-back transaction as the rest of the migration:
  `type: decision` to `type: log`, `title:` to `summary:`, and every
  `records:` edge to `follows:` — kept a structured link, because
  structured links are the spelling the surrogate-key machinery keeps
  current across a target rename, while a `citations: - item:` entry is
  bare-id data nothing maintains.
- **The `design-debate` preset (`debate`, `option`, `claim`, `position`)
  is retired** with the type its grouping was built around. A project
  enabling it at `hardware@3` gets a load error naming the preset;
  migrate the entries to plain `log` items linked by
  `follows:`/`supersedes:`, or declare the four types in your own
  `refdes-schema.yaml` to keep them verbatim.
