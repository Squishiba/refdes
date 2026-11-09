#!/usr/bin/env python3
"""Claims check for the run-17 gate report.

Extracts every backticked span from the report, normalizes whitespace and
quotes, splits spans on the ellipsis character, and greps each fragment
against the concatenated evidence files. Fragments that carry verifiable
content (a digit, a colon, a double dash, a slash, or ALL-CAPS identifiers)
must be found; a MISS means add the evidence or soften the claim.
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
REPORT = HERE.parent / "user-sim-release-gate-run17.md"

evidence = "\n".join(
    p.read_text() for p in sorted(HERE.iterdir())
    if p.is_file() and p.name not in {"claims-check.py", "claims-check.txt"}
)
names = {p.name for p in HERE.iterdir()} | {HERE.name}


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s).replace('"', "")
    return s.replace("[ ", "[").replace(" ]", "]").strip()


def verifiable(frag: str) -> bool:
    if any(c.isdigit() for c in frag):
        return True
    if ":" in frag or "--" in frag or "/" in frag:
        return True
    letters = [c for c in frag if c.isalpha()]
    return len(letters) >= 8 and sum(c.isupper() for c in letters) >= 0.6 * len(letters)


evidence_n = norm(evidence)
report = REPORT.read_text()

misses: list[tuple[int, str]] = []
checked = 0
for lineno, line in enumerate(report.splitlines(), 1):
    for span in re.findall(r"``([^`]+)``|`([^`\n]+)`", line):
        span = (span[0] or span[1]).rstrip("/")
        if span in names:
            continue
        for frag in norm(span).split("…"):
            frag = frag.strip(" ,.;:()[]{}'`*")
            if len(frag) < 4 or not verifiable(frag):
                continue
            checked += 1
            if frag not in evidence_n:
                misses.append((lineno, frag))

print(f"report: {REPORT.name}; evidence dir: {HERE.name}")
print(f"fragments checked: {checked}; misses: {len(misses)}")
for lineno, frag in misses:
    print(f"  MISS line {lineno}: {frag[:110]}")
