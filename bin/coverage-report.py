#!/usr/bin/env python3
"""Summarise or gate a project's test coverage for CI, for any coverage tool.

One implementation shared by every project that publishes to this coverage site. What differs
between projects — which suites exist, which tool wrote each report, and where the gate sits — is
declared in a ``coverage.toml`` at the project root. The percentage maths, the combined total, the
rendering and the gate logic live here, so a project needs no coverage code of its own.

Usage (run from the project root, after the suites have produced their reports)::

    coverage-report.py [--config coverage.toml] --format md
    coverage-report.py [--config coverage.toml] --format reports
    coverage-report.py [--config coverage.toml] --gate

  --format md         GitHub-flavored Markdown table for the Actions run summary
                      ($GITHUB_STEP_SUMMARY): one row per suite, plus a combined total.
  --format reports    The JSON "reports" array consumed by bin/make-meta.py: a leading combined
                      "total" entry (no ``path``, so the site renders it as the headline) followed
                      by one linkable entry per suite.
  --format collect    One record per suite for collect-coverage.sh, so that the config is parsed in
                      exactly one place: ``key``, ``html``, ``require,…``, ``include,…``, ``index``
                      joined by US (0x1f). See COLLECT_SEPARATOR for why not a tab.
  --format codecov    One record per suite for the codecov action: ``key`` (used as the upload flag)
                      and the file Codecov parses, likewise US-joined.
  --gate              Check each suite's LINE coverage against its ``gate`` and exit non-zero if any
                      suite is below its bound or has no report.

The ``coverage.toml`` schema::

    heading = "Coverage"        # optional: the Markdown H2 above the table
    column  = "Suite"           # optional: header of the table's first column
    total   = true              # optional: emit the combined "total" row

    [suites.frontend]
    label  = "Frontend (TypeScript)"                    # row label, and manifest ``name``
    format = "istanbul"                                 # which parser reads ``report``
    report = "frontend/coverage/coverage-summary.json"  # the machine-readable summary
    html   = "frontend/coverage"                        # HTML directory (collect-coverage.sh)
    gate   = 98.0                                       # omit to make the suite informational

Every suite takes the same five keys whatever the tool. What each tool's output has to be assembled
into for publishing is derived from ``format`` — see _publishing — rather than restated per project.

A suite's key is the subdirectory its HTML is published under, so it is also the manifest ``path``
the site links to. Suites keep their declared order in the table and the manifest.
"""
import argparse
import json
import os
import re
import sys
import tomllib
from xml.etree import ElementTree

# Canonical metric keys, in the order they are rendered. A parser only reports the metrics its tool
# actually measures, and any metric whose denominator is zero is dropped, so each project's table
# has exactly the columns its tooling can fill: line-only for shell, line+branch for JS/Python,
# line+methods for PCOV, and so on. No configuration is needed to select them.
METRICS = ("line", "branch", "instruction", "methods")

# Column headings for the Markdown table.
HEADINGS = {"line": "Line", "branch": "Branch", "instruction": "Instruction", "methods": "Methods"}

# A gate passes when coverage rounds up to its bound: reports carry one decimal, so a suite sitting
# at 97.96% displays as "98.0%" and must not fail a "≥ 98" gate for a difference it cannot show.
ROUNDING_TOLERANCE = 0.05

# Field separator for --format collect. US (0x1f) rather than a tab because bash's `read` treats tab
# as whitespace and so collapses runs of them: a suite with an empty field would silently shift every
# later field along, publishing the wrong thing. Non-whitespace separators preserve empty fields.
COLLECT_SEPARATOR = "\x1f"


def _parse_istanbul(path):
    """Counts from an istanbul/vitest ``json-summary`` report (``coverage-summary.json``)."""
    with open(path) as f:
        total = json.load(f).get("total", {})
    lines, branches = total.get("lines", {}), total.get("branches", {})
    return {
        "line": (lines.get("covered", 0), lines.get("total", 0)),
        "branch": (branches.get("covered", 0), branches.get("total", 0)),
    }


