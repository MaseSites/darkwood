"""Severins Plan, gerechnet: 300 CHF Margin, 7x Hebel, und dann aufstocken.

**Der Plan, wie er gestellt wurde.** Von 1.000 CHF mit 300 CHF in einen Trade,
7x Hebel. Nach einem Gewinn mit 350 in den zweiten, dann 400, dann 470 — also
die Margin als FESTER ANTEIL des gewachsenen Kontos. Das ist ein bekanntes und
korrektes Verfahren (fixed-fractional sizing), und es ist genau der Mechanismus,
durch den eine positive Kante exponentiell wächst.

**Was dieses Skript prüft, ist nicht die Idee, sondern das Vorzeichen.**
Dieselbe Formel, die eine positive Kante vervielfacht, vervielfacht eine
negative. Das Konto wächst mit `(1 + f * R)` je Trade; der Erwartungswert des
Logarithmus ist näherungsweise `f * E[R] - f^2 * Var(R) / 2`. Beide Terme sind
negativ, sobald `E[R] < 0` — der erste linear in `f`, der zweite quadratisch.
Mehr Hebel macht das Ergebnis also nicht besser, sondern **schneller
schlechter**, und es gibt kein `f > 0`, das das Vorzeichen dreht.

Das ist keine Meinung, das ist die Rechnung. Dieses Skript führt sie mit den
echten 7.335 Trades durch, statt sie zu behaupten.

**Drei Dinge, die der Plan zusätzlich trifft und die in der Idee nicht
vorkommen:**

1. *Liquidation.* Bei 7x liegt sie rund 14 % vom Einstieg entfernt. 1 % der
   gemessenen Trades hat einen Stop, der **weiter** liegt — dort schliesst die
   Börse vor dem Stop und die ganze Margin ist weg, nicht der geplante Betrag.
2. *Der Kontoboden.* Unter einem Mindestnominal lässt sich die Position nicht
   mehr stellen; danach ist das Konto handlungsunfähig, auch wenn noch Geld da
   ist.
3. *Die Reihenfolge.* Ein Pfad ist Glück. Darum wird nicht ein Pfad gerechnet,
   sondern 20.000 Umordnungen derselben Trades.

    python scripts/study_leverage_plan.py
    python scripts/study_leverage_plan.py --margin-anteil 0.30 --hebel 7
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

#: Wartungsmarge aus `data/venue_specs/binance.json` -- 0,5 % fuer alle zwoelf.
MMR = 0.005

#: Unter diesem Kontostand ist kein Trade mehr stellbar. Das kleinste
#: Mindestnominal der zwoelf Maerkte ist 5 USDT, das groesste 50 (BTC); bei
#: einem Nominal von Konto x Anteil x Hebel ist der Boden entsprechend klein,
#: aber er ist nicht null, und ein Konto unter 1 % des Starts ist praktisch tot.
BODEN_ANTEIL = 0.01


def lade(root: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """R, Stopabstand als Preisanteil, und Eroeffnungszeit -- in Zeitordnung."""
    zeilen: list[tuple[int, float, float]] = []
    for path in sorted(root.glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8"))["fills"]:
            e, q = float(row["entry_price"]), float(row["qty"])
            if e <= 0 or q <= 0:
                continue
            zeilen.append(
                (
                    int(row["opened_ts"]),
                    float(row["r_multiple"]),
                    (float(row["risk_amount"]) / q) / e,
                )
            )
    zeilen.sort()
    return (
        np.array([z[1] for z in zeilen]),
        np.array([z[2] for z in zeilen]),
        np.array([z[0] for z in zeilen]),
    )


def ein_pfad(
    r: np.ndarray,
    stop: np.ndarray,
    *,
    f_nominal: float,
    hebel: float,
    start: float = 1.0,
) -> tuple[float, float, int]:
    """Ein Durchlauf. Gibt Endstand, groessten Rueckgang und Trades bis zum Boden.

    `f_nominal` ist Nominal geteilt durch Konto. Der Verlust am Stop ist
    `f_nominal * stop * |R|` des Kontos -- die Groesse kuerzt sich NICHT weg,
    weil sie hier als Anteil des Kontos wirkt und nicht als Skalierung von R.

    Liquidation: eine Gegenbewegung von `1/hebel - MMR` loescht die Margin. Ist
    der Stop weiter entfernt, trifft die Boerse zuerst, und der Verlust ist die
    ganze Margin statt des geplanten Betrags.
    """
    liq_abstand = 1.0 / hebel - MMR
    margin_anteil = f_nominal / hebel
    konto = start
    hoch = start
    boden_bei = -1
    for i in range(r.size):
        if konto <= start * BODEN_ANTEIL:
            boden_bei = i
            break
        verlust_weg = min(stop[i], liq_abstand) if r[i] < 0 else stop[i]
        if r[i] < 0 and stop[i] > liq_abstand:
            # Liquidation vor dem Stop: die ganze Margin ist weg.
            schritt = -margin_anteil
        else:
            schritt = f_nominal * verlust_weg * r[i]
        konto *= 1.0 + schritt
        konto = max(konto, 0.0)
        hoch = max(hoch, konto)
    rueckgang = 1.0 - konto / hoch if hoch > 0 else 1.0
    return konto, rueckgang, boden_bei


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--margin-anteil", type=float, default=0.30,
                        help="300 von 1.000 CHF = 0.30")
    parser.add_argument("--hebel", type=float, default=7.0)
    parser.add_argument("--umordnungen", type=int, default=2_000)
    args = parser.parse_args(argv)

    r, stop, _ts = lade(args.fills)
    print(f"{r.size:,} Trades, Erwartungswert {r.mean():+.4f} R\n")

    f_plan = args.margin_anteil * args.hebel
    print("1. DEIN PLAN, EINMAL IN DER ECHTEN REIHENFOLGE")
    print(
        f"   {args.margin_anteil:.0%} Margin x {args.hebel:g}x Hebel "
        f"= Nominal {f_plan:.2f}x Konto"
    )
    liq = 1.0 / args.hebel - MMR
    zu_weit = int((stop > liq).sum())
    print(f"   Liquidation liegt {liq:.2%} entfernt")
    print(
        f"   Trades mit Stop JENSEITS der Liquidation: {zu_weit:,} "
        f"({zu_weit / r.size:.2%}) -- dort trifft die Boerse zuerst"
    )
    ende, dd, boden = ein_pfad(r, stop, f_nominal=f_plan, hebel=args.hebel)
    print(f"   Endstand nach {r.size:,} Trades: {ende:.6f}x des Starts")
    print(f"   groesster Rueckgang: {dd:.2%}")
    if boden >= 0:
        print(f"   KONTOBODEN nach {boden:,} Trades erreicht")

    # -- 2. Die Reihenfolge ist Glueck, also viele Reihenfolgen ------------- #
    print(f"\n2. {args.umordnungen:,} UMORDNUNGEN DERSELBEN TRADES")
    rng = np.random.default_rng(7)
    enden, boeden = [], 0
    for _ in range(args.umordnungen):
        idx = rng.permutation(r.size)
        e, _d, b = ein_pfad(r[idx], stop[idx], f_nominal=f_plan, hebel=args.hebel)
        enden.append(e)
        boeden += 1 if b >= 0 else 0
    enden_a = np.array(enden)
    print(f"   Median Endstand   {np.median(enden_a):.6f}x")
    print(f"   5. Perzentil      {np.percentile(enden_a, 5):.6f}x")
    print(f"   95. Perzentil     {np.percentile(enden_a, 95):.6f}x")
    print(f"   besser als Start  {(enden_a > 1.0).mean():.2%} der Umordnungen")
    print(f"   Kontoboden        {boeden / args.umordnungen:.2%} der Umordnungen")

    # -- 3. Mehr Hebel macht es schneller schlechter ----------------------- #
    print("\n3. DER HEBEL ALS SCHALTER -- dieselbe Trade-Folge, nur andere Groesse")
    print(f"   {'Margin':>7s} {'Hebel':>6s} {'Nominal':>8s} {'Endstand':>12s} "
          f"{'Rueckgang':>10s} {'Boden':>7s}")
    for ma, hb in ((0.01, 1.0), (0.05, 1.0), (0.10, 2.0), (0.20, 5.0),
                   (0.30, 7.0), (0.30, 10.0), (0.50, 10.0)):
        e, d, b = ein_pfad(r, stop, f_nominal=ma * hb, hebel=hb)
        print(
            f"   {ma:7.0%} {hb:6.0f}x {ma*hb:7.2f}x {e:12.6f}x {d:10.2%} "
            f"{('nach ' + format(b, ',')) if b >= 0 else 'nein':>7s}"
        )

    # -- 4. Was es braeuchte, damit der Plan aufgeht ----------------------- #
    print("\n4. WAS DER PLAN BRAUCHT, DAMIT ER AUFGEHT")
    mittel_stop = float(stop.mean())
    # Erwartungswert des Logarithmus, naeherungsweise: f*E[R] - f^2*Var/2,
    # mit f = f_nominal * Stopanteil als Kontoanteil je Trade.
    f_konto = f_plan * mittel_stop
    var = float((stop * r).var()) * f_plan**2
    print(f"   Risiko je Trade als Kontoanteil (Mittel) : {f_konto:.2%}")
    print(f"   E[R] heute                               : {r.mean():+.4f}")
    noetig = f_konto * 0 + (var / 2.0) / f_konto if f_konto > 0 else float("nan")
    print(
        f"   E[R] noetig, nur damit das Konto NICHT faellt (Varianzausgleich): "
        f"{noetig:+.4f}"
    )
    print(
        "\n   Das ist der Punkt, und er hat nichts mit der Groesse zu tun:\n"
        "   solange E[R] negativ ist, ist JEDE Groesse > 0 ein Verlust, und\n"
        "   eine groessere Groesse ist ein GROESSERER Verlust. Die Groesse\n"
        "   entscheidet nur, wie schnell. Sie kann das Vorzeichen nicht drehen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
