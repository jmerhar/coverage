#!/usr/bin/env bash
# Tests for bin/collect-coverage.sh (no network, no dependencies beyond git-less coreutils).
#
# This script decides what actually reaches the site, and it can fail silently in two ways: a copy that
# dereferences a coverage tool's symlinks republishes a duplicate tree per link, and a report whose
# entry point is not where the site looks leaves a dead link on the commit page. Both are asserted
# here, since neither shows up as a failing build.
#
# Run: bin/test-collect-coverage.sh
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
collect="$here/collect-coverage.sh"

# Invoke the script under test. $SHELL_RUNNER lets a coverage run wrap this — kcov must be handed the
# script itself, not `bash script`, or it instruments the bash binary and reports nothing at all.
# shellcheck disable=SC2086  # SHELL_RUNNER is a command with arguments, deliberately split
run_collect() { ${SHELL_RUNNER:-} "$collect" "$@"; }
passed=0 failed=0

pass() { passed=$((passed + 1)); printf '  ok   %s\n' "$1"; }
fail() { failed=$((failed + 1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

check() { # name, expected, actual
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "expected [$2], got [$3]"; fi
}
check_file() { # name, path
  if [ -f "$2" ]; then pass "$1"; else fail "$1" "missing file: $2"; fi
}
check_no_file() { # name, path
  if [ ! -e "$2" ]; then pass "$1"; else fail "$1" "should not exist: $2"; fi
}
check_contains() { # name, needle, file
  if grep -qF -- "$2" "$3" 2>/dev/null; then pass "$1"; else fail "$1" "[$2] not in $3"; fi
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work" || exit 1

# A minimal kcov-shaped report: a JSON summary the engine can parse, plus an HTML tree.
fixture() { # dir
  mkdir -p "$1/data/js" "$1/kcov-merged/data"
  printf '{"covered_lines": 9, "total_lines": 10}\n' > "$1/kcov-merged/coverage.json"
  echo "<html>merged</html>" > "$1/kcov-merged/index.html"
  echo "<html>root</html>" > "$1/index.html"
  echo "css" > "$1/data/bcov.css"
  echo "js" > "$1/data/js/kcov.js"
}

config() { # file, extra suite keys
  cat > "$1" <<EOF
[suites.scripts]
label = "Shell"
format = "kcov"
report = "cov/kcov-merged/coverage.json"
html = "cov"
$2
EOF
}

echo "== a kcov suite publishes its report directory and the assets it resolves"
fixture cov
config c1.toml ""
run_collect up1 c1.toml >/dev/null 2>&1; rc=$?
check "exits 0" 0 "$rc"
check_file "merged report published" up1/scripts/kcov-merged/index.html
check_file "the data/ its pages resolve as ../data/bcov.css" up1/scripts/data/bcov.css
check_contains "the suite root redirects to it" 'url=kcov-merged/index.html' up1/scripts/index.html
# kcov's own top-level page aggregates the per-invocation reports, so it must not be the entry point.
if grep -qF 'root' up1/scripts/index.html; then
  fail "kcov's own top-level page is not the entry point" "index.html is the tool's own page"
else
  pass "kcov's own top-level page is not the entry point"
fi
check_file "manifest written" up1/reports.json
check_contains "manifest names the suite" '"path": "scripts"' up1/reports.json

echo "== a self-contained report is published whole, with its own index as the entry point"
mkdir -p istan/lcov-report
printf '{"total":{"lines":{"covered":9,"total":10},"branches":{"covered":0,"total":0}}}\n' \
  > istan/coverage-summary.json
echo "<html>istanbul</html>" > istan/index.html
echo "<html>detail</html>" > istan/lcov-report/index.html
cat > c2.toml <<'EOF'
[suites.app]
label = "App"
format = "istanbul"
report = "istan/coverage-summary.json"
html = "istan"
EOF
run_collect up2 c2.toml >/dev/null 2>&1
check "exits 0" 0 $?
check_contains "the tool's own index is the entry point" 'istanbul' up2/app/index.html
check_file "the rest of the tree comes along" up2/app/lcov-report/index.html

echo "== a symlinked directory is not dereferenced into a duplicate tree"
rm -rf cov3 && fixture cov3
ln -s "$work/cov3/kcov-merged" cov3/alias
sed 's#html = "cov"#html = "cov3"#; s#cov/kcov#cov3/kcov#' c1.toml > c3.toml
run_collect up3 c3.toml >/dev/null 2>&1
check_no_file "the symlink itself is stripped" up3/scripts/alias
check_no_file "the link target is not copied through it" up3/scripts/alias/index.html
# The fixture has two of its own: the tool's root report and the merged one. Dereferencing the link
# would add a third — a whole duplicate tree crediting a slice of the hits.
check "no duplicate tree published" 2 "$(find up3/scripts -name 'index.html' | wc -l | tr -d ' ')"

echo "== runtime helpers are stripped"
rm -rf cov4 && fixture cov4
echo "binary" > cov4/libkcov.so
sed 's#html = "cov"#html = "cov4"#; s#cov/kcov#cov4/kcov#' c1.toml > c4.toml
run_collect up4 c4.toml >/dev/null 2>&1
check_no_file "shared object stripped" up4/scripts/libkcov.so

echo "== a tool's own .gitignore is stripped"
# coverage.py writes one containing `*` into its HTML output. Publishing is a `git add`, so leaving it
# in place drops the whole report and the commit page links to nothing.
rm -rf cov13 && fixture cov13
printf '# Created by coverage.py\n*\n' > cov13/.gitignore
sed 's#html = "cov"#html = "cov13"#; s#cov/kcov#cov13/kcov#' c1.toml > c13.toml
run_collect up13 c13.toml >/dev/null 2>&1
check_no_file "the .gitignore is not published" up13/scripts/.gitignore
check_file "the report itself still is" up13/scripts/index.html

echo "== the assets a kcov report resolves must survive the copy"
# Its per-file pages reference ../data/bcov.css; without it the line highlighting silently vanishes.
rm -rf cov5 && fixture cov5 && rm -rf cov5/data
sed 's#html = "cov"#html = "cov5"#; s#cov/kcov#cov5/kcov#' c1.toml > c5.toml
run_collect up5 c5.toml >/dev/null 2>&1
check "a kcov report without its data/ fails" 1 $?

echo "== failures the site would otherwise show as a dead link"
rm -rf cov7 && fixture cov7 && rm -f cov7/kcov-merged/index.html
sed 's#html = "cov"#html = "cov7"#; s#cov/kcov#cov7/kcov#' c1.toml > c7.toml
run_collect up7 c7.toml >/dev/null 2>&1
check "a kcov report directory with no index.html fails" 1 $?

rm -rf cov8 && mkdir -p cov8/kcov-merged
printf '{"covered_lines": 1, "total_lines": 1}\n' > cov8/kcov-merged/coverage.json
sed 's#html = "cov"#html = "cov8"#; s#cov/kcov#cov8/kcov#' c1.toml > c8.toml
run_collect up8 c8.toml >/dev/null 2>&1
check "a report with no index.html fails" 1 $?

sed 's#html = "cov"#html = "absent-dir"#' c1.toml > c9.toml
run_collect up9 c9.toml >/dev/null 2>&1
check "a missing html directory fails" 1 $?

# The derived report directory comes from `report`; if kcov never wrote it, fail rather than publish
# an output root full of per-invocation reports.
sed 's#html = "cov"#html = "cov"#; s#cov/kcov-merged#cov/absent-dir#' c1.toml > c10.toml
run_collect up10 c10.toml >/dev/null 2>&1
check "a report directory kcov never wrote fails" 1 $?

echo "== the output directory is rebuilt, not merged into"
config c11.toml ""
run_collect up11 c11.toml >/dev/null 2>&1
echo stale > up11/scripts/stale.html
run_collect up11 c11.toml >/dev/null 2>&1
check_no_file "a previous run's file is gone" up11/scripts/stale.html

echo "== two suites land in their own directories"
rm -rf covA covB && fixture covA && fixture covB
cat > c12.toml <<'EOF'
[suites.one]
label = "One"
format = "kcov"
report = "covA/kcov-merged/coverage.json"
html = "covA"

[suites.two]
label = "Two"
format = "kcov"
report = "covB/kcov-merged/coverage.json"
html = "covB"
EOF
run_collect up12 c12.toml >/dev/null 2>&1
check_file "first suite" up12/one/index.html
check_file "second suite" up12/two/index.html

printf '\n%s passed, %s failed\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
