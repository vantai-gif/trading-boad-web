"""Phân tích dữ liệu giá theo tháng, quý và các phiên bất thường."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _json_number(value: Any) -> float | int | None:
    if pd.isna(value):
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def build_analysis(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Tạo số liệu pandas cho dashboard từ các phiên đã chuẩn hóa."""
    if not days:
        return {
            "time_basis": "ordinal_trading_day",
            "monthly": [],
            "quarterly": [],
            "anomalies": [],
            "distributions": {},
            "overall": {},
        }

    frame = pd.DataFrame(days)
    frame["trading_day"] = frame["day"].astype(int)
    frame["month_number"] = (
        ((frame["trading_day"] - 1) * 12 // len(frame)) + 1
    ).clip(upper=12)
    frame["quarter_number"] = ((frame["month_number"] - 1) // 3) + 1
    frame["range"] = frame["high"] - frame["low"]

    monthly = (
        frame.groupby("month_number", sort=True)
        .agg(
            trading_days=("trading_day", "count"),
            average_price=("close", "mean"),
            volatility=("close", "std"),
            low=("low", "min"),
            high=("high", "max"),
            range=("range", "max"),
        )
        .reset_index()
    )
    monthly["volatility"] = monthly["volatility"].fillna(0)
    strongest_month = monthly.loc[monthly["range"].idxmax()]

    quarterly = (
        frame.groupby("quarter_number", sort=True)
        .agg(
            trading_days=("trading_day", "count"),
            average_price=("close", "mean"),
            volatility=("close", "std"),
            low=("low", "min"),
            high=("high", "max"),
            range=("range", "max"),
        )
        .reset_index()
    )
    quarterly["volatility"] = quarterly["volatility"].fillna(0)

    anomaly_rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        kinds = []
        for point_index, value in enumerate(row.points, start=1):
            if value == row.floor:
                kinds.append(f"điểm {point_index}: giá sàn")
            elif value == row.ceiling:
                kinds.append(f"điểm {point_index}: giá trần")
            elif value == row.reference:
                kinds.append(f"điểm {point_index}: giá tham chiếu")
            elif value < row.floor or value > row.ceiling:
                kinds.append(f"điểm {point_index}: ngoài biên")
        if kinds:
            anomaly_rows.append(
                {"trading_day": int(row.trading_day), "types": kinds}
            )

    first_close = float(frame.iloc[0]["close"])
    last_close = float(frame.iloc[-1]["close"])
    overall_high_row = frame.loc[frame["high"].idxmax()]
    overall_low_row = frame.loc[frame["low"].idxmin()]
    direction = "tăng" if last_close > first_close else "giảm" if last_close < first_close else "đi ngang"
    overall_range = float(frame["high"].max() - frame["low"].min())

    def records(table: pd.DataFrame, key: str) -> list[dict[str, Any]]:
        result = []
        for item in table.to_dict("records"):
            result.append(
                {
                    key: int(item[key]),
                    "trading_days": int(item["trading_days"]),
                    "average_price": _json_number(item["average_price"]),
                    "volatility": _json_number(item["volatility"]),
                    "low": _json_number(item["low"]),
                    "high": _json_number(item["high"]),
                    "range": _json_number(item["range"]),
                }
            )
        return result

    return {
        "time_basis": "ordinal_trading_day",
        "time_basis_note": "CSV không có ngày lịch; tháng được chia theo thứ tự 12 kỳ trong tập dữ liệu.",
        "monthly": records(monthly, "month_number"),
        "quarterly": records(quarterly, "quarter_number"),
        "anomalies": anomaly_rows,
        "distributions": {
            "first_half": frame.loc[frame["quarter_number"] <= 2, "close"].round(6).tolist(),
            "second_half": frame.loc[frame["quarter_number"] >= 3, "close"].round(6).tolist(),
        },
        "overall": {
            "direction": direction,
            "first_close": _json_number(first_close),
            "last_close": _json_number(last_close),
            "change": _json_number(last_close - first_close),
            "maximum_range": _json_number(overall_range),
            "range_low_day": int(overall_low_row["trading_day"]),
            "range_high_day": int(overall_high_row["trading_day"]),
            "strongest_month": int(strongest_month["month_number"]),
        },
    }
