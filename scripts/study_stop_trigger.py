"""E10 -- der Stop-AUSLOESER: Beruehrung gegen Schlusskurs.

    python scripts/study_stop_trigger.py --markets BTCUSDT,ETHUSDT,SOLUSDT

**Warum diese Frage.** Das Journal zaehlt selbst, wie oft ein Stop von einem
Docht geholt wird, dessen Kerze danach wieder auf der richtigen Seite
schliesst -- `post_mortem.stopped_by_wick`. Ueber 2.749 Trades sind das
**967: 35.2 % aller Trades und 51.9 % aller Stops.** Das ist die groesste
einzelne Population dieses Projekts, die noch nie als eigene Politik geprueft
wurde.

**Warum das nicht schon gemessen ist.** E3 hat Ausgangs-*Politiken* geprueft
(24h-Uhr, 2.0-ATR-Trail), `study_widen_stop.py` die *Weite* des Stops. Beide
lassen den **Ausloeser** unangetastet: der Stop greift bei Beruehrung. Ein
schlusskurs-bestaetigter Stop laesst den Stop, wo er ist, und verlangt eine
Bestaetigung. Das ist eine dritte Sache.

**Und die Rechnung, die man hier NICHT machen darf.** Aus dem Journal laesst
sich ausrechnen: ohne die 967 Docht-Stops waere das System +0.4151 R je Trade
statt -0.0865. Diese Zahl ist **bedeutungslos**. Man darf die Verlierer nicht
entfernen und den Rest behalten -- und ein anderer Stop-Ausloeser aendert den
Pfad *aller* Trades, nicht nur der unerwuenschten. Nur ein neu simulierter
Pfad entscheidet. Genau dafuer ist dieses Skript da.

**Zwei Sicherungen, die ein naiver Test vergisst** (vorab angemeldet in
audit/EXPERIMENTS_NEXT.yaml, Arm E10):

1. **Liquidation greift weiter bei Beruehrung.** Die Boerse wartet auf keinen
   Schlusskurs. Ohne das waere der Arm eine Fiktion, in der man Verluste
   aussitzt, die ein echtes Konto nicht aussitzen kann -- und der Hebel ist so
   gesetzt, dass die Liquidation nur 2.5 Stop-Abstaende hinter dem Stop liegt.
2. **Die Verlustverteilung wird berichtet, nicht nur der Mittelwert.** Ein
   Stop, der auf einen Schlusskurs wartet, kann mehr als 1R verlieren. Anteil
   unter -1R, schlimmster Einzelverlust und Zahl der Liquidationen gehoeren in
   den Bericht -- sonst ist ein besserer Mittelwert eine Taeuschung ueber den
   Rand der Verteilung.

**Dieser Arm aendert die Bedeutung von `risk_amount`:** der geplante Verlust
ist nicht mehr der tatsaechliche Hoechstverlust. Das beruehrt die harte
3-%-Grenze und laeuft deshalb ausschliesslich im Simulator, als
Stressszenario -- nicht als Vorschlag fuer die Risk Engine.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.signals import Action, SignalStore
from traidingbrain.learn.labels import Minutes, label_signal
from traidingbrain.reporting.intervals import paired_difference
from traidingbrain.risk.leverage import liquidation_price

#: Dieselbe Signatur, auf der E1 und E3 rechnen.
SIGNATURE = "1000.0|['A', 'B', 'E', 'F', 'G']|0.08|M15|refused-v1"

#: Derselbe Horizont wie in E3, damit die Zahlen vergleichbar sind.
HORIZON_HOURS = 48
HOUR_MS = 3_600_000

#: Bonferroni auf die 50 angemeldeten Vergleiche.
COMPARISONS = 50
LEVEL = 1.0 - 0.05 / COMPARISONS

#: Unter so vielen Paaren kein Intervall.
MIN_PAIRS = 100

#: Darunter gilt eine Differenz als null und das Replikationsverhaeltnis
#: als nicht berechenbar -- sonst teilt man durch Rauschen.
NEAR_ZERO = 1e-9

#: Fenstergrenzen aus `meta.windows` der Registrierung, fuer Tor 2.
DEV_TO_MS = 1774915200000     # 2026-03-31 24:00 UTC
CONFIRM_FROM_MS = 1774915200000


@dataclass(frozen=True, slots=True)
class Outcome:
    net_r: float
    minutes_held: int
    barrier: str


def confirmed_stop_exit(
    minutes: Minutes,
    closes_all: np.ndarray,
    *,
    side: Side,
    fill_price: float,
    fill_index: int,
    stop: float,
    target: float,
    liq: float,
    end: int,
    frame_ms: int,
) -> tuple[int, float, str]:
    """Ausstieg, wenn eine Signalkerze JENSEITS des Stops schliesst.

    Drei Tueren, und die frueheste gewinnt:

      * **Liquidation bei Beruehrung** -- die Boerse wartet nicht.
      * **Ziel bei Beruehrung** -- unveraendert gegenueber der Basis.
      * **Stop bei Schlusskurs** -- erst wenn eine abgeschlossene Signalkerze
        jenseits des Stops schliesst, und dann zu diesem Schlusskurs.

    Laeuft keine der drei, wird am Horizont zum Marktpreis geschlossen, wie es
    die Basis auch tut.
    """
    start = fill_index + 1
    if end <= start:
        return fill_index, fill_price, "kein_fenster"

    high = minutes.high[start:end]
    low = minutes.low[start:end]
    close = closes_all[start:end]
    stamps = minutes.ts[start:end]

    long = side is Side.LONG

    # Tuer 1: Liquidation, bei Beruehrung.
    liq_hit = (low <= liq) if long else (high >= liq)
    liq_at = int(np.argmax(liq_hit)) if liq_hit.any() else None

    # Tuer 2: Ziel, bei Beruehrung.
    tgt_hit = (high >= target) if long else (low <= target)
    tgt_at = int(np.argmax(tgt_hit)) if tgt_hit.any() else None

    # Tuer 3: Stop, nur auf einem Signalkerzen-SCHLUSS. Eine Signalkerze
    # endet, wenn die naechste Minute in ein neues Raster faellt -- so ist
    # der letzte Minutenschluss innerhalb der Kerze auch ihr Schluss.
    bucket = stamps // frame_ms
    last_of_bucket = np.empty(bucket.size, dtype=bool)
    last_of_bucket[:-1] = bucket[:-1] != bucket[1:]
    last_of_bucket[-1] = True
    beyond = (close < stop) if long else (close > stop)
    stop_hit = last_of_bucket & beyond
    stop_at = int(np.argmax(stop_hit)) if stop_hit.any() else None

    doors = [
        (liq_at, liq, "liquidation"),
        (tgt_at, target, "ziel"),
        (stop_at, None, "stop_bestaetigt"),
    ]
    live = [(at, price, name) for at, price, name in doors if at is not None]
    if not live:
        last = end - 1
        return start + (last - start), float(minutes.open[last]), "zeit"

    at, price, name = min(live, key=lambda d: d[0])
    # Ein bestaetigter Stop verlaesst zum Schlusskurs der Kerze, nicht am
    # Stop-Preis. Das ist der ganze Unterschied -- und er kann teurer sein.
    exit_price = float(close[at]) if price is None else float(price)
    return start + at, exit_price, name


def replay(
    record: object,
    minutes: Minutes,
    closes: np.ndarray,
    spec: SymbolSpec,
    config: object,
) -> dict[str, Outcome] | None:
    """Denselben Einstieg unter zwei Stop-Ausloesern."""
    side = record.side  # type: ignore[attr-defined]
    entry = float(record.entry)  # type: ignore[attr-defined]
    stop = float(record.stop)  # type: ignore[attr-defined]
    target = float(record.target)  # type: ignore[attr-defined]
    leverage = float(record.leverage)  # type: ignore[attr-defined]
    decided = int(record.decided_ts)  # type: ignore[attr-defined]
    sim = config.engine.simulation  # type: ignore[attr-defined]
    expiry = sim.entry_expiry_bars * timeframe_ms(config.engine.timeframes.signal)  # type: ignore[attr-defined]
    frame_ms = timeframe_ms(config.engine.timeframes.signal)  # type: ignore[attr-defined]

    base = label_signal(
        side=side, entry=entry, stop=stop, target=target, decision_ts=decided,
        minutes=minutes, spec=spec, config=sim,
        horizon_ms=HORIZON_HOURS * HOUR_MS, expiry_ms=expiry,
    )
    if not base.resolved:
        return None

    risk = abs(entry - stop)
    if risk <= 0 or leverage <= 0:
        return None

    at = int(np.searchsorted(minutes.ts, base.filled_ts, side="left"))
    end = min(len(minutes.ts), int(np.searchsorted(
        minutes.ts, base.filled_ts + HORIZON_HOURS * HOUR_MS, side="right")))
    liq = liquidation_price(side, base.entry_price, leverage, spec.maintenance_margin_rate)

    index, exit_price, barrier = confirmed_stop_exit(
        minutes, closes, side=side, fill_price=base.entry_price, fill_index=at,
        stop=stop, target=target, liq=liq, end=end, frame_ms=frame_ms,
    )
    if barrier == "kein_fenster":
        return None

    sign = 1.0 if side is Side.LONG else -1.0
    # Gebuehren wie im Broker: ein Ziel ruht im Buch und verdient Maker,
    # alles andere verlaesst zu Markt und zahlt Taker.
    exit_fee = spec.maker_fee if barrier == "ziel" else spec.taker_fee
    cost = (base.entry_price * spec.maker_fee + exit_price * exit_fee) / risk

    return {
        "E10.1 Stop bei Beruehrung": Outcome(base.net_r, base.minutes_held, str(base.barrier)),
        "E10.2 Stop bei Schlusskurs": Outcome(
            net_r=sign * (exit_price - base.entry_price) / risk - cost,
            minutes_held=index - at,
            barrier=barrier,
        ),
    }


def collect(symbols: list[str]) -> list[tuple[int, dict[str, Outcome]]]:
    config = load_config()
    store = ParquetStore(config.engine.paths.data_dir / "ohlcv")
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")

    cases: list[tuple[int, dict[str, Outcome]]] = []
    for symbol in symbols:
        # Nur genommene Signale. `Action` ist ein Enum -- auf seinen Wert zu
        # vergleichen hiesse, die deutsche Beschriftung zur Schnittstelle zu
        # machen, und ein abgelehntes Signal traegt ohnehin Hebel 0.
        records = [r for r in signals.all(symbol=symbol, run_signature=SIGNATURE)
                   if r.action is Action.TAKEN]
        if not records:
            print(f"  {symbol:10s} keine genommenen Signale")
            continue
        frame = store.read(symbol, Timeframe.M1)
        if frame.empty:
            print(f"  {symbol:10s} keine Minutendaten")
            continue
        minutes = Minutes.of(frame)
        closes = frame["close"].to_numpy(dtype="float64")
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        kept = 0
        for record in records:
            got = replay(record, minutes, closes, spec, config)
            if got is not None:
                cases.append((int(record.decided_ts), got))
                kept += 1
        print(f"  {symbol:10s} {kept:>5,} von {len(records):,} Signalen aufgeloest")
    return cases


def tail(values: list[float]) -> str:
    """Der linke Rand, der bei diesem Arm die eigentliche Frage ist."""
    arr = np.asarray(values, dtype=float)
    worse = float(np.mean(arr < -1.0))
    return (f"unter -1R {100 * worse:>5.1f} %   schlimmster {arr.min():+7.3f} R   "
            f"5%-Quantil {np.percentile(arr, 5):+7.3f} R")


def judge(cases: list[tuple[int, dict[str, Outcome]]], *, level: float) -> None:
    names = list(cases[0][1].keys())
    print(f"\n  {len(cases):,} gepaarte Faelle, Niveau {100 * level:.4f}% "
          f"(Bonferroni auf {COMPARISONS})\n")

    for name in names:
        rs = [c[1][name].net_r for c in cases]
        held = [c[1][name].minutes_held for c in cases]
        bars: dict[str, int] = {}
        for c in cases:
            bars[c[1][name].barrier] = bars.get(c[1][name].barrier, 0) + 1
        print(f"  {name}")
        print(f"    Mittel {np.mean(rs):+.4f} R   Haltezeit {np.mean(held) / 60:.1f}h")
        print(f"    {tail(rs)}")
        print("    Ausgaenge: " + ", ".join(f"{k} {v:,}" for k, v in sorted(bars.items())))

    base, other = names[0], names[1]
    pairs_a = [c[1][base].net_r for c in cases]
    pairs_b = [c[1][other].net_r for c in cases]
    diff = paired_difference(pairs_b, pairs_a, level=level)
    print(f"\n  GEPAARTE DIFFERENZ ({other} minus {base}):")
    if diff is None:
        print("    zu wenige Paare")
        return
    excl = diff.low > 0 or diff.high < 0
    print(f"    {diff.mean:+.4f} R  [{diff.low:+.4f}, {diff.high:+.4f}]   "
          f"Null {'AUSGESCHLOSSEN' if excl else 'enthalten'}")

    # Tor 2: dieselbe Differenz in zwei Zeitfenstern.
    early = [c for c in cases if c[0] < DEV_TO_MS]
    late = [c for c in cases if c[0] >= CONFIRM_FROM_MS]
    print(f"\n  Replikation: {len(early):,} frueher, {len(late):,} spaeter")
    ratios = []
    for label, group in (("frueher", early), ("spaeter", late)):
        if len(group) < MIN_PAIRS:
            print(f"    {label:8s} nur {len(group):,} Paare -- unter {MIN_PAIRS}")
            ratios.append(None)
            continue
        d = paired_difference([c[1][other].net_r for c in group],
                              [c[1][base].net_r for c in group], level=level)
        if d is None:
            ratios.append(None)
            continue
        print(f"    {label:8s} {d.mean:+.4f} R  [{d.low:+.4f}, {d.high:+.4f}]")
        ratios.append(d.mean)
    if all(r is not None for r in ratios) and abs(ratios[0]) > NEAR_ZERO:
        ratio = ratios[1] / ratios[0]
        band = "IM BAND" if 0.5 <= ratio <= 2.0 else "AUSSERHALB"  # noqa: PLR2004
        print(f"    Verhaeltnis {ratio:+.2f}x -- {band} (0.5-2.0)")
        if ratio < 0:
            print("    Negativ heisst Vorzeichenwechsel, nicht ein kleines Mass.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--level", type=float, default=LEVEL)
    args = parser.parse_args()

    print("=" * 84)
    print("E10 -- der Stop-Ausloeser: Beruehrung gegen Schlusskurs")
    print("=" * 84)
    print(
        "\n  Liquidation greift in BEIDEN Armen bei Beruehrung. Die Boerse\n"
        "  wartet auf keinen Schlusskurs, und der Hebel laesst nur 2.5\n"
        "  Stop-Abstaende Luft.\n"
        "\n  Der linke Rand der Verteilung steht neben jedem Mittelwert. Ein\n"
        "  besserer Mittelwert bei schwererem Rand ist kein Gewinn.\n"
    )

    symbols = [s.strip().upper() for s in args.markets.split(",") if s.strip()]
    cases = collect(symbols)
    if len(cases) < MIN_PAIRS:
        print(f"\n  Nur {len(cases)} Paare -- unter {MIN_PAIRS}. Kein Urteil.")
        return 0
    judge(cases, level=args.level)
    print(
        "\n" + "=" * 84 + "\n"
        "  Vorab festgelegt: dieser Arm aendert die Bedeutung von risk_amount --\n"
        "  der geplante Verlust ist nicht mehr der Hoechstverlust. Er laeuft\n"
        "  ausschliesslich im Simulator, als Stressszenario, und ist kein\n"
        "  Vorschlag fuer die Risk Engine."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
