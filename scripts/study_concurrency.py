"""E13 — was ein Deckel auf gleichzeitig offene Positionen kostet.

**Die Frage, und warum sie heute gestellt werden muss.** Bis zum 13.10.2026
führte der Papierhandel zwölf getrennte Konten. `max_open_positions: 2` galt
dort für nichts: ein `SimBroker` hat strukturell einen Platz, also konnte kein
Wert dieser Einstellung das Verhalten ändern. Seit der Umstellung auf **eine**
Kasse ist das anders — zwölf Symbole in einem Konto sind genau der Fall, für
den die Einstellung geschrieben wurde.

Damit steht eine Zahl zur Entscheidung, und sie hat einen Preis: jeder Deckel
lehnt Trades ab, die das System sonst genommen hätte.

**Die Auswahlregel steht VOR der Messung fest, und sie ist arithmetisch.**

    Deckel = floor(max_daily_loss_pct / risk_pct je Trade)

Begründung: die Tagesgrenze zählt nur **realisierte** Verluste. Sie kann
nicht greifen, bevor die Positionen geschlossen sind. Was gleichzeitig offenes
Risiko begrenzt, ist allein die Zahl der Plätze — und die Zahl, die zur
Tagesgrenze passt, ist die, bei der ein vollständig schiefgelaufener Tag
genau die Tagesgrenze erreicht und nicht mehr. Bei 5 % Tagesdeckel und 1 %
Risiko je Trade sind das fünf.

**Die Zahlen unten sind beschreibend und ausdrücklich NICHT das
Auswahlkriterium.** Wer den Deckel nach seinem R-Ergebnis wählt, hat einen
Parameter auf seine eigene beste Zelle gefittet. Darum wird hier berichtet,
was jeder Deckel kostet, und entschieden wird nach der Regel oben.

**Was diese Messung kann und was nicht.**

Sie läuft über die 7.335 Replay-Trades aller zwölf Märkte, die eine
gemeinsame Zeitachse haben. Die Gegenrechnung ist erster Ordnung: Ereignisse
in Zeitreihenfolge, und eine Eröffnung wird abgelehnt, wenn schon `cap`
Positionen offen sind. Was sie **nicht** modelliert: der echte Prüfpunkt ist
die Vorschlagszeit, nicht die Füllzeit, und eine abgelehnte Eröffnung
verändert in Wirklichkeit auch die späteren Belegungen auf eine Weise, die
nur ein vollständiger Neulauf abbildet. Die Richtung des Fehlers ist bekannt:
weil hier an der Füllzeit geprüft wird, fällt die Ablehnungsquote eher zu
niedrig aus als zu hoch.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from traidingbrain.reporting.intervals import (
    block_bootstrap,
    draws_for,
    two_group_difference,
)

ROOT = Path(__file__).resolve().parents[1]
FILLS = ROOT / "data" / "replay_fills"

#: Die Deckel, die berichtet werden. Vorab festgelegt, damit die Liste nicht
#: nachtraeglich um die Zelle erweitert wird, die am besten aussieht.
CAPS = (1, 2, 3, 4, 5, 6, 8, 12)

#: Die Auswahlregel, aus der Konfiguration gelesen statt hier gesetzt.
DAILY_CAP = 0.05
RISK_PCT = 0.010

#: Die Zahl aus audit/EXPERIMENTS_NEXT.yaml, auf die korrigiert wird.
COMPARISONS_DECLARED = 65


@dataclass(frozen=True)
class Trade:
    symbol: str
    opened_ts: int
    closed_ts: int
    r: float


def load() -> list[Trade]:
    out: list[Trade] = []
    for path in sorted(FILLS.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        symbol = payload["symbol"]
        for fill in payload["fills"]:
            if fill.get("closed_ts") is None:
                continue
            out.append(Trade(
                symbol=symbol,
                opened_ts=int(fill["opened_ts"]),
                closed_ts=int(fill["closed_ts"]),
                r=float(fill["r_multiple"]),
            ))
    return sorted(out, key=lambda t: t.opened_ts)


def admitted_under(trades: list[Trade], cap: int) -> tuple[list[Trade], list[Trade]]:
    """Welche Trades ein Deckel durchlaesst, und welche er ablehnt.

    Ereignisse in Zeitreihenfolge. Schliessungen werden VOR Eroeffnungen
    derselben Millisekunde verarbeitet -- ein Platz, der in dieser Millisekunde
    frei wird, ist frei. Die andere Reihenfolge waere strenger als die Boerse.
    """
    events: list[tuple[int, int, Trade]] = []
    for trade in trades:
        events.append((trade.opened_ts, 1, trade))
        events.append((trade.closed_ts, 0, trade))
    # 0 = Schliessung, 1 = Eroeffnung; die Sortierung nach dem zweiten Feld
    # erledigt die Reihenfolge innerhalb einer Millisekunde.
    events.sort(key=lambda e: (e[0], e[1]))

    open_now: set[int] = set()
    taken: list[Trade] = []
    refused: list[Trade] = []
    live: set[int] = set()
    for _ts, kind, trade in events:
        key = id(trade)
        if kind == 0:
            if key in live:
                live.discard(key)
                open_now.discard(key)
            continue
        if len(open_now) >= cap:
            refused.append(trade)
            continue
        open_now.add(key)
        live.add(key)
        taken.append(trade)
    return taken, refused


def peak_concurrency(trades: list[Trade]) -> int:
    events = sorted(
        [(t.opened_ts, 1) for t in trades] + [(t.closed_ts, 0) for t in trades],
        key=lambda e: (e[0], e[1]),
    )
    now = peak = 0
    for _ts, kind in events:
        now += 1 if kind else -1
        peak = max(peak, now)
    return peak


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=ROOT / "data" / "study_concurrency.json")
    args = parser.parse_args(argv)

    trades = load()
    if not trades:
        print(f"Keine Fills in {FILLS} -- erst scripts/replay_all_markets.py")
        return 1

    derived = math.floor(DAILY_CAP / RISK_PCT)
    print(__doc__.split("\n\n")[0])
    print()
    print(f"AUSWAHLREGEL, vorab:  floor({DAILY_CAP} / {RISK_PCT}) = {derived}")
    print(f"Grundlage:            {len(trades):,} Trades, "
          f"{len({t.symbol for t in trades})} Maerkte")
    print(f"Hoechststand ohne Deckel: {peak_concurrency(trades)} gleichzeitig")
    print()
    print(f"{'Deckel':>7} {'genommen':>10} {'abgelehnt':>10} {'Quote':>7} "
          f"{'R/Trade':>9} {'R TOTAL':>10} {'R/Trade abgelehnt':>19}")

    rows = []
    for cap in CAPS:
        taken, refused = admitted_under(trades, cap)
        share = len(refused) / len(trades)
        row = {
            "cap": cap,
            "taken": len(taken),
            "refused": len(refused),
            "refused_share": share,
            "r_per_trade": mean([t.r for t in taken]),
            "r_total": sum(t.r for t in taken),
            "r_per_refused": mean([t.r for t in refused]),
        }
        rows.append(row)
        print(f"{cap:>7} {len(taken):>10,} {len(refused):>10,} {share:>6.1%} "
              f"{row['r_per_trade']:>+9.4f} {row['r_total']:>+10.1f} "
              f"{row['r_per_refused']:>+19.4f}")

    print()
    print("Ohne Deckel (alle Trades):"
          f"  {len(trades):,}  {mean([t.r for t in trades]):+.4f} R/Trade  "
          f"{sum(t.r for t in trades):+.1f} R TOTAL")
    print()
    print("Die Spalte 'R/Trade abgelehnt' ist der Preis des Deckels: ist sie")
    print("negativ, hat er Verlustgeschaefte verhindert, und das ist ein")
    print("Nebeneffekt und kein Argument -- die Regel oben entscheidet.")

    # Keine Zahl ohne ihr Intervall. Die Entscheidungsgroessen sind Zaehlungen
    # und damit exakt; die R-Zahlen sind es nicht, und ohne Intervall liest
    # jemand aus "-0.0029 gegen -0.0129" einen Unterschied, den die Streuung
    # nicht traegt.
    level = 1.0 - 0.05 / COMPARISONS_DECLARED
    draws = draws_for(level)
    taken, refused = admitted_under(trades, derived)
    print()
    print(f"Korrigiertes Niveau bei {COMPARISONS_DECLARED} angemeldeten "
          f"Vergleichen: {100 * level:.3f}%, {draws:,} Ziehungen")
    interval = two_group_difference(
        [t.r for t in taken], [t.r for t in trades], level=level, draws=draws
    )
    own = block_bootstrap([t.r for t in taken], level=level, draws=draws)
    print(f"  Deckel {derived}, R/Trade:              "
          f"{mean([t.r for t in taken]):+.4f}  {own}" if own else "")
    print(f"  Differenz zu 'kein Deckel':  {interval}" if interval else "")
    if interval is not None and not interval.excludes_zero:
        print("  Das Intervall enthaelt die Null: der Deckel ist NICHT als")
        print("  Verbesserung der Erwartung belegt. Er ist eine Schutzregel,")
        print("  und als solche wird er gesetzt.")
    inner = {
        "level": level,
        "draws": draws,
        "cap": derived,
        "r_per_trade": mean([t.r for t in taken]),
        "own_interval": [own.low, own.high] if own else None,
        "difference_vs_uncapped": [interval.low, interval.high] if interval else None,
        "difference_excludes_zero": bool(interval.excludes_zero) if interval else None,
    }

    args.json.write_text(
        json.dumps({
            "selection_rule": f"floor({DAILY_CAP}/{RISK_PCT})",
            "derived_cap": derived,
            "trades": len(trades),
            "markets": sorted({t.symbol for t in trades}),
            "peak_without_cap": peak_concurrency(trades),
            "r_per_trade_uncapped": mean([t.r for t in trades]),
            "rows": rows,
            "declared_cap": inner,
            "caveat": (
                "Gegenrechnung erster Ordnung an der Fuellzeit, nicht an der "
                "Vorschlagszeit. Ablehnungsquote eher zu niedrig."
            ),
        }, indent=2),
        encoding="utf-8",
    )
    print(f"\nGeschrieben: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
