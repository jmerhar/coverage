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
import re
import sys
from datetime import datetime, timezone

ROOT = sys.argv[1] if len(sys.argv) > 1 else "reports"

STYLE = (
    "<style>"
    "body{font-family:system-ui,-apple-system,sans-serif;max-width:860px;margin:2.5rem auto;"
    "padding:0 1rem;color:#191c20}"
    "h1{font-size:1.5rem}h1 small{font-weight:normal}"
    "table{border-collapse:collapse;width:100%;margin:1rem 0}"
    "th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #e2e4ea;vertical-align:top}"
    "th{font-size:.8rem;text-transform:uppercase;letter-spacing:.03em;color:#57606a}"
    "a{color:#4A90D9;text-decoration:none}a:hover{text-decoration:underline}"
    "code{background:#f0f2f5;padding:.1rem .4rem;border-radius:5px;font-size:.9em}"
    ".muted{color:#666}nav{font-size:.9rem;margin-bottom:1rem}"
    ".nowrap{white-space:nowrap}"
    "td.msg{width:100%}"                       # message column absorbs the slack; the rest stay put
    ".metric{display:inline-block;white-space:nowrap;background:#f0f2f5;border-radius:6px;"
    "padding:.1rem .5rem;margin:.1rem .25rem .1rem 0;font-size:.85em}"
    ".metric .k{color:#57606a}.metric b{font-weight:600}"
    ".good{color:#1a7f37}.mid{color:#9a6700}.low{color:#cf222e}"
    "</style>"
)

# Timestamps are emitted in UTC (see ts_span) with the raw ISO in data-utc. This rewrites each to
# the visitor's local time (with its zone abbreviation) and moves the UTC value into the tooltip,
# clearly labelled. Without JS, the UTC text remains visible and labelled.
SCRIPT = """<script>
(function () {
  var opts = {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'};
  document.querySelectorAll('.ts').forEach(function (el) {
    var d = new Date(el.getAttribute('data-utc'));
    if (isNaN(d.getTime())) return;
    var local = d.toLocaleString('sv-SE', opts);            // ISO-like "2026-07-09 13:24"
    var tz = new Intl.DateTimeFormat(undefined, {timeZoneName:'short'})
      .formatToParts(d).find(function (p) { return p.type === 'timeZoneName'; });
    el.textContent = tz ? local + ' ' + tz.value : local;
    el.title = d.toLocaleString('sv-SE', Object.assign({timeZone:'UTC'}, opts)) + ' UTC';
  });
})();
</script>"""

_PCT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")


def esc(s):
    return html.escape(str(s))


def page(title, body):
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title>{STYLE}{body}{SCRIPT}"
    )


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def fmt_date(iso):
    """ISO-8601 -> 'YYYY-MM-DD HH:MM' (UTC). Falls back to the raw string if unparseable."""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d&nbsp;%H:%M")
    except (ValueError, TypeError):
        return esc(iso)


def ts_span(iso):
    """A timestamp shown as UTC (labelled) by default; JS rewrites it to local time on load."""
    return f"<span class=ts data-utc='{esc(iso)}'>{fmt_date(iso)}&nbsp;UTC</span>"


def date_cell(iso):
    return f"<td class='nowrap muted'>{ts_span(iso)}</td>"


def _pct_class(value):
    m = _PCT.match(str(value))
    if not m:
        return ""
    n = float(m.group(1))
    return "good" if n >= 80 else "mid" if n >= 50 else "low"


def metric_pills(metrics):
    """Render a metrics map as pills; percentages get a subtle good/mid/low colour."""
    if not metrics:
        return "<span class=muted>—</span>"
    pills = []
    for k, v in metrics.items():
        cls = _pct_class(v)
        val = f"<b class={cls}>{esc(v)}</b>" if cls else f"<b>{esc(v)}</b>"
        pills.append(f"<span class=metric><span class=k>{esc(k)}</span> {val}</span>")
    return "".join(pills)


def short(commit):
    return commit.get("short_sha") or commit["sha"][:10]


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


def build_root(root, projects):
    rows = "".join(
        f"<tr><td class=nowrap><a href='{esc(p)}/'>{esc(p)}</a></td>"
        f"<td class=nowrap>{len(cs)}</td>{date_cell(cs[0].get('committed_at', ''))}</tr>"
        for p, cs in sorted(projects.items())
    ) or "<tr><td colspan=3 class=muted>No projects yet.</td></tr>"
    write(os.path.join(root, "index.html"), page(
        "Coverage reports",
        "<h1>Coverage reports</h1>"
        "<p class=muted>Per-commit code-coverage reports, one section per project.</p>"
        "<table><tr><th class=nowrap>Project</th><th class=nowrap>Commits</th>"
        "<th class=nowrap>Latest</th></tr>" + rows + "</table>"))


def build_project(root, project, commits):
    rows = ""
    for c in commits:
        primary = c["reports"][0].get("metrics", {}) if c.get("reports") else {}
        rows += (
            f"<tr><td class=nowrap><a href='{esc(c['sha'])}/'><code>{esc(short(c))}</code></a></td>"
            f"<td class=msg>{esc(c.get('message', ''))}</td>"
            f"{date_cell(c.get('committed_at', ''))}"
            f"<td class=nowrap>{metric_pills(primary)}</td></tr>"
        )
    write(os.path.join(root, project, "index.html"), page(
        f"{project} — coverage",
        "<nav><a href='../'>← all projects</a></nav>"
        f"<h1>{esc(project)}</h1>"
        f"<p class=muted>{len(commits)} commit(s), newest first. "
        "The coverage column summarises the first report.</p>"
        "<table><tr><th class=nowrap>Commit</th><th>Message</th>"
        "<th class=nowrap>Date</th><th class=nowrap>Coverage</th></tr>" + rows + "</table>"))


def build_commit(root, project, commits, i):
    c = commits[i]
    reports = c.get("reports", [])
    # A report with a `path` links to its HTML; one without (e.g. a computed "total" summary row) is
    # rendered as plain text — it contributes metrics only.
    report_rows = "".join(
        (
            f"<tr><td class=nowrap><a href='{esc(r['path'])}/index.html'>{esc(r['name'])}</a></td>"
            if r.get("path")
            else f"<tr><td class=nowrap>{esc(r['name'])}</td>"
        )
        + f"<td>{metric_pills(r.get('metrics', {}))}</td></tr>"
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
        f"<p class=muted>{esc(c.get('message', ''))}<br>{ts_span(c.get('committed_at', ''))}</p>"
        "<table><tr><th class=nowrap>Report</th><th class=nowrap>Coverage</th></tr>"
        + report_rows + "</table>"))


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
