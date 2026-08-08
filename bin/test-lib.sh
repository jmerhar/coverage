#!/usr/bin/env bash
# Assertions and reporting shared by this repository's shell test suites.
#
# Source it, run assertions, then call `test_summary` as the last statement so its exit status becomes
# the suite's. Setting $JUNIT_OUT additionally writes a JUnit report there, which is what Codecov's test
# analytics reads; without it the suites need nothing but bash.
#
#   source "$(dirname "${BASH_SOURCE[0]}")/test-lib.sh"
#   check "two plus two" 4 "$((2 + 2))"
#   test_summary

passed=0
failed=0
_junit_cases=""

# The suite name JUnit groups the cases under: the sourcing script, without directory or extension.
_junit_suite="$(basename "${BASH_SOURCE[1]:-shell}" .sh)"

# XML has no way to carry these literally inside an attribute, and an assertion name is free text.
_xml_escape() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' \
                         -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"
}

_junit_case() { # name, failure-message (empty when passing)
  [ -n "${JUNIT_OUT:-}" ] || return 0
  local name failure
  name="$(_xml_escape "$1")"
  if [ -n "${2:-}" ]; then
    failure="$(_xml_escape "$2")"
    _junit_cases+="    <testcase classname=\"$_junit_suite\" name=\"$name\">"
    _junit_cases+="<failure message=\"$failure\"/></testcase>"$'\n'
  else
    _junit_cases+="    <testcase classname=\"$_junit_suite\" name=\"$name\"/>"$'\n'
  fi
}

pass() { passed=$((passed + 1)); printf '  ok   %s\n' "$1"; _junit_case "$1"; }

fail() {
  failed=$((failed + 1))
  printf '  FAIL %s\n     %s\n' "$1" "${2:-}"
  _junit_case "$1" "${2:-assertion failed}"
}

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

# Print the tally, write the JUnit report if asked, and return the suite's exit status.
test_summary() {
  printf '\n%s passed, %s failed\n' "$passed" "$failed"
  if [ -n "${JUNIT_OUT:-}" ]; then
    mkdir -p "$(dirname "$JUNIT_OUT")"
    {
      printf '<?xml version="1.0" encoding="UTF-8"?>\n'
      printf '<testsuites>\n  <testsuite name="%s" tests="%s" failures="%s">\n' \
        "$_junit_suite" "$((passed + failed))" "$failed"
      printf '%s' "$_junit_cases"
      printf '  </testsuite>\n</testsuites>\n'
    } > "$JUNIT_OUT"
  fi
  [ "$failed" -eq 0 ]
}
