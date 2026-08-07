#!/usr/bin/env python3
"""Unit tests for bin/coverage-report.py (stdlib unittest, no network).

This script is the coverage gate and the source of the published numbers for every project on the
site, so its parsing, percentage maths and threshold logic are worth locking down — a silent
regression here would mis-report or stop gating six repositories at once.

Each test writes fixture reports and a coverage.toml into a temp directory and exercises the real
code paths. Run: python3 bin/test-coverage-report.py
"""
import importlib.util
import json
import os
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "coverage_report", os.path.join(os.path.dirname(os.path.abspath(__file__)), "coverage-report.py"))
cr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cr)


def write(path, text):
    """Write `text` to `path`, creating parent directories as needed."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def istanbul(path, line=(90, 100), branch=(40, 50)):
    """Write an istanbul/vitest json-summary fixture."""
    write(path, json.dumps({"total": {
        "lines": {"covered": line[0], "total": line[1]},
        "branches": {"covered": branch[0], "total": branch[1]},
    }}))


def coveragepy(path, line=(90, 100), branch=(40, 50)):
    """Write a coverage.py JSON fixture."""
    write(path, json.dumps({"totals": {
        "covered_lines": line[0], "num_statements": line[1],
        "covered_branches": branch[0], "num_branches": branch[1],
    }}))


def kcov(path, line=(90, 100)):
    """Write a kcov JSON fixture (line coverage only, integer totals)."""
    write(path, json.dumps({"covered_lines": line[0], "total_lines": line[1]}))


def kover(path, line=(90, 10), branch=(40, 10), instruction=(980, 20)):
    """Write a Kover/JaCoCo XML fixture. Counters are (covered, missed), not (covered, total)."""
    counters = "".join(
        f'<counter type="{kind}" covered="{c}" missed="{m}"/>'
        for kind, (c, m) in (("LINE", line), ("BRANCH", branch), ("INSTRUCTION", instruction))
    )
    write(path, f"<report>{counters}</report>")


def clover(path, line=(90, 100), methods=(8, 10), conditionals=(0, 0)):
    """Write a Clover XML fixture."""
    write(path, (
        f'<coverage><project><metrics statements="{line[1]}" coveredstatements="{line[0]}" '
        f'methods="{methods[1]}" coveredmethods="{methods[0]}" '
        f'conditionals="{conditionals[1]}" coveredconditionals="{conditionals[0]}"/>'
        "</project></coverage>"
    ))


def config(suites, **top):
    """Build an in-memory config dict equivalent to a parsed coverage.toml."""
    return {**top, "suites": suites}


def suite(fmt, report, gate=None, label=None, html=None, require=None):
    """Build one [suites.<key>] entry."""
    spec = {"label": label or fmt, "format": fmt, "report": report}
    if gate is not None:
        spec["gate"] = gate
    if html is not None:
        spec["html"] = html
    if require is not None:
        spec["require"] = require
    return spec


class TempCwd(unittest.TestCase):
    """Base class that runs each test in a scratch directory, since report paths are relative."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()


