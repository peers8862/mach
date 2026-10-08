#!/usr/bin/env bash
# tests/run.sh: run every test. Usage: bash tests/run.sh [name-filter]
# Needs bash (3.2+) and python3 (3.9+). Never calls a real AI tool or the network: mocks sit first on PATH inside a sandbox
# under <repo>/.tmp/ (gitignored), and HOME / MACH_* variables point there.
# Python tests: python3 -m unittest discover -s tests   (also run from here).
set -u
export PYTHONDONTWRITEBYTECODE=1   # no __pycache__ inside the synced folder
ROOT=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT" || exit 2
FILTER=${1:-}
FAILED=""; TOTAL=0

for t in tests/test_*.sh; do
  case "$t" in *"$FILTER"*) ;; *) continue ;; esac
  TOTAL=$((TOTAL + 1))
  printf '== %s\n' "$t"
  if ! bash "$t"; then FAILED="$FAILED $t"; fi
done

if command -v python3 >/dev/null 2>&1; then
  TOTAL=$((TOTAL + 1))
  printf '== python unittest (tests/test_*.py)\n'
  if ! python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -n 15; then :; fi
  # `tail` hides the exit code: run again quietly for the verdict
  if ! python3 -m unittest discover -s tests -p 'test_*.py' >/dev/null 2>&1; then FAILED="$FAILED python-unittest"; fi
else
  printf 'python3 not found: python tests skipped\n'
  FAILED="$FAILED python3-missing"
fi

# leftovers from a crashed test never stay behind
case "$ROOT/.tmp" in "$ROOT"/.tmp) rmdir "$ROOT/.tmp" 2>/dev/null || true ;; esac

printf '\n'
if [ -z "$FAILED" ]; then
  printf 'ALL %d test groups passed\n' "$TOTAL"
  exit 0
fi
printf 'FAILED:%s\n' "$FAILED"
exit 1
