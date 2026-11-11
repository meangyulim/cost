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
from directional_outlook import MOODS, PLAIN, labels, validate_outlook, details as outlook_details, notice as outlook_notice, timestamp, view_written

ROOT = Path(__file__).resolve().parents[1]
REPORT_ID = re.compile(r"(?:test-layout|kr-pre|kr-close|kr-intraday|us-pre|us-close|us-intraday)-\d{4}-\d{2}-\d{2}(?:-\d{4})?\Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def text(value: object) -> str:
    return escape(str(value), quote=True)


def percent(value: str) -> str:
    """Report inputs may already contain their percent unit; %p and bp changes keep their own unit."""
    value = value.strip()
    if re.search(r"(%p|bp)$", value):
        return text(value)
    return text(value.rstrip("%％").rstrip()) + "%"


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
    require(len(report["issues"]) >= 1, "At least one issue is required")
    require(len(report["stocks"]) >= 1, "At least one watch stock is required")
    require(len(report["next_checks"]) >= 2, "At least two next checks are required")
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


WEEKDAYS = "월화수목금토일"
MARKET_NAME = {"KR": "한국", "US": "미국"}
SESSION_NAME = {"pre": "장전", "close": "마감", "intraday": "장중"}
# The four scheduled editions of one market day, in reading order (KST schedule).
SLOTS = [("KR", "pre", "08:20"), ("KR", "close", "15:45"), ("US", "pre", "22:59"), ("US", "close", "06:15")]
ICON_BACK = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>'
ICON_SHARE = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>'


def number(value: object) -> float:
    """Parse a displayed number such as '1,277,000' or '−3.12'."""
    cleaned = str(value).replace(",", "").replace("−", "-").replace("+", "").strip().rstrip("%％").strip()
    require(re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned) is not None, f"Not a number: {value}")
    return float(cleaned)


def edition_label(report: dict) -> str:
    return f'{MARKET_NAME[report["market"]]} {SESSION_NAME[report["session"]]}'


def day_label(value: date) -> str:
    return f'{value.month}월 {value.day}일 {WEEKDAYS[value.weekday()]}요일'


