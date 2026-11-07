#!/usr/bin/env python3
"""Send queued briefing notices to KakaoTalk "나에게 보내기" from GitHub Actions.

Commands
  send          Process dispatch/*.json records whose status is "queued".
  setup [--test]  Exchange KAKAO_AUTH_CODE for a refresh token and store it as a Secret.

Only the standard library is used. Tokens, authorization codes and Kakao response
bodies are never printed or written to the repository; only HTTP status and error
codes are recorded.
"""
import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_DIR = ROOT / 'dispatch'
BRANCH = 'main'
SITE_URL = 'https://meangyulim.github.io/cost/'
REPORT_URL = SITE_URL + 'reports/{}/'
TOKEN_URL = 'https://kauth.kakao.com/oauth/token'
SEND_URL = 'https://kapi.kakao.com/v2/api/talk/memo/default/send'
BUTTON_TITLE = '브리핑 열기'
TEST_TEXT = '카카오 알림 연결 테스트입니다.'
MAX_TEXT = 200
MAX_AGE = timedelta(hours=6)
FUTURE_SKEW = timedelta(minutes=10)
PUSH_RETRIES = 3
KST = timezone(timedelta(hours=9))
REPORT_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,80}')
SAFE_CODE = re.compile(r'-?\d{1,8}|KOE\d{3,4}|[a-z_]{1,40}')
NETWORK_ERRORS = (urllib.error.URLError, OSError, http.client.HTTPException)


class KakaoError(Exception):
    """Sanitized Kakao failure: carries only HTTP status and error code."""

    def __init__(self, reason, http_status=None, error_code=None):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status
        self.error_code = error_code


# ---------------------------------------------------------------- helpers

def now_utc():
    return datetime.now(timezone.utc)


def stamps(moment):
    return (moment.astimezone(KST).isoformat(timespec='seconds'),
            moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))


def mask(value):
    if value and os.environ.get('GITHUB_ACTIONS') == 'true':
        print(f'::add-mask::{value}', flush=True)


def safe_code(raw):
    """Return Kakao's error code from a response body, or None. Never the body."""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ('error_code', 'code', 'result_code', 'error'):
        value = payload.get(key)
        if isinstance(value, (int, str)) and not isinstance(value, bool) and SAFE_CODE.fullmatch(str(value)):
            return value
    return None


