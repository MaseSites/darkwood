"""Zehn Millionen Sechs-Monats-Szenarien -- und was die besten gemeinsam haben.

**Die Frage.** Unter zehn Millionen Konten, die dasselbe System handeln, gibt
es sehr gute. Was unterscheidet sie? Und ist dieser Unterschied etwas, das man
VORHER wissen kann -- dann waere es eine Strategie -- oder etwas, das erst
hinterher feststeht?

**Wie zehn Millionen rechenbar werden.** Bei festem Margin-Anteil haengt es
NICHT vom Kontostand ab, wie viele Positionen ins Konto passen: jede bindet
denselben Anteil. Damit ist die Menge der genommenen Trades eines Monats eine
Eigenschaft des Monats, nicht des Kontos -- und der Monatsfaktor ist eine
Konstante. Ein Szenario ist das Produkt von sechs gezogenen Monatsfaktoren.

Das ist keine Vereinfachung aus Bequemlichkeit, sondern eine nachgerechnete
Eigenschaft der Groessenregel. Die eine Stelle, an der sie bricht, ist der
Kontoboden: unter einem Rest laesst sich keine Position mehr stellen. Darum
wird je Monat ZUSAETZLICH der tiefste Zwischenstand gefuehrt, und ein Szenario
stirbt, sobald es ihn unterschreitet.

**Was analysiert wird.** Die Zusammensetzung der besten Szenarien: welche
Monate kommen darin vor, wie oft, und in welcher Reihenfolge. Daraus die
entscheidende Frage: sagt ein guter Monat etwas ueber den naechsten? Nur dann
liesse sich die Erkenntnis in echtes Geld uebersetzen.

    python scripts/study_zehn_millionen.py
    python scripts/study_zehn_millionen.py --laeufe 1000000 --hebel 2.1 --margin-anteil 1.0
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.learn.aussicht import (
    BLOCK_TAGE,
    BODEN,
    MIN_TRADES_JE_BLOCK,
    TAG_MS,
    Fill,
    _block_faktor,
)

START = 1_000.0
#: Monate je Szenario.
MONATE = 6

#: Ein Monat mit weniger Trades ist kein Monat, sondern eine Luecke.
MIN_TRADES = 10

#: Unter so vielen guten Szenarien laesst sich nichts zerlegen.
MIN_GUTE = 20


def bausteine(root: Path, *, anteil: float, hebel: float
              ) -> tuple[list[int], np.ndarray, np.ndarray]:
    """Die Monatsfaktoren, mit ihren Startzeitpunkten.

    Nutzt `learn.aussicht._block_faktor` statt einer zweiten Fassung: das
    Dashboard und dieses Skript muessen dieselbe Zahl zeigen, und zwei
    Implementierungen derselben Rechnung driften irgendwann um ein paar
    Hundertstel auseinander -- genau die Groesse der Effekte, um die es hier
    geht.
    """
    fills: list[Fill] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            gelesen = Fill.von(row)
            if gelesen is not None:
                fills.append(gelesen)
    fills.sort(key=lambda f: f.opened_ts)
    t0, t1 = fills[0].opened_ts, fills[-1].opened_ts

    start: list[int] = []
    faktor: list[float] = []
    tiefst: list[float] = []
    anfang = t0
    while anfang + BLOCK_TAGE * TAG_MS <= t1:
        block = [f for f in fills if anfang <= f.opened_ts < anfang + BLOCK_TAGE * TAG_MS]
        if len(block) >= MIN_TRADES_JE_BLOCK:
            f_, tief = _block_faktor(block, margin_share=anteil, leverage=hebel)
            start.append(anfang)
            faktor.append(f_)
            tiefst.append(tief)
        anfang += BLOCK_TAGE * TAG_MS
    return start, np.array(faktor), np.array(tiefst)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--laeufe", type=int, default=10_000_000)
    parser.add_argument("--margin-anteil", type=float, default=0.30)
    parser.add_argument("--hebel", type=float, default=7.0)
    parser.add_argument("--seed", type=int, default=20261019)
    args = parser.parse_args(argv)

    start, faktor, tiefst = bausteine(
        args.fills, anteil=args.margin_anteil, hebel=args.hebel
    )
    bloecke = start

    print(f"{len(faktor)} echte Monate als Bausteine, "
          f"{args.margin_anteil:.0%} Margin x {args.hebel:g}x")
    print(f"  Monatsfaktor: schlechtester {faktor.min():.4f}  Median "
          f"{np.median(faktor):.4f}  bester {faktor.max():.4f}")
    print(f"  Monate mit Faktor > 1: {int((faktor > 1).sum())} von {len(bloecke)}\n")

    # -- Zehn Millionen Szenarien ----------------------------------------- #
    rng = np.random.default_rng(args.seed)
    print(f"{args.laeufe:,} Szenarien a {MONATE} Monate ...")
    zug = rng.integers(0, faktor.size, size=(args.laeufe, MONATE))

    konto = np.full(args.laeufe, 1.0)
    lebt = np.ones(args.laeufe, dtype=bool)
    for m in range(MONATE):
        idx = zug[:, m]
        # Stirbt das Konto INNERHALB des Monats an seinem tiefsten Punkt?
        lebt &= (konto * tiefst[idx]) > BODEN
        konto = np.where(lebt, konto * faktor[idx], konto)
    ende = konto * START
    ende[~lebt] = 0.0

    srt = np.sort(ende)
    n = ende.size

    print(f"\nERGEBNIS ueber {n:,} Szenarien")
    for q in (0.05, 0.25, 0.50, 0.75, 0.95, 0.99, 0.999, 0.9999):
        print(f"  {q:7.2%}-Perzentil {srt[min(n-1, int(q*n))]:14,.0f} CHF")
    print(f"  bestes            {srt[-1]:14,.0f} CHF")
    for s in (1_000, 10_000, 20_000, 50_000, 100_000):
        k = int((ende >= s).sum())
        print(f"  >= {s:>7,} CHF   {k:10,d}  ({k/n:.5%})")

    return zerlege(ende, zug, faktor, bloecke, rng)


def zerlege(ende, zug, faktor, bloecke, rng) -> int:
    """Was die besten Szenarien gemeinsam haben -- und ob man es vorher weiss."""

    schwelle = 20_000.0
    gut = ende >= schwelle
    print(f"\n{'=' * 70}\nWAS HABEN DIE {int(gut.sum()):,} SZENARIEN UEBER "
          f"{schwelle:,.0f} CHF GEMEINSAM?\n{'=' * 70}")
    if gut.sum() < MIN_GUTE:
        print("  Zu wenige fuer eine Analyse.")
        return 0

    print("\n1. WELCHE MONATE ZIEHEN SIE?")
    haeufig_gut = np.bincount(zug[gut].ravel(), minlength=len(faktor)) / (gut.sum() * MONATE)
    haeufig_alle = np.full(len(faktor), 1.0 / len(faktor))
    ordnung = np.argsort(-haeufig_gut)
    print(f"   {'Monat ab':12s} {'Faktor':>8s} {'Anteil gut':>11s} "
          f"{'Anteil alle':>12s} {'Verhaeltnis':>12s}")
    for i in ordnung[:8]:
        tag = datetime.datetime.fromtimestamp(
            bloecke[i] / 1000, datetime.UTC).strftime("%d.%m.%Y")
        print(f"   {tag:12s} {faktor[i]:8.4f} {haeufig_gut[i]:11.3%} "
              f"{haeufig_alle[i]:12.3%} {haeufig_gut[i]/haeufig_alle[i]:11.2f}x")

    print("\n2. WIE VIELE DER SECHS MONATE SIND GEWINNMONATE?")
    gewinnmonate = (faktor[zug] > 1.0).sum(axis=1)
    for k in range(MONATE + 1):
        a = (gewinnmonate[gut] == k).mean() if gut.sum() else 0.0
        b = (gewinnmonate == k).mean()
        print(f"   {k} von {MONATE}: bei den guten {a:7.2%}   bei allen {b:7.2%}")

    print("\n3. SPIELT DIE REIHENFOLGE EINE ROLLE?")
    print("   (dieselben sechs Monate, anders sortiert -- aendert das den Ausgang?)")
    probe = zug[gut][: min(2000, int(gut.sum()))]
    gleich = 0
    for reihe in probe:
        p = START
        for i in sorted(reihe, key=lambda j: faktor[j]):      # schlechte zuerst
            p *= faktor[i]
        q = START
        for i in sorted(reihe, key=lambda j: -faktor[j]):     # gute zuerst
            q *= faktor[i]
        gleich += 1 if abs(p - q) < 0.01 * max(p, q) else 0
    print(f"   Bei {gleich}/{len(probe)} der guten Szenarien ist das Produkt")
    print("   unabhaengig von der Reihenfolge (ohne Kontoboden ist es das IMMER).")

    print("\n4. DIE ENTSCHEIDENDE FRAGE: SAGT EIN MONAT ETWAS UEBER DEN NAECHSTEN?")
    lf = np.log(np.maximum(faktor, 1e-9))
    rho = float(np.corrcoef(lf[:-1], lf[1:])[0, 1])
    perm = np.array([
        float(np.corrcoef(x[:-1], x[1:])[0, 1])
        for x in (rng.permutation(lf) for _ in range(4000))
    ])
    lo, hi = np.percentile(perm, [2.5, 97.5])
    drin = lo <= rho <= hi
    print(f"   Autokorrelation der Monatsfaktoren: {rho:+.4f}")
    print(f"   Zufallsband aus 4.000 Mischungen:   [{lo:+.4f}, {hi:+.4f}]")
    print(f"   -> {'INNERHALB -- kein Zusammenhang' if drin else 'AUSSERHALB'}")
    print(f"\n   Nach einem GUTEN Monat folgt im Median ein Faktor von "
          f"{np.median(faktor[1:][faktor[:-1] > 1]):.4f}")
    print(f"   Nach einem SCHLECHTEN Monat:                           "
          f"{np.median(faktor[1:][faktor[:-1] <= 1]):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