class ParserTest(TempCwd):
    def test_istanbul(self):
        istanbul("c.json", line=(90, 100), branch=(40, 50))
        cfg = config({"s": suite("istanbul", "c.json")})
        self.assertEqual(cr.counts(cfg)["s"], {"line": (90, 100), "branch": (40, 50)})

    def test_coveragepy(self):
        coveragepy("c.json", line=(90, 100), branch=(40, 50))
        cfg = config({"s": suite("coveragepy", "c.json")})
        self.assertEqual(cr.counts(cfg)["s"], {"line": (90, 100), "branch": (40, 50)})

    def test_kcov_is_line_only(self):
        kcov("c.json", line=(108, 108))
        cfg = config({"s": suite("kcov", "c.json")})
        self.assertEqual(cr.counts(cfg)["s"], {"line": (108, 108)})

    def test_kover_converts_missed_to_total(self):
        kover("r.xml", line=(90, 10), branch=(40, 10), instruction=(980, 20))
        cfg = config({"s": suite("kover", "r.xml")})
        self.assertEqual(
            cr.counts(cfg)["s"], {"line": (90, 100), "branch": (40, 50), "instruction": (980, 1000)})

    def test_clover(self):
        clover("c.xml", line=(90, 100), methods=(8, 10), conditionals=(6, 12))
        cfg = config({"s": suite("clover", "c.xml")})
        self.assertEqual(
            cr.counts(cfg)["s"], {"line": (90, 100), "methods": (8, 10), "branch": (6, 12)})

    def test_zero_denominator_metrics_are_dropped(self):
        # A tool that cannot measure something reports 0/0; PCOV does this for Clover conditionals.
        clover("c.xml", conditionals=(0, 0))
        cfg = config({"s": suite("clover", "c.xml")})
        self.assertNotIn("branch", cr.counts(cfg)["s"])

    def test_missing_report_is_none(self):
        cfg = config({"s": suite("istanbul", "absent.json")})
        self.assertIsNone(cr.counts(cfg)["s"])

    def test_malformed_json_is_none(self):
        write("c.json", "{not json")
        cfg = config({"s": suite("istanbul", "c.json")})
        self.assertIsNone(cr.counts(cfg)["s"])

    def test_malformed_xml_is_none(self):
        write("r.xml", "<report><counter")
        cfg = config({"s": suite("kover", "r.xml")})
        self.assertIsNone(cr.counts(cfg)["s"])

    def test_clover_without_metrics_element_is_none(self):
        write("c.xml", "<coverage><project/></coverage>")
        cfg = config({"s": suite("clover", "c.xml")})
        self.assertIsNone(cr.counts(cfg)["s"])


class PercentageTest(TempCwd):
    def test_one_decimal_place(self):
        istanbul("c.json", line=(2, 3), branch=(1, 3))
        cfg = config({"s": suite("istanbul", "c.json")})
        self.assertEqual(cr.percentages(cfg)["s"], {"line": "66.7%", "branch": "33.3%"})

    def test_suite_without_report_is_absent_from_percentages(self):
        istanbul("a.json")
        cfg = config({"a": suite("istanbul", "a.json"), "b": suite("istanbul", "absent.json")})
        self.assertEqual(list(cr.percentages(cfg)), ["a"])

    def test_line_percent_is_none_without_a_report(self):
        cfg = config({"s": suite("istanbul", "absent.json")})
        self.assertIsNone(cr.line_percent(cfg, "s"))


class TotalTest(TempCwd):
    def test_weighted_by_size_not_averaged(self):
        # 100/1000 and 100/100: summing gives 200/1100 = 18.2%, whereas averaging the two
        # percentages (10% and 100%) would flatter the result at 55%.
        istanbul("big.json", line=(100, 1000), branch=(1, 1))
        istanbul("small.json", line=(100, 100), branch=(1, 1))
        cfg = config({"big": suite("istanbul", "big.json"), "small": suite("istanbul", "small.json")})
        self.assertEqual(cr.total_metrics(cfg)["line"], "18.2%")

    def test_metric_missing_from_any_suite_is_not_aggregated(self):
        # The total must never be one suite's number wearing a "Total" label.
        istanbul("front.json", line=(90, 100), branch=(40, 50))
        kcov("shell.json", line=(50, 100))
        cfg = config({"front": suite("istanbul", "front.json"), "shell": suite("kcov", "shell.json")})
        total = cr.total_metrics(cfg)
        self.assertIn("line", total)
        self.assertNotIn("branch", total)

    def test_suites_without_reports_are_excluded(self):
        istanbul("a.json", line=(50, 100), branch=(1, 1))
        cfg = config({"a": suite("istanbul", "a.json"), "b": suite("istanbul", "absent.json")})
        self.assertEqual(cr.total_metrics(cfg)["line"], "50.0%")

    def test_no_reports_at_all_yields_no_total(self):
        cfg = config({"a": suite("istanbul", "absent.json")})
        self.assertEqual(cr.total_metrics(cfg), {})


