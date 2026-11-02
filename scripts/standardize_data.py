from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
source_path = ROOT / "data" / "source" / "abc.csv"
output_path = ROOT / "public" / "data.json"

df = pd.read_csv(source_path, encoding="utf-8", parse_dates=True)

#Chuẩn hóa ngày
df['Date'] = pd.to_datetime(df['Date'], format='%Y-%m-%d')

# Gộp các cột chứa giá lại để tìm High và Low
price_cols = [
    "Open", "Price_2", "Price_3",
    "Price_4", "Price_5", "Price_6", "Close"
]

df['Low'] = df[price_cols].min(axis=1)
df['High'] = df[price_cols].max(axis=1)

series = df.rename(columns={
    'Date': 'time',
    'Open': 'open', 
    'Close': 'close', 
    'High': 'high', 
    'Low': 'low'
    })[['time', 'open', 'close', 'high', 'low']]

series.to_json(
    output_path,
    orient="records",
    date_format="iso"
)
