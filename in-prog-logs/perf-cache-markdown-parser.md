# perf: cache the markdown-it parser (Opportunity 1) — DONE

Scope: `.scratch/refdes-optimization-plan.txt` §4 only — one markdown-it
parser instead of one per item, in `src/refdes/build.py`. Nothing from
Opportunity 2 or 3. One source file touched.

## What changed

`build.py` constructed `MarkdownIt("gfm-like", {"html": False, "linkify": False})`
at three sites: `_image_inputs_hash_value` (per item — 1602 constructions for a
1600-item corpus), `render_bodies` and `render_pages` (once per build each).
All three now call one factory, `_markdown_parser()`, which caches per thread
in a module-level `threading.local()`.

Measured construction count, instrumented via a patched `MarkdownIt.__init__`
over one `loader.load_readonly` of the N=1600 corpus: **1602 → 1** (and 0 on a
second load in the same thread).

## The three §4 constraints

**Configuration byte-identical.** One literal now lives in `_markdown_parser`;
the other two copies are gone, so the hash pass and the render pass cannot
drift apart. Verified by snapshotting `md.options` and the four active rule
chains (`core`/`block`/`inline`/`inline2`) before and after a full build —
identical, and identical to the pre-change instance:
`html=False, linkify=False, xhtmlOut=True, breaks=False, typographer=False,
langPrefix='language-', maxNesting=20`.

**No mutation.** Grepped `src/` and `tests/` for `.enable(`, `.disable(`,
`.configure(`, `.use(` — zero hits on any parser. Read the installed
markdown-it-py 4.2.0 too: every `self.<attr> =` in `main.py` is in `__init__`,
`configure`, `enable`, `disable` or `use`; `parse()` builds a fresh `StateCore`
and a fresh `env` per call, `RendererHTML.render` only reads `self.rules`, and
no rule ever assigns to `state.md.*` or `md.options.*`. So a shared instance
would be safe today.

**Thread safety — decided, not assumed.** Chose `threading.local()` over a bare
module global. Rationale: `refdes serve` runs a poller thread
(`serve/state.py` `Poller`) plus one thread per HTTP connection
(`serve/server.py` `ThreadingHTTPServer`), and `loader.load_readonly` can run
concurrently — so the shared object would be shared across threads for real.
Per-thread ownership makes safety a property of this module rather than a
promise about markdown-it's internals that a future release could break, and
the cost is one parser per live thread instead of one per item. A build runs
entirely within one thread, so the hot path still gets exactly one parser.
Verified: 4 threads alive simultaneously hold 4 distinct instances, and each
gets the same instance back on repeat calls.

## Correctness gate, in §4's order

1. **Golden byte-diff — empty.** `.scratch/golden.py` builds a corpus and
   records sha256 of every file under `_site` (incl. `items.json`).
   - Synthetic corpus (`.scratch/goldproj`, 303 items, 321 output files):
     before/after manifests identical. It deliberately exercises the paths the
     hash/render agreement is about — bare-name image resolving through
     `site.assets:`, an **ambiguous** bare name (`assets/a.png` vs
     `assets/more/a.png`), an unresolved src, an item-relative src, a
     URL-scheme src, an image inside a code fence, an escaped raw `<img>`
     (html disabled), a link-wrapped image, and images on pages as well as
     items. `check` on it reports 5 errors / 4 warnings identically before and
     after.
   - This repo's own project (45 output files): identical.
   - Extra probe (`.scratch/hashprobe.py`), because `content_hash` is not in
     the site output: per-item `content_hash` + `_image_inputs_hash_value`
     contribution for all 303 items. The only line that differs between the
     before and after manifests is the probe's own `_parser.reused` sentinel
     (`n/a` → `True`). Image contributions unchanged, e.g. MD-GOLD-0001 stays
     `[['a.png', None], ['assets/b.png', 'a7da74a9bae60f0f'], ['nope.png', None]]`.
2. **Tests.** `pytest tests/test_image_hash.py tests/test_build.py
   tests/test_eol_fidelity.py tests/test_no_write.py` → 131 passed. Full suite
   as the final gate → **2548 passed, 2 skipped** (174 s).
3. **`refdes check` on this repo's own project** — before/after output byte-
   identical (`.scratch/checkrepo.py`), exit 1 both. The pre-existing
   `items/decisions/dec-pwr-001-regulator-topology.md:2 [DEC-PWR-001] — P_dens
   violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2` appears
   exactly once, same wording including the superscript/unit mismatch. Not
   touched — out of scope.
4. **`ruff check src/refdes/build.py --select I,F`** — 1 finding, `I001` on the
   import block. **Pre-existing**: the same file at HEAD, run through ruff the
   same way, reports the identical `I001` (it is the
   `from . import calc, dates, history as history_mod, imports, seal` ordering,
   nothing to do with `import threading`). Not fixed — out of scope per
   AGENTS.md. No `F` findings.

Also: 8 threads × (a full `load_readonly` + 50 render/parse rounds over a set
of bodies) against single-threaded reference output — no mismatches, no
exceptions.

## Measured, this machine (best-of-5, N=1600 synthetic corpus)

| | before | after | |
|---|---|---|---|
| `build.build()` (model build) | 319.7 ms | **131.7 ms** | −59% |
| `loader.load_readonly` | 372.9 ms | **186.6 ms** | −50% |
| `refdes check` | 372.2 ms | **188.6 ms** | −49% |
| `refdes index` | 424.0 ms | **231.6 ms** | −45% |
| tracemalloc peak, one `load_readonly` | 7.8 MB | 7.8 MB | unchanged |

Per-item model-build cost 0.200 → 0.082 ms. The plan predicted 335→~185 ms;
measured here 320→132 ms — better than predicted, so the parser really was
~59% of the model build on this corpus, not the ~45% the planning pass measured
(machine difference; treat the planning pass's absolutes as ±10% noise).
`parse_items` (39.5 ms) is now the second-biggest phase at 21%, not 10%.

Memory: no decrease. The plan expected one, on the reasoning that one parser
replaces N — but the N parsers were each garbage-collected immediately after
their item, so peak was never N parsers high. Peak is unchanged at 7.8 MB,
which is the honest number.

## Environment notes

- The shared venv's editable install still points at `/tmp/w-pr59-merge`
  (gone), so the `refdes` console script raises `ModuleNotFoundError`. Did NOT
  reinstall it — that would repoint the install other sessions share. Ran every
  CLI invocation through `.scratch/runcli.py`, which inserts this worktree's
  `src` and calls `refdes.cli.main()`. `pytest` is unaffected:
  `tests/conftest.py` bootstraps `../src` itself.
- `.scratch/` did not carry over into this worktree; regenerated the harness
  from the plan's §3 description: `mkperfproj.py` (corpus generator),
  `perf-phases.py`, `mem-bench.py`, `golden.py`, `hashprobe.py`,
  `checkrepo.py`, `runcli.py`. All left in `.scratch/`.
- One probe of my own deadlocked (a `threading.Barrier(5)` the main thread
  never joined) — my bug, fixed, not a finding about the code.

## Status

DONE. Golden diff empty, full suite green, one file changed, changelog fragment
added (`changelog.d/markdown-parser-cache.changed.md`, following the
`libyaml-parsing.changed.md` precedent for a perf entry).
