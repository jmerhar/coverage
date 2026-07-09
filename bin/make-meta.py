#!/usr/bin/env python3
"""Build a coverage ``meta.json`` for one commit of one project (source-agnostic).

``meta.json`` is the contract between a source project and this coverage site. It carries just
enough metadata for the site generator to build the indexes and cross-links, without knowing
anything about the coverage tool that produced the report.

Usage::

    make-meta.py --project P --sha SHA --message MSG --commit-url URL \\
                 --reports reports.json [--date ISO8601] > meta.json

``reports.json`` is a JSON array describing each published report, e.g.::

    [{"name": "shared", "path": "shared", "metrics": {"line": "99.6%", "branch": "88.8%"}}, ...]

    - name:    display label
    - path:    subdirectory (relative to the commit dir) holding that report's index.html
    - metrics: free-form label -> value map, rendered as-is. Any keys work, so different tools and
               languages can report whatever metrics they have.
"""
import argparse
import json
import sys
from datetime import datetime, timezone


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--message", default="")
    ap.add_argument("--commit-url", default="")
    ap.add_argument("--reports", required=True, help="path to a JSON array of reports")
    ap.add_argument("--date", default=None, help="ISO-8601 commit timestamp (defaults to now, UTC)")
    args = ap.parse_args()

    with open(args.reports) as f:
        reports = json.load(f)
    if not isinstance(reports, list):
        sys.exit("--reports must contain a JSON array")

    meta = {
        "project": args.project,
        "sha": args.sha,
        "short_sha": args.sha[:10],
        "committed_at": args.date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "message": args.message,
        "commit_url": args.commit_url,
        "reports": reports,
    }
    json.dump(meta, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
