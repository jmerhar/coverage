#!/usr/bin/env bash
# Tests for bin/run-kcov.sh, against stand-ins for kcov, docker and apt-get (no network, no container).
#
# The runner decides where a project's shell is measured and what reaches the coverage gate, so the
# choice between the local toolchain and the container, the merge it performs, and the exit status it
# reports are asserted here. The stand-ins record how they were called, so a test can check what the
# runner asked of each tool without that tool doing the work.
#
# Run: bin/test-run-kcov.sh
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runner="$here/run-kcov.sh"

# Invoke the script under test. $SHELL_RUNNER lets a coverage run wrap this — kcov must be handed the
# script itself, not `bash script`, or it instruments the bash binary and reports nothing at all.
# shellcheck disable=SC2086  # SHELL_RUNNER is a command with arguments, deliberately split
run_kcov() { ${SHELL_RUNNER:-} "$runner" "$@"; }
# shellcheck source=bin/test-lib.sh
source "$here/test-lib.sh"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
calls="$work/calls"
mkdir -p "$work/stubs"

# kcov: `--merge OUT DIR…` writes OUT/kcov-merged; anything else is the bash probe, answered with
# $STUB_KCOV_BASH so a test chooses which bash the "local kcov" traces with.
cat > "$work/stubs/kcov" <<'EOF'
#!/usr/bin/env bash
echo "kcov $*" >> "$CALLS"
if [ "$1" = --merge ]; then
  mkdir -p "$2/kcov-merged"
  echo '{"covered_lines": 7, "total_lines": 8}' > "$2/kcov-merged/coverage.json"
  exit 0
fi
printf '%s' "${STUB_KCOV_BASH-5}"
EOF
# docker: records its arguments; with STUB_DOCKER_REPORT it leaves the merged report a container run
# would, and it exits with $STUB_DOCKER_EXIT.
cat > "$work/stubs/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$CALLS"
if [ -n "${STUB_DOCKER_REPORT:-}" ]; then
  mkdir -p "$STUB_DOCKER_REPORT/kcov-merged"
  echo '{}' > "$STUB_DOCKER_REPORT/kcov-merged/coverage.json"
fi
exit "${STUB_DOCKER_EXIT:-0}"
EOF
cat > "$work/stubs/apt-get" <<'EOF'
#!/usr/bin/env bash
echo "apt-get $*" >> "$CALLS"
EOF
chmod +x "$work/stubs/"*
export CALLS="$calls"
export KCOV_BIN="$work/stubs/kcov" DOCKER_BIN="$work/stubs/docker" APT_GET_BIN="$work/stubs/apt-get"
unset KCOV_FORCE_DOCKER KCOV_IN_CONTAINER JUNIT_DIR

# A project whose suite command records what it was given and writes per-invocation reports.
project() { # dir, extra suite keys
  rm -rf "$1"
  mkdir -p "$1/bin"
  cat > "$1/bin/suite.sh" <<'EOF'
#!/usr/bin/env bash
echo "suite COVERAGE_DIR=$COVERAGE_DIR JUNIT_DIR=${JUNIT_DIR:-}" >> "$CALLS"
for ((n = 1; n <= ${STUB_REPORTS:-2}; n++)); do
  mkdir -p "$COVERAGE_DIR/s.sh.$n"
  echo '{"covered_lines": 1, "total_lines": 2}' > "$COVERAGE_DIR/s.sh.$n/coverage.json"
done
if [ -n "${STUB_PRIVATE:-}" ]; then
  echo private > "$COVERAGE_DIR/private.txt"
  chmod 600 "$COVERAGE_DIR/private.txt"
fi
if [ -n "${STUB_SUITE_MERGES:-}" ]; then
  mkdir -p "$COVERAGE_DIR/kcov-merged"
  echo '{}' > "$COVERAGE_DIR/kcov-merged/coverage.json"
fi
exit "${STUB_SUITE_EXIT:-0}"
EOF
  cat > "$1/coverage.toml" <<EOF
[suites.shell]
label = "Shell"
format = "kcov"
report = "cov/kcov-merged/coverage.json"
html = "cov"
command = "bash bin/suite.sh"
$2
EOF
}

# Runs the runner in a project directory, leaving its output in $out and its status in $rc.
in_project() { # dir, args…
  local dir="$1"; shift
  : > "$calls"
  out="$( (cd "$dir" && run_kcov "$@") 2>&1 )"; rc=$?
}

