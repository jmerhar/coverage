#!/usr/bin/env python3
"""Generate the browsable coverage site from the raw per-commit reports (source-agnostic).

Scans ``reports/<project>/<sha>/meta.json`` and writes:

  * ``reports/index.html``                  — list of projects
  * ``reports/<project>/index.html``         — that project's commits, newest first
  * ``reports/<project>/<sha>/index.html``   — per-commit landing (links each report + back-links)

plus ``reports/.nojekyll``. Nothing here is committed: the workflow runs this and deploys
``reports/`` to GitHub Pages. It is idempotent — only the generated ``index.html`` files (and
``.nojekyll``) are (over)written; the raw report directories and ``meta.json`` files are untouched.

Usage: ``build-site.py [reports-dir]``  (default: ``reports``)
"""
import html
import json
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "reports"

STYLE = (
    "<style>body{font-family:system-ui,-apple-system,sans-serif;max-width:820px;margin:2.5rem auto;"
    "padding:0 1rem;color:#191c20}h1{font-size:1.5rem}h1 small{font-weight:normal}"
    "table{border-collapse:collapse;width:100%;margin:1rem 0}"
    "th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #e2e4ea;vertical-align:top}"
    "a{color:#4A90D9;text-decoration:none}a:hover{text-decoration:underline}"
    "code{background:#f0f2f5;padding:.1rem .35rem;border-radius:4px;font-size:.9em}"
    ".muted{color:#666}nav{font-size:.9rem;margin-bottom:1rem}</style>"
)


def esc(s):
    return html.escape(str(s))


def page(title, body):
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title>{STYLE}{body}"
    )


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def load_projects(root):
    """Return {project: [meta, ...]} with each project's commits sorted newest-first."""
    projects = {}
    for project in sorted(os.listdir(root)):
        pdir = os.path.join(root, project)
        if not os.path.isdir(pdir):
            continue
        commits = []
        for sha in os.listdir(pdir):
            meta_path = os.path.join(pdir, sha, "meta.json")
            if os.path.isfile(meta_path):
                with open(meta_path) as f:
                    commits.append(json.load(f))
        if commits:
            commits.sort(key=lambda m: m.get("committed_at", ""), reverse=True)
            projects[project] = commits
    return projects


def metrics_str(metrics, bold=False):
    fmt = "{} <b>{}</b>" if bold else "{} {}"
    return " · ".join(fmt.format(esc(k), esc(v)) for k, v in metrics.items())


def short(commit):
    return commit.get("short_sha") or commit["sha"][:10]


def build_root(root, projects):
    rows = "".join(
        f"<tr><td><a href='{esc(p)}/'>{esc(p)}</a></td><td>{len(cs)}</td>"
        f"<td class=muted>{esc(cs[0].get('committed_at', ''))}</td></tr>"
        for p, cs in sorted(projects.items())
    ) or "<tr><td colspan=3 class=muted>No projects yet.</td></tr>"
    write(os.path.join(root, "index.html"), page(
        "Coverage reports",
        "<h1>Coverage reports</h1>"
        "<p class=muted>Per-commit code-coverage reports, one section per project.</p>"
        "<table><tr><th>Project</th><th>Commits</th><th>Latest</th></tr>" + rows + "</table>"))


def build_project(root, project, commits):
    rows = ""
    for c in commits:
        primary = c["reports"][0].get("metrics", {}) if c.get("reports") else {}
        rows += (
            f"<tr><td><a href='{esc(c['sha'])}/'><code>{esc(short(c))}</code></a></td>"
            f"<td>{esc(c.get('message', ''))}</td>"
            f"<td class=muted>{esc(c.get('committed_at', ''))}</td>"
            f"<td class=muted>{metrics_str(primary)}</td></tr>"
        )
    write(os.path.join(root, project, "index.html"), page(
        f"{project} — coverage",
        "<nav><a href='../'>← all projects</a></nav>"
        f"<h1>{esc(project)}</h1>"
        f"<p class=muted>{len(commits)} commit(s), newest first. "
        "The coverage column summarises the first report.</p>"
        "<table><tr><th>Commit</th><th>Message</th><th>Date</th><th>Coverage</th></tr>"
        + rows + "</table>"))


def build_commit(root, project, commits, i):
    c = commits[i]
    reports = c.get("reports", [])
    report_rows = "".join(
        f"<tr><td><a href='{esc(r['path'])}/index.html'>{esc(r['name'])}</a></td>"
        f"<td>{metrics_str(r.get('metrics', {}), bold=True)}</td></tr>"
        for r in reports
    ) or "<tr><td colspan=2 class=muted>No reports.</td></tr>"

    nav = ["<a href='../'>← " + esc(project) + "</a>"]
    if i > 0:  # newer commit exists (list is newest-first)
        nav.append(f"<a href='../{esc(commits[i - 1]['sha'])}/'>newer</a>")
    if i + 1 < len(commits):
        nav.append(f"<a href='../{esc(commits[i + 1]['sha'])}/'>older</a>")

    commit_ref = (
        f"<a href='{esc(c['commit_url'])}'>{esc(short(c))}</a>"
        if c.get("commit_url") else f"<code>{esc(short(c))}</code>"
    )
    write(os.path.join(root, project, c["sha"], "index.html"), page(
        f"{project} @ {short(c)}",
        f"<nav>{' · '.join(nav)}</nav>"
        f"<h1>{esc(project)} <small>@ {commit_ref}</small></h1>"
        f"<p class=muted>{esc(c.get('message', ''))}<br>{esc(c.get('committed_at', ''))}</p>"
        "<table><tr><th>Report</th><th>Coverage</th></tr>" + report_rows + "</table>"))


def main():
    open(os.path.join(ROOT, ".nojekyll"), "w").close()
    projects = load_projects(ROOT)
    build_root(ROOT, projects)
    for project, commits in projects.items():
        build_project(ROOT, project, commits)
        for i in range(len(commits)):
            build_commit(ROOT, project, commits, i)
    print(f"Generated site for {len(projects)} project(s): {', '.join(projects) or '(none)'}")


if __name__ == "__main__":
    main()
