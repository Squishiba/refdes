#!/usr/bin/env bash
# Run 16, F16-1 (Low, docs/UX) reproduction: on the exact
# docs/getting-started.md pre-`refdes id` shape (yaml list file, entry
# with a body carrying a navi marker, NO id), `check` is loud
# (load ERROR, exit 1) but `navis ls` answers with a plain-empty
# message that claims no marker exists in any body, exit 0.
# From the repo checkout root (fixtures are created under the repo .scratch/):
#   REPO=$PWD PYTHONPATH=$PWD/src bash repro-f16-ls.sh
# (or REFDES=<installed refdes> bash repro-f16-ls.sh)
set -u
REPO="${REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
REFDES="${REFDES:-}"
if [ -z "$REFDES" ]; then
  export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
  RUN() { python -c 'import sys;from refdes.cli import main;sys.exit(main())' "$@"; }
else
  RUN() { "$REFDES" "$@"; }
fi
SCRATCH="${REFDES_SCRATCH:-$PWD/.scratch}"
mkdir -p "$SCRATCH"
FIX="$(mktemp -d -p "$SCRATCH")"
mkdir -p "$FIX/items/requirements"
ROOT="$PWD"
cd "$FIX"
printf 'site:\n  title: F16LS\n  out: _site\nstandard:\n  base: hardware\n  version: 3\nid:\n  width: 3\n' > refdes-project.yaml
cat > items/requirements/power.yaml <<'EOF'
defaults:
  type: requirement
  prefix: REQ-PWR
  owner: J. Bin
  tags: [power]
  status: active

items:
  - body: "The unit shall survive 1.2 kV surges. <!--navi: check the surge rating-->"
    source: Customer spec rev D, §3.1
EOF
echo "== refdes --no-write check =="
RUN --no-write check; echo "exit=$?"
echo "== refdes --no-write navis ls =="
RUN --no-write navis ls; echo "exit=$?"
echo "== refdes id =="
RUN id; echo "exit=$?"
echo "== refdes --no-write navis ls (after id) =="
RUN --no-write navis ls; echo "exit=$?"
echo "== expected =="
echo 'check: ERROR items/requirements/power.yaml:9 — item has no id — run '"'"'refdes id'"'"' to allocate one; 0 items, 1 errors; exit 1.'
echo 'navis ls BEFORE id: "no Navis: no `<!--navi: text-->` marker in any item body", exit 0 -- no error, no hint'
echo 'that the entry carrying the marker was skipped for having no id; after `refdes id` the same marker lists.'
echo "fixture kept at ${FIX#"$ROOT"/}"