def post_form(url, fields, token=None, timeout=20):
    """POST a form. Raises KakaoError on HTTP errors; network errors propagate."""
    headers = {'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode('utf-8'),
                                     headers=headers, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read(100_000)
    except urllib.error.HTTPError as error:
        try:
            raw = error.read(20_000)
        except NETWORK_ERRORS:
            raw = b''
        raise KakaoError('http_error', error.code, safe_code(raw)) from None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        payload = None
    return status, payload


def token_fields(grant):
    key = os.environ.get('KAKAO_REST_API_KEY', '').strip()
    if not key:
        raise KakaoError('missing_secret', error_code='KAKAO_REST_API_KEY')
    fields = {'grant_type': grant, 'client_id': key}
    secret = os.environ.get('KAKAO_CLIENT_SECRET', '').strip()
    if secret:
        fields['client_secret'] = secret
    return fields


def request_token(fields):
    try:
        status, payload = post_form(TOKEN_URL, fields)
    except NETWORK_ERRORS:
        raise KakaoError('network_error') from None
    access = payload.get('access_token') if isinstance(payload, dict) else None
    if not isinstance(access, str) or not access:
        raise KakaoError('token_response_invalid', status)
    refresh = payload.get('refresh_token')
    refresh = refresh if isinstance(refresh, str) and refresh else None
    mask(access)
    mask(refresh)
    return access, refresh


def refresh_access_token():
    """Return (access_token, new_refresh_token_or_None)."""
    refresh = os.environ.get('KAKAO_REFRESH_TOKEN', '').strip()
    if not refresh:
        raise KakaoError('missing_secret', error_code='KAKAO_REFRESH_TOKEN')
    fields = token_fields('refresh_token')
    fields['refresh_token'] = refresh
    return request_token(fields)


def exchange_auth_code(code):
    if not code:
        raise KakaoError('missing_input', error_code='KAKAO_AUTH_CODE')
    fields = token_fields('authorization_code')
    fields['redirect_uri'] = SITE_URL
    fields['code'] = code
    return request_token(fields)


def store_refresh_token(value):
    """Replace the KAKAO_REFRESH_TOKEN Secret. The value goes through stdin only."""
    gh_token = os.environ.get('GH_SECRET_TOKEN', '').strip()
    if not gh_token:
        print('KAKAO_REFRESH_TOKEN 교체 실패: GH_SECRET_TOKEN 없음', file=sys.stderr)
        return False
    command = ['gh', 'secret', 'set', 'KAKAO_REFRESH_TOKEN']
    repo = os.environ.get('GITHUB_REPOSITORY', '').strip()
    if repo:
        command += ['--repo', repo]
    env = dict(os.environ, GH_TOKEN=gh_token)
    try:
        result = subprocess.run(command, input=value, text=True, env=env,
                                capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        print('KAKAO_REFRESH_TOKEN 교체 실패: gh 실행 오류', file=sys.stderr)
        return False
    if result.returncode != 0:
        print(f'KAKAO_REFRESH_TOKEN 교체 실패: gh 종료 코드 {result.returncode}', file=sys.stderr)
        return False
    print('KAKAO_REFRESH_TOKEN 교체 완료')
    return True


def build_text(summary, url):
    """Summary + newline + URL within MAX_TEXT characters; only the summary is cut."""
    summary = summary.strip()
    room = MAX_TEXT - len(url) - 1
    if room < 1:
        raise ValueError('url_too_long')
    if len(summary) > room:
        summary = summary[:room - 1].rstrip() + '…'
    return summary + '\n' + url


def send_memo(access_token, text, url):
    """Call the memo API exactly once. Returns (status, http_status, error_code)."""
    template = {'object_type': 'text', 'text': text,
                'link': {'web_url': url, 'mobile_web_url': url},
                'button_title': BUTTON_TITLE}
    fields = {'template_object': json.dumps(template, ensure_ascii=False)}
    try:
        status, payload = post_form(SEND_URL, fields, token=access_token)
    except KakaoError as error:
        return 'failed', error.http_status, error.error_code
    except NETWORK_ERRORS:
        return 'unknown', None, None
    if not isinstance(payload, dict) or 'result_code' not in payload:
        return 'unknown', status, None
    if payload.get('result_code') == 0:
        return 'sent', status, None
    code = payload.get('result_code')
    return 'failed', status, code if isinstance(code, int) and not isinstance(code, bool) else None


# ---------------------------------------------------------------- records

def load_record(path):
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return None
    return record if isinstance(record, dict) else None


def write_record(path, record):
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def parse_utc(value):
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def check_record(record, path, now):
    """Return None when sendable, else (status, failure_reason)."""
    report_id = record.get('report_id')
    if not isinstance(report_id, str) or not REPORT_ID.fullmatch(report_id) or path.stem != report_id:
        return 'failed', 'invalid_report_id'
    url = REPORT_URL.format(report_id)
    if record.get('report_url') != url:
        return 'failed', 'report_url_mismatch'
    summary = record.get('kakao_summary')
    if not isinstance(summary, str) or not summary.strip():
        return 'failed', 'missing_kakao_summary'
    if record.get('send_tool_called') is not False:
        return 'failed', 'send_tool_called_not_false'
    if record.get('attempted_record_created') is not False:
        return 'failed', 'attempted_record_created_not_false'
    if MAX_TEXT - len(url) - 1 < 1:
        return 'failed', 'url_too_long'
    queued_at = parse_utc(record.get('queued_at_utc'))
    if queued_at is None:
        return 'failed', 'invalid_queued_at_utc'
    if queued_at - now > FUTURE_SKEW:
        return 'failed', 'queued_at_in_future'
    if now - queued_at > MAX_AGE:
        return 'expired', 'queued_over_6_hours'
    return None


# ---------------------------------------------------------------- git

def git(*args, check=True):
    return subprocess.run(['git', *args], cwd=ROOT, check=check, capture_output=True, text=True)


def pull_rebase():
    if git('pull', '--rebase', '--quiet', 'origin', BRANCH, check=False).returncode == 0:
        return True
    git('rebase', '--abort', check=False)
    return False


def publish(path, message):
    """Commit one record and push with up to PUSH_RETRIES rebased retries."""
    rel = str(path.resolve().relative_to(ROOT))
    if git('add', rel, check=False).returncode or git('commit', '-q', '-m', message, check=False).returncode:
        return False
    for attempt in range(PUSH_RETRIES + 1):
        if git('push', '-q', 'origin', f'HEAD:{BRANCH}', check=False).returncode == 0:
            return True
        if attempt == PUSH_RETRIES or not pull_rebase():
            break
    return False


def verify_remote(path, record):
    """Re-read the pushed attempted record from origin before sending."""
    rel = str(path.resolve().relative_to(ROOT))
    if git('fetch', '-q', 'origin', BRANCH, check=False).returncode:
        return False
    shown = git('show', f'origin/{BRANCH}:{rel}', check=False)
    if shown.returncode:
        return False
    try:
        remote = json.loads(shown.stdout)
    except ValueError:
        return False
    keys = ('status', 'attempted_at_utc', 'workflow_run_id', 'attempted_record_created')
    return isinstance(remote, dict) and all(remote.get(k) == record.get(k) for k in keys)


# ---------------------------------------------------------------- commands

def run_id():
    value = os.environ.get('GITHUB_RUN_ID', '')
    return int(value) if value.isdigit() else None


def cmd_send(dispatch_dir=DISPATCH_DIR, clock=now_utc):
    if not pull_rebase():
        print('git pull --rebase 실패: 전송하지 않음', file=sys.stderr)
        return 1
    queued = []
    for path in sorted(dispatch_dir.glob('*.json')):
        record = load_record(path)
        if record is not None and record.get('status') == 'queued':
            queued.append((path, record))
    if not queued:
        print('queued 기록 없음')
        return 0

    ok = True
    token = None
    for path, record in queued:
        report_id = path.stem
        problem = check_record(record, path, clock())
        if problem:
            status, reason = problem
            kst, utc = stamps(clock())
            record.update(status=status, failure_reason=reason, recorded_at_kst=kst, recorded_at_utc=utc)
            write_record(path, record)
            print(f'{report_id}: {status} ({reason})')
            if not publish(path, f'Record Kakao dispatch {status} for {report_id}'):
                print(f'{report_id}: 상태 푸시 실패', file=sys.stderr)
                return 1
            ok = ok and status == 'expired'
            continue

        kst, utc = stamps(clock())
        record.update(status='attempted', attempted_at_kst=kst, attempted_at_utc=utc,
                      attempted_record_created=True, workflow_run_id=run_id())
        write_record(path, record)
        if not publish(path, f'Record Kakao dispatch attempted for {report_id}') or not verify_remote(path, record):
            print(f'{report_id}: attempted 기록 푸시·확인 실패: 전송하지 않음', file=sys.stderr)
            return 1

        if token is None:
            try:
                access, new_refresh = refresh_access_token()
                token = ('ok', access)
                if new_refresh and not store_refresh_token(new_refresh):
                    ok = False
            except KakaoError as error:
                token = ('error', error)
        if token[0] == 'error':
            error = token[1]
            result, http_status, code, reason = 'failed', error.http_status, error.error_code, f'token_{error.reason}'
            called = False
        else:
            text = build_text(record['kakao_summary'], record['report_url'])
            result, http_status, code = send_memo(token[1], text, record['report_url'])
            reason = {'failed': 'kakao_api_error', 'unknown': 'network_error_after_send'}.get(result)
            called = True
            record['message_length'] = len(text)

        kst, utc = stamps(clock())
        record.update(status=result, kakao_result=result, send_tool_called=called,
                      kakao_http_status=http_status, kakao_error_code=code,
                      result_recorded_at_kst=kst, result_recorded_at_utc=utc)
        if reason:
            record['failure_reason'] = reason
        write_record(path, record)
        print(f'{report_id}: {result} (HTTP {http_status}, code {code})')
        if result != 'sent':
            ok = False
        if not publish(path, f'Record Kakao dispatch {result} for {report_id}'):
            print(f'{report_id}: 결과 푸시 실패(재전송하지 않음)', file=sys.stderr)
            ok = False
    return 0 if ok else 1


def cmd_setup(test=False):
    code = os.environ.get('KAKAO_AUTH_CODE', '').strip()
    mask(code)
    try:
        access, refresh = exchange_auth_code(code)
    except KakaoError as error:
        print(f'인가 코드 교환 실패: {error.reason} (HTTP {error.http_status}, code {error.error_code})',
              file=sys.stderr)
        return 1
    if not refresh:
        print('인가 코드 교환 응답에 refresh_token 없음', file=sys.stderr)
        return 1
    ok = store_refresh_token(refresh)
    if test:
        result, http_status, error_code = send_memo(access, TEST_TEXT, SITE_URL)
        print(f'연결 테스트: {result} (HTTP {http_status}, code {error_code})')
        ok = ok and result == 'sent'
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('send')
    setup = sub.add_parser('setup')
    setup.add_argument('--test', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'send':
        return cmd_send()
    return cmd_setup(args.test)


if __name__ == '__main__':
    raise SystemExit(main())
