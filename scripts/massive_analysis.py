"""Fetch US daily briefing inputs. Credentials and raw universes stay in memory."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = {'SPY': '미국 대형주', 'QQQ': '나스닥100', 'DIA': '다우30', 'IWM': '미국 소형주'}
SECTORS = {'SOXX': '반도체', 'XLK': '정보기술', 'XLF': '금융', 'XLE': '에너지',
           'XLV': '헬스케어', 'XLI': '산업재', 'XLU': '유틸리티', 'XLY': '경기소비재',
           'XLP': '필수소비재', 'XLB': '소재', 'XLRE': '부동산', 'XLC': '커뮤니케이션'}


class DataError(ValueError):
    """Sanitized failure: never print response bodies, URLs or credentials."""


class RecencyError(DataError):
    """The requested date is newer than this subscription allows."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def numeric(value):
    if isinstance(value, bool):
        raise DataError('잘못된 숫자입니다.')
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise DataError('숫자가 누락됐습니다.') from None
    if not math.isfinite(result):
        raise DataError('유한한 숫자가 필요합니다.')
    return result


def pct(now, before):
    if before <= 0:
        raise DataError('비교 가격이 0 이하입니다.')
    return round((now / before - 1) * 100, 4)


def watch_tickers(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 7:
        raise DataError('관찰 티커는 1~7개 목록이어야 합니다.')
    if any(not isinstance(t, str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', t) for t in value):
        raise DataError('잘못된 관찰 티커입니다.')
    return list(dict.fromkeys(value))


class Client:
    def __init__(self, key, interval=13):
        if not isinstance(key, str) or not key.strip():
            raise DataError('MASSIVE_API_KEY를 GitHub Actions Secrets에 등록하세요.')
        self._key = key.strip()
        self.interval = interval
        self.last_request = None
        self.requests = 0

    def fetch(self, path, params=None):
        if not (re.fullmatch(r'/v2/aggs/ticker/[A-Z][A-Z0-9.-]{0,14}/range/1/day/\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}', path)
                or re.fullmatch(r'/v2/aggs/grouped/locale/us/market/stocks/\d{4}-\d{2}-\d{2}', path)
                or re.fullmatch(r'/v1/open-close/[A-Z][A-Z0-9.-]{0,14}/\d{4}-\d{2}-\d{2}', path)):
            raise DataError('허용되지 않은 API 경로입니다.')
        params = params or {}
        if set(params) - {'adjusted', 'sort', 'limit', 'include_otc'}:
            raise DataError('허용되지 않은 조회 인수입니다.')
        url = 'https://api.massive.com' + path + '?' + urllib.parse.urlencode(params)
        for attempt in range(3):
            if self.last_request is not None:
                time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            self.requests += 1
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self._key,
                                                       'Accept': 'application/json'})
            try:
                with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
                    payload = json.loads(response.read(12_000_001))
            except urllib.error.HTTPError as error:
                # Inspect only to classify subscription recency; never log it.
                try:
                    message = str(json.loads(error.read(20_000)).get('message', '')).lower()
                except (ValueError, AttributeError):
                    message = ''
                if error.code == 403 and ('timeframe' in message or 'data this recent' in message):
                    raise RecencyError('해당 날짜 자료가 아직 허용되지 않습니다.') from None
                if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(60 if error.code == 429 else 2 ** attempt)
                    continue
                raise DataError(f'미국 일별 API HTTP {error.code}; 응답 본문은 생략합니다.') from None
            except (urllib.error.URLError, OSError, TimeoutError):
                if attempt < 2:
                    continue
                raise DataError('미국 일별 API 네트워크 오류입니다.') from None
            except (ValueError, UnicodeError):
                raise DataError('미국 일별 API JSON 오류입니다.') from None
            if not isinstance(payload, dict) or payload.get('status') not in ('OK', 'DELAYED'):
                raise DataError('미국 일별 API 응답 상태가 유효하지 않습니다.')
            if payload.get('next_url'):
                raise DataError('응답이 잘렸습니다. 부분 자료로 계산하지 않습니다.')
            return payload
        raise DataError('수집에 실패했습니다.')

    def bars(self, ticker, end):
        start = end - timedelta(days=150)
        payload = self.fetch(f'/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}',
                             {'adjusted': 'true', 'sort': 'asc', 'limit': 5000})
        if payload.get('ticker') != ticker or payload.get('adjusted') is not True:
            raise DataError('티커 또는 분할 보정 상태가 다릅니다.')
        return validate_bars(payload.get('results', []), start, end)


def validate_bars(rows, start, end):
    if not isinstance(rows, list):
        raise DataError('일별 자료 목록이 유효하지 않습니다.')
    seen = set()
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise DataError('일별 행이 유효하지 않습니다.')
        try:
            day = datetime.fromtimestamp(numeric(row.get('t')) / 1000, NY).date()
        except (OverflowError, OSError):
            raise DataError('일별 시각이 유효하지 않습니다.') from None
        close, volume = numeric(row.get('c')), numeric(row.get('v'))
        if not start <= day <= end or day in seen or close <= 0 or volume < 0:
            raise DataError('일별 날짜·가격·거래량이 유효하지 않습니다.')
        seen.add(day)
        result.append((day, close, volume))
    return sorted(result)


def metrics(ticker, points, name):
    if len(points) < 65:
        raise DataError(f'{ticker}: 65거래일 이력이 필요합니다.')
    points = points[-65:]
    values = [x[1] for x in points]
    last = values[-1]
    ma20, ma60 = statistics.mean(values[-20:]), statistics.mean(values[-60:])
    prior_ma20 = statistics.mean(values[-25:-5])
    trend = ('상승 추세 조건 충족' if last > ma20 > ma60 and ma20 > prior_ma20 else
             '하락 추세 조건 충족' if last < ma20 < ma60 and ma20 < prior_ma20 else '혼조')
    prior_volume = statistics.mean(x[2] for x in points[-6:-1])
    return {'ticker': ticker, 'name': name, 'data_date': points[-1][0].isoformat(),
            'history_sessions': len(points), 'currency': 'USD', 'price_basis': 'split_adjusted_daily_aggregate',
            'close': last, 'daily_return_pct': pct(last, values[-2]),
            'return_5_sessions_pct': pct(last, values[-6]), 'return_20_sessions_pct': pct(last, values[-21]),
            'ma20': round(ma20, 4), 'ma60': round(ma60, 4), 'trend': trend,
            'volume_ratio_previous_5': round(points[-1][2] / prior_volume, 4) if prior_volume else None}


def universe(rows, day):
    if not isinstance(rows, list) or not rows:
        raise DataError('전체 일별 자료가 없습니다.')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('T'), str) or row['T'] in result:
            raise DataError('전체 자료의 티커가 누락 또는 중복됐습니다.')
        when = datetime.fromtimestamp(numeric(row.get('t')) / 1000, NY).date()
        if when != day or row.get('otc'):
            raise DataError('전체 자료의 기준일 또는 OTC 범위가 다릅니다.')
        close, volume = numeric(row.get('c')), numeric(row.get('v'))
        if close <= 0 or volume < 0:
            raise DataError('전체 자료의 가격·거래량이 유효하지 않습니다.')
        result[row['T']] = (close, volume)
    return result


