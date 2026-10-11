"""Den Replay-Neulauf gegen das *vorher* festgelegte Kriterium prüfen.

    python scripts/eval_replay_rerun.py

**Was die Frage ist.** Der alte Replay belegte „die genommene Population ist
zuverlässig negativ" mit t = -3,37 gegen eine korrigierte Schwelle von 3,317
— sie passiert also knapp. Ohne Setup C war es t = -2,02 und damit nicht
belegt. C ist am 04.10. abgeschaltet worden, E dazugekommen. Die laufende
Konfiguration ist eine andere als die, über die der alte Replay gemessen hat.

**Das Kriterium stand vor dem Lauf** (`audit/PLAN_20H.md`, Zeile 166-175):
C verschwindet, E erscheint, A/B/G innerhalb ±10 %, Laufzeit über 15 min je
Markt. *Bricht die dritte Zeile, ist der Neulauf nicht vergleichbar* — dann
hat sich mehr geändert als die Setup-Liste. Das ist selbst ein Befund und
kein Grund, die Zahl trotzdem zu nehmen. Darum sagt dieses Skript das Urteil,
**bevor** es die interessante Zahl zeigt.

**Zwei Fehlversuche dieser Auswertung, beide am 11.10.**

*Erstens, die falsche Tabelle.* Die erste Fassung las die neuen Trades aus
`data/journal.sqlite`. Dort lagen 2.734 Trades über **vier** Märkte, während
der Neulauf zwölf gerechnet hatte, und BTCUSDT hatte 495 Zeilen, wo der Lauf
263 meldete. Das Journal hält den *alten* Lauf; der Neulauf schrieb nichts
hinein. Aufgefallen ist es an einer Nebenzahl — „4 Märkte" bei elf
Ergebnisdateien.

*Zweitens, die falsche Rekonstruktion.* Dieselbe Fassung leitete die alten
Setup-Zahlen aus `study_drop_setup.json` ab: Länge von `alle` minus Länge von
`ohne C` sei die Zahl der C-Trades. Das ist falsch, und die Studie sagt es in
ihrem eigenen Docstring — Setups konkurrieren um den einen Slot, also löscht
das Weglassen eines Setups nicht einfach seine Trades, sondern lässt andere
feuern. Die Differenz der Armlängen ist kein Zählwert.

Die alten Setup-Zahlen kommen deshalb direkt aus dem Journal, das die
einzelnen Trades des alten Laufs samt `setup_key` hält, und die neuen aus
`data/replay_fills/`, das der korrigierte Runner schreibt. Zwei Quellen, die
beide pro Trade eine Zeile haben — nicht eine Zusammenfassung gegen eine
Rekonstruktion.
"""

from __future__ import annotations

import json
import random
import sqlite3
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

NEW = ROOT / "data" / "replay_fills"
JOURNAL = ROOT / "data" / "journal.sqlite"
OUT = ROOT / "data" / "eval_replay_rerun.json"

# Vorab festgelegt, siehe audit/PLAN_20H.md.
TOLERANCE = 0.10
STABLE = ("A", "B", "G")
MIN_SECONDS = 900
DRAWS = 20_000
SEED = 20261011

#: Bonferroni-Nenner. Diese Auswertung ist eine vorab registrierte Frage.
TOTAL_COMPARISONS = 58


def setup_key(label: str) -> str:
    """`"B Trendlinien-Fakeout (V06)"` -> `"B"`.

    Der Fill speichert den Anzeigenamen, das Journal den Schluessel. Beide
    muessen auf denselben Wert kommen, sonst vergleicht die Tabelle Namen
    mit Buchstaben und findet ueberall eine Abweichung.
    """
    return (label or "?").split(" ", 1)[0].strip() or "?"


