const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {wrap, layout, createCanvases, init} = require('../assets/brief-image.js');

const W = 540, H = 675, PAD = 30;

function context() {
  return {
    font: '400 16px sans-serif', calls: [],
    measureText(value) { const size = Number(this.font.match(/ (\d+)px/)[1]); return {width: Array.from(value).length * size}; },
    scale() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, arcTo() {}, closePath() {},
    arc() {}, fill() {}, stroke() {}, setLineDash() {},
    fillText(value, x, y) { this.calls.push({value, x, y, font: this.font}); }
  };
}

function payloads() {
  const root = path.join(__dirname, '../public');
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json')));
  return manifest.reports.map(item => {
    const html = fs.readFileSync(path.join(root, item.path, 'index.html'), 'utf8');
    const data = JSON.parse(html.split('id="brief-image-data">')[1].split('</script>')[0]);
    data.report_url = new URL(data.report_path, `https://meangyulim.github.io/cost/${item.path}`).href;
    return data;
  });
}

const texts = plan => plan.pages.flatMap(page => page.ops.filter(op => op.kind === 'text'));
// Card content without the repeated per-card frame (brand, date, page number, "이어서").
const body = plan => plan.pages.flatMap(page => page.ops.filter(op => op.kind === 'text' && !op.frame));
const squash = value => String(value).replace(/\s/g, '');

