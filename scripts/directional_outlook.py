"""Evidence-backed editorial scenarios; never infer forecasts from past returns."""
from datetime import datetime, timedelta
from html import escape

# Direction codes of older per-item outlooks; validated, no longer drawn as badges.
STATES = {'up': '↗ 상방 우세', 'down': '↘ 하방 우세',
          'mixed': '± 재료 상충', 'unknown': '? 판단 보류'}
DIRECTIONAL = ('up', 'down')
PLAIN = {'up': '오를 쪽 재료가 더 많다고 봤어요', 'down': '내릴 쪽 재료가 더 많다고 봤어요',
         'mixed': '재료가 엇갈려 방향을 정하지 않았어요', 'unknown': '자료가 부족해 판단을 미뤘어요'}
PERIODS = ('d1', 'd5')
# 2026.11.12: the owner asked for a plain-language reading instead of per-item horizon badges.
MOODS = {'fear': '불안', 'caution': '경계', 'neutral': '중립', 'relief': '안도', 'euphoria': '들뜸'}
VIEW_KEYS = {'headline', 'mood', 'drivers', 'history', 'paths', 'estimated_at', 'input_cutoff', 'added_later'}


def labels(report):
    return {'d1': {'pre': '당일', 'close': '다음 거래일', 'intraday': '남은 장'}[report['session']],
            'd5': '5거래일'}


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(hours=9):
        raise ValueError('Outlook timestamps require +09:00')
    return parsed


def entries(report):
    reading = report.get('reading', {})
    return reading.get('issues', []) + list(reading.get('stocks', {}).values()) + reading.get('next_checks', [])


def validate_outlook(report):
    validate_view(report)
    reading = report.get('reading', {})
    meta = reading.get('outlook')
    items = entries(report)
    if meta is None:
        if any('outlook' in item for item in items):
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
    for item in items:
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


def validate_view(report):
    """reading.view: interpretation in plain words. Never probabilities, targets or hit rates."""
    view = report.get('reading', {}).get('view')
    if view is None:
        return
    if not isinstance(view, dict) or set(view) != VIEW_KEYS:
        raise ValueError('reading.view needs exactly: ' + ', '.join(sorted(VIEW_KEYS)))
    source_ids = {item['id'] for item in report['sources']}

    def words(value, name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'reading.view {name} cannot be empty')

    def refs(value):
        if not isinstance(value, list) or not value or not all(ref in source_ids for ref in value):
            raise ValueError('reading.view evidence must refer to report sources')

    words(view['headline'], 'headline')
    mood = view['mood']
    if not isinstance(mood, dict) or set(mood) != {'level', 'note'} or mood['level'] not in MOODS:
        raise ValueError('reading.view mood needs a known level and a note')
    words(mood['note'], 'mood note')
    if not isinstance(view['drivers'], list) or not 1 <= len(view['drivers']) <= 5:
        raise ValueError('reading.view needs one to five drivers')
    for item in view['drivers']:
        if not isinstance(item, dict) or set(item) != {'title', 'text', 'sources'}:
            raise ValueError('drivers need title, text and sources')
        words(item['title'], 'driver title')
        words(item['text'], 'driver text')
        refs(item['sources'])
    if not isinstance(view['history'], list) or len(view['history']) > 2:
        raise ValueError('reading.view history is a list of at most two cases')
    for case in view['history']:
        if not isinstance(case, dict) or set(case) != {'title', 'then', 'next', 'after', 'difference', 'sources'}:
            raise ValueError('history cases need title, then, next, after, difference and sources')
        for key in ('title', 'then', 'next', 'after', 'difference'):
            words(case[key], 'history ' + key)
        refs(case['sources'])
    paths = view['paths']
    if not isinstance(paths, dict) or set(paths) != {'good', 'caution'}:
        raise ValueError('reading.view paths need good and caution')
    words(paths['good'], 'good path')
    words(paths['caution'], 'caution path')
    cutoff, estimated = timestamp(view['input_cutoff']), timestamp(view['estimated_at'])
    if type(view['added_later']) is not bool:
        raise ValueError('reading.view added_later must be boolean')
    if cutoff > estimated or cutoff > timestamp(report['queried_at']):
        raise ValueError('reading.view inputs cannot include future information')
    if not view['added_later'] and estimated > timestamp(report['queried_at']):
        raise ValueError('Late readings must be explicitly marked')


def is_directional(entry):
    outlook = entry.get('outlook') or {}
    return any(outlook.get(key, {}).get('direction') in DIRECTIONAL for key in PERIODS)


def details(entry, report):
    if not entry.get('outlook'):
        return ''
    periods = labels(report)
    parts = []
    for key in PERIODS:
        item = entry['outlook'][key]
        parts.append(f'<div class="outlook-detail"><b>{periods[key]} · {PLAIN[item["direction"]]}</b>')
        for label, field in [('대상', 'target'), ('근거', 'basis'), ('반대 요인', 'counter'), ('무효·재판단 조건', 'invalidation')]:
            parts.append(f'<p><span>{label}</span>{escape(item[field], quote=True)}</p>')
        parts.append('</div>')
    return ''.join(parts)


def notice(report):
    meta = report.get('reading', {}).get('outlook')
    if not meta:
        return ''
    estimated = timestamp(meta['estimated_at']).strftime('%m.%d %H:%M')
    cutoff = timestamp(meta['input_cutoff']).strftime('%m.%d %H:%M')
    action = '추가' if meta['added_later'] else '작성'
    return (f'<p class="view-meta">이전 형식의 조건부 해석 · 검증 전 · 확률 아님 · {estimated} {action} · 입력 자료 {cutoff}'
            f'<br>{escape(meta["note"], quote=True)}</p>')


def view_written(report):
    view = report['reading']['view']
    return timestamp(view['estimated_at']).strftime('%m.%d %H:%M') + (' 추가' if view['added_later'] else ' 작성')
