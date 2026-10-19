"""E18 — der Kostendeckel, out-of-sample. Regel steht in der Vorregistrierung.

**Lies `audit/E18_KOSTENDECKEL_VORREGISTRIERUNG.md`, bevor du eine Zahl aus
diesem Skript benutzt.** Dort steht die Auswahlregel, und sie wurde
aufgeschrieben, bevor der gesperrte Teil gerechnet wurde.

**Was gemessen wird.** Das Kostentor lehnt beim produktiven Deckel 48 % aller
Signale ab und ist damit die bindendste Regel des Systems. Im Register fällt
die Erwartung je Trade fast monoton, je lockerer der Deckel — aber alle sechs
Intervalle schliessen die Null ein, und die Zahlen stammen aus derselben
Population, aus der der Deckel gewählt würde.

**Wie der Deckel aus einem Fill fällt, ohne ihn nachzuschlagen.** Die
Kostenquote ist

    cost_fraction = Rundenkosten / Risiko
                  = Nominal * c / Risiko
                  = c / Stopweite        (die Menge kürzt sich heraus)

und die Stopweite steht im Fill: `risk_amount / (qty * entry_price)`. Jeder
gespeicherte Trade trägt seine Kostenquote also in sich, und ein Deckel ist
schlicht ein Filter darauf.

**Die Teilung ist zeitlich, nicht zufällig.** Ein gemeinsamer Wochenfaktor
trägt gemessen 96,9 % der Struktur; eine zufällige Teilung legt Trades
derselben Woche auf beide Seiten und schmuggelt die Antwort über die Grenze.

    python scripts/study_e18_kostendeckel.py
    python scripts/study_e18_kostendeckel.py --auswahl-anteil 0.6
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.domain.market import DEFAULT_SPEC

#: Die sechs Kandidaten aus der Vorregistrierung. Nichts dazwischen.
DECKEL = (0.03, 0.04, 0.06, 0.08, 0.10, 0.12)

#: Der produktive Deckel -- die Vergleichsgrösse, nicht die Null.
PRODUKTIV = 0.08

TAG_MS = 86_400_000
ZIEHUNGEN = 20_000
SEED = 20261019

#: Unter so wenigen Beobachtungen ist ein Mittelwert keiner.
MIN_N = 2


def lade(root: Path, schlupf_bps: float) -> list[dict[str, object]]:
    """Jeder Fill mit seiner Kostenquote, aus sich selbst gerechnet."""
    c = DEFAULT_SPEC["maker_fee"] + DEFAULT_SPEC["taker_fee"] + schlupf_bps * 1e-4
    zeilen: list[dict[str, object]] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            entry, qty = float(row["entry_price"]), float(row["qty"])
            risiko = float(row["risk_amount"])
            if entry <= 0 or qty <= 0 or risiko <= 0:
                continue
            stopweite = risiko / (qty * entry)
            if stopweite <= 0:
                continue
            zeilen.append({
                "symbol": blob["symbol"],
                "ts": int(row["opened_ts"]),
                "r": float(row["r_multiple"]),
                "kostenquote": c / stopweite,
            })
    zeilen.sort(key=lambda z: z["ts"])
    return zeilen


def _zweiweg_intervall(
    werte: np.ndarray, markt: np.ndarray, zeit: np.ndarray
) -> tuple[float, float]:
    """95 % nach Cameron/Gelbach/Miller: V = V_markt + V_zeit - V_schnitt.

    Nicht nur nach Markt geclustert, weil am 19.10.2026 gemessen wurde, dass
    das nur 0,682 der wahren Streuung erfasst -- ein gemeinsamer Wochenfaktor
    trägt 96,9 % der Struktur.
    """
    n = werte.size
    if n < MIN_N:
        return float("nan"), float("nan")
    e = werte - werte.mean()

    def v(gruppen: np.ndarray) -> float:
        return float(sum(e[gruppen == g].sum() ** 2 for g in set(gruppen.tolist()))) / (n * n)

    schnitt = np.array([f"{a}|{b}" for a, b in zip(markt, zeit, strict=True)])
    var = v(markt) + v(zeit) - v(schnitt)
    if var <= 0:
        return float("nan"), float("nan")
    se = math.sqrt(var)
    return werte.mean() - 1.96 * se, werte.mean() + 1.96 * se


def _bloecke(ts: np.ndarray, tage: int = 7) -> np.ndarray:
    return ((ts - ts.min()) // (tage * TAG_MS)).astype(int)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--auswahl-anteil", type=float, default=0.70)
    args = parser.parse_args(argv)

    cfg = load_config()
    zeilen = lade(args.fills, cfg.engine.simulation.slippage_bps)
    t0, t1 = zeilen[0]["ts"], zeilen[-1]["ts"]
    grenze = int(t0 + (t1 - t0) * args.auswahl_anteil)

    def tag(ms: int) -> str:
        return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%d.%m.%Y")

    auswahl = [z for z in zeilen if z["ts"] < grenze]
    gesperrt = [z for z in zeilen if z["ts"] >= grenze]
    print(f"{len(zeilen):,} Fills, zeitlich geteilt bei {tag(grenze)}")
    print(f"  Auswahlmenge  {tag(t0)} .. {tag(grenze)}   {len(auswahl):,} Trades")
    print(f"  GESPERRT      {tag(grenze)} .. {tag(t1)}   {len(gesperrt):,} Trades\n")

    # -- Teil 1: Auswahl, nur auf der Auswahlmenge ------------------------ #
    print("TEIL 1 -- AUSWAHL (nur Auswahlmenge, gesperrter Teil unberuehrt)")
    print(f"{'Deckel':>8s} {'Trades':>8s} {'Anteil':>8s} {'Mittel R':>10s} {'R GESAMT':>11s}")
    bestes, bester_deckel = -1e18, None
    for d in DECKEL:
        genommen = [z for z in auswahl if z["kostenquote"] <= d]
        if not genommen:
            continue
        r = np.array([z["r"] for z in genommen])
        summe = float(r.sum())
        marke = "  <- produktiv" if d == PRODUKTIV else ""
        print(f"{d:8.2f} {r.size:8,d} {r.size/len(auswahl):8.1%} "
              f"{r.mean():+10.4f} {summe:+11.1f}{marke}")
        if summe > bestes:
            bestes, bester_deckel = summe, d

    print("\n  Auswahlregel (vorregistriert): hoechste GESAMTSUMME in R.")
    print(f"  -> gewaehlt: Deckel {bester_deckel:.2f} mit {bestes:+.1f} R")
    if bester_deckel == PRODUKTIV:
        print("  Das ist der produktive Deckel. Es gibt nichts zu testen.")
        return 0

    return pruefe(gesperrt, bester_deckel)


def pruefe(gesperrt: list[dict[str, object]], bester_deckel: float) -> int:
    """Der EINE Lauf auf dem gesperrten Teil. Kein zweiter."""
    print("\nTEIL 2 -- DER TEST (gesperrter Teil, einmal)")
    sym = np.array([z["symbol"] for z in gesperrt])
    ts = np.array([z["ts"] for z in gesperrt], dtype=np.int64)
    kq = np.array([z["kostenquote"] for z in gesperrt])
    r = np.array([z["r"] for z in gesperrt])
    blk = _bloecke(ts)

    print(f"{'Deckel':>8s} {'Trades':>8s} {'Mittel R':>10s} {'R GESAMT':>11s} "
          f"{'95 %-Intervall':>24s}")
    ergebnis = {}
    for d in (PRODUKTIV, bester_deckel):
        m = kq <= d
        lo, hi = _zweiweg_intervall(r[m], sym[m], blk[m])
        ergebnis[d] = (r[m], m)
        name = "produktiv" if d == PRODUKTIV else "gewaehlt"
        print(f"{d:8.2f} {int(m.sum()):8,d} {r[m].mean():+10.4f} {r[m].sum():+11.1f} "
              f"[{lo:+.4f}, {hi:+.4f}]  {name}")

    # -- Das vorregistrierte Kriterium ------------------------------------ #
    r_prod, m_prod = ergebnis[PRODUKTIV]
    r_neu, m_neu = ergebnis[bester_deckel]
    diff = float(r_neu.mean() - r_prod.mean())

    # Die Differenz als EINE Groesse bootstrappen: je Zeitblock und Markt
    # werden BEIDE Mengen gemeinsam gezogen, sonst vergleicht man zwei
    # unabhaengig gezogene Stichproben derselben Wochen.
    rng = np.random.default_rng(SEED)
    paare = sorted({(s, int(b)) for s, b in zip(sym, blk, strict=True)})
    idx = {p: np.where((sym == p[0]) & (blk == p[1]))[0] for p in paare}
    zuege = []
    for _ in range(ZIEHUNGEN):
        pick = [paare[i] for i in rng.integers(0, len(paare), len(paare))]
        teile = np.concatenate([idx[p] for p in pick])
        a, b = m_prod[teile], m_neu[teile]
        if a.sum() < MIN_N or b.sum() < MIN_N:
            continue
        zuege.append(r[teile][b].mean() - r[teile][a].mean())
    lo, hi = np.percentile(zuege, [2.5, 97.5])

    print("\nDAS VORREGISTRIERTE KRITERIUM")
    print(f"  1) Erwartung besser als produktiv?   {diff:+.4f} R   "
          f"{'JA' if diff > 0 else 'NEIN'}")
    print(f"  2) Intervall der Differenz ohne null? [{lo:+.4f}, {hi:+.4f}]   "
          f"{'JA' if (lo > 0 or hi < 0) else 'NEIN'}")
    print(f"     (zwei-weg geclustert, {len(zuege):,} gueltige Ziehungen, Seed {SEED})")
    bestanden = diff > 0 and (lo > 0 or hi < 0)
    print(f"\n  E18 {'BESTANDEN' if bestanden else 'GEFALLEN'}")
    if not bestanden:
        print("  Nach der Vorregistrierung ist der Kostendeckel als Hebel damit")
        print("  erledigt und wird nicht erneut variiert. Produktiv bleibt 0,08.")
    else:
        print("  Die erste out-of-sample bestaetigte positive Kante dieses")
        print("  Projekts. Sie erreicht die 20x NICHT -- die Schranke liegt bei")
        print("  +0,1851 R -- aber sie ist das erste, was traegt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
