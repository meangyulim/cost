"""Collect approved KRX daily APIs and compute descriptive briefing inputs.

The credential is read only from KRX_API_KEY. Raw API rows remain in memory;
the output contains derived metrics, provenance and explicit limitations.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import statistics
import sys
import urllib.error
import urllib.request

KST = timezone(timedelta(hours=9))
BASE = "https://data-dbg.krx.co.kr/svc/apis/"
INDEX_APIS = {"KOSPI": "idx/kospi_dd_trd", "KOSDAQ": "idx/kosdaq_dd_trd", "KRX": "idx/krx_dd_trd"}
SNAPSHOT_APIS = {"KOSPI": "sto/stk_bydd_trd", "KOSDAQ": "sto/ksq_bydd_trd", "ETF": "etp/etf_bydd_trd"}
ALLOWED = set(INDEX_APIS.values()) | set(SNAPSHOT_APIS.values())
ROOT = Path(__file__).resolve().parents[1]


class DataError(ValueError):
    """Safe-to-print failure; never includes a response body or credential."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # AUTH_KEY must never follow a redirect to another host.
        return None


def number(value: object) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def percent(now: float, before: float) -> float | None:
    return round((now / before - 1) * 100, 4) if before > 0 else None


class Client:
    def __init__(self, key: str):
        if not key.strip():
            raise DataError("KRX_API_KEY가 없습니다. GitHub Actions Secrets에 등록하세요.")
        self._key = key.strip()

    def fetch(self, api: str, day: date) -> list[dict]:
        if api not in ALLOWED:
            raise DataError("승인 목록에 없는 API입니다.")
        req = urllib.request.Request(BASE + api + "?basDd=" + day.strftime("%Y%m%d"),
                                     headers={"AUTH_KEY": self._key, "Accept": "application/json"})
        try:
            # Each call has its own opener for concurrent use; TLS stays enabled.
            with urllib.request.build_opener(NoRedirect).open(req, timeout=25) as response:
                payload = json.loads(response.read(5_000_001))
        except urllib.error.HTTPError as error:
            raise DataError(f"{api} {day}: HTTP {error.code}; 키 값과 응답 본문은 출력하지 않습니다.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise DataError(f"{api} {day}: 네트워크 오류") from None
        except (ValueError, UnicodeError):
            raise DataError(f"{api} {day}: JSON 형식 오류") from None
        rows = payload.get("OutBlock_1") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DataError(f"{api} {day}: 응답 구조 오류")
        expected = day.strftime("%Y%m%d")
        if any(row.get("BAS_DD") != expected for row in rows):
            raise DataError(f"{api} {day}: 요청일과 데이터 기준일 불일치")
        return rows


def collect(client: Client, end: date, sessions: int) -> tuple[dict, dict]:
    # Weekdays are only candidates. Empty responses, not weekday arithmetic,
    # determine which sessions actually have data. No formal calendar inference.
    candidates = [end - timedelta(days=n) for n in range(sessions * 2 + 30)
                  if (end - timedelta(days=n)).weekday() < 5]
    kospi = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for start in range(0, len(candidates), 10):
            batch = candidates[start:start + 10]
            for day, rows in zip(batch, pool.map(lambda d: client.fetch(INDEX_APIS["KOSPI"], d), batch)):
                if rows:
                    kospi[day] = rows
            if len(kospi) >= sessions:
                break
        days = sorted(kospi, reverse=True)[:sessions]
        if len(days) < sessions:
            raise DataError(f"지수 이력이 부족합니다: {len(days)}/{sessions} 거래일")
        if (end - days[0]).days > 14:
            raise DataError("최신 데이터가 요청일보다 14일 이상 오래됐습니다.")
        indices = {"KOSPI": {d: kospi[d] for d in days}, "KOSDAQ": {}, "KRX": {}}
        tasks = [(group, day) for group in ("KOSDAQ", "KRX") for day in days]
        for (group, day), rows in zip(tasks, pool.map(lambda t: client.fetch(INDEX_APIS[t[0]], t[1]), tasks)):
            if not rows:
                raise DataError(f"{group} {day}: 다른 지수와 거래일 이력이 일치하지 않습니다.")
            indices[group][day] = rows
        snapshots = {group: {} for group in SNAPSHOT_APIS}
        tasks = [(group, day) for group in SNAPSHOT_APIS for day in days[:6]]
        for (group, day), rows in zip(tasks, pool.map(lambda t: client.fetch(SNAPSHOT_APIS[t[0]], t[1]), tasks)):
            if not rows:
                raise DataError(f"{group} {day}: 종목/ETF 데이터가 없습니다.")
            snapshots[group][day] = rows
    return indices, snapshots


def series_metrics(points: list[tuple[date, dict]], name: str) -> dict:
    points = sorted(points)
    values = [number(row.get("CLSPRC_IDX")) for _, row in points]
    if len(values) < 65 or any(value is None or value <= 0 for value in values):
        raise DataError(f"{name}: 65거래일 유효 종가가 필요합니다.")
    close = values[-1]
    ma20 = statistics.mean(values[-20:])
    ma60 = statistics.mean(values[-60:])
    prior_ma20 = statistics.mean(values[-25:-5])
    if close > ma20 > ma60 and ma20 > prior_ma20:
        trend = "상승 추세 조건 충족"
    elif close < ma20 < ma60 and ma20 < prior_ma20:
        trend = "하락 추세 조건 충족"
    else:
        trend = "혼조 / 추세 전환 확인 필요"
    return {"name": name, "history_sessions": len(values), "data_date": points[-1][0].isoformat(),
            "close": close, "daily_return_pct": number(points[-1][1].get("FLUC_RT")),
            "return_5_sessions_pct": percent(close, values[-6]),
            "return_20_sessions_pct": percent(close, values[-21]),
            "ma20": round(ma20, 4), "ma60": round(ma60, 4),
            "ma20_change_5_sessions_pct": percent(ma20, prior_ma20), "trend": trend}


def index_series(history: dict[date, list[dict]]) -> dict[str, list]:
    result = {}
    for day, rows in history.items():
        names = set()
        for row in rows:
            name = row.get("IDX_NM")
            if not isinstance(name, str) or not name or name in names:
                raise DataError(f"{day}: 지수명 누락 또는 중복")
            names.add(name)
            result.setdefault(name, []).append((day, row))
    return result


def traded(row: dict) -> bool:
    volume = number(row.get("ACC_TRDVOL"))
    return volume is not None and volume > 0


def turnover(rows: list[dict]) -> int:
    values = [number(row.get("ACC_TRDVAL")) for row in rows]
    if any(value is None or value < 0 for value in values):
        raise DataError("거래대금 누락 또는 오류: 합계를 계산하지 않습니다.")
    return round(sum(values))


def breadth(history: dict[date, list[dict]]) -> dict:
    days = sorted(history, reverse=True)
    rows = history[days[0]]
    eligible = [row for row in rows if traded(row)]
    returns = [number(row.get("FLUC_RT")) for row in eligible]
    valid = [value for value in returns if value is not None]
    if not valid:
        raise DataError("시장 폭을 계산할 유효 종목이 없습니다.")
    up, down, flat = (sum(test(value) for value in valid)
                      for test in (lambda x: x > 0, lambda x: x < 0, lambda x: x == 0))
    current_value = turnover(rows)
    previous_mean = statistics.mean(turnover(history[d]) for d in days[1:6])
    return {"rows": len(rows), "traded_rows": len(eligible), "valid_return_rows": len(valid),
            "excluded_nontraded_rows": len(rows) - len(eligible),
            "excluded_missing_return_rows": len(eligible) - len(valid),
            "advancing": up, "declining": down, "unchanged": flat,
            "advancing_share_pct": round(up / len(valid) * 100, 2),
            "advance_decline_ratio": round(up / down, 4) if down else None,
            "turnover_krw": current_value,
            "turnover_vs_previous_5_mean": round(current_value / previous_mean, 4) if previous_mean > 0 else None}


def etf_strength(history: dict[date, list[dict]]) -> list[dict]:
    days = sorted(history, reverse=True)
    current = {row["ISU_CD"]: row for row in history[days[0]]}
    before = {row["ISU_CD"]: row for row in history[days[5]]}
    ranked = []
    for code, row in current.items():
        # Leveraged/inverse ETFs are excluded from this directional comparison.
        if not traded(row) or any(word in row.get("ISU_NM", "") for word in ("레버리지", "인버스", "2X", "3X")):
            continue
        now, old = number(row.get("TDD_CLSPRC")), number(before.get(code, {}).get("TDD_CLSPRC"))
        if now is None or old is None or now <= 0 or old <= 0:
            continue
        trade_value = number(row.get("ACC_TRDVAL"))
        # Thinly traded funds can give a misleading ranking.
        if trade_value is None or trade_value < 1_000_000_000:
            continue
        ranked.append({"name": row.get("ISU_NM"), "code": code,
                       "return_5_sessions_pct": percent(now, old), "turnover_krw": round(trade_value)})
    return sorted(ranked, key=lambda item: item["return_5_sessions_pct"], reverse=True)[:5]


def analyze(indices: dict, snapshots: dict, requested_end: date, queried_at: str) -> dict:
    maps = {group: index_series(history) for group, history in indices.items()}
    benchmarks = {}
    for group, name in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        points = maps[group].get(name)
        if not points:
            raise DataError(f"{name}: 대표 지수가 없습니다.")
        benchmarks[group] = series_metrics(points, name)
    latest = max(indices["KOSPI"])
    markets = {group: breadth(snapshots[group]) for group in ("KOSPI", "KOSDAQ")}
    rank = []
    excluded = 0
    for name, points in maps["KRX"].items():
        if len(points) < 65 or max(day for day, _ in points) != latest:
            excluded += 1
            continue
        try:
            metrics = series_metrics(points, name)
        except DataError:
            excluded += 1
            continue
        metrics["excess_vs_kospi_20_sessions_pp"] = round(
            metrics["return_20_sessions_pct"] - benchmarks["KOSPI"]["return_20_sessions_pct"], 4)
        rank.append(metrics)
    rank.sort(key=lambda item: item["excess_vs_kospi_20_sessions_pp"], reverse=True)
    signals = []
    for group, benchmark in benchmarks.items():
        market = markets[group]
        spread = market["advancing_share_pct"]
        signals.append({"market": group, "trend": benchmark["trend"],
                        "breadth": "당일 상승 확산" if spread >= 60 else "당일 하락 확산" if spread <= 40 else "당일 종목 혼조",
                        "breadth_pct": spread,
                        "confirmation": "다음 종가의 20일선 유지 여부와 상승 종목 비율을 함께 확인"})
    return {"version": 1, "kind": "descriptive_daily_analysis", "source": "한국거래소 통계정보",
            "requested_end_date": requested_end.isoformat(), "data_date": latest.isoformat(),
            "queried_at": queried_at, "session": "daily", "benchmarks": benchmarks,
            "market_breadth": markets, "krx_series_strength": rank[:5],
            "excluded_krx_series": excluded, "etf_5_session_strength": etf_strength(snapshots["ETF"]),
            "signals": signals, "forecast_probability": None, "backtest_status": "not_validated",
            "methods": {"trend": "종가>MA20>MA60 및 MA20 상승이면 상승 조건, 반대이면 하락 조건, 나머지 혼조",
                        "returns": "5/20 거래일 전 종가 대비 단순 가격수익률; 배당·분할 보정 없음",
                        "breadth": "거래량>0이고 등락률이 유효한 종목 중 상승 종목 비율; 우선주 등 포함",
                        "turnover": "전체 제공 종목 거래대금 합계 / 직전 5 거래일 합계의 평균",
                        "series_strength": "KRX 지수 시리즈의 20거래일 가격수익률에서 코스피 수익률을 뺀 %p; 업종·테마 등 혼합",
                        "etf": "당일 거래대금 10억원 이상 ETF의 5거래일 가격수익률; 이름으로 레버리지·인버스 제외"},
            "limitations": ["일별 자료이며 장중 실시간 시세가 아닙니다. OpenAPI의 정확한 제공 시각은 확인되지 않았습니다.",
                            "데이터가 있는 날짜는 공식 거래일 달력 검증을 대신하지 않습니다.",
                            "추세 조건은 미래 상승 확률이 아닙니다. 예측 확률과 매매 신호는 백테스트 전 제공하지 않습니다.",
                            "가격수익률은 총수익률이 아니며 ETF 분배금과 분할 등에 왜곡될 수 있습니다.",
                            "거래대금은 순자금 유입이나 외국인·기관 순매수를 뜻하지 않습니다.",
                            "ETF의 상품 구조를 이름만으로 완전히 분류하지 못합니다. 주도 업종 판단 시 지수와 함께 확인하세요."]}


def save_result(result: dict, output: Path) -> None:
    # Do not allow analysis outputs to silently become Pages/report sources.
    resolved = output.resolve()
    for protected in (ROOT / "public", ROOT / "data/reports"):
        if resolved.is_relative_to(protected.resolve()):
            raise DataError("KRX 분석 결과는 public 또는 data/reports에 직접 저장할 수 없습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default="", help="YYYY-MM-DD; blank means yesterday in KST")
    parser.add_argument("--sessions", type=int, default=65)
    parser.add_argument("--output", type=Path, default=Path("krx-output/analysis.json"))
    args = parser.parse_args()
    try:
        today = datetime.now(KST).date()
        end = date.fromisoformat(args.end_date) if args.end_date else today - timedelta(days=1)
        if end > today or not 65 <= args.sessions <= 250:
            raise DataError("기준일은 오늘 이하, 이력은 65~250 거래일이어야 합니다.")
        client = Client(os.environ.get("KRX_API_KEY", ""))
        started = datetime.now(KST).isoformat(timespec="seconds")
        indices, snapshots = collect(client, end, args.sessions)
        result = analyze(indices, snapshots, end, datetime.now(KST).isoformat(timespec="seconds"))
        result["collection_started_at"] = started
        save_result(result, args.output)
        print(f"KRX 분석 완료: 기준일 {result['data_date']}, {args.sessions} 거래일 이력. 키·원시 응답은 저장하지 않았습니다.")
        return 0
    except (DataError, ValueError) as error:
        # Unexpected server exceptions are never printed with raw request data.
        print(f"KRX 분석 실패: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
