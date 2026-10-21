from __future__ import annotations

# Thư viện chuẩn: xử lý số, biến môi trường và đường dẫn file.
import math
import os
from pathlib import Path
from typing import Any

# Thành phần FastAPI: tạo API, trả HTML và phục vụ file tĩnh.
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles


# Cấu hình đường dẫn dữ liệu và thư mục gốc của ứng dụng.
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_PATHS = (
    Path(os.getenv("ABF_DATA_PATH", "")) if os.getenv("ABF_DATA_PATH") else None,
    Path(r"D:\abf.csv"),
    PROJECT_ROOT / "abf.csv",
    PROJECT_ROOT / "data" / "abf.csv",
)

# Khởi tạo ứng dụng và đăng ký thư mục CSS/JavaScript.
app = FastAPI(title="ABF Price Board")
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")


@app.get("/assets/link_anh_luffy_chay_transparent.gif.gif")
def luffy_animation() -> FileResponse:
    """Serve the user-provided Luffy animation without renaming the asset."""
    asset_path = PROJECT_ROOT / "link_anh_luffy_chay_transparent.gif.gif"
    if not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Luffy animation not found.")
    return FileResponse(asset_path, media_type="image/gif")


# ─── CHART-005: Đơn giản hóa parse số ────────────────────────────────────────
# Định dạng CSV chuẩn của dự án: số float không có dấu phân cách hàng nghìn.
# Ví dụ hợp lệ: 9125.517621  |  10000.0  |  8500
# Không hỗ trợ: 9.500 (ambiguous với vi-VN locale) hoặc 9,500 (ambiguous với en-US).
def normalize_number(raw_value: str) -> float:
    """Chuyển chuỗi số VND (float) thành float.

    Định dạng chuẩn: số float với dấu chấm thập phân, ví dụ 9125.517621.
    Tự động loại bỏ khoảng trắng và ký hiệu tiền tệ.
    """
    cleaned = str(raw_value).strip().replace(" ", "").replace("_", "")
    cleaned = cleaned.replace("₫", "").replace("$", "").replace("%", "")
    if not cleaned:
        raise ValueError("Giá trị rỗng không hợp lệ.")
    try:
        number = float(cleaned)
    except ValueError as error:
        raise ValueError(
            f"Giá trị '{raw_value}' không phải số float hợp lệ. "
            "Định dạng chuẩn: 9125.517621 (dấu chấm là thập phân)."
        ) from error
    if not math.isfinite(number):
        raise ValueError(f"Giá trị '{raw_value}' không hợp lệ (inf hoặc nan).")
    return number


# ─── CHART-005: Đơn giản hóa parse dòng CSV ──────────────────────────────────
def parse_csv_line(raw_line: str, line_number: int) -> list[float]:
    """Phân tích một dòng CSV thành đúng 7 giá trị float.

    Hỗ trợ các ký tự phân cách: dấu phẩy (,), chấm phẩy (;), tab, gạch dọc (|).
    Định dạng mỗi ô: số float chuẩn, ví dụ 9125.517621.
    """
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        return []

    # Thử lần lượt các delimiter phổ biến
    for delimiter in (",", ";", "\t", "|"):
        parts = [p.strip() for p in stripped.split(delimiter) if p.strip()]
        if len(parts) == 7:
            try:
                return [normalize_number(p) for p in parts]
            except ValueError as error:
                raise ValueError(
                    f"Dòng {line_number} có dữ liệu không hợp lệ: {error}"
                ) from error

    # Không tìm được 7 phần hợp lệ
    parts_comma = [p.strip() for p in stripped.split(",") if p.strip()]
    raise ValueError(
        f"Dòng {line_number} phải có 7 giá trị, nhận được {len(parts_comma)}. "
        "Kiểm tra số cột và ký tự phân cách trong file CSV."
    )


def read_prices(path: Path) -> list[list[float]]:
    """Đọc toàn bộ dữ liệu giá từ file CSV trên máy chủ."""
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file dữ liệu: {path}")

    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for line_number, raw_line in enumerate(source, start=1):
            if not raw_line.strip():
                continue
            result = parse_csv_line(raw_line, line_number)
            if result:
                rows.append(result)

    if not rows:
        raise ValueError("File dữ liệu không có dòng nào.")
    return rows


