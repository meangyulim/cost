"""Build a dependency-free static site from validated, append-only report sources."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from html import escape
import hashlib
import json
from pathlib import Path
import re
import shutil
from string import Template
from urllib.parse import urlsplit
from directional_outlook import validate_outlook, badges as outlook_badges, details as outlook_details, notice as outlook_notice, image_meta

ROOT = Path(__file__).resolve().parents[1]
REPORT_ID = re.compile(r"(?:test-layout|kr-pre|kr-close|kr-intraday|us-pre|us-close|us-intraday)-\d{4}-\d{2}-\d{2}(?:-\d{4})?\Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def text(value: object) -> str:
    return escape(str(value), quote=True)


def percent(value: str) -> str:
    """Report inputs may already contain their percent unit."""
    return text(value.strip().rstrip("%％").rstrip()) + "%"


def kst(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    require(parsed.utcoffset() == timedelta(hours=9), "Timestamp must include +09:00")
    return parsed.strftime("%Y.%m.%d %H:%M KST")


def validate(report: dict) -> None:
    require(bool(REPORT_ID.fullmatch(report["id"])), "Invalid report ID")
    require(type(report["is_test"]) is bool, "is_test must be a boolean")
    require(report["market"] in ("KR", "US"), "Invalid market")
    require(report["session"] in ("pre", "close", "intraday"), "Invalid session")
    date.fromisoformat(report["market_date"])
    dated_id = report["id"].endswith(report["market_date"])
    timed_intraday_id = (report["session"] == "intraday" and report["id"].endswith(
        report["market_date"] + "-" + datetime.fromisoformat(report["as_of"]).strftime("%H%M")))
    timed_close_id = False
    if report["session"] == "close" and report.get("revision_at"):
        kst(report["revision_at"])
        revision = datetime.fromisoformat(report["revision_at"])
        require(revision.date().isoformat() == report["market_date"], "Revision must match market date")
        require(revision >= datetime.fromisoformat(report["as_of"]), "Revision precedes market close")
        timed_close_id = report["id"].endswith(report["market_date"] + "-" + revision.strftime("%H%M"))
    require(dated_id or timed_intraday_id or timed_close_id, "ID must match market date and edition time")
    if report["is_test"]:
        require(report["id"].startswith("test-layout-"), "TEST report must have a TEST ID")
    else:
        prefix = f'{report["market"].lower()}-{report["session"]}-'
        require(report["id"].startswith(prefix), "ID must match market and session")
        require(report.get("calendar_evidence"), "Live report requires official calendar evidence")
        calendar = report["calendar_evidence"]
        check_url(calendar["url"])
        require(calendar["market_date"] == report["market_date"], "Calendar date mismatch")
        require(calendar["is_trading_day"] is True, "Do not publish on closed days")
        require(type(calendar["early_close"]) is bool, "Record early-close status")
        kst(calendar["checked_at"])
        require(calendar["note"], "Calendar verification note required")
    for key in ("title", "venue", "summary", "summary_detail", "interpretation", "calculation_notes"):
        require(isinstance(report[key], str) and bool(report[key]), f"Missing {key}")
    kst(report["as_of"])
    kst(report["queried_at"])
    require(report["indices"], "At least one index is required")
    require(len(report["issues"]) == 3, "Three issues are required")
    require(len(report["stocks"]) == 3, "Three watch stocks are required")
    require(2 <= len(report["next_checks"]) <= 3, "Two or three next checks are required")
    sources = {source["id"]: source for source in report["sources"]}
    require(len(sources) == len(report["sources"]), "Duplicate source ID")
    for source in sources.values():
        require(re.fullmatch(r"[a-zA-Z0-9_-]+", source["id"]) is not None, "Unsafe source ID")
        require(source["label"] and source["note"], "Source label and note required")
        require(type(source.get("show_public", True)) is bool, "Source visibility must be boolean")
        if source["url"]:
            check_url(source["url"])
        else:
            require(report["is_test"], "Live sources must have original links")
    for entry in report["indices"] + report["stocks"] + report["issues"] + [report["fx"]]:
        require(entry["source"] in sources, "Unknown source reference")
        for key in ("additional_sources", "reason_sources"):
            references = entry.get(key, [])
            require(isinstance(references, list), "Source references must be a list")
            require(all(reference in sources for reference in references), "Unknown supporting source reference")
    for entry in report["indices"] + report["stocks"]:
        require(entry["direction"] in ("up", "down", "flat", "missing"), "Invalid direction")
        for key in ("delta", "percent"):
            require(isinstance(entry[key], str) and bool(entry[key]), f"Missing {key}")
        if entry["direction"] == "missing":
            require(entry.get("missing_reason"), "Explain unverified prices")
        else:
            sign = {"up": "+", "down": "−", "flat": "0"}[entry["direction"]]
            require(all(entry[key].startswith(sign) for key in ("delta", "percent")), "Change sign mismatch")
    for entry in report["indices"]:
        require(entry["name"] and entry["value"] and entry["unit"], "Index fields required")
    for stock in report["stocks"]:
        for key in ("name", "ticker", "price", "currency", "session", "reason", "watch"):
            require(isinstance(stock[key], str) and bool(stock[key]), f"Stock {key} required")
        kst(stock["as_of"])
        if stock["direction"] == "missing":
            require(stock["price"] == "미확인", "Unknown price must say 미확인")
    fx = report["fx"]
    for key in ("label", "value", "unit", "delta", "session"):
        require(isinstance(fx[key], str) and bool(fx[key]), f"FX {key} required")
    require(fx["direction"] in ("up", "down", "flat", "missing"), "Invalid FX direction")
    kst(fx["as_of"])
    for check in report["next_checks"]:
        require(check["label"] and check["title"] and check["detail"], "Next-check fields required")


def check_url(url: str) -> None:
    parsed = urlsplit(url)
    require(parsed.scheme == "https" and bool(parsed.hostname), "Sources require HTTPS")
    require(not parsed.username and not parsed.password, "No credentials in URLs")


def paragraphs(value: str) -> list[str]:
    """Break prose at sentence boundaries without dropping evidence."""
    return [part.strip() for part in re.split(r'(?<=[.!?])\s+', value) if part.strip()]


def bullet_list(items: list[str], class_name: str = "brief-points") -> str:
    return f'<ul class="{text(class_name)}">' + ''.join(f'<li>{text(item)}</li>' for item in items) + '</ul>'


def image_payload(report: dict, prefix: str) -> dict:
    """Share only public, concise report fields; never export hidden evidence."""
    validate_outlook(report)
    reading = report.get("reading", {})
    short_issues = reading.get("issues", [])
    short_checks = reading.get("next_checks", [])
    session = {"pre": "장전", "close": "정규장 마감", "intraday": "장중"}[report["session"]]
    issues = []
    for n, issue in enumerate(report["issues"]):
        short = short_issues[n] if n < len(short_issues) else {}
        issues.append({"title": short.get("title", issue["title"]),
                       "preview": short.get("preview") or short.get("meaning") or paragraphs(issue["fact"])[0],
                       "outlook": short.get("outlook")})
    stocks = []
    for stock in report["stocks"]:
        short = reading.get("stocks", {}).get(stock["ticker"], {})
        stocks.append({key: stock[key] for key in ("name", "ticker", "price", "currency", "percent", "direction", "session")} | {
            "as_of": kst(stock["as_of"]), "reason": short.get("reason", stock["reason"]),
            "watch": short.get("watch", stock["watch"]), "missing_reason": stock.get("missing_reason", ""),
            "outlook": short.get("outlook")})
    return {
        "id": report["id"], "title": report["title"], "is_test": report["is_test"],
        "market": report["market"], "session": session, "as_of": kst(report["as_of"]),
        "queried_at": kst(report["queried_at"]),
        "headline": reading.get("headline", report["summary"]),
        "summary_points": reading.get("summary_points", paragraphs(report["summary_detail"])),
        "indices": [{key: item[key] for key in ("name", "value", "unit", "percent", "direction")} |
                    {"missing_reason": item.get("missing_reason", "")} for item in report["indices"]],
        "fx": {key: report["fx"][key] for key in ("label", "value", "unit", "delta", "direction", "session")} |
              {"as_of": kst(report["fx"]["as_of"])},
        "notices": reading.get("notices") or [report["venue"], report["fx"]["session"]],
        "issues": issues, "stocks": stocks,
        "outlook": image_meta(report),
        "next_checks": [{"label": item["label"], "title": (short_checks[n] if n < len(short_checks) else {}).get("title", item["title"]),
                         "detail": (short_checks[n] if n < len(short_checks) else {}).get("detail", item["detail"]),
                         "outlook": (short_checks[n] if n < len(short_checks) else {}).get("outlook")}
                        for n, item in enumerate(report["next_checks"])],
        "sources": [reading.get("source_labels", {}).get(source["id"], source["label"])
                    for source in report["sources"] if source.get("show_public", True)],
        "report_path": f'{prefix}/reports/{report["id"]}/',
    }


def image_controls(report: dict, prefix: str) -> str:
    # JSON lives in a non-executable script; escape HTML delimiters, not JSON quotes.
    payload = json.dumps(image_payload(report, prefix), ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f'''<div class="image-actions" hidden>
<button type="button" data-image-action="save">이미지 저장</button>
<button type="button" data-image-action="share">이미지 공유 ↗</button>
</div>
<dialog id="image-dialog" aria-labelledby="image-dialog-title">
<div class="image-dialog-head"><h2 id="image-dialog-title">한 장 브리핑</h2><button type="button" id="image-close" aria-label="이미지 미리보기 닫기">닫기</button></div>
<p id="image-status" role="status" aria-live="polite">이미지를 만들고 있어요…</p>
<div class="image-dialog-actions"><a id="image-download" hidden>PNG 저장</a><button type="button" id="image-share" disabled>이미지 공유 ↗</button><button type="button" id="image-retry" hidden>다시 만들기</button></div>
<p class="image-help">아이폰: 공유 창에서 카카오톡 또는 ‘이미지 저장’을 선택하세요. 미리보기 이미지를 길게 눌러 저장할 수도 있어요.</p>
<img id="image-preview" alt="결론, 지수, 이슈, 관찰 종목, 다음 확인을 담은 한 장 브리핑" hidden>
</dialog>
<script type="application/json" id="brief-image-data">{payload}</script>'''


def render_report(report: dict, prefix: str) -> str:
    validate_outlook(report)
    reading = report.get("reading", {})
    session = {"pre": "장전", "close": "정규장 마감", "intraday": "장중"}[report["session"]]
    parts = []
    if report["is_test"]:
        parts.append('<aside class="test-banner"><strong>TEST</strong>레이아웃 확인용 자료 · 실제 시세 아님</aside>')
    parts.extend([
        f'<header><p class="eyebrow">MARKET BRIEF · {text(report["market"])} / {text(session)}</p><h1>{text(report["title"])}</h1><p class="date">{text(kst(report["as_of"]))} 기준</p></header>',
        image_controls(report, prefix),
        '<section class="summary" aria-label="오늘의 결론"><span class="tag">오늘의 결론</span>',
        f'<h2>{text(reading.get("headline", report["summary"]))}</h2>',
        bullet_list(reading.get("summary_points", paragraphs(report["summary_detail"])), "summary-points"),
        '</section><div class="markets" aria-label="지수와 전일 대비 변화">'])
    for index in report["indices"]:
        change = "미확인" if index["direction"] == "missing" else percent(index["percent"])
        parts.append(f'<div class="market"><span class="name">{text(index["name"].split(" · ")[0])}</span><strong>{text(index["value"])}</strong><span class="change {text(index["direction"])}">{change}</span></div>')
        if index["direction"] == "missing":
            parts.append(f'<p class="notice">{text(index["missing_reason"])}</p>')
    parts.append('</div><details class="market-extra"><summary>지수 등락폭 보기</summary><div class="detail-body">')
    for index in report["indices"]:
        delta = "미확인" if index["direction"] == "missing" else f'{index["delta"]} {index["unit"]}'
        parts.append(f'<p>{text(index["name"])} · 전일 대비 {text(delta)}</p>')
    parts.append('</div></details>')
    fx = report["fx"]
    parts.append(f'<div class="fx"><span>{text(fx["label"].split(" · ")[0])}</span><strong>{text(fx["value"])} <small>{text(fx["unit"])}</small></strong><span class="{text(fx["direction"])}">{text(fx["delta"])} {text(fx["unit"])}</span></div>')
    # Session distinctions and uncertainty always stay visible, never in details.
    notices = reading.get("notices") or [report["venue"], fx["session"]]
    parts.append('<aside class="notices" aria-label="자료 기준과 유의사항">')
    parts.extend(f'<p class="notice">{text(notice)}</p>' for notice in notices)
    parts.append('</aside>')
    parts.append(outlook_notice(report))
    parts.append('<nav class="section-nav" aria-label="본문 바로가기"><a href="#issues-title">핵심 이슈</a><a href="#stocks-title">관찰 종목</a><a href="#next-title">다음 확인</a></nav>')
    parts.append('<section aria-labelledby="issues-title"><div class="section-head"><h2 id="issues-title">핵심 이슈</h2><small>눌러서 상세 보기</small></div><div class="issue-list">')
    short_issues = reading.get("issues", [])
    for n, issue in enumerate(report["issues"]):
        short = short_issues[n] if n < len(short_issues) else {}
        preview = short.get("preview") or short.get("meaning") or paragraphs(issue["fact"])[0]
        parts.append(f'<details class="issue"><summary><span class="item-heading"><span class="n">{n+1:02}</span><strong>{text(short.get("title", issue["title"]))}</strong><span class="expand-mark" aria-hidden="true"></span></span><span class="item-preview">{text(preview)}</span>{outlook_badges(short, report)}</summary><div class="detail-body">')
        parts.append(outlook_details(short, report))
        # Show the complete fact text on expansion without repeating its summary.
        parts.append(bullet_list(paragraphs(issue["fact"])))
        if short.get("meaning") and short["meaning"] != preview:
            parts.append(f'<p class="meaning">{text(short["meaning"])}</p>')
        parts.append('</div></details>')
    parts.append('</div></section>')
    parts.append('<section aria-labelledby="stocks-title"><div class="section-head"><h2 id="stocks-title">관찰 종목</h2><small>가격 · 전일 대비</small></div><div class="stocks">')
    for stock in report["stocks"]:
        short = reading.get("stocks", {}).get(stock["ticker"], {})
        change = "미확인" if stock["direction"] == "missing" else percent(stock["percent"])
        parts.append(f'<details class="stock"><summary><span class="stock-top"><span class="stock-identity"><strong>{text(stock["name"])}</strong><span class="code">{text(stock["ticker"])}</span></span><span class="stock-quote"><strong>{text(stock["price"])} <small>{text(stock["currency"])}</small></strong><b class="{text(stock["direction"])}">{change}</b><span class="expand-mark" aria-hidden="true"></span></span></span><span class="item-preview">{text(short.get("reason", stock["reason"]))}</span>')
        if stock["direction"] == "missing":
            parts.append(f'<span class="notice">{text(stock["missing_reason"])}</span>')
        parts.append(outlook_badges(short, report))
        parts.append('</summary><div class="detail-body">')
        parts.append(outlook_details(short, report))
        parts.append(f'<p class="price-meta">{text(stock["session"])} · {text(kst(stock["as_of"]))}</p>')
        if stock["direction"] != "missing":
            parts.append(f'<p class="price-meta">전일 대비 {text(stock["delta"])} {text(stock["currency"])}</p>')
        if short.get("reason") and short["reason"] != stock["reason"]:
            parts.append(f'<p>{text(stock["reason"])}</p>')
        parts.append(f'<p class="watch"><span>확인할 것</span>{text(short.get("watch", stock["watch"]))}</p>')
        if short.get("watch") and short["watch"] != stock["watch"]:
            parts.append(f'<p class="full-context">{text(stock["watch"])}</p>')
        parts.append('</div></details>')
    parts.append('</div></section>')
    parts.append('<section aria-labelledby="next-title"><div class="section-head"><h2 id="next-title">다음 확인</h2></div><ol class="next">')
    short_checks = reading.get("next_checks", [])
    for n, check in enumerate(report["next_checks"]):
        short = short_checks[n] if n < len(short_checks) else {}
        parts.append(f'<li><span>{text(check["label"])}</span><div><b>{text(short.get("title", check["title"]))}</b><p>{text(short.get("detail", check["detail"]))}</p>')
        if short.get('outlook'):
            parts.append(outlook_badges(short, report))
            parts.append('<details class="check-more"><summary>조건별 방향 보기</summary>' + outlook_details(short, report) + '</details>')
        if short.get("detail") and short["detail"] != check["detail"]:
            parts.append(f'<details class="check-more"><summary>일정 근거</summary><p>{text(check["detail"])}</p></details>')
        parts.append('</div></li>')
    parts.append('</ol><details class="interpretation"><summary>판단 기준·계산 근거</summary><div class="detail-body">')
    parts.append(bullet_list(reading.get("interpretation_points", paragraphs(report["interpretation"]))))
    parts.append(f'<p class="full-context">{text(report["interpretation"])}</p><p class="full-context">{text(report["calculation_notes"])}</p></div></details></section>')
    sources = [source for source in report["sources"] if source.get("show_public", True)]
    labels = reading.get("source_labels", {})
    parts.append(f'<section class="sources-section"><details><summary>출처 <span class="source-count">{len(sources)}</span></summary><ul class="source-list">')
    for source in sources:
        label = labels.get(source["id"], source["label"])
        link = f'<a href="{text(source["url"])}" rel="noreferrer">{text(label)} ↗</a>' if source["url"] else text(label)
        parts.append(f'<li id="source-{text(source["id"])}">{link}</li>')
    parts.append(f'</ul></details><p class="source-note">자료 조회 {text(kst(report["queried_at"]))}</p></section>')
    return '\n'.join(parts)


def load_reports(data_dir: Path) -> list[dict]:
    reports = []
    ids = set()
    for file in sorted(data_dir.glob("*.json")):
        report = json.loads(file.read_text(encoding="utf-8"))
        validate(report)
        reading_file = data_dir.parent / "reading" / file.name
        if reading_file.is_file():
            report["reading"] = json.loads(reading_file.read_text(encoding="utf-8"))
        validate_outlook(report)
        require(file.stem == report["id"], "Source filename must match report ID")
        require(report["id"] not in ids, "Duplicate report ID")
        ids.add(report["id"])
        reports.append(report)
    require(bool(reports), "No reports to publish")
    return sorted(reports, key=lambda r: (r["market_date"], r["as_of"], r.get("revision_at", r["as_of"]), r["id"]), reverse=True)


def build(output: Path, data_dir: Path = ROOT / "data/reports") -> None:
    reports = load_reports(data_dir)
    # Validate every source before writing any output. Never delete previous reports.
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "assets/style.css", output / "assets/style.css")
    shutil.copyfile(ROOT / "assets/brief-image.js", output / "assets/brief-image.js")
    image_version = hashlib.sha256((ROOT / "assets/brief-image.js").read_bytes()).hexdigest()[:16]
    style_version = hashlib.sha256((ROOT / "assets/style.css").read_bytes()).hexdigest()[:16]
    page = Template((ROOT / "templates/page.html").read_text(encoding="utf-8"))

    def write_page(path: str, title: str, content: str, prefix: str) -> None:
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page.substitute(title=text(title), description=text("TEST · 레이아웃 확인용 자료 · 실제 시세 아님" if 'TEST' in title else title), asset_prefix=prefix, image_version=image_version, style_version=style_version, content=content), encoding="utf-8")

    manifest = []
    for report in reports:
        report_path = f'reports/{report["id"]}/index.html'
        write_page(report_path, report["title"], render_report(report, "../.."), "../..")
        manifest.append({key: report[key] for key in ("id", "is_test", "market", "session", "market_date", "title", "summary", "as_of") } | {"path": f'reports/{report["id"]}/'})
    live_reports = [report for report in reports if not report["is_test"]]
    latest = (live_reports or reports)[0]
    latest_path = f'reports/{latest["id"]}/'
    history_rows = []
    for item in manifest:
        if item["id"] != latest["id"]:
            history_rows.append(f'<li><a href="{item["path"]}">{text(item["title"])}</a><p>{text(kst(item["as_of"]))} · {text(item["market"])} / {text(item["session"])}</p></li>')
    history = '<section class="history-section"><details><summary>지난 브리핑</summary><ul class="archive">' + '\n'.join(history_rows) + '</ul></details></section>' if history_rows else ''
    write_page("index.html", latest["title"], render_report(latest, ".") + f'<p class="archive-link"><a href="{latest_path}">이 회차 고유 주소</a> · <a href="archive/">전체 날짜별 목록</a></p>' + history, ".")
    rows = []
    for item in manifest:
        label = "TEST · " if item["is_test"] else ""
        rows.append(f'<li><a href="../{item["path"]}">{label}{text(item["title"])}</a><p>{text(kst(item["as_of"]))} · {text(item["market"])} / {text(item["session"])}</p><p>{text(item["summary"])}</p></li>')
    write_page("archive/index.html", "날짜별 보관함 · MARKET BRIEF", '<header><h1>날짜별 보관함</h1></header><p class="source-note">최신순 · TEST는 실제 보고서와 구분합니다.</p><ul class="archive">' + '\n'.join(rows) + '</ul>', "..")
    (output / "manifest.json").write_text(json.dumps({"version": 1, "latest_id": latest["id"], "reports": manifest}, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    (output / ".nojekyll").touch()
    print(f"Built {len(reports)} report(s) → {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "public")
    args = parser.parse_args()
    build(args.output)
