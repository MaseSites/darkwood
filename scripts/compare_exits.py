"""Does moving the stop to the entry help, or does it just cut the winners?

    python scripts/compare_exits.py --at 1.0 0.5

The journal says 19% of two thousand trades were at least one R in profit and
ended as losses, and 35% were stopped by a wick the bar closed back through.
Only 8% never went our way at all. That points at the exit, and this measures
whether the obvious fix is one.

**The rule runs inside the simulator, not beside it.** An earlier version of
this replayed the minute bars in a separate script, and its own self-check
caught it being wrong by 0.074 R -- almost as large as the effect being
measured. It had missed gaps through the stop, liquidations and V08's runner,
each of which the simulator already handles. A rule tested beside the engine is
a second answer to the same question, and the second answer was wrong.

**It cuts both ways by construction.** A stop at the entry saves the trades
that gave a point back and scratches the ones that dipped before running. The
whole question is which of the two is bigger, so a result near zero is a real
answer rather than a failed measurement.

**One history, several rules.** The best of four is the best of four draws.
Intervals are printed; a winner here has earned a forward test, not a promotion.

--------------------------------------------------------------------------- #

**Was sich am 14.10.2026 geaendert hat, und warum vor dem ersten Lauf.** Das
Skript rechnete einen Mittelwert und einen 95%-Standardfehler. E14 ist aber mit
mehr angemeldet (`audit/EXPERIMENTS_NEXT.yaml`), und ein angemeldetes Kriterium
nachtraeglich fallen zu lassen ist derselbe Fehler wie eines nachtraeglich
hinzuzufuegen:

* **Beide Tore.** Korrigiertes Intervall ohne Null auf der DIFFERENZ zur
  heutigen Regel, Niveau `1 - 0.05/67`, UND Replikation 0.5-2.0x zwischen der
  frueheren und der spaeteren Haelfte.
* **Ungepaart.** Ein Einstand-Stop beendet Trades frueher und gibt den
  naechsten Einstieg frei. Die Mengen sind verschieden gross und enthalten
  verschiedene Trades; `paired_difference` waere hier falsch, also
  `two_group_difference`.
* **Block-Bootstrap statt Standardfehler.** Zwoelf korrelierte Maerkte, ein
  schlechter Nachmittag ist ein Ereignis und nicht zwoelf. Der
  Standardfehler oben war zuverlaessig zu schmal.
* **Der Rand, vorab festgelegt** (Lehre aus E10: besserer Mittelwert,
  dreifacher schlimmster Verlust): Anteil unter -1R, schlimmster
  Einzelverlust, 5%-Quantil, und der Anteil der scharfgestellten Trades, die
  der Einstand-Stop abschneidet.

**Und der Lauf ist fortsetzbar.** 12 Maerkte x 3 Regeln, je ein voller
Motorlauf, grob 18 Stunden. Ohne Zwischenspeicher verliert ein Abbruch in
Stunde 17 alles -- und ein Fehler in der Auswertung kostet die 18 Stunden
nochmal. Jedes (Regel, Markt)-Paar wird deshalb sofort nach dem Lauf als
JSONL-Zeile geschrieben und beim naechsten Start uebersprungen.
`--only-report` rechnet allein aus dem Zwischenspeicher.

Nur lesen, bis auf den Zwischenspeicher. Keine Datei in `data/` wird
veraendert.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import ExitReason
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.reporting.intervals import block_bootstrap, two_group_difference
from traidingbrain.sim.engine import load_engine
from traidingbrain.strategies.guide import GuidePool

#: Angemeldete Vergleiche im Versuchsregister, Stand 14.10.2026. Dieselbe Zahl
#: wie in `audit/EXPERIMENTS_NEXT.yaml:46`; sie steht hier als Literal, weil
#: ein Skript, das sein eigenes Niveau aus einer Datei liest, die es auch
#: schreiben koennte, kein Niveau hat.
TOTAL_COMPARISONS = 67

#: Die Replikationsschranken, wie fuer jeden Arm in diesem Projekt.
REPLICATION = (0.5, 2.0)

#: Unterhalb dieser Differenz in der frueheren Haelfte ist das Verhaeltnis
#: nicht mehr lesbar -- durch fast null geteilt wird jede Zahl gross.
#:
#: Dass ein winziges `early` das Verhaeltnis explodieren laesst, ist KEIN
#: Defekt: zeigt die erste Haelfte keinen Effekt, hat er nicht repliziert, und
#: ein Tor, das dann faellt, hat recht. Die echte Schwaeche eines
#: Verhaeltnisses liegt andersherum -- sind BEIDE Haelften winzig und
#: gleichgerichtet, steht da 1.0x und das Tor geht auf Rauschen auf. Dagegen
#: schuetzt Tor 1, nicht dieses.
NEAR_ZERO = 1e-9

#: Wohin der Zwischenspeicher geht. `data/` ist gitignoriert.
CACHE = ROOT / "data" / "e14_exits.jsonl"


@dataclass(frozen=True)
class Trade:
    """Das, was die Auswertung von einem Trade braucht -- und nichts weiter."""

    r: float
    opened_ts: int
    reason: str
    #: Ob der Stop bis zum Ausstieg auf den Einstand nachgezogen war. Ohne
    #: dieses Feld ist die vierte angemeldete Rand-Kennzahl nicht messbar,
    #: siehe `sim/broker.py:Fill.stop_moved`.
    stop_moved: bool

    @property
    def scratched(self) -> bool:
        """Scharfgestellt und dann am Einstand ausgestoppt.

        Das ist die Menge, die die Regel KOSTET: diese Trades lagen weit
        genug vorn, um den Stop nachzuziehen, und wurden dann dort
        abgeschnitten, statt weiterzulaufen.
        """
        return self.stop_moved and self.reason == ExitReason.STOP.value


def run(symbol: str, breakeven: float | None) -> list[Trade]:
    """Jeder Trade eines Marktes unter einer Ausstiegsregel."""
    config = load_config()
    if breakeven is not None:
        simulation = config.engine.simulation.model_copy(update={"breakeven_at_r": breakeven})
        engine_config = config.engine.model_copy(update={"simulation": simulation})
        config = config.model_copy(update={"engine": engine_config})

    store = ParquetStore(config.engine.paths.parquet_dir)
    frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
    minutes = store.read(symbol, config.engine.timeframes.execution)
    if any(frame.empty for frame in frames.values()) or minutes.empty:
        return []

    engine = load_engine(
        symbol,
        frames,
        minute_frame=minutes,
        spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
        config=config,
        funding=FundingStore(config.engine.paths.funding_dir).read(symbol),
        history=None,
    )
    result = engine.run(GuidePool.for_config(config))
    return [
        Trade(
            r=fill.r_multiple,
            opened_ts=fill.opened_ts,
            reason=str(fill.reason),
            stop_moved=fill.stop_moved,
        )
        for fill in result.fills
    ]


# --------------------------------------------------------------------------- #
# Zwischenspeicher
# --------------------------------------------------------------------------- #


def load_cache(path: Path) -> dict[tuple[str, str], list[Trade]]:
    """Was schon gelaufen ist, nach (Regel, Markt)."""
    if not path.exists():
        return {}
    done: dict[tuple[str, str], list[Trade]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        done[(row["rule"], row["symbol"])] = [Trade(**t) for t in row["trades"]]
    return done


def append_cache(path: Path, rule: str, symbol: str, trades: list[Trade]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "rule": rule,
            "symbol": symbol,
            "trades": [asdict(t) for t in trades],
        }) + "\n")


# --------------------------------------------------------------------------- #
# Auswertung
# --------------------------------------------------------------------------- #


def tail(trades: list[Trade]) -> str:
    """Die vier vorab angemeldeten Rand-Kennzahlen, in einer Zeile.

    Vorab festgelegt heisst: diese vier und nicht die, die nach dem Lauf gut
    aussehen. E10 lieferte einen besseren Mittelwert bei dreifachem
    schlimmstem Verlust und wurde deshalb verworfen -- ohne den Rand waere es
    als Erfolg durchgegangen.
    """
    values = np.array([t.r for t in trades], dtype="float64")
    below = float((values < -1.0).mean())
    worst = float(values.min())
    quantile = float(np.percentile(values, 5))

    armed = [t for t in trades if t.stop_moved]
    if armed:
        cut = sum(1 for t in armed if t.scratched) / len(armed)
        scratch = f"abgeschnitten {cut:.1%} von {len(armed)} scharfen"
    else:
        scratch = "abgeschnitten n/a (Regel aus)"

    return (
        f"unter -1R {below:.1%}  schlimmster {worst:+.2f} R  "
        f"5%-Quantil {quantile:+.2f} R  {scratch}"
    )


def halves(trades: list[Trade]) -> tuple[list[float], list[float]]:
    """Die Stichprobe nach Eroeffnungszeit in zwei Haelften geteilt.

    Nach der ZEIT, nicht nach der Reihenfolge in der Liste: die Liste ist nach
    Markt gruppiert, und eine Teilung darin waere eine Teilung nach Maerkten,
    also genau nicht die zeitliche Replikation, die angemeldet ist.
    """
    ordered = sorted(trades, key=lambda t: t.opened_ts)
    middle = len(ordered) // 2
    return (
        [t.r for t in ordered[:middle]],
        [t.r for t in ordered[middle:]],
    )


def report(results: dict[str, list[Trade]], order: list[str]) -> None:
    level = 1.0 - 0.05 / TOTAL_COMPARISONS
    print(
        f"Niveau {100 * level:.3f}%  ({TOTAL_COMPARISONS} angemeldete Vergleiche, "
        f"Bonferroni)\n"
    )

    base_label = order[0]
    base = results.get(base_label, [])
    if not base:
        print("  Keine Basis-Trades -- nichts zu vergleichen.")
        return

    for label in order:
        trades = results.get(label, [])
        if not trades:
            print(f"  {label:22s} keine Trades")
            continue

        values = [t.r for t in trades]
        own = block_bootstrap(values, level=level)
        mean = float(np.mean(values))
        line = f"  {label:22s} n={len(values):5d}  {mean:+.4f} R"
        print(f"{line}  {own.labelled() if own else '(zu wenige Trades)'}")
        print(f"  {'':22s} {tail(trades)}")

        if label == base_label:
            print()
            continue

        # --- Tor 1: korrigiertes Intervall auf der Differenz, ungepaart ---
        diff = two_group_difference([t.r for t in trades], [t.r for t in base], level=level)
        if diff is None:
            print(f"  {'':22s} Differenz: zu wenige Trades\n")
            continue
        gate_one = diff.excludes_zero and diff.tail_resolved
        print(f"  {'':22s} Differenz {diff.mean:+.4f} R  {diff.labelled()}")

        # --- Tor 2: Replikation ueber die Haelften ---
        early_new, late_new = halves(trades)
        early_base, late_base = halves(base)
        early = float(np.mean(early_new)) - float(np.mean(early_base))
        late = float(np.mean(late_new)) - float(np.mean(late_base))
        if abs(early) < NEAR_ZERO:
            ratio_text = "Replikation n/a (frühe Hälfte bei null)"
            gate_two = False
        else:
            ratio = late / early
            low, high = REPLICATION
            gate_two = low <= ratio <= high
            ratio_text = (
                f"Replikation {ratio:+.2f}x  (früh {early:+.4f}, spät {late:+.4f})"
            )
        print(f"  {'':22s} {ratio_text}")

        verdict = (
            "BEIDE TORE" if gate_one and gate_two
            else f"gefallen (Intervall {'ja' if gate_one else 'nein'}, "
                 f"Replikation {'ja' if gate_two else 'nein'})"
        )
        print(f"  {'':22s} -> {verdict}\n")

    print(
        "Die Trade-Zahlen unterscheiden sich, weil ein früher beendeter Trade "
        "den nächsten\nEinstieg freigibt. Verglichen werden damit nicht dieselben "
        "Trades mit anderen\nAusstiegen, sondern zwei verschiedene Mengen -- "
        "darum ungepaart."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--at",
        type=float,
        nargs="*",
        default=[1.0, 0.5],
        help="move the stop to entry at these R multiples",
    )
    parser.add_argument("--symbol", action="append")
    parser.add_argument(
        "--cache", type=Path, default=CACHE,
        help="JSONL-Zwischenspeicher; fertige (Regel, Markt)-Paare werden übersprungen",
    )
    parser.add_argument(
        "--only-report", action="store_true",
        help="nichts rechnen, nur den Zwischenspeicher auswerten",
    )
    args = parser.parse_args()

    symbols = args.symbol or list(load_config().engine.symbols.active)
    rules: list[tuple[str, float | None]] = [("ohne (original)", None)]
    rules += [(f"Einstand bei {at:g} R", at) for at in args.at]
    order = [label for label, _ in rules]

    done = load_cache(args.cache)
    results: dict[str, list[Trade]] = {label: [] for label in order}

    if args.only_report:
        # Die Maerkte kommen aus dem ZWISCHENSPEICHER, nicht aus der
        # Konfiguration.
        #
        # Umgekehrt war es zuerst, und eine Probe mit einem erfundenen Markt
        # hat es sofort gefangen: liegt im Speicher ein Symbol, das nicht
        # mehr in `symbols.active` steht, schnitt der Schnitt alles weg und
        # der Bericht sagte "Niveau 99.925%" ueber null Trades. Genau die
        # Bauart, die dieses Projekt schon zweimal bezahlt hat -- eine
        # Auswertung ueber eine leere Menge druckt ein zuversichtliches
        # Nichts.
        cached = sorted({symbol for _, symbol in done})
        print(f"Nur Bericht: {len(done)} Paare, {len(cached)} Märkte aus "
              f"{args.cache.name}")
        for (label, _symbol), trades in done.items():
            if label in results:
                results[label].extend(trades)
        missing = [label for label in order if not results[label]]
        if missing:
            print(f"  ! ohne Zeilen im Speicher: {', '.join(missing)}")
    else:
        print(f"{len(symbols)} Märkte x {len(rules)} Regeln", flush=True)
        if done:
            print(f"  {len(done)} Paare schon im Zwischenspeicher", flush=True)
        for label, at in rules:
            for symbol in symbols:
                key = (label, symbol)
                if key in done:
                    results[label].extend(done[key])
                    continue
                trades = run(symbol, at)
                append_cache(args.cache, label, symbol, trades)
                results[label].extend(trades)
                print(f"  {label:22s} {symbol:10s} {len(trades):4d} Trades", flush=True)

    print()
    report(results, order)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