test('wrapping preserves Korean, numbers, Unicode and explicit line breaks', () => {
  const ctx = context();
  for (const value of ['한글 요약 +1.23% −0.50%', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', '🚀 미국 ETF 65거래일', '첫 줄\n둘째 줄']) {
    const lines = wrap(ctx, value, 112);
    assert.equal(lines.join('').replace(/\s/g, ''), value.replace(/\s/g, ''));
    for (const line of lines) assert.ok(ctx.measureText(line).width <= 112, line);
  }
});

test('card percentages have one unit for both report input formats', () => {
  for (const [raw, expected] of [['+1.95', '+1.95%'], ['+1.95%', '+1.95%'],
    ['−0.50%', '−0.50%'], ['0.00', '0.00%']]) {
    const data = payloads()[0];
    for (const entry of [...data.indices, ...data.stocks]) {
      entry.direction = 'flat';
      entry.percent = raw;
    }
    const content = texts(layout(data, context())).map(op => op.value).join('');
    assert.ok(content.includes(expected));
    assert.ok(!content.includes('%%'));
    assert.equal(data.indices[0].percent, raw);
  }
});

const VIEW = {
  headline: '급락 뒤 이틀 연속 반등. 안도는 왔지만 아직 확인 단계예요.', mood: 'relief', mood_label: '안도',
  mood_note: '경계에서 안도로 옮겨 가는 중이에요.',
  drivers: [{title: '나쁜 뉴스에도 버텼다.', text: '오전 약세를 오후에 뒤집었어요. '.repeat(6)},
    {title: '기대가 컸던 곳엔 냉정하다.', text: '실적이 기대에 못 미친 종목은 크게 빠졌어요.'}],
  history: [{title: '2024년 8월 5일 코스피 급락', then: '공포성 매도', next: '다음 날 반등', after: '한 달 넘게 고점 미회복',
    difference: '이번엔 이익 전망이 받쳐 줘요.'}],
  paths: {good: '외국인 매수가 이어지면 회복으로 볼 수 있어요.', caution: '물가 지표가 높게 나오면 불안이 돌아올 수 있어요.'},
  written: '11/11 15:51 작성'};

test('시장 읽기 card follows the summary and draws every plain-language part', () => {
  const data = payloads()[0];
  data.reading = structuredClone(VIEW);
  const plan = layout(data, context());
  const firsts = plan.pages.map(page => (page.ops.find(op => op.kind === 'text' && !op.frame) || {}).value);
  const reading = firsts.indexOf('시장 읽기');
  assert.ok(reading >= 1 && plan.pages.slice(0, reading).every(page => page.section === '요약'));
  assert.ok(reading < firsts.findIndex(value => String(value).startsWith('이야기')));
  const content = squash(body(plan).map(op => op.value).join(''));
  for (const value of [VIEW.headline, VIEW.mood_note, '왜이런분위기일까', ...VIEW.drivers.flatMap(item => [item.title, item.text]),
    ...['then', 'next', 'after', 'difference'].map(key => VIEW.history[0][key]), VIEW.paths.good, VIEW.paths.caution,
    '같은흐름이반복된다는뜻은아니에요', '작성자해석·지표아님', '확률이나목표가아님']) {
    assert.ok(content.includes(squash(value)), value);
  }
  const moods = texts(plan).filter(op => ['불안', '경계', '중립', '안도', '들뜸'].includes(op.value));
  assert.deepEqual(moods.map(op => op.value), ['불안', '경계', '중립', '안도', '들뜸']);
  assert.equal(moods.find(op => op.weight === 900).value, '안도');
  for (const removed of ['상방 우세', '하방 우세', '재료 상충', '판단 보류', '판단선']) assert.ok(!content.includes(squash(removed)), removed);
  assert.ok(plan.pages.every(page => page.ops.every(op => op.kind !== 'pill')));
});

test('older editions show one plain sentence per period on the 시장 읽기 card', () => {
  const data = payloads().find(item => item.id === 'kr-pre-2026-10-02');
  const content = squash(body(layout(data, context())).map(op => op.value).join(''));
  for (const item of data.reading.legacy) assert.ok(content.includes(squash(`${item.label} · ${item.plain}`)) && content.includes(squash(item.condition)));
  assert.ok(content.includes('장전예측의적중률평가에서제외'));
  assert.ok(!content.includes('상방우세'));
});

test('every real and TEST report fits 4:5 cards without cropping or omitted fields', () => {
  for (const data of payloads()) {
    const ctx = context(), plan = layout(data, ctx);
    assert.equal(plan.width, W);
    assert.equal(plan.height, H);
    assert.ok(plan.pages.length >= 3);
    for (const [n, page] of plan.pages.entries()) {
      const drawn = page.ops.filter(op => op.kind === 'text');
      for (const op of drawn) {
        ctx.font = `${op.weight} ${op.size}px sans-serif`;
        assert.ok(op.x >= PAD - 1 && op.x + ctx.measureText(op.value).width <= W - PAD + 1, op.value);
        assert.ok(op.y >= 0 && op.y + op.size <= H - 20, op.value);
      }
      assert.ok(drawn.some(op => op.value === `${n + 1} / ${plan.pages.length}`));
      assert.ok(drawn.some(op => op.value === '관찰용 자료 · 투자 권유 아님'));
      if (data.is_test) assert.ok(drawn.some(op => op.value.includes('TEST')));
    }
    const content = squash(body(plan).map(op => op.value).join(''));
    for (const section of [`이야기 ${data.issues.length}`, `관찰 종목 ${data.stocks.length}`, '달력']) {
      assert.ok(content.includes(squash(section)), section);
    }
    for (const value of [data.headline, data.as_of, ...data.summary_points, ...data.notices,
      ...data.issues.flatMap(item => [item.title, item.preview]),
      ...data.stocks.flatMap(item => [item.price, item.percent, item.reason, item.watch, `${item.session} · ${item.as_of}`]),
      ...data.next_checks.flatMap(item => [item.title, item.detail])]) {
      assert.ok(content.includes(squash(value)), value);
    }
    if (data.reading && data.reading.legacy) assert.ok(content.includes(squash('시장 읽기')));
    assert.ok(!content.includes(squash(data.report_url)));
    assert.ok(!content.includes('출처·'));
  }
});

test('very long content flows onto more cards instead of clipping text', () => {
  const data = payloads()[0];
  data.notices = ['주의 사항 '.repeat(1500)];
  const ctx = context(), plan = layout(data, ctx);
  assert.ok(plan.pages.length > 6);
  const drawn = texts(plan);
  for (const op of drawn) assert.ok(op.y + op.size <= H - 20, op.value);
  assert.equal(squash(drawn.filter(op => op.value.includes('주의') || op.value.includes('사항')).map(op => op.value).join('')).length,
    squash('※ ' + data.notices[0]).length);
});

test('each card is drawn at 1080 × 1350', () => {
  const data = payloads()[0];
  const canvases = createCanvases(data, {createElement: () => ({getContext: () => context()})});
  assert.equal(canvases.length, layout(data, context()).pages.length);
  for (const canvas of canvases) {
    assert.equal(canvas.width, 1080);
    assert.equal(canvas.height, 1350);
  }
});

function ui(shareSupported = true) {
  const data = payloads()[0], nodes = {}, buttons = ['save', 'share'].map(action => node(action));
  function node(action) {
    return {hidden: true, disabled: false, listeners: {}, dataset: {imageAction: action}, children: [],
      addEventListener(type, fn) { this.listeners[type] = fn; }, focus() {},
      append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; },
      showModal() { this.open = true; }, close() { this.open = false; this.listeners.close(); }};
  }
  for (const id of ['brief-image-data', 'image-dialog', 'image-status', 'image-previews', 'image-share', 'image-retry', 'image-close']) nodes[id] = node();
  nodes['brief-image-data'].textContent = JSON.stringify(data);
  const doc = {fonts: {ready: Promise.resolve(), load: () => Promise.resolve([])}, activeElement: buttons[0],
    getElementById: id => nodes[id], querySelectorAll: () => buttons,
    createElement: tag => tag === 'canvas' ? {getContext: () => context(), toBlob: fn => fn(new Blob(['PNG'], {type: 'image/png'}))} : node()};
  const calls = [], events = {};
  const win = {File, URL: {createObjectURL: () => 'blob:preview', revokeObjectURL: () => {}},
    location: {href: 'https://meangyulim.github.io/cost/'},
    navigator: shareSupported ? {canShare: () => true, share: data => {calls.push(data); return Promise.resolve(); }} : {},
    requestIdleCallback: fn => fn(), addEventListener: (type, fn) => {events[type] = fn;}};
  init(doc, win);
  return {nodes, buttons, calls, win, data};
}