def load_new() -> tuple[list[dict[str, object]], dict[str, float], set[str], list[str]]:
    """Trades, Laufzeiten, Codestaende und Setup-Liste des Neulaufs."""
    trades: list[dict[str, object]] = []
    runtimes: dict[str, float] = {}
    stamps: set[str] = set()
    configured: list[str] = []
    for path in sorted(NEW.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("max_bars"):
            continue  # ein gekuerzter Rauchtest ist kein Messlauf
        runtimes[payload["symbol"]] = float(payload.get("seconds", 0.0))
        stamps.add(payload.get("decision_version"))
        configured = payload.get("setups") or configured
        for fill in payload.get("fills", []):
            trades.append({
                "symbol": payload["symbol"],
                "opened_ts": fill["opened_ts"],
                "r": float(fill["r_multiple"]),
                "setup": setup_key(fill.get("setup", "")),
            })
    return trades, runtimes, stamps, configured


def load_old() -> list[dict[str, object]]:
    """Die Trades des alten Laufs aus dem Journal."""
    if not JOURNAL.exists():
        return []
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)
    rows = []
    for symbol, opened, r_multiple, payload in conn.execute(
        "select symbol, opened_ts, r_multiple, payload from trades "
        "where source = 'replay' and r_multiple is not null"
    ):
        reason = json.loads(payload).get("reason") or {}
        rows.append({
            "symbol": symbol,
            "opened_ts": opened,
            "r": float(r_multiple),
            "setup": setup_key(reason.get("setup_key") or "?"),
        })
    conn.close()
    return rows


