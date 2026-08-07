# coverage

Central, multi-project host for browsable **code-coverage reports**, published to GitHub Pages:

**→ https://jmerhar.github.io/coverage/**

Any project (in any language, using any coverage tool) can publish here. Onboarding is a
`coverage.toml` and three `uses:` steps — the summary table, the coverage gate and the publishing are
all shared code living in this repo, so a source project needs no coverage scripts of its own.

Coverage is kept **per commit** and **forever**: every commit that publishes gets its own permanent
report, so you can always open the exact report for any historical commit.

## Branches

| Branch | Holds |
|---|---|
| `main` | the tooling: `bin/`, the composite actions, this README |
| `reports` | the published reports, and the workflow that deploys them |

They are separate because a source project fetches the tooling on every CI run, and the report
archive grows without bound — a few kilobytes of scripts should not cost a download of every report
ever published.

## Layout

Reports live under `reports/` on the `reports` branch, namespaced by project and commit SHA. The
served site has the same shape (`reports/` is the site root):

```
reports/
  index.html                      ← generated: list of projects
  <project>/
    index.html                    ← generated: that project's commits, newest first
    <full-commit-sha>/
      index.html                  ← generated: per-commit landing (links each report + back-links)
      meta.json                   ← pushed by the source project (the contract)
      <report>/…                  ← pushed by the source project (raw HTML, e.g. shared/, app/)
```

URLs:

- Root (all projects): `https://jmerhar.github.io/coverage/`
- A project (commit list): `…/coverage/<project>/`
- A specific commit: `…/coverage/<project>/<sha>/`
- A report within a commit: `…/coverage/<project>/<sha>/<report>/`

## How it works

1. A **source project's CI** runs the shared composite actions. They read the project's
   `coverage.toml`, render the summary, enforce the gate, assemble the HTML via
   [`bin/collect-coverage.sh`](bin/collect-coverage.sh), and publish via
   [`bin/add-report.sh`](bin/add-report.sh) — which pushes the report to the `reports` branch under
   `reports/<project>/<sha>/` together with a `meta.json` built by
   [`bin/make-meta.py`](bin/make-meta.py). It clones that branch itself, shallow and sparse, so
   publishing costs nothing regardless of how large the archive is.
2. That push triggers [`.github/workflows/publish.yml`](.github/workflows/publish.yml), which runs
   [`bin/build-site.py`](bin/build-site.py) to (re)generate all the `index.html` pages, then deploys
   `reports/` to GitHub Pages via the **GitHub Actions Pages** pipeline.

The generated `index.html` pages are **not committed** — they're rebuilt on every deploy from the
`meta.json` files, so the site is always consistent with whatever reports are present.

### The `meta.json` contract

This is all the site needs to know about a report — no coverage-tool specifics:

```json
{
  "project": "sweetspot-android",
  "sha": "4187057…",
  "short_sha": "4187057abc",
  "committed_at": "2026-07-09T09:08:00Z",
  "message": "commit subject",
  "commit_url": "https://github.com/jmerhar/sweetspot-android/commit/4187057…",
  "reports": [
    { "name": "total",  "metrics": { "line": "97.4%", "branch": "90.1%" } },
    { "name": "shared", "path": "shared", "metrics": { "line": "99.6%", "branch": "88.8%" } },
    { "name": "app",    "path": "app",    "metrics": { "line": "99.0%", "branch": "82.5%" } }
  ]
}
```

`metrics` is a free-form label→value map, rendered as-is — so different tools/languages can report
whatever numbers they have. `path` is **optional**: omit it for a metrics-only summary row (e.g. a
computed "total" across suites), which the site renders as plain text with no link. The project
index summarises each commit with its **first** report's metrics, so the "total" entry leads.

## Onboarding a new project

Two things: a token, and a `coverage.toml` plus three CI steps. No changes to *this* repo are
required — it discovers new projects automatically.

### 1. Token

Create a **fine-grained personal access token** with **Contents: Read and write** on
`jmerhar/coverage` (reuse the same token across projects). Add it to the source repo as an Actions
secret named `COVERAGE_PAGES_TOKEN`.

### 2. `coverage.toml` in the project root

Declare each test suite: its label, which tool wrote its report, where that report and its HTML are,
and where its gate sits.

