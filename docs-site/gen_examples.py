#!/usr/bin/env python3
"""Generate the per-type filled-in examples in docs/schema-reference.md.

The reference docs described schema *abstractly* and never showed a filled-in,
valid instance of any type -- exactly the artifact `refdes new <type>` already
generates from the resolved schema (backlog finding 20). This script closes
that gap at docs-build time: it runs the identical generator
(`scaffold.new_item_text()`, the function `refdes new` itself calls) for every
type in the pinned standard and injects the results between the markers in
`docs/schema-reference.md`, labelled with the standard version they came from.

The wrinkle the finding flags: `docs-site/` pins no `standard:` of its own --
it is a pages-only project -- so there is nothing to generate *from* there.
The pin is read from the repo's own `refdes-project.yaml` `standard:` block
and replayed against a scratch project with **no schema overlay**, so the
examples show the standard's types, not this project's `log`-field tweak.

Staleness is the failure mode this exists to prevent, and it is gated, not
hoped for: `tests/test_docs_examples.py` asserts the injected block equals
live generator output, so a hand-edited or stale example fails the test
suite rather than shipping as a successful-but-wrong docs build.

    python docs-site/gen_examples.py           # rewrite the block in place
    python docs-site/gen_examples.py --check   # exit 1 if the block is stale
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from refdes import scaffold as scaffold_mod  # noqa: E402
from refdes.schema import load_project  # noqa: E402

PROJECT_CONFIG = os.path.join(ROOT, "refdes-project.yaml")
TARGET_DOC = os.path.join(ROOT, "docs", "schema-reference.md")

BEGIN = "<!-- BEGIN GENERATED per-type-examples -->"
END = "<!-- END GENERATED per-type-examples -->"
_BLOCK_RE = re.compile(
    re.escape(BEGIN) + r"\n(.*?)" + re.escape(END),
    re.DOTALL,
)


def standard_pin(config_path: str = PROJECT_CONFIG) -> dict:
    """The repo's own `standard:` block, read raw.

    Read from the settings file rather than a resolved Project on purpose:
    the pin is the pointer, and the examples must track *this repo's* pin --
    whatever version `refdes-project.yaml` says is current -- not a number
    hard-coded here that would go stale on the next bump.
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    standard = raw.get("standard")
    if not isinstance(standard, dict):
        raise SystemExit(
            f"{config_path} has no standard: block to pin the examples to"
        )
    return standard


def pinned_project():
    """A Project resolving the repo's pinned standard with no overlay.

    A scratch project dir holding only `standard:` (plus the minimal site/id
    keys every settings file needs) is loaded, so the resolved types are the
    standard's own -- the repo's `refdes-schema.yaml` overlay (a project-
    specific `log.board` field) must not leak into examples labelled as the
    standard.
    """
    standard = standard_pin()
    with tempfile.TemporaryDirectory(prefix="refdes-docs-examples-") as tmp:
        config = os.path.join(tmp, "refdes-project.yaml")
        doc = {
            "site": {"title": "Docs examples", "out": "_site"},
            "id": {"width": 3, "ledger": ".refdes/ids.yaml"},
            "standard": standard,
        }
        with open(config, "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh, sort_keys=False)
        # The Project is fully resolved at load; deleting the scratch dir
        # afterwards cannot invalidate the in-memory ItemType specs.
        return load_project(config_path=config), standard


def render_block() -> str:
    """The generated markdown: one fenced example per type, version-labelled."""
    project, standard = pinned_project()
    label = f"{standard['base']}@{standard['version']}"

    lines = [
        f"Every example below is live `refdes new <type>` output -- the same",
        f"`scaffold.new_item_text()` the CLI calls, run against the resolved",
        f"**{label}** schema pinned in this repo's `refdes-project.yaml`, and",
        f"written here by `python docs-site/gen_examples.py`. Do not hand-edit",
        f"this block: `tests/test_docs_examples.py` fails if it differs from",
        f"what the generator produces today.",
        "",
    ]
    for type_name, spec in project.types.items():
        lines.append(f"#### `{type_name}` — {label}")
        lines.append("")
        lines.append("```yaml")
        # new_item_text() already ends with its trailing newline; writing it
        # verbatim keeps the fenced content byte-identical to `refdes new`.
        lines.append(scaffold_mod.new_item_text(type_name, spec) + "```")
        lines.append("")
    return "\n".join(lines)


def extract_block(page_text: str) -> str:
    """The current generated content between the markers, or '' if absent."""
    match = _BLOCK_RE.search(page_text)
    return match.group(1) if match else ""


def inject(page_text: str, block: str) -> str:
    """`page_text` with the marker region replaced by `block`."""
    if not _BLOCK_RE.search(page_text):
        raise SystemExit(
            f"markers not found in the target page -- add the BEGIN/END "
            f"'per-type-examples' marker lines first:\n  {BEGIN}\n  {END}"
        )
    return _BLOCK_RE.sub(lambda m: BEGIN + "\n" + block + END, page_text, count=1)


def is_current(page_text: str) -> bool:
    return extract_block(page_text) == render_block()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the injected block is stale",
    )
    args = parser.parse_args(argv)

    with open(TARGET_DOC, "r", encoding="utf-8") as fh:
        page = fh.read()

    if args.check:
        if is_current(page):
            print(f"{os.path.relpath(TARGET_DOC, ROOT)} is up to date.")
            return 0
        print(
            f"{os.path.relpath(TARGET_DOC, ROOT)} carries a stale generated "
            "example block -- run `python docs-site/gen_examples.py`.",
            file=sys.stderr,
        )
        return 1

    updated = inject(page, render_block())
    with open(TARGET_DOC, "w", encoding="utf-8") as fh:
        fh.write(updated)
    print(f"updated {os.path.relpath(TARGET_DOC, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
