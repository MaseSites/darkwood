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
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data.dataversion import content_version
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.execution.policy import policy_for
from traidingbrain.execution.venuebinding import Environment, VenueBinding
from traidingbrain.journal.build import entries_from
from traidingbrain.journal.identity import identity_for
from traidingbrain.journal.record import Source
from traidingbrain.journal.version import code_version, decision_version, run_signature
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool

#: Von welcher Boerse die Instrumentregeln dieses Laufs stammen.
#:
#: **"bybit" und nicht die konfigurierte Boerse, und das ist eine Aussage.**
#: Dieses Skript baut seine Specs aus `DEFAULT_SPEC` (`domain/market.py:77`),
#: und die Zahlen darin sind Bybits: taker 0.00055, maker 0.0002. Die Kerzen
#: kommen von Binance. Hier `config.engine.exchange.name` einzusetzen hiesse,
#: den Widerspruch in der Aufzeichnung zuzudecken -- also steht er drin, und
#: `identity.venues_agree()` antwortet mit Nein.
#:
#: Am 18.10.2026 gemessen, was das kostet: +0.0014 R je Trade [+0.001, +0.002],
#: in allen zwoelf Maerkten gleichgerichtet (`scripts/study_venue_fee.py`).
#: Diese Zeile verschwindet, sobald der Replay seine Specs von der
#: konfigurierten Boerse holt -- nicht vorher.
SPEC_VENUE = "bybit"

#: Und dieselbe Lage fuer die Analyse: `analysis/context.py` traegt
#: `venue="bybit"` hartkodiert, im Widerspruch zur Konfiguration.
ANALYSIS_VENUE = "bybit"

#: Warum dieser Lauf zwei Boersen mischen DARF.
#:
#: `VenueBinding.research()` weist ihn ab, und zu Recht -- das Tor aus Phase 2
#: hat diesen Widerspruch am 18.10.2026 gefunden, ohne ihn zu kennen. Nur ist
#: die eingefrorene Population genau so entstanden, und sie muss
#: reproduzierbar bleiben. `legacy_incoherent` nimmt diesen Grund, schreibt ihn
#: in den Fingerprint und kann nicht ausfuehren.
#:
#: Diese Konstante verschwindet gemeinsam mit `SPEC_VENUE`, sobald der Replay
#: seine Instrumentregeln von der konfigurierten Boerse holt.
INCOHERENCE_REASON = (
    "DEFAULT_SPEC traegt Bybits Instrumentregeln (taker 0.00055), die Kerzen "
    "kommen von Binance (taker 0.0005) -- so ist die eingefrorene Population "
    "von 7.335 Fills entstanden. Kosten gemessen am 18.10.2026: +0.0014 R je "
    "Trade [+0.001, +0.002], siehe scripts/study_venue_fee.py. "
    "ZWEITE Abweichung: broker.py:493 berechnet die Makergebuehr fuer jeden "
    "Limit-Einstieg, OHNE maker_role_proven zu pruefen -- der Simulator "
    "rechnet also als waere die Makerrolle bewiesen, waehrend die Policy sie "
    "mit False fuehrt. broker.py:747 tut dasselbe fuer Zielausstiege und sagt "
    "im eigenen Docstring, das sei 'quietly optimistic about every winner'. "
    "Gemessen kostet diese Annahme +0.017 R je Trade [+0.017, +0.018]"
)