```toml
heading = "Coverage"        # optional: the Markdown H2 above the table
column  = "Suite"           # optional: header of the table's first column
total   = true              # optional: emit the combined "total" row

[suites.backend]
label  = "Backend (Python)"     # row label, and the manifest `name`
format = "coveragepy"
report = "backend/coverage.json"    # the machine-readable summary
html   = "backend/htmlcov"          # the HTML directory to publish
gate   = 95.0                       # omit to make the suite informational

[suites.frontend]
label  = "Frontend (TypeScript)"
format = "istanbul"
report = "frontend/coverage/coverage-summary.json"
html   = "frontend/coverage"
gate   = 98.0
```

A suite's **key** (`backend`) is the subdirectory its HTML is published under, so it is also the
`path` the site links to. Suites keep their declared order in the table and the manifest.

Supported `format` values, and the report each one reads:

| `format` | Tool | `report` should point at | Metrics |
|---|---|---|---|
| `istanbul` | vitest / jest / nyc | `coverage-summary.json` (`json-summary` reporter) | line, branch |
| `coveragepy` | coverage.py / pytest-cov | `coverage.json` (`--cov-report=json`) | line, branch |
| `kcov` | kcov (shell) | `kcov-merged/coverage.json` | line |
| `kover` | Kover / JaCoCo | `reportDebug.xml` (the XML report) | line, branch, instruction |
| `clover` | PHPUnit / PCOV | `clover.xml` | line, methods, branch |

A metric whose denominator the tool reports as zero is dropped, so each project's table has exactly
the columns its tooling can fill — no configuration needed. The gate always checks **line** coverage.
Other keys are optional: `require = ["data/bcov.css"]` asserts files the HTML must ship with.

### 3. Three CI steps

```yaml
jobs:
  test:
    permissions:
      contents: read
      statuses: write        # only needed for the commit-status link
    steps:
      # … check out, install, and run your tests with coverage first …

      - uses: jmerhar/coverage/.github/actions/summary@v1

      # Any coverage uploads (Codecov and the like) belong here — before the gate, so their data
      # still lands when the gate fails.

      - uses: jmerhar/coverage/.github/actions/gate@v1

      - uses: jmerhar/coverage/.github/actions/publish@v1
        if: success() && github.event_name == 'push' && github.ref == 'refs/heads/main'
        with:
          token: ${{ secrets.COVERAGE_PAGES_TOKEN }}
```

That's it — the next push shows up at `https://jmerhar.github.io/coverage/<project>/`.

Notes:

- **Python 3.11+** must be on the runner (`coverage.toml` is parsed with `tomllib`). The runner
  images provide it; add `actions/setup-python` if your job pins an older one.
- `publish` **skips rather than fails** when `token` is empty, so the workflow stays green before the
  secret exists.
- Useful inputs: `config` (default `coverage.toml`), `working-directory`, `project` (defaults to the
  repository name), `description` and `status-context` for the commit status, and
  `commit-status: false` to skip it. See
  [the action definitions](.github/actions) for the full list.
- Pin to `@v1`. Referencing `@main` works but takes changes unreviewed.

`idealista` is the reference implementation for two suites across separate CI jobs;
`sweetspot-android` for several modules in one build.

## Local development

Check the coverage-report engine against a project without CI:

```bash
python3 bin/coverage-report.py --config /path/to/project/coverage.toml --format md
python3 bin/coverage-report.py --config /path/to/project/coverage.toml --gate
```

Run the tooling's own tests, and regenerate the site from a checkout of the `reports` branch:

```bash
python3 bin/test-coverage-report.py
python3 bin/build-site.py <reports-checkout>/reports    # then open its reports/index.html
```

`bin/add-report.sh` takes `--data-repo` as a path or URL, so a publish can be exercised end to end
against a throwaway repository instead of the real site.

## Notes & maintenance

- **Pages is deployed via GitHub Actions** (`build_type: workflow`), not from a branch. Don't switch
  it to branch serving: the index pages are generated at deploy time rather than committed, and
  generating them means scanning every project's `meta.json`, which would push that work into each
  source project's CI.
- **`publish.yml` runs from the `reports` branch**, since a push resolves workflows from the branch
  it targets. The copy on `main` is the original — after editing it there, sync it to `reports`.
- **Retention is unlimited** — every commit's report is kept, so the `reports` branch grows over
  time. If it ever gets heavy, prune old `reports/<project>/<sha>/` directories (the site regenerates
  from whatever remains) or add a cap to `bin/build-site.py`.
- Adding or removing reports never requires touching the generator — it scans `reports/` on each run.
- The tooling is used by every project on the site, so `bin/` changes are covered by
  [`bin/test-coverage-report.py`](bin/test-coverage-report.py), run by
  [`.github/workflows/test.yml`](.github/workflows/test.yml).
