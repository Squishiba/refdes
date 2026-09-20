#!/usr/bin/env python3
"""Generate the derived reference content in the docs site.

Two artifacts, both staleness-gated marker-injected pages:

- the per-type filled-in examples in `docs/schema-reference.md` (finding 20);
- `docs/vocabulary.md`, the bundled standard's own vocabulary page (finding
  38) -- the same `refdes.vocabulary` a built site renders as its
  `vocabulary.html`, rendered as markdown so the docs site gives it its own
  chrome and anchors. The docs site is pages-only and pins no `standard:` of
  its own, so it gets the vocabulary page as generated markdown rather than
  as a built report.

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
from refdes import vocabulary as vocabulary_mod  # noqa: E402
from refdes.schema import load_project  # noqa: E402

PROJECT_CONFIG = os.path.join(ROOT, "refdes-project.yaml")
TARGET_DOC = os.path.join(ROOT, "docs", "schema-reference.md")
VOCAB_DOC = os.path.join(ROOT, "docs", "vocabulary.md")

BEGIN = "<!-- BEGIN GENERATED per-type-examples -->"
END = "<!-- END GENERATED per-type-examples -->"
_BLOCK_RE = re.compile(
    re.escape(BEGIN) + r"\n(.*?)" + re.escape(END),
    re.DOTALL,
)

VOCAB_BEGIN = "<!-- BEGIN GENERATED vocabulary -->"
VOCAB_END = "<!-- END GENERATED vocabulary -->"
_VOCAB_BLOCK_RE = re.compile(
    re.escape(VOCAB_BEGIN) + r"\n(.*?)" + re.escape(VOCAB_END),
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


def render_vocabulary_block() -> str:
    """The bundled standard's vocabulary as markdown, version-labelled.

    Same resolved schema as the examples: the repo's pin, replayed against a
    scratch project with no overlay, so the page describes the standard and
    not this repo's `log` tweak.
    """
    project, standard = pinned_project()
    label = f"{standard['base']}@{standard['version']}"
    header = (
        f"Every term below is what the resolved **{label}** schema in this "
        f"repo's `refdes-project.yaml` means today, written here by "
        f"`python docs-site/gen_examples.py`. A built site renders the same "
        f"structure as its own `vocabulary.html`, from its own resolved "
        f"schema -- base standard, presets, and the project's overlay. Do "
        f"not hand-edit this block: `tests/test_vocabulary_page.py` fails if "
        f"it differs from what the generator produces today.\n"
    )
    return header + "\n" + vocabulary_mod.render_markdown(project)


def _extract(page_text: str, pattern: re.Pattern) -> str:
    match = pattern.search(page_text)
    return match.group(1) if match else ""


def _inject(page_text: str, block: str, pattern: re.Pattern, begin: str, end: str, name: str) -> str:
    if not pattern.search(page_text):
        raise SystemExit(
            f"markers not found in the target page -- add the BEGIN/END "
            f"'{name}' marker lines first:\n  {begin}\n  {end}"
        )
    return pattern.sub(lambda m: begin + "\n" + block + end, page_text, count=1)


def extract_block(page_text: str) -> str:
    """The current generated content between the markers, or '' if absent."""
    return _extract(page_text, _BLOCK_RE)


def extract_vocabulary_block(page_text: str) -> str:
    return _extract(page_text, _VOCAB_BLOCK_RE)


def inject(page_text: str, block: str) -> str:
    """`page_text` with the marker region replaced by `block`."""
    return _inject(page_text, block, _BLOCK_RE, BEGIN, END, "per-type-examples")


def inject_vocabulary(page_text: str, block: str) -> str:
    return _inject(page_text, block, _VOCAB_BLOCK_RE, VOCAB_BEGIN, VOCAB_END, "vocabulary")


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

    stale = False
    for page in (
        (TARGET_DOC, extract_block, inject, render_block),
        (VOCAB_DOC, extract_vocabulary_block, inject_vocabulary, render_vocabulary_block),
    ):
        path, extract, inject_page, render = page
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        block = render()
        if args.check:
            if extract(text) == block:
                print(f"{os.path.relpath(path, ROOT)} is up to date.")
                continue
            print(
                f"{os.path.relpath(path, ROOT)} carries a stale generated "
                "block -- run `python docs-site/gen_examples.py`.",
                file=sys.stderr,
            )
            stale = True
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(inject_page(text, block))
        print(f"updated {os.path.relpath(path, ROOT)}")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