def breadth(current, previous):
    paired = [t for t in current if t in previous and current[t][1] > 0 and previous[t][1] > 0]
    if not paired:
        raise DataError('시장 폭의 비교 가능한 증권이 없습니다.')
    up = sum(current[t][0] > previous[t][0] for t in paired)
    down = sum(current[t][0] < previous[t][0] for t in paired)
    return {'scope': 'OTC 제외 전체 증권; ETF·우선주·워런트 등 포함, 보통주만의 시장 폭 아님',
            'current_rows': len(current), 'paired_traded_rows': len(paired),
            'excluded_current_rows': len(current) - len(paired), 'advancing': up, 'declining': down,
            'unchanged': len(paired) - up - down, 'advancing_share_pct': round(up / len(paired) * 100, 2)}


def collect(client, requested_end, watch):
    history = None
    for offset in range(15):
        candidate = requested_end - timedelta(days=offset)
        try:
            history = client.bars('SPY', candidate)
        except RecencyError:
            continue
        if history:
            break
    if not history or (requested_end - history[-1][0]).days > 14:
        raise DataError('최근 미국 일별 자료가 없습니다.')
    data_day = history[-1][0]
    history = history[-65:]
    if len(history) < 65:
        raise DataError('시장 기준 65거래일 이력이 부족합니다.')
    expected_days = [x[0] for x in history]
    result = {'SPY': metrics('SPY', history, BENCHMARKS['SPY'])}
    for ticker in dict.fromkeys(list(BENCHMARKS) + list(SECTORS) + watch):
        if ticker == 'SPY':
            continue
        points = client.bars(ticker, data_day)[-65:]
        if [x[0] for x in points] != expected_days:
            raise DataError(f'{ticker}: 기준 시장과 거래일 이력이 다릅니다.')
        result[ticker] = metrics(ticker, points, BENCHMARKS.get(ticker, SECTORS.get(ticker, ticker)))
    sector_metrics = []
    for ticker in SECTORS:
        row = dict(result[ticker])
        row['relative_to_spy_20_pct_points'] = round(row['return_20_sessions_pct'] - result['SPY']['return_20_sessions_pct'], 4)
        sector_metrics.append(row)
    market_rows = []
    for day in (data_day, expected_days[-2]):
        payload = client.fetch(f'/v2/aggs/grouped/locale/us/market/stocks/{day}',
                               {'adjusted': 'true', 'include_otc': 'false'})
        if payload.get('adjusted') is not True:
            raise DataError('전체 자료가 분할 보정되지 않았습니다.')
        market_rows.append(universe(payload.get('results'), day))
    regular = {}
    for ticker in watch:
        now = client.fetch(f'/v1/open-close/{ticker}/{data_day}', {'adjusted': 'true'})
        prior = client.fetch(f'/v1/open-close/{ticker}/{expected_days[-2]}', {'adjusted': 'true'})
        for payload, day in ((now, data_day), (prior, expected_days[-2])):
            if payload.get('symbol') != ticker or payload.get('from') != day.isoformat():
                raise DataError('종목 정규장 요약 기준이 다릅니다.')
        close, before = numeric(now.get('close')), numeric(prior.get('close'))
        if close <= 0 or before <= 0:
            raise DataError('정규장 종가가 유효하지 않습니다.')
        regular[ticker] = {'data_date': data_day.isoformat(), 'session': 'regular', 'currency': 'USD',
                           'close': close, 'previous_close': before, 'delta': round(close - before, 8),
                           'daily_return_pct': pct(close, before), 'adjusted_for_splits': True,
                           'close_time': '공식 달력의 해당일 폐장 시각을 별도 확인; 일봉 시각을 폐장 시각으로 쓰지 않음'}
    return {'provider': 'Massive', 'requested_end_date': requested_end.isoformat(),
            'data_date': data_day.isoformat(), 'queried_at': datetime.now(KST).isoformat(timespec='seconds'),
            'request_count': client.requests, 'benchmarks_are_etfs_not_indices': True,
            'benchmarks': [result[t] for t in BENCHMARKS],
            'sectors': sorted(sector_metrics, key=lambda x: x['relative_to_spy_20_pct_points'], reverse=True),
            'watch': [dict(result[t], regular_session=regular[t]) for t in watch],
            'breadth': breadth(*market_rows), 'forecast_probability': None, 'backtest_status': 'not_validated',
            'limitations': ['일별 자료이며 장중·장전 실시간 시세 아님', 'ETF 가격은 지수 값이 아님',
                            '분할 보정 가격수익률이며 배당 재투자 총수익률 아님',
                            '거래량 증가는 순자금 유입이나 기관 순매수를 뜻하지 않음',
                            '분석·공개 게시 권한은 API 조회 권한과 별개']}