def short_time(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%H:%M")


def validate_extras(report: dict) -> None:
    """Optional chart fields. They must agree with the published prices they decorate."""
    for entry in report["indices"] + report["stocks"]:
        if "range" not in entry:
            continue
        bounds = entry["range"]
        require(isinstance(bounds, dict) and {"high", "low"} <= set(bounds) <= {"open", "high", "low", "prev_close"},
                "range needs high/low and only open/high/low/prev_close")
        low, high = number(bounds["low"]), number(bounds["high"])
        require(low <= high, "range low must not exceed high")
        close = number(entry.get("value", entry.get("price")))
        for value in [close] + ([number(bounds["open"])] if "open" in bounds else []):
            require(low <= value <= high, "Published price must sit inside its day range")
        if "prev_close" in bounds:
            number(bounds["prev_close"])
    reading = report.get("reading", {})
    levels = reading.get("levels")
    if levels is not None:
        require(isinstance(levels, dict) and isinstance(levels.get("target"), str) and levels["target"], "levels need a target")
        number(levels["close"])
        require("d1" in levels and set(levels) <= {"target", "close", "d1", "d5"}, "levels need d1 and only d1/d5")
        for key in ("d1", "d5"):
            if key in levels:
                for side in ("up", "down"):
                    line = levels[key][side]
                    number(line["value"])
                    require(isinstance(line.get("rule", ""), str), "level rule must be text")
                require(number(levels[key]["down"]["value"]) < number(levels[key]["up"]["value"]), "down line must sit below up line")
    figure = reading.get("key_figure")
    if figure is not None:
        require(isinstance(figure.get("value"), str) and figure["value"] and isinstance(figure.get("label"), str) and figure["label"],
                "key_figure needs value and label")
        require(figure.get("direction", "flat") in ("up", "down", "flat"), "key_figure direction")


def fx_value(fx: dict) -> str:
    return fx["value"] + ("%" if fx["unit"] == "%" else "")


def fx_change(fx: dict) -> str:
    """Append the unit only to a bare number; '+0.119%p' already carries its own."""
    delta = fx["delta"].strip()
    return f'{delta} {fx["unit"]}' if re.fullmatch(r"[+−-]?[\d.,]+", delta) else delta


def change_text(entry: dict) -> str:
    return "미확인" if entry["direction"] == "missing" else percent(entry["percent"])


def range_bar(entry: dict, labels: bool = False) -> str:
    bounds = entry.get("range")
    if not bounds:
        return ""
    low, high = number(bounds["low"]), number(bounds["high"])
    if high <= low:
        return ""
    close = number(entry.get("value", entry.get("price")))
    pos = lambda value: f'{(value - low) / (high - low) * 100:.1f}%'
    parts = [f'<div class="range" role="img" aria-label="당일 저가 {text(bounds["low"])}, 고가 {text(bounds["high"])}'
             + (f', 시가 {text(bounds["open"])}' if "open" in bounds else "") + f', 현재 {text(entry.get("value", entry.get("price")))}">',
             '<span class="track"></span>']
    if "open" in bounds:
        start = number(bounds["open"])
        tone = "up" if close > start else "down" if close < start else "flat"
        left, right = sorted((start, close))
        parts.append(f'<span class="path {tone}" style="left:{pos(left)};width:{(right - left) / (high - low) * 100:.1f}%"></span>')
        parts.append(f'<span class="open" style="left:{pos(start)}"></span>')
    if "prev_close" in bounds and low <= number(bounds["prev_close"]) <= high:
        parts.append(f'<span class="prev" style="left:{pos(number(bounds["prev_close"]))}"></span>')
    parts.append(f'<span class="close" style="left:{pos(close)}"></span></div>')
    if labels:
        parts.append('<div class="range-labels">' + f'<span>저 {text(bounds["low"])}</span>'
                     + (f'<span>전일 {text(bounds["prev_close"])}</span>' if "prev_close" in bounds else "")
                     + f'<span>고 {text(bounds["high"])}</span></div>')
    return "".join(parts)


def masthead(report: dict, prefix: str) -> str:
    when = day_label(date.fromisoformat(report["market_date"]))
    place = " · 뉴욕" if report["market"] == "US" else ""
    return (f'<header class="masthead"><a class="icon-btn" href="{prefix}/archive/" aria-label="날짜별 보관함">{ICON_BACK}</a>'
            f'<div class="brand"><a href="{prefix}/index.html">코스트 브리핑</a><span>{text(when)}{place}</span></div>'
            f'<button type="button" class="icon-btn" data-image-action="share" aria-label="카드 이미지 공유" hidden>{ICON_SHARE}</button></header>')


def day_strip(report: dict, day_reports: dict, prefix: str) -> str:
    if report["is_test"]:
        return ""
    cells = []
    for market, session, scheduled in SLOTS:
        name = f'{MARKET_NAME[market]} {SESSION_NAME[session]}'
        found = day_reports.get((report["market_date"], market, session))
        if found is None:
            cells.append(f'<span class="none"><i></i>{name} {scheduled}</span>')
        elif found["id"] == report["id"]:
            cells.append(f'<span class="current" aria-current="page"><i></i>{name} {short_time(found["queried_at"])}</span>')
        else:
            cells.append(f'<a class="done" href="{prefix}/reports/{found["id"]}/"><i></i>{name} {short_time(found["queried_at"])}</a>')
    return '<nav class="day-strip" aria-label="같은 날 회차">' + "".join(cells) + '</nav>'


def band(report: dict) -> str:
    first, *others = report["indices"]
    parts = ['<section class="band" aria-label="지수와 환율"><div class="lead-index">',
             f'<div class="quote-row"><span class="name">{text(first["name"].split(" · ")[0])}</span>'
             f'<span class="value"><b>{text(first["value"])}</b><span class="change {text(first["direction"])}">{change_text(first)}</span></span></div>']
    if first["direction"] == "missing":
        parts.append(f'<p class="missing-note">{text(first["missing_reason"])}</p>')
    else:
        parts.append(f'<span class="delta">전일 대비 {text(first["delta"])} {text(first["unit"])}</span>')
    parts.append(range_bar(first, labels=True) + '</div><div class="band-grid">')
    fx = report["fx"]
    for item in others:
        parts.append(f'<div><span class="name">{text(item["name"].split(" · ")[0])}</span><span class="value"><b>{text(item["value"])}</b>'
                     f'<span class="change {text(item["direction"])}">{change_text(item)}</span></span>'
                     + (f'<span class="missing-note">{text(item["missing_reason"])}</span>' if item["direction"] == "missing" else "") + '</div>')
    parts.append(f'<div><span class="name">{text(fx["label"].split(" · ")[0])}</span><span class="value"><b>{text(fx_value(fx))}</b>'
                 f'<span class="change {text(fx["direction"])}">{text(fx_change(fx))}</span></span></div>')
    return "".join(parts) + '</div></section>'


def key_figure(report: dict) -> str:
    figure = report.get("reading", {}).get("key_figure")
    if not figure:
        return ""
    note = f' <span class="tag caution">{text(figure["note"])}</span>' if figure.get("note") else ""
    detail = f'<br>{text(figure["detail"])}' if figure.get("detail") else ""
    return (f'<section class="key-figure" aria-label="오늘의 숫자"><b class="{text(figure.get("direction", "flat"))}">{text(figure["value"])}</b>'
            f'<span>{text(figure["label"])}{note}{detail}</span></section>')


def representative(report: dict):
    reading = report.get("reading", {})
    for entry in reading.get("issues", []) + reading.get("next_checks", []):
        if entry.get("outlook"):
            return entry
    return None


def cite(report: dict, ids: list[str]) -> str:
    """Outlet names linking to the originals (full label on hover); hidden sources stay hidden."""
    names = report.get("reading", {}).get("source_labels", {})
    links = []
    for source in report["sources"]:
        if source["id"] not in ids or not source.get("show_public", True):
            continue
        label = names.get(source["id"], source["label"])
        short = label.split(" · ")[0]
        links.append(f'<a href="{text(source["url"])}" rel="noreferrer" title="{text(label)}">{text(short)}</a>' if source["url"] else text(short))
    return f'<span class="cite">출처 {" · ".join(links)}</span>' if links else ""


def mood_scale(level: str, note: str = "") -> str:
    cells = "".join(f'<span class="m-{key}{" on" if key == level else ""}"></span>' for key in MOODS)
    names = "".join(f'<b>{name}</b>' if key == level else f'<span>{name}</span>' for key, name in MOODS.items())
    return (f'<div class="mood" role="img" aria-label="시장 분위기 {MOODS[level]}. 작성자 해석이며 지표가 아님">'
            f'<div class="mood-head"><b>시장 분위기</b><span>작성자 해석 · 지표 아님</span></div>'
            f'<div class="mood-scale">{cells}</div><div class="mood-names">{names}</div>'
            + (f'<p>{text(note)}</p>' if note else "") + '</div>')


def reading_section(report: dict) -> str:
    """시장 읽기: one plain judgement, the mood, why, a sourced precedent and what to watch."""
    view = report.get("reading", {}).get("view")
    head = '<section class="block reading" id="reading" aria-labelledby="reading-title"><div class="block-head"><h2 id="reading-title">시장 읽기</h2>'
    if view:
        parts = [head + '<small>브리핑 해석 · 검증 전</small></div>',
                 f'<p class="reading-headline">{text(view["headline"])}</p>',
                 mood_scale(view["mood"]["level"], view["mood"]["note"]),
                 '<div class="drivers"><h3>왜 이런 분위기일까</h3>']
        for n, item in enumerate(view["drivers"], 1):
            parts.append(f'<div class="driver"><span class="num" aria-hidden="true">{n}</span><p><b>{text(item["title"])}</b> '
                         f'{text(item["text"])} {cite(report, item["sources"])}</p></div>')
        parts.append('</div>')
        for case in view["history"]:
            parts.append(f'<article class="history"><span class="eyebrow">과거엔 어땠나 · 참고 사례</span><h3>{text(case["title"])}</h3><dl>'
                         + "".join(f'<dt>{label}</dt><dd>{text(case[key])}</dd>' for label, key in (("그날", "then"), ("다음 날", "next"), ("그 뒤", "after")))
                         + f'</dl><p class="difference"><b>이번과 다른 점</b> · {text(case["difference"])}</p>'
                         f'<p class="history-note">{cite(report, case["sources"])}<span>같은 흐름이 반복된다는 뜻은 아니에요</span></p></article>')
        parts.append(f'<div class="paths"><h3>이렇게 보면 돼요</h3>'
                     f'<p class="path good"><b>좋은 쪽</b> · {text(view["paths"]["good"])}</p>'
                     f'<p class="path caution"><b>조심할 쪽</b> · {text(view["paths"]["caution"])}</p></div>')
        parts.append(f'<p class="view-meta">출처 기반 해석이며 검증 전이에요 · 확률이나 목표가는 아니에요 · {view_written(report)}</p></section>')
        return "".join(parts)
    entry = representative(report)
    if entry is None:
        return ""
    # Older editions: the same judgement in a sentence per period, without badges or distances.
    periods = labels(report)
    parts = [head + '<small>이전 형식 요약 · 검증 전</small></div><div class="legacy-reading">']
    for key in ("d1", "d5"):
        item = entry["outlook"][key]
        parts.append(f'<p><b>{periods[key]}</b> {PLAIN[item["direction"]]}.<span>{text(item["invalidation"])}</span></p>')
    parts.append(f'</div><details><summary class="more">근거·반대 요인</summary><div class="detail-body">{outlook_details(entry, report)}</div></details>')
    parts.append(outlook_notice(report) + '</section>')
    return "".join(parts)


def heat_class(stock: dict) -> str:
    if stock["direction"] not in ("up", "down"):
        return "heat-flat"
    size = abs(number(stock["percent"]))
    level = 4 if size >= 15 else 3 if size >= 8 else 2 if size >= 4 else 1
    return f'heat-{stock["direction"]}-{level}'


def anchor(value: str) -> str:
    return "stock-" + re.sub(r"[^A-Za-z0-9_-]", "-", value)


def stocks_section(report: dict) -> str:
    reading = report.get("reading", {})
    stocks = report["stocks"]
    ranked = sorted(stocks, key=lambda s: number(s["percent"]) if s["direction"] in ("up", "down", "flat") else -1e9, reverse=True)
    widest = max(stocks, key=lambda s: abs(number(s["percent"])) if s["direction"] in ("up", "down") else -1)
    venues = sorted({stock["session"].split(" ")[0] for stock in stocks})
    parts = [f'<section class="block" id="stocks" aria-labelledby="stocks-title"><div class="block-head"><h2 id="stocks-title">종목</h2>'
             f'<small>전일 대비</small></div><div class="heatmap" aria-label="종목 등락 한눈에 보기">']
    cells = 0
    for stock in ranked:
        wide = stock is widest and widest["direction"] in ("up", "down") and len(stocks) > 1
        cells += 2 if wide else 1
        parts.append(f'<a class="{heat_class(stock)}{" wide" if wide else ""}" href="#{anchor(stock["ticker"])}">'
                     f'<span>{text(stock["name"])}</span><b>{change_text(stock)}</b></a>')
    if cells % 3:
        parts.append(f'<span class="legend" style="grid-column:span {3 - cells % 3}">진할수록 변동 큼</span>')
    parts.append('</div>')
    for stock in stocks:
        short = reading.get("stocks", {}).get(stock["ticker"], {})
        currency = "" if stock["currency"] == "KRW" else f'<small>{text(stock["currency"])}</small>'
        parts.append(f'<details class="stock" id="{anchor(stock["ticker"])}"><summary><span class="stock-line">'
                     f'<span class="stock-name">{text(stock["name"])}<small>{text(stock["ticker"])}</small></span>'
                     f'<span class="stock-quote"><span class="price">{text(stock["price"])}{currency}</span>'
                     f'<b class="{text(stock["direction"])}">{change_text(stock)}</b></span></span>'
                     + range_bar(stock)
                     + f'<span class="stock-reason">{text(short.get("reason", stock["reason"]))}</span>'
                     + (f'<span class="stock-reason missing">{text(stock["missing_reason"])}</span>' if stock["direction"] == "missing" else "")
                     + '</summary><div class="detail-body">')
        parts.append(f'<p><span class="label">확인선</span> {text(short.get("watch", stock["watch"]))}</p>')
        parts.append(f'<p>{text(stock["session"])} · {text(kst(stock["as_of"]))}'
                     + (f' · 전일 대비 {text(stock["delta"])} {text(stock["currency"])}' if stock["direction"] != "missing" else "") + '</p>')
        if short.get("reason") and short["reason"] != stock["reason"]:
            parts.append(f'<p>{text(stock["reason"])}</p>')
        if short.get("watch") and short["watch"] != stock["watch"]:
            parts.append(f'<p>{text(stock["watch"])}</p>')
        parts.append('</div></details>')
    return "".join(parts) + '</section>'


def stories_section(report: dict) -> str:
    short_issues = report.get("reading", {}).get("issues", [])
    parts = [f'<section class="block" id="issues" aria-labelledby="issues-title"><div class="block-head"><h2 id="issues-title">이야기 {len(report["issues"])}</h2>'
             '<small>눌러서 자세히</small></div>']
    for n, issue in enumerate(report["issues"]):
        short = short_issues[n] if n < len(short_issues) else {}
        preview = short.get("preview") or short.get("meaning") or paragraphs(issue["fact"])[0]
        minor = " minor" if n >= 3 else ""
        parts.append(f'<details class="story{minor}"><summary><span class="num">{n + 1}</span><span><h3>{text(short.get("title", issue["title"]))}</h3>'
                     f'<p class="preview">{text(preview)}</p></span><span class="mark" aria-hidden="true">+</span></summary>'
                     '<div class="detail-body">' + bullet_list(paragraphs(issue["fact"]))
                     + (f'<p><span class="label">시장 의미</span> {text(short["meaning"])}</p>' if short.get("meaning") and short["meaning"] != preview else "")
                     + '</div></details>')
    return "".join(parts) + '</section>'


def parse_when(label: str, year: int):
    """(date, time text) from labels like '2026-11-12 09:00 KST' or '확인 순서: 11-11 장후'."""
    found = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}:\d{2}))?", label)
    if found:
        return date(int(found[1]), int(found[2]), int(found[3])), found[4] or ""
    found = re.search(r"(?<!\d)(\d{1,2})-(\d{2})(?!\d)\s*(장전|장후|장중|개장|마감)?", label)
    if found:
        try:
            return date(year, int(found[1]), int(found[2])), found[3] or ""
        except ValueError:
            return None, ""
    return None, ""


