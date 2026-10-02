"""Evidence-backed editorial scenarios; never infer forecasts from past returns."""
from datetime import datetime, timedelta
from html import escape

STATES = {'up': '+ 상방 우세', 'down': '− 하방 우세',
          'mixed': '± 재료 상충', 'unknown': '? 판단 보류'}
PERIODS = ('d1', 'd5')


def labels(report):
    return {'d1': {'pre': '당일', 'close': '다음 거래일', 'intraday': '남은 장'}[report['session']],
            'd5': '5거래일'}


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(hours=9):
        raise ValueError('Outlook timestamps require +09:00')
    return parsed


def validate_outlook(report):
    reading = report.get('reading', {})
    meta = reading.get('outlook')
    entries = reading.get('issues', []) + list(reading.get('stocks', {}).values()) + reading.get('next_checks', [])
    if meta is None:
        if any('outlook' in item for item in entries):
            raise ValueError('Outlook entries require timestamped metadata')
        return
    required = {'method', 'validation', 'estimated_at', 'input_cutoff', 'added_later', 'evaluation_eligible', 'note'}
    if set(meta) != required or meta['method'] != 'conditional' or meta['validation'] != 'not_validated':
        raise ValueError('Only explicit, unvalidated conditional outlooks are supported')
    cutoff, estimated = timestamp(meta['input_cutoff']), timestamp(meta['estimated_at'])
    if cutoff > estimated or cutoff > timestamp(report['queried_at']):
        raise ValueError('Outlook inputs cannot include future information')
    if type(meta['added_later']) is not bool or type(meta['evaluation_eligible']) is not bool or not meta['note']:
        raise ValueError('Outlook publication status and note are required')
    if meta['added_later'] and meta['evaluation_eligible']:
        raise ValueError('Retrospectively added outlooks cannot count as original predictions')
    if not meta['added_later'] and estimated > timestamp(report['queried_at']):
        raise ValueError('Late outlooks must be explicitly marked')
    if meta['evaluation_eligible'] and report['is_test']:
        raise ValueError('TEST outlooks cannot count as real predictions')
    if len(reading.get('issues', [])) != len(report['issues']) or len(reading.get('next_checks', [])) != len(report['next_checks']):
        raise ValueError('Each issue and next check needs a two-period outlook')
    stocks = reading.get('stocks', {})
    if set(stocks) != {item['ticker'] for item in report['stocks']}:
        raise ValueError('Each watch stock needs an outlook')
    source_ids = {item['id'] for item in report['sources']}
    for item in entries:
        outlook = item.get('outlook', {})
        if set(outlook) != set(PERIODS):
            raise ValueError('Both d1 and d5 outlooks are required')
        for entry in outlook.values():
            if set(entry) != {'direction', 'target', 'basis', 'counter', 'invalidation', 'sources'}:
                raise ValueError('Outlooks require evidence and invalidation, not invented probabilities')
            if entry['direction'] not in STATES:
                raise ValueError('Unknown outlook direction')
            if any(not isinstance(entry[key], str) or not entry[key].strip()
                   for key in ('target', 'basis', 'counter', 'invalidation')):
                raise ValueError('Outlook evidence cannot be empty')
            refs = entry['sources']
            if not isinstance(refs, list) or not refs or not all(ref in source_ids for ref in refs):
                raise ValueError('Outlook evidence must refer to report sources')


def badges(entry, report):
    if not entry.get('outlook'):
        return ''
    periods = labels(report)
    return '<span class="outlook-badges" aria-label="조건부 방향 전망">' + ''.join(
        f'<span class="outlook-badge outlook-{entry["outlook"][key]["direction"]}">{periods[key]} · {STATES[entry["outlook"][key]["direction"]]}</span>'
        for key in PERIODS) + '</span>'


def details(entry, report):
    if not entry.get('outlook'):
        return ''
    periods = labels(report)
    parts = ['<div class="outlook-details">']
    for key in PERIODS:
        item = entry['outlook'][key]
        parts.append(f'<p class="outlook-{item["direction"]}"><strong>{periods[key]} · {STATES[item["direction"]]}</strong></p>')
        for label, field in [('대상', 'target'), ('근거', 'basis'), ('반대 요인', 'counter'), ('무효·재판단 조건', 'invalidation')]:
            parts.append(f'<p><span>{label}</span> {escape(item[field], quote=True)}</p>')
    parts.append('</div>')
    return ''.join(parts)


def notice(report):
    meta = report.get('reading', {}).get('outlook')
    if not meta:
        return ''
    estimated = timestamp(meta['estimated_at']).strftime('%Y.%m.%d %H:%M KST')
    cutoff = timestamp(meta['input_cutoff']).strftime('%Y.%m.%d %H:%M KST')
    action = '추가' if meta['added_later'] else '작성'
    return (f'<aside class="outlook-notice"><strong>조건부 방향 전망 · 검증 전</strong>'
            f'<p>{estimated} {action} · 입력 자료 {cutoff}</p>'
            f'<p>{escape(meta["note"], quote=True)}</p></aside>')


def image_meta(report):
    meta = report.get('reading', {}).get('outlook')
    if not meta:
        return None
    return {'labels': labels(report), 'status': '조건부 방향 전망 · 검증 전',
            'estimated_at': timestamp(meta['estimated_at']).strftime('%m/%d %H:%M KST'),
            'input_cutoff': timestamp(meta['input_cutoff']).strftime('%m/%d %H:%M KST'),
            'added_later': meta['added_later'], 'note': meta['note']}
