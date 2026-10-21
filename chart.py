"""Vẽ biểu đồ chứng khoán ABF từ file CSV và lưu thành ảnh PNG.

Cấu trúc biểu đồ gồm hai panel:
  - Panel trên : Nến Nhật theo màu giá đóng cửa so với tham chiếu.
  - Panel dưới : Đường giá đóng cửa + vùng biên độ.

Định dạng CSV chuẩn — mỗi dòng có 7 giá trị float cách nhau bằng dấu phẩy.
Dòng đầu tiên bắt buộc là ngày giao dịch liền trước; close của dòng này
được dùng làm giá tham chiếu cho dòng dữ liệu kế tiếp và không được vẽ:
    open, point_2, point_3, point_4, point_5, point_6, close
Ví dụ: 9125.517621,9200.0,9450.5,9300.2,9150.8,9000.1,9050.3

Ví dụ chạy:
    python chart.py data\\abf.csv --output charts\\abf.png
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

# CHART-007: Import đúng vị trí public API của Matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter


# ─── Màu sắc (đồng bộ với chart.js) ─────────────────────────────────────────
COLOR = {
    "bg":         "#000000",
    "grid":       "#242424",
    "text":       "#d0d0d0",
    "candle_up":  "#00c800",   # Xanh lá – giá > tham chiếu
    "candle_dn":  "#ff1616",   # Đỏ     – giá < tham chiếu
    "reference":  "#d4a017",   # Vàng   – đường tham chiếu
    "floor":      "#1e6fd4",   # Xanh dương – giá sàn (90%)
    "ceiling":    "#9b30d9",   # Tím    – giá trần (110%)
    "close_line": "#00c800",   # Đường close panel dưới
    "band_green": "#00c800",   # Vùng biên độ xanh nhạt
    "band_red":   "#ff3c00",   # Vùng biên độ đỏ/cam nhạt
    "guide_high": "#00aa44",   # Ngưỡng trần panel dưới (cố định)
    "guide_low":  "#bb2222",   # Ngưỡng sàn panel dưới (cố định)
}

# Map point_color string → màu thực
POINT_COLOR_MAP = {
    "ceiling":   COLOR["ceiling"],
    "floor":     COLOR["floor"],
    "up":        COLOR["candle_up"],
    "down":      COLOR["candle_dn"],
    "reference": COLOR["reference"],
}

YMAX  = 20_000
XDAYS = 360
# CHART-008: ngưỡng giảm mật độ nến, dữ liệu và đường close vẫn dùng đủ ngày.
CANDLE_CLOSE_THRESHOLD = 0.005  # close lệch tham chiếu ít nhất 0,5%
CANDLE_RANGE_THRESHOLD = 0.01   # high-low ít nhất 1% tham chiếu


# ─── CHART-005: Parse số float chuẩn ─────────────────────────────────────────
def normalize_number(raw_value: str) -> float:
    """Chuyển chuỗi số VND thành float.

    Định dạng chuẩn: số float với dấu chấm thập phân (ví dụ: 9125.517621).
    """
    cleaned = raw_value.strip().replace(" ", "").replace("_", "")
    cleaned = cleaned.replace("₫", "").replace("$", "").replace("%", "")
    if not cleaned:
        raise ValueError("Giá trị rỗng không hợp lệ.")
    try:
        number = float(cleaned)
    except ValueError as error:
        raise ValueError(
            f"Giá trị '{raw_value}' không phải số float hợp lệ. "
            "Định dạng chuẩn: 9125.517621"
        ) from error
    if not math.isfinite(number):
        raise ValueError(f"Giá trị '{raw_value}' không hợp lệ (inf/nan).")
    return number


def read_prices(path: Path) -> list[list[float]]:
    """Đọc file CSV và kiểm tra mỗi dòng có đúng 7 giá trị float."""
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for line_number, row in enumerate(csv.reader(source), start=1):
            stripped = [cell.strip() for cell in row if cell.strip()]
            if not stripped or stripped[0].startswith("#"):
                continue
            if len(stripped) != 7:
                raise ValueError(
                    f"Dòng {line_number} phải có 7 giá trị, nhận được {len(stripped)}."
                )
            try:
                rows.append([normalize_number(cell) for cell in stripped])
            except ValueError as error:
                raise ValueError(f"Dòng {line_number}: {error}") from error

    if not rows:
        raise ValueError("File dữ liệu không có dòng nào.")
    return rows


def build_days(rows: list[list[float]]) -> tuple[list[dict], list[str], float, float]:
    """Tính OHLC, màu từng điểm, sàn và trần cho từng ngày.

    Returns:
    (days, warnings, guide_high, guide_low). Dòng đầu là ngày liền trước,
    chỉ dùng close của dòng đó làm giá tham chiếu đầu tiên.
    """
    days: list[dict] = []
    warnings: list[str] = []
    if len(rows) < 2:
        raise ValueError("Cần ít nhất 2 dòng: ngày liền trước và ngày cần hiển thị.")
    previous_close: float = rows[0][-1]

    for line_idx, points in enumerate(rows[1:], start=1):
        reference  = previous_close
        floor_val  = reference * 0.9
        ceiling_val = reference * 1.1

        # Chuẩn hóa sai số float rất nhỏ tại đúng giá sàn/trần.
        bounded = [
            floor_val if math.isclose(p, floor_val, rel_tol=1e-9, abs_tol=1e-9)
            else ceiling_val if math.isclose(p, ceiling_val, rel_tol=1e-9, abs_tol=1e-9)
            else p
            for p in points
        ]
        # CHART-004: Phát hiện vi phạm biên
        violations = [(i + 1, p) for i, p in enumerate(points)
                      if not (floor_val <= bounded[i] <= ceiling_val)]
        if violations:
            detail = ", ".join(f"điểm {pi}={pv:.2f}" for pi, pv in violations)
            warnings.append(
                f"Ngày {line_idx + 1}: {len(violations)} điểm ngoài biên "
                f"[sàn={floor_val:.2f}, trần={ceiling_val:.2f}] → {detail}"
            )

        if violations:
            detail = ", ".join(f"điểm {pi}={pv:g}" for pi, pv in violations)
            raise ValueError(f"Ngày {line_idx}: giá ngoài biên [sàn={floor_val:g}, trần={ceiling_val:g}]: {detail}.")
        def _color(v: float, ref: float = reference,
                   fl: float = floor_val, ceil: float = ceiling_val) -> str:
            if v >= ceil:  return "ceiling"
            if v <= fl:    return "floor"
            if v > ref:    return "up"
            if v < ref:    return "down"
            return "reference"

        point_colors = [_color(p) for p in bounded]
        close = bounded[-1]

        # Màu nến tổng thể (theo giá đóng cửa)
        candle_color = POINT_COLOR_MAP[point_colors[-1]]

        days.append({
            "day":          line_idx,
            "points":       bounded,
            "point_colors": point_colors,
            "open":         bounded[0],
            "high":         max(bounded),
            "low":          min(bounded),
            "close":        close,
            "reference":    reference,
            "floor":        floor_val,
            "ceiling":      ceiling_val,
            "candle_color": candle_color,
        })
        previous_close = close

    # CHART-003: guide lines cố định từ toàn bộ dataset
    guide_high = max(d["high"] for d in days)
    guide_low  = min(d["low"] for d in days)
    return days, warnings, guide_high, guide_low


# ─── Vẽ biểu đồ ──────────────────────────────────────────────────────────────
def draw_chart(
    rows: list[list[float]],
    output_path: Path,
    symbol: str = "ABF",
) -> None:
    """Vẽ biểu đồ hai panel và lưu PNG."""
    days, warnings, guide_high, guide_low = build_days(rows)

    if warnings:
        print(f"[CẢNH BÁO] {len(warnings)} ngày có giá ngoài biên:")
        for w in warnings:
            print(f"  • {w}")

    n      = len(days)
    x_vals = [i / max(n - 1, 1) * XDAYS for i in range(n)]

    plt.style.use("dark_background")
    fig, (ax_up, ax_lo) = plt.subplots(
        2, 1,
        figsize=(16, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [1, 1], "hspace": 0.08},
        constrained_layout=True,
    )
    fig.suptitle(f"{symbol.upper()} Price Motion", fontsize=15,
                 fontweight="bold", color=COLOR["text"])

    fmt_price = FuncFormatter(lambda v, _: f"{int(v):,}")  # CHART-007: public API

    for ax in (ax_up, ax_lo):
        ax.set_facecolor(COLOR["bg"])
        ax.set_xlim(0, XDAYS)
        ax.set_ylim(0, YMAX)
        ax.set_yticks([0, 5000, 10000, 15000, 20000])
        ax.yaxis.set_major_formatter(fmt_price)
        ax.set_ylabel("VND", color=COLOR["text"])
        ax.tick_params(colors=COLOR["text"])
        ax.grid(True, color=COLOR["grid"], linewidth=0.7, alpha=0.9)
        for spine in ax.spines.values():
            spine.set_edgecolor("#8c8c8c")

    ax_lo.set_xlabel("Date", color=COLOR["text"])
    ax_lo.set_xticks(range(0, XDAYS + 1, 30))

    # ════════════════════════════════════════════════════════════════════════
    # PANEL TRÊN – Nến Nhật
    # ════════════════════════════════════════════════════════════════════════
    candle_days = [
        day for day in days
        if abs(day["close"] - day["reference"]) / day["reference"] >= CANDLE_CLOSE_THRESHOLD
        or (day["high"] - day["low"]) / day["reference"] >= CANDLE_RANGE_THRESHOLD
    ]
    if not candle_days and days:
        candle_days.append(days[0])
    if len(days) > 1 and candle_days[-1] is not days[-1]:
        candle_days.append(days[-1])

    candle_positions = [x_vals[day["day"] - 1] for day in candle_days]
    for index, day in enumerate(candle_days):
        xi = x_vals[day["day"] - 1]
        left_gap = xi - candle_positions[index - 1] if index > 0 else float("inf")
        right_gap = candle_positions[index + 1] - xi if index < len(candle_positions) - 1 else float("inf")
        nearest_gap = min(left_gap, right_gap)
        candle_w = min(3.0, nearest_gap * 0.62) if math.isfinite(nearest_gap) else 12.0
        candle_w = max(0.4, candle_w)
        color = day["candle_color"]

        # Bấc (wick)
        ax_up.vlines(xi, day["low"], day["high"], color=color, linewidth=1.0)

        # Thân nến
        body_bot = min(day["open"], day["close"])
        body_h   = max(abs(day["close"] - day["open"]), 8.0)
        ax_up.add_patch(Rectangle(
            (xi - candle_w / 2, body_bot), candle_w, body_h,
            facecolor=color, edgecolor=color,
        ))

        # Vạch tham chiếu nhỏ (vàng)
        ax_up.hlines(day["reference"], xi - candle_w, xi + candle_w,
                     colors=COLOR["reference"], linewidth=0.7, alpha=0.8)

    ax_up.set_title("Nến OHLC theo màu giá đóng cửa so với tham chiếu",
                    loc="left", fontsize=10, color=COLOR["text"])

    # ════════════════════════════════════════════════════════════════════════
    # PANEL DƯỚI – Đường close + vùng biên độ + ngưỡng cố định (CHART-003)
    # ════════════════════════════════════════════════════════════════════════
    closes     = [d["close"]     for d in days]
    references = [d["reference"] for d in days]
    ceilings   = [d["ceiling"]   for d in days]
    floors     = [d["floor"]     for d in days]

    # CHART-009: tô từng đoạn để hai vùng chỉ gặp nhau tại reference,
    # không tạo đa giác tự giao nhau khi mức tham chiếu đổi theo ngày.
    for i in range(len(x_vals) - 1):
        ax_lo.fill_between(x_vals[i:i + 2], references[i:i + 2], ceilings[i:i + 2],
                           color=COLOR["band_green"], alpha=0.28, zorder=1)
        ax_lo.fill_between(x_vals[i:i + 2], floors[i:i + 2], references[i:i + 2],
                           color=COLOR["band_red"], alpha=0.28, zorder=1)

    # CHART-003: Đường ngang cố định từ toàn bộ dataset
    ax_lo.axhline(guide_high, color=COLOR["guide_high"], linewidth=1.2,
                  alpha=0.9, zorder=2, label=f"Trần cao nhất: {guide_high:,.0f}")
    ax_lo.axhline(guide_low,  color=COLOR["guide_low"],  linewidth=1.2,
                  alpha=0.9, zorder=2, label=f"Sàn thấp nhất: {guide_low:,.0f}")
    ax_lo.text(XDAYS + 2, guide_high, f"{guide_high:,.0f}",
               color=COLOR["guide_high"], va="center", fontsize=9)
    ax_lo.text(XDAYS + 2, guide_low, f"{guide_low:,.0f}",
               color=COLOR["guide_low"], va="center", fontsize=9)

    # Đường close chính (xanh lá)
    ax_lo.plot(x_vals, closes, color=COLOR["close_line"],
               linewidth=1.6, zorder=3)

    # Nhãn giá đóng cửa cuối
    if closes:
        ax_lo.text(x_vals[-1] + 1, closes[-1], f"{closes[-1]:,.0f}",
                   color=COLOR["close_line"], va="center", fontsize=9)

    ax_lo.set_title("Diễn biến giá – đường close và biên độ",
                    loc="left", fontsize=10, color=COLOR["text"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor=COLOR["bg"])
    plt.close(fig)
    print(f"Chart saved → {output_path}")


# ─── CLI ──────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    """Đọc tham số dòng lệnh."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Đường dẫn file CSV đầu vào.")
    parser.add_argument("-o", "--output", type=Path, default=Path("chart.png"),
                        help="Đường dẫn ảnh PNG đầu ra (mặc định: chart.png).")
    parser.add_argument("--symbol", default=None,
                        help="Tên mã hiển thị (mặc định lấy từ tên file).")
    return parser.parse_args()


def main() -> None:
    """Điểm bắt đầu khi chạy chart.py từ dòng lệnh."""
    args   = parse_args()
    symbol = args.symbol or args.input.stem
    draw_chart(read_prices(args.input), args.output, symbol)


if __name__ == "__main__":
    main()