class MarkdownTest(TempCwd):
    def test_columns_are_the_union_of_metrics_present(self):
        kcov("shell.json", line=(90, 100))
        cfg = config({"shell": suite("kcov", "shell.json", label="Shell")})
        md = cr.render_markdown(cfg)
        self.assertIn("| Suite | Line |", md)
        self.assertNotIn("Branch", md)

    def test_canonical_column_order(self):
        kover("r.xml")
        cfg = config({"m": suite("kover", "r.xml")})
        self.assertIn("| Suite | Line | Branch | Instruction |", cr.render_markdown(cfg))

    def test_heading_and_column_are_configurable(self):
        kover("r.xml")
        cfg = config({"m": suite("kover", "r.xml")}, heading="Coverage (debug unit tests)",
                     column="Module")
        md = cr.render_markdown(cfg)
        self.assertTrue(md.startswith("## Coverage (debug unit tests)"))
        self.assertIn("| Module |", md)

    def test_default_heading(self):
        kcov("c.json")
        self.assertTrue(cr.render_markdown(config({"s": suite("kcov", "c.json")})).startswith("## Coverage"))

    def test_total_row_present_by_default_and_suppressible(self):
        kcov("c.json", line=(90, 100))
        cfg = config({"s": suite("kcov", "c.json")})
        self.assertIn("**Total**", cr.render_markdown(cfg))
        self.assertNotIn("**Total**", cr.render_markdown(config({"s": suite("kcov", "c.json")}, total=False)))

    def test_suite_labels_are_used_as_row_labels(self):
        istanbul("c.json")
        cfg = config({"frontend": suite("istanbul", "c.json", label="Frontend (TypeScript)")})
        self.assertIn("| Frontend (TypeScript) |", cr.render_markdown(cfg))


class ManifestTest(TempCwd):
    def test_total_leads_and_has_no_path(self):
        # The site summarises each commit with its FIRST report's metrics, so the combined total
        # must lead; `path` is omitted so the site renders it as text rather than a dead link.
        istanbul("c.json")
        reports = json.loads(cr.render_reports(config({"app": suite("istanbul", "c.json")})))
        self.assertEqual(reports[0]["name"], "total")
        self.assertNotIn("path", reports[0])

    def test_suite_path_is_its_key(self):
        # The key is the subdirectory collect-coverage.sh publishes the HTML under, so the manifest
        # path must match it or the site's link 404s.
        istanbul("c.json")
        reports = json.loads(cr.render_reports(config({"app": suite("istanbul", "c.json", label="App")})))
        self.assertEqual(reports[1], {"name": "App", "path": "app",
                                      "metrics": {"line": "90.0%", "branch": "80.0%"}})

    def test_suites_keep_declared_order(self):
        istanbul("a.json")
        istanbul("b.json")
        cfg = config({"zebra": suite("istanbul", "a.json"), "alpha": suite("istanbul", "b.json")})
        reports = json.loads(cr.render_reports(cfg))
        self.assertEqual([r["path"] for r in reports[1:]], ["zebra", "alpha"])

    def test_total_false_omits_the_total_entry(self):
        istanbul("c.json")
        reports = json.loads(cr.render_reports(config({"app": suite("istanbul", "c.json")}, total=False)))
        self.assertEqual([r["name"] for r in reports], ["istanbul"])

    def test_suite_without_a_report_is_omitted(self):
        istanbul("a.json")
        cfg = config({"a": suite("istanbul", "a.json"), "b": suite("istanbul", "absent.json")})
        reports = json.loads(cr.render_reports(cfg))
        self.assertEqual([r.get("path") for r in reports], [None, "a"])


class GateTest(TempCwd):
    def test_passes_when_every_suite_meets_its_gate(self):
        istanbul("a.json", line=(99, 100))
        kcov("b.json", line=(95, 100))
        cfg = config({"a": suite("istanbul", "a.json", gate=98.0),
                      "b": suite("kcov", "b.json", gate=94.0)})
        self.assertEqual(cr.run_gate(cfg), 0)

    def test_fails_when_one_suite_is_below(self):
        istanbul("a.json", line=(99, 100))
        kcov("b.json", line=(90, 100))
        cfg = config({"a": suite("istanbul", "a.json", gate=98.0),
                      "b": suite("kcov", "b.json", gate=94.0)})
        self.assertEqual(cr.run_gate(cfg), 1)

    def test_fails_when_a_report_is_missing(self):
        # A gate that passes when the report vanishes is worse than no gate at all.
        cfg = config({"a": suite("istanbul", "absent.json", gate=98.0)})
        self.assertEqual(cr.run_gate(cfg), 1)

    def test_missing_report_fails_even_without_a_gate(self):
        cfg = config({"a": suite("istanbul", "absent.json")})
        self.assertEqual(cr.run_gate(cfg), 1)

    def test_suite_without_a_gate_is_informational(self):
        istanbul("a.json", line=(1, 100))
        self.assertEqual(cr.run_gate(config({"a": suite("istanbul", "a.json")})), 0)

    def test_value_that_rounds_up_to_the_bound_passes(self):
        # 97.96% displays as "98.0%"; failing a "≥ 98" gate on a difference the report cannot show
        # would be indistinguishable from a bug.
        istanbul("a.json", line=(4898, 5000))
        self.assertEqual(cr.run_gate(config({"a": suite("istanbul", "a.json", gate=98.0)})), 0)

    def test_value_below_the_tolerance_still_fails(self):
        istanbul("a.json", line=(4895, 5000))
        self.assertEqual(cr.run_gate(config({"a": suite("istanbul", "a.json", gate=98.0)})), 1)

    def test_gate_uses_line_coverage_not_other_metrics(self):
        # Branch coverage is routinely far lower than line coverage; gating on it by accident would
        # fail every build.
        kover("r.xml", line=(99, 1), branch=(1, 99))
        self.assertEqual(cr.run_gate(config({"m": suite("kover", "r.xml", gate=98.0)})), 0)


