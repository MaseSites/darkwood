"""E-TM run: the Time Machine on every trade of data/replay_fills_0311 (68 markets).
Same mechanics as tm_on_ours.simulate; one seeded generator per market (reproducible).
Writes results/tm_0311.csv. Rules and gates: E_TM_VORREGISTRIERUNG.md."""
import csv, glob, json, os, sys, zlib
from concurrent.futures import ProcessPoolExecutor
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tm_on_ours import ROOT, load_m15, simulate  # noqa: E402

SRC = os.path.join(ROOT, "replay_fills_0311")
SEEN = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(ROOT, "replay_fills", "*.json"))}


def run(path):
    d = json.load(open(path))
    sym = d["symbol"]
    ts, X = load_m15(sym)
    rng = np.random.default_rng(zlib.crc32(sym.encode()))
    rows = []
    for j in d["journal"]:
        rs = j["reason"]
        side = 1 if rs["side"] in ("long", "buy") else -1
        e, s, t = float(j["entry_price"]), float(rs["stop"]), float(rs["target"])
        if (e - s) * side <= 0 or (t - e) * side <= 0:
            continue
        res = simulate(ts, X, int(j["opened_ts"]), e, s, t, side, rng)
        rows.append([sym, sym in SEEN, j["opened_ts"], side, round((t - e) / (e - s), 4),
                     j["r_multiple"], res[0] if res else "", res[1] if res else ""])
    return sym, rows


def main(workers=3):
    out = os.path.join(HERE, "results", "tm_0311.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f, ProcessPoolExecutor(workers) as ex:
        w = csv.writer(f)
        w.writerow(["sym", "seen", "opened_ts", "side", "rr", "R", "tm_pt", "tm_ps"])
        for sym, rows in ex.map(run, sorted(glob.glob(os.path.join(SRC, "*.json")))):
            w.writerows(rows)
            f.flush()
            print(sym, len(rows), flush=True)
    print("FERTIG", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
