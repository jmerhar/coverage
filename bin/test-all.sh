#!/usr/bin/env bash
# Run every test suite in this repository, printing one summary line each and the full output of any
# that fails.
#
# The Python suites are invoked through $PYTHON_RUNNER so CI can measure them without this list of
# suites being written down twice: `PYTHON_RUNNER="python3 -m coverage run -p" bin/test-all.sh`.
# The shell suites drive their scripts as subprocesses, so they are run directly.
#
# Usage: bin/test-all.sh
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_RUNNER="${PYTHON_RUNNER:-python3}"

PYTHON_SUITES=(test-coverage-report.py test-build-site.py test-make-meta.py)
SHELL_SUITES=(test-collect-coverage.sh test-add-report.sh)

log="$(mktemp)"
trap 'rm -f "$log"' EXIT
failed=()

run() { # name, command...
  local name="$1"; shift
  if "$@" > "$log" 2>&1; then
    # unittest reports on stderr, the shell suites on stdout; either way the tally is what matters.
    printf '  ok   %-26s %s\n' "$name" "$(grep -oE '^(Ran [0-9]+ tests|[0-9]+ passed, [0-9]+ failed)' "$log" | tail -1)"
  else
    failed+=("$name")
    printf '  FAIL %s\n' "$name"
    sed 's/^/       /' "$log"
  fi
}

for suite in "${PYTHON_SUITES[@]}"; do
  # shellcheck disable=SC2086  # PYTHON_RUNNER is a command with arguments, deliberately split
  run "$suite" $PYTHON_RUNNER "$here/$suite"
done
for suite in "${SHELL_SUITES[@]}"; do
  run "$suite" bash "$here/$suite"
done

printf '\n'
if [ ${#failed[@]} -gt 0 ]; then
  printf 'FAILED: %s\n' "${failed[*]}"
  exit 1
fi
printf 'All %s suites passed.\n' "$((${#PYTHON_SUITES[@]} + ${#SHELL_SUITES[@]}))"