def calendar_groups(report: dict) -> list[dict]:
    short_checks = report.get("reading", {}).get("next_checks", [])
    today = datetime.fromisoformat(report["queried_at"]).date()
    dated, anytime = {}, []
    for n, check in enumerate(report["next_checks"]):
        short = short_checks[n] if n < len(short_checks) else {}
        day, when = parse_when(check["label"], today.year)
        item = {"n": n, "check": check, "short": short, "when": when,
                "rest": "" if day else re.sub(r"^확인 순서\s*:\s*", "", check["label"])}
        (dated.setdefault(day, []) if day else anytime).append(item)
    groups = []
    for day in sorted(dated):
        relative = {0: "오늘", 1: "내일"}.get((day - today).days, "")
        events = sorted(dated[day], key=lambda item: (item["when"] == "" or not re.match(r"\d", item["when"]), item["when"], item["n"]))
        groups.append({"date": day, "day": str(day.day), "sub": WEEKDAYS[day.weekday()] + (f" · {relative}" if relative else ""),
                       "today": day == today, "events": events})
    if anytime:
        groups.append({"date": None, "day": "수시", "sub": "", "today": False, "events": anytime})
    return groups


def calendar_section(report: dict) -> str:
    parts = [f'<section class="block" id="calendar" aria-labelledby="calendar-title"><div class="block-head"><h2 id="calendar-title">달력</h2>'
             f'<small>다음 확인 {len(report["next_checks"])}</small></div>']
    for group in calendar_groups(report):
        css = " today" if group["today"] else " anytime" if group["date"] is None else ""
        parts.append(f'<div class="day"><div class="day-date{css}"><b>{text(group["day"])}</b><span>{text(group["sub"])}</span></div><div class="events">')
        for item in group["events"]:
            check, short = item["check"], item["short"]
            when = item["when"] or item["rest"]
            parts.append(f'<div class="event"><p class="event-title">' + (f'<span class="when">{text(when)}</span>' if when else "")
                         + f'{text(short.get("title", check["title"]))}</p><p>{text(short.get("detail", check["detail"]))}</p>'
                         + '<details><summary class="more">일정 근거·조건</summary><div class="detail-body">'
                         + f'<p><span class="label">표기</span> {text(check["label"])}</p>'
                         + (f'<p>{text(check["detail"])}</p>' if short.get("detail") and short["detail"] != check["detail"] else "")
                         + '</div></details></div>')
        parts.append('</div></div>')
    return "".join(parts) + '</section>'


