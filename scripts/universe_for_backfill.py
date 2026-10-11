"""Welche Märkte dazukommen — nach einer Regel, nicht nach Augenmass.

    python scripts/universe_for_backfill.py
    python scripts/universe_for_backfill.py --before 2021-10-01 --write

**Warum das ein eigenes Skript ist.** Die Evidenzbasis dieses Projekts sind
zwölf Märkte über vier Jahre, und darauf sind 124 Registereinträge gelaufen.
Gemessen am Versuchsbudget (Bailey/Borwein/López de Prado/Zhu) tragen fünf
Jahre Daten etwa 45 unabhängige Versuche. **Die Suche hat die Datenlänge
überholt.** Was dagegen hilft, ist nicht ein weiterer Arm, sondern mehr
Daten — und zwar Daten, die nicht danach ausgewählt wurden, wie sie aussehen.

**Die Regel steht vor der Liste.** Aufgenommen wird jeder USDT-Perpetual,
dessen Börsenstart (`onboardDate`) **vor** dem Fensterbeginn liegt. Das ist
ein Kriterium zum Zeitpunkt *damals* und nicht heute: es fragt nicht, wie ein
Markt gelaufen ist, nur ob er zu Fensterbeginn existierte. Die Alternative
— „die zwanzig mit dem meisten Volumen" oder „die mit der saubersten
Historie" — würde nach dem Ergebnis auswählen.

**Und die Lücke, die das Skript nicht schliessen kann.** Die Börse listet nur
Märkte, die es **heute** gibt. Jeder Perpetual, der im Fenster delistet wurde,
fehlt in dieser Abfrage und ist damit unsichtbar. Das ist
Überlebensauswahl, und sie ist gemessen: 3,4 % der Perps dieses Zeitraums
existieren nicht mehr. Das Skript schreibt diese Zahl mit, damit die
Erweiterung nicht als „vollständiges Universum" gelesen wird. Sie ist eine
grössere Stichprobe mit demselben Bias, nicht ein unverzerrtes Universum.

**Was die neuen Märkte sind und was nicht.** Sie sind die
**Replikationsseite** für Befunde, die auf den alten zwölf gefunden wurden.
Sie sind *nicht* eine Einladung, die 124 Arme erneut durchzuprobieren und die
zu behalten, die diesmal passen — das wäre dieselbe Suche mit mehr Zellen.
Replizieren darf nur, was auf den alten Märkten schon das erste Tor genommen
hat.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ccxt

from traidingbrain.config.settings import load_config

OHLCV = ROOT / "data" / "ohlcv"
OUT = ROOT / "data" / "universe_for_backfill.json"

#: Fensterbeginn der Minutendaten. Wer danach startete, hat im Fenster Luecken.
DEFAULT_BEFORE = "2021-10-01"

#: Gemessene Ueberlebensquote der Perps dieses Zeitraums, aus E4. Die Abfrage
#: sieht nur Ueberlebende, also fehlen rund so viele.
DELISTED_SHARE = 0.034


def listed_perps() -> list[dict[str, object]]:
    """Alle USDT-Perpetuals der konfigurierten Boerse mit ihrem Startdatum."""
    config = load_config()
    name = config.engine.exchange.name
    client = getattr(ccxt, name)({"options": {"defaultType": "future"}})
    markets = client.load_markets()
    out = []
    for symbol, market in markets.items():
        if not market.get("swap") or market.get("quote") != "USDT":
            continue
        if not market.get("active") or market.get("linear") is not True:
            continue
        info = market.get("info") or {}
        onboard = info.get("onboardDate")
        out.append({
            "id": market["id"],
            "symbol": symbol,
            "onboard_ms": int(onboard) if onboard else None,
            "onboard": (datetime.fromtimestamp(int(onboard) / 1000, UTC).date().isoformat()
                        if onboard else None),
        })
    return sorted(out, key=lambda m: (m["onboard_ms"] or 0, m["id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default=DEFAULT_BEFORE,
                        help="nur Maerkte, die vor diesem Datum starteten")
    parser.add_argument("--write", action="store_true",
                        help="die Liste nach data/universe_for_backfill.json schreiben")
    args = parser.parse_args()

    cutoff = datetime.fromisoformat(args.before).replace(tzinfo=UTC)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    print("=" * 74)
    print("Marktauswahl fuer die Datenerweiterung")
    print("=" * 74)
    print(f"\n  Regel: USDT-Perpetual, Boersenstart VOR {args.before}")
    print("  Kriterium zum Zeitpunkt damals, nicht heute.\n")

    try:
        perps = listed_perps()
    except Exception as exc:  # ein Netzfehler ist eine Antwort, kein Absturz
        print(f"  ABBRUCH: Boerse nicht erreichbar -- {type(exc).__name__}: {exc}\n")
        return 2

    eligible = [m for m in perps if m["onboard_ms"] and m["onboard_ms"] < cutoff_ms]
    have = {p.name for p in OHLCV.iterdir() if p.is_dir()} if OHLCV.exists() else set()
    new = [m for m in eligible if m["id"] not in have]
    missing_locally = sorted(have - {m["id"] for m in eligible})

    print(f"  {len(perps):>4} aktive USDT-Perps gelistet")
    print(f"  {len(eligible):>4} davon mit Start vor {args.before}")
    print(f"  {len(have):>4} liegen lokal vor")
    print(f"  {len(new):>4} kommen dazu\n")

    if missing_locally:
        print(f"  Lokal vorhanden, aber NICHT in der Regel: {', '.join(missing_locally)}")
        print("  (spaeter gestartet -- im Fenster also mit Luecken)\n")

    for index, market in enumerate(new, 1):
        print(f"    {index:>3}. {market['id']:14s} seit {market['onboard']}")

    print("\n  Ueberlebensauswahl: die Abfrage sieht nur Maerkte, die es HEUTE")
    print(f"  gibt. Rund {DELISTED_SHARE:.1%} der Perps dieses Zeitraums sind")
    print("  delistet und in dieser Liste unsichtbar. Das ist eine groessere")
    print("  Stichprobe mit demselben Bias, kein unverzerrtes Universum.\n")

    if args.write:
        OUT.write_text(json.dumps({
            "measured_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "rule": f"USDT perp, onboardDate < {args.before}",
            "delisted_share_estimate": DELISTED_SHARE,
            "listed_active": len(perps),
            "eligible": [m["id"] for m in eligible],
            "already_local": sorted(have),
            "to_backfill": [m["id"] for m in new],
            "local_but_outside_rule": missing_locally,
            "onboard_dates": {m["id"]: m["onboard"] for m in eligible},
        }, indent=1), encoding="utf-8")
        print(f"  -> {OUT.relative_to(ROOT)}\n")
    else:
        print("  (mit --write wird die Liste gespeichert)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
