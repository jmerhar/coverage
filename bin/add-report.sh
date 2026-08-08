#!/usr/bin/env bash
# Publish one project's coverage report for one commit into the coverage site, then push.
#
# Source repos call this from their CI. It is the only entry point a source project needs — the
# browsable site (indexes, cross-links) is rebuilt separately by this repo's own workflow
# (.github/workflows/publish.yml) whenever the report branch changes.
#
# Reports live on their own branch, not on the default branch, so that the tooling here stays small
# enough to fetch cheaply: a source repo pulls a few kilobytes of scripts instead of the whole
# accumulated report archive. This script clones that branch itself — shallow, blobless and sparse,
# so the clone costs almost nothing regardless of how large the archive has grown — which means a
# caller needs no checkout of this repository and never has to know where the reports are kept.
#
# Usage:
#   add-report.sh --project P --sha SHA --message MSG --commit-url URL --report-dir DIR
#                 [--token TOKEN] [--branch BRANCH] [--data-repo OWNER/NAME|URL]
#
# The token needs Contents: write on the report repository. It is taken from --token, else
# $COVERAGE_PAGES_TOKEN, else $GITHUB_TOKEN. --data-repo also accepts a full remote URL or a local
# path, which needs no token — useful for a self-hosted forge, or for exercising this script against
# a throwaway repository.
#
# DIR must contain the report's static HTML (one subdirectory per report, each with an index.html)
# and a reports.json manifest (see bin/make-meta.py). Everything in DIR except reports.json is
# copied verbatim to reports/<project>/<sha>/. bin/collect-coverage.sh assembles such a directory.
set -euo pipefail

# The repository and branch holding the published reports. The site is deployed from here.
DATA_REPO="jmerhar/coverage"
DATA_BRANCH="reports"

# Concurrent publishes from different source repos race for the branch tip. A rejected push is
# expected rather than exceptional, so retry from a fresh clone: each attempt only adds files under
# its own reports/<project>/<sha>/ path, so it can never clobber a report that won the race.
MAX_ATTEMPTS=3

repo="" project="" sha="" message="" commit_url="" report_dir="" token=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project) project="$2"; shift 2;;
    --sha) sha="$2"; shift 2;;
    --message) message="$2"; shift 2;;
    --commit-url) commit_url="$2"; shift 2;;
    --report-dir) report_dir="$2"; shift 2;;
    --token) token="$2"; shift 2;;
    --branch) DATA_BRANCH="$2"; shift 2;;
    --data-repo) DATA_REPO="$2"; shift 2;;
    # Accepted so that a caller passing a checkout of this repository still works; the report branch
    # is cloned directly, so no such checkout is needed.
    --repo) repo="$2"; shift 2;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
: "${repo:=}"
for v in project sha report_dir; do
  [ -n "${!v}" ] || { echo "missing --${v//_/-}" >&2; exit 2; }
done
[ -f "$report_dir/reports.json" ] || { echo "$report_dir/reports.json not found" >&2; exit 2; }

# An owner/name pair is resolved against github.com and needs a token; anything else is already a
# remote git can reach on its own.
if [[ "$DATA_REPO" == */* && "$DATA_REPO" != *://* && ! -e "$DATA_REPO" ]]; then
  token="${token:-${COVERAGE_PAGES_TOKEN:-${GITHUB_TOKEN:-}}}"
  if [ -z "$token" ]; then
    echo "add-report: no token (pass --token, or set COVERAGE_PAGES_TOKEN or GITHUB_TOKEN)" >&2
    exit 2
  fi
  remote="https://x-access-token:${token}@github.com/${DATA_REPO}.git"
else
  remote="$DATA_REPO"
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
report_dir="$(cd "$report_dir" && pwd)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Publish once: clone the report branch, add this commit's report, push. Returns 0 on success, 3 when
# there is nothing to publish, and non-zero otherwise (a losing race, or a real failure).
publish() {
  local checkout="$work/repo"
  rm -rf "$checkout"

  # --filter=blob:none --depth=1 fetches neither history nor file contents, and --sparse leaves the
  # working tree at the root, so none of the existing reports are transferred or written to disk.
  git clone --quiet --depth=1 --filter=blob:none --sparse \
    --branch "$DATA_BRANCH" "$remote" "$checkout"

  # Widen the sparse checkout to just this report's own directory. It does not exist upstream, so
  # nothing is downloaded; it only makes the path writable, since git refuses to stage files outside
  # the sparse definition.
  local dest="reports/$project/$sha"
  git -C "$checkout" sparse-checkout add "$dest"

  rm -rf "$checkout/${dest:?}"
  mkdir -p "$checkout/$dest"
  # Copy the report HTML verbatim, excluding the manifest (which becomes meta.json).
  ( cd "$report_dir" && tar cf - --exclude=reports.json . ) | ( cd "$checkout/$dest" && tar xf - )
  python3 "$here/make-meta.py" \
    --project "$project" --sha "$sha" --message "$message" --commit-url "$commit_url" \
    --reports "$report_dir/reports.json" > "$checkout/$dest/meta.json"

  # --force so nothing assembled can be dropped by an ignore rule: a coverage tool that writes a
  # .gitignore into its HTML output (coverage.py writes one containing `*`) would otherwise publish an
  # empty directory, and the failure is invisible here — the push succeeds, carrying only meta.json.
  git -C "$checkout" add --force -A "$dest"
  if git -C "$checkout" diff --cached --quiet; then
    return 3
  fi
  # gpgsign off explicitly: this is a machine-made commit in a throwaway clone, and a developer whose
  # global config signs every commit would otherwise have this fail for want of a key.
  git -C "$checkout" \
    -c user.name="coverage-bot" -c user.email="coverage-bot@users.noreply.github.com" \
    -c commit.gpgsign=false \
    commit --quiet -m "coverage: $project @ ${sha:0:10}"
  git -C "$checkout" push --quiet origin "HEAD:$DATA_BRANCH"
}

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  set +e
  publish
  status=$?
  set -e
  case "$status" in
    0)
      echo "Published $project @ ${sha:0:10} -> reports/$project/$sha/"
      exit 0;;
    3)
      echo "No changes for $project @ ${sha:0:10}; nothing to push."
      exit 0;;
    *)
      if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
        echo "add-report: publish attempt $attempt failed; retrying from a fresh clone" >&2
        sleep $((attempt * 3))
      fi;;
  esac
done

echo "add-report: failed to publish $project @ ${sha:0:10} after $MAX_ATTEMPTS attempts" >&2
exit 1
