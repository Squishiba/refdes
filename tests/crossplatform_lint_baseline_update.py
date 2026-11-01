#!/usr/bin/env python
"""Regenerate crossplatform_lint_baseline.json from the current tree.

The ratchet test in tests/test_crossplatform_lint.py fails when any
per-file hit count rises (a new regression) AND when a count falls below
baseline (good news, recorded debt: lower the baseline in the same PR).
Run this after fixing offending code, and commit the lowered baseline
together with the fix.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_crossplatform_lint import BASELINE_PATH, baseline_dict, scan_repo


def main():
    findings = scan_repo()
    data = baseline_dict(findings)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    BASELINE_PATH.write_bytes(text.encode("utf-8"))
    for rule in sorted(data):
        total = sum(data[rule].values())
        files = len(data[rule])
        print(f"{rule}: {total} hits across {files} files")
    print(f"wrote {BASELINE_PATH}")


if __name__ == "__main__":
    main()