async function settle() { for (let n = 0; n < 20; n++) await new Promise(resolve => setImmediate(resolve)); }

test('prepared cards share as PNG files synchronously from the masthead click', async () => {
  const app = ui();
  await settle();
  assert.ok(app.buttons.every(button => button.hidden === false));
  assert.equal(app.nodes['image-share'].disabled, false);
  app.buttons[1].listeners.click();
  assert.equal(app.calls.length, 1);
  assert.ok(app.calls[0].files.length >= 3);
  assert.ok(app.calls[0].files.every(file => file.type === 'image/png' && file.name.endsWith('.png')));
  assert.equal(app.calls[0].url, undefined); // Files, not a link-only share.
});

test('unsupported file sharing falls back to per-card save previews', async () => {
  const app = ui(false);
  await settle();
  app.buttons[1].listeners.click();
  assert.equal(app.nodes['image-dialog'].open, true);
  assert.equal(app.nodes['image-share'].disabled, true);
  const figures = app.nodes['image-previews'].children;
  assert.ok(figures.length >= 3);
  assert.equal(figures[0].children[1].href, 'blob:preview');
  assert.ok(app.nodes['image-status'].textContent.includes('PNG 저장'));
});

test('cancelling native sharing never sends or retries', async () => {
  const app = ui();
  await settle();
  app.win.navigator.share = () => {app.calls.push('cancel'); return Promise.reject({name: 'AbortError'});};
  await app.nodes['image-share'].listeners.click();
  assert.equal(app.calls.length, 1);
  assert.equal(app.nodes['image-share'].disabled, false);
});
