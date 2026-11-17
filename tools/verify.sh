#!/usr/bin/env bash
# Runs lint, security scan, tests with coverage and the E2E suite. Ends in PASS or FAIL.
# Usage: tools/verify.sh            # everything
#        tools/verify.sh --quick    # skip E2E
set -uo pipefail

cd "$(dirname "$0")/.."
export PATH="$PWD/.venv/bin:$PATH"   # E2E calls `imnot`; use the venv one, not a global install
status=0

echo "== Lint"
ruff check imnot/ tests/ && ruff format --check imnot/ tests/ || status=1

echo "== Security (bandit)"
out=$(bandit -r imnot/ -q -f screen 2>&1) || { status=1; echo "$out"; }

echo "== Tests"
pytest -q --cov=imnot --cov-report=term-missing:skip-covered 2>&1 | tail -n 25
[[ ${PIPESTATUS[0]} -eq 0 ]] || status=1

if [[ "${1:-}" != "--quick" ]]; then
	echo "== E2E"
	# Capture the exit code before filtering: an "|| true" after grep would overwrite PIPESTATUS.
	out=$(bash scripts/qa/run.sh 2>&1) || status=1
	grep -E "\[FAIL\]|Results:" <<<"$out"
fi

if [[ $status -eq 0 ]]; then echo "PASS"; else echo "FAIL"; fi
exit $status
