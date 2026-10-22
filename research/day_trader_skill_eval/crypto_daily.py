"""T2b: the skill's pre-market daily scan (scan.find_setups, their exact code) on our D1 perps."""
import csv, glob, os, sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from us_eval import scan, write  # noqa: E402

DATA = r"C:\Users\sever\OneDrive\Desktop\traidingBrain\data\ohlcv"
rows = []
for sym in sorted(os.listdir(DATA)):
    files = sorted(glob.glob(os.path.join(DATA, sym, "D1", "*.parquet")))
    if not files:
        continue
    df = pd.concat([pd.read_parquet(f) for f in files]).drop_duplicates("ts").sort_values("ts")
    d = pd.to_datetime(df["ts"], unit="ms").dt.date.astype(str).values
    o, c = df["open"].values, df["close"].values
    for i in range(63, len(df) - 6):
        tags, _ = scan.find_setups(list(c[i - 62:i + 1]))
        rows.append({"sym": sym, "day": d[i], "tags": "|".join(tags),
                     "next_oc": c[i + 1] / o[i + 1] - 1, "fwd5": c[i + 5] / c[i] - 1})
write(rows, "crypto_daily.csv")
