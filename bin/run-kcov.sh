#!/usr/bin/env bash
# Run a project's kcov suite and leave its merged report in the suite's `html` directory, using a local
# kcov when it can do the job and the pinned kcov container otherwise.
#
# Shared by every project that measures shell with kcov. What differs between them — the command that
# runs the tests, what the container needs installed, the bash the scripts require — is declared on the
# kcov suite in the project's coverage.toml and read through coverage-report.py --format kcov, so the
# config is parsed in one place:
#
#   [suites.scripts]
#   format   = "kcov"
#   report   = "coverage/kcov-merged/coverage.json"
#   html     = "coverage"
#   command  = "bats test/"         # run with COVERAGE_DIR set to html's absolute path
#   packages = ["bats", "git"]      # installed with apt-get in the container
#   requires = ["bats"]             # commands a local run needs, besides kcov
#   min_bash = 4                    # the bash a local kcov must trace with
#   setup    = "bin/setup.sh"       # optional, run in the container before command
#   local    = false                # optional, always measure in the container
#
# The command applies kcov itself, per invocation, reading COVERAGE_DIR: kcov wrapped around a test
# runner collects nothing, because the runner executes the scripts in grandchild processes (kcov issue
# #462). kcov must be handed the script, not `bash script`, or it instruments the bash binary.
#
# A local kcov is used when it and every `requires` command are installed and, if `min_bash` is set, a
# probe shows it traces with that bash or newer. Stock kcov on macOS traces with /bin/bash (3.2)
# whatever the shebang, so a suite whose scripts need bash 4 falls back to the container there instead
# of failing on syntax the scripts are allowed to use. kcov is not packaged for Ubuntu 24.04, so CI
# always takes the container. Both produce the same figures for scripts that behave the same on macOS
# and Linux; a suite whose scripts branch on the platform, the coreutils flavour or root sets
# `local = false`, so its figure is always the one CI publishes.
#
# kcov writes kcov-merged/ only once a second script is traced into a directory, and the published
# report is the merged one, so it is merged here whenever the run did not produce it.
#
# Usage: run-kcov.sh [--config coverage.toml] [--suite NAME]    (from the project root)
#   JUNIT_DIR=junit       exported to the command, which decides whether to write JUnit there
#   KCOV_FORCE_DOCKER=1   use the container even when the local toolchain would do
#
# Finds coverage-report.py beside itself, which is where both the coverage actions and a project's
# fetched copy of the tooling keep it.
set -o errexit
set -o nounset
set -o pipefail

# Pinned by digest so a reported percentage cannot drift when the tag moves. Image: kcov/kcov
# v44-pre-test3. Update deliberately, then re-check the gates of the projects that use it.
KCOV_IMAGE=${KCOV_IMAGE:-kcov/kcov@sha256:481289ae32e55e5b733019515acd10948a4f76dfed381765577db909664fc603}

# The tools this drives, named through the environment so a test can hand it doubles.
: "${KCOV_BIN:=kcov}"
: "${DOCKER_BIN:=docker}"
: "${APT_GET_BIN:=apt-get}"

self="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/$(basename "${BASH_SOURCE[0]}")"

die() {
  echo "run-kcov: $*" >&2
  exit 2
}

# Prints the bash major version the local kcov traces scripts with, or nothing if the probe fails.
local_kcov_bash() {
  local dir
  dir="$(mktemp -d)"
  # shellcheck disable=SC2016  # the probe expands BASH_VERSINFO when kcov runs it, not here
  printf '#!/usr/bin/env bash\nprintf "%%s" "${BASH_VERSINFO[0]}"\n' > "$dir/probe.sh"
  chmod +x "$dir/probe.sh"
  "$KCOV_BIN" --include-path="$dir/probe.sh" "$dir/out" "$dir/probe.sh" 2>/dev/null || true
  rm -rf "$dir"
}

