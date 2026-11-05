Added `tools/docs_context/refs.py`, a maintainer-only tool that parses a
docs page with the site's own markdown parser and prints one JSON object of
fact cards for every code ref, file ref, `refdes` command and link the page
makes. It lives under `tools/`, is not shipped in the package, and is strictly
read-only: paths are refused before they are opened, and a command's card runs
`--help` as a list argv only when refdes's own argparse accepts the verb path.
