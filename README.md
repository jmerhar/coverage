# coverage

Central, multi-project host for browsable **code-coverage reports**, published to GitHub Pages:

**→ https://jmerhar.github.io/coverage/**

Any project (in any language, using any coverage tool) can publish here. The repo is
**source-agnostic**: source projects push their raw HTML report plus a small `meta.json` manifest,
and this repo builds everything around it — the list of projects, each project's list of commits,
per-commit landing pages, and the cross-links — then deploys the site.

Coverage is kept **per commit** and **forever**: every commit that publishes gets its own permanent
report, so you can always open the exact report for any historical commit.

## Layout

Raw reports live under `reports/`, namespaced by project and commit SHA. The served site has the
same shape (`reports/` is the site root):

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

1. A **source project's CI** builds its coverage HTML, writes a `reports.json` manifest, checks out
   *this* repo, and runs [`bin/add-report.sh`](bin/add-report.sh) — which drops the files under
   `reports/<project>/<sha>/`, builds `meta.json` via [`bin/make-meta.py`](bin/make-meta.py), and
   commits + pushes.
2. The push to `reports/**` triggers [`.github/workflows/publish.yml`](.github/workflows/publish.yml),
   which runs [`bin/build-site.py`](bin/build-site.py) to (re)generate all the `index.html` pages,
   then deploys `reports/` to GitHub Pages via the **GitHub Actions Pages** pipeline.

The generated `index.html` pages are **not committed** — they're rebuilt on every deploy from the
`meta.json` files, so the site is always consistent with whatever reports are present.

### The `meta.json` contract

This is all this repo needs to know about a report — no coverage-tool specifics. Produced by
`bin/make-meta.py` from a project-supplied `reports.json`:

```json
{
  "project": "sweetspot-android",
  "sha": "4187057…",
  "short_sha": "4187057abc",
  "committed_at": "2026-07-09T09:08:00Z",
  "message": "commit subject",
  "commit_url": "https://github.com/jmerhar/sweetspot-android/commit/4187057…",
  "reports": [
    { "name": "shared", "path": "shared", "metrics": { "line": "99.6%", "branch": "88.8%" } },
    { "name": "app",    "path": "app",    "metrics": { "line": "15.7%", "branch": "6.8%" } }
  ]
}
```

`metrics` is a free-form label→value map, rendered as-is — so different tools/languages can report
whatever numbers they have.

## Onboarding a new project

You need three things: a token, a CI step that publishes, and the reports themselves. No changes to
*this* repo are required — it discovers new projects automatically from `reports/`.

### 1. Token

Create a **fine-grained personal access token** with **Contents: Read and write** on `jmerhar/coverage`
(reuse the same token across projects). Add it to the source repo as an Actions secret named
`COVERAGE_PAGES_TOKEN`.

### 2. Produce a report directory in the source CI

After your tests run, assemble a directory containing one subdirectory per report (each with its
own `index.html`) and a `reports.json` manifest describing them:

```
coverage-upload/
  reports.json          # [{ "name": "...", "path": "<subdir>", "metrics": { … } }, …]
  <subdir>/index.html   # the raw HTML report(s)
  …
```

`reports.json` is the only tool-specific part — build it however your coverage tool allows (parse a
Kover/JaCoCo/lcov/coverage.py report, etc.). Example:

```json
[
  { "name": "shared", "path": "shared", "metrics": { "line": "99.6%", "branch": "88.8%" } },
  { "name": "app",    "path": "app",    "metrics": { "line": "15.7%", "branch": "6.8%" } }
]
```

### 3. Publish from the source CI

Add these steps to the source project's workflow (guard on your default branch + token presence so
it's skipped, not failed, before setup):

```yaml
- name: Check out the coverage repo
  uses: actions/checkout@v4
  with:
    repository: jmerhar/coverage
    token: ${{ secrets.COVERAGE_PAGES_TOKEN }}
    path: coverage-repo

- name: Publish coverage report
  run: |
    coverage-repo/bin/add-report.sh \
      --repo coverage-repo \
      --project "${GITHUB_REPOSITORY##*/}" \
      --sha "$GITHUB_SHA" \
      --message "$(git -C "$GITHUB_WORKSPACE" log -1 --pretty=%s)" \
      --commit-url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/commit/$GITHUB_SHA" \
      --report-dir coverage-upload

# Optional: link the report from the commit's checks in the source repo.
- name: Link report from commit
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}   # needs: permissions: { statuses: write }
  run: |
    gh api --method POST "repos/$GITHUB_REPOSITORY/statuses/$GITHUB_SHA" \
      -f state=success -f context="coverage/report" \
      -f description="Coverage report" \
      -f target_url="https://jmerhar.github.io/coverage/${GITHUB_REPOSITORY##*/}/$GITHUB_SHA/"
```

That's it — the next push shows up at `https://jmerhar.github.io/coverage/<project>/`.
`sweetspot-android` is the reference implementation.

## Local development

Regenerate the site from the reports currently present:

```bash
python3 bin/build-site.py reports    # writes reports/index.html, reports/<project>/… , reports/.nojekyll
# then open reports/index.html
```

## Notes & maintenance

- **Pages is deployed via GitHub Actions** (`build_type: workflow`), not from a branch. Don't switch
  it back to branch-based serving — every project relies on the Actions deploy.
- **Retention is unlimited** — every commit's report is kept. The repo (and each deploy) therefore
  grows over time; if it ever gets heavy, prune old `reports/<project>/<sha>/` directories (the site
  regenerates from whatever remains) or add a cap to a future version of `build-site.py`.
- Adding/removing reports never requires touching the generator — it scans `reports/` on each run.