def _parse_coveragepy(path):
    """Counts from a coverage.py JSON report (``--cov-report=json``)."""
    with open(path) as f:
        totals = json.load(f).get("totals", {})
    return {
        "line": (totals.get("covered_lines", 0), totals.get("num_statements", 0)),
        "branch": (totals.get("covered_branches", 0), totals.get("num_branches", 0)),
    }


def _parse_kcov(path):
    """Counts from a kcov JSON report.

    kcov measures lines only — there is no branch coverage for shell. The top-level totals are
    integers, unlike the per-file entries, which are strings.
    """
    with open(path) as f:
        data = json.load(f)
    return {"line": (int(data.get("covered_lines", 0)), int(data.get("total_lines", 0)))}


def _parse_kover(path):
    """Counts from a Kover/JaCoCo XML report's project-level ``<counter>`` elements.

    Only the counters the site renders are mapped; JaCoCo also emits METHOD, CLASS and COMPLEXITY.
    """
    counters = {c.get("type"): c for c in ElementTree.parse(path).getroot().findall("counter")}

    def counts(kind):
        c = counters.get(kind)
        if c is None:
            return (0, 0)
        covered, missed = int(c.get("covered", 0)), int(c.get("missed", 0))
        return (covered, covered + missed)

    return {"line": counts("LINE"), "branch": counts("BRANCH"), "instruction": counts("INSTRUCTION")}


def _parse_clover(path):
    """Counts from a Clover XML report's project-level ``<metrics>`` element.

    Line coverage comes from ``statements``, which is what PHP's line-coverage drivers record.
    ``conditionals`` is read as branch coverage but is zero under PCOV, which cannot measure it —
    zero-denominator metrics are dropped, so such a project simply shows no Branch column.
    """
    project = ElementTree.parse(path).getroot().find("project")
    metrics = project.find("metrics") if project is not None else None
    if metrics is None:
        raise ElementTree.ParseError(f"{path} has no project-level <metrics>")

    def counts(covered_attr, total_attr):
        return (int(metrics.get(covered_attr, 0)), int(metrics.get(total_attr, 0)))

    return {
        "line": counts("coveredstatements", "statements"),
        "branch": counts("coveredconditionals", "conditionals"),
        "methods": counts("coveredmethods", "methods"),
    }


PARSERS = {
    "istanbul": _parse_istanbul,
    "coveragepy": _parse_coveragepy,
    "kcov": _parse_kcov,
    "kover": _parse_kover,
    "clover": _parse_clover,
}


def load_config(path):
    """Read and validate a ``coverage.toml``, returning it as a dict.

    Exits with a message rather than raising, so a malformed config fails CI legibly.
    """
    try:
        with open(path, "rb") as f:
            config = tomllib.load(f)
    except FileNotFoundError:
        sys.exit(f"coverage-report: no config at {path}")
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"coverage-report: {path} is not valid TOML: {e}")

    suites = config.get("suites")
    if not suites:
        sys.exit(f"coverage-report: {path} declares no [suites.<name>]")
    for key, spec in suites.items():
        # A key becomes both a directory under the upload root and a URL path segment on the site, so
        # anything that could escape either — a slash, a parent reference — has to be refused here
        # rather than produce a report published outside its own directory.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", key):
            sys.exit(
                f"coverage-report: suite name {key!r} must be a single path segment of letters, "
                "digits, dots, underscores or dashes"
            )
        for field in ("label", "format", "report"):
            if field not in spec:
                sys.exit(f"coverage-report: suite '{key}' is missing '{field}'")
        if spec["format"] not in PARSERS:
            sys.exit(
                f"coverage-report: suite '{key}' has unknown format '{spec['format']}' "
                f"(known: {', '.join(sorted(PARSERS))})"
            )
        # The publishing table joins its fields with COLLECT_SEPARATOR and its lists with commas, and
        # the paths published out of `html` are derived from these two, so either character in them
        # would silently split one path into two.
        for field in ("html", "report"):
            value = spec.get(field, "")
            if any(c in value for c in (",", COLLECT_SEPARATOR, "\t", "\n")):
                sys.exit(f"coverage-report: suite '{key}' has a separator character in {field}: {value!r}")
    return config


