"""Welche der 7.335 Fills hätte die echte Instrumentspec nicht entstehen lassen?

**Die Frage, die nach der Gebühr übrig bleibt.** `scripts/study_venue_fee.py`
hat den Gebührenteil exakt gerechnet: +0.0014 R. Die Instrumentregeln sind der
andere Teil, und sie wirken anders -- nicht auf das Ergebnis eines Trades,
sondern darauf, **ob er überhaupt entsteht**.

`DEFAULT_SPEC` trägt `qty_step = min_qty = 0.001` für alle zwölf Märkte. Echt
sind, gemessen am 18.10.2026 (`data/venue_specs/binance.json`):

    ADA, AVAX, DOGE   qty_step = min_qty = 1       -- Faktor 1000
    XRP, DOT          qty_step = min_qty = 0.1     -- Faktor 100
    SOL, LINK, BNB, ATOM  0.01                     -- Faktor 10
    BTC, ETH, LTC     0.001                        -- wie angenommen

und `min_notional` zwischen 5 und **50** gegen angenommene 5 überall.

**Warum das ohne Neulauf zu rechnen ist, und wo die Grenze liegt.** Jeder Fill
trägt `qty` und `risk_amount`. Die gespeicherte `qty` ist das Ergebnis von
`int(raw/0.001)*0.001`, liegt also höchstens 0.001 unter der Rohgrösse -- für
die Frage „hätte die echte Schrittweite auf null gerundet" ist `qty` damit eine
gute Schätzung der Rohgrösse, und zwar eine **konservative**: sie unterschätzt
sie nie um mehr als einen Legacy-Schritt.

Was dieses Skript darum NICHT sagt: wie sich die Population verändert. Ein
abgelehnter Trade gibt seinen Platz frei, ein anderer rückt nacht -- das
entscheidet nur ein Neulauf mit gemeinsamem Konto. Gemessen wird hier, **wie
viele Trades die echte Spec gar nicht zugelassen hätte**, und was die
verbleibenden im Mittel liefern.

    python scripts/study_spec_effect.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from traidingbrain.sim.metrics import bootstrap_mean

#: Was der Legacy-Lauf angenommen hat (`domain/market.py:77`).
LEGACY_STEP = 0.001
LEGACY_MIN_QTY = 0.001
LEGACY_MIN_NOTIONAL = 5.0


def lade_specs(path: Path) -> dict[str, dict[str, float]]:
    blob = json.loads(path.read_text(encoding="utf-8"))
    if blob.get("incomplete"):
        print(
            f"ABBRUCH: der Schnappschuss {path} hat Luecken "
            f"({sorted(blob['incomplete'])}). Eine Messung gegen eine "
            f"unvollstaendige Spec waere teilweise gegen DEFAULT_SPEC.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(
        f"Spec-Schnappschuss {blob['venue']} / {blob['environment']}, "
        f"gelesen {blob['fetched_utc']}, ccxt {blob['ccxt_version']}"
    )
    return {str(k): v for k, v in blob["specs"].items()}


def lade_fills(root: Path) -> list[tuple[str, dict[str, object]]]:
    zeilen: list[tuple[str, dict[str, object]]] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            zeilen.append((str(blob["symbol"]), row))
    return zeilen


def berichte_maerkte(
    zeilen: list[tuple[str, dict[str, object]]],
    specs: dict[str, dict[str, float]],
) -> tuple[list[float], list[float], int]:
    """Je Markt: wie viele Fills die echte Spec abgelehnt hätte, und warum.

    Drei getrennte Spalten für die drei Gründe. Eine Gesamtzahl „abgelehnt"
    hätte nicht gesagt, ob es die Schrittweite, die Mindeststückzahl oder das
    Mindestnominal war -- und das sind drei verschiedene Befunde.
    """
    print("JE MARKT: wie viele Fills die echte Spec abgelehnt haette")
    print(
        f"   {'Symbol':10s} {'n':>6s} {'step':>8s} {'minqty':>8s} "
        f"{'minnot':>7s} {'step->0':>8s} {'<minqty':>8s} {'<minnot':>8s} "
        f"{'bleibt':>7s}"
    )
    gehalten: list[float] = []
    alle: list[float] = []
    verloren_gesamt = 0
    for symbol in sorted({s for s, _r in zeilen}):
        spec = specs[symbol]
        step, min_qty = spec["qty_step"], spec["min_qty"]
        min_notional = spec["min_notional"]
        teil = [r for s, r in zeilen if s == symbol]

        null = unter_qty = unter_notional = 0
        for row in teil:
            qty = float(row["qty"])  # type: ignore[arg-type]
            entry = float(row["entry_price"])  # type: ignore[arg-type]
            # Die Rohgroesse, auf die ECHTE Schrittweite abgerundet.
            echt = int(qty / step) * step
            if echt <= 0.0:
                null += 1
            elif echt < min_qty:
                unter_qty += 1
            elif echt * entry < min_notional:
                unter_notional += 1
            else:
                gehalten.append(float(row["r_multiple"]))  # type: ignore[arg-type]
        alle.extend(float(row["r_multiple"]) for row in teil)  # type: ignore[arg-type]
        verloren = null + unter_qty + unter_notional
        verloren_gesamt += verloren
        print(
            f"   {symbol:10s} {len(teil):6,} {step:8g} {min_qty:8g} "
            f"{min_notional:7g} {null:8,} {unter_qty:8,} {unter_notional:8,} "
            f"{len(teil) - verloren:7,}"
        )

    print(
        f"\n   {'GESAMT':10s} {len(alle):6,} abgelehnt {verloren_gesamt:,} "
        f"({verloren_gesamt / len(alle):.2%}), bleibt {len(gehalten):,}"
    )
    return gehalten, alle, verloren_gesamt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument(
        "--specs", type=Path, default=Path("data/venue_specs/binance.json")
    )
    parser.add_argument("--draws", type=int, default=20_000)
    args = parser.parse_args(argv)

    specs = lade_specs(args.specs)
    zeilen = lade_fills(args.fills)
    if not zeilen:
        print(f"keine Fills unter {args.fills}", file=sys.stderr)
        return 2
    print(f"{len(zeilen):,} Fills\n")

    fehlend = sorted({s for s, _r in zeilen} - set(specs))
    if fehlend:
        print(
            f"ABBRUCH: fuer {', '.join(fehlend)} gibt es keine Spec im "
            f"Schnappschuss.",
            file=sys.stderr,
        )
        return 2

    gehalten, alle, _verloren = berichte_maerkte(zeilen, specs)

    print("\nERWARTUNGSWERT")
    ganz = bootstrap_mean(np.array(alle, dtype=float), samples=args.draws)
    print(f"   alle Fills (Legacy-Spec)      {ganz} R  n={len(alle):,}")
    if gehalten:
        rest = bootstrap_mean(np.array(gehalten, dtype=float), samples=args.draws)
        print(f"   nur die echt moeglichen       {rest} R  n={len(gehalten):,}")
        print(f"   Unterschied                   {rest.value - ganz.value:+.4f} R")
    else:
        print("   nur die echt moeglichen       KEINE")

    print(
        "\nGRENZE. Gemessen ist, wie viele Trades die echte Spec nicht\n"
        "zugelassen haette, und was die uebrigen liefern. NICHT gemessen ist,\n"
        "was statt ihnen passiert waere: ein abgelehnter Trade gibt seinen Platz\n"
        "frei, und welcher dann einrueckt, entscheidet nur ein Neulauf mit\n"
        "gemeinsamem Konto. Die Richtung des Fehlers ist zudem bekannt --\n"
        "`qty` ist die abgerundete Groesse, also wird die Rohgroesse nie um mehr\n"
        "als einen Legacy-Schritt unterschaetzt und die Ablehnungszahl ist eine\n"
        "Obergrenze."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
