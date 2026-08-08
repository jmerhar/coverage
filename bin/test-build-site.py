#!/usr/bin/env python3
"""Unit tests for bin/build-site.py (stdlib unittest, no network).

Every deploy runs this over every project's reports, and the pages it writes are the only way anyone
reaches a report. A regression here breaks the whole site at once — silently, since the raw reports
are still there and the workflow still goes green — so the page structure, the links and the
newest-first ordering are pinned.

Run: python3 bin/test-build-site.py
"""
import importlib.util
import json
import os
import re
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "build_site", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build-site.py"))
bs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bs)


def meta(sha, at, message="a commit", reports=None, **extra):
    """A meta.json dict as bin/make-meta.py would write it."""
    m = {"project": "demo", "sha": sha, "short_sha": sha[:10], "committed_at": at,
         "message": message, "commit_url": f"https://example.com/c/{sha[:7]}",
         "reports": reports if reports is not None else
         [{"name": "total", "metrics": {"line": "90.0%"}},
          {"name": "app", "path": "app", "metrics": {"line": "90.0%"}}]}
    m.update(extra)
    return m


class SiteTest(unittest.TestCase):
    """Builds a small reports tree in a temp dir and inspects the generated pages."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "reports")
        os.makedirs(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def add(self, project, m):
        d = os.path.join(self.root, project, m["sha"])
        os.makedirs(os.path.join(d, "app"), exist_ok=True)
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)

    def build(self):
        """Run the generator over the temp tree exactly as the workflow does."""
        bs.ROOT = self.root
        bs.main()

    def read(self, *parts):
        with open(os.path.join(self.root, *parts), encoding="utf-8") as f:
            return f.read()


class LoadTest(SiteTest):
    def test_commits_are_newest_first(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z"))
        self.add("demo", meta("b" * 40, "2026-03-01T00:00:00Z"))
        self.add("demo", meta("c" * 40, "2026-02-01T00:00:00Z"))
        order = [c["sha"][0] for c in bs.load_projects(self.root)["demo"]]
        self.assertEqual(order, ["b", "c", "a"])

    def test_directories_without_meta_are_ignored(self):
        # A half-written publish must not take the whole deploy down.
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z"))
        os.makedirs(os.path.join(self.root, "demo", "d" * 40, "app"))
        self.assertEqual(len(bs.load_projects(self.root)["demo"]), 1)

    def test_projects_without_commits_are_dropped(self):
        os.makedirs(os.path.join(self.root, "empty"))
        self.assertEqual(bs.load_projects(self.root), {})

    def test_stray_files_at_the_root_are_ignored(self):
        # .nojekyll and index.html live beside the project directories.
        open(os.path.join(self.root, ".nojekyll"), "w").close()
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z"))
        self.assertEqual(list(bs.load_projects(self.root)), ["demo"])


class PagesTest(SiteTest):
    def test_every_page_is_generated(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z"))
        self.build()
        for p in ("index.html", "demo/index.html", f"demo/{'a' * 40}/index.html", ".nojekyll"):
            self.assertTrue(os.path.exists(os.path.join(self.root, p)), p)

    def test_root_lists_projects_with_counts(self):
        self.add("one", meta("a" * 40, "2026-01-01T00:00:00Z"))
        self.add("two", meta("b" * 40, "2026-01-01T00:00:00Z"))
        self.add("two", meta("c" * 40, "2026-02-01T00:00:00Z"))
        self.build()
        root = self.read("index.html")
        self.assertIn("href='one/'", root)
        self.assertIn("href='two/'", root)
        self.assertRegex(root, r"href='two/'>two</a></td><td class=nowrap>2<")

    def test_root_says_so_when_there_is_nothing(self):
        self.build()
        self.assertIn("No projects yet.", self.read("index.html"))

    def test_project_page_links_each_commit(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z", message="first"))
        self.build()
        page = self.read("demo", "index.html")
        self.assertIn(f"href='{'a' * 40}/'", page)
        self.assertIn("first", page)

    def test_project_headline_uses_the_first_report(self):
        # The manifest leads with a combined "total" for exactly this reason.
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z", reports=[
            {"name": "total", "metrics": {"line": "77.7%"}},
            {"name": "app", "path": "app", "metrics": {"line": "12.3%"}}]))
        self.build()
        page = self.read("demo", "index.html")
        self.assertIn("77.7%", page)
        self.assertNotIn("12.3%", page)

    def test_commit_page_links_reports_with_a_path(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z"))
        self.build()
        page = self.read("demo", "a" * 40, "index.html")
        self.assertIn("href='app/index.html'", page)

    def test_metrics_only_rows_are_text_not_links(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z", reports=[
            {"name": "total", "metrics": {"line": "90.0%"}}]))
        self.build()
        page = self.read("demo", "a" * 40, "index.html")
        self.assertIn(">total<", page)
        self.assertNotIn("total</a>", page)

    def test_commit_page_says_so_with_no_reports(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z", reports=[]))
        self.build()
        self.assertIn("No reports.", self.read("demo", "a" * 40, "index.html"))

    def test_commit_page_links_the_source_commit(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z"))
        self.build()
        self.assertIn("https://example.com/c/aaaaaaa", self.read("demo", "a" * 40, "index.html"))

    def test_commit_without_a_url_is_not_linked(self):
        m = meta("a" * 40, "2026-01-01T00:00:00Z")
        del m["commit_url"]
        self.add("demo", m)
        self.build()
        page = self.read("demo", "a" * 40, "index.html")
        self.assertIn("<code>aaaaaaaaaa</code>", page)

    def test_newer_and_older_navigation(self):
        for i, sha in enumerate("abc"):
            self.add("demo", meta(sha * 40, f"2026-0{i + 1}-01T00:00:00Z"))
        self.build()
        newest, middle, oldest = ("c" * 40, "b" * 40, "a" * 40)
        self.assertNotIn("newer", self.read("demo", newest, "index.html"))
        mid = self.read("demo", middle, "index.html")
        self.assertIn(f"href='../{newest}/'>newer", mid)
        self.assertIn(f"href='../{oldest}/'>older", mid)
        self.assertNotIn("older", self.read("demo", oldest, "index.html"))

    def test_generation_is_idempotent(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z"))
        self.build()
        first = self.read("demo", "index.html")
        self.build()
        self.assertEqual(first, self.read("demo", "index.html"))

    def test_the_raw_report_is_never_touched(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z"))
        report = os.path.join(self.root, "demo", "a" * 40, "app", "index.html")
        with open(report, "w", encoding="utf-8") as f:
            f.write("RAW REPORT")
        self.build()
        with open(report, encoding="utf-8") as f:
            self.assertEqual(f.read(), "RAW REPORT")


class EscapingTest(SiteTest):
    def test_a_commit_message_cannot_inject_markup(self):
        # Messages come from arbitrary source repositories and are rendered on a shared site.
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z",
                              message="<script>alert(1)</script> & \"quoted\""))
        self.build()
        page = self.read("demo", "index.html")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&amp;", page)

    def test_metric_names_and_values_are_escaped(self):
        self.add("demo", meta("a" * 40, "2026-01-01T00:00:00Z",
                              reports=[{"name": "<b>x</b>", "metrics": {"<k>": "<v>"}}]))
        self.build()
        page = self.read("demo", "a" * 40, "index.html")
        self.assertNotIn("<b>x</b>", page)
        self.assertIn("&lt;k&gt;", page)


class FormattingTest(unittest.TestCase):
    def test_percentage_colour_bands(self):
        self.assertEqual(bs._pct_class("90.0%"), "good")
        self.assertEqual(bs._pct_class("80%"), "good")
        self.assertEqual(bs._pct_class("79.9%"), "mid")
        self.assertEqual(bs._pct_class("50%"), "mid")
        self.assertEqual(bs._pct_class("49.9%"), "low")

    def test_non_percentages_get_no_colour(self):
        # metrics is a free-form map: a project may report "n/a", counts, or anything else.
        for value in ("n/a", "1234", "", "yes"):
            self.assertEqual(bs._pct_class(value), "", value)

    def test_dates_render_as_utc(self):
        self.assertEqual(bs.fmt_date("2026-07-09T09:08:00Z"), "2026-07-09&nbsp;09:08")

    def test_offset_dates_are_converted_to_utc(self):
        self.assertEqual(bs.fmt_date("2026-07-09T11:08:00+02:00"), "2026-07-09&nbsp;09:08")

    def test_unparseable_dates_fall_back_to_the_raw_value(self):
        self.assertEqual(bs.fmt_date("not a date"), "not a date")
        self.assertEqual(bs.fmt_date(None), "None")

    def test_timestamp_carries_the_iso_value_for_the_local_time_script(self):
        self.assertIn("data-utc='2026-07-09T09:08:00Z'", bs.ts_span("2026-07-09T09:08:00Z"))

    def test_empty_metrics_render_as_a_dash(self):
        self.assertIn("—", bs.metric_pills({}))

    def test_short_sha_falls_back_to_the_full_sha(self):
        self.assertEqual(bs.short({"sha": "a" * 40}), "a" * 10)
        self.assertEqual(bs.short({"sha": "a" * 40, "short_sha": "given"}), "given")


class PageShellTest(unittest.TestCase):
    def test_pages_are_valid_standalone_documents(self):
        out = bs.page("Title", "<h1>Body</h1>")
        self.assertTrue(out.startswith("<!doctype html>"))
        self.assertIn("<title>Title</title>", out)
        self.assertIn("<h1>Body</h1>", out)
        self.assertIn("charset=utf-8", out)

    def test_page_titles_are_escaped(self):
        self.assertIn("&lt;script&gt;", bs.page("<script>", ""))

    def test_every_generated_page_carries_the_local_time_script(self):
        self.assertIn("data-utc", bs.SCRIPT + bs.ts_span("2026-01-01T00:00:00Z"))
        self.assertIn("querySelectorAll('.ts')", bs.SCRIPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
