"""Exercise the site in Chromium at the same /cost/ subpath as project Pages.

Requires Python Playwright and Chromium; neither is needed for site generation.
The server and browser are local and closed after verification.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
from threading import Thread

from playwright.sync_api import sync_playwright
from build_site import ROOT


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def verify() -> None:
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if not chromium:
        raise RuntimeError("Chromium is required for the optional browser check")
    with tempfile.TemporaryDirectory() as tmp:
        mount = Path(tmp) / "cost"
        mount.symlink_to(ROOT / "public", target_is_directory=True)
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=tmp))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=chromium, headless=True)
                results = []
                for width in (390, 430):
                    context = browser.new_context(viewport={"width": width, "height": 850}, device_scale_factor=1)
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    response = page.goto(origin + "/cost/", wait_until="networkidle")
                    assert response.status == 200
                    assert page.locator(".test-banner").inner_text().startswith("TEST")
                    assert "레이아웃 확인용 자료 · 실제 시세 아님" in page.locator(".test-banner").inner_text()
                    assert page.locator(".stock").count() == 3
                    assert "12,345 KRW" in page.locator(".price-row").first.inner_text()
                    assert "2026.09.30 15:30 KST" in page.locator(".price-meta").first.inner_text()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert page.locator(".summary h2").bounding_box()["y"] < 350
                    assert page.locator(".issue").last.bounding_box()["y"] < 850
                    height = page.evaluate("document.documentElement.scrollHeight")
                    assert height <= 2000, f"Report too long: {height}px at {width}px"
                    for selector in (".summary p", ".issue p", ".stock p:not(.watch):not(.price-meta):not(.source-note)"):
                        for item in page.locator(selector).all():
                            assert item.evaluate("e => parseFloat(getComputedStyle(e).fontSize)") >= 16
                    # Changing the root font size tests 200% text enlargement,
                    # independent of viewport/device pixel ratio.
                    page.evaluate("document.documentElement.style.fontSize = '200%'")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "200% text causes horizontal overflow"
                    assert page.locator(".summary p").evaluate("e => parseFloat(getComputedStyle(e).fontSize)") >= 32
                    page.evaluate("document.documentElement.style.fontSize = ''")
                    page.get_by_role("link", name="날짜별 보관함").first.click()
                    assert page.url.endswith("/cost/archive/")
                    page.locator(".archive a").first.click()
                    assert page.url.endswith("/cost/reports/test-layout-2026-09-30/")
                    assert page.locator(".test-banner").is_visible()
                    page.locator(".number-source").first.click()
                    assert page.locator("#source-sample").is_visible()
                    assert not errors, errors
                    context.close()
                    results.append({"width": width, "height": height, "text_200_percent": "passed", "navigation": "passed"})
                browser.close()
                print(json.dumps({"local_browser_only": True, "checks": results}, ensure_ascii=False, indent=2))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    verify()
