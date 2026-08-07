#!/usr/bin/env bash
# Assemble a project's HTML coverage reports + a reports.json manifest into <out>, ready to publish
# via bin/add-report.sh. Shared by every project that publishes to this site: which suites exist and
# where their HTML lives is declared in the project's coverage.toml, so this needs no per-project
# variant.
#
# All of a project's suites go into ONE output directory, published under ONE commit SHA in a single
# add-report.sh call — add-report.sh clears its destination, so publishing suites separately would
# let the second wipe the first.
#
# Each suite's HTML is copied to <out>/<suite-key>/, because the key is the manifest `path` the
# generated site links to.
#
# Usage: collect-coverage.sh [output-dir] [config]   (defaults: coverage-upload, coverage.toml)
# Run from the project root, after the suites have produced their HTML reports.
set -euo pipefail

out="${1:-coverage-upload}"
config="${2:-coverage.toml}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
report="$here/coverage-report.py"

suites="$(python3 "$report" --config "$config" --format collect)"

rm -rf "$out"
mkdir -p "$out"

while IFS=$'\t' read -r key html require; do
  [ -n "$key" ] || continue
  if [ ! -d "$html" ]; then
    echo "collect-coverage: suite '$key' has no HTML report at $html" >&2
    exit 1
  fi
  mkdir -p "$out/$key"
  # Copy via tar rather than cp: cp's symlink handling differs between BSD and GNU and, in its
  # common `cp -r src dest` form, dereferences symlinked directories into real ones — which would
  # defeat the symlink stripping below and publish a duplicate tree per link. tar preserves them
  # identically on both platforms, so the stripping actually applies. Copying the contents (`.`)
  # rather than the directory lands the suite at <out>/<key>/ regardless of what `html` is named.
  ( cd "$html" && tar cf - . ) | ( cd "$out/$key" && tar xf - )

  # The site links to <key>/index.html; without it the commit page has a dead link.
  if [ ! -f "$out/$key/index.html" ]; then
    echo "collect-coverage: suite '$key' has no index.html — the site would link to nothing" >&2
    exit 1
  fi

  # Tool-specific files the report needs to render correctly (e.g. kcov's per-file pages reference
  # ../data/bcov.css, so dropping it silently costs the covered/uncovered line highlighting).
  if [ -n "$require" ]; then
    IFS=',' read -ra required <<< "$require"
    for file in "${required[@]}"; do
      if [ ! -f "$out/$key/$file" ]; then
        echo "collect-coverage: suite '$key' is missing required $file" >&2
        exit 1
      fi
    done
  fi
done <<< "$suites"

python3 "$report" --config "$config" --format reports > "$out/reports.json"

# Strip what a static site cannot serve and what would break the deploy for *every* project:
# GitHub's upload-pages-artifact cannot tar a dangling symlink, and coverage tools leave absolute
# symlinks into the directory they ran from (which dangle anywhere else) plus .so runtime helpers.
# One such file from any single project fails the shared site's deployment for all of them.
find "$out" -type l -delete
find "$out" -name '*.so' -delete

# Belt and braces: a future tool version could introduce something else unpublishable, and it must
# fail here rather than in the coverage repository, far from the code that produced it.
if find "$out" -type l | grep -q .; then
  echo "collect-coverage: refusing to publish symlinks:" >&2
  find "$out" -type l >&2
  exit 1
fi
if find "$out" -name '*.so' | grep -q .; then
  echo "collect-coverage: refusing to publish shared objects:" >&2
  find "$out" -name '*.so' >&2
  exit 1
fi

echo "Collected coverage upload in $out/ (suites: $(cut -f1 <<< "$suites" | paste -sd, -))"