def evidence_section(report: dict, prefix: str) -> str:
    reading = report.get("reading", {})
    sources = [source for source in report["sources"] if source.get("show_public", True)]
    labels_map = reading.get("source_labels", {})
    parts = ['<section class="evidence" aria-label="근거와 출처">',
             '<details><summary class="more">판단 기준·계산 근거</summary><div class="detail-body">',
             bullet_list(reading.get("interpretation_points", paragraphs(report["interpretation"]))),
             f'<p>{text(report["interpretation"])}</p><p>{text(report["calculation_notes"])}</p></div></details>',
             f'<details><summary class="more">출처 {len(sources)}</summary><ul class="source-list">']
    for source in sources:
        label = labels_map.get(source["id"], source["label"])
        link = f'<a href="{text(source["url"])}" rel="noreferrer">{text(label)} ↗</a>' if source["url"] else text(label)
        parts.append(f'<li id="source-{text(source["id"])}">{link}</li>')
    parts.append(f'</ul></details><p class="fineprint">자료 조회 {text(kst(report["queried_at"]))} · '
                 f'<a href="{prefix}/reports/{report["id"]}/">이 회차 고유 주소</a> · '
                 f'<button type="button" class="link-btn" data-image-action="save" hidden>카드 이미지 저장</button></p></section>')
    return "".join(parts)