class CollectTest(TempCwd):
    def test_emits_key_html_and_require(self):
        cfg = config({"s": suite("kcov", "c.json", html="coverage", require=["data/bcov.css"])})
        self.assertEqual(cr.render_collect(cfg), "s\tcoverage\tdata/bcov.css\t\t")

    def test_optional_fields_are_empty_when_absent(self):
        cfg = config({"s": suite("kcov", "c.json", html="coverage")})
        self.assertEqual(cr.render_collect(cfg), "s\tcoverage\t\t\t")

    def test_emits_include_and_index(self):
        spec = suite("kcov", "c.json", html="coverage")
        spec["include"] = ["kcov-merged", "data"]
        spec["index"] = "kcov-merged/index.html"
        self.assertEqual(
            cr.render_collect(config({"s": spec})),
            "s\tcoverage\t\tkcov-merged,data\tkcov-merged/index.html")

    def test_field_count_is_stable(self):
        # collect-coverage.sh reads these positionally, so a dropped field would silently shift the
        # rest — an empty `include` becoming the index, for instance.
        spec = suite("kcov", "c.json", html="coverage", require=["a"])
        spec["include"] = ["b"]
        spec["index"] = "c.html"
        self.assertEqual(len(cr.render_collect(config({"s": spec})).split("\t")), 5)

    def test_missing_html_exits(self):
        cfg = config({"s": suite("kcov", "c.json")})
        with self.assertRaises(SystemExit):
            cr.render_collect(cfg)


class ConfigTest(TempCwd):
    def test_reads_a_toml_file(self):
        write("coverage.toml", '[suites.app]\nlabel="App"\nformat="istanbul"\nreport="c.json"\ngate=98.0\n')
        cfg = cr.load_config("coverage.toml")
        self.assertEqual(cfg["suites"]["app"]["gate"], 98.0)

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            cr.load_config("absent.toml")

    def test_invalid_toml_exits(self):
        write("coverage.toml", "this is not toml {{{")
        with self.assertRaises(SystemExit):
            cr.load_config("coverage.toml")

    def test_no_suites_exits(self):
        write("coverage.toml", 'heading = "Coverage"\n')
        with self.assertRaises(SystemExit):
            cr.load_config("coverage.toml")

    def test_missing_required_field_exits(self):
        write("coverage.toml", '[suites.app]\nlabel="App"\nformat="istanbul"\n')
        with self.assertRaises(SystemExit):
            cr.load_config("coverage.toml")

    def test_unknown_format_exits(self):
        write("coverage.toml", '[suites.app]\nlabel="App"\nformat="lcov"\nreport="c.json"\n')
        with self.assertRaises(SystemExit):
            cr.load_config("coverage.toml")

    def test_comma_in_a_published_path_exits(self):
        # The publishing table comma-joins these, so a comma would split one path into two.
        for field in ("include", "require"):
            write("coverage.toml",
                  f'[suites.app]\nlabel="App"\nformat="istanbul"\nreport="c.json"\n{field}=["a,b"]\n')
            with self.assertRaises(SystemExit):
                cr.load_config("coverage.toml")


if __name__ == "__main__":
    unittest.main(verbosity=2)
