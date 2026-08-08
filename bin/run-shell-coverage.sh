#!/usr/bin/env bash
# Run the shell test suites under kcov and leave a merged report in coverage/shell/.
#
# The suites invoke their target through $SHELL_RUNNER, which this sets to a kcov invocation. kcov must
# be given the *script* rather than `bash script` — handed the interpreter it instruments the bash
# binary and reports nothing — and the default PS4 collection method must be used, since
# --bash-method=DEBUG fails outright on macOS.
#
# kcov accumulates into one output directory across invocations, producing a merged report beside one
# report per traced invocation. Only the merged one is published (see coverage.toml).
#
# kcov is not packaged for Ubuntu 24.04 (its Debian package was dropped over an FTBFS with GCC 15), so
# CI falls back to the upstream image. A locally installed kcov is preferred because it avoids the
# container round-trip; both produce identical figures.
#
# Set $JUNIT_DIR to also collect the suites' JUnit reports there, as bin/test-all.sh does.
#
# Usage: bin/run-shell-coverage.sh   (set KCOV_FORCE_DOCKER=1 to exercise the container path)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"

# Pinned by digest so the reported percentage cannot drift when the tag moves. Image: kcov/kcov
# v44-pre-test3. It carries Python 3.11 (tomllib, which coverage.toml needs) but not git, which
# bin/test-add-report.sh drives; update deliberately, then re-check the gate in coverage.toml.
KCOV_IMAGE=${KCOV_IMAGE:-kcov/kcov@sha256:481289ae32e55e5b733019515acd10948a4f76dfed381765577db909664fc603}

SUITES=(test-collect-coverage.sh test-add-report.sh)
OUT=coverage/shell
EXCLUDE=/bin/test-,/bin/run-shell-coverage.sh

cd "$root"
rm -rf "$OUT"
mkdir -p "$OUT"

# Empty unless a JUnit report was asked for, in which case each suite writes its own.
junit_out() { # suite
  [ -n "${JUNIT_DIR:-}" ] || return 0
  printf '%s/%s.xml' "$JUNIT_DIR" "${1%.sh}"
}

# --include-path limits the report to this repo's shell. The suites and this driver live in bin/ too
# and are harness rather than the code under test, so they are excluded.
kcov_runner() { # output-dir
  printf 'kcov --include-path=%s/bin --exclude-pattern=%s %s' "$1" "$EXCLUDE" "$1/$OUT"
}

if [ -z "${KCOV_FORCE_DOCKER:-}" ] && command -v kcov >/dev/null 2>&1; then
  echo "Running the shell suites under the local kcov …"
  for suite in "${SUITES[@]}"; do
    SHELL_RUNNER="$(kcov_runner "$root")" JUNIT_OUT="$(junit_out "$suite")" \
      bash "$here/$suite" | tail -2
  done
else
  if [ -n "${KCOV_FORCE_DOCKER:-}" ]; then
    echo "KCOV_FORCE_DOCKER is set; running the shell suites in $KCOV_IMAGE …"
  else
    echo "kcov not installed locally; running the shell suites in $KCOV_IMAGE …"
  fi
  # $JUNIT_DIR is repo-relative here, since only the repository is mounted into the container.
  case "${JUNIT_DIR:-}" in
    /*) echo "run-shell-coverage: JUNIT_DIR must be repo-relative for the container path" >&2
        exit 2;;
  esac
  docker run --rm -v "$root":/src -w /src --entrypoint bash \
    -e "JUNIT_DIR=${JUNIT_DIR:-}" -e "EXCLUDE=$EXCLUDE" -e "OUT=$OUT" \
    -e "SUITES=${SUITES[*]}" "$KCOV_IMAGE" -c '
    set -eu
    apt-get update -qq >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git >/dev/null
    for suite in $SUITES; do
      junit=""
      if [ -n "$JUNIT_DIR" ]; then junit="/src/$JUNIT_DIR/${suite%.sh}.xml"; fi
      SHELL_RUNNER="kcov --include-path=/src/bin --exclude-pattern=$EXCLUDE /src/$OUT" \
        JUNIT_OUT="$junit" bash "bin/$suite" | tail -2
    done
    # The container runs as root; keep what it wrote readable by the host user and later CI steps.
    chmod -R a+rX "/src/$OUT"
    if [ -n "$JUNIT_DIR" ]; then chmod -R a+rX "/src/$JUNIT_DIR"; fi
  '
fi

if [ ! -f "$OUT/kcov-merged/coverage.json" ]; then
  echo "run-shell-coverage: kcov produced no merged report in $OUT" >&2
  exit 1
fi
echo "Shell coverage in $OUT/kcov-merged/"
