"""Check the public TEST report in fresh signed-out Chromium contexts.

TLS verification stays enabled. On this cloud machine the default sandboxed
browser could not use certificate trust successfully; the same checks passed
when run through the approved execution context outside that sandbox.
This is a TEST report readiness check, not a verifier of live market facts.
"""
from playwright.sync_api import sync_playwright
import json
base='https://meangyulim.github.io/cost/'
results=[]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    for width in (390,430):
        c=b.new_context(viewport={'width':width,'height':850},device_scale_factor=1)
        page=c.new_page()
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        response=page.goto(base,wait_until='networkidle',timeout=30000)
        assert response.status==200
        assert page.url==base
        assert page.locator('.summary h2').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('link',name='날짜별 보관함').first.click()
        assert page.url==base+'archive/'
        page.locator('.archive a[href="../reports/test-layout-2026-09-30/"]').click()
        assert page.url==base+'reports/test-layout-2026-09-30/'
        assert page.locator('.test-banner').is_visible()
        assert '레이아웃 확인용 자료 · 실제 시세 아님' in page.locator('.test-banner').inner_text()
        assert page.locator('.stock').count()==3
        assert '12,345 KRW' in page.locator('.price-row').first.inner_text()
        assert '2026.09.30 15:30 KST' in page.locator('.price-meta').first.inner_text()
        height=page.evaluate('document.documentElement.scrollHeight')
        page.evaluate("document.documentElement.style.fontSize = '200%'")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('.summary p').evaluate('e => parseFloat(getComputedStyle(e).fontSize)')>=32
        page.evaluate("document.documentElement.style.fontSize = ''")
        page.locator('.number-source').first.click()
        assert page.locator('#source-sample').is_visible()
        assert not errors,errors
        results.append({'width':width,'height':height,'anonymous_browser':'passed','text_200_percent':'passed','archive_report_sources':'passed'})
        c.close()
    b.close()
output=json.dumps({'base_url':base,'tls_verification':True,'checks':results},ensure_ascii=False,indent=2)
print(output)
