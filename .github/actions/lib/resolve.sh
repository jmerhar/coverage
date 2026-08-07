#!/usr/bin/env bash
# Locate this repository's bin/ from inside a composite action, and check the Python it will run.
#
# Sourced by the coverage actions as: source "$GITHUB_ACTION_PATH/../lib/resolve.sh"
#
# A composite action referenced as `owner/repo/.github/actions/<name>@ref` is unpacked with the whole
# repository around it, so bin/ sits three levels above the action directory. Resolving it here means
# the actions do not each hard-code that relationship.
#
# Sets COVERAGE_BIN. Exits non-zero with an explanation if the layout or the Python is unusable,
# because both failures are otherwise reported as a bare "No such file" from deep inside a script.
set -euo pipefail

COVERAGE_BIN="$(cd "$GITHUB_ACTION_PATH/../../.." && pwd)/bin"

if [ ! -f "$COVERAGE_BIN/coverage-report.py" ]; then
  echo "::error::Could not find the coverage tooling at $COVERAGE_BIN." >&2
  echo "The action expects to be unpacked with its repository; check the 'uses:' reference." >&2
  exit 1
fi

# coverage.toml is read with tomllib, added to the standard library in 3.11.
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "::error::Python 3.11+ is required (coverage.toml is parsed with tomllib); found $(python3 -V 2>&1)." >&2
  echo "Add actions/setup-python with python-version: '3.12' before this step." >&2
  exit 1
fi

export COVERAGE_BIN