def reading_payload(report: dict):
    """The card copy of 시장 읽기: words only, no source notes, no counts."""
    view = report.get("reading", {}).get("view")
    if view:
        return {"headline": view["headline"], "mood": view["mood"]["level"], "mood_label": MOODS[view["mood"]["level"]],
                "mood_note": view["mood"]["note"], "drivers": [{key: item[key] for key in ("title", "text")} for item in view["drivers"]],
                "history": [{key: case[key] for key in ("title", "then", "next", "after", "difference")} for case in view["history"]],
                "paths": dict(view["paths"]), "written": view_written(report).replace(".", "/", 1)}
    entry = representative(report)
    if entry is None:
        return None
    periods = labels(report)
    meta = report["reading"]["outlook"]
    return {"legacy": [{"label": periods[key], "plain": PLAIN[entry["outlook"][key]["direction"]],
                        "condition": entry["outlook"][key]["invalidation"]} for key in ("d1", "d5")],
            "written": timestamp(meta["estimated_at"]).strftime("%m/%d %H:%M") + (" 추가" if meta["added_later"] else " 작성"),
            "note": meta["note"]}


def image_payload(report: dict, prefix: str) -> dict:
    """Share only public, concise report fields; never export hidden evidence."""
    validate_outlook(report)
    reading = report.get("reading", {})
    short_issues = reading.get("issues", [])
    session = {"pre": "장전", "close": "정규장 마감", "intraday": "장중"}[report["session"]]
    issues = []
    for n, issue in enumerate(report["issues"]):
        short = short_issues[n] if n < len(short_issues) else {}
        issues.append({"title": short.get("title", issue["title"]),
                       "preview": short.get("preview") or short.get("meaning") or paragraphs(issue["fact"])[0]})
    stocks = []
    for stock in report["stocks"]:
        short = reading.get("stocks", {}).get(stock["ticker"], {})
        stocks.append({key: stock[key] for key in ("name", "ticker", "price", "currency", "percent", "direction", "session")} | {
            "as_of": kst(stock["as_of"]), "reason": short.get("reason", stock["reason"]),
            "watch": short.get("watch", stock["watch"]), "missing_reason": stock.get("missing_reason", ""),
            "range": stock.get("range")})
    calendar = []
    for group in calendar_groups(report):
        calendar.append({"day": group["day"], "sub": group["sub"], "today": group["today"], "events": [
            {"when": item["when"] or item["rest"], "label": item["check"]["label"],
             "title": item["short"].get("title", item["check"]["title"]),
             "detail": item["short"].get("detail", item["check"]["detail"])}
            for item in group["events"]]})
    return {
        "id": report["id"], "title": report["title"], "is_test": report["is_test"],
        "market": report["market"], "session": session, "edition": edition_label(report),
        "date_label": day_label(date.fromisoformat(report["market_date"])) + (" · 뉴욕" if report["market"] == "US" else ""),
        "as_of": kst(report["as_of"]), "queried_at": kst(report["queried_at"]),
        "headline": reading.get("headline", report["summary"]),
        "summary_points": reading.get("summary_points", paragraphs(report["summary_detail"])),
        "indices": [{key: item[key] for key in ("name", "value", "unit", "percent", "direction")} |
                    {"missing_reason": item.get("missing_reason", ""), "range": item.get("range")} for item in report["indices"]],
        "fx": {key: report["fx"][key] for key in ("label", "value", "unit", "delta", "direction", "session")} |
              {"as_of": kst(report["fx"]["as_of"])},
        "notices": reading.get("notices") or [report["venue"], report["fx"]["session"]],
        "key_figure": reading.get("key_figure"), "reading": reading_payload(report),
        "issues": issues, "stocks": stocks, "calendar": calendar,
        "next_checks": [{"label": item["label"], "title": (reading.get("next_checks", [])[n] if n < len(reading.get("next_checks", [])) else {}).get("title", item["title"]),
                         "detail": (reading.get("next_checks", [])[n] if n < len(reading.get("next_checks", [])) else {}).get("detail", item["detail"])}
                        for n, item in enumerate(report["next_checks"])],
        "sources": [reading.get("source_labels", {}).get(source["id"], source["label"])
                    for source in report["sources"] if source.get("show_public", True)],
        "report_path": f'{prefix}/reports/{report["id"]}/',
    }


