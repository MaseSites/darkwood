"""Binance-Spot-Kerzen holen — die Reihe, die E6.1 blockiert hat.

    python scripts/backfill_spot.py
    python scripts/backfill_spot.py --symbols BNBUSDT --since 2023-01-01

**Wofür das da ist.** Funding-Carry ist der einzige im Projekt gemessene
Ertrag, der keine Richtungsvorhersage braucht: Perp short gegen Spot long,
Preis herausgehedgt, man kassiert die Funding-Rate. Gemessen über zwölf
Märkte und 3,8 bis 6,7 Jahre liegt er bei +5,5 % bis +14,8 % p.a. aufs
Notional, in 11 von 12 Märkten mit einem Intervall über Null.

Und er war trotzdem nicht einsetzbar, aus einem benannten Grund. Das
Versuchsregister führt E6 als `teilweise_blockiert` mit dem Defekt *„Keine
Spot-Reihe auf der Platte, also Basisrisiko ungemessen."* Das ist nicht
eine Lücke unter mehreren — **die Basis ist das ganze Risiko dieses
Trades.** Das Funding fliesst auf dem Perp-Bein; was schiefgehen kann, ist
dass die beiden Beine auseinanderlaufen. Wer den Carry ohne die Basis
rechnet, hat die Einnahme gemessen und die Gefahr weggelassen.

**Warum nur acht Märkte.** Für E6.1 („same venue") müssen Spot, Perp und
Funding von *einer* Börse kommen, auf *einer* Uhr. Gemessen am 07.10.2026
mit `scripts/verify_funding_provenance.py`:

* **Binance-Funding (8):** ADA, ATOM, AVAX, BNB, DOGE, DOT, LINK, LTC
* Bybit-Funding (4): BTC, ETH, SOL, XRP

Die Perp-Kerzen sind laut `config/settings.yaml` durchweg Binance. Also
ergibt Binance-Spot für die acht einen sauberen Same-Venue-Arm — und für
die vier anderen ausdrücklich **nicht**. Für die wäre es Bybit-Funding
gegen Binance-Preise gegen Binance-Spot: drei Dinge, von denen zwei nicht
zusammengehören. Die vier bleiben darum aussen vor, statt die Zahl zu
vergrössern.

**Was hier nicht passiert.** Keine Order, kein Schlüssel, kein Handelsweg.
`binance_spot` steht in `DATA_ONLY` und nicht in `SUPPORTED`, also lehnt
`ExchangeConfig` eine `settings.yaml` ab, die es als Handelsvenue nennt --
geprüft in `tests/test_venue.py`.

Die Daten landen unter `data/spot/` und nicht neben den Perp-Kerzen. Zwei
Reihen desselben Symbols, die sich im Preis um Basispunkte unterscheiden,
gehören nicht in dasselbe Verzeichnis: eine Verwechslung wäre hier kein
Fehler, der auffällt, sondern einer, der eine Basis von null misst.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.clock import SystemClock
from traidingbrain.config.settings import load_config
from traidingbrain.data.backfill import Backfiller
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe

#: Die acht Märkte, deren Funding von Binance kommt. Gemessen, nicht
#: angenommen: `scripts/verify_funding_provenance.py` vergleicht die
#: gespeicherten Raten an identischen Zeitstempeln gegen beide Börsen.
BINANCE_FUNDING = (
    "ADAUSDT",
    "ATOMUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "LTCUSDT",
)

#: Die vier, für die derselbe Arm NICHT gebaut werden darf, mit dem Grund.
BYBIT_FUNDING = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")

#: Wohin. Getrennt von `data/ohlcv/`, siehe Modul-Docstring.
SPOT_DIR = ROOT / "data" / "spot"

#: H1 reicht und ist die richtige Wahl. Funding fällt achtstündlich an, und
#: die Basis wird auf demselben Raster wie die Perp-Kerzen gebraucht --
#: feiner würde nur Daten erzeugen, die keine Frage beantworten.
DEFAULT_TF = Timeframe.H1

#: Das gemeinsame Fenster der Funding-Prüfung. Früher zu beginnen wäre
#: möglich, brächte aber Tage, für die die Gegenseite fehlt.
DEFAULT_SINCE = "2023-01-01"


def parse_date(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--symbols",
        default="",
        help=f"Komma-getrennt. Vorgabe: die acht mit Binance-Funding ({len(BINANCE_FUNDING)}).",
    )
    parser.add_argument("--since", type=parse_date, default=parse_date(DEFAULT_SINCE))
    parser.add_argument("--until", type=parse_date, default=None)
    parser.add_argument(
        "--allow-cross-venue",
        action="store_true",
        help=(
            "Auch die vier Maerkte mit Bybit-Funding holen. Deren Spot-Reihe "
            "ergibt KEINEN Same-Venue-Arm und ist als Vergleichsmaterial zu "
            "behandeln, nicht als E6.1."
        ),
    )
    args = parser.parse_args(argv)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.allow_cross_venue:
        symbols = [*BINANCE_FUNDING, *BYBIT_FUNDING]
    else:
        symbols = list(BINANCE_FUNDING)

    crossed = [s for s in symbols if s in BYBIT_FUNDING]
    if crossed and not args.allow_cross_venue:
        parser.error(
            f"{', '.join(crossed)} hat BYBIT-Funding. Binance-Spot dagegen zu stellen\n"
            f"ist kein Same-Venue-Arm und beantwortet E6.1 nicht. Mit\n"
            f"--allow-cross-venue trotzdem holen, dann aber als Vergleichsmaterial."
        )

    print("=" * 88)
    print("Binance-SPOT-Kerzen -- die Reihe, die E6.1 (Basisrisiko) blockiert hat")
    print("=" * 88)
    print(
        f"\n  Venue     binance_spot (nur lesen; nicht in SUPPORTED, also keine Handelsvenue)\n"
        f"  Ziel      {SPOT_DIR}\n"
        f"  Raster    {DEFAULT_TF.value}\n"
        f"  Ab        {datetime.fromtimestamp(args.since / 1000, tz=UTC):%Y-%m-%d}\n"
        f"  Maerkte   {len(symbols)}: {', '.join(symbols)}\n"
    )
    if crossed:
        print(
            f"  ! {', '.join(crossed)} haben Bybit-Funding. Diese Reihen sind\n"
            f"    Vergleichsmaterial und KEIN Same-Venue-Arm.\n"
        )

    store = ParquetStore(SPOT_DIR)
    source = MarketData(
        venue_name="binance_spot",
        testnet=False,
        rate_limit_ms=config.engine.exchange.rate_limit_ms,
    )
    backfiller = Backfiller(source, store, clock=SystemClock())

    def progress(symbol: str, timeframe: Timeframe, bars: int, newest_ts: int) -> None:
        when = datetime.fromtimestamp(newest_ts / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
        print(
            f"\r  {symbol} {timeframe.value:<4} {bars:>8,} Kerzen  ->  {when}",
            end="",
            flush=True,
        )

    failed: list[str] = []
    for symbol in symbols:
        print(f"\n{symbol}")
        try:
            for result in backfiller.run_many(
                symbol, [DEFAULT_TF], args.since, args.until, progress=progress
            ):
                print(f"\r  {result.summary()}")
        except Exception as error:
            # Ein fehlender Spot-Markt ist eine Tatsache ueber die Boerse und
            # kein Grund, die anderen sieben zu verlieren. Er wird am Ende
            # benannt, damit er nicht in der Ausgabe verschwindet.
            print(f"\r  FEHLER: {error}")
            failed.append(f"{symbol}: {error}")

    print("\n" + "=" * 88)
    if failed:
        print("  Nicht geholt:")
        for line in failed:
            print(f"    {line}")
        print()
    done = [s for s in symbols if s not in {f.split(':')[0] for f in failed}]
    print(
        f"  {len(done)} von {len(symbols)} Maerkten liegen als Spot-Reihe vor.\n"
        f"  Naechster Schritt: die Basis messen -- scripts/study_basis.py.\n"
        f"  Diese Reihen beantworten E6.1 NICHT allein; sie heben den Defekt\n"
        f"  'keine Spot-Reihe auf der Platte' auf, mehr nicht."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