#: Die Policy, deren Gebuehrenverhalten dieser Lauf wirklich zeigt.
#:
#: Aus der Gebuehrenspalte rekonstruiert, nicht gewaehlt: maker ein, maker auf
#: Zielausstieg, taker auf Stopausstieg -- das ist `maker-target`, und die
#: Saetze sind Bybits. `safety-first` waere falsch (dessen Ziel ist eine
#: Market-Order und zahlt taker).
#:
#: `maker_role_proven` bleibt dabei False, obwohl der Simulator als bewiesen
#: rechnet. Das ist Absicht: das Feld wuerde sonst einen Beweis behaupten, den
#: es nicht gibt. Die Abweichung steht stattdessen ausgeschrieben in
#: `INCOHERENCE_REASON` und damit im Fingerprint.
LEGACY_POLICY = "maker-target"

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
    funding = funding_store.read(symbol)
    analysed = time.perf_counter() - started
    engine = BacktestEngine(
        symbol,
        analysis,
        minute_frame=minutes,
        spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
        config=config,
        funding=funding,
        history=None,
    )
    pool = GuidePool.for_config(config)
    result = engine.run(pool, max_bars=max_bars)
    journal = entries_from(
        analysis,
        result.fills,
        symbol=symbol,
        strategy=pool.name,
        source=Source.REPLAY,
        signal=config.engine.timeframes.signal,
    )
    # Die Herkunft JE EINTRAG, nicht nur je Datei.
    #
    # `entries_from` laesst die drei Felder leer, weil es den Lauf nicht
    # kennt. Wer die zwoelf Journal-Listen zu einer zusammenwirft -- also das
    # Naheliegende tut -- haette dann Eintraege ohne Konfiguration und ohne
    # Commit. Genau dieser Zustand hat den alten 4-Markt-Lauf unvergleichbar
    # gemacht: seine Kadenz war nur aus der Minutenverteilung der Einstiege
    # zu erschliessen.
    stamp, commit = decision_version(), code_version()
    signature = run_signature(config, max_bars=max_bars)
    # Die VOLLSTAENDIGE Herkunft, nicht nur Konfiguration und Commit.
    #
    # Der Grund steht in `journal/identity.py`: aus den 7.335 alten Fills ist
    # nicht entscheidbar, unter welcher Boerse und welchem Gebuehrenplan sie
    # entstanden -- die Antwort stand nur in einem Kommentar. Und am
    # 18.10.2026 wurde gemessen, dass der Gebuehrenplan das Ergebnis reliabel
    # verschiebt: dieselben Fills unter Bybits und Binances Takersatz
    # unterscheiden sich um +0.0014 R [+0.001, +0.002].
    #
    # `content_version` und nicht `coverage_version`: die Rahmen liegen hier
    # ohnehin im Speicher, und die billige Form ist blind dagegen, dass eine
    # Quelle ihre eigene Vergangenheit umschreibt.
    identity = identity_for(
        config,
        VenueBinding.legacy_incoherent(
            data_venue=config.engine.exchange.name,  # type: ignore[attr-defined]
            price_venue=config.engine.exchange.name,  # type: ignore[attr-defined]
            price_environment=Environment.MAINNET,
            instrument_spec_venue=SPEC_VENUE,
            # Bybits Saetze, weil Bybits Saetze berechnet wurden. Die Policy
            # nennt hier NICHT die konfigurierte Boerse -- sonst stuende im
            # Fingerprint 0.0005, und berechnet wurden 0.00055.
            policy=policy_for(SPEC_VENUE, LEGACY_POLICY),
            reason=INCOHERENCE_REASON,
        ),
        pool,
        data_version=content_version({**frames, "m1": minutes}),
        funding_source=str(funding_store.root),
        analysis_venue=ANALYSIS_VENUE,
        max_bars=max_bars,
    )
    journal = [
        replace(entry, run_signature=signature, decision_version=stamp, code_version=commit)
        for entry in journal
    ]

    return {
        "symbol": symbol,
        "strategy": pool.name,
        "setups": [s.key for s in pool.setups],
        "decision_version": stamp,
        "code_version": commit,
        "run_signature": signature,
        # Die siebzehn Herkunftsfelder und ihr Stempel. Der Stempel ist das,
        # worauf eine spaetere Auswertung filtert; die Felder stehen daneben,
        # damit die Datei ohne den Code lesbar bleibt, der sie erzeugt hat.
        "identity_stamp": identity.stamp(),
        "identity": identity.to_dict(),
        # Und die eine Frage, die der Istzustand mit Nein beantwortet.
        "venues_agree": identity.venues_agree(),
        # Die Kadenz ausgeschrieben, nicht nur in der Signatur versteckt.
        #
        # Der alte 4-Markt-Lauf im Journal traegt keine Signatur, und seine
        # Kadenz liess sich nur aus der Minutenverteilung der Einstiege
        # erschliessen: 500 von 542 M15-Trades auf :00, nur ZWEI auf
        # 15/30/45. Er lief also auf H1-Kadenz, der heutige Lauf auf M15 --
        # ein groesserer Unterschied als die Setup-Liste, und nichts in den
        # Daten sagte es. Eine Eigenschaft, die man nur aus der Verteilung
        # erschliesst, ist keine aufgezeichnete Eigenschaft.
        "signal_timeframe": config.engine.timeframes.signal.value,
        "execution_timeframe": config.engine.timeframes.execution.value,
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
        "funding_settlements": len(funding) if funding is not None else 0,
        # Die rohe Population. Vollstaendig, immer.
        "fills": [fill_record(f) for f in result.fills],
        # Und dieselben Trades mit ihrer Begruendung: Rating, Regime,
        # Faktorfamilien, Post-Mortem mit `bars_held` und `stopped_by_wick`.
        #
        # Das ist die Anreicherung, die das Journal fuer den alten Lauf hatte
        # und die den fruehen Fassungen dieses Skripts fehlte. E10 brauchte
        # `stopped_by_wick`, E11 brauchte das Regime -- Felder, die in einer
        # Datei mit nur den Fills nicht stehen. Ein Lauf, der sechs Stunden
        # kostet, soll jede Frage beantworten koennen, die der alte beantworten
        # konnte, und nicht nur die, die beim Schreiben gerade anstand.
        "journal": [json.loads(entry.to_json()) for entry in journal],
        # Beide Zahlen, weil `entries_from` einen Fill ueberspringt, dessen
        # Entscheidungsbalken oder Score sich nicht rekonstruieren laesst. Die
        # Luecke stillschweigend zu tragen waere genau die Sorte Verlust, die
        # dieses Skript dreimal umgebaut hat.
        "fills_count": len(result.fills),
        "journal_count": len(journal),
        "enrichment_gap": len(result.fills) - len(journal),
    }


def banner(config: object, *, stamp: str, markets: int, out: Path) -> None:
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
    print(f"  {markets} Maerkte nach {out}\n", flush=True)


def one_code_version(symbols: list[str], out: Path = OUT) -> int:
    """Pruefen, ob alle Ergebnisse aus demselben Codestand kommen."""
    stamps = set()
    total = 0
    for symbol in symbols:
        target = out / f"{symbol}.json"
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
    parser.add_argument("--out", type=Path, default=OUT,
                        help="Zielordner. Vorgabe ist die eingefrorene Population -- "
                             "fuer einen Probelauf einen anderen angeben, damit die "
                             "7.335 Legacy-Fills unberuehrt bleiben")
    args = parser.parse_args()

    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    stamp = decision_version()

    banner(config, stamp=stamp, markets=len(symbols), out=out)

    done = 0
    for index, symbol in enumerate(symbols, 1):
        target = out / f"{symbol}.json"
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
        gap = result["enrichment_gap"]
        note = f", {gap} ohne Begruendung" if gap else ""
        print(f"{result['fills_count']:,} Trades{note} in {result['seconds']:.0f}s", flush=True)
        done += 1

    print(f"\n  {done}/{len(symbols)} Maerkte fertig.", flush=True)
    return one_code_version(symbols)


if __name__ == "__main__":
    raise SystemExit(main())