def find_default_data() -> Path:
    """Tìm file dữ liệu mặc định theo thứ tự ưu tiên đã cấu hình."""
    for path in DEFAULT_DATA_PATHS:
        if path is not None and path.is_file():
            return path
    raise FileNotFoundError("Chưa tìm thấy abf.csv. Hãy chọn file CSV từ giao diện.")


def build_payload(rows: list[list[float]], symbol: str = "ABF") -> dict[str, Any]:
    """Tính sàn, trần, nến và tạo dữ liệu cho biểu đồ trình duyệt.

    Quy tắc màu từng điểm giao dịch:
      'ceiling'   → giá chạm trần (= 110% tham chiếu)
      'floor'     → giá chạm sàn  (=  90% tham chiếu)
      'up'        → giá > tham chiếu (nhưng < trần)
      'down'      → giá < tham chiếu (nhưng > sàn)
      'reference' → giá = tham chiếu

    Dòng đầu tiên là ngày giao dịch liền trước (dùng làm mốc, không hiển thị).
    Mỗi ngày tiếp theo có 7 giá theo thứ tự thời gian; reference bằng close
    của dòng ngay trước đó.
    """
    if len(rows) < 2:
        raise ValueError("Cần ít nhất 2 dòng: ngày liền trước và ngày cần hiển thị.")
    days: list[dict[str, Any]] = []
    previous_close: float = rows[0][-1]

    for index, points in enumerate(rows[1:], start=1):
        reference = previous_close
        floor_val = reference * 0.9
        ceiling_val = reference * 1.1

        # Phép nhân float có thể lệch vài chữ số cuối; giá sát biên được
        # chuẩn hóa về đúng sàn/trần trước khi phân loại màu và dựng OHLC.
        bounded_points = [
            floor_val if math.isclose(p, floor_val, rel_tol=1e-9, abs_tol=1e-9)
            else ceiling_val if math.isclose(p, ceiling_val, rel_tol=1e-9, abs_tol=1e-9)
            else p
            for p in points
        ]
        violations = [
            (i + 1, p)
            for i, p in enumerate(bounded_points)
            if not (floor_val <= p <= ceiling_val)
        ]
        if violations:
            detail = ", ".join(f"điểm {pi}={pv:g}" for pi, pv in violations)
            raise ValueError(
                f"Ngày {index}: {len(violations)} điểm ngoài biên "
                f"[sàn={floor_val:g}, trần={ceiling_val:g}]: {detail}."
            )
        def _point_color(value: float, ref: float = reference,
                         fl: float = floor_val, ceil: float = ceiling_val) -> str:
            if value >= ceil:
                return "ceiling"
            if value <= fl:
                return "floor"
            if value > ref:
                return "up"
            if value < ref:
                return "down"
            return "reference"

        point_colors = [_point_color(p) for p in bounded_points]
        close = bounded_points[-1]

        days.append(
            {
                "day": index,
                "points": bounded_points,
                "point_colors": point_colors,
                "open": bounded_points[0],
                "high": max(bounded_points),
                "low": min(bounded_points),
                "close": close,
                "reference": reference,
                "floor": floor_val,
                "ceiling": ceiling_val,
                "color": point_colors[-1],
            }
        )
        previous_close = close

    return {
        "symbol":     symbol.upper(),
        "days":       days,
        "count":      len(days),
    }


# Giao diện web chính.
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    template = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(template)


# API đọc file dữ liệu mặc định.
@app.get("/api/data")
def get_data() -> dict[str, Any]:
    try:
        path = find_default_data()
        return build_payload(read_prices(path), path.stem)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Dữ liệu thị trường mặc định không hợp lệ: {error}",
        ) from error


# API nhận CSV do người dùng tải lên và trả dữ liệu biểu đồ.
@app.post("/api/data/upload")
async def upload_data(file: UploadFile) -> dict[str, Any]:
    if not file.filename or Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="Vui lòng chọn một file .csv.")
    try:
        content = (await file.read()).decode("utf-8-sig")
        rows: list[list[float]] = []
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            if not raw_line.strip():
                continue
            result = parse_csv_line(raw_line, line_number)
            if result:
                rows.append(result)
        return build_payload(rows, Path(file.filename).stem)
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"File không hợp lệ: {error}") from error
