"""Build a dependency-free static site from validated, append-only report sources."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from html import escape
import json
from pathlib import Path
import re
import shutil
from string import Template
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPORT_ID = re.compile(r"(?:test-layout|kr-pre|kr-close|kr-intraday|us-pre|us-close)-\d{4}-\d{2}-\d{2}(?:-\d{4})?\Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def text(value: object) -> str:
    return escape(str(value), quote=True)


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


def render_report(report: dict, prefix: str) -> str:
    reading = report.get("reading", {})
    banner = '<aside class="test-banner"><strong>TEST</strong>레이아웃 확인용 자료 · 실제 시세 아님</aside>' if report["is_test"] else ''
    session = {"pre": "장전", "close": "정규장 마감", "intraday": "장중"}[report["session"]]
    parts = [banner,
        f'<header><p class="eyebrow">MARKET BRIEF</p><h1>{text(report["title"])}</h1><p class="date">{text(kst(report["as_of"]))} 기준 · {session}</p></header>',
        f'<section class="summary" aria-label="오늘의 결론"><span class="tag">오늘의 결론</span><h2>{text(reading.get("headline", report["summary"]))}</h2>',
        bullet_list(reading.get("summary_points", paragraphs(report["summary_detail"])), "summary-points"), '</section>',
        '<div class="markets" aria-label="지수와 전일 대비 변화">']
    for index in report["indices"]:
        name = index["name"].split(" · ")[0]
        change = "전일 대비 미확인" if index["direction"] == "missing" else f'{text(index["percent"])}%'
        delta = "" if index["direction"] == "missing" else f'전일 대비 {text(index["delta"])} {text(index["unit"])}'
        parts.append(f'<div class="market"><span class="name">{text(name)}</span><strong>{text(index["value"])}</strong><div class="change {text(index["direction"])}">{change}</div><small>{delta}</small></div>')
        if index["direction"] == "missing":
            parts.append(f'<p class="notice">{text(index["missing_reason"])}</p>')
    fx = report["fx"]
    parts.extend(['</div>', f'<div class="fx"><span>{text(fx["label"].split(" · ")[0])}</span><strong>{text(fx["value"])} <small>{text(fx["unit"])}</small></strong><span class="{text(fx["direction"])}">{text(fx["delta"])} {text(fx["unit"])}</span></div>'])
    notices = reading.get("notices", [])
    if not notices:
        # Keep market/session distinctions visible on legacy reports too.
        notices = [report["venue"], fx["session"]]
    for notice in notices:
        parts.append(f'<p class="notice">{text(notice)}</p>')
    parts.append('<section aria-labelledby="issues-title"><div class="section-head"><h2 id="issues-title">오늘 움직인 이유</h2></div><div class="issue-list">')
    issue_readings = reading.get("issues", [])
    for number, issue in enumerate(report["issues"]):
        short = issue_readings[number] if number < len(issue_readings) else {}
        parts.append(f'<article class="issue"><h3><span class="n">{number+1:02}</span>{text(short.get("title", issue["title"]))}</h3>')
        parts.append(bullet_list(short.get("points", paragraphs(issue["fact"]))))
        if short.get("meaning"):
            parts.append(f'<p class="meaning"><span>의미</span>{text(short["meaning"])}</p>')
        parts.append('</article>')
    parts.extend(['</div>', '<div class="reading"><h3>다음에 볼 것</h3>', bullet_list(reading.get("interpretation_points", paragraphs(report["interpretation"]))), '</div></section>',
        '<section aria-labelledby="stocks-title"><div class="section-head"><h2 id="stocks-title">관찰 종목</h2><small>가격 · 전일 대비</small></div><div class="stocks">'])
    stock_readings = reading.get("stocks", {})
    for stock in report["stocks"]:
        short = stock_readings.get(stock["ticker"], {})
        change = "미확인" if stock["direction"] == "missing" else f'{text(stock["percent"])}%'
        delta = "" if stock["direction"] == "missing" else f'{text(stock["delta"])} {text(stock["currency"])}'
        parts.append(f'<article class="stock"><div class="stock-top"><h3>{text(stock["name"])}</h3><span class="code">{text(stock["ticker"])}</span></div><div class="price-row"><strong>{text(stock["price"])} <small>{text(stock["currency"])}</small></strong><b class="{text(stock["direction"])}">{change}</b></div><p class="price-meta">{delta} · {text(kst(stock["as_of"]))}</p>')
        if stock["direction"] == "missing":
            parts.append(f'<p class="notice">{text(stock["missing_reason"])}</p>')
        parts.append(f'<p>{text(short.get("reason", stock["reason"]))}</p><p class="watch"><span>확인할 것</span>{text(short.get("watch", stock["watch"]))}</p>')
        if not short:
            parts.append(f'<p class="price-meta">{text(stock["session"])}</p>')
        parts.append('</article>')
    parts.extend(['</div></section>', '<section aria-labelledby="next-title"><div class="section-head"><h2 id="next-title">다음 일정·확인 순서</h2></div><ol class="next">'])
    check_readings = reading.get("next_checks", [])
    for number, check in enumerate(report["next_checks"]):
        short = check_readings[number] if number < len(check_readings) else {}
        parts.append(f'<li><span>{text(check["label"])}</span><div><b>{text(short.get("title", check["title"]))}</b><p>{text(short.get("detail", check["detail"]))}</p></div></li>')
    parts.extend(['</ol></section>', '<section class="sources-section" aria-labelledby="sources-title"><h2 id="sources-title">출처</h2><p class="source-caption">매체명과 자료 제목을 누르면 원문으로 이동합니다.</p><ul class="source-list">'])
    labels = reading.get("source_labels", {})
    for source in report["sources"]:
        if not source.get("show_public", True):
            continue
        label = labels.get(source["id"], source["label"])
        link = f'<a href="{text(source["url"])}" rel="noreferrer">{text(label)} ↗</a>' if source["url"] else text(label)
        parts.append(f'<li id="source-{text(source["id"])}">{link}</li>')
    parts.extend(['</ul>', f'<p class="source-note">자료 조회 {text(kst(report["queried_at"]))}</p></section>'])
    return '\n'.join(part for part in parts if part)


def load_reports(data_dir: Path) -> list[dict]:
    reports = []
    ids = set()
    for file in sorted(data_dir.glob("*.json")):
        report = json.loads(file.read_text(encoding="utf-8"))
        validate(report)
        reading_file = data_dir.parent / "reading" / file.name
        if reading_file.is_file():
            report["reading"] = json.loads(reading_file.read_text(encoding="utf-8"))
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
    page = Template((ROOT / "templates/page.html").read_text(encoding="utf-8"))

    def write_page(path: str, title: str, content: str, prefix: str) -> None:
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page.substitute(title=text(title), description=text("TEST · 레이아웃 확인용 자료 · 실제 시세 아님" if 'TEST' in title else title), asset_prefix=prefix, content=content), encoding="utf-8")

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
    history = '<section aria-labelledby="history-title"><h2 id="history-title">이전 브리핑</h2><ul class="archive">' + '\n'.join(history_rows) + '</ul></section>' if history_rows else ''
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
