"""Den Replay über alle zwölf Märkte fahren, als EIN Prozess.

    python scripts/replay_all_markets.py
    python scripts/replay_all_markets.py --symbols BTCUSDT,ETHUSDT

**Warum das ein Skript ist und keine Shell-Schleife.** Am 11.10.2026 lief der
Replay zuerst als `for SYM in ...; do python run_backtest.py; done` im
Hintergrund. Dann musste er gestoppt werden, weil mitten im Lauf der Broker
korrigiert wurde und zwölf Märkte unter zwei Codeständen keine Messung sind.
Das Stoppen hat drei Anläufe gebraucht und dabei fast alles falsch gemacht,
was man falsch machen kann:

* Der Abbruch der Hintergrundaufgabe beendete die **Schleife** nicht. Sie lief
  weiter und startete den nächsten Markt.
* Ein `Stop-Process` auf die Python-Prozesse traf nur die **Kinder**. Die
  Schleife bemerkte den Tod und ging zum nächsten Symbol über — also liefen
  danach *zwei* Läufe parallel in dieselben Logdateien.
* Und die Prozessabfrage, mit der ich das prüfte, **zählte sich selbst**: ihre
  eigene Kommandozeile enthält das Suchmuster, also meldete sie beharrlich
  „drei Schleifen", wo keine war. Dieselbe Sorte Fehler wie an sechs anderen
  Stellen dieser Sitzung — das Messgerät beschreibt sich statt die Welt.

Ein Prozess, der die Schleife selbst enthält, hat keinen dieser Zustände. Er
wird gestoppt, indem man ihn stoppt.

**Wiederaufnehmbar.** Ein Markt, dessen Ergebnisdatei schon dasteht, wird
übersprungen. Eine Unterbrechung kostet damit höchstens den laufenden Markt
und nicht den ganzen Lauf — bei über fünfzehn Minuten je Markt ist das der
Unterschied zwischen einer Stunde und einem Tag.

**Der Codestand wird mitgeschrieben.** `decision_version` und `code_version`
stehen in der Ergebnisdatei jedes Marktes. Wer sie später vergleicht, sieht
sofort, ob sie aus demselben Lauf stammen — genau die Frage, an der dieser
Lauf schon einmal gescheitert ist.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.journal.version import code_version, decision_version

MARKETS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOGEUSDT", "BNBUSDT", "LTCUSDT", "DOTUSDT", "ATOMUSDT",
)

OUT = ROOT / "data" / "replay_rerun"


def run_one(symbol: str, *, strategy: str) -> dict[str, object]:
    started = time.time()
    done = subprocess.run(
        [sys.executable, "-u", str(ROOT / "scripts" / "run_backtest.py"),
         "--strategy", strategy, "--symbol", symbol],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    return {
        "symbol": symbol,
        "strategy": strategy,
        "exit": done.returncode,
        "seconds": round(time.time() - started, 1),
        "decision_version": decision_version(),
        "code_version": code_version(),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "stdout": done.stdout,
        "stderr": done.stderr[-4000:] if done.stderr else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(MARKETS))
    parser.add_argument("--strategy", default="guide-all")
    parser.add_argument("--force", action="store_true",
                        help="auch Maerkte neu rechnen, die schon ein Ergebnis haben")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    stamp = decision_version()

    print("=" * 74, flush=True)
    print(f"Replay-Neulauf, Strategie {args.strategy}", flush=True)
    print("=" * 74, flush=True)
    print(f"\n  Entscheidungsstempel {stamp}  |  Commit {code_version()}", flush=True)
    print(f"  {len(symbols)} Maerkte nach {OUT.relative_to(ROOT)}\n", flush=True)

    done_count = 0
    for index, symbol in enumerate(symbols, 1):
        target = OUT / f"{symbol}.json"
        if target.exists() and not args.force:
            previous = json.loads(target.read_text(encoding="utf-8"))
            same = previous.get("decision_version") == stamp
            note = "" if same else "  <-- ANDERER CODESTAND, mit --force neu rechnen"
            print(f"  [{index:>2}/{len(symbols)}] {symbol:9s} liegt vor "
                  f"({previous.get('seconds', 0):.0f}s){note}", flush=True)
            done_count += 1
            continue

        print(f"  [{index:>2}/{len(symbols)}] {symbol:9s} laeuft ... ", end="", flush=True)
        result = run_one(symbol, strategy=args.strategy)
        target.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"exit {result['exit']} nach {result['seconds']:.0f}s", flush=True)
        if result["exit"] == 0:
            done_count += 1

    print(f"\n  {done_count}/{len(symbols)} Maerkte fertig.", flush=True)

    stamps = set()
    for symbol in symbols:
        target = OUT / f"{symbol}.json"
        if target.exists():
            stamps.add(json.loads(target.read_text(encoding="utf-8")).get("decision_version"))
    if len(stamps) > 1:
        print(f"  WARNUNG: {len(stamps)} verschiedene Codestaende in den Ergebnissen.")
        print("  Das ist keine Messung. Mit --force neu rechnen.\n")
        return 1
    print(f"  Alle aus demselben Codestand: {stamps.pop() if stamps else '-'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
