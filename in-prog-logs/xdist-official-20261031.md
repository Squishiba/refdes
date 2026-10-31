# Parallel pytest runs

- Inspected the two link-edit modules and searched test parametrization sites for minted keys. `test_serve_edit_http_links.py` uses its module-level `K_REQ2` only in fixture data and assertions; the identified random parametrized value is in `test_serve_edit_links.py`.
- Ran the requested pre-change targeted xdist collection command. It unexpectedly succeeded with 12 tests collected, including a random key in the node ID; the reported collection mismatch did not reproduce in this run.
- Replaced that node ID with `surrogate-key`, added pytest-xdist to the `dev` extra, enabled automatic work-stealing in both full-suite CI jobs, and documented the four-worker command in README's existing Tests section.
- Changelog review found `changelog.d/ci-py313-job.added.md`, so this repo does use fragments for CI process changes; added a `changed` fragment for parallel test execution.
- Post-change targeted collection passed: 12 tests collected, with the key case named `[surrogate-key]`. Full collection under xdist passed with 5,565 tests collected.
- Two complete serial collection outputs matched after excluding the elapsed-time summary, confirming identical node IDs across runs.
- Ruff passed for `tests/test_serve_edit_links.py`.
- The requested full xdist suite ran for 2m37s but could not pass in this sandbox: loopback binds raised `PermissionError: Operation not permitted`, yielding 5,035 passed, 2 skipped, 108 failed, and 420 errors. An outside-sandbox rerun was requested and rejected, so the suite result remains unverified outside the sandbox.
- Work completed; changes are committed locally.
