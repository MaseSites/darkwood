"""T2 + T3a: the skill's ORB + Time Machine on our own perp minute data (read-only).

Sessions of 78 five-minute bars at two anchors:
  ny  = 09:30-16:00 New York (DST-aware), weekdays only (the skill's own clock)
  utc = 00:00-06:30 UTC, every day
For every trade: gross R, Time Machine odds from the prior 59 full sessions,
and a random-bar control (same session, random entry bar, same % risk).
Writes results/crypto_<anchor>.csv.
"""
import glob, os, sys, csv
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orb_core as oc  # noqa: E402

DATA = r"C:\Users\sever\OneDrive\Desktop\traidingBrain\data\ohlcv"
OUT = os.path.join(HERE, "results")
POOL = 59
MIN_POOL = 20


def load_5m(sym):
    files = sorted(glob.glob(os.path.join(DATA, sym, "M1", "*.parquet")))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.drop_duplicates("ts").sort_values("ts")
    df["t"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    g = df.set_index("t").resample("5min", label="left", closed="left")
    b = pd.DataFrame({"o": g["open"].first(), "h": g["high"].max(), "l": g["low"].min(),
                      "c": g["close"].last(), "n": g["close"].count()})
    return b[b["n"] == 5]   # a 5m bar counts only when all five minutes are there


def sessions(b, anchor):
    if anchor == "ny":
        loc = b.index.tz_convert("America/New_York")
        mins = loc.hour * 60 + loc.minute
        keep = (mins >= 570) & (mins < 960) & (loc.weekday < 5)
        day = loc.date
        slot = (mins - 570) // 5
    else:
        u = b.index
        mins = u.hour * 60 + u.minute
        keep = mins < 390
        day = u.date
        slot = mins // 5
    x = b[keep].copy()
    x["day"] = np.asarray(day)[keep]
    x["slot"] = np.asarray(slot)[keep]
    days, arrs = [], []
    for d, g in x.groupby("day"):
        if len(g) != oc.SESSION_BARS:
            continue
        g = g.sort_values("slot")
        if not (g["slot"].values == np.arange(oc.SESSION_BARS)).all():
            continue
        days.append(d)
        arrs.append(g[["o", "h", "l", "c"]].values)
    return days, np.array(arrs)


def run_market(args):
    sym, anchor = args
    try:
        b = load_5m(sym)
    except Exception as e:  # noqa: BLE001
        return sym, [], str(e)
    days, S = sessions(b, anchor)
    if len(days) < MIN_POOL + 5:
        return sym, [], "too few sessions (%d)" % len(days)
    rng = np.random.default_rng(abs(hash((sym, anchor))) % 2**32)
    rows = []
    for side in (1, -1):
        for t in oc.orb_trades(S, side=side):
            d, k = t["d"], t["k"]
            row = {"sym": sym, "anchor": anchor, "day": str(days[d]), "side": side, "k": k,
                   "entry": t["entry"], "risk_pct": t["risk"] / t["entry"], "outcome": t["outcome"], "R": t["R"]}
            if d >= MIN_POOL:
                pool = oc.build_pool(S[max(0, d - POOL):d])
                pt, ps, pn, ar = oc.simulate(pool, t["entry"], t["stop"], t["target"], k, oc.FLAT_BAR,
                                             side=side, replays=2000, rng=rng)
                row.update(tm_pt=pt, tm_ps=ps, tm_pn=pn, tm_avgR=ar, tm_class=oc.verdict_class(pt, ps))
            # random-bar control: same session and side, random entry bar, same % risk, 1R target
            D = S[d]
            kr = int(rng.integers(oc.OR_BARS, oc.ENTRY_LAST_BAR + 1))
            e = D[kr, 3]
            risk = e * row["risk_pct"]
            s, tg = e - side * risk, e + side * risk
            R = None
            for bb in D[kr + 1:oc.FLAT_BAR + 1]:
                if (bb[2] <= s) if side == 1 else (bb[1] >= s):
                    R = -1.0
                    break
                if (bb[1] >= tg) if side == 1 else (bb[2] <= tg):
                    R = 1.0
                    break
            if R is None:
                R = (D[oc.FLAT_BAR, 3] - e) * side / risk if kr < oc.FLAT_BAR else 0.0
            row["ctrl_R"] = R
            rows.append(row)
    return sym, rows, "ok %d sessions" % len(days)


def main(anchor, workers=3):
    os.makedirs(OUT, exist_ok=True)
    syms = sorted(s for s in os.listdir(DATA) if glob.glob(os.path.join(DATA, s, "M1", "*.parquet")))
    path = os.path.join(OUT, "crypto_%s.csv" % anchor)
    w = None
    with open(path, "w", newline="") as f, ProcessPoolExecutor(workers) as ex:
        for sym, rows, msg in ex.map(run_market, [(s, anchor) for s in syms]):
            print(sym, msg, len(rows), flush=True)
            for r in rows:
                if w is None:
                    keys = ["sym", "anchor", "day", "side", "k", "entry", "risk_pct", "outcome", "R",
                            "tm_pt", "tm_ps", "tm_pn", "tm_avgR", "tm_class", "ctrl_R"]
                    w = csv.DictWriter(f, keys)
                    w.writeheader()
                w.writerow(r)
            f.flush()


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3)
