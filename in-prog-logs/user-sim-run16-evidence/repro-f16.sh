#!/usr/bin/env bash
# Run 16, F16-1 retraction / F16-5 subject reproduction, built to run
# from a checkout of the PR. It exercises the two "id-less" shapes the
# review asked to distinguish:
#   A. a yaml LIST-FILE entry with no `id:` (the shape docs/getting-started.md
#      teaches pre-`refdes id`) -> load ERROR, marker excluded with the project
#      red and the fix named in the message;
#   B. a markdown THREAD entry with `key:` and no `id:` (a keyed thread tip)
#      -> loads clean, marker IS listed (empty id column = F16-5).
# Usage: from the repo checkout root, run `bash repro-f16.sh` with the
# package importable (PYTHONPATH=src) and a python interpreter:
#   PYTHONPATH=$PWD/src python repro-f16.sh
# (or point REFDES at an installed `refdes` CLI).
set -u
SRC="$(cd "$(dirname "$0")" && pwd)"
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
mkdir -p "$FIX/items"
ROOT="$PWD"
cd "$FIX"
printf 'site:\n  title: Repro16\n  out: _site\nstandard:\n  base: hardware\n  version: 3\nid:\n  width: 3\n' > refdes-project.yaml
cat > items/listfile.yaml <<'EOF'
items:
  - type: log
    prefix: LOG-C
    body: "note body <!--navi: marker A--> "
EOF
cat > items/thread.md <<'EOF'
---
defaults:
  type: log
  prefix: LOG-A
---
id: LOG-A-001
key: dgqvaw9hj55
summary: Seed.
date: 2026-11-01
---

Seed body.

---
key: 4jfd3hhpajc
summary: Keyed tip, no id.
date: 2026-11-02
follows: LOG-A-001@dgqvaw9hj55
---

Tip body with <!--navi: marker B--> inside.
EOF
echo "== refdes check =="
RUN check
echo "== refdes navis ls =="
RUN navis ls
echo "== expected =="
echo 'check: ERROR .../listfile.yaml:2 — item has no id — run '"'"'refdes id'"'"' to allocate one (entry A excluded from the project, marker A unlisted);'
echo 'navis ls: marker B listed on the KEYED id-less THREAD tip with an EMPTY id column (F16-5); the project is red only because of entry A.'
echo "fixture kept at ${FIX#"$ROOT"/}"
