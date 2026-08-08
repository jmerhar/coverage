#!/usr/bin/env python3
"""Unit tests for bin/make-meta.py (stdlib unittest, no network).

meta.json is the contract between a source project and this site: the generator reads nothing else
about a report. A change that dropped or renamed a field would leave every project's commit pages
half-rendered, so the shape is pinned here.

Run: python3 bin/test-make-meta.py
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "make_meta", os.path.join(os.path.dirname(os.path.abspath(__file__)), "make-meta.py"))
mm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mm)

REPORTS = [
    {"name": "total", "metrics": {"line": "97.4%"}},
    {"name": "shared", "path": "shared", "metrics": {"line": "99.6%", "branch": "88.8%"}},
]


def run(reports=REPORTS, **overrides):
    """Invoke make-meta's CLI in-process and return the parsed meta.json it prints."""
    args = {"project": "demo", "sha": "0123456789abcdef0123456789abcdef01234567",
            "message": "commit subject", "commit-url": "https://example.com/c/1"}
    args.update(overrides)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "reports.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(reports, f)
        argv = ["make-meta.py"]
        for k, v in args.items():
            if v is not None:
                argv += [f"--{k}", v]
        argv += ["--reports", path]
        out = io.StringIO()
        old_argv = mm.sys.argv
        mm.sys.argv = argv
        try:
            with contextlib.redirect_stdout(out):
                mm.main()
        finally:
            mm.sys.argv = old_argv
    return json.loads(out.getvalue())


class ShapeTest(unittest.TestCase):
    def test_every_field_the_generator_reads_is_present(self):
        meta = run()
        self.assertEqual(
            set(meta),
            {"project", "sha", "short_sha", "committed_at", "message", "commit_url", "reports"})

    def test_values_are_passed_through(self):
        meta = run()
        self.assertEqual(meta["project"], "demo")
        self.assertEqual(meta["sha"], "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(meta["message"], "commit subject")
        self.assertEqual(meta["commit_url"], "https://example.com/c/1")

    def test_short_sha_is_ten_characters(self):
        # The site shows this as the commit label, and build-site falls back to sha[:10].
        self.assertEqual(run()["short_sha"], "0123456789")

    def test_reports_array_is_preserved_verbatim(self):
        self.assertEqual(run()["reports"], REPORTS)

    def test_explicit_date_is_used(self):
        self.assertEqual(run(date="2026-07-09T09:08:00Z")["committed_at"], "2026-07-09T09:08:00Z")

    def test_default_date_is_utc_iso(self):
        # build-site parses this; a stamp without the Z would render in the wrong zone.
        stamp = run()["committed_at"]
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_optional_text_defaults_to_empty(self):
        meta = run(message=None, **{"commit-url": None})
        self.assertEqual(meta["message"], "")
        self.assertEqual(meta["commit_url"], "")

    def test_empty_reports_array_is_allowed(self):
        # A project may publish metrics-free; the commit page then says "No reports".
        self.assertEqual(run(reports=[])["reports"], [])


class FailureTest(unittest.TestCase):
    def test_reports_that_are_not_an_array_are_rejected(self):
        with self.assertRaises(SystemExit):
            run(reports={"name": "total"})

    def test_missing_reports_file_is_an_error(self):
        argv = ["make-meta.py", "--project", "p", "--sha", "abc", "--reports", "absent.json"]
        old_argv = mm.sys.argv
        mm.sys.argv = argv
        try:
            with self.assertRaises(FileNotFoundError):
                mm.main()
        finally:
            mm.sys.argv = old_argv

    def test_missing_required_argument_is_an_error(self):
        old_argv = mm.sys.argv
        mm.sys.argv = ["make-meta.py", "--project", "p"]
        try:
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                mm.main()
        finally:
            mm.sys.argv = old_argv


if __name__ == "__main__":
    unittest.main(verbosity=2)
