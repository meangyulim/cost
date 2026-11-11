/* Share cards (1080×1350, 4:5) drawn entirely on-device with the page's own font.
   Every public field is drawn; long content flows onto more cards instead of being cut. */
(function () {
  "use strict";
  const W = 540, H = 675, PAD = 30, BODY = W - PAD * 2, SCALE = 2;
  const TOP = 84, BOTTOM = H - 54;
  const FONT = '"Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif';
  const C = {paper: "#FBFBF9", ink: "#14213D", ink2: "#2B3550", ink3: "#4A5470", line: "#D9DCE3",
    navy: "#14213D", navyLine: "#34436A", navyInk2: "#C3CBDD", navyInk3: "#A7B1C8", panel: "#F1F2F5",
    up: "#B0182F", down: "#1D4ED8", upNavy: "#FF9AA6", downNavy: "#9CC2FF", flat: "#4A5470",
    caution: "#6B4300", cautionBg: "#FFF1CF", white: "#FFFFFF"};
  const HEAT = {"up-4": ["#B0182F", C.white], "up-3": ["#C73049", C.white], "up-2": ["#F2A4AF", C.ink], "up-1": ["#F8CDD3", C.ink],
    "down-4": ["#1D4ED8", C.white], "down-3": ["#3563DC", C.white], "down-2": ["#A9C3F7", C.ink], "down-1": ["#D3E0FB", C.ink],
    flat: [C.panel, C.ink]};
  const DIRECTIONAL = ["up", "down"];
  // 시장 읽기 mood scale: the writer's interpretation, never an indicator.
  const MOODS = [["fear", "불안", "#A9C3F7"], ["caution", "경계", "#D3E0FB"], ["neutral", "중립", "#E1E4EA"],
    ["relief", "안도", "#F8CDD3"], ["euphoria", "들뜸", "#F2A4AF"]];
  const tone = (direction, onNavy) => ({up: onNavy ? C.upNavy : C.up, down: onNavy ? C.downNavy : C.down}[direction] || (onNavy ? C.navyInk2 : C.flat));
  const num = value => Number(String(value).replace(/,/g, "").replace(/−/g, "-").replace(/\+/g, "").replace(/[%％]\s*$/, "").trim());
  const change = item => item.direction === "missing" ? "미확인" : /(%p|bp)$/.test(String(item.percent).trim()) ?
    String(item.percent).trim() : `${String(item.percent).trim().replace(/[%％]+$/, "").trimEnd()}%`;

  function wrap(ctx, value, maxWidth) {
    const lines = [];
    for (const paragraph of String(value).split("\n")) {
      let line = "";
      for (const char of Array.from(paragraph)) {
        if (line && ctx.measureText(line + char).width > maxWidth) {
          const space = line.lastIndexOf(" ");
          if (space > line.length / 2) {
            lines.push(line.slice(0, space));
            line = line.slice(space + 1) + char;
          } else {
            lines.push(line.trimEnd());
            line = char.trimStart();
          }
        } else line += char;
      }
      lines.push(line.trimEnd());
    }
    return lines;
  }

  function heat(stock) {
    if (!DIRECTIONAL.includes(stock.direction)) return HEAT.flat;
    const size = Math.abs(num(stock.percent));
    const level = size >= 15 ? 4 : size >= 8 ? 3 : size >= 4 ? 2 : 1;
    return HEAT[`${stock.direction}-${level}`];
  }

  function layout(data, ctx) {
    // A unit is a block of ops drawn relative to its own top. Groups stay on one card when they fit.
    const groups = [];
    let group = null;
    function start(title, breakBefore) { group = {units: [], title, breakBefore}; groups.push(group); }
    function unit(h, ops, continueOps) { group.units.push({h, ops, continueOps}); }
    function measure(size, weight, value) { ctx.font = `${weight} ${size}px ${FONT}`; return ctx.measureText(value).width; }
    function lines(value, size, weight, fill, x = PAD, width = BODY, leading = 1.5, gapAfter = 0) {
      ctx.font = `${weight} ${size}px ${FONT}`;
      const rows = wrap(ctx, value, width);
      rows.forEach((row, n) => unit(size * leading + (n === rows.length - 1 ? gapAfter : 0),
        [{kind: "text", value: row, x, y: (size * leading - size) / 2, size, weight, fill}]));
    }
    function sectionTitle(title, note) {
      const ops = [{kind: "text", value: title, x: PAD, y: 0, size: 22, weight: 900, fill: C.ink},
        {kind: "rect", x: PAD, y: 36, width: BODY, height: 3, fill: C.navy}];
      if (note) ops.push({kind: "text", value: note, x: W - PAD - measure(12, 400, note), y: 9, size: 12, weight: 400, fill: C.ink3});
      unit(50, ops);
    }
    // Text with a coloured rule on its left; each row is its own unit so it can continue on the next card.
    function ruled(value, size, weight, fill, rule, gapAfter = 0) {
      ctx.font = `${weight} ${size}px ${FONT}`;
      const rows = wrap(ctx, value, BODY - 16);
      rows.forEach((row, n) => {
        const h = size * 1.6 + (n === rows.length - 1 ? gapAfter : 0);
        // Overlap the next row by 1px so a multi-row rule reads as one line.
        unit(h, [{kind: "rect", x: PAD, y: 0, width: 4, height: n === rows.length - 1 && gapAfter ? size * 1.6 : h + 1, fill: rule},
          {kind: "text", value: row, x: PAD + 16, y: size * 0.3, size, weight, fill}]);
      });
    }
    function rangeOps(range, value, x, y, width, onNavy) {
      if (!range) return [];
      const low = num(range.low), high = num(range.high), close = num(value);
      if (!(high > low)) return [];
      const at = v => x + (v - low) / (high - low) * width;
      const ops = [{kind: "rect", x, y: y + 5, width, height: 2, fill: onNavy ? C.navyLine : C.line}];
      if (range.open !== undefined) {
        const open = num(range.open), left = Math.min(open, close), right = Math.max(open, close);
        const dir = close > open ? "up" : close < open ? "down" : "flat";
        ops.push({kind: "rect", x: at(left), y: y + 3, width: Math.max(at(right) - at(left), 2), height: 6, fill: tone(dir, onNavy), radius: 3});
        ops.push({kind: "rect", x: at(open) - 1, y, width: 2, height: 12, fill: onNavy ? "#8A97B8" : C.ink3});
      }
      ops.push({kind: "circle", x: at(close), y: y + 6, r: onNavy ? 6 : 5, fill: onNavy ? C.white : C.ink, stroke: onNavy ? C.navy : C.paper});
      return ops;
    }

    // Card 1 · summary
    start("요약", false);
    lines(`${data.edition} · ${data.as_of} 기준`, 12, 700, C.ink3, PAD, BODY, 1.5, 6);
    lines(data.headline, 32, 900, C.ink, PAD, BODY, 1.3, 10);
    for (const point of data.summary_points) lines(point, 16, 400, C.ink2, PAD, BODY, 1.6);
    unit(14, []);
    const [first, ...others] = data.indices;
    const bandOps = [];
    let by = 16;
    bandOps.push({kind: "text", value: first.name.split(" · ")[0], x: PAD + 16, y: by + 6, size: 13, weight: 400, fill: C.navyInk2});
    const firstChange = change(first);
    const changeW = measure(15, 700, firstChange);
    bandOps.push({kind: "text", value: firstChange, x: W - PAD - 16 - changeW, y: by + 4, size: 15, weight: 700, fill: tone(first.direction, true)});
    let firstSize = 24;
    while (firstSize > 12 && measure(firstSize, 700, first.value) + measure(13, 400, first.name.split(" · ")[0]) + changeW + 52 > BODY) firstSize -= 1;
    bandOps.push({kind: "text", value: first.value, x: W - PAD - 26 - changeW - measure(firstSize, 700, first.value), y: by + (24 - firstSize), size: firstSize, weight: 700, fill: C.white});
    by += 40;
    if (first.direction === "missing" && first.missing_reason) {
      ctx.font = `400 12px ${FONT}`;
      for (const row of wrap(ctx, first.missing_reason, BODY - 32)) {
        bandOps.push({kind: "text", value: row, x: PAD + 16, y: by, size: 12, weight: 400, fill: C.navyInk2}); by += 18;
      }
    }
    if (first.range) {
      bandOps.push(...rangeOps(first.range, first.value, PAD + 16, by, BODY - 32, true));
      by += 20;
      const low = `저 ${first.range.low}`, high = `고 ${first.range.high}`;
      bandOps.push({kind: "text", value: low, x: PAD + 16, y: by, size: 11, weight: 400, fill: C.navyInk3});
      if (first.range.prev_close !== undefined) {
        const prev = `전일 ${first.range.prev_close}`;
        bandOps.push({kind: "text", value: prev, x: W / 2 - measure(11, 400, prev) / 2, y: by, size: 11, weight: 400, fill: C.navyInk3});
      }
      bandOps.push({kind: "text", value: high, x: W - PAD - 16 - measure(11, 400, high), y: by, size: 11, weight: 400, fill: C.navyInk3});
      by += 22;
    }
    const cells = others.map(item => ({name: item.name.split(" · ")[0], value: item.value, change: change(item), direction: item.direction,
      note: item.direction === "missing" ? item.missing_reason : ""}));
    const fxDelta = String(data.fx.delta).trim();
    cells.push({name: data.fx.label.split(" · ")[0], value: data.fx.value + (data.fx.unit === "%" ? "%" : ""),
      change: /^[+−-]?[\d.,]+$/.test(fxDelta) ? `${fxDelta} ${data.fx.unit}` : fxDelta, direction: data.fx.direction, note: ""});
    bandOps.push({kind: "rect", x: PAD + 16, y: by, width: BODY - 32, height: 1, fill: C.navyLine});
    by += 12;
    const colW = (BODY - 32) / 2;
    for (let n = 0; n < cells.length; n += 2) {
      let rowH = 44;
      for (const [k, cell] of cells.slice(n, n + 2).entries()) {
        const x = PAD + 16 + k * colW + (k ? 12 : 0), width = colW - 14;
        ctx.font = `400 12px ${FONT}`;
        const nameRows = wrap(ctx, cell.name, width);
        nameRows.forEach((row, i) => bandOps.push({kind: "text", value: row, x, y: by + i * 17, size: 12, weight: 400, fill: C.navyInk2}));
        let cy = by + nameRows.length * 17 + 2;
        let valueSize = 17;
        while (valueSize > 10 && measure(valueSize, 700, cell.value) > width) valueSize -= 1;
        bandOps.push({kind: "text", value: cell.value, x, y: cy + (17 - valueSize), size: valueSize, weight: 700, fill: C.white});
        const valueW = measure(valueSize, 700, cell.value);
        if (valueW + 8 + measure(13, 700, cell.change) <= width) {
          bandOps.push({kind: "text", value: cell.change, x: x + valueW + 8, y: cy + 3, size: 13, weight: 700, fill: tone(cell.direction, true)});
          cy += 24;
        } else {
          cy += 24;
          ctx.font = `700 13px ${FONT}`;
          for (const row of wrap(ctx, cell.change, width)) {
            bandOps.push({kind: "text", value: row, x, y: cy, size: 13, weight: 700, fill: tone(cell.direction, true)});
            cy += 19;
          }
        }
        if (cell.note) {
          for (const row of wrap(ctx, cell.note, width)) { bandOps.push({kind: "text", value: row, x, y: cy, size: 12, weight: 400, fill: C.navyInk2}); cy += 17; }
        }
        if (k) bandOps.push({kind: "rect", x: x - 12, y: by, width: 1, height: Math.max(cy - by, 36), fill: C.navyLine});
        rowH = Math.max(rowH, cy - by + 6);
      }
      by += rowH;
    }
    by += 8;
    unit(by + 12, [{kind: "rect", x: PAD, y: 0, width: BODY, height: by, fill: C.navy, radius: 6}, ...bandOps]);
    if (data.key_figure) {
      const kf = data.key_figure, kfW = measure(36, 900, kf.value);
      const ops = [{kind: "text", value: kf.value, x: PAD, y: 2, size: 36, weight: 900, fill: tone(kf.direction || "flat", false)}];
      const label = kf.label + (kf.note ? ` · ${kf.note}` : "");
      ctx.font = `400 14px ${FONT}`;
      const rows = wrap(ctx, label, BODY - kfW - 16);
      rows.forEach((row, n) => ops.push({kind: "text", value: row, x: PAD + kfW + 16, y: 6 + n * 21, size: 14, weight: 400, fill: C.ink2}));
      unit(Math.max(52, rows.length * 21 + 14), ops);
    }
    unit(6, [{kind: "rect", x: PAD, y: 0, width: BODY, height: 1, fill: C.line}]);
    for (const notice of data.notices) lines(`※ ${notice}`, 14, 400, C.caution, PAD, BODY, 1.55, 4);

    // Card · 시장 읽기
    const rd = data.reading;
    if (rd && rd.legacy) {
      start("시장 읽기", false); // Two sentences: share the summary card when they fit.
      sectionTitle("시장 읽기", "이전 형식 요약 · 검증 전");
      for (const item of rd.legacy) {
        lines(`${item.label} · ${item.plain}`, 16, 700, C.ink, PAD, BODY, 1.5, 2);
        lines(item.condition, 14, 400, C.ink3, PAD, BODY, 1.55, 12);
      }
      lines(`${rd.written} · 확률 아님`, 11, 400, C.ink3, PAD, BODY, 1.5);
      lines(rd.note, 11, 400, C.ink3, PAD, BODY, 1.5);
    } else if (rd) {
      start("시장 읽기", true);
      sectionTitle("시장 읽기", "해석 · 검증 전");
      lines(rd.headline, 22, 900, C.ink, PAD, BODY, 1.4, 12);
      const segW = (BODY - 16) / 5, moodOps = [
        {kind: "text", value: "시장 분위기", x: PAD, y: 0, size: 12, weight: 700, fill: C.ink},
        {kind: "text", value: "작성자 해석 · 지표 아님", x: W - PAD - measure(11, 400, "작성자 해석 · 지표 아님"), y: 1, size: 11, weight: 400, fill: C.ink3}];
      MOODS.forEach(([key, name, color], n) => {
        const x = PAD + n * (segW + 4), on = key === rd.mood;
        if (on) moodOps.push({kind: "rect", x: x - 2, y: 22, width: segW + 4, height: 14, fill: C.ink, radius: 3});
        moodOps.push({kind: "rect", x, y: 24, width: segW, height: 10, fill: color, radius: 2});
        moodOps.push({kind: "text", value: name, x: x + segW / 2 - measure(12, on ? 900 : 400, name) / 2, y: 42, size: 12, weight: on ? 900 : 400, fill: on ? C.ink : C.ink3});
      });
      unit(66, moodOps);
      lines(rd.mood_note, 13, 400, C.ink2, PAD, BODY, 1.55, 12);
      rd.drivers.forEach((item, n) => {
        start(null, false);
        if (!n) lines("왜 이런 분위기일까", 15, 700, C.ink, PAD, BODY, 1.5, 4);
        ctx.font = `700 15px ${FONT}`;
        const titleRows = wrap(ctx, item.title, BODY - 30);
        ctx.font = `400 14px ${FONT}`;
        const textRows = wrap(ctx, item.text, BODY - 30);
        const ops = [{kind: "circle", x: PAD + 10, y: 11, r: 10, fill: C.navy},
          {kind: "text", value: String(n + 1), x: PAD + 10 - measure(12, 700, String(n + 1)) / 2, y: 4, size: 12, weight: 700, fill: C.white}];
        let y = 0;
        titleRows.forEach(row => { ops.push({kind: "text", value: row, x: PAD + 30, y: y + 2, size: 15, weight: 700, fill: C.ink}); y += 23; });
        unit(y, ops);
        for (const row of textRows) unit(22, [{kind: "text", value: row, x: PAD + 30, y: 2, size: 14, weight: 400, fill: C.ink2}]);
        unit(10, []);
      });
      for (const item of rd.history) {
        start(null, false);
        unit(4, []);
        ruled(`과거엔 · ${item.title}`, 13, 700, C.ink, C.navy, 2);
        ruled(`그날 · ${item.then}`, 13, 400, C.ink2, C.navy);
        ruled(`다음 날 · ${item.next}`, 13, 400, C.ink2, C.navy);
        ruled(`그 뒤 · ${item.after}`, 13, 400, C.ink2, C.navy);
        ruled(`이번과 다른 점 · ${item.difference}`, 13, 400, C.ink, C.navy);
        lines("같은 흐름이 반복된다는 뜻은 아니에요", 11, 400, C.ink3, PAD + 16, BODY - 16, 1.6, 10);
      }
      start(null, false);
      ruled(`좋은 쪽 · ${rd.paths.good}`, 14, 400, C.ink, C.up, 8);
      ruled(`조심할 쪽 · ${rd.paths.caution}`, 14, 400, C.ink, C.down, 10);
      lines(`출처 기반 해석 · 검증 전 · 확률이나 목표가 아님 · ${rd.written}`, 11, 400, C.ink3, PAD, BODY, 1.5);
    }

    // Card · stories
    start(`이야기 ${data.issues.length}`, true);
    sectionTitle(`이야기 ${data.issues.length}`, "핵심 이슈");
    data.issues.forEach((issue, n) => {
      if (n) start(null, false);
      ctx.font = `700 17px ${FONT}`;
      const titleRows = wrap(ctx, issue.title, BODY - 34);
      ctx.font = `400 14px ${FONT}`;
      const previewRows = wrap(ctx, issue.preview, BODY - 34);
      const ops = [{kind: "text", value: String(n + 1), x: PAD, y: 2, size: 22, weight: 900, fill: C.ink}];
      let y = 0;
      titleRows.forEach(row => { ops.push({kind: "text", value: row, x: PAD + 34, y: y + 3, size: 17, weight: 700, fill: C.ink}); y += 26; });
      previewRows.forEach(row => { ops.push({kind: "text", value: row, x: PAD + 34, y: y + 2, size: 14, weight: 400, fill: C.ink3}); y += 22; });
      unit(y + 6, ops);
      unit(12, [{kind: "rect", x: PAD, y: 5, width: BODY, height: 1, fill: C.line}]);
    });

    // Card · stocks
    start(`관찰 종목 ${data.stocks.length}`, true);
    sectionTitle(`관찰 종목 ${data.stocks.length}`, "전일 대비");
    const ranked = [...data.stocks].sort((a, b) => (DIRECTIONAL.includes(b.direction) || b.direction === "flat" ? num(b.percent) : -1e9) -
      (DIRECTIONAL.includes(a.direction) || a.direction === "flat" ? num(a.percent) : -1e9));
    // State the most common price basis once; stocks priced on another basis keep their own line.
    const counts = new Map();
    for (const stock of data.stocks) {
      const key = `${stock.session} · ${stock.as_of}`;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    const shared = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
    lines(`가격 기준 · ${shared}${counts.size > 1 ? " (다른 기준은 종목에 표시)" : ""}`, 12, 400, C.ink3, PAD, BODY, 1.5, 6);
    const tileW = (BODY - 18) / 4;
    for (let n = 0; n < ranked.length; n += 4) {
      const ops = [];
      ranked.slice(n, n + 4).forEach((stock, k) => {
        const [bg, fg] = heat(stock), x = PAD + k * (tileW + 6);
        ops.push({kind: "rect", x, y: 0, width: tileW, height: 54, fill: bg, radius: 5});
        ctx.font = `700 12px ${FONT}`;
        const rows = wrap(ctx, stock.name, tileW - 16);
        const name = rows.length > 1 ? wrap(ctx, stock.name, tileW - 16 - measure(12, 700, "…"))[0] + "…" : rows[0];
        ops.push({kind: "text", value: name, x: x + 8, y: 7, size: 12, weight: 700, fill: fg});
        let pctSize = 16;
        while (pctSize > 10 && measure(pctSize, 900, change(stock)) > tileW - 16) pctSize -= 1;
        ops.push({kind: "text", value: change(stock), x: x + 8, y: 27 + (16 - pctSize), size: pctSize, weight: 900, fill: fg});
      });
      unit(60, ops);
    }
    unit(8, []);
    for (const stock of data.stocks) {
      start(null, false);
      const quote = `${stock.price}${stock.currency === "KRW" ? "" : " " + stock.currency}`;
      const pct = change(stock), pctW = measure(15, 700, pct), quoteW = measure(14, 400, quote);
      ctx.font = `700 16px ${FONT}`;
      const nameRows = wrap(ctx, `${stock.name} ${stock.ticker}`, BODY - pctW - quoteW - 24);
      const ops = [];
      nameRows.forEach((row, n) => ops.push({kind: "text", value: row, x: PAD, y: n * 24 + 2, size: 16, weight: 700, fill: C.ink}));
      ops.push({kind: "text", value: pct, x: W - PAD - pctW, y: 3, size: 15, weight: 700, fill: tone(stock.direction, false)});
      ops.push({kind: "text", value: quote, x: W - PAD - pctW - 10 - quoteW, y: 4, size: 14, weight: 400, fill: C.ink});
      unit(nameRows.length * 24 + 4, [{kind: "rect", x: PAD, y: 0, width: BODY, height: 1, fill: C.line}, ...ops.map(op => ({...op, y: op.y + 8}))]);
      if (stock.range) unit(20, rangeOps(stock.range, stock.price, PAD, 4, BODY, false));
      if (`${stock.session} · ${stock.as_of}` !== shared) lines(`${stock.session} · ${stock.as_of}`, 11, 400, C.ink3, PAD, BODY, 1.5);
      if (stock.missing_reason) lines(stock.missing_reason, 13, 400, C.ink3, PAD, BODY, 1.5);
      lines(stock.reason, 14, 400, C.ink2, PAD, BODY, 1.55);
      lines(`확인 · ${stock.watch}`, 14, 400, C.ink3, PAD, BODY, 1.55, 2);
      unit(6, []);
    }

    // Card · calendar
    start("달력", true);
    sectionTitle("달력", `다음 확인 ${data.next_checks.length}`);
    let firstEvent = true;
    for (const day of data.calendar) {
      day.events.forEach((event, n) => {
        if (!firstEvent) start(null, false);
        firstEvent = false;
        const big = day.day.length > 2 ? 15 : 24;
        const centered = (size, weight, value) => Math.max(PAD, PAD + 24 - measure(size, weight, value) / 2);
        const dateOps = [{kind: "text", value: day.day, x: centered(big, 900, day.day), y: 0, size: big, weight: 900, fill: day.today ? C.up : C.ink}];
        if (day.sub) dateOps.push({kind: "text", value: day.sub, x: centered(11, 400, day.sub), y: big + 8, size: 11, weight: 400, fill: C.ink3});
        const ops = n === 0 ? [...dateOps] : [];
        const x = PAD + 60, width = BODY - 60;
        let y = 0;
        ctx.font = `700 15px ${FONT}`;
        for (const row of wrap(ctx, (event.when ? `${event.when}  ` : "") + event.title, width)) {
          ops.push({kind: "text", value: row, x, y: y + 2, size: 15, weight: 700, fill: C.ink}); y += 23;
        }
        ctx.font = `400 13px ${FONT}`;
        for (const row of wrap(ctx, event.detail, width)) {
          ops.push({kind: "text", value: row, x, y: y + 1, size: 13, weight: 400, fill: C.ink3}); y += 20;
        }
        unit(Math.max(y, 44) + 6, ops, n === 0 ? null : dateOps);
        if (n === day.events.length - 1) unit(12, [{kind: "rect", x: PAD, y: 5, width: BODY, height: 1, fill: C.line}]);
      });
    }

    // Paginate: a group moves to a fresh card when it fits there; taller groups break between units.
    const pages = [];
    let page = null, y = 0, section = "요약", fresh = false;
    function newPage(continued) {
      page = {ops: [], section, continued};
      pages.push(page);
      y = TOP + (data.is_test ? 34 : 0);
      if (continued) {
        page.ops.push({kind: "text", value: `${section} (이어서)`, x: PAD, y, size: 13, weight: 700, fill: C.ink3, frame: true});
        y += 26;
      }
      fresh = true;
    }
    for (const g of groups) {
      if (g.title) section = g.title;
      const height = g.units.reduce((sum, u) => sum + u.h, 0);
      if (!page || g.breakBefore) newPage(false);
      else if (y + height > BOTTOM && height <= BOTTOM - TOP - 60) newPage(true);
      for (const u of g.units) {
        if (y + u.h > BOTTOM && y > TOP + 40) newPage(true);
        for (const op of u.ops.concat(fresh && u.continueOps ? u.continueOps : [])) page.ops.push({...op, y: op.y + y});
        fresh = false;
        y += u.h;
      }
    }
    pages.forEach((p, n) => {
      const frame = [];
      frame.push({kind: "text", value: "코스트 브리핑", x: PAD, y: 30, size: 20, weight: 900, fill: C.ink});
      const right = `${data.date_label} · ${data.edition}`;
      frame.push({kind: "text", value: right, x: W - PAD - measure(12, 400, right), y: 37, size: 12, weight: 400, fill: C.ink3});
      frame.push({kind: "rect", x: PAD, y: 64, width: BODY, height: 4, fill: C.navy});
      if (data.is_test) {
        frame.push({kind: "rect", x: PAD, y: TOP - 4, width: BODY, height: 26, fill: C.cautionBg, radius: 4});
        frame.push({kind: "text", value: "TEST · 레이아웃 확인용 자료 · 실제 시세 아님", x: PAD + 10, y: TOP + 1, size: 12, weight: 700, fill: C.caution});
      }
      frame.push({kind: "rect", x: PAD, y: H - 44, width: BODY, height: 1, fill: C.line});
      frame.push({kind: "text", value: "관찰용 자료 · 투자 권유 아님", x: PAD, y: H - 34, size: 11, weight: 400, fill: C.ink3});
      const count = `${n + 1} / ${pages.length}`;
      frame.push({kind: "text", value: count, x: W - PAD - measure(11, 700, count), y: H - 34, size: 11, weight: 700, fill: C.ink});
      p.ops = frame.map(op => ({...op, frame: true})).concat(p.ops);
    });
    return {width: W, height: H, pages};
  }

  function draw(ctx, op) {
    if (op.kind === "text") {
      ctx.font = `${op.weight} ${op.size}px ${FONT}`;
      ctx.fillStyle = op.fill;
      ctx.fillText(op.value, op.x, op.y);
    } else if (op.kind === "rect") {
      ctx.fillStyle = op.fill;
      if (op.radius && ctx.beginPath) {
        roundPath(ctx, op.x, op.y, op.width, op.height, op.radius); ctx.fill();
      } else ctx.fillRect(op.x, op.y, op.width, op.height);
    } else if (op.kind === "circle") {
      ctx.beginPath(); ctx.arc(op.x, op.y, op.r, 0, Math.PI * 2);
      ctx.fillStyle = op.fill; ctx.fill();
      if (op.stroke) { ctx.strokeStyle = op.stroke; ctx.lineWidth = op.lineWidth || 2; ctx.stroke(); }
    }
  }

  function roundPath(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h - r); ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
    ctx.lineTo(x + r, y + h); ctx.arcTo(x, y + h, x, y + h - r, r);
    ctx.lineTo(x, y + r); ctx.arcTo(x, y, x + r, y, r); ctx.closePath();
  }

  function createCanvases(data, doc) {
    const probe = doc.createElement("canvas").getContext("2d");
    if (!probe) throw new Error("이 브라우저에서는 이미지를 만들 수 없어요.");
    const plan = layout(data, probe);
    return plan.pages.map(page => {
      const canvas = doc.createElement("canvas"), ctx = canvas.getContext("2d");
      canvas.width = W * SCALE;
      canvas.height = H * SCALE;
      ctx.scale(SCALE, SCALE);
      ctx.fillStyle = C.paper;
      ctx.fillRect(0, 0, W, H);
      ctx.textBaseline = "top";
      for (const op of page.ops) draw(ctx, op);
      return canvas;
    });
  }

  async function loadFonts(doc) {
    if (!doc.fonts) return;
    if (doc.fonts.load) {
      try { await Promise.all(["400", "700", "900"].map(weight => doc.fonts.load(`${weight} 16px "Noto Sans KR"`, "가나다 0123 ▲▼"))); }
      catch (_) { /* Fall back to the system Korean face. */ }
    }
    await doc.fonts.ready;
  }

  function init(doc, win) {
    const dataEl = doc.getElementById("brief-image-data");
    if (!dataEl) return;
    const data = JSON.parse(dataEl.textContent);
    data.report_url = new URL(data.report_path, win.location.href).href;
    const dialog = doc.getElementById("image-dialog"), status = doc.getElementById("image-status");
    const previews = doc.getElementById("image-previews");
    const share = doc.getElementById("image-share"), retry = doc.getElementById("image-retry");
    const nav = win.navigator;
    let files = [], urls = [], pending = null, lastFocus = null, sharing = false;
    function canShare() {
      try { return !!(files.length && nav.share && nav.canShare && nav.canShare({files})); }
      catch (_) { return false; }
    }
    function open() {
      if (dialog.open) return;
      lastFocus = doc.activeElement;
      dialog.showModal();
    }
    function prepare() {
      if (pending) return pending;
      retry.hidden = true;
      status.textContent = "카드를 만들고 있어요…";
      pending = (async () => {
        await loadFonts(doc);
        const canvases = createCanvases(data, doc);
        const blobs = [];
        for (const canvas of canvases) {
          blobs.push(await new Promise((resolve, reject) => canvas.toBlob(value =>
            value ? resolve(value) : reject(new Error("이미지 생성에 실패했어요.")), "image/png")));
          canvas.width = canvas.height = 0; // Release each drawing surface after encoding.
        }
        files = typeof win.File === "function" ? blobs.map((blob, n) =>
          new win.File([blob], `cost-brief-${data.id}-${n + 1}.png`, {type: "image/png"})) : [];
        urls = blobs.map(blob => win.URL.createObjectURL(blob));
        if (previews.replaceChildren) previews.replaceChildren();
        urls.forEach((url, n) => {
          const figure = doc.createElement("figure"), img = doc.createElement("img"), link = doc.createElement("a");
          img.src = url;
          img.alt = `카드 ${n + 1} / ${urls.length}`;
          link.href = url;
          link.download = `cost-brief-${data.id}-${n + 1}.png`;
          link.textContent = `${n + 1} / ${urls.length} 저장`;
          if (figure.append) figure.append(img, link);
          if (previews.append) previews.append(figure);
        });
        share.disabled = !canShare();
        status.textContent = canShare() ? `카드 ${urls.length}장이 준비됐어요. 모두 공유하거나 한 장씩 저장하세요.` :
          `카드 ${urls.length}장이 준비됐어요. 이 브라우저는 파일 공유를 지원하지 않아 카드별 PNG 저장을 이용해주세요.`;
        return blobs;
      })().catch(() => {
        pending = null;
        retry.hidden = false;
        status.textContent = "카드를 만들지 못했어요. 다시 만들기를 눌러주세요.";
        return null;
      });
      return pending;
    }
    // Never await card creation before share(): mobile requires a fresh gesture.
    async function shareFiles() {
      if (sharing) return;
      if (!canShare()) { open(); prepare(); return; }
      sharing = true;
      share.disabled = true;
      try {
        await nav.share({files, title: data.title});
        status.textContent = "공유 창을 닫았어요. 다른 곳에도 공유할 수 있어요.";
      } catch (error) {
        if (error.name !== "AbortError") {
          open();
          status.textContent = "공유 창을 열지 못했어요. 카드별 PNG 저장 후 첨부하거나 미리보기를 길게 눌러주세요.";
        }
      } finally { sharing = false; share.disabled = !canShare(); }
    }
    doc.querySelectorAll("[data-image-action]").forEach(button => {
      button.hidden = false;
      button.addEventListener("click", () => {
        if (button.dataset.imageAction === "share" && canShare()) shareFiles();
        else { open(); prepare(); }
      });
    });
    share.addEventListener("click", shareFiles);
    retry.addEventListener("click", prepare);
    doc.getElementById("image-close").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => { if (lastFocus) lastFocus.focus(); });
    // Prepare once, so the masthead share button can open the native sheet directly.
    if (win.requestIdleCallback) win.requestIdleCallback(prepare, {timeout: 1500});
    else win.setTimeout(prepare, 0);
    win.addEventListener("pagehide", event => {
      if (!event.persisted) urls.forEach(url => win.URL.revokeObjectURL(url));
    });
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {wrap, layout, createCanvases, init};
  else init(document, window);
})();
