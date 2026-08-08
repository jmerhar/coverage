#!/usr/bin/env bash
# Run every test suite in this repository, printing one summary line each and the full output of any
# that fails.
#
# The Python suites are invoked through $PYTHON_RUNNER so CI can measure them without this list of
# suites being written down twice: `PYTHON_RUNNER="python3 -m coverage run -p" bin/test-all.sh`.
# The shell suites drive their scripts as subprocesses, so they are run directly.
#
# Set $JUNIT_DIR to also write JUnit reports there, which is what Codecov's test analytics reads. The
# Python suites then run under pytest, since unittest cannot write JUnit itself; without it nothing but
# bash and python3 is needed.
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
    printf '  ok   %-26s %s\n' "$name" "$(grep -oE '^(Ran [0-9]+ tests|[0-9]+ passed, [0-9]+ failed)|[0-9]+ passed' "$log" | tail -1)"
  else
    failed+=("$name")
    printf '  FAIL %s\n' "$name"
    sed 's/^/       /' "$log"
  fi
}

if [ -n "${JUNIT_DIR:-}" ]; then
  mkdir -p "$JUNIT_DIR"
  # One pytest run over all three, so the measured run and the reported one are the same run. pytest
  # collects unittest.TestCase classes directly; each file's `unittest.main()` guard simply never fires.
  # shellcheck disable=SC2086  # PYTHON_RUNNER is a command with arguments, deliberately split
  run "python suites" $PYTHON_RUNNER -m pytest -q --junitxml="$JUNIT_DIR/python.xml" \
    "${PYTHON_SUITES[@]/#/$here/}"
else
  for suite in "${PYTHON_SUITES[@]}"; do
    # shellcheck disable=SC2086  # as above
    run "$suite" $PYTHON_RUNNER "$here/$suite"
  done
fi

# CI runs these through bin/run-shell-coverage.sh instead, which drives them under kcov to measure
# them; skipping here keeps them from running twice.
if [ -z "${SKIP_SHELL_SUITES:-}" ]; then
  for suite in "${SHELL_SUITES[@]}"; do
    if [ -n "${JUNIT_DIR:-}" ]; then
      JUNIT_OUT="$JUNIT_DIR/${suite%.sh}.xml" run "$suite" bash "$here/$suite"
    else
      run "$suite" bash "$here/$suite"
    fi
  done
fi

# A malformed report is worse than none: the upload tolerates errors, so Codecov would simply show no
# tests and nothing would say why. Fail here instead.
if [ -n "${JUNIT_DIR:-}" ]; then
  for report in "$JUNIT_DIR"/*.xml; do
    [ -f "$report" ] || continue
    if ! python3 -c 'import sys,xml.etree.ElementTree as ET; ET.parse(sys.argv[1])' "$report"; then
      printf '  FAIL %s is not well-formed XML\n' "$report"
      failed+=("$(basename "$report")")
    fi
  done
fi

printf '\n'
if [ ${#failed[@]} -gt 0 ]; then
  printf 'FAILED: %s\n' "${failed[*]}"
  exit 1
fi
ran=${#PYTHON_SUITES[@]}
[ -z "${SKIP_SHELL_SUITES:-}" ] && ran=$((ran + ${#SHELL_SUITES[@]}))
printf 'All %s suites passed.\n' "$ran"
