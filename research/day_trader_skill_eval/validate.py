"""Check orb_core against the skill's own code on its own TSLA fixture."""
import gzip, os, sys, importlib.util, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "ext", "day-trader-skill")
sys.path.insert(0, HERE)
import orb_core as oc  # noqa: E402

spec = importlib.util.spec_from_file_location("tm", os.path.join(REPO, "trader-timemachine", "timemachine.py"))
tm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tm)


def sessions_from_text(text, sym, before):
    now = datetime.datetime(2030, 1, 1)
    meta, bars, _ = tm.parse_bars(tm.chart_result(text, sym), now)
    days = tm.split_sessions(bars)
    full, _ = tm.full_sessions(days, before)
    return full, days


if __name__ == "__main__":
    text = gzip.open(os.path.join(REPO, "tests", "fixtures", "trader-timemachine", "TSLA-60d5m.json.gz"), "rt").read()
    full, days = sessions_from_text(text, "TSLA", "2026-10-19")
    rule = {"or_minutes": 15, "stop_rule": "or_mid", "target_r": 1.0}
    theirs = tm.history_replay(full, rule, 77)
    S = np.array([[[b["o"], b["h"], b["l"], b["c"]] for b in D] for _, D in full])
    mine = oc.orb_trades(S, last=77, entry_last=77)
    cnt = {x: sum(t["outcome"] == x for t in mine) for x in ("target", "stop", "close")}
    print("theirs:", theirs["triggered"], theirs["target"], theirs["stop"], theirs["close"], theirs["avg_R"])
    print("mine:  ", len(mine), cnt, round(np.mean([t["R"] for t in mine]), 3))
    pool_t = tm.build_pool(full)
    mc = tm.simulate(pool_t, 364.18, 358.32, 370.04, 8, 77, replays=10000)
    print("their TM:", mc["p_target"], mc["p_stop"], mc["p_neither"], mc["avg_R"])
    print("my TM:   ", oc.simulate(oc.build_pool(S), 364.18, 358.32, 370.04, 8, 77, replays=10000))
