const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {wrap, layout, createCanvas, init} = require('../assets/brief-image.js');

function context() {
  return {
    font: '400 16px sans-serif', calls: [],
    measureText(value) { const size = Number(this.font.match(/ (\d+)px/)[1]); return {width: Array.from(value).length * size}; },
    scale() {}, fillRect() {},
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

test('wrapping preserves Korean, numbers, Unicode and explicit line breaks', () => {
  const ctx = context();
  for (const value of ['한글 요약 +1.23% −0.50%', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', '🚀 미국 ETF 65거래일', '첫 줄\n둘째 줄']) {
    const lines = wrap(ctx, value, 112);
    assert.equal(lines.join('').replace(/\s/g, ''), value.replace(/\s/g, ''));
    for (const line of lines) assert.ok(ctx.measureText(line).width <= 112, line);
  }
});

test('image percentages have one unit for both report input formats', () => {
  for (const [raw, expected] of [['+1.95', '+1.95%'], ['+1.95%', '+1.95%'],
    ['−0.50%', '−0.50%'], ['0.00', '0.00%']]) {
    const data = payloads()[0];
    for (const entry of [...data.indices, ...data.stocks]) {
      entry.direction = 'flat';
      entry.percent = raw;
    }
    const content = layout(data, context()).ops.filter(op => op.kind === 'text').map(op => op.value).join('');
    assert.ok(content.includes(expected));
    assert.ok(!content.includes('%%'));
    assert.equal(data.indices[0].percent, raw);
  }
});

test('saved image distinguishes conditional horizons from observed price changes', () => {
  const data = payloads().find(item => item.id === 'kr-pre-2026-10-02');
  data.stocks[0].outlook.d1.direction = 'down';
  data.stocks[0].outlook.d5.direction = 'up';
  const plan = layout(data, context());
  const text = plan.ops.filter(op => op.kind === 'text');
  assert.ok(text.some(op => op.value === '당일 · − 하방 우세' && op.fill === '#1768ae'));
  assert.ok(text.some(op => op.value === '5거래일 · + 상방 우세' && op.fill === '#c32d4b'));
  assert.ok(text.some(op => op.value.includes('+2.79%') && op.fill === '#c32d4b'));
  assert.ok(text.some(op => op.value.includes('조건부 방향 전망 · 검증 전')));
  assert.ok(text.map(op => op.value).join('').replace(/\s/g, '').includes('장전예측의적중률평가에서제외'));
});

test('every real and TEST report renders without cropping or omitted sections', () => {
  for (const data of payloads()) {
    const ctx = context(), plan = layout(data, ctx);
    assert.equal(plan.width, 540);
    const drawn = plan.ops.filter(op => op.kind === 'text');
    assert.ok(drawn.length > 30);
    for (const op of drawn) {
      ctx.font = `${op.weight} ${op.size}px sans-serif`;
      assert.ok(op.x + ctx.measureText(op.value).width <= plan.width - 21, op.value);
      assert.ok(op.y + op.size <= plan.height - 20, op.value);
    }
    const content = drawn.map(op => op.value).join('').replace(/\s/g, '');
    for (const section of ['오늘의 결론', '핵심 이슈 3', '관찰 종목 3', '다음 확인', '투자 권유 아님']) {
      assert.ok(content.includes(section.replace(/\s/g, '')));
    }
    for (const stock of data.stocks) assert.ok(content.includes(stock.price.replace(/\s/g, '')));
    for (const value of [data.title, data.headline, data.as_of, ...data.summary_points,
      ...data.notices, ...data.issues.flatMap(item => [item.title, item.preview]),
      ...data.stocks.flatMap(item => [item.price, item.percent, item.as_of, item.session, item.reason, item.watch]),
      ...data.next_checks.flatMap(item => [item.label, item.title, item.detail])]) {
      assert.ok(content.includes(value.replace(/\s/g, '')), value);
    }
    assert.ok(!content.includes(data.report_url.replace(/\s/g, '')));
    assert.ok(!content.includes('출처·'));
    if (data.is_test) assert.ok(content.includes('TEST'));
    const canvas = {getContext: () => ctx};
    createCanvas(data, {createElement: () => canvas});
    assert.equal(canvas.width, 1080);
    assert.ok(canvas.height > 1000 && canvas.height <= 8192);
  }
});

test('very long content expands the image instead of clipping text', () => {
  const data = payloads()[0];
  data.notices = ['주의 사항 '.repeat(4000)];
  const ctx = context(), plan = layout(data, ctx);
  assert.ok(plan.height > 8192);
  const canvas = {getContext: () => ctx};
  createCanvas(data, {createElement: () => canvas});
  assert.ok(canvas.height <= 8192);
  assert.ok(canvas.width * canvas.height <= 16010000);
  assert.equal(plan.ops.filter(op => op.kind === 'text').at(-1).value, '관찰용 자료 · 투자 권유 아님');
});

function ui(shareSupported = true) {
  const data = payloads()[0], nodes = {}, buttons = ['save', 'share'].map(action => node(action));
  function node(action) {
    return {hidden: false, disabled: false, listeners: {}, dataset: {imageAction: action},
      addEventListener(type, fn) { this.listeners[type] = fn; }, focus() {},
      showModal() { this.open = true; }, close() { this.open = false; this.listeners.close(); }};
  }
  for (const id of ['brief-image-data', 'image-dialog', 'image-status', 'image-preview', 'image-download', 'image-share', 'image-retry', 'image-close']) nodes[id] = node();
  nodes['brief-image-data'].textContent = JSON.stringify(data);
  const ctx = context();
  const doc = {fonts: {ready: Promise.resolve()}, activeElement: buttons[0],
    getElementById: id => nodes[id], querySelector: () => node(), querySelectorAll: () => buttons,
    createElement: () => ({getContext: () => ctx, toBlob: fn => fn(new Blob(['PNG'], {type: 'image/png'}))})};
  const calls = [], events = {};
  const win = {File, URL: {createObjectURL: () => 'blob:preview', revokeObjectURL: () => {}},
    location: {href: 'https://meangyulim.github.io/cost/'},
    navigator: shareSupported ? {canShare: () => true, share: data => {calls.push(data); return Promise.resolve(); }} : {},
    requestIdleCallback: fn => fn(), addEventListener: (type, fn) => {events[type] = fn;}};
  init(doc, win);
  return {nodes, buttons, calls, win};
}

test('prepared toolbar shares a PNG File synchronously from the click', async () => {
  const app = ui();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.nodes['image-share'].disabled, false);
  app.buttons[1].listeners.click();
  assert.equal(app.calls.length, 1);
  assert.equal(app.calls[0].files[0].type, 'image/png');
  assert.ok(app.calls[0].files[0].name.endsWith('.png'));
  assert.equal(app.calls[0].url, undefined); // File, not a link-only share.
});

test('unsupported file sharing falls back to an accessible save preview', async () => {
  const app = ui(false);
  await new Promise(resolve => setImmediate(resolve));
  app.buttons[1].listeners.click();
  assert.equal(app.nodes['image-dialog'].open, true);
  assert.equal(app.nodes['image-share'].disabled, true);
  assert.equal(app.nodes['image-download'].href, 'blob:preview');
  assert.ok(app.nodes['image-status'].textContent.includes('PNG 저장'));
});

test('cancelling native sharing never sends or retries', async () => {
  const app = ui();
  await new Promise(resolve => setImmediate(resolve));
  app.win.navigator.share = () => {app.calls.push('cancel'); return Promise.reject({name: 'AbortError'});};
  await app.nodes['image-share'].listeners.click();
  assert.equal(app.calls.length, 1);
  assert.equal(app.nodes['image-share'].disabled, false);
});
