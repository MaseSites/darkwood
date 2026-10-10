"""Was passiert hier gegen 08:30 UTC? Drei Adressen gleichzeitig, bis der Ausbruch kommt.

    python scripts/probe_burst_window.py --hours 24

**Anlass.** Der Papierhandel hatte zwei Fehler-Ausbrüche an zwei Tagen, beide
im selben Tagesfenster:

| | 09.10.2026 | 10.10.2026 |
|---|---|---|
| Fenster (UTC) | 08:20 - 10:43 | Ende 08:33 |
| Fehlerquote | 47 % | **77 %** |
| Signatur | `fetch_ohlcv(.., W1)`, alle 12 Märkte | identisch |

Gemessen und ausgeschlossen ist dabei schon zweierlei (`audit/WARUM_W1.md`):
es ist **nicht W1** — die Streuung der Antwortzeiten über Zeitebenen ist 3 ms,
über Positionen im Zyklus 37 ms, W1 trug nur den Hut der Position 1 — und es
ist auch **nicht der Kaltstart**, denn 36 ms Aufschlag erzeugen keinen Abbruch
bei 10 000 ms, und er verschiebt den Körper der Verteilung ohne einen Rand
hinzuzufügen, während ein Timeout ein Randereignis ist.

**Was bleibt, und was dieses Skript trennt.** Drei Kandidaten, und sie sind
durch *gleichzeitige* Abrufe unterscheidbar:

| fällt aus | Schluss |
|---|---|
| nur `klines` | der eine Endpunkt, nicht die Börse |
| `klines` **und** `time` | die Börse |
| alle drei | **diese Leitung** (geplanter Vorgang auf dieser Maschine) |

**Warum es laufen muss, bevor das Fenster aufgeht.** Am 09.10. habe ich nach
dem Ausbruch 1 415 Abrufe gemacht, 0 Fehler gezählt und daraus gelesen, er
wiederhole sich nicht. Einen Tag später war er schlimmer. Ein Ruhe-Mass kann
einen Rand nicht auflösen, der während der Messung abwesend war — darum
beginnt dieses hier *vor* dem Fenster und läuft hindurch.

**Takt und Rücksicht.** Eine Runde je 60 s, drei Abrufe. Gewicht 1 je
`klines`-Abruf mit `limit=24` und 1 je `time`; gegen das Minutenbudget der
Börse ist das nichts, und der Papierhandel teilt dieselbe IP. Die
Vergleichsadresse ist Cloudflares `cdn-cgi/trace` — ein Diagnose-Endpunkt von
wenigen hundert Bytes, für genau diesen Zweck gebaut.

Nur lesen. Kein Schlüssel, keine Order, kein Konto.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Die drei Adressen. Der Name steht im Bericht, also kurz und eindeutig.
TARGETS = (
    # Genau der Aufruf, der scheitert -- dieselbe Ebene, dieselbe Grenze.
    ("klines", "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1w&limit=24"),
    # Billigste Lebenszeichen derselben Boerse. Trennt "dieser Endpunkt" von
    # "die Boerse".
    ("time", "https://fapi.binance.com/fapi/v1/time"),
    # Unabhaengig von der Boerse. Trennt "die Boerse" von "diese Leitung".
    ("fremd", "https://cloudflare.com/cdn-cgi/trace"),
)

TIMEOUT = 20.0
EVERY = 60.0
GAP = 1.0
#: Je Lauf eine eigene Datei. Ein fester Pfad hat am 10.10. beinahe die
#: Rohwerte des Vorlaufs geloescht: der zweite Lauf schreibt seinen ersten
#: Checkpoint nach fuenfzehn Runden, und `data/` ist gitignoriert, also waere
#: nichts davon wiederherstellbar gewesen. Der Zeitstempel kommt aus der
#: ersten Runde, nicht aus dem Start, damit er zur Messung passt.
OUT_DIR = ROOT / "data"


def one(url: str) -> tuple[float, str]:
    """Antwortzeit in Millisekunden, oder der Fehler."""
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:
            answer.read()
        return 1000.0 * (time.perf_counter() - started), ""
    except (urllib.error.URLError, TimeoutError, OSError) as problem:
        return (
            1000.0 * (time.perf_counter() - started),
            f"{type(problem).__name__}: {str(problem)[:70]}",
        )


def _target(rows: list[dict[str, float | str]]) -> Path:
    """Der Dateiname dieses Laufs, benannt nach seiner ersten Runde."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.fromtimestamp(float(rows[0]["ts"]), dt.UTC)
    return OUT_DIR / f"probe_burst_window_{stamp:%Y%m%d_%H%M}.json"


