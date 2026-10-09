"""Warum W1 -- die Antwortzeit je Zeitebene messen, statt sie zu erklären.

    python scripts/probe_kline_latency.py --minutes 120

**Anlass.** Am 09.10.2026 lief der Papierhandel rund zweieinhalb Stunden mit
etwa 47 % Fehlerquote, und **alle zwölf Märkte** scheiterten an
`fetch_ohlcv(..., W1)` -- dem ersten Abruf jedes Zyklus -- mit einem
ccxt-Timeout. Dass W1 der erste ist, ist eine Beobachtung und keine Erklärung.

Zwei Deutungen, und sie sind unterscheidbar:

1. **W1 ist teuer.** Eine Wochenkerze spannt über viele Rohkerzen; falls die
   Börse sie beim Abruf aggregiert, wäre sie systematisch langsamer. Dann
   müsste die Antwortzeit je Zeitebene auseinanderliegen -- unabhängig von der
   Reihenfolge.
2. **W1 ist nur zuerst dran.** Dann trägt der erste Abruf eines Zyklus die
   Kosten des Verbindungsaufbaus, und die Zeitebene ist gleichgültig. Dann
   müsste der ERSTE Abruf langsam sein, egal welche Ebene das ist.

Dieses Skript trennt die beiden: es fragt jede Zeitebene ab, und in jedem
Durchgang in **gedrehter** Reihenfolge. Die Drehung ist der ganze Trick --
ohne sie messen Reihenfolge und Zeitebene dasselbe.

**Nur lesen.** Kein Schlüssel, keine Order, derselbe öffentliche Endpunkt, den
der Papierhandel benutzt.

*Dass es derselbe ist, wurde geprüft und nicht angenommen:* `settings.yaml`
sagt `testnet: true`, und `venue.build()` schickt einen Testnet-Client auf
`demo-fapi.binance.com` -- rund doppelt so langsam (848 gegen 442 ms Median).
Aber `papertrade.py:105` übergibt ausdrücklich `testnet=False`, weil Kerzen
öffentlich sind. Die Zeile in der Konfiguration gilt dem Ausführer, nicht den
Daten. Gemessen wird also der Pfad, der auch gescheitert ist.

**Die Rohwerte bleiben.** Eine Zusammenfassung ohne ihre Stichprobe lässt sich
nicht nachprüfen; alle Einzelmessungen gehen nach
`data/probe_kline_latency.json`.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BASE = "https://fapi.binance.com/fapi/v1/klines"
TIMEOUT = 20.0

#: Dieselben Zeitebenen, die der Papierhandel je Zyklus holt, mit denselben
#: Grenzen: 24 Kerzen je Kontextebene.
FRAMES = (("1w", 24), ("1d", 24), ("4h", 24), ("1h", 24), ("15m", 24))

#: Ein Symbol genügt für die Frage. Zwölf würden die Rate verdreifachen,
#: während der Papierhandel dieselbe IP benutzt.
SYMBOL = "BTCUSDT"

#: Pause zwischen zwei Abrufen innerhalb eines Durchgangs. Gewicht 1 je
#: klines-Abruf mit limit=24; fünf Abrufe je Durchgang sind nichts. Die Pause
#: steht da, damit der Papierhandel nicht verdrängt wird.
GAP = 2.0

#: Pause zwischen Durchgängen.
EVERY = 30.0

#: Wohin die Einzelmessungen gehen. Ohne sie ist der Bericht eine Behauptung
#: über eine Stichprobe, die niemand mehr hat.
OUT = ROOT / "data" / "probe_kline_latency.json"


def one_call(interval: str, limit: int) -> tuple[float, str]:
    """Antwortzeit in Millisekunden, oder der Fehler."""
    url = f"{BASE}?symbol={SYMBOL}&interval={interval}&limit={limit}"
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:
            rows = json.loads(answer.read())
        spent = 1000.0 * (time.perf_counter() - started)
        return spent, "" if rows else "leer"
    except (urllib.error.URLError, TimeoutError, OSError) as problem:
        spent = 1000.0 * (time.perf_counter() - started)
        return spent, f"{type(problem).__name__}: {str(problem)[:60]}"


def report(
    by_frame: dict[str, list[float]],
    by_position: dict[int, list[float]],
    errors: dict[str, int],
    rounds: int,
) -> None:
    print("\n" + "=" * 78)
    print(f"  {rounds} Durchgaenge, Reihenfolge je Durchgang gedreht")
    print("=" * 78)

    print("\n  Nach ZEITEBENE -- traegt W1 eine eigene Kosten?\n")
    print(f"  {'Ebene':8s} {'n':>5s} {'Median':>9s} {'p90':>9s} {'max':>9s} {'Fehler':>7s}")
    print("  " + "-" * 52)
    for interval, _ in FRAMES:
        times = by_frame.get(interval, [])
        if not times:
            continue
        ordered = sorted(times)
        p90 = ordered[int(0.9 * (len(ordered) - 1))]
        print(f"  {interval:8s} {len(times):>5} {statistics.median(times):>8.0f}ms "
              f"{p90:>8.0f}ms {max(times):>8.0f}ms {errors.get(interval, 0):>7}")

    print("\n  Nach POSITION im Durchgang -- zahlt der erste Abruf?\n")
    print(f"  {'Position':9s} {'n':>5s} {'Median':>9s} {'p90':>9s} {'max':>9s}")
    print("  " + "-" * 45)
    for position in sorted(by_position):
        times = by_position[position]
        ordered = sorted(times)
        p90 = ordered[int(0.9 * (len(ordered) - 1))]
        print(f"  {position + 1:>9} {len(times):>5} {statistics.median(times):>8.0f}ms "
              f"{p90:>8.0f}ms {max(times):>8.0f}ms")

    frames_spread = _spread({k: v for k, v in by_frame.items() if v})
    positions_spread = _spread({str(k): v for k, v in by_position.items() if v})
    print(
        f"\n  Streuung der Mediane:\n"
        f"    ueber Zeitebenen  {frames_spread:>7.0f} ms\n"
        f"    ueber Positionen  {positions_spread:>7.0f} ms\n"
    )
    print(
        "  Lesehilfe, vorab: ist die Streuung ueber ZEITEBENEN deutlich groesser,\n"
        "  traegt W1 eigene Kosten. Ist die Streuung ueber POSITIONEN groesser,\n"
        "  zahlt der erste Abruf eines Zyklus und die Ebene ist gleichgueltig.\n"
        "  Sind beide klein, war der Ausbruch vom 09.10. keine Eigenschaft des\n"
        "  Abrufs -- und dann bleibt die Frage offen statt beantwortet."
    )


def _spread(groups: dict[str, list[float]]) -> float:
    medians = [statistics.median(v) for v in groups.values() if v]
    return (max(medians) - min(medians)) if len(medians) > 1 else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=120.0)
    args = parser.parse_args()

    print("=" * 78)
    print("Antwortzeit je Zeitebene -- warum W1?")
    print("=" * 78)
    print(
        f"\n  {SYMBOL}, {len(FRAMES)} Zeitebenen, Reihenfolge je Durchgang gedreht.\n"
        f"  Takt {EVERY:.0f}s, {GAP:.0f}s zwischen den Abrufen, {args.minutes:.0f} Minuten.\n"
        f"\n  Die Drehung ist der ganze Trick: ohne sie messen Reihenfolge und\n"
        f"  Zeitebene dasselbe.\n"
        f"\n  Nur lesen. Kein Schluessel, keine Order.\n",
        flush=True,
    )

    by_frame: dict[str, list[float]] = defaultdict(list)
    by_position: dict[int, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    raw: list[dict[str, Any]] = []
    deadline = time.time() + args.minutes * 60
    rounds = 0

    try:
        while time.time() < deadline:
            order = FRAMES[rounds % len(FRAMES):] + FRAMES[: rounds % len(FRAMES)]
            for position, (interval, limit) in enumerate(order):
                spent, problem = one_call(interval, limit)
                raw.append({
                    "round": rounds,
                    "position": position,
                    "frame": interval,
                    "ms": round(spent, 3),
                    "error": problem,
                })
                if problem:
                    errors[interval] += 1
                    print(f"  ! {interval} nach {spent:.0f}ms: {problem}", flush=True)
                else:
                    by_frame[interval].append(spent)
                    by_position[position].append(spent)
                time.sleep(GAP)
            rounds += 1
            if rounds % 10 == 0:
                done = sum(len(v) for v in by_frame.values())
                print(f"  [{rounds:>4} Durchgaenge] {done:,} Messungen, "
                      f"{sum(errors.values())} Fehler", flush=True)
            time.sleep(max(0.0, EVERY - GAP * len(FRAMES)))
    except KeyboardInterrupt:
        print("\n  Abgebrochen. Was gemessen ist, bleibt.")

    if raw:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps({"symbol": SYMBOL, "rounds": rounds, "calls": raw}, indent=1),
            encoding="utf-8",
        )
        print(f"\n  {len(raw):,} Einzelmessungen nach {OUT.relative_to(ROOT)}")
    if rounds:
        report(by_frame, by_position, errors, rounds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
