/* Exact text/price rendering, entirely on-device. No screenshot service or CDN. */
(function () {
  "use strict";
  const WIDTH = 540, PAD = 22, BODY = WIDTH - PAD * 2;
  const FONT = '"Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif';
  const C = {ink: "#17263b", muted: "#586b80", navy: "#122238", mint: "#9edbcd",
    line: "#dce4ed", pale: "#f1f5fa", up: "#c32d4b", down: "#1768ae"};
  const color = direction => C[direction] || C.muted;
  const change = item => item.direction === "missing" ? "미확인" :
    `${String(item.percent).trim().replace(/[%％]+$/, "").trimEnd()}%`;

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

  function layout(data, ctx) {
    let y = PAD;
    const ops = [];
    function rect(x, top, width, height, fill) {
      ops.push({kind: "rect", x, y: top, width, height, fill});
    }
    function paragraph(value, size = 16, fill = C.ink, weight = 400,
      x = PAD, width = BODY, leading = 1.28) {
      ctx.font = `${weight} ${size}px ${FONT}`;
      const lines = wrap(ctx, value, width);
      lines.forEach((line, n) => ops.push({kind: "text", value: line,
        x, y: y + n * size * leading, size, fill, weight}));
      y += lines.length * size * leading;
    }
    function heading(label) {
      y += 11;
      rect(PAD, y, 3, 19, "#287667");
      paragraph(label, 17, C.ink, 700, PAD + 12, BODY - 12);
      y += 6;
    }
    function rule() { rect(PAD, y, BODY, 1, C.line); y += 7; }
    function pair(left, right, rightColor = C.ink, size = 16, weight = 600) {
      const top = y;
      ctx.font = `${weight} ${size}px ${FONT}`;
      const rightWidth = Math.min(BODY * .62, Math.max(BODY * .45, ctx.measureText(right).width));
      const col = BODY - rightWidth - 12;
      paragraph(left, size, C.ink, weight, PAD, col);
      const leftEnd = y;
      y = top;
      paragraph(right, size, rightColor, weight, PAD + col + 12, rightWidth);
      y = Math.max(leftEnd, y) + 3;
    }
    // Put a bold label and its complete explanation in one flowing paragraph.
    function inline(label, detail, size = 16) {
      const start = ops.length, value = `${label} · ${detail}`;
      paragraph(value, size, C.ink, 600);
      let cursor = 0;
      for (const op of ops.splice(start)) {
        const offset = value.indexOf(op.value, cursor);
        const count = Math.max(0, Math.min(label.length - offset, op.value.length));
        const prefix = op.value.slice(0, count), rest = op.value.slice(count);
        if (prefix) ops.push({...op, value: prefix});
        if (rest) {
          ctx.font = `600 ${size}px ${FONT}`;
          ops.push({...op, value: rest, x: op.x + ctx.measureText(prefix).width,
            weight: 400, fill: C.muted});
        }
        cursor = offset + op.value.length;
      }
    }

    rect(0, 0, WIDTH, 0, C.navy); // Its final height is measured below.
    paragraph(data.title, 20, "#ffffff", 700);
    y += 4;
    paragraph(`${data.as_of} 기준`, 12, "#c7d6e6");
    if (data.is_test) {
      y += 7;
      paragraph("TEST · 레이아웃 확인용 자료 · 실제 시세 아님", 13, C.mint, 700);
    }
    y += 13;
    ops[0].height = y;
    y += 12;
    paragraph("오늘의 결론", 12, "#287667", 700);
    y += 5;
    paragraph(data.headline, 22, C.ink, 700, PAD, BODY, 1.25);
    y += 6;
    for (const point of data.summary_points) {
      paragraph(`• ${point}`, 16);
      y += 2;
    }
    y += 5;
    rule();
    for (const item of data.indices) {
      pair(item.name, `${item.value} ${item.unit}  ${change(item)}`, color(item.direction), 16);
      if (item.missing_reason) paragraph(item.missing_reason, 13, C.muted);
    }
    const fx = data.fx;
    pair(fx.label, `${fx.value} ${fx.unit} (${fx.delta} ${fx.unit})`, color(fx.direction), 14, 600);
    paragraph(`기준 · ${fx.session} · ${fx.as_of}`, 11, C.muted);
    y += 4;
    for (const notice of new Set(data.notices)) {
      paragraph(`※ ${notice}`, 13, C.muted);
      y += 2;
    }
    heading("핵심 이슈 3");
    data.issues.forEach((issue, n) => {
      inline(`${n + 1}. ${issue.title}`, issue.preview);
      y += 6;
    });
    heading("관찰 종목 3");
    data.stocks.forEach(stock => {
      pair(`${stock.name} · ${stock.ticker}`, `${stock.price} ${stock.currency}  ${change(stock)}`,
        color(stock.direction), 16);
      paragraph(`${stock.session} · ${stock.as_of}`, 11, C.muted);
      if (stock.missing_reason) {
        y += 4;
        paragraph(`※ ${stock.missing_reason}`, 13, C.muted);
      }
      y += 3;
      paragraph(`${stock.reason} 확인 · ${stock.watch}`, 16, C.muted);
      y += 6;
      rule();
    });
    heading("다음 확인");
    data.next_checks.forEach(item => {
      inline(`${item.label} · ${item.title}`, item.detail);
      y += 5;
    });
    y += 5;
    rule();
    paragraph("관찰용 자료 · 투자 권유 아님", 11, C.muted);
    return {width: WIDTH, height: Math.ceil(y + PAD), ops};
  }

  function createCanvas(data, doc) {
    const canvas = doc.createElement("canvas"), ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("이 브라우저에서는 이미지를 만들 수 없어요.");
    const plan = layout(data, ctx);
    // Bound memory for exceptionally verbose legacy reports, without truncation.
    const scale = Math.min(2, 8192 / plan.height, Math.sqrt(16000000 / (WIDTH * plan.height)));
    canvas.width = Math.ceil(plan.width * scale);
    canvas.height = Math.ceil(plan.height * scale);
    ctx.scale(scale, scale);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, plan.width, plan.height);
    ctx.textBaseline = "top";
    for (const op of plan.ops) {
      ctx.fillStyle = op.fill;
      if (op.kind === "rect") ctx.fillRect(op.x, op.y, op.width, op.height);
      else {
        ctx.font = `${op.weight} ${op.size}px ${FONT}`;
        ctx.fillText(op.value, op.x, op.y);
      }
    }
    return canvas;
  }

  function init(doc, win) {
    const dataEl = doc.getElementById("brief-image-data");
    if (!dataEl) return;
    const data = JSON.parse(dataEl.textContent);
    data.report_url = new URL(data.report_path, win.location.href).href;
    const dialog = doc.getElementById("image-dialog"), status = doc.getElementById("image-status");
    const preview = doc.getElementById("image-preview"), download = doc.getElementById("image-download");
    const share = doc.getElementById("image-share"), retry = doc.getElementById("image-retry");
    const nav = win.navigator;
    let file = null, objectUrl = null, pending = null, lastFocus = null, sharing = false;
    const name = `market-brief-${data.id}.png`;
    function canShare() {
      try { return !!(file && nav.share && nav.canShare && nav.canShare({files: [file]})); }
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
      status.textContent = "한 장 이미지를 만들고 있어요…";
      pending = (async () => {
        if (doc.fonts) await doc.fonts.ready;
        const canvas = createCanvas(data, doc);
        const blob = await new Promise((resolve, reject) => canvas.toBlob(value =>
          value ? resolve(value) : reject(new Error("이미지 생성에 실패했어요.")), "image/png"));
        file = typeof win.File === "function" ? new win.File([blob], name, {type: "image/png"}) : null;
        objectUrl = win.URL.createObjectURL(blob);
        preview.src = objectUrl;
        preview.hidden = false;
        download.href = objectUrl;
        download.download = name;
        download.hidden = false;
        share.disabled = !canShare();
        status.textContent = canShare() ? "준비됐어요. 저장하거나 카카오톡으로 공유하세요." :
          "준비됐어요. 이 브라우저는 파일 공유를 지원하지 않아 PNG 저장을 이용해주세요.";
        canvas.width = canvas.height = 0; // Release the drawing surface after encoding.
        return blob;
      })().catch(() => {
        pending = null;
        retry.hidden = false;
        status.textContent = "이미지를 만들지 못했어요. 다시 만들기를 눌러주세요.";
        return null;
      });
      return pending;
    }
    // Never await image creation before share(): mobile requires a fresh gesture.
    async function shareFile() {
      if (sharing) return;
      if (!canShare()) { open(); prepare(); return; }
      sharing = true;
      share.disabled = true;
      try {
        await nav.share({files: [file], title: data.title});
        status.textContent = "공유 창을 닫았어요. 다른 곳에도 공유할 수 있어요.";
      } catch (error) {
        if (error.name !== "AbortError") {
          open();
          status.textContent = "공유 창을 열지 못했어요. PNG 저장 후 첨부하거나 미리보기를 길게 눌러주세요.";
        }
      } finally { sharing = false; share.disabled = !canShare(); }
    }
    doc.querySelector(".image-actions").hidden = false;
    doc.querySelectorAll("[data-image-action]").forEach(button => button.addEventListener("click", () => {
      if (button.dataset.imageAction === "share" && canShare()) shareFile();
      else { open(); prepare(); }
    }));
    share.addEventListener("click", shareFile);
    retry.addEventListener("click", prepare);
    doc.getElementById("image-close").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => { if (lastFocus) lastFocus.focus(); });
    download.addEventListener("click", () => {
      status.textContent = "PNG 저장을 요청했어요. 아이폰은 공유 → 이미지 저장 또는 미리보기 길게 누르기도 가능해요.";
    });
    // Prepare once, so the toolbar share button can open the native sheet directly.
    if (win.requestIdleCallback) win.requestIdleCallback(prepare, {timeout: 1200});
    else win.setTimeout(prepare, 0);
    win.addEventListener("pagehide", event => {
      if (!event.persisted && objectUrl) win.URL.revokeObjectURL(objectUrl);
    });
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {wrap, layout, createCanvas, init};
  else init(document, window);
})();
