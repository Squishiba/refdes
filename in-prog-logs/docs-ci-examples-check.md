# docs.yml: gate stale docs examples on deploy (+ comment fix)

Task: small CI change in `.github/workflows/docs.yml`.

## Done

1. Added a `Check docs examples are current` step to the `build` job, between
   `pip install .` and `Build docs-site`, running
   `python docs-site/gen_examples.py --check` from the repo root (no
   `working-directory` key, so it defaults to the workspace root). The script
   (verified: `docs-site/gen_examples.py`, `main()`/`--check`) exits 1 when the
   generated per-type example block in `docs/schema-reference.md` is stale, so
   the docs deploy now fails on stale examples. `pyyaml>=6.0` is a declared
   dependency in `pyproject.toml`, so `pip install .` covers the script's
   `import yaml`; the script also inserts `src/` on `sys.path` itself.
2. Corrected both `docs-site/refdes.yaml` comment references (lines 2 and 43)
   to `docs-site/refdes-project.yaml`. Verified by grep that `site.out`
   (`out: ../_docs`) lives in `docs-site/refdes-project.yaml`; the workflow
   directory no longer has a `refdes.yaml` at all (only
   `refdes-project.yaml` + `refdes-schema.yaml`).

## Verification

- `python docs-site/gen_examples.py --check` -> 0 ("docs\schema-reference.md
  is up to date.").
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/docs.yml'))"`
  -> 0.
- Full suite: see run below / report (pass count in the final report).

## Notes

- Also updated `docs/design/backlog.md` finding 20's Status line: it still
  said "outstanding" although the generator shipped in `1e997b8`; the CI gate
  completes the finding's deploy-time staleness check.
- No changelog fragment (CI-only).