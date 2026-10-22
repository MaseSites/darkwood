"""Read results/*.csv and print every number the report uses.
Intervals: 95 % bootstrap, resampling whole ISO weeks (the project's shared weekly
factor makes market- or trade-level resampling too narrow), 5,000 draws."""
import os, sys
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
DRAWS = 5000


def week_of(day):
    return pd.to_datetime(day).dt.strftime("%G-%V")


def ci(df, col, draws=DRAWS, seed=7):
    """Mean of col with a week-clustered bootstrap interval."""
    g = df.groupby("week")[col].agg(["sum", "count"])
    s, n = g["sum"].values, g["count"].values
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(draws, len(g)))
    boot = s[idx].sum(1) / n[idx].sum(1)
    return s.sum() / n.sum(), np.percentile(boot, 2.5), np.percentile(boot, 97.5)


def diff_ci(df, mask, col, draws=DRAWS, seed=7):
    """mean(col | mask) - mean(col | all), week-clustered."""
    d = df.assign(_in=mask.astype(float), _x=df[col] * mask)
    g = d.groupby("week").agg(s_all=(col, "sum"), n_all=(col, "count"), s_in=("_x", "sum"), n_in=("_in", "sum"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(draws, len(g)))
    a = g.values
    boot = a[idx, 2].sum(1) / a[idx, 3].sum(1) - a[idx, 0].sum(1) / a[idx, 1].sum(1)
    pt = a[:, 2].sum() / a[:, 3].sum() - a[:, 0].sum() / a[:, 1].sum()
    return pt, np.percentile(boot, 2.5), np.percentile(boot, 97.5)


def fmt(t):
    return "%+.4f [%+.4f, %+.4f]" % t


def orb_block(df, cost_bp, label):
    df = df.copy()
    df["week"] = week_of(df["day"])
    df["R_net"] = df["R"] - (cost_bp / 1e4) / df["risk_pct"]
    print("\n=== %s  (cost %g bp round trip) ===" % (label, cost_bp))
    for side, g in df.groupby("side"):
        nm = "long (skill)" if side == 1 else "short (mirror, not in skill)"
        print("%-28s n=%6d  hit=%.3f  gross %s  net %s" % (nm, len(g), (g.outcome == "target").mean(),
                                                         fmt(ci(g, "R")), fmt(ci(g, "R_net"))))
        if "ctrl_R" in g:
            g2 = g.assign(d=g["R"] - g["ctrl_R"])
            print("%-28s ORB minus random-bar control: %s" % ("", fmt(ci(g2, "d"))))
        print("%-28s median risk %.3f %% -> cost %.3f R" % ("", 100 * g.risk_pct.median(),
                                                          (cost_bp / 1e4) / g.risk_pct.median()))
    lg = df[df.side == 1]
    yr = lg.groupby(pd.to_datetime(lg["day"]).dt.year).agg(n=("R", "size"), gross=("R", "mean"), net=("R_net", "mean"))
    print("long by year:\n" + yr.round(4).to_string())
    t = df.dropna(subset=["tm_pt"])
    if len(t):
        t = t.assign(lean=t.tm_pt / (t.tm_pt + t.tm_ps) - 0.5)
        rho = spearmanr(t["lean"], t["R"]).correlation
        print("Time Machine: n=%d, Spearman(lean, R) = %+.4f" % (len(t), rho))
        for c, g in t.groupby("tm_class"):
            print("   %-14s n=%6d  mean R %+.4f   share %.3f" % (c, len(g), g.R.mean(), len(g) / len(t)))
        keep = t["tm_class"].isin(["leans_target", "strong_target"])
        print("   filter 'leans/strong target' vs all: %s (keeps %.1f %%)" % (fmt(diff_ci(t, keep, "R")), 100 * keep.mean()))
        drop = t["tm_class"].isin(["leans_stop", "strong_stop"])
        print("   filter 'drop leans/strong stop'  vs all: %s (keeps %.1f %%)" % (fmt(diff_ci(t, ~drop, "R")), 100 * (~drop).mean()))
        if "tm_avgR" in t:
            print("   filter 'TM avg R > 0' vs all:     %s (keeps %.1f %%)" % (
                fmt(diff_ci(t, t.tm_avgR > 0, "R")), 100 * (t.tm_avgR > 0).mean()))


def ours():
    p = os.path.join(RES, "tm_on_ours.csv")
    if not os.path.exists(p):
        return
    t = pd.read_csv(p).dropna(subset=["tm_pt", "R_gross"])
    t["day"] = pd.to_datetime(t["opened_ts"], unit="ms").dt.strftime("%Y-%m-%d")
    t["week"] = week_of(t["day"])
    hit = t.tm_pt + t.tm_ps
    t["lean"] = np.where(hit > 0, t.tm_pt / hit.where(hit > 0, 1), np.nan) - 1 / (1 + t.rr)
    t = t.dropna(subset=["lean"])
    print("\n=== Time Machine on OUR %d replay trades (12 markets) ===" % len(t))
    print("all trades      gross %s   net %s" % (fmt(ci(t, "R_gross")), fmt(ci(t, "R_net"))))
    print("Spearman(lean, R_gross) = %+.4f   (lean, R_net) = %+.4f" % (
        spearmanr(t.lean, t.R_gross).correlation, spearmanr(t.lean, t.R_net).correlation))
    t["q"] = pd.qcut(t.lean, 5, labels=False)
    print(t.groupby("q").agg(n=("R_net", "size"), lean=("lean", "mean"), R_gross=("R_gross", "mean"),
                             R_net=("R_net", "mean")).round(4).to_string())
    for name, m in (("lean > +0.05 (leans target)", t.lean > 0.05), ("lean > 0", t.lean > 0),
                    ("drop lean < -0.05", t.lean >= -0.05)):
        print("filter %-28s keeps %5.1f %%  net diff %s   gross diff %s" % (
            name, 100 * m.mean(), fmt(diff_ci(t, m, "R_net")), fmt(diff_ci(t, m, "R_gross"))))
        print("        kept trades net %s" % fmt(ci(t[m], "R_net")))


def us():
    p = os.path.join(RES, "us_orb.csv")
    if os.path.exists(p):
        df = pd.read_csv(p)
        orb_block(df, 4, "US stocks ORB, 60 days, home market")
        orb_block(df, 10, "US stocks ORB, 60 days, home market")
    p = os.path.join(RES, "us_daily.csv")
    if os.path.exists(p):
        daily(pd.read_csv(p), "US daily scan, 10 years")


def daily(df, label):
    df = df.dropna(subset=["next_oc", "fwd5"]).copy()
    df["week"] = week_of(df["day"])
    for col in ("next_oc", "fwd5"):
        df[col + "_x"] = df[col] - df.groupby("day")[col].transform("mean")   # vs same-day cross-section
    df["tags"] = df["tags"].fillna("")
    print("\n=== %s: %d stock-days ===" % (label, len(df)))
    for tag in ("breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce"):
        g = df[df.tags.str.contains(tag)]
        if len(g) < 30:
            continue
        print("%-16s n=%6d  next-day o->c excess %s bp   5-day excess %s bp" % (
            tag, len(g), fmtbp(ci(g, "next_oc_x")), fmtbp(ci(g, "fwd5_x"))))


def pipeline(orb_csv, daily_csv, label):
    """The skill's intended chain: pre-market tag (previous day's close) -> ORB long that day.
    Does a scanner tag improve the ORB trade?"""
    o = pd.read_csv(os.path.join(RES, orb_csv))
    o = o[o.side == 1].copy()
    d = pd.read_csv(os.path.join(RES, daily_csv))[["sym", "day", "tags"]]
    d["tags"] = d["tags"].fillna("")
    d = d.sort_values(["sym", "day"])
    d["next_day"] = d.groupby("sym")["day"].shift(-1)        # the tag is known before that day's open
    m = o.merge(d.rename(columns={"day": "tag_day", "next_day": "day"}), on=["sym", "day"], how="left")
    m["tags"] = m["tags"].fillna("")
    m["week"] = week_of(m["day"])
    print("\n=== pipeline %s: %d ORB longs, %d with a pre-market tag ===" % (label, len(m), (m.tags != "").sum()))
    print("all ORB longs            %s" % fmt(ci(m, "R")))
    for tag in ("", "breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce"):
        mask = (m.tags != "") if tag == "" else m.tags.str.split("|").apply(lambda x: tag in x)
        if mask.sum() < 30:
            continue
        print("tag %-18s n=%6d  R %s   vs all %s" % (tag or "(any)", mask.sum(), fmt(ci(m[mask], "R")),
                                                     fmt(diff_ci(m, mask, "R"))))


def fmtbp(t):
    return "%+.1f [%+.1f, %+.1f]" % tuple(1e4 * x for x in t)


if __name__ == "__main__":
    for a in ("ny", "utc"):
        p = os.path.join(RES, "crypto_%s.csv" % a)
        if os.path.exists(p):
            orb_block(pd.read_csv(p), 10, "crypto perps ORB, anchor %s" % a)
    ours()
    us()
    p = os.path.join(RES, "crypto_daily.csv")
    if os.path.exists(p):
        daily(pd.read_csv(p), "crypto daily scan (D1, all perps)")
