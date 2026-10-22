"""E-TM gates, exactly as E_TM_VORREGISTRIERUNG.md. Clustering and tail from E17's own code."""
import importlib.util, json, os, sys
from statistics import NormalDist
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "e17", os.path.join(HERE, "..", "..", "scripts", "study_e17_zeitebene.py"))
e17 = importlib.util.module_from_spec(spec)
sys.modules["e17"] = e17
spec.loader.exec_module(e17)

VERGLEICHE = 86
Z = NormalDist().inv_cdf(1 - 0.05 / (2 * VERGLEICHE))
MIN_TRADES = 200
WOCHE = 7 * 86_400_000


def lade():
    t = pd.read_csv(os.path.join(HERE, "results", "tm_0311.csv"))
    t = t.dropna(subset=["tm_pt", "tm_ps"])
    t = t[(t.tm_pt + t.tm_ps) > 0].copy()
    t["lean"] = t.tm_pt / (t.tm_pt + t.tm_ps) - 1 / (1 + t.rr)
    t["arm"] = t.lean >= -0.05
    t["block"] = (t.opened_ts - t.opened_ts.min()) // WOCHE
    return t


def mittel(g):
    return e17.zweiweg(g.R.values, g.sym.values, g.block.values, Z)


def differenz(g):
    """(arm mean - base mean) with a two-way clustered interval via influence values."""
    r, m = g.R.values, g.arm.values.astype(float)
    p = m.mean()
    ma, mb = r[m == 1].mean(), r.mean()
    u = m / p * (r - ma) - (r - mb)          # mean(u) == 0; its clustered SE is the SE of the difference
    _, lo, hi = e17.zweiweg(u, g.sym.values, g.block.values, Z)
    return ma - mb, ma - mb + lo, ma - mb + hi


def main():
    t = lade()
    out = {"vergleiche": VERGLEICHE, "z": Z}
    for name, g in (("ungesehen", t[~t.seen]), ("gesehen_0311", t[t.seen])):
        a = g[g.arm]
        out[name] = {
            "maerkte": int(g.sym.nunique()), "trades_basis": len(g), "trades_arm": len(a),
            "anteil_behalten": round(len(a) / len(g), 4),
            "basis": mittel(g), "arm": mittel(a), "differenz": differenz(g),
            "spearman_lean_R": float(g.lean.rank().corr(g.R.rank())),
            "schwanz_arm": e17.schwanz([{"r": x.R, "ts": x.opened_ts, "symbol": x.sym} for x in a.itertuples()]),
        }
    u = out["ungesehen"]
    if u["trades_arm"] < MIN_TRADES:
        urteil = "UNENTSCHEIDBAR"
    else:
        tor1 = u["arm"][1] > 0
        tor2 = u["differenz"][1] > 0
        out["tor1_absolut"], out["tor2_verbesserung"] = bool(tor1), bool(tor2)
        urteil = "BESTANDEN" if tor1 and tor2 else "GEFALLEN"
    out["urteil"] = urteil
    print(json.dumps(out, indent=1, default=float))
    json.dump(out, open(os.path.join(HERE, "results", "E_TM_ERGEBNIS.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
