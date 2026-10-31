- The AgentCoder driver (`tools/agentcoder/`, its tests, fixtures, design/progress
logs and the "AgentCoder supervised mode" docs page) has left this repository for its
own project, `agentcoder`. It never imported refdes and is not part of the refdes
tool or its docs; the only thing left behind is the `tests/fixtures/agentcoder347`
project, which `tests/test_inline_calc_agentcoder_trial.py` still uses as a refdes
fixture.
