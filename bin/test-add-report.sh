#!/usr/bin/env bash
# Tests for bin/add-report.sh, against a throwaway local repository standing in for the site.
#
# This is the one script that writes to the published branch, from six repositories' CI. It has to add
# a report without disturbing any other, and it has to refuse rather than publish something the site
# cannot use — a half-formed upload is only noticed as a dead link days later.
#
# Run: bin/test-add-report.sh   (needs git; no network)
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
add="$here/add-report.sh"
passed=0 failed=0
SHA_A="1111111111111111111111111111111111111111"
SHA_B="2222222222222222222222222222222222222222"

pass() { passed=$((passed + 1)); printf '  ok   %s\n' "$1"; }
fail() { failed=$((failed + 1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }
check() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "expected [$2], got [$3]"; fi; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work" || exit 1

# A bare repository with a populated `reports` branch, as the site's data branch looks.
git init -q --bare remote.git
git init -q seed && (
  cd seed && git checkout -q --orphan reports
  mkdir -p reports/existing/abcdef1234
  echo '{"project": "existing"}' > reports/existing/abcdef1234/meta.json
  echo "<html>kept</html>" > reports/existing/abcdef1234/index.html
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm seed
  git push -q ../remote.git reports:reports
)
REMOTE="file://$work/remote.git"

# An upload directory as collect-coverage.sh produces one.
upload() { # dir
  mkdir -p "$1/app"
  echo "<html>report</html>" > "$1/app/index.html"
  printf '[{"name":"total","metrics":{"line":"90.0%%"}},{"name":"App","path":"app","metrics":{"line":"90.0%%"}}]\n' \
    > "$1/reports.json"
}
upload up

publish() { # sha, extra args...
  local sha="$1"; shift
  bash "$add" --project demo --sha "$sha" --message "a commit" \
    --commit-url "https://example.com/c/1" --report-dir up \
    --data-repo "$REMOTE" --branch reports "$@" 2>&1 | grep -v '^warning:'
}

# Read the pushed branch without keeping a working tree around.
at() { git --git-dir=remote.git show "reports:$1" 2>/dev/null; }
listing() { git --git-dir=remote.git ls-tree -r --name-only reports; }

echo "== publishing a report"
publish "$SHA_A" >/dev/null; rc=$?
check "exits 0" 0 "$rc"
check "report HTML is published" "<html>report</html>" "$(at "reports/demo/$SHA_A/app/index.html")"
check "meta.json is generated" "demo" "$(at "reports/demo/$SHA_A/meta.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["project"])')"
check "the manifest itself is not published" "" "$(at "reports/demo/$SHA_A/reports.json")"
check "an unrelated project is untouched" "<html>kept</html>" "$(at "reports/existing/abcdef1234/index.html")"

echo "== a second project's report does not disturb the first"
publish "$SHA_B" >/dev/null
check "first report still there" "<html>report</html>" "$(at "reports/demo/$SHA_A/app/index.html")"
check "second report added" "<html>report</html>" "$(at "reports/demo/$SHA_B/app/index.html")"

echo "== republishing the same commit replaces its directory"
rm -rf up2 && mkdir -p up2/app && echo "<html>new</html>" > up2/app/index.html
echo "<html>stale</html>" > up2/app/stale.html
cp up/reports.json up2/reports.json
bash "$add" --project demo --sha "$SHA_A" --message m --commit-url u --report-dir up2 \
  --data-repo "$REMOTE" --branch reports >/dev/null 2>&1
check "content is replaced" "<html>new</html>" "$(at "reports/demo/$SHA_A/app/index.html")"
rm -rf up3 && mkdir -p up3/app && echo "<html>third</html>" > up3/app/index.html
cp up/reports.json up3/reports.json
bash "$add" --project demo --sha "$SHA_A" --message m --commit-url u --report-dir up3 \
  --data-repo "$REMOTE" --branch reports >/dev/null 2>&1
check "a file from the previous upload is gone" "" "$(at "reports/demo/$SHA_A/app/stale.html")"

echo "== an ignore rule cannot silently empty the published report"
# Publishing is a `git add`, and coverage.py writes a .gitignore containing `*` into its HTML output.
# Without --force the push succeeds carrying only meta.json, which reads as a successful publish.
rm -rf up4 && mkdir -p up4/app && echo "<html>kept</html>" > up4/app/index.html
printf '# Created by coverage.py\n*\n' > up4/app/.gitignore
cp up/reports.json up4/reports.json
SHA_C="3333333333333333333333333333333333333333"
bash "$add" --project demo --sha "$SHA_C" --message m --commit-url u --report-dir up4 \
  --data-repo "$REMOTE" --branch reports >/dev/null 2>&1
check "the report is published despite the ignore rule" "<html>kept</html>" \
  "$(at "reports/demo/$SHA_C/app/index.html")"

echo "== the published layout is the one the site expects"
check "no stray paths outside the commit directory" 0 \
  "$(listing | grep -cv -E '^reports/(demo|existing)/[0-9a-f]+/')"

echo "== refusals"
mkdir -p empty
bash "$add" --project demo --sha "$SHA_A" --report-dir empty --data-repo "$REMOTE" >/dev/null 2>&1
check "a report dir without reports.json is refused" 2 $?
bash "$add" --sha "$SHA_A" --report-dir up --data-repo "$REMOTE" >/dev/null 2>&1
check "a missing --project is refused" 2 $?
bash "$add" --project demo --report-dir up --data-repo "$REMOTE" >/dev/null 2>&1
check "a missing --sha is refused" 2 $?
bash "$add" --project demo --sha "$SHA_A" --data-repo "$REMOTE" >/dev/null 2>&1
check "a missing --report-dir is refused" 2 $?
bash "$add" --project demo --sha "$SHA_A" --report-dir up --nonsense x >/dev/null 2>&1
check "an unknown argument is refused" 2 $?
(unset COVERAGE_PAGES_TOKEN GITHUB_TOKEN
 bash "$add" --project demo --sha "$SHA_A" --report-dir up --data-repo owner/name >/dev/null 2>&1
 exit $?)
check "a GitHub target without a token is refused" 2 $?

echo "== a caller may still pass a checkout, which is ignored"
publish "$SHA_B" --repo /nonexistent-checkout >/dev/null
check "publishes anyway" "<html>report</html>" "$(at "reports/demo/$SHA_B/app/index.html")"

printf '\n%s passed, %s failed\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