def counts(config):
    """Map every suite key to its ``{metric: (covered, total)}``, or to None if it has no report.

    Metrics whose denominator is zero are dropped: a tool that cannot measure something reports it
    as 0/0, and a column of "n/a" is noise rather than information.
    """
    result = {}
    for key, spec in config["suites"].items():
        try:
            parsed = PARSERS[spec["format"]](spec["report"])
        except (FileNotFoundError, json.JSONDecodeError, ElementTree.ParseError, KeyError, ValueError):
            result[key] = None
            continue
        result[key] = {m: c for m, c in parsed.items() if c[1]}
    return result


def _pct(covered, total):
    """A '12.3%' string for covered/total, or 'n/a' when the denominator is zero."""
    return f"{covered / total * 100:.1f}%" if total else "n/a"


def percentages(config):
    """Map every suite that has a report to its ``{metric: "12.3%"}``, preserving declared order."""
    return {
        key: {m: _pct(*c) for m, c in suite.items()}
        for key, suite in counts(config).items()
        if suite is not None
    }


def total_metrics(config):
    """Combined coverage across the suites that have a report, line-count-weighted.

    Sums covered and total across suites then divides, so a large low-coverage suite drags the
    total down in proportion to its size — unlike averaging the per-suite percentages. A metric is
    only aggregated when *every* reporting suite provides it, so the total can never be one suite's
    number wearing a "Total" label.
    """
    reporting = [suite for suite in counts(config).values() if suite]
    metrics = {}
    for metric in METRICS:
        if not reporting or any(metric not in suite for suite in reporting):
            continue
        covered = sum(suite[metric][0] for suite in reporting)
        total = sum(suite[metric][1] for suite in reporting)
        if total:
            metrics[metric] = _pct(covered, total)
    return metrics


def _columns(rows, total):
    """The metrics to render, in canonical order: those any suite or the total reports."""
    present = {m for stats in rows.values() for m in stats} | set(total)
    return [m for m in METRICS if m in present]


