# coverage — report data

This branch holds the published coverage reports and the workflow that deploys them to
GitHub Pages. It is written by `bin/add-report.sh` from source projects, one commit per
published report, and served from `reports/`.

The tooling, and the documentation for publishing here, are on the default branch. The two are
kept apart so that a source project can fetch a few kilobytes of scripts without downloading
every report ever published.

The `index.html` pages are generated at deploy time and are not committed.