echo "== a usable local toolchain runs the suite locally and merges its reports"
project "$work/p1" ""
in_project "$work/p1"
check "exits 0" 0 "$rc"
check_contains "says it ran locally" "under the local kcov" <(echo "$out")
check_contains "the command gets an absolute COVERAGE_DIR" "COVERAGE_DIR=$work/p1/cov " "$calls"
check_contains "merges the per-invocation reports" "kcov --merge" "$calls"
check_file "the merged report exists" "$work/p1/cov/kcov-merged/coverage.json"
check "docker is not used" 0 "$(grep -c '^docker' "$calls")"

echo "== a run that merged its own reports is left alone"
STUB_SUITE_MERGES=1 in_project "$work/p1"
check "exits 0" 0 "$rc"
check "no merge" 0 "$(grep -c -- '--merge' "$calls")"

echo "== a stale report from an earlier run is removed first"
project "$work/p2" ""
mkdir -p "$work/p2/cov/kcov-merged" && echo '{}' > "$work/p2/cov/kcov-merged/coverage.json"
STUB_REPORTS=0 in_project "$work/p2"
check "exits 1 when this run produced nothing" 1 "$rc"
check_contains "says no merged report" "no merged report in cov/kcov-merged/" <(echo "$out")

echo "== a failing suite keeps its exit status and still leaves a merged report"
project "$work/p3" ""
STUB_SUITE_EXIT=3 in_project "$work/p3"
check "exits with the suite's status" 3 "$rc"
check_file "the merged report exists" "$work/p3/cov/kcov-merged/coverage.json"

echo "== JUNIT_DIR reaches the command and is created"
project "$work/p4" ""
JUNIT_DIR=junit in_project "$work/p4"
check "exits 0" 0 "$rc"
check_contains "the command sees JUNIT_DIR" "JUNIT_DIR=junit" "$calls"
if [ -d "$work/p4/junit" ]; then pass "junit/ is created"; else fail "junit/ is created" "missing"; fi

echo "== paths outside the project are refused"
project "$work/p5" ""
JUNIT_DIR=/tmp/junit in_project "$work/p5"
check "an absolute JUNIT_DIR exits 2" 2 "$rc"
sed -i.bak 's|^html = "cov"|html = "../cov"|' "$work/p5/coverage.toml"
in_project "$work/p5"
check "an html outside the project exits 2" 2 "$rc"

echo "== KCOV_FORCE_DOCKER uses the container"
project "$work/p6" 'packages = ["bats", "git"]'
KCOV_FORCE_DOCKER=1 STUB_DOCKER_REPORT="$work/p6/cov" in_project "$work/p6"
check "exits 0" 0 "$rc"
check_contains "gives the reason" "KCOV_FORCE_DOCKER is set" <(echo "$out")
docker_call="$(grep '^docker' "$calls")"
check_contains "runs the pinned image" "kcov/kcov@sha256:" <(echo "$docker_call")
check_contains "mounts the project at /src" "-v $work/p6:/src -w /src" <(echo "$docker_call")
check_contains "mounts the runner" "$runner:/opt/run-kcov.sh:ro" <(echo "$docker_call")
check_contains "runs the runner in container mode" "-e KCOV_IN_CONTAINER=1" <(echo "$docker_call")
check "the suite does not run on the host" 0 "$(grep -c '^suite' "$calls")"

echo "== the container's exit status is reported"
STUB_DOCKER_EXIT=4 KCOV_FORCE_DOCKER=1 STUB_DOCKER_REPORT="$work/p6/cov" in_project "$work/p6"
check "exits with the container's status" 4 "$rc"

echo "== a missing kcov falls back to the container"
project "$work/p7" ""
KCOV_BIN="$work/stubs/absent" STUB_DOCKER_REPORT="$work/p7/cov" in_project "$work/p7"
check "exits 0" 0 "$rc"
check_contains "names the missing tool" "absent is not installed locally" <(echo "$out")

echo "== a missing required command falls back to the container"
project "$work/p8" 'requires = ["no-such-command-here"]'
STUB_DOCKER_REPORT="$work/p8/cov" in_project "$work/p8"
check "exits 0" 0 "$rc"
check_contains "names the missing command" "no-such-command-here is not installed locally" <(echo "$out")
check "uses docker" 1 "$(grep -c '^docker' "$calls")"