def image_controls(report: dict, prefix: str) -> str:
    # JSON lives in a non-executable script; escape HTML delimiters, not JSON quotes.
    payload = json.dumps(image_payload(report, prefix), ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f'''<dialog id="image-dialog" aria-labelledby="image-dialog-title">
<div class="image-dialog-head"><h2 id="image-dialog-title">카드 이미지</h2><button type="button" id="image-close" aria-label="카드 이미지 닫기">닫기</button></div>
<p id="image-status" role="status" aria-live="polite">카드를 만들고 있어요…</p>
<div class="image-dialog-actions"><button type="button" id="image-share" disabled>모두 공유 ↗</button><button type="button" id="image-retry" class="secondary" hidden>다시 만들기</button></div>
<div class="image-previews" id="image-previews"></div>
<p class="image-help">아이폰: 공유 창에서 카카오톡이나 ‘이미지 저장’을 고르세요. 카드를 길게 눌러 한 장씩 저장할 수도 있어요.</p>
</dialog>
<script type="application/json" id="brief-image-data">{payload}</script>'''


def render_report(report: dict, prefix: str, strip: str = "") -> str:
    validate_outlook(report)
    validate_extras(report)
    reading = report.get("reading", {})
    parts = [masthead(report, prefix), strip]
    if report["is_test"]:
        parts.append('<aside class="test-banner"><strong>TEST</strong>레이아웃 확인용 자료 · 실제 시세 아님</aside>')
    written = f'작성 {short_time(report.get("revision_at") or report["queried_at"])}'
    dek = " ".join(reading.get("summary_points", paragraphs(report["summary_detail"])))
    parts.append(f'<section class="lead"><p class="kicker">{text(edition_label(report))} · {text(kst(report["as_of"]))} 기준 · {written}</p>'
                 f'<h1>{text(reading.get("headline", report["summary"]))}</h1><p class="dek">{text(dek)}</p></section>')
    parts.append(band(report))
    parts.append(key_figure(report))
    # Session distinctions and uncertainty always stay visible, never in details.
    notices = reading.get("notices") or [report["venue"], report["fx"]["session"]]
    parts.append('<aside class="notices" aria-label="자료 기준과 유의사항">' + "".join(f'<p>{text(item)}</p>' for item in notices) + '</aside>')
    parts.append(reading_section(report))
    parts.append(stocks_section(report))
    parts.append(stories_section(report))
    parts.append(calendar_section(report))
    parts.append(evidence_section(report, prefix))
    parts.append(image_controls(report, prefix))
    return "\n".join(part for part in parts if part)


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
        validate_extras(report)
        require(file.stem == report["id"], "Source filename must match report ID")
        require(report["id"] not in ids, "Duplicate report ID")
        ids.add(report["id"])
        reports.append(report)
    require(bool(reports), "No reports to publish")
    # Order by when each briefing was actually written (queried_at), not by its data
    # basis time: a US pre-market report uses the prior close (06:00 KST) as as_of but
    # is written around 23:00 KST, after that day's Korean reports.
    def written(r: dict) -> tuple:
        return (datetime.fromisoformat(r["queried_at"]), datetime.fromisoformat(r.get("revision_at", r["as_of"])),
                datetime.fromisoformat(r["as_of"]), r["id"])
    return sorted(reports, key=written, reverse=True)


def build(output: Path, data_dir: Path = ROOT / "data/reports") -> None:
    reports = load_reports(data_dir)
    # Validate every source before writing any output. Never delete previous reports.
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets/fonts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "assets/style.css", output / "assets/style.css")
    shutil.copyfile(ROOT / "assets/brief-image.js", output / "assets/brief-image.js")
    for font in sorted((ROOT / "assets/fonts").iterdir()):
        shutil.copyfile(font, output / "assets/fonts" / font.name)
    image_version = hashlib.sha256((ROOT / "assets/brief-image.js").read_bytes()).hexdigest()[:16]
    style_version = hashlib.sha256((ROOT / "assets/style.css").read_bytes()).hexdigest()[:16]
    page = Template((ROOT / "templates/page.html").read_text(encoding="utf-8"))

    def write_page(path: str, title: str, content: str, prefix: str) -> None:
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page.substitute(title=text(title), description=text("TEST · 레이아웃 확인용 자료 · 실제 시세 아님" if 'TEST' in title else title), asset_prefix=prefix, image_version=image_version, style_version=style_version, content=content), encoding="utf-8")

    # One edition per market day and slot; reports are newest-first, so keep the first seen.
    day_reports = {}
    for report in reports:
        if not report["is_test"]:
            day_reports.setdefault((report["market_date"], report["market"], report["session"]), report)
    manifest = []
    for report in reports:
        report_path = f'reports/{report["id"]}/index.html'
        write_page(report_path, report["title"], render_report(report, "../..", day_strip(report, day_reports, "../..")), "../..")
        manifest.append({key: report[key] for key in ("id", "is_test", "market", "session", "market_date", "title", "summary", "as_of", "queried_at") } | {"path": f'reports/{report["id"]}/'})
    live_reports = [report for report in reports if not report["is_test"]]
    latest = (live_reports or reports)[0]
    recent = [f'<li><a href="reports/{item["id"]}/"><span class="slot">{text(edition_label(item))}<small>{text(item["market_date"][5:].replace("-", "."))}</small></span>'
              f'<span class="headline">{text(item.get("reading", {}).get("headline", item["summary"]))}</span></a></li>'
              for item in reports if item["id"] != latest["id"]][:8]
    history = ('<section class="archive-day" aria-label="최근 브리핑"><h2>최근 브리핑</h2><ul>' + ''.join(recent)
               + '</ul><p class="fineprint"><a href="archive/">날짜별 보관함 전체 보기</a></p></section>') if recent else ''
    write_page("index.html", latest["title"], render_report(latest, ".", day_strip(latest, day_reports, ".")) + history, ".")
    write_page("archive/index.html", "날짜별 보관함 · 코스트 브리핑", archive_page(reports), "..")
    (output / "manifest.json").write_text(json.dumps({"version": 1, "latest_id": latest["id"], "reports": manifest}, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    (output / ".nojekyll").touch()
    print(f"Built {len(reports)} report(s) → {output}")


def archive_page(reports: list[dict]) -> str:
    order = {(market, session): n for n, (market, session, _) in enumerate(SLOTS)}
    days = {}
    for report in reports:
        key = "TEST" if report["is_test"] else report["market_date"]
        days.setdefault(key, []).append(report)
    parts = [f'<header class="masthead"><a class="icon-btn" href="../index.html" aria-label="최신 브리핑">{ICON_BACK}</a>'
             '<div class="brand"><a href="../index.html">코스트 브리핑</a><span>날짜별 보관함</span></div><span></span></header>',
             f'<p class="archive-intro">{len(reports)}개 회차 · 시장 날짜별 · 한국 장전 → 한국 마감 → 미국 장전 → 미국 마감</p>']
    for key in sorted((k for k in days if k != "TEST"), reverse=True) + (["TEST"] if "TEST" in days else []):
        items = sorted(days[key], key=lambda r: (order.get((r["market"], r["session"]), 9), r["queried_at"]))
        title = "TEST · 레이아웃 확인용" if key == "TEST" else day_label(date.fromisoformat(key))
        parts.append(f'<section class="archive-day"><h2>{text(title)}</h2><ul>')
        for report in items:
            headline = report.get("reading", {}).get("headline", report["summary"])
            parts.append(f'<li><a href="../reports/{report["id"]}/"><span class="slot">{text(edition_label(report))}<small>{text(short_time(report["queried_at"]))}</small></span>'
                         f'<span class="headline">{text(headline)}<span>{text(report["title"])}</span></span></a></li>')
        parts.append('</ul></section>')
    return "".join(parts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "public")
    args = parser.parse_args()
    build(args.output)
