"""Ein Band echter Kerzen einfrieren, damit der Live-Pfad einen Golden-Test bekommt.

    python scripts/freeze_decision_tape.py

**Warum.** Am 09.10.2026 musste die Vorwärtsstichprobe dreimal nachgeschnitten
werden, und zweimal war die Begründung falsch — weil keine Prüfung meldet, wenn
sich der Live-Entscheidungspfad verhält. Der Replay-Pfad hat einen Golden-Test
(`tests/golden/backtest_baseline.json`), der Papierhandel hatte keinen, und er
ist der Pfad, der die einzige noch wachsende Evidenz erzeugt.

**Warum echte Kerzen und nicht die synthetische Fixture.** Die bestehenden
Papierhandels-Tests nehmen `FixedIntent` statt der echten Strategie, mit
Begründung im Modul: *„a real setup fires on a handful of bars in a fixture and
on none in some."* Gemessen auf echten BTCUSDT-Kerzen feuert `GuidePool`
**18 Mal auf 300 Balken** — ein Signal je 16,7 Balken, über drei Setups. Auf
der synthetischen Sinus-Reihe wäre die Folge möglicherweise leer, und ein Hash
über eine leere Folge ist stabil, egal was sich ändert.

**Warum diese zwei Märkte.** Gemessen über je 1 100 Balken, Fenster gleich:

    Markt       vorgeschlagen  ANGENOMMEN  abgelehnt (Regel)
    BTCUSDT               58            1   kosten 41, chance_risiko 16
    DOTUSDT               60           16   chance_risiko 24, kosten 20
    LINKUSDT              54           12   chance_risiko 17, kosten 25
    ADAUSDT               52           12   kosten 21, chance_risiko 19
    ATOMUSDT              56            9   chance_risiko 21, kosten 26
    SOLUSDT               62            8   chance_risiko 19, kosten 35

BTC ist der Ausreisser: die Risk Engine nimmt dort 1 von 58 Vorschlägen an, weil
die Stops relativ zur Maut eng sind. Für einen Test, der eine Änderung an
Sizing oder Hebel fangen soll, ist das zu wenig. **DOT** deckt den angenommenen
Pfad (16) und die Chance-Risiko-Regel (24), **BTC** die Kostenregel (41).
Zusammen sind beide Ablehnungsregeln und der angenommene Pfad zweistellig
gedeckt.

*Nicht gemessen und darum nicht behauptet:* dass diese zwei Märkte die
Setup-Vielfalt erschöpfen. Sie decken A, B, F und G; Setup E kam in diesem
Fenster nicht vor.

**Was NICHT variiert, und das ist gemessen.** Das Eigenkapital. Bei 1 000,
5 000, 12 000 und 50 000 USDT sind Vorschläge, Annahmen und Ablehnungen
**identisch** — die Kostenregel vergleicht Maut mit riskiertem Betrag, und beide
skalieren mit dem Konto. Der Test läuft deshalb auf *einem* Niveau; zwei wären
derselbe Hash zweimal.

Nur lesen aus `data/`, geschrieben wird allein nach `tests/golden/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore

#: Wohin die Fixture geht. Unter `tests/`, weil sie Testeingabe ist und nicht
#: Projektdaten -- `data/` ist gitignoriert und wächst, während der
#: Papierhandel läuft. Ein Golden-Test auf mitlaufenden Daten bricht bei jedem
#: Backfill und sagt nichts über den Code.
TAPE = ROOT / "tests" / "golden" / "decision_tape"

#: Die zwei Märkte aus dem Kopf dieser Datei, mit Begründung dort.
SYMBOLS = ("BTCUSDT", "DOTUSDT")

#: Balken je Zeitebene. Der Papierhandel liest `tail(HISTORY_BARS)` mit
#: HISTORY_BARS = 5000; 800 ist der gemessene Kompromiss. Die Aufwärmung ist
#: erfüllt (`not_ready` = 0), und die Entscheidungszahlen sind **identisch** mit
#: denen bei 1 200 Balken (22 Vorschläge, 10 angenommen, 12 abgelehnt auf DOT
#: über 300 Balken), während der Aufbau der Analyse von 2,69 s auf 1,68 s fällt.
#: Bei 400 Balken ändern sich die Zahlen (20/7/13) — die Analyse hat dann zu
#: wenig Geschichte, also ist 400 nicht äquivalent und 800 die Untergrenze.
BARS = 800

#: Wo das Band endet, in Epoch-ms. Der Zweck ist nicht Sparsamkeit, sondern
#: Treffsicherheit: der Papierhändler erwägt ein Signal nur, wenn das Konto
#: flach ist (der „Belegungsschatten"), also liefert ein beliebiges Fenster
#: wenige Entscheidungen. Dieses Ende liegt kurz **nach** den beiden echten
#: Live-Entscheidungen vom 09.10.2026 — BTCUSDT short @ 81 316,0 Stop 82 750,0
#: und DOTUSDT short @ 1,0781 Stop 1,0945, beide so im Journal — damit ein
#: kurzes Fenster sie enthält. Der Test reproduziert damit nicht irgendwelche
#: Entscheidungen, sondern zwei, die wirklich gefallen sind.
#:
#: `None` heisst: bis zum letzten vorhandenen Balken. Das ist bequem und für
#: einen Test schlecht, weil der letzte Balken sich ändert, solange der
#: Papierhandel läuft.
UNTIL = 1791500400000


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=BARS)
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--until", type=int, default=UNTIL,
                        help="letzter Balken in Epoch-ms; 0 heisst bis zum Ende")
    args = parser.parse_args()

    config = load_config(ROOT / "config")
    source = ParquetStore(ROOT / "data" / "ohlcv")
    frozen = ParquetStore(TAPE)
    symbols = tuple(args.symbols.split(","))

    print("=" * 78)
    print("Band einfrieren fuer den Live-Golden-Test")
    print("=" * 78)
    print(f"\n  Quelle : {source.root if hasattr(source, 'root') else ROOT / 'data' / 'ohlcv'}")
    print(f"  Ziel   : {TAPE.relative_to(ROOT)}")
    print(f"  Balken : {args.bars} je Ebene\n")

    manifest: dict[str, object] = {
        "befehl": f"python scripts/freeze_decision_tape.py --bars {args.bars} "
                  f"--symbols {','.join(symbols)} --until {args.until}",
        "balken_je_ebene": args.bars,
        "letzter_balken": args.until or None,
        "symbole": list(symbols),
        "ebenen": [tf.value for tf in config.engine.timeframes.context],
        "rahmen": {},
        "dateien": {},
    }
    frames_meta: dict[str, dict[str, object]] = {}

    for symbol in symbols:
        frames_meta[symbol] = {}
        for timeframe in config.engine.timeframes.context:
            frame = source.read(symbol, timeframe)
            if args.until:
                frame = frame[frame["ts"] <= args.until]
            frame = frame.tail(args.bars).reset_index(drop=True)
            if frame.empty:
                raise SystemExit(f"{symbol} {timeframe.value}: keine Kerzen im Speicher")
            frozen.write(symbol, timeframe, frame)
            frames_meta[symbol][timeframe.value] = {
                "balken": len(frame),
                "erster_ts": int(frame["ts"].iloc[0]),
                "letzter_ts": int(frame["ts"].iloc[-1]),
            }
            print(f"  {symbol:9s} {timeframe.value:4s} {len(frame):>6,} Balken  "
                  f"{int(frame['ts'].iloc[0])} .. {int(frame['ts'].iloc[-1])}")

    manifest["rahmen"] = frames_meta

    # Je Datei ein Hash, und ein Hash ueber alle. Der Zweck ist eine
    # Unterscheidung, die heute gefehlt hat: aendert sich der BANDHASH, hat
    # jemand die Eingabe erneuert; aendert sich nur der ENTSCHEIDUNGSHASH, hat
    # sich das Verhalten geaendert. Ohne das erste ist das zweite nicht lesbar.
    files = sorted(p for p in TAPE.rglob("*.parquet"))
    per_file = {str(p.relative_to(TAPE)).replace("\\", "/"): digest(p) for p in files}
    manifest["dateien"] = per_file
    joined = "".join(f"{name}:{sha}" for name, sha in sorted(per_file.items()))
    manifest["bandhash"] = hashlib.sha256(joined.encode()).hexdigest()

    total = sum(p.stat().st_size for p in files)
    (TAPE / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\n  {len(files)} Dateien, {total / 1024:.1f} KiB")
    print(f"  Bandhash: {manifest['bandhash']}")
    print(f"\n  Manifest: {(TAPE / 'MANIFEST.json').relative_to(ROOT)}")
    print("\n  Jetzt `pytest tests/test_live_decision_golden.py` -- der Test schreibt\n"
          "  seinen Entscheidungshash beim ersten Lauf und vergleicht danach.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
