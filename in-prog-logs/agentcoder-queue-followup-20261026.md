# AgentCoder queue follow-up — 2026-10-26

Scope: tests and documentation follow-up for merged #376; `tools/agentcoder/*.py` was not changed.

## Progress

- Read `AGENTS.md`; checkout began clean at `2f23121` on `chore/agentcoder-queue-followup`.
- T1: changed the Windows atomic JSON test to record all `os.open` calls and require none. In `.scratch/queue_mode_no_win_guard.py`, deleting the `win32` early return made the targeted test fail with the recorded job-directory open.
- T2: added a third disposable-copy mutation probe that skips reading state paths. With `timeout=0`, the wait check fails at `assert event['status']=='landed' and code==0`; the captured traceback is retained under `.scratch/agentcoder-mutation-*/mutation-result.txt`.
- T3: added corrupt-state coverage for `queue wait` (`cli` returns 1 and bytes remain identical). Observed `supervise()` catches corruption and overwrites `state.json` with a parked supervisor-failure record; the test asserts that behavior rather than claiming it preserves corrupt bytes.
- T4: both pre-existing `supervise()` no-child tests now have a `subprocess.run` fake that fails if a driver child is spawned, plus no-op sleep functions. The corrupt-state supervisor test also has the same child guard.
- T5: use `pytest.skip` when `fcntl` is absent; increased thread wait/join margins from 2s/0.1s to 10s/0.5s.
- T6: platform/os/time patches in queue tests now shadow attributes on the module under test. The monotonic fake is a call counter rather than a two-value iterator. No requested process-global patch remained that needed to be skipped.
- T7: corrected the failure-matrix wording and marked future-design subsection headings `NOT SHIPPED in #376`; fixture README now explains the differing command payload key casing and cwd shapes for `inspect.json` and `ls-g.json`.
- T8: bound loop closure variables, removed the unused state result and tautological env assertion, and added scope-specific wait-test docstrings describing what each does and does not simulate.

## Verification

The first full run exposed six test setup failures from duplicate keyword construction in local namespace shadows; corrected those. Focused rerun of those cases and the new mutation/corrupt tests passed. Final combined run passed: 203 tests across the queue suite and three legacy AgentCoder suites. `ruff check tests/test_agentcoder_queue.py` and `git diff --check` passed. No `tools/agentcoder/*.py` file changed.
