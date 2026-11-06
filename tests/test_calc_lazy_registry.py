"""AUDIT-B: the pint unit registry is built lazily, not at import.

`import refdes.cli` pulls `refdes.calc` through every command's import chain
(`cli -> adopt -> boards -> keys -> ids -> model -> calc`), and building a
`pint.UnitRegistry()` costs a measurable share of every unit-free command's
runtime (audit 2026-11-06 §3.2). These tests pin the contract:

* importing the CLI leaves `pint` out of `sys.modules` entirely;
* the first evaluation imports pint and builds the registry on demand;
* the registry is a single instance per process, even under the thread race
  of serve's preview builds (single-flight, not first-writer-wins);
* Quantity objects copy and pickle losslessly against that one registry;
* the historical module attributes `calc.UREG` / `calc.Q` keep working.
"""

from __future__ import annotations

import subprocess
import sys


def _run(script: str) -> str:
    """Run a probe in a fresh interpreter with this checkout's src on the path."""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_importing_the_cli_does_not_import_pint():
    out = _run("import sys; import refdes.cli; print('pint' in sys.modules)")
    assert out == "False"


def test_importing_calc_alone_does_not_import_pint():
    out = _run("import sys; import refdes.calc; print('pint' in sys.modules)")
    assert out == "False"


def test_first_evaluation_imports_pint_and_evaluates():
    out = _run(
        "import sys\n"
        "import refdes.calc as calc\n"
        "assert 'pint' not in sys.modules, 'pint imported at module import'\n"
        "env = {}\n"
        "outcomes = calc.evaluate_block('P = 3.3 V * 1.2 A', env)\n"
        "assert outcomes[0].error is None, outcomes[0].error\n"
        "assert 'pint' in sys.modules, 'pint never imported by evaluation'\n"
        "print(calc.format_value(env['P']))\n"
    )
    assert out == "3.96 W"


def test_registry_is_built_once_under_a_thread_race():
    out = _run(
        "import threading\n"
        "import refdes.calc as calc\n"
        "n = 16\n"
        "barrier = threading.Barrier(n)\n"
        "regs = []\n"
        "lock = threading.Lock()\n"
        "def worker():\n"
        "    barrier.wait()\n"
        "    r = calc._registry()\n"
        "    with lock:\n"
        "        regs.append(r)\n"
        "threads = [threading.Thread(target=worker) for _ in range(n)]\n"
        "for t in threads: t.start()\n"
        "for t in threads: t.join()\n"
        "assert len(regs) == n\n"
        "assert all(r is regs[0] for r in regs), 'lazy init built more than one registry'\n"
        "print('single')\n"
    )
    assert out == "single"


def test_quantities_copy_and_pickle_losslessly_on_the_one_registry():
    # deepcopy of a pint Quantity stays on its own registry (same class, so
    # same instance); pickling snapshots the registry by value -- true of
    # pint itself, unchanged by laziness. The invariant pinned here is that
    # the process accessor hands out exactly one registry instance.
    out = _run(
        "import copy\n"
        "import pickle\n"
        "import refdes.calc as calc\n"
        "value = calc.parse_quantity('3.3 V')\n"
        "back = pickle.loads(pickle.dumps(value.nom))\n"
        "assert back == value.nom and str(back.units) == str(value.nom.units)\n"
        "deep = copy.deepcopy(value.nom)\n"
        "assert type(deep) is type(value.nom)\n"
        "assert type(deep)._REGISTRY is calc._registry(), 'deepcopy left the registry'\n"
        "assert calc.UREG is calc._registry() and calc.Q is calc._registry().Quantity\n"
        "print('copy-pickle-ok')\n"
    )
    assert out == "copy-pickle-ok"


def test_UREG_and_Q_module_attributes_still_work():
    out = _run(
        "import refdes.calc as calc\n"
        "ureg = calc.UREG\n"
        "assert ureg is calc.UREG, 'UREG attribute not stable'\n"
        "assert ureg.parse_expression('3.3 V') is not None\n"
        "assert calc.Q is calc.Q, 'Q attribute not stable'\n"
        "assert calc.Q(1, 'W').dimensionality == ureg.Quantity(1, 'J/s').dimensionality\n"
        "assert calc.Q(1, 'W')._REGISTRY is ureg\n"
        "print('attrs-ok')\n"
    )
    assert out == "attrs-ok"


def test_calc_imports_pint_for_isinstance_style_consumers():
    """The registry's Quantity class identifies itself as pint's own."""
    out = _run(
        "import pint\n"
        "import refdes.calc as calc\n"
        "q = calc.Q(1, 'V')\n"
        "assert isinstance(q, pint.Quantity)\n"
        "assert isinstance(calc._registry(), pint.UnitRegistry)\n"
        "print('pint-types-ok')\n"
    )
    assert out == "pint-types-ok"
