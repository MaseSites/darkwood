"""Den Replay über alle zwölf Märkte fahren und **jeden Trade behalten**.

    python scripts/replay_all_markets.py
    python scripts/replay_all_markets.py --symbols BTCUSDT,ETHUSDT --force

**Warum dieses Skript zweimal umgebaut wurde.**

*Erster Umbau (11.10., vormittags).* Der Replay lief als
`for SYM in ...; do python run_backtest.py; done` im Hintergrund. Dann musste
er gestoppt werden, weil mitten im Lauf der Broker korrigiert wurde und zwölf
Märkte unter zwei Codeständen keine Messung sind. Das Stoppen hat drei
Anläufe gebraucht: der Abbruch der Hintergrundaufgabe beendete die *Schleife*
nicht; ein `Stop-Process` traf nur die *Kinder*, worauf zwei Läufe parallel in
dieselben Logdateien schrieben; und die Prozessabfrage, mit der ich das
prüfte, **zählte sich selbst** und meldete beharrlich drei Schleifen, wo keine
war. Ein Prozess, der die Schleife selbst enthält, hat keinen dieser Zustände.

*Zweiter Umbau (11.10., abends) — der teurere Fehler.* Der Lauf ging über
sechs Stunden durch und lieferte **nichts Nachrechenbares**. Er rief
`run_backtest.py` als Unterprozess auf, und das Skript *druckt* seine
Ergebnisse: Trade-Zahl, Expectancy, Exitgründe. Es persistiert keinen
einzigen Trade. Gespeichert wurde also die Zusammenfassung, nicht die
Stichprobe. Das vorab festgelegte Abnahmekriterium fragt nach der Trade-Zahl
**je Setup** — eine Zahl, die in keiner dieser Zeilen steht. Sechs Stunden
Rechenzeit, und die Frage, für die gerechnet wurde, blieb unbeantwortbar.

Genau diese Lehre stand schon in `scripts/probe_kline_latency.py`: *eine
Zusammenfassung ohne ihre Stichprobe lässt sich nicht nachprüfen.* Sie stand
dort, weil dieselbe Sache bei der Latenzmessung passiert war. Eine Lehre, die
in einem Skript notiert ist und im nächsten wieder gebrochen wird, ist nicht
gelernt.

**Was jetzt anders ist.** Dieses Skript fährt `BacktestEngine` im eigenen
Prozess — so, wie es die `study_*.py` von Anfang an gemacht haben — und
schreibt **jeden einzelnen Fill** als Datensatz heraus: Setup, Seite,
Zeitstempel, R, Brutto, Gebühren, Funding, risikierter Betrag, Exitgrund.
Damit ist jede Folgefrage über denselben Lauf beantwortbar, ohne ihn neu zu
rechnen: Setup-Verteilung, Wochentag, Tageszeit, Kostenanteil, Haltedauer.

*Dritter Umbau, wenige Minuten spaeter.* Der Rauchtest meldete „6 Setups:
A, B, C, E, F, G" — und die Konfiguration hat C am 04.10. abgeschaltet. Der
Runner baute seinen Pool aus `TRADEABLE`, der Liste *aller* Setups, statt aus
`GuidePool.for_config`. Damit haette er gemessen, was passiert waere, wenn
niemand C abgeschaltet haette: ein System, das niemand faehrt. Die Klasse
beschreibt genau diese Falle in ihrem eigenen Docstring — „a default of 'all
of them' means a forgotten call site keeps trading a setup the configuration
switched off, and the switch looks like it works for as long as nobody
checks". Dieses Skript war die vergessene Aufrufstelle. Gefunden hat es nur
der Rauchtest, der vor dem Sechsstundenlauf lief.

**Jeder Messlauf baut seinen Pool aus der Konfiguration.** Die
`study_*.py` duerfen Setups explizit setzen — sie vergleichen Arme, das ist
ihr Zweck. Ein Lauf, der „das laufende System" messen soll, darf es nicht.

**Wiederaufnehmbar.** Ein Markt, dessen Ergebnisdatei dasteht, wird
übersprungen — bei über fünfzehn Minuten je Markt der Unterschied zwischen
einer Stunde und einem Tag.

**Der Codestand wird mitgeschrieben.** `decision_version` steht in jeder
Ergebnisdatei, und am Ende prüft das Skript, ob alle aus demselben Stand
kommen. Sonst sagt es, dass das keine Messung ist. Genau daran war der erste
Lauf gescheitert.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.version import code_version, decision_version
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool

MARKETS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOGEUSDT", "BNBUSDT", "LTCUSDT", "DOTUSDT", "ATOMUSDT",
)

OUT = ROOT / "data" / "replay_fills"


def fill_record(fill: object) -> dict[str, object]:
    """Ein Fill als flacher Datensatz, inklusive der abgeleiteten Groessen.

    `r_multiple` und `net_pnl` sind Properties und fallen bei `asdict` weg;
    sie werden hier ausgeschrieben, damit die Datei ohne den Code lesbar
    bleibt. Eine Ergebnisdatei, die zum Auswerten den Codestand braucht, der
    sie erzeugt hat, ist nur halb persistiert.
    """
    record = {k: v for k, v in asdict(fill).items()}
    for key in ("side", "state", "reason"):
        value = record.get(key)
        if value is not None and not isinstance(value, (str, int, float)):
            record[key] = getattr(value, "value", str(value))
    record["net_pnl"] = fill.net_pnl
    record["r_multiple"] = fill.r_multiple
    return record


def run_one(symbol: str, *, config: object, store: ParquetStore,
            funding_store: FundingStore, max_bars: int | None = None) -> dict[str, object] | None:
    started = time.perf_counter()
    frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
    minutes = store.read(symbol, config.engine.timeframes.execution)
    if any(f.empty for f in frames.values()) or minutes.empty:
        return None

    analysis = MultiFrameAnalysis(frames, config.engine)
    analysed = time.perf_counter() - started
    engine = BacktestEngine(
        symbol,
        analysis,
        minute_frame=minutes,
        spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
        config=config,
        funding=funding_store.read(symbol),
        history=None,
    )
    pool = GuidePool.for_config(config)
    result = engine.run(pool, max_bars=max_bars)

    return {
        "symbol": symbol,
        "strategy": pool.name,
        "setups": [s.key for s in pool.setups],
        "decision_version": decision_version(),
        "code_version": code_version(),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "analysis_seconds": round(analysed, 1),
        "seconds": round(time.perf_counter() - started, 1),
        "snapshots_built": result.snapshots_built,
        "intents": result.intents,
        "intents_rejected_by_risk": result.intents_rejected_by_risk,
        "first_ts": result.first_ts,
        "last_ts": result.last_ts,
        "window_note": result.window_note,
        "max_bars": max_bars,
        "summary": result.summary(),
        "fills": [fill_record(f) for f in result.fills],
    }


def banner(config: object, *, stamp: str, markets: int) -> None:
    """Was dieser Lauf ist, bevor er sechs Stunden rechnet.

    Die Setup-Liste steht hier und nicht nur in der Ergebnisdatei, weil der
    Lauf, der diese Zeile nicht gedruckt hat, sechs Stunden lang das falsche
    System gemessen hat.
    """
    pool = GuidePool.for_config(config)
    print("=" * 74, flush=True)
    print("Replay-Neulauf, Strategie guide-all, mit Trade-Persistenz", flush=True)
    print("=" * 74, flush=True)
    print(f"\n  Entscheidungsstempel {stamp}  |  Commit {code_version()}", flush=True)
    print(f"  {len(pool.setups)} Setups wie konfiguriert: "
          f"{', '.join(s.key for s in pool.setups)}", flush=True)
    print(f"  {markets} Maerkte nach {OUT.relative_to(ROOT)}\n", flush=True)


def one_code_version(symbols: list[str]) -> int:
    """Pruefen, ob alle Ergebnisse aus demselben Codestand kommen."""
    stamps = set()
    total = 0
    for symbol in symbols:
        target = OUT / f"{symbol}.json"
        if target.exists():
            payload = json.loads(target.read_text(encoding="utf-8"))
            stamps.add(payload.get("decision_version"))
            total += len(payload.get("fills", []))
    if len(stamps) > 1:
        print(f"  WARNUNG: {len(stamps)} verschiedene Codestaende in den Ergebnissen.")
        print("  Das ist keine Messung. Mit --force neu rechnen.\n")
        return 1
    print(f"  {total:,} Trades, alle aus {stamps.pop() if stamps else '-'}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(MARKETS))
    parser.add_argument("--max-bars", type=int, default=None,
                        help="Lauf kuerzen -- nur zum Testen, kein Messlauf")
    parser.add_argument("--force", action="store_true",
                        help="auch Maerkte neu rechnen, die schon ein Ergebnis haben")
    args = parser.parse_args()

    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)

    OUT.mkdir(parents=True, exist_ok=True)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    stamp = decision_version()

    banner(config, stamp=stamp, markets=len(symbols))

    done = 0
    for index, symbol in enumerate(symbols, 1):
        target = OUT / f"{symbol}.json"
        if target.exists() and not args.force:
            previous = json.loads(target.read_text(encoding="utf-8"))
            same = previous.get("decision_version") == stamp
            note = "" if same else "  <-- ANDERER CODESTAND, mit --force neu rechnen"
            print(f"  [{index:>2}/{len(symbols)}] {symbol:9s} liegt vor "
                  f"({len(previous.get('fills', [])):,} Trades){note}", flush=True)
            done += 1
            continue

        print(f"  [{index:>2}/{len(symbols)}] {symbol:9s} laeuft ... ", end="", flush=True)
        try:
            result = run_one(symbol, config=config, store=store,
                             funding_store=funding_store, max_bars=args.max_bars)
        except Exception as exc:
            print(f"FEHLER {type(exc).__name__}: {exc}", flush=True)
            continue
        if result is None:
            print("keine Daten", flush=True)
            continue
        target.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"{len(result['fills']):,} Trades in {result['seconds']:.0f}s", flush=True)
        done += 1

    print(f"\n  {done}/{len(symbols)} Maerkte fertig.", flush=True)
    return one_code_version(symbols)


if __name__ == "__main__":
    raise SystemExit(main())