def render_markdown(config):
    """A Markdown table with one row per reporting suite and a combined total row."""
    rows = percentages(config)
    total = total_metrics(config) if config.get("total", True) else {}
    columns = _columns(rows, total)

    heading = config.get("heading", "Coverage")
    header = [config.get("column", "Suite")] + [HEADINGS[m] for m in columns]
    lines = [f"## {heading}", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for key, stats in rows.items():
        cells = [config["suites"][key]["label"]] + [stats.get(m, "n/a") for m in columns]
        lines.append("| " + " | ".join(cells) + " |")
    if total:
        cells = ["**Total**"] + [f"**{total.get(m, 'n/a')}**" for m in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_reports(config):
    """The ``reports.json`` manifest for the site.

    A leading "total" entry (combined coverage, no ``path``) so the project index shows the overall
    number as its headline, then one linkable entry per suite. The site reads ``metrics`` as a
    free-form label→value map, so whatever the project's tools measure is what appears.
    """
    suites = [
        {"name": config["suites"][key]["label"], "path": key, "metrics": stats}
        for key, stats in percentages(config).items()
    ]
    total = total_metrics(config) if config.get("total", True) else {}
    reports = ([{"name": "total", "metrics": total}] if total else []) + suites
    return json.dumps(reports, indent=2)


def _publishing(key, spec):
    """What to publish out of a suite's ``html``: (subpaths, entry point, files that must survive).

    Derived from the format because it describes the coverage tool's output layout, not the project.
    An empty subpath list means publish the whole directory, and an empty entry point means the site's
    ``index.html`` is already at the top of it — true of every tool that writes one self-contained
    report.

    kcov does not: it writes the report the summaries read into its own subdirectory, beside a shared
    ``data/`` whose stylesheet the report's per-file pages resolve as ``../data/bcov.css``. Publishing
    the whole output root would also publish kcov's per-invocation reports, each covering only the runs
    that targeted one script, so each lists every file while crediting a slice of the hits. The
    subdirectory is taken from ``report`` rather than assumed to be ``kcov-merged``, which is the name
    only when more than one script was traced into the same directory.
    """
    if spec["format"] != "kcov":
        return [], "", []
    report_dir = os.path.relpath(os.path.dirname(spec["report"]), spec["html"])
    if report_dir == os.curdir or report_dir.split(os.sep)[0] == os.pardir:
        sys.exit(
            f"coverage-report: suite '{key}' expects its kcov report in a subdirectory of "
            f"'{spec['html']}', but 'report' resolves to '{report_dir}'"
        )
    return [report_dir, "data"], f"{report_dir}/index.html", ["data/bcov.css"]


# The file Codecov parses, per format. Kover and Clover already write a dialect it reads, so the report
# the summaries read is also the upload; the others write one beside that report under a fixed name.
CODECOV_FILES = {"istanbul": "lcov.info", "coveragepy": "coverage.xml", "kcov": "cobertura.xml"}


def render_codecov(config):
    """The suite → Codecov upload table: the flag to upload under, and the file to upload.

    Derived rather than configured, for the same reason as _publishing: which file Codecov wants is a
    property of the coverage tool. Each suite is uploaded under its own flag so the halves of a
    multi-suite project stay separable in Codecov's UI.

    A tool that writes its Codecov dialect only when asked (istanbul's ``lcov``, coverage.py's ``xml``)
    may not have produced the file; the action reports that rather than failing, since Codecov is
    informational here and the gate is the actual check.
    """
    lines = []
    for key, spec in config["suites"].items():
        fmt = spec["format"]
        path = spec["report"] if fmt not in CODECOV_FILES else os.path.join(
            os.path.dirname(spec["report"]), CODECOV_FILES[fmt])
        lines.append(COLLECT_SEPARATOR.join((key, path)))
    return "\n".join(lines)


def render_collect(config):
    """The suite → publishing table for collect-coverage.sh, one record per line.

    Publishing needs each suite's ``html`` directory plus what _publishing derives from its format,
    none of which the summaries use. Emitting it here keeps ``coverage.toml`` parsed in one language.
    Fields are joined by COLLECT_SEPARATOR and lists by commas, which is why load_config rejects both
    characters in these paths.
    """
    lines = []
    for key, spec in config["suites"].items():
        if "html" not in spec:
            sys.exit(f"coverage-report: suite '{key}' is missing 'html', needed to publish it")
        include, index, require = _publishing(key, spec)
        lines.append(COLLECT_SEPARATOR.join((
            key, spec["html"], ",".join(require), ",".join(include), index,
        )))
    return "\n".join(lines)


def line_percent(config, key):
    """A suite's LINE coverage as a float percent, or None if it has no report."""
    suite = counts(config)[key]
    if not suite or "line" not in suite:
        return None
    return suite["line"][0] / suite["line"][1] * 100


def run_gate(config):
    """Check every suite's LINE coverage against its ``gate``. Returns a process exit code.

    A suite with no ``gate`` is informational: its number is printed and never fails the build. A
    suite with no report always fails — a gate that silently passes when the report goes missing
    would be worse than no gate at all.
    """
    failures = []
    for key, spec in config["suites"].items():
        pct = line_percent(config, key)
        if pct is None:
            print(f"✗ {key}  no coverage report at {spec['report']}")
            failures.append(key)
            continue
        threshold = spec.get("gate")
        if threshold is None:
            print(f"• {key}  line {pct:.1f}%  (informational — no gate configured)")
            continue
        ok = pct + ROUNDING_TOLERANCE >= threshold
        print(f"{'✓' if ok else '✗'} {key}  line {pct:.1f}%  (gate ≥ {threshold:.0f}%)")
        if not ok:
            failures.append(key)

    if failures:
        print(f"\nCoverage gate FAILED for: {', '.join(failures)}")
        return 1
    print("\nCoverage gate passed.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Summarise or gate per-suite coverage.")
    ap.add_argument("--config", default="coverage.toml", help="path to coverage.toml")
    ap.add_argument("--format", choices=("md", "reports", "collect", "codecov"), default="md")
    ap.add_argument("--gate", action="store_true",
                    help="check LINE coverage against each suite's gate; exit non-zero if below")
    args = ap.parse_args()

    config = load_config(args.config)
    if args.gate:
        raise SystemExit(run_gate(config))
    renderers = {"md": render_markdown, "reports": render_reports,
                 "collect": render_collect, "codecov": render_codecov}
    print(renderers[args.format](config))


if __name__ == "__main__":
    main()