def report(rows: list[dict[str, float | str]]) -> None:
    print("\n" + "=" * 78)
    print(f"  {len(rows)} Runden")
    print("=" * 78)
    print(f"\n  {'Adresse':9s} {'n':>5s} {'Median':>9s} {'p90':>9s} {'Fehler':>7s} {'Quote':>7s}")
    print("  " + "-" * 52)
    for name, _ in TARGETS:
        times = [float(r[f"{name}_ms"]) for r in rows if not r[f"{name}_err"]]
        bad = sum(1 for r in rows if r[f"{name}_err"])
        if not times:
            print(f"  {name:9s} {0:>5} {'-':>9s} {'-':>9s} {bad:>7} {'100.0':>6}%")
            continue
        ordered = sorted(times)
        p90 = ordered[int(0.9 * (len(ordered) - 1))]
        quote = 100.0 * bad / len(rows)
        print(f"  {name:9s} {len(times):>5} {statistics.median(times):>8.0f}ms "
              f"{p90:>8.0f}ms {bad:>7} {quote:>6.1f}%")

    print("\n  Lesehilfe, vorab festgelegt:")
    print("    nur 'klines' faellt aus          -> der Endpunkt, nicht die Boerse")
    print("    'klines' UND 'time' fallen aus   -> die Boerse")
    print("    alle drei fallen aus             -> diese Leitung")
    print("    keiner faellt aus                -> das Fenster war heute leer,")
    print("                                        und das ist KEINE Antwort")

    windows = [r for r in rows if any(r[f"{n}_err"] for n, _ in TARGETS)]
    if windows:
        first = dt.datetime.fromtimestamp(float(windows[0]["ts"]), dt.UTC)
        last = dt.datetime.fromtimestamp(float(windows[-1]["ts"]), dt.UTC)
        print(f"\n  Fehler zwischen {first:%d.%m %H:%M} und {last:%d.%m %H:%M} UTC")
    else:
        print("\n  Kein einziger Fehler im ganzen Fenster.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args()

    print("=" * 78)
    print("Drei Adressen gleichzeitig -- wo faellt es aus?")
    print("=" * 78)
    print(f"\n  {len(TARGETS)} Adressen, Takt {EVERY:.0f}s, {args.hours:.0f} Stunden.")
    print("  Beginnt VOR dem Fenster und laeuft hindurch -- ein Ruhe-Mass kann")
    print("  einen Rand nicht aufloesen, der waehrend der Messung fehlt.\n")
    print("  Nur lesen. Kein Schluessel, keine Order.\n", flush=True)

    rows: list[dict[str, float | str]] = []
    out: Path | None = None
    deadline = time.time() + args.hours * 3600
    try:
        while time.time() < deadline:
            row: dict[str, float | str] = {"ts": time.time()}
            for name, url in TARGETS:
                spent, problem = one(url)
                row[f"{name}_ms"] = round(spent, 1)
                row[f"{name}_err"] = problem
                if problem:
                    stamp = dt.datetime.now(dt.UTC)
                    print(f"  ! {stamp:%d.%m %H:%M:%S} {name:9s} nach {spent:.0f}ms: "
                          f"{problem}", flush=True)
                time.sleep(GAP)
            rows.append(row)
            if len(rows) % 15 == 0:
                bad = sum(1 for r in rows if any(r[f"{n}_err"] for n, _ in TARGETS))
                stamp = dt.datetime.now(dt.UTC)
                print(f"  [{stamp:%H:%M} UTC] {len(rows)} Runden, {bad} mit Fehler",
                      flush=True)
                out = out or _target(rows)
                out.write_text(json.dumps({"rounds": rows}, indent=1), encoding="utf-8")
            time.sleep(max(0.0, EVERY - GAP * len(TARGETS)))
    except KeyboardInterrupt:
        print("\n  Abgebrochen. Was gemessen ist, bleibt.")

    if rows:
        out = out or _target(rows)
        out.write_text(json.dumps({"rounds": rows}, indent=1), encoding="utf-8")
        print(f"\n  {len(rows)} Runden nach {out.relative_to(ROOT)}")
        report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
