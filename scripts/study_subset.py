"""Enthält ein Pool ohne Vorteil eine Teilmenge mit Vorteil?

    python scripts/study_subset.py
    python scripts/study_subset.py --draws 20000

Der Zustandsbericht behauptete in Abschnitt 6.4: solange die regelbasierte
Auswahl keinen Vorteil hat, könne eine Auswahl *unter* diesen Einträgen nichts
beitragen -- "man kann aus nichts keine bessere Teilmenge ziehen".

Das ist ein Kategoriefehler. "Der Mittelwert des Pools ist nicht von null zu
trennen" und "keine Teilmenge hat einen positiven Mittelwert" sind
verschiedene Aussagen, und die zweite folgt nicht aus der ersten. Hundert
Signale aus zwanzig Trades à +1 R und achtzig à -0,4 R haben einen Pool von
-0,12 R und eine Teilmenge von +1 R.

Dieses Skript prüft es nicht am Beispiel, sondern an den eigenen Daten: es
teilt die Replay-Trades des Journals nach Merkmalen auf, die **vor** dem Trade
bekannt sind, und zeigt die Mittelwerte.

**Besonders unangenehm an dem Fehler:** Das Projekt hat bereits danach
gehandelt. Setup C wurde am 04.10.2026 abgeschaltet, weil seine Teilmenge
schlechter war als der Rest. Die Aussage in 6.4 widerspricht einer Entscheidung,
die drei Tage vorher auf derselben Grundlage getroffen wurde.

**Was dieses Skript NICHT zeigt.** Eine positive Teilmenge auf Daten, die
bereits gelesen wurden, ist ein Kandidat. Darum stehen hier zwei Dinge daneben,
die der Forschungsauftrag verlangt:

* ein Wochenblock-Intervall auf dem absoluten Mittelwert, denn "besser als der
  Pool" ist nicht dasselbe wie "profitabel", und
* ein **Zufallsfilter gleicher Selektivität** als Kontrolle. Ohne ihn
  verwechselt man den Effekt der Auswahl mit dem Effekt, überhaupt weniger
  Trades zu nehmen.

Nur Merkmale, die zum Entscheidungszeitpunkt existieren, dürfen aufteilen.
Haltezeit, MFE/MAE und Ausstiegsgrund sind hier deshalb bewusst nicht dabei --
die trennen nach dem Ergebnis und würden jede Teilmenge beliebig gut aussehen
lassen.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.journal.replayset import (
    load_replay as load_identified_replay,
)

JOURNAL = ROOT / "data" / "journal.sqlite"

DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS

DEFAULT_DRAWS = 10_000
SEED = 20261007

#: Unter so vielen Trades sagt ein Zellmittelwert mehr über die paar Trades als
#: über das Merkmal.
MIN_CELL = 30

#: Merkmale, die zum Entscheidungszeitpunkt feststehen. `symbol` kommt aus der
#: Tabelle, der Rest aus dem gespeicherten `reason`-Block -- also aus dem, was
#: die Bewertungsschicht VOR dem Einstieg erzeugt hat.
EX_ANTE = ("setup_key", "setup_timeframe", "rating_band", "regime", "side")

#: Ziehungen für die Zufallsfilter-Kontrolle. Weniger als der Bootstrap, weil
#: hier nur eine Spannweite gebraucht wird und nicht ein Rand.
CONTROL_DRAWS = 2_000


def load_replay() -> tuple[np.ndarray, np.ndarray, list[str], list[dict]]:
    """R-Vielfache, Eröffnungszeit, Markt und der ex-ante-Block je Replay-Trade.

    **Aus `data/replay_fills/`, nicht aus der Journal-Datenbank.** Hier stand
    bis zum 15.10.2026 ein `SELECT ... WHERE source='replay'` auf
    `data/journal.sqlite`, und das sind 2.734 Trades über **vier** Märkte,
    alle mit leerer `run_signature`, leerem `decision_version` und leerem
    `code_version`. Welche Konfiguration sie erzeugt hat, ist aus den Daten
    nicht zu beantworten; sie stimmen nicht einmal mit denselben vier Märkten
    in den Dateien überein (BTCUSDT: 495 Zeilen gegen 263). Die Datenbank hält
    einen älteren Lauf, der korrigierte Runner schreibt Dateien.

    Zwei Folgen, und die zweite wiegt schwerer:

    * Die Suche lief auf einem Viertel der Daten. Es liegen 7.335 Trades über
      zwölf Märkte vor, mit Herkunft je Datei und je Eintrag.
    * **`setup_key` ist eines der ex-ante-Merkmale dieser Suche, und es war
      falsch.** `journal/build.py:_setup_for` schrieb einen Trade dem ersten
      Setup zu, das auf seinem Balken feuerte — aus ALLEN Setups statt aus
      den freigegebenen. In den Dateien tragen 204 von 7.335 Trades das
      Etikett eines Setups, das zur Laufzeit abgeschaltet war. Eine Suche
      nach einer profitablen Teilmenge mit einem falschen Merkmal sucht in
      der falschen Richtung.

    `Fill.setup` trägt die Wahrheit — der Pool setzt es beim Feuern — und in
    jeder Datei stehen `fills` und `journal` index-gleich nebeneinander. Das
    Setup kommt deshalb aus dem Fill, alles übrige aus dem `reason`-Block.
    """
    population = load_identified_replay(ROOT / "data")
    if population is None:
        raise SystemExit(
            "Keine Replay-Dateien in data/replay_fills -- "
            "scripts/replay_all_markets.py hat noch nicht gelaufen."
        )
    print(f"Population: {population.labelled()}")
    if population.mixed:
        raise SystemExit(
            "Gemischte Codestaende in der Population. Eine Teilmengensuche "
            "ueber zwei Staende findet Unterschiede zwischen den Staenden."
        )

    rows: list[tuple[float, int, str, dict]] = []
    for path in sorted((ROOT / "data" / "replay_fills").glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        fills, entries = blob.get("fills", []), blob.get("journal", [])
        if len(fills) != len(entries):
            raise SystemExit(
                f"{path.name}: {len(fills)} Fills gegen {len(entries)} "
                "Journal-Eintraege -- ohne gleiche Laenge ist die Zuordnung "
                "von Setup zu Begruendung geraten und nicht gelesen."
            )
        for fill, entry in zip(fills, entries, strict=True):
            reason = dict(entry.get("reason") or {})
            # Das Setup aus dem FILL, der Rest aus der Begruendung.
            reason["setup_key"] = fill.get("setup") or reason.get("setup_key", "?")
            rows.append((fill["r_multiple"], fill["opened_ts"], blob["symbol"], reason))

    rows.sort(key=lambda row: row[1])
    r = np.array([row[0] for row in rows], dtype=float)
    ts = np.array([row[1] for row in rows], dtype=np.int64)
    symbols = [row[2] for row in rows]
    reasons = [row[3] for row in rows]
    return r, ts, symbols, reasons


def block_bootstrap(
    values: np.ndarray, stamps: np.ndarray, *, draws: int, seed: int = SEED
) -> tuple[float, float]:
    """95%-Intervall für den Mittelwert, ganze Wochen mit Zurücklegen gezogen.

    Zeilen zu ziehen wäre hier doppelt falsch: die Märkte bewegen sich
    gemeinsam, und ein Trade dauert mehrere Kerzen. Beides macht benachbarte
    Zeilen abhängig, und das Intervall mehrfach zu eng.
    """
    rng = np.random.default_rng(seed)
    blocks = stamps // WEEK_MS
    unique = np.unique(blocks)
    index = {b: np.flatnonzero(blocks == b) for b in unique}
    target = values.size
    per_draw = int(np.ceil(target / np.mean([index[b].size for b in unique]))) + 2

    means = np.empty(draws)
    for d in range(draws):
        taken = np.concatenate(
            [index[b] for b in rng.choice(unique, size=per_draw, replace=True)]
        )
        while taken.size < target:
            extra = rng.choice(unique, size=per_draw, replace=True)
            taken = np.concatenate([taken, *(index[b] for b in extra)])
        means[d] = values[taken[:target]].mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def random_filter(
    values: np.ndarray, *, share: float, seed: int = SEED
) -> tuple[float, float, float]:
    """Was ein Filter erreicht, der nichts weiss, aber genauso selektiv ist.

    Die Kontrolle, ohne die man den Effekt der Auswahl mit dem Effekt
    verwechselt, überhaupt weniger Trades zu nehmen.
    """
    rng = np.random.default_rng(seed + 1)
    means = []
    for _ in range(CONTROL_DRAWS):
        pick = rng.random(values.size) < share
        if pick.sum() > MIN_CELL:
            means.append(values[pick].mean())
    arr = np.array(means)
    return float(arr.mean()), float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))


def report_cells(title: str, buckets: dict[str, list[float]]) -> None:
    print(f"\n{title}")
    cells = [(k, float(np.mean(v)), len(v)) for k, v in buckets.items() if len(v) >= MIN_CELL]
    if not cells:
        print(f"  keine Zelle mit mindestens {MIN_CELL} Trades")
        return
    for key, mean, n in sorted(cells, key=lambda c: -c[1]):
        mark = "   <-- POSITIV" if mean > 0 else ""
        print(f"  {key:26s} n={n:>5d}  {mean:+.4f} R{mark}")


def judge(
    r: np.ndarray, ts: np.ndarray, mask: np.ndarray, *, label: str, draws: int
) -> None:
    """Die beste Zelle gegen die beiden Pruefungen, die sie bestehen muesste.

    Getrennt von `main`, weil hier die eigentliche Arbeit steckt: ein
    Punktwert ohne Intervall und ohne Kontrolle ist genau die Form, in der
    dieses Projekt schon acht Scheinfunde produziert hat.
    """
    print("\n" + "=" * 78)
    print("Die beste Zelle, mit den beiden Pruefungen daneben")
    print("=" * 78)
    pool_low, pool_high = block_bootstrap(r, ts, draws=draws)
    print(
        f"\n  GESAMTPOOL            n={r.size:>5d}  {r.mean():+.4f} R"
        f"  [{pool_low:+.4f}, {pool_high:+.4f}]"
    )

    sub, sub_ts = r[mask], ts[mask]
    low, high = block_bootstrap(sub, sub_ts, draws=draws)
    print(f"  {label:22s}n={sub.size:>5d}  {sub.mean():+.4f} R  [{low:+.4f}, {high:+.4f}]")

    share = float(mask.mean())
    ctrl_mean, ctrl_low, ctrl_high = random_filter(r, share=share)
    print(
        f"\n  Zufallsfilter gleicher Selektivitaet ({100 * share:.1f}%):"
        f"\n    Mittel {ctrl_mean:+.4f} R, 95%-Spanne [{ctrl_low:+.4f}, {ctrl_high:+.4f}]"
    )

    print("\n" + "-" * 78)
    if low > 0.0:
        print("  Die Teilmenge ist absolut belegt positiv: ihr Intervall schliesst die")
        print("  Null aus. Das rechtfertigt einen Kandidaten fuers Prueffenster -- nach")
        print("  Mehrfachkorrektur ueber alle hier angesehenen Zellen.")
    else:
        print("  Die Teilmenge ist NICHT absolut belegt: ihr Intervall umspannt die Null.")
    if sub.mean() > ctrl_high:
        print("  Gegen den Zufallsfilter liegt sie oberhalb dessen 97,5-%-Punkts, also")
        print("  nicht allein dadurch erklaerbar, dass sie weniger Trades nimmt.")
    else:
        print("  Gegen den Zufallsfilter liegt sie innerhalb dessen Spanne -- der Effekt")
        print("  ist von 'einfach weniger Trades' nicht zu trennen.")
    print(
        "\n  Beides entscheidet die Frage dieses Skripts aber nicht: die Zellen oben\n"
        "  wurden alle auf denselben, schon oft gelesenen Daten angesehen. Was hier\n"
        "  steht, widerlegt den Satz 'eine Auswahl kann nichts beitragen' -- es belegt\n"
        "  keinen Vorteil. Der Nachweis ist E1, auf neuen Daten, mit angemeldeten Zellen."
    )
    print("-" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    args = parser.parse_args()

    r, ts, symbols, reasons = load_replay()

    print("=" * 78)
    print("Hat ein Pool ohne Vorteil eine Teilmenge mit Vorteil?")
    print("=" * 78)
    print(f"\nGESAMTPOOL  n={r.size:,}  {r.mean():+.4f} R")

    buckets: dict[str, dict[str, list[float]]] = {"symbol": defaultdict(list)}
    for key in EX_ANTE:
        buckets[key] = defaultdict(list)
    for value, symbol, reason in zip(r, symbols, reasons, strict=True):
        buckets["symbol"][symbol].append(value)
        for key in EX_ANTE:
            found = reason.get(key)
            if found is not None:
                buckets[key][str(found)].append(value)

    report_cells("Nach Markt (steht vor dem Trade fest):", buckets["symbol"])
    for key in EX_ANTE:
        report_cells(f"Nach {key} (aus dem gespeicherten reason-Block):", buckets[key])

    # Die beste Zelle bekommt die beiden Prüfungen, die aus einem Punktwert
    # entweder einen Kandidaten oder nichts machen.
    best_key, best_value, best_mask = None, None, None
    best_mean = -np.inf
    for key, cells in buckets.items():
        for name, values in cells.items():
            if len(values) < MIN_CELL:
                continue
            mean = float(np.mean(values))
            if mean > best_mean:
                best_mean, best_key, best_value = mean, key, name
                if key == "symbol":
                    best_mask = np.array([s == name for s in symbols])
                else:
                    best_mask = np.array([str(x.get(key)) == name for x in reasons])

    assert best_mask is not None
    judge(r, ts, best_mask, label=f"{best_key}={best_value}", draws=args.draws)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