def block_bootstrap(values: list[float], *, draws: int, block: int) -> list[float]:
    """Mittelwerte aus Block-Resamples. Trades sind zeitlich abhaengig."""
    rng = random.Random(SEED)
    n = len(values)
    if n == 0:
        return []
    out = []
    blocks = max(1, -(-n // block))
    for _ in range(draws):
        sample: list[float] = []
        for _ in range(blocks):
            start = rng.randrange(n)
            sample.extend(values[(start + i) % n] for i in range(block))
        out.append(statistics.fmean(sample[:n]))
    return sorted(out)


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    index = q * (len(sorted_values) - 1)
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (index - low)


def interval(values: list[float]) -> tuple[float, float, float, int]:
    ordered = [v["r"] if isinstance(v, dict) else v for v in values]
    block = max(1, round(len(ordered) ** (1 / 3)))
    draws = block_bootstrap(ordered, draws=DRAWS, block=block)
    alpha = 0.05 / TOTAL_COMPARISONS
    return (statistics.fmean(ordered), percentile(draws, alpha / 2),
            percentile(draws, 1 - alpha / 2), block)


def setup_table(old_counts: Counter, new_counts: Counter, *, comparable: bool) -> bool:
    """Die Setup-Tabelle drucken und sagen, ob A/B/G in der Toleranz liegen."""
    print("  Setup-Tabelle\n")
    print(f"    {'Setup':6s} {'alt':>7s} {'neu':>7s} {'Delta':>9s}   Urteil")
    print(f"    {'-'*6} {'-'*7} {'-'*7} {'-'*9}   {'-'*10}")
    stable_ok = True
    for setup in sorted(set(new_counts) | set(old_counts)):
        old_n, new_n = old_counts.get(setup, 0), new_counts.get(setup, 0)
        shown = f"{(new_n - old_n) / old_n:+8.1%}" if old_n else "       —"
        note = ""
        if setup in STABLE and old_n and comparable:
            ok = abs((new_n - old_n) / old_n) <= TOLERANCE
            note = "ok" if ok else "ABWEICHUNG"
            stable_ok = stable_ok and ok
        elif setup in STABLE and not comparable:
            note = "n/a"
        print(f"    {setup:6s} {old_n:>7,} {new_n:>7,} {shown}   {note}")
    return stable_ok


def main() -> int:
    new, runtimes, stamps, configured = load_new()
    old = load_old()

    print("=" * 74)
    print("Replay-Neulauf gegen das vorab festgelegte Kriterium")
    print("=" * 74)

    if not new:
        print(f"\n  Noch keine Messergebnisse in {NEW.relative_to(ROOT)}.")
        print("  Der Lauf laeuft noch, oder es liegen nur gekuerzte Rauchtests.\n")
        return 2

    print(f"\n  neu   {len(runtimes)} Maerkte, {len(new):,} Trades, Stempel {stamps}")
    print(f"        Setups wie konfiguriert: {', '.join(configured)}")
    print(f"  alt   {len(set(t['symbol'] for t in old))} Maerkte, {len(old):,} Trades (Journal)\n")

    if len(stamps) > 1:
        print("  ABBRUCH: mehrere Codestaende im Neulauf. Das ist keine Messung.\n")
        return 1

    new_counts = Counter(t["setup"] for t in new)
    old_counts = Counter(t["setup"] for t in old)

    # Die Maerkte muessen dieselben sein, sonst vergleicht die Tabelle
    # Grundgesamtheiten und nicht Konfigurationen.
    new_markets = set(runtimes)
    old_markets = set(t["symbol"] for t in old)
    comparable = new_markets == old_markets
    shared = sorted(new_markets & old_markets)

    stable_ok = setup_table(old_counts, new_counts, comparable=comparable)

    verdicts: list[tuple[str, bool, str]] = [
        ("C verschwindet", new_counts.get("C", 0) == 0,
         f"{new_counts.get('C', 0)} C-Trades"),
        ("E erscheint", new_counts.get("E", 0) > 0,
         f"{new_counts.get('E', 0)} E-Trades"),
        (f"A, B, G innerhalb +/-{TOLERANCE:.0%}", stable_ok and comparable,
         "Trade-Zahl je Setup" if comparable
         else f"NICHT PRUEFBAR: alt {len(old_markets)} vs neu {len(new_markets)} Maerkte"),
        ("Laufzeit > 15 min je Markt",
         bool(runtimes) and all(v >= MIN_SECONDS for v in runtimes.values()),
         f"min {min(runtimes.values()):.0f}s, max {max(runtimes.values()):.0f}s"
         if runtimes else "keine"),
    ]

    print("\n  Kriterium (stand vor dem Lauf):\n")
    all_ok = True
    for name, ok, detail in verdicts:
        print(f"    [{'x' if ok else ' '}] {name:34s} {detail}")
        all_ok = all_ok and ok

    # ---- Erst jetzt die interessante Zahl -------------------------------
    print("\n  Die genommene Population")
    rows = []
    for label, pool in (("alt", old), ("neu", new)):
        if not pool:
            continue
        ordered = [t["r"] for t in sorted(pool, key=lambda t: t["opened_ts"])]
        mean, low, high, block = interval(ordered)
        excl = (low > 0) or (high < 0)
        print(f"    {label:4s} n={len(ordered):>6,}  Mittel {mean:+.4f} R  "
              f"Block {block:>2}  [{low:+.4f}, {high:+.4f}]  "
              f"Null {'AUS' if excl else 'EIN'}")
        rows.append({"arm": label, "n": len(ordered), "mean_r": round(mean, 6),
                     "block": block, "interval": [round(low, 6), round(high, 6)],
                     "excludes_zero": excl})

    # Dieselbe Frage nur ueber die gemeinsamen Maerkte, falls sie sich
    # unterscheiden -- sonst misst die Differenz die Marktauswahl.
    if not comparable and shared:
        print(f"\n    nur die {len(shared)} gemeinsamen Maerkte ({', '.join(shared)}):")
        for label, pool in (("alt", old), ("neu", new)):
            ordered = [t["r"] for t in sorted(
                (t for t in pool if t["symbol"] in shared), key=lambda t: t["opened_ts"])]
            if not ordered:
                continue
            mean, low, high, block = interval(ordered)
            excl = (low > 0) or (high < 0)
            print(f"    {label:4s} n={len(ordered):>6,}  Mittel {mean:+.4f} R  "
                  f"[{low:+.4f}, {high:+.4f}]  Null {'AUS' if excl else 'EIN'}")
            rows.append({"arm": f"{label}-gemeinsam", "n": len(ordered),
                         "mean_r": round(mean, 6),
                         "interval": [round(low, 6), round(high, 6)],
                         "excludes_zero": excl})

    if not all_ok:
        print("\n  Das Kriterium ist NICHT erfuellt. Die Zahlen oben sind damit")
        print("  nicht als Vergleich zweier Konfigurationen zu lesen — das ist")
        print("  der Befund, nicht die Expectancy.\n")

    OUT.write_text(json.dumps({
        "measured_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "decision_version": next(iter(stamps), None),
        "setups_configured": configured,
        "markets_new": sorted(new_markets),
        "markets_old": sorted(old_markets),
        "markets_comparable": comparable,
        "setup_counts_new": dict(sorted(new_counts.items())),
        "setup_counts_old": dict(sorted(old_counts.items())),
        "criterion": [{"name": n, "passed": o, "detail": d} for n, o, d in verdicts],
        "criterion_passed": all_ok,
        "populations": rows,
        "draws": DRAWS,
        "alpha_corrected": 0.05 / TOTAL_COMPARISONS,
        "runtimes_seconds": runtimes,
    }, indent=1), encoding="utf-8")
    print(f"  -> {OUT.relative_to(ROOT)}\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
