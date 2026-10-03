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

# The user docs for how one item file is read: the `duplicate key ... in one
# mapping` family (a repeated key, which YAML resolves by keeping the last
# value, and the shape that causes it), among the rest of that section's
# per-message catalogue. troubleshooting.md's own `## Items and fields`
# heading -- slug checked against `pages._slugify`, the function that
# generates the anchors, rather than guessed.
ITEMS_FIELDS_DOCS = f"{DOCS_URL}/troubleshooting.html#items-and-fields"

# The user docs for a `page:` that is not a page number -- the one breaking
# declaration error in the page-`#fragment` delta, and the one diagnostic of it
# with no remedy of its own. What to write instead is a citation question
# rather than an items-and-fields one (a range is one entry per page; a printed
# page number is not the PDF's own sheet), so it points at troubleshooting.md's
# own `## Citations` heading rather than reusing ITEMS_FIELDS_DOCS -- slug
# checked against `pages._slugify` the same way.
CITATION_PAGE_DOCS = f"{DOCS_URL}/troubleshooting.html#citations"

# The user docs for the design log's append-only rules: the two `sealing:
# build` sealed-entry errors, the `edited after captured` warning a
# history-backed type gets in their place, and the one move that is legal in
# both -- a new entry that `amends` the old one. troubleshooting.md's own
# `## The design log` heading, which is the page that quotes the warning word
# for word and gives the advice the warning now carries; slug checked against
# `pages._slugify` and against the anchors of a real build of docs-site/.
DESIGN_LOG_DOCS = f"{DOCS_URL}/troubleshooting.html#the-design-log"
