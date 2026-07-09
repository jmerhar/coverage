#!/usr/bin/env bash
# Publish one project's coverage report for one commit into this coverage repo, then push.
#
# Source repos call this from a checkout of the coverage repo in their CI. It is the only entry
# point a source project needs — the browsable site (indexes, cross-links) is rebuilt separately by
# this repo's own workflow (.github/workflows/publish.yml) whenever reports/ changes.
#
# Usage:
#   bin/add-report.sh --repo <coverage-checkout> --project P --sha SHA \
#       --message MSG --commit-url URL --report-dir DIR
#
# DIR must contain the report's static HTML (one subdirectory per report, each with an index.html)
# and a reports.json manifest (see bin/make-meta.py). Everything in DIR except reports.json is
# copied verbatim to reports/<project>/<sha>/.
set -euo pipefail

repo="" project="" sha="" message="" commit_url="" report_dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) repo="$2"; shift 2;;
    --project) project="$2"; shift 2;;
    --sha) sha="$2"; shift 2;;
    --message) message="$2"; shift 2;;
    --commit-url) commit_url="$2"; shift 2;;
    --report-dir) report_dir="$2"; shift 2;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
for v in repo project sha report_dir; do
  [ -n "${!v}" ] || { echo "missing --${v//_/-}" >&2; exit 2; }
done
[ -f "$report_dir/reports.json" ] || { echo "$report_dir/reports.json not found" >&2; exit 2; }

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="$repo/reports/$project/$sha"

rm -rf "$dest"
mkdir -p "$dest"
# Copy the report HTML verbatim, excluding the manifest (which becomes meta.json).
( cd "$report_dir" && tar cf - --exclude=reports.json . ) | ( cd "$dest" && tar xf - )
python3 "$here/make-meta.py" \
  --project "$project" --sha "$sha" --message "$message" --commit-url "$commit_url" \
  --reports "$report_dir/reports.json" > "$dest/meta.json"

cd "$repo"
git add -A "reports/$project/$sha"
if git diff --cached --quiet; then
  echo "No changes for $project @ ${sha:0:10}; nothing to push."
  exit 0
fi
git -c user.name="coverage-bot" -c user.email="coverage-bot@users.noreply.github.com" \
    commit -q -m "coverage: $project @ ${sha:0:10}"
git push -q
echo "Published $project @ ${sha:0:10} -> reports/$project/$sha/"