echo "== min_bash rejects a local kcov that traces with an older bash"
project "$work/p9" 'min_bash = 4'
STUB_KCOV_BASH=3 STUB_DOCKER_REPORT="$work/p9/cov" in_project "$work/p9"
check "exits 0" 0 "$rc"
check_contains "explains the bash it found" "traces with bash 3, and this suite needs 4" <(echo "$out")
check "uses docker" 1 "$(grep -c '^docker' "$calls")"
STUB_KCOV_BASH="" STUB_DOCKER_REPORT="$work/p9/cov" in_project "$work/p9"
check_contains "an unreadable probe counts as too old" "traces with bash ?" <(echo "$out")
STUB_KCOV_BASH=5 in_project "$work/p9"
check_contains "a new enough bash runs locally" "under the local kcov" <(echo "$out")

echo "== local = false always measures in the container"
project "$work/p12" 'local = false'
STUB_DOCKER_REPORT="$work/p12/cov" in_project "$work/p12"
check "exits 0" 0 "$rc"
check_contains "gives the reason" "the suite sets local = false" <(echo "$out")
check "uses docker" 1 "$(grep -c '^docker' "$calls")"
check "the suite does not run on the host" 0 "$(grep -c '^suite' "$calls")"

echo "== container mode installs, sets up, runs and leaves its output readable"
project "$work/p10" ""
# shellcheck disable=SC2016  # $CALLS expands when the setup script runs
echo 'echo "setup ran" >> "$CALLS"' > "$work/p10/bin/setup.sh"
: > "$calls"
out="$(cd "$work/p10" && KCOV_IN_CONTAINER=1 KCOV_SUITE=shell KCOV_OUT=cov \
  KCOV_COMMAND="bash bin/suite.sh" KCOV_PACKAGES="bats,git" KCOV_REQUIRES="" KCOV_MIN_BASH="" \
  KCOV_SETUP="bin/setup.sh" JUNIT_DIR=junit STUB_PRIVATE=1 run_kcov 2>&1)"; rc=$?
check "exits 0" 0 "$rc"
check_contains "installs the packages" "apt-get install -y -qq bats git" "$calls"
check_contains "runs the setup script" "setup ran" "$calls"
check_contains "runs the suite" "suite COVERAGE_DIR=$work/p10/cov" "$calls"
check_file "the merged report exists" "$work/p10/cov/kcov-merged/coverage.json"
check "the suite comes after setup" "setup ran" "$(grep -v '^apt-get' "$calls" | head -1)"
check "what the suite wrote is left readable by others" "4" \
  "$(python3 -c 'import os,sys; print(os.stat(sys.argv[1]).st_mode & 0o4)' "$work/p10/cov/private.txt")"

echo "== container mode without packages or setup installs nothing"
: > "$calls"
(cd "$work/p10" && KCOV_IN_CONTAINER=1 KCOV_SUITE=shell KCOV_OUT=cov KCOV_COMMAND="bash bin/suite.sh" \
  KCOV_PACKAGES="" KCOV_REQUIRES="" KCOV_MIN_BASH="" KCOV_SETUP="" STUB_SUITE_EXIT=5 run_kcov) >/dev/null 2>&1
rc=$?
check "exits with the suite's status" 5 "$rc"
check "apt-get is not called" 0 "$(grep -c '^apt-get' "$calls")"

echo "== --suite chooses between several runnable suites"
project "$work/p11" ""
cat >> "$work/p11/coverage.toml" <<'EOF'

[suites.other]
label = "Other"
format = "kcov"
report = "cov2/kcov-merged/coverage.json"
html = "cov2"
command = "bash bin/suite.sh"
EOF
in_project "$work/p11"
check "without --suite it exits 2" 2 "$rc"
in_project "$work/p11" --suite other
check "with --suite it exits 0" 0 "$rc"
check_contains "and writes that suite's report" "COVERAGE_DIR=$work/p11/cov2 " "$calls"
in_project "$work/p11" --config coverage.toml --suite shell
check "--config is accepted" 0 "$rc"

echo "== argument and setup errors exit 2"
in_project "$work/p11" --bogus
check "an unknown argument" 2 "$rc"
mkdir -p "$work/lonely"
cp "$runner" "$work/lonely/run-kcov.sh"
out="$(cd "$work/p1" && "$work/lonely/run-kcov.sh" 2>&1)"; rc=$?
check "no coverage-report.py beside the runner" 2 "$rc"
check_contains "says what is missing" "coverage-report.py not found" <(echo "$out")

test_summary
