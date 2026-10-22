"""T1: the skill on its HOME market (US stocks), with the skill's own code where it exists.

T1a  intraday ORB (the reel's trade) over the last 60 days of 5m bars, ~150 liquid names:
     sessions/pool parsed by timemachine.parse_bars/full_sessions, Time Machine by
     timemachine.simulate (their exact code, 2,000 replays), trade rule = orb_core
     (validated identical to their history_replay) with entry cutoff 15:30 and flat 15:55.
T1b  the pre-market daily scan (scan.find_setups, their exact code) over 10 years of
     daily closes: next-day open->close, and next-5-day close->close, each against the
     same day's cross-section of the same universe.
Writes results/us_orb.csv and results/us_daily.csv.
"""
import csv, datetime, gzip, glob, importlib.util, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "ext", "day-trader-skill")
sys.path.insert(0, HERE)
import orb_core as oc  # noqa: E402


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tm = load("tm", "trader-timemachine/timemachine.py")
scan = load("scan", "trader-scanner/scan.py")
NOW = datetime.datetime(2030, 1, 1)


def t1a():
    rows = []
    for p in sorted(glob.glob(os.path.join(HERE, "us", "5m", "*.json.gz"))):
        sym = os.path.basename(p).split(".")[0]
        try:
            text = gzip.open(p, "rt").read()
            meta, bars, _ = tm.parse_bars(tm.chart_result(text, sym), NOW)
        except Exception as e:  # noqa: BLE001
            print(sym, "skip", e)
            continue
        full, _ = tm.full_sessions(tm.split_sessions(bars), "9999-12-31")
        if len(full) < 25:
            continue
        S = np.array([[[b["o"], b["h"], b["l"], b["c"]] for b in D] for _, D in full])
        for side, sname in ((1, "buy"), (-1, "sell")):
            for t in oc.orb_trades(S, side=side):
                d = t["d"]
                row = {"sym": sym, "day": full[d][0], "side": side, "k": t["k"], "entry": t["entry"],
                       "risk_pct": t["risk"] / t["entry"], "outcome": t["outcome"], "R": t["R"]}
                if d >= 20:
                    pool = tm.build_pool(full[max(0, d - 59):d])
                    mc = tm.simulate(pool, t["entry"], t["stop"], t["target"], t["k"], oc.FLAT_BAR,
                                     replays=2000, side=sname)
                    row.update(tm_pt=mc["p_target"], tm_ps=mc["p_stop"], tm_avgR=mc["avg_R"],
                               tm_class=oc.verdict_class(mc["p_target"], mc["p_stop"]))
                rows.append(row)
        print(sym, len(full), "sessions", flush=True)
    write(rows, "us_orb.csv")


def t1b():
    series = {}
    for p in sorted(glob.glob(os.path.join(HERE, "us", "1d", "*.json.gz"))):
        sym = os.path.basename(p).split(".")[0]
        try:
            r = json.loads(gzip.open(p, "rt").read())["chart"]["result"][0]
            q = r["indicators"]["quote"][0]
            series[sym] = [(datetime.datetime.utcfromtimestamp(t).date(), o, c)
                           for t, o, c in zip(r["timestamp"], q["open"], q["close"]) if o and c]
        except Exception as e:  # noqa: BLE001
            print(sym, "skip", e)
    rows = []
    for sym, s in series.items():
        c = [x[2] for x in s]
        o = [x[1] for x in s]
        for i in range(63, len(s) - 6):
            tags, _ = scan.find_setups(c[i - 62:i + 1])      # ~3 months, like the spark range
            rows.append({"sym": sym, "day": s[i][0].isoformat(), "tags": "|".join(tags),
                         "next_oc": o[i + 1] and (c[i + 1] / o[i + 1] - 1),
                         "fwd5": c[i + 5] / c[i] - 1})
    write(rows, "us_daily.csv")


def write(rows, name):
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with open(os.path.join(HERE, "results", name), "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rows)
    print(name, len(rows))


if __name__ == "__main__":
    {"a": t1a, "b": t1b}[sys.argv[1]]()
