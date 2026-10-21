const TradingChart = (() => {
  // ─── Bảng màu (đồng bộ với chart.py) ────────────────────────────────────────
  const CLR = {
    bg:         "#FFFFFF",
    border:     "#BCD9F2",
    text:       "#1B2A4A",
    grid:       "#E5EEF7",
    candleUp:   "#19734A",              // Xanh lá – close cao hơn tham chiếu
    candleDown: "#C43D4F",              // Đỏ – close thấp hơn tham chiếu
    reference:  "#A66A00",              // Vàng đậm – giá tham chiếu
    floor:      "#2166A5",              // Xanh dương – giá sàn (90%)
    ceiling:    "#7040A0",              // Tím – giá trần (110%)
    closeLine:  "#1B2A4A",              // Đường close xanh đậm
    bandGreen:  "rgba(25,115,74,0.18)",
    bandRed:    "rgba(196,61,79,0.16)",
    guideHigh:  "#19734A",
    guideLow:   "#C43D4F",
  };

  // CHART-001: Map point_color string → màu canvas
  const POINT_CLR = {
    ceiling:   CLR.ceiling,
    floor:     CLR.floor,
    up:        CLR.candleUp,
    down:      CLR.candleDown,
    reference: CLR.reference,
  };

  // CHART-008: chỉ rút thưa nến; đường close và dữ liệu gốc vẫn giữ mọi ngày.
  const CANDLE_CLOSE_THRESHOLD = 0.005; // close lệch tham chiếu ít nhất 0,5%
  const CANDLE_RANGE_THRESHOLD = 0.01;  // high-low ít nhất 1% tham chiếu

  let canvas, ctx, data, visible = 0;

  const fmt = (v) =>
    new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);

  function setup(target) {
    canvas = target;
    ctx = canvas.getContext("2d");
    resize();
    window.addEventListener("resize", resize);
  }

  function resize() {
    if (!canvas || !ctx) return;
    const ratio = window.devicePixelRatio || 1;
    const box   = canvas.getBoundingClientRect();
    canvas.width  = Math.max(1, Math.floor(box.width  * ratio));
    canvas.height = Math.max(1, Math.floor(box.height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    draw();
  }

  function ln(x1, y1, x2, y2, color, lw = 1, dash = []) {
    ctx.save();
    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.setLineDash(dash);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.restore();
  }

  function tx(str, x, y, color, align) {
    ctx.fillStyle = color || CLR.text;
    ctx.textAlign = align || "left";
    ctx.fillText(str, x, y);
  }


  // ─── Hàm vẽ chính ─────────────────────────────────────────────────────────
  function draw() {
    if (!data || !ctx) return;

    const { width, height } = canvas.getBoundingClientRect();
    const PAD   = { left: 0, right: 92, top: 12, bottom: 38 };
    const GAP   = 24;
    const pH    = (height - PAD.top - PAD.bottom - GAP) / 2;
    const upTop = PAD.top;
    const loTop = PAD.top + pH + GAP;
    const YMAX = 20000;
    const yPos = (v, t) => t + ((YMAX - v) / YMAX) * pH;

    // ── 1. Nền & font ─────────────────────────────────────────────────────────
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = CLR.bg;
    ctx.fillRect(0, 0, width, height);
    ctx.font = "12px Arial, sans-serif";
    const yLabelWidth = ctx.measureText(fmt(YMAX)).width;
    PAD.left = Math.max(104, yLabelWidth + 60);
    const right = width - PAD.right;
    const pW = right - PAD.left;
    const plotLeft = PAD.left + 12;
    const plotRight = right - 12;
    let displaySlotCount = 1;
    const xPos = (slot) => displaySlotCount <= 1
      ? (plotLeft + plotRight) / 2
      : plotLeft + (slot / (displaySlotCount - 1)) * (plotRight - plotLeft);

    // ── 2. Lưới ngang & nhãn trục Y ──────────────────────────────────────────
    [0, 5000, 10000, 15000, 20000].forEach((v) => {
      const uy = yPos(v, upTop);
      const ly = yPos(v, loTop);
      if (v > 0 && v < YMAX) {
        ln(PAD.left, uy, right, uy, CLR.grid);
        ln(PAD.left, ly, right, ly, CLR.grid);
      }
      tx(fmt(v), PAD.left - 8, uy + 4, CLR.text, "right");
      tx(fmt(v), PAD.left - 8, ly + 4, CLR.text, "right");
    });

    // ── 3. Viền hai panel ─────────────────────────────────────────────────────
    ctx.strokeStyle = CLR.border; ctx.lineWidth = 1.5;
    ctx.strokeRect(PAD.left, upTop, pW, pH);
    ctx.strokeRect(PAD.left, loTop, pW, pH);

    // Nhãn VND xoay dọc
    [upTop, loTop].forEach((top) => {
      const midY = top + pH / 2;
      ctx.save();
      ctx.fillStyle = CLR.text; ctx.textAlign = "center";
      const unitX = Math.max(8, PAD.left - yLabelWidth - 42);
      ctx.translate(unitX, midY); ctx.rotate(-Math.PI / 2);
      ctx.fillText("VND", 0, 0);
      ctx.restore();
    });

    // ── 4. Trục X ─────────────────────────────────────────────────────────────
    ctx.font = "12px Arial, sans-serif";
    tx("Date", (PAD.left + right) / 2, height - 5, CLR.text, "center");

    // ── 6. Nội dung animation (chỉ khi đang phát) ────────────────────────────
    if (!visible || !data.days.length) return;

    const days  = data.days.slice(0, visible);

    // ════════════════════════════════════════════════════════════════════════
    // PANEL TRÊN – OHLC candles with density-aware grouping (CHART-013)
    // ════════════════════════════════════════════════════════════════════════
    const candleDays = days.filter((day) =>
      Math.abs(day.close - day.reference) / day.reference >= CANDLE_CLOSE_THRESHOLD ||
      (day.high - day.low) / day.reference >= CANDLE_RANGE_THRESHOLD
    );
    // Luôn giữ điểm đầu/cuối để nến vẫn có ngữ cảnh nếu toàn kỳ yên ắng.
    if (candleDays.length === 0 && days.length) candleDays.push(days[0]);
    if (days.length > 1 && candleDays[candleDays.length - 1] !== days[days.length - 1]) {
      candleDays.push(days[days.length - 1]);
    }

    // Giữ nến thưa theo CHART-008; nếu số nến vẫn vượt sức chứa theo pixel,
    // gộp các ngày liền kề thành OHLC đại diện. Payload đầy đủ không thay đổi.
    const maxCandles = Math.max(1, Math.floor(pW / 8));
    let renderedCandles = candleDays.map((day, displayIndex) => ({
      ...day,
      firstDay: day.day,
      lastDay: day.day,
      displayIndex,
    }));
    if (candleDays.length > maxCandles) {
      const bucketSize = Math.ceil(days.length / maxCandles);
      renderedCandles = [];
      for (let start = 0; start < days.length; start += bucketSize) {
        const bucket = days.slice(start, start + bucketSize);
        const first = bucket[0], last = bucket[bucket.length - 1];
        renderedCandles.push({
          day: last.day,
          firstDay: first.day,
          lastDay: last.day,
          displayIndex: renderedCandles.length,
          open: first.open,
          high: Math.max(...bucket.map((d) => d.high)),
          low: Math.min(...bucket.map((d) => d.low)),
          close: last.close,
          reference: last.reference,
          color: last.color,
        });
      }
    }

    // CHART-012: nến được nén theo thứ tự hiển thị; ngày gốc vẫn dùng làm nhãn.
    displaySlotCount = renderedCandles.length;
    const tickStep = Math.max(1, Math.ceil(displaySlotCount / 6));
    const tickIndices = new Set();
    for (let i = 0; i < displaySlotCount; i += tickStep) tickIndices.add(i);
    tickIndices.add(displaySlotCount - 1);
    [...tickIndices].forEach((i) => {
      const candle = renderedCandles[i];
      const label = candle.firstDay === candle.lastDay
        ? String(candle.firstDay)
        : `${candle.firstDay}–${candle.lastDay}`;
      const xT = xPos(i);
      ln(xT, loTop + pH, xT, loTop + pH + 6, CLR.border);
      tx(label, xT, height - 20, CLR.text, "center");
    });

    const dayAnchors = renderedCandles.map((candle, i) => ({
      day: (candle.firstDay + candle.lastDay) / 2,
      slot: i,
    }));
    const dayToSlot = (dayNumber) => {
      if (dayAnchors.length <= 1 || dayNumber <= dayAnchors[0].day) return 0;
      const last = dayAnchors[dayAnchors.length - 1];
      if (dayNumber >= last.day) return last.slot;
      for (let i = 1; i < dayAnchors.length; i++) {
        const left = dayAnchors[i - 1], rightAnchor = dayAnchors[i];
        if (dayNumber <= rightAnchor.day) {
          const fraction = (dayNumber - left.day) / (rightAnchor.day - left.day || 1);
          return left.slot + fraction * (rightAnchor.slot - left.slot);
        }
      }
      return last.slot;
    };
    const cx = (i) => xPos(dayToSlot(i + 1));

    const slotWidth = pW / Math.max(renderedCandles.length, 1);
    const candleW = Math.max(3, Math.min(10, slotWidth * 0.62));
    renderedCandles.forEach((day) => {
      const cxI = xPos(day.displayIndex);
      // Màu theo giá đóng cửa so với tham chiếu; chạm sàn/trần giữ màu riêng.
      const candleColor = POINT_CLR[day.color] || CLR.text;
      const highY = yPos(day.high, upTop), lowY = yPos(day.low, upTop);
      const oY = yPos(day.open, upTop), cY = yPos(day.close, upTop);

      // Bấc ở lớp dưới; thân có viền để dễ tách khỏi bấc và nến kế cận.
      ln(cxI, highY, cxI, lowY, candleColor, 1);
      const isDoji = Math.abs(cY - oY) < 1.5;
      const bodyHeight = isDoji ? 2.5 : Math.abs(cY - oY);
      const bodyWidth = isDoji ? Math.max(4, candleW) : candleW;
      const bodyCenterY = (oY + cY) / 2;
      const bodyTop = bodyCenterY - bodyHeight / 2;
      ctx.fillStyle = candleColor;
      ctx.fillRect(cxI - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
      ctx.strokeStyle = CLR.text;
      ctx.lineWidth = 1;
      ctx.strokeRect(cxI - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);

      // Dấu tham chiếu vàng ngắn, đặt ngoài mép trái thân nến.
      const ry = yPos(day.reference, upTop);
      ln(cxI - bodyWidth / 2 - 4, ry, cxI - bodyWidth / 2 - 1, ry, CLR.reference, 1.5);
    });

    // ════════════════════════════════════════════════════════════════════════
    // PANEL DƯỚI – Vùng biên độ + đường close
    // ════════════════════════════════════════════════════════════════════════

    if (days.length >= 2) {
      // Vẽ từng đoạn để hai vùng chỉ gặp nhau tại reference, không tự cắt nhau.
      days.slice(0, -1).forEach((day, i) => {
        const next = days[i + 1], x1 = cx(i), x2 = cx(i + 1);
        ctx.beginPath();
        ctx.moveTo(x1, yPos(day.reference, loTop));
        ctx.lineTo(x2, yPos(next.reference, loTop));
        ctx.lineTo(x2, yPos(next.ceiling, loTop));
        ctx.lineTo(x1, yPos(day.ceiling, loTop));
        ctx.closePath();
        ctx.fillStyle = CLR.bandGreen;
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(x1, yPos(day.floor, loTop));
        ctx.lineTo(x2, yPos(next.floor, loTop));
        ctx.lineTo(x2, yPos(next.reference, loTop));
        ctx.lineTo(x1, yPos(day.reference, loTop));
        ctx.closePath();
        ctx.fillStyle = CLR.bandRed;
        ctx.fill();
      });
    }

    const dynamicHigh = Math.max(...days.map((d) => d.high));
    const dynamicLow = Math.min(...days.map((d) => d.low));
    const ghY = yPos(dynamicHigh, loTop), glY = yPos(dynamicLow, loTop);
    ln(PAD.left, ghY, right, ghY, CLR.guideHigh, 1.5);
    ln(PAD.left, glY, right, glY, CLR.guideLow, 1.5);
    tx(`Đỉnh ${fmt(dynamicHigh)}`, right + 6, ghY + 4, CLR.guideHigh);
    tx(`Đáy ${fmt(dynamicLow)}`, right + 6, glY + 4, CLR.guideLow);

    // Đường close (xanh lá đậm)
    ctx.save();
    ctx.beginPath();
    ctx.strokeStyle = CLR.closeLine;
    ctx.lineWidth   = 1.8;
    ctx.setLineDash([]);
    days.forEach((d, i) => {
      i === 0
        ? ctx.moveTo(cx(i), yPos(d.close, loTop))
        : ctx.lineTo(cx(i), yPos(d.close, loTop));
    });
    ctx.stroke();
    ctx.restore();

    // Nhãn giá đóng cửa cuối
    const lastDay = days[days.length - 1];
    const lcX = cx(days.length - 1);
    const lcY = yPos(lastDay.close, loTop);
    tx(fmt(lastDay.close), lcX + 8, lcY + 4, CLR.closeLine);
  }

  // ─── API công khai ─────────────────────────────────────────────────────────
  return {
    setup,
    setData(nextData) {
      data    = nextData;
      visible = 0;
      draw();
    },
    setVisible(n) {
      visible = n;
      draw();
    },
  };
})();
