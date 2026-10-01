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
from build_site import ROOT, build, validate, render_report, image_payload


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

    def test_source_visibility_preserves_original_evidence(self):
        report = copy.deepcopy(self.report)
        source = report['sources'][0]
        source['show_public'] = False
        source['label'] = 'hidden-provider-test'
        source['url'] = 'https://api.massive.com/test'
        validate(report)
        html = render_report(report, '.')
        self.assertNotIn('hidden-provider-test', html)
        self.assertNotIn('https://api.massive.com/test', html)
        self.assertEqual(report['sources'][0]['label'], 'hidden-provider-test')
        source['show_public'] = 'false'
        with self.assertRaises(ValueError):
            validate(report)

    def test_percent_unit_is_displayed_once_with_or_without_input_suffix(self):
        for raw, expected in [("+1.95", "+1.95%"), ("+1.95%", "+1.95%"),
                              ("−0.50%", "−0.50%"), ("0.00", "0.00%")]:
            with self.subTest(raw=raw):
                report = copy.deepcopy(self.report)
                for entry in report['indices'] + report['stocks']:
                    entry['direction'] = 'flat' if raw.startswith('0') else ('down' if raw.startswith('−') else 'up')
                    entry['percent'] = raw
                html = render_report(report, '.')
                self.assertNotIn('%%', html)
                self.assertIn('>' + expected + '<', html)
                self.assertEqual(report['indices'][0]['percent'], raw)

    def test_image_uses_public_summary_and_exact_prices(self):
        report = copy.deepcopy(self.report)
        report['reading'] = {'headline': '짧은 결론', 'issues': [{'preview': '핵심 의미'}],
                             'stocks': {report['stocks'][0]['ticker']: {'reason': '짧은 이유'}}}
        report['sources'][0]['show_public'] = False
        report['sources'][0]['label'] = 'do-not-export-provider'
        payload = image_payload(report, '../..')
        self.assertEqual(payload['headline'], '짧은 결론')
        self.assertEqual(payload['issues'][0]['preview'], '핵심 의미')
        self.assertEqual(payload['stocks'][0]['reason'], '짧은 이유')
        self.assertEqual(payload['stocks'][0]['price'], report['stocks'][0]['price'])
        self.assertEqual(payload['stocks'][0]['session'], report['stocks'][0]['session'])
        self.assertEqual(payload['indices'][0]['value'], report['indices'][0]['value'])
        self.assertNotIn('do-not-export-provider', json.dumps(payload))
        self.assertEqual(payload['report_path'], '../../reports/' + report['id'] + '/')
        self.assertTrue(payload['is_test'])
        self.assertEqual(len(payload['issues']), 3)
        self.assertEqual(len(payload['stocks']), 3)

    def test_image_json_cannot_close_script_or_inject_html(self):
        report = copy.deepcopy(self.report)
        report['summary'] = '</script><img src=x onerror=alert(1)> & "text"'
        html = render_report(report, '.')
        payload_text = html.split('id="brief-image-data">', 1)[1].split('</script>', 1)[0]
        self.assertNotIn('<', payload_text)
        self.assertNotIn('&', payload_text)
        self.assertEqual(json.loads(payload_text)['headline'], report['summary'])
        self.assertIn('data-image-action="share"', html)
        self.assertIn('data-image-action="save"', html)

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
            self.assertIn('href="reports/test-layout-2026-09-30/"', (output / "index.html").read_text())
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

    def test_us_intraday_id_uses_new_york_date_and_kst_time(self):
        report = copy.deepcopy(self.report)
        report.update(id="us-intraday-2026-10-01-0321", is_test=False, market="US", session="intraday",
                      market_date="2026-10-01", as_of="2026-10-02T03:21:00+09:00")
        report['calendar_evidence'] = {'url': 'https://www.nyse.com/trade/hours-calendars',
            'market_date': '2026-10-01', 'is_trading_day': True, 'early_close': False,
            'checked_at': '2026-10-02T03:21:00+09:00', 'note': 'Unit test fixture'}
        report['sources'][0]['url'] = 'https://example.com/source'
        validate(report)
        report['id'] = 'us-intraday-2026-10-01-0421'
        with self.assertRaises(ValueError):
            validate(report)

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