def write_output(output, payload, key):
    output = Path(output).resolve()
    if any(output.is_relative_to((ROOT / folder).resolve()) for folder in ('public', 'data/reports')):
        raise DataError('분석 산출물을 보고서·배포 경로에 직접 저장할 수 없습니다.')
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if key and key in encoded:
        raise DataError('산출물에 비밀키가 포함돼 저장을 중단합니다.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--end-date', default='')
    parser.add_argument('--watch', default='NVDA,AAPL,MSFT')
    parser.add_argument('--output', default='massive-output/analysis.json')
    args = parser.parse_args()
    try:
        end = date.fromisoformat(args.end_date) if args.end_date else datetime.now(NY).date() - timedelta(days=1)
        if end > datetime.now(NY).date():
            raise DataError('미래 날짜를 요청할 수 없습니다.')
        watch = watch_tickers(args.watch.split(','))
        key = os.environ.get('MASSIVE_API_KEY', '')
        payload = collect(Client(key), end, watch)
        write_output(args.output, payload, key)
        print(f"미국 일별 분석 완료: {payload['data_date']}, {payload['request_count']}개 요청")
    except (DataError, ValueError):
        # Do not print arbitrary exceptions, credential-containing URLs or bodies.
        print('미국 일별 분석 실패. 날짜·권한·Secrets 설정과 네트워크를 확인하세요.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
