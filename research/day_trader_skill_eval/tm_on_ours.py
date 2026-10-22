"""T3b: the skill's Time Machine as a filter on OUR replay trades (read-only).

For each of the 7,335 replay trades (data/replay_fills, 12 markets): bootstrap the
next 72 h from the market's own prior 59 days of M15 bars, drawn by time of day
(+-2 slots), with OUR entry, stop and target. Same mechanics as the skill's
simulate(): stop checked before target, no look-ahead (pool ends before entry).
Writes results/tm_on_ours.csv with the odds next to the trade's real R.
"""
import glob, json, os, sys, csv
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"C:\Users\sever\OneDrive\Desktop\traidingBrain\data"
SLOTS = 96          # M15 bars per day
HORIZON = 288       # 72 h
DAYS = 59
REPLAYS = 2000


def load_m15(sym):
    files = sorted(glob.glob(os.path.join(ROOT, "ohlcv", sym, "M15", "*.parquet")))
    df = pd.concat([pd.read_parquet(f) for f in files]).drop_duplicates("ts").sort_values("ts")
    return df["ts"].values, df[["open", "high", "low", "close"]].values


def simulate(ts, X, t0, entry, stop, target, side, rng):
    i0 = np.searchsorted(ts, t0)          # first bar starting at/after entry: pool strictly before
    lo_i = np.searchsorted(ts, t0 - DAYS * 86400000)
    if i0 - lo_i < 20 * SLOTS or i0 < 2:
        return None
    seg = X[lo_i - 1:i0]
    segts = ts[lo_i:i0]
    ratios = seg[1:] / seg[:-1, 3:4]
    slot_of = ((segts // 900000) % SLOTS).astype(int)
    by_slot = [np.nonzero(slot_of == s)[0] for s in range(SLOTS)]
    start_slot = int((t0 // 900000) % SLOTS)
    steps = (start_slot + np.arange(HORIZON)) % SLOTS
    jitter = rng.integers(-2, 3, size=(REPLAYS, HORIZON))
    sl = (steps[None, :] + jitter) % SLOTS
    pick = np.empty((REPLAYS, HORIZON), dtype=int)
    for s in range(SLOTS):
        m = sl == s
        cand = by_slot[s]
        pick[m] = cand[rng.integers(0, len(cand), size=m.sum())]
    r = ratios[pick]
    closes = entry * np.cumprod(r[:, :, 3], axis=1)
    prevc = np.concatenate([np.full((REPLAYS, 1), entry), closes[:, :-1]], axis=1)
    hi, lo = prevc * r[:, :, 1], prevc * r[:, :, 2]
    sb, tb = (lo <= stop, hi >= target) if side == 1 else (hi >= stop, lo <= target)
    big = HORIZON + 1
    fs = np.where(sb.any(1), sb.argmax(1), big)
    ft = np.where(tb.any(1), tb.argmax(1), big)
    stop_first = (fs <= ft) & (fs < big)
    targ_first = ft < fs
    return float(targ_first.mean()), float(stop_first.mean())


def main():
    out = os.path.join(HERE, "results", "tm_on_ours.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rng = np.random.default_rng(19)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sym", "opened_ts", "side", "setup", "tf", "rr", "R_net", "R_gross", "tm_pt", "tm_ps"])
        for p in sorted(glob.glob(os.path.join(ROOT, "replay_fills", "*.json"))):
            d = json.load(open(p))
            sym = d["symbol"]
            ts, X = load_m15(sym)
            n = 0
            for j in d["journal"]:
                rs = j["reason"]
                side = 1 if rs["side"] in ("long", "buy") else -1
                e, s, t = float(j["entry_price"]), float(rs["stop"]), float(rs["target"])
                if (e - s) * side <= 0 or (t - e) * side <= 0:
                    continue
                res = simulate(ts, X, int(j["opened_ts"]), e, s, t, side, rng)
                if res is None:
                    continue
                rg = j["gross_pnl"] / j["risk_amount"] if j.get("risk_amount") else None
                w.writerow([sym, j["opened_ts"], side, rs.get("setup_key"), rs.get("setup_timeframe"),
                            round((t - e) / (e - s), 4), j["r_multiple"], rg, res[0], res[1]])
                n += 1
            print(sym, n, flush=True)
            f.flush()


if __name__ == "__main__":
    main()
