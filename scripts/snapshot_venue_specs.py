"""Die Instrumentregeln der konfigurierten Börse, einmal gelesen und festgehalten.

**Warum als Datei und nicht als Aufruf.** Ein Replay, der seine Specs live holt,
ist nicht reproduzierbar: die Börse ändert Schrittweiten und Mindestnominale,
und ein Lauf von morgen rechnet dann unter anderen Regeln als einer von heute,
ohne dass sich etwas im Code bewegt. Eine Datei mit Zeitstempel und Herkunft ist
ein Messobjekt; ein Netzaufruf ist eine Nebenwirkung.

**Warum es diese Datei überhaupt braucht.** `DEFAULT_SPEC` in
`domain/market.py:77` trägt EINEN Satz Regeln für alle zwölf Märkte, und am
18.10.2026 gemessen weichen die echten je Symbol ab -- `price_tick` von 0.1 bis
1e-05, `qty_step` von 0.001 bis 1, `min_notional` von 5 bis 50. Dazu Bybits
Takersatz auf Binance-Kerzen.

**Nur lesen.** Das Kline- und Market-Endpunkt braucht keine Zugangsdaten; dieses
Skript liest keine und sendet nichts.

    python scripts/snapshot_venue_specs.py
    python scripts/snapshot_venue_specs.py --out data/venue_specs
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import ccxt

from traidingbrain.config.settings import load_config
from traidingbrain.data.exchange import MarketData, UnpublishedSpecError
from traidingbrain.journal.version import code_version

#: Wo die Schnappschüsse liegen. Eine Datei je Börse, nicht je Lauf.
STANDARD_OUT = Path("data/venue_specs")

#: Die Felder, die ein Schnappschuss je Symbol trägt. Namentlich aufgeführt und
#: nicht aus dem Modell abgeleitet, damit ein später hinzugefügtes Feld hier
#: auffällt statt stillschweigend zu fehlen.
FELDER = (
    "price_tick",
    "qty_step",
    "min_qty",
    "min_notional",
    "max_leverage",
    "taker_fee",
    "maker_fee",
    "maintenance_margin_rate",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=STANDARD_OUT)
    parser.add_argument(
        "--venue",
        default=None,
        help="Vorgabe ist die konfigurierte Boerse (config/settings.yaml)",
    )
    args = parser.parse_args(argv)

    config = load_config()
    venue = args.venue or config.engine.exchange.name
    symbols = list(config.engine.symbols.active)

    quelle = MarketData(venue_name=venue, testnet=False)
    print(f"{venue}, {len(symbols)} Symbole, nur lesen\n")

    specs: dict[str, dict[str, float]] = {}
    fehler: dict[str, str] = {}
    for symbol in symbols:
        try:
            spec = quelle.fetch_symbol_spec(symbol)
        except UnpublishedSpecError as problem:
            fehler[symbol] = f"UnpublishedSpecError: {problem}"
            print(f"  {symbol:10s} UNVOLLSTAENDIG")
            continue
        except Exception as problem:
            fehler[symbol] = f"{type(problem).__name__}: {problem}"
            print(f"  {symbol:10s} FEHLER {type(problem).__name__}")
            continue
        specs[symbol] = {feld: getattr(spec, feld) for feld in FELDER}
        print(
            f"  {symbol:10s} tick={spec.price_tick:<10g} step={spec.qty_step:<8g} "
            f"minqty={spec.min_qty:<8g} minnot={spec.min_notional:<6g} "
            f"taker={spec.taker_fee:g}"
        )

    blob = {
        "venue": venue,
        "environment": "mainnet",
        # Die Herkunft, damit ein Schnappschuss nicht mit einem anderen
        # verwechselt werden kann. `fetched_utc` ist der Grund, warum diese
        # Datei existiert: sie sagt, WANN diese Regeln galten.
        "fetched_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "ccxt_version": ccxt.__version__,
        "code_version": code_version(),
        "source": "ccxt load_markets + market(symbol), oeffentlich, ohne Zugangsdaten",
        "fields": list(FELDER),
        "specs": specs,
        # Fehler stehen MIT in der Datei. Ein Schnappschuss, der die Luecken
        # weglaesst, sieht vollstaendig aus.
        "incomplete": fehler,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    ziel = args.out / f"{venue}.json"
    ziel.write_text(json.dumps(blob, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\n{len(specs)} Specs nach {ziel}")
    if fehler:
        print(f"{len(fehler)} unvollstaendig -- stehen in der Datei unter 'incomplete'")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
