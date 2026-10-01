"""Where the docs are for someone who installed refdes from a wheel.

A repo-relative "docs/parts.md" resolves only inside a git checkout of this
repo, and the wheel ships no .md files at all (packages.find is scoped to
src/, package-data carries only templates/standards/serve-static), so such a
path names a file that does not exist for the person reading it -- in the
brand-new project `refdes init` just created for them. The published Pages
site is the one form of the reference that resolves everywhere; .github/
workflows/docs.yml deploys docs-site/ to it on every push to main.

This lives in its own module rather than in cli.py because the diagnostics
that point at a page come from build/keys/links/configcheck, none of which
should import the CLI back (cli imports all four). cli re-exports DOCS_URL,
so `from refdes.cli import DOCS_URL` keeps working.

The page URLs below are the *user* docs, all of which docs-site publishes:
docs-site/refdes-project.yaml sets site.pages to ../docs, so every docs/*.md
is a page, and nav.py renders a top-level docs/<page>.md to <page>.html --
verified by building docs-site/ and listing _docs/**/*.html, not assumed.
docs/design/*.md is published too but flattened to design-<name>.html, and is
aimed at contributors rather than users; where a message wants the user docs
for a topic, it names one of these instead.
"""

# Base of the published site. `pyproject.toml`'s [project.urls] Documentation
# entry is the same URL.
DOCS_URL = "https://squishiba.github.io/refdes"

# `boards:` and `workspaces:` are documented on their own pages (the two
# configcheck unknown-key errors). Direct mappings, both pages in the nav.
MULTI_BOARD_DOCS = f"{DOCS_URL}/multi-board.html"
WORKSPACES_DOCS = f"{DOCS_URL}/workspaces.html"

# The user docs for surrogate keys: composite form, `keys restore`, and why a
# composite nobody typed can fail to resolve. One page for all four messages
# that used to cite the contributor-facing docs/design/keys.md. The anchor is
# troubleshooting.md's own `## Surrogate keys` heading.
SURROGATE_KEYS_DOCS = f"{DOCS_URL}/troubleshooting.html#surrogate-keys"

# The user docs for a structured reference that resolves to nothing: the
# `<link verb> points at 'X', which does not exist` family, and what to do
# when the item was renamed by hand. troubleshooting.md's own `## Links`
# heading.
DANGLING_LINK_DOCS = f"{DOCS_URL}/troubleshooting.html#links"