# Succeeds when the local toolchain can run this suite; otherwise prints why not and fails.
local_toolchain_usable() {
  local tool version
  if [ -n "${KCOV_FORCE_DOCKER:-}" ]; then
    echo "KCOV_FORCE_DOCKER is set"
    return 1
  fi
  if [ "$KCOV_LOCAL" = false ]; then
    echo "the suite sets local = false"
    return 1
  fi
  for tool in "$KCOV_BIN" ${KCOV_REQUIRES//,/ }; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "$tool is not installed locally"
      return 1
    fi
  done
  if [ -n "$KCOV_MIN_BASH" ]; then
    version="$(local_kcov_bash)"
    if ! [[ $version =~ ^[0-9]+$ ]] || (( version < KCOV_MIN_BASH )); then
      echo "the local kcov traces with bash ${version:-?}, and this suite needs $KCOV_MIN_BASH or newer" \
        "(stock kcov on macOS uses /bin/bash 3.2)"
      return 1
    fi
  fi
}

# Merges the per-invocation reports into kcov-merged/ when the run did not write one.
ensure_merged() {
  local dir merged reports=()
  [ -f "$KCOV_OUT/kcov-merged/coverage.json" ] && return 0
  for dir in "$KCOV_OUT"/*/; do
    dir="${dir%/}"
    [ -f "$dir/coverage.json" ] && reports+=("$dir")
  done
  [ ${#reports[@]} -gt 0 ] || return 0
  merged="$(mktemp -d)"
  "$KCOV_BIN" --merge "$merged" "${reports[@]}" >/dev/null
  rm -rf "$KCOV_OUT/kcov-merged"
  cp -R "$merged/kcov-merged" "$KCOV_OUT/kcov-merged"
  rm -rf "$merged"
}

# Runs the command into a fresh output directory and merges what it wrote. Returns the command's status.
run_suite() {
  local status=0
  rm -rf "$KCOV_OUT"
  mkdir -p "$KCOV_OUT"
  if [ -n "${JUNIT_DIR:-}" ]; then
    mkdir -p "$JUNIT_DIR"
  fi
  COVERAGE_DIR="$PWD/$KCOV_OUT" bash -c "$KCOV_COMMAND" || status=$?
  ensure_merged
  return "$status"
}

config=coverage.toml
suite=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config) config="${2:?--config needs a path}"; shift 2 ;;
    --suite) suite="${2:?--suite needs a name}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

if [ -z "${KCOV_IN_CONTAINER:-}" ]; then
  report_py="$(dirname "$self")/coverage-report.py"
  [ -f "$report_py" ] || die "coverage-report.py not found beside $self"
  record="$(python3 "$report_py" --config "$config" --format kcov ${suite:+--suite "$suite"})" || exit 2
  IFS=$'\x1f' read -r KCOV_SUITE KCOV_OUT KCOV_COMMAND KCOV_PACKAGES KCOV_REQUIRES KCOV_MIN_BASH \
    KCOV_SETUP KCOV_LOCAL <<< "$record"
  export KCOV_SUITE KCOV_OUT KCOV_COMMAND KCOV_PACKAGES KCOV_REQUIRES KCOV_MIN_BASH KCOV_SETUP KCOV_LOCAL
fi

# Both are mounted into the container under /src, so only a path inside the project survives the trip.
for path in "$KCOV_OUT" "${JUNIT_DIR:-}"; do
  case "$path" in
    /* | ../* | .. ) die "paths must be relative to the project root, got '$path'" ;;
  esac
done

if [ -n "${KCOV_IN_CONTAINER:-}" ]; then
  status=0
  if [ -n "$KCOV_PACKAGES" ]; then
    "$APT_GET_BIN" update -qq >/dev/null
    # shellcheck disable=SC2086  # the package list is meant to split into arguments
    DEBIAN_FRONTEND=noninteractive "$APT_GET_BIN" install -y -qq ${KCOV_PACKAGES//,/ } >/dev/null
  fi
  if [ -n "$KCOV_SETUP" ]; then
    bash "$KCOV_SETUP"
  fi
  run_suite || status=$?
  # The container runs as root; leave what it wrote readable by the host user and later CI steps.
  chmod -R a+rX "$KCOV_OUT"
  if [ -n "${JUNIT_DIR:-}" ]; then
    chmod -R a+rX "$JUNIT_DIR"
  fi
  exit "$status"
fi

status=0
if reason="$(local_toolchain_usable)"; then
  echo "Running the $KCOV_SUITE suite under the local kcov …"
  run_suite || status=$?
else
  echo "Running the $KCOV_SUITE suite in $KCOV_IMAGE ($reason) …"
  "$DOCKER_BIN" run --rm -v "$PWD:/src" -w /src -v "$self:/opt/run-kcov.sh:ro" \
    -e KCOV_IN_CONTAINER=1 -e KCOV_SUITE -e KCOV_OUT -e KCOV_COMMAND -e KCOV_PACKAGES \
    -e KCOV_REQUIRES -e KCOV_MIN_BASH -e KCOV_SETUP -e "JUNIT_DIR=${JUNIT_DIR:-}" \
    --entrypoint bash "$KCOV_IMAGE" /opt/run-kcov.sh || status=$?
fi

if [ ! -f "$KCOV_OUT/kcov-merged/coverage.json" ]; then
  echo "run-kcov: no merged report in $KCOV_OUT/kcov-merged/" >&2
  exit 1
fi
echo "Coverage in $KCOV_OUT/kcov-merged/"
exit "$status"
