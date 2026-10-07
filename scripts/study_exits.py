"""E3: Macht eine andere Ausstiegspolitik auf DENSELBEN Einstiegen einen Unterschied?

    python scripts/study_exits.py
    python scripts/study_exits.py --symbols BTCUSDT,ETHUSDT

**Warum diese Frage ueberlebt hat, wo alle anderen fielen.** Der
Zustandsbericht schloss lange mit `net_r = (eingefangene Bewegung minus
Gebuehr) / Stop-Abstand`, daraus "Stop, Positionsgroesse und Hebel kuerzen
sich heraus", und daraus die Folgerung, jeder Vorschlag mit anderen Stops
sei arithmetisch erledigt.

Die Positionsgroesse kuerzt sich heraus. **Der Stop nicht.** Er steht im
Nenner, und -- der uebersehene Teil -- er verschiebt den
**Ausstiegszeitpunkt**. Ein Trade, der heute bei -1 R ausgestoppt wird und
danach gedreht haette, ist bei einem anderen Ausstieg ein anderer Trade:
andere Haltezeit, anderes Ergebnis, anderes Funding, andere Gebuehren.

`scripts/study_stop_path.py` hat gemessen, dass die Annahme "gleicher Pfad"
oft verletzt ist, und ausdruecklich festgehalten, dass es **keine**
Exit-Studie ist: "ob das in Summe hilft, kann nur ein vollstaendig neu
simulierter Pfad sagen (E3)". Das ist dieses Skript.

**Die drei Arme, vorab im Register angemeldet** (`comparisons: 3`):

* **E3.1** -- bisheriger Stop und Ziel, bisheriger Horizont. Die Basis.
* **E3.2** -- bisheriger Stop, **kein Ziel**, fester Zeitausstieg nach 24h.
* **E3.3** -- bisheriger Stop als Start, dann **2,0-ATR-Trailing**, kein
  Ziel, bisheriger Horizont als Deckel.

Zur Lesart von E3.2: das Register sagt "bisheriger Stop mit festem
Zeitausstieg (24h)" und laesst offen, ob das Ziel bleibt. Es bleibt **nicht
stehen** -- die bisherige Politik hat ohnehin einen Horizont, also waere
"Stop, Ziel und 24h" nur derselbe Arm mit kuerzerer Uhr und kein anderer
Ausstieg. Diese Auslegung steht hier, weil sie eine Auslegung ist.

Und die 2,0 ATR sind vorab festgelegt und werden nicht nachjustiert. ATR(14)
auf H1, Wilder-geglaettet, am Entscheidungsbalken -- wer nach dem Ergebnis
auf 1,5 oder 3,0 ausweicht, hat die Vorab-Registrierung weggeworfen.

**Gepaart, und das ist der ganze Punkt.** Jeder Arm sieht dieselben
Einstiege, und verglichen wird die **Differenz je Trade**. Ein
unverbundener Vergleich zweier Mittelwerte wuerde die Streuung der
Einstiege mitmessen, die beide Arme gemeinsam haben -- und die ist hier um
Groessenordnungen groesser als der Effekt, den wir suchen.

**Was auch ein positiver Befund hier nicht waere.** Diese Signale haben nie
um einen Platz konkurriert. Ein laengerer Haltezeitraum belegt Slots, die
ein anderer Trade gebraucht haette, und das sieht nur ein vollstaendiger
Portfolio-Replay. Das Register sagt es: "Gepaarter Mehrwert auf denselben
Entries, DANACH vollstaendige Portfolio-Simulation."
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.analysis.indicators import atr
from traidingbrain.config.settings import load_config
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.signals import SignalStore
from traidingbrain.journal.version import run_signature
from traidingbrain.learn.labels import Minutes, label_signal
from traidingbrain.reporting.intervals import block_bootstrap

#: Regeln, deren abgelehnte Signale hier NICHT mitlaufen.
#:
#: **Und das ist eine andere Population als in E1, mit Absicht.**
#: `study_meta_label.py` filtert nur `liquidation` und behaelt die von
#: Kosten- und Chance-Risiko-Regel abgelehnten Signale -- weil E1 fragt, ob
#: ein Modell Gewinner aus dem GANZEN Kandidatenpool picken kann, auch aus
#: denen, die die Risikoschicht verworfen hat.
#:
#: E3 fragt etwas anderes: ob eine andere Ausstiegspolitik die Trades
#: verbessert, die das System TATSAECHLICH NIMMT. Eine Ausstiegspolitik gilt
#: nur fuer eine Position, die es gibt; ein Signal, das an der Kostenregel
#: scheiterte, wird nie eroeffnet, und seinen Ausstieg zu variieren
#: beantwortet nichts.
#:
#: Preis dieser Wahl: auf BTC bleiben 203 von 2'552 Signalen (92% fallen an
#: den Regeln). Die Fallzahlen von E1 und E3 sind darum NICHT vergleichbar,
#: und wer sie nebeneinander liest, muss das wissen.
#:
#: Was dabei offen bleibt: ein Signal, das die Kostenregel verwirft, koennte
#: unter einem Trailing-Ausstieg annehmbar werden -- der erwartete
#: Kostenanteil haengt an der Haltedauer. Das waere aber eine andere
#: EINSTIEGS-Menge und wuerde die Paarung zerstoeren, auf der dieser Test
#: beruht. Es ist eine eigene Frage, nicht ein Nachbessern dieser.
SAFETY_RULES = {"liquidation", "chance_risiko", "kosten"}

#: Bisheriger Horizont, wie E1 ihn benutzt. Deckel fuer E3.1 und E3.3.
HORIZON_HOURS = 48

#: E3.2s Uhr. Vorab festgelegt, nicht nachjustiert.
TIME_EXIT_HOURS = 24

#: E3.3s Trail-Abstand in ATR. Vorab festgelegt. Nicht nachjustiert.
TRAIL_ATR = 2.0

#: Zeitebene, auf der die ATR gemessen wird. Das Register nennt die Zahl und
#: nicht die Ebene; H1 ist der Takt des Systems, und die Wahl steht hier,
#: damit sie eine Wahl bleibt und keine Annahme wird.
ATR_FRAME = Timeframe.H1
ATR_PERIOD = 14

#: Angemeldete Vergleichszahl des Gesamtregisters.
TOTAL_COMPARISONS = 46

HOUR_MS = 3_600_000
MIN_CASES = 200


@dataclass(frozen=True, slots=True)
class Outcome:
    """Was ein Arm auf einem Trade erzielte."""

    net_r: float
    minutes_held: int
    barrier: str


@dataclass(frozen=True, slots=True)
class Case:
    symbol: str
    decided_ts: int
    #: Ergebnis je Arm, nach Armnamen. Alle Arme sahen denselben Einstieg.
    by_arm: dict[str, Outcome]


def trail_exit(
    minutes: Minutes,
    *,
    side: Side,
    fill_price: float,
    fill_index: int,
    stop: float,
    trail: float,
    end: int,
) -> tuple[int, float] | None:
    """Erster Minutenindex, an dem ein mitlaufender Stop greift.

    Vektorisiert, weil es sich vektorisieren laesst: der Stop zum Zeitpunkt
    k haengt am laufenden Extrem bis k, und das ist
    `np.maximum.accumulate`. Eine Schleife ueber Millionen Minuten waere
    hier der Unterschied zwischen Sekunden und Stunden.

    Der Trail zieht nur in eine Richtung. Ein Stop, der mit dem Preis
    zuruecklaeuft, ist kein Stop.
    """
    start = fill_index + 1
    if end <= start:
        return None
    high = minutes.high[start:end]
    low = minutes.low[start:end]

    if side is Side.LONG:
        peak = np.maximum.accumulate(np.maximum(high, fill_price))
        level = np.maximum(peak - trail, stop)
        hit = low <= level
    else:
        trough = np.minimum.accumulate(np.minimum(low, fill_price))
        level = np.minimum(trough + trail, stop)
        hit = high >= level

    if not hit.any():
        return None
    k = int(np.argmax(hit))
    return start + k, float(level[k])


def replay(
    record: object,
    minutes: Minutes,
    spec: SymbolSpec,
    config: object,
    *,
    atr_value: float,
) -> dict[str, Outcome] | None:
    """Denselben Einstieg unter drei Ausstiegspolitiken."""
    side = record.side  # type: ignore[attr-defined]
    entry = float(record.entry)  # type: ignore[attr-defined]
    stop = float(record.stop)  # type: ignore[attr-defined]
    target = float(record.target)  # type: ignore[attr-defined]
    decided = int(record.decided_ts)  # type: ignore[attr-defined]
    sim = config.engine.simulation  # type: ignore[attr-defined]
    expiry = sim.entry_expiry_bars * timeframe_ms(config.engine.timeframes.signal)  # type: ignore[attr-defined]

    # E3.1 -- die Basis, unveraendert.
    base = label_signal(
        side=side, entry=entry, stop=stop, target=target, decision_ts=decided,
        minutes=minutes, spec=spec, config=sim,
        horizon_ms=HORIZON_HOURS * HOUR_MS, expiry_ms=expiry,
    )
    if not base.resolved:
        return None

    # E3.2 -- Stop und Uhr, kein Ziel. Ein Ziel so weit weg, dass es nie
    # greift, ist der saubere Weg: dieselbe Funktion, dieselbe
    # Fill-Behandlung, nur eine Tuer weniger.
    far = entry * (100.0 if side is Side.LONG else 0.01)
    timed = label_signal(
        side=side, entry=entry, stop=stop, target=far, decision_ts=decided,
        minutes=minutes, spec=spec, config=sim,
        horizon_ms=TIME_EXIT_HOURS * HOUR_MS, expiry_ms=expiry,
    )
    if not timed.resolved:
        return None

    # E3.3 -- Trailing. Der Einstieg kommt aus der Basis, damit alle drei
    # Arme beim selben Fill beginnen; nur der Ausstieg unterscheidet sich.
    risk = abs(entry - stop)
    if risk <= 0 or atr_value <= 0:
        return None
    at = int(np.searchsorted(minutes.ts, base.filled_ts, side="left"))
    end = min(len(minutes.ts), int(np.searchsorted(
        minutes.ts, base.filled_ts + HORIZON_HOURS * HOUR_MS, side="right")))
    hit = trail_exit(
        minutes, side=side, fill_price=base.entry_price, fill_index=at,
        stop=stop, trail=TRAIL_ATR * atr_value, end=end,
    )
    sign = 1.0 if side is Side.LONG else -1.0
    if hit is None:
        # Horizont ausgelaufen: am Markt geschlossen, wie die Basis es tut.
        last = max(at + 1, end) - 1
        if last <= at:
            return None
        exit_price = float(minutes.open[last])
        held = last - at
        barrier = "zeit"
    else:
        index, level = hit
        exit_price = level
        held = index - at
        barrier = "trail"
    trail_cost = (base.entry_price * spec.maker_fee + exit_price * spec.taker_fee) / risk
    trailed = Outcome(
        net_r=sign * (exit_price - base.entry_price) / risk - trail_cost,
        minutes_held=held,
        barrier=barrier,
    )

    return {
        "E3.1 Stop und Ziel": Outcome(base.net_r, base.minutes_held, str(base.barrier)),
        "E3.2 Stop und 24h-Uhr": Outcome(timed.net_r, timed.minutes_held, str(timed.barrier)),
        "E3.3 Stop und 2.0-ATR-Trail": trailed,
    }


def build(symbols: list[str], *, signature: str) -> list[Case]:
    config = load_config()
    store = ParquetStore(config.engine.paths.data_dir / "ohlcv")
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")

    cases: list[Case] = []
    for symbol in symbols:
        records = signals.all(symbol=symbol, run_signature=signature)
        if not records:
            print(f"  {symbol:10s} keine Signale unter dieser Signatur")
            continue
        frame = store.read(symbol, config.engine.timeframes.execution)
        hourly = store.read(symbol, ATR_FRAME)
        if frame.empty or hourly.empty:
            print(f"  {symbol:10s} keine Minuten- oder H1-Daten")
            continue

        minutes = Minutes.of(frame)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        # ATR je H1-Balken, dann je Signal der letzte ABGESCHLOSSENE Balken
        # vor der Entscheidung. `searchsorted(..., "left") - 1` ist genau
        # das: der Balken, der zur Entscheidungszeit fertig vorlag.
        atr_series = atr(hourly, ATR_PERIOD).to_numpy(dtype=float)
        atr_ts = hourly["ts"].to_numpy(dtype="int64")

        started = time.perf_counter()
        kept = 0
        for record in records:
            if record.refused_by in SAFETY_RULES:
                continue
            j = int(np.searchsorted(atr_ts, record.decided_ts, side="left")) - 1
            if j < ATR_PERIOD or not np.isfinite(atr_series[j]):
                continue
            arms = replay(record, minutes, spec, config, atr_value=float(atr_series[j]))
            if arms is None:
                continue
            cases.append(Case(symbol=symbol, decided_ts=record.decided_ts, by_arm=arms))
            kept += 1
        print(f"  {symbol:10s} {len(records):6,d} Signale -> {kept:6,d} auf allen drei Armen "
              f"({time.perf_counter() - started:5.1f}s)")
    return sorted(cases, key=lambda c: c.decided_ts)


def judge(cases: list[Case], *, level: float) -> None:
    names = list(cases[0].by_arm)
    base = names[0]
    print(f"\n  {'Arm':30s} {'Netto-R':>9s} {'Haltezeit':>11s} "
          f"{'gepaarte Differenz zur Basis':>34s}")
    print("  " + "-" * 88)
    survivors: list[str] = []
    for name in names:
        values = [c.by_arm[name].net_r for c in cases]
        held = [c.by_arm[name].minutes_held for c in cases]
        line = (
            f"  {name:30s} {float(np.mean(values)):>+9.4f} "
            f"{float(np.mean(held)) / 60:>9.1f}h"
        )
        if name == base:
            print(line + f" {'(Basis)':>34s}")
            continue
        diff = [c.by_arm[name].net_r - c.by_arm[base].net_r for c in cases]
        interval = block_bootstrap(diff, level=level)
        if interval is None:
            print(line + f" {'kein Intervall':>34s}")
            continue
        good = interval.low > 0
        mark = " *" if good else ""
        if good:
            survivors.append(name)
        print(line + f"  {float(np.mean(diff)):>+8.4f} "
                     f"[{interval.low:+.4f}, {interval.high:+.4f}]{mark}")

    print("\n  Ausstiegsgrund je Arm:")
    for name in names:
        counts: dict[str, int] = {}
        for c in cases:
            counts[c.by_arm[name].barrier] = counts.get(c.by_arm[name].barrier, 0) + 1
        share = "  ".join(
            f"{k} {100 * v / len(cases):.1f}%" for k, v in sorted(counts.items())
        )
        print(f"    {name:30s} {share}")

    print("\n" + "=" * 92)
    print("  Abnahme, vorab festgelegt")
    print("=" * 92)
    def mean_of(name: str) -> float:
        return float(np.mean([c.by_arm[name].net_r for c in cases]))

    positive = [n for n in names if mean_of(n) > 0]
    print(
        f"\n  (a) gepaarter Mehrwert mit korrigiertem Intervall ohne Null: "
        f"{', '.join(survivors) if survivors else 'KEINER'}\n"
        f"  (b) absolut netto positiv: {', '.join(positive) or 'KEINER'}"
    )
    absolute = [n for n in survivors if mean_of(n) > 0]
    print(f"\n  -> {'KANDIDAT: ' + ', '.join(absolute) if absolute else 'NICHT BELEGT'}")
    print(
        "\n  Und was auch ein bestandener Arm hier nicht waere: diese Signale haben\n"
        "  nie um einen Platz konkurriert. Ein laengerer Halt belegt Slots, die ein\n"
        "  anderer Trade gebraucht haette -- das sieht nur ein vollstaendiger\n"
        "  Portfolio-Replay, und das Register verlangt ihn ausdruecklich DANACH."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="")
    args = parser.parse_args()

    config = load_config()
    signature = run_signature(config)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or list(
        config.engine.symbols.active
    )
    corrected = 1.0 - 0.05 / TOTAL_COMPARISONS

    print("=" * 92)
    print("E3 -- veraendert eine andere Ausstiegspolitik das Ergebnis?")
    print("=" * 92)
    print(
        f"\n  Signatur   {signature}\n"
        f"  Arme       E3.1 Stop+Ziel ({HORIZON_HOURS}h)  |  "
        f"E3.2 Stop+{TIME_EXIT_HOURS}h-Uhr, kein Ziel  |  "
        f"E3.3 Stop+{TRAIL_ATR}-ATR-Trail\n"
        f"  ATR        {ATR_PERIOD} Perioden auf {ATR_FRAME.value}, am letzten "
        f"abgeschlossenen Balken vor der Entscheidung\n"
        f"  Niveau     {100 * corrected:.3f}% ({TOTAL_COMPARISONS} angemeldete Vergleiche)\n"
        f"  Gepaart    jeder Arm sieht dieselben Einstiege\n"
    )

    cases = build(symbols, signature=signature)
    if len(cases) < MIN_CASES:
        raise SystemExit(f"Nur {len(cases)} Faelle auf allen drei Armen -- zu wenig.")
    print(f"\n  {len(cases):,} Faelle, auf allen drei Armen aufgeloest.")
    judge(cases, level=corrected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
