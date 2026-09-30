import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from add_report import add_report
from build_site import ROOT, build, validate


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((ROOT / "data/reports/test-layout-2026-09-30.json").read_text())

    def test_all_generated_links_resolve_under_project_subpath(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "cost"
            build(output)
            for file in output.rglob("*.html"):
                parser = Links()
                parser.feed(file.read_text())
                for link in parser.links:
                    parsed = urlsplit(link)
                    if parsed.scheme:
                        continue
                    self.assertFalse(parsed.path.startswith("/"), link)
                    target = (file.parent / unquote(parsed.path)).resolve() if parsed.path else file
                    self.assertTrue(target.is_relative_to(output.resolve()), link)
                    if target.is_dir():
                        target /= "index.html"
                    self.assertTrue(target.is_file(), link)
                    if parsed.fragment:
                        other = Links()
                        other.feed(target.read_text())
                        self.assertIn(parsed.fragment, other.ids)

    def test_duplicate_report_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.json"
            source.write_text(json.dumps(self.report))
            target = add_report(source, Path(tmp) / "data")
            before = target.read_bytes()
            self.report["summary"] = "Do not overwrite"
            source.write_text(json.dumps(self.report))
            with self.assertRaises(FileExistsError):
                add_report(source, Path(tmp) / "data")
            self.assertEqual(before, target.read_bytes())

    def test_build_preserves_archive_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            report = copy.deepcopy(self.report)
            first = data / (report["id"] + ".json")
            first.write_text(json.dumps(report))
            output = Path(tmp) / "public"
            build(output, data)
            old_report = output / "reports" / report["id"] / "index.html"
            old_content = old_report.read_bytes()
            report["market_date"] = "2026-10-01"
            report["id"] = "test-layout-2026-10-01"
            report["as_of"] = "2026-10-01T15:30:00+09:00"
            (data / (report["id"] + ".json")).write_text(json.dumps(report))
            build(output, data)
            self.assertEqual(old_content, old_report.read_bytes())
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(2, len(manifest["reports"]))
            self.assertEqual(report["id"], manifest["latest_id"])
            contents = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            build(output, data)
            self.assertEqual(contents, {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()})

    def test_market_id_and_kst_are_enforced(self):
        self.report["as_of"] = "2026-09-30T15:30:00"
        with self.assertRaises(ValueError):
            validate(self.report)
        self.report["as_of"] = "2026-09-30T15:30:00+09:00"
        self.report["market_date"] = "2026-10-01"
        with self.assertRaises(ValueError):
            validate(self.report)

    def test_live_report_requires_calendar_and_original_sources(self):
        report = self.report
        report.update(id="kr-close-2026-09-30", is_test=False)
        with self.assertRaises(ValueError):
            validate(report)
        report["calendar_evidence"] = {"url": "https://www.nyse.com/markets/hours-calendars", "market_date": "2026-09-30", "is_trading_day": True, "early_close": False, "checked_at": "2026-09-30T17:45:00+09:00", "note": "Unit test fixture only"}
        with self.assertRaises(ValueError):
            validate(report)
        report["sources"][0]["url"] = "https://example.com/source"
        validate(report)
        report["calendar_evidence"]["is_trading_day"] = False
        with self.assertRaises(ValueError):
            validate(report)

    def test_source_urls_cannot_execute_script(self):
        self.report["sources"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            validate(self.report)

    def test_user_text_is_escaped_and_test_label_is_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            self.report["summary"] = '<script>alert("bad")</script>'
            (data / (self.report["id"] + ".json")).write_text(json.dumps(self.report))
            output = Path(tmp) / "public"
            build(output, data)
            html = (output / "index.html").read_text()
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertIn("레이아웃 확인용 자료 · 실제 시세 아님", html)
            self.assertNotIn("6,838.04", html)

    def test_live_report_is_featured_instead_of_later_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            sample = copy.deepcopy(self.report)
            sample.update(id="test-layout-2026-10-01", market_date="2026-10-01", as_of="2026-10-01T15:30:00+09:00")
            (data / (sample["id"] + ".json")).write_text(json.dumps(sample))
            live = copy.deepcopy(self.report)
            live.update(id="kr-close-2026-09-30", is_test=False, title="Unit test live fixture")
            live["calendar_evidence"] = {"url": "https://example.com/calendar", "market_date": "2026-09-30", "is_trading_day": True, "early_close": False, "checked_at": "2026-09-30T17:45:00+09:00", "note": "Unit test fixture"}
            live["sources"][0]["url"] = "https://example.com/source"
            (data / (live["id"] + ".json")).write_text(json.dumps(live))
            output = Path(tmp) / "public"
            build(output, data)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(live["id"], manifest["latest_id"])


if __name__ == "__main__":
    unittest.main()
