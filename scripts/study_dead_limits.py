"""Was würde es kosten, die drei toten Sicherungen scharfzuschalten?

    python scripts/study_dead_limits.py

**Anlass.** Das Audit vom 10.10.2026 hat belegt, dass drei von sechs
Sicherungen in `config/risk.yaml` **in keinem laufenden Prozess auslösen
können**: `max_daily_loss_pct`, `max_weekly_loss_pct` und
`cooldown_after_consecutive_losses` lesen alle `AccountState.recent_trades`,
und jede der drei Stellen, die einen `AccountState` baut, übergibt `[]`
(`run_live.py:120-127`, `run_dashboard.py:222-229`, `api/app.py:176`). Dazu
wird `max_open_positions` im Papierpfad nie geprüft, weil der Händler
`sim/plan.py:assess()` ruft und das keine offenen Positionen entgegennimmt.

Die Konfiguration beschreibt also ein Verhalten, das es nicht gibt. Das zu
reparieren ist richtig — und es **verändert, welche Trades entstehen**, also
schneidet es die Vorwärtsstichprobe. Dieses Skript beziffert, wie teuer der
Schnitt wäre, statt darüber zu mutmassen.

**Die Mehrdeutigkeit, die dabei auffällt, und sie ist selbst ein Befund.** Die
Konfiguration sagte nicht, ob die Grenzen **je Konto** oder **über das
Portfolio** gelten. Zur Zeit dieser Messung führte der Papierhandel zwölf
getrennte Händler mit je 1 000 USDT und einem Positionsplatz; je Konto konnte
`max_open_positions: 2` darum gar nicht binden, über das Portfolio hätte es
bei vier gleichzeitig offenen Positionen gebunden. Beide Lesarten werden hier
gerechnet.

**Nachtrag, 14.10.2026: die Frage ist entschieden, und zwar für das
Portfolio.** Seit dem 13.10.2026 zieht der Papierhandel aus EINER Kasse, und
`live/book.py` setzt `max_open_positions` über alle Märkte durch. Die untere
der beiden Lesarten ist seitdem die wirkliche; die obere beschreibt, wie es
war. Die Zahlen dieses Skripts bleiben richtig für die Population, über die
sie gerechnet wurden — geändert hat sich, welche Spalte die Gegenwart ist.

**Was dieses Skript NICHT kann.** Es prüft die *genommenen* Trades gegen die
Regeln. Eine blockierte Order gibt ihren Platz frei, und ein echter Neulauf
nähme danach andere Trades — die Zahl unten ist also eine Untergrenze für die
Veränderung, nicht die Veränderung selbst. Dieselbe Einschränkung wie bei
jeder nachträglichen Filterrechnung in diesem Projekt.

Nur lesen. Keine Datei in `data/` wird angefasst.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config

DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000


@dataclass(frozen=True)
class Trade:
    symbol: str
    opened_ts: int
    closed_ts: int
    r_multiple: float
    net_pnl: float


def load(source: str) -> list[Trade]:
    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'journal.sqlite'}?mode=ro", uri=True)
    where = "source = 'live'" if source == "live" else "source != 'live'"
    rows = conn.execute(
        "SELECT symbol, opened_ts, closed_ts, r_multiple, net_pnl FROM trades "
        f"WHERE {where} AND closed_ts IS NOT NULL ORDER BY opened_ts"
    ).fetchall()
    return [Trade(*row) for row in rows]


def would_block(
    trades: list[Trade], config: object, *, portfolio: bool, start_equity: float
) -> dict[str, list[Trade]]:
    """Welche Trades hätte jede Regel beim Eröffnen geblockt?

    Chronologisch durchgegangen, und jede Regel wird gegen den Stand
    *unmittelbar vor* dem Eröffnen geprüft -- genau so, wie `RiskLimits.check`
    es täte. Die Trades bleiben dabei alle im Lauf: ein geblockter Trade wird
    gezählt, aber nicht entfernt, weil sonst die Reihenfolge der
    Folgeentscheidungen eine andere wäre und das Ergebnis eine Simulation
    statt einer Zählung.
    """
    limits = config.risk.limits  # type: ignore[attr-defined]
    hits: dict[str, list[Trade]] = {
        "max_open_positions": [],
        "max_daily_loss_pct": [],
        "max_weekly_loss_pct": [],
        "cooldown_after_consecutive_losses": [],
    }

    for trade in trades:
        at = trade.opened_ts
        # Der Umfang, gegen den gerechnet wird: alles, oder nur dieser Markt.
        scope = trades if portfolio else [t for t in trades if t.symbol == trade.symbol]
        closed_before = [t for t in scope if t.closed_ts <= at]
        open_now = [t for t in scope if t.opened_ts < at < t.closed_ts]

        if len(open_now) >= limits.max_open_positions:
            hits["max_open_positions"].append(trade)

        day = sum(t.net_pnl for t in closed_before if t.closed_ts >= at - DAY_MS)
        if -day >= start_equity * limits.max_daily_loss_pct:
            hits["max_daily_loss_pct"].append(trade)

        week = sum(t.net_pnl for t in closed_before if t.closed_ts >= at - 7 * DAY_MS)
        if -week >= start_equity * limits.max_weekly_loss_pct:
            hits["max_weekly_loss_pct"].append(trade)

        run = 0
        for past in sorted(closed_before, key=lambda t: t.closed_ts, reverse=True):
            if past.net_pnl >= 0:
                break
            run += 1
        if run >= limits.cooldown_after_consecutive_losses:
            losses = [t.closed_ts for t in closed_before if t.net_pnl < 0]
            if losses and (at - max(losses)) / HOUR_MS < limits.cooldown_hours:
                hits["cooldown_after_consecutive_losses"].append(trade)

    return hits


def tell(label: str, trades: list[Trade], hits: dict[str, list[Trade]]) -> None:
    blocked = {t.opened_ts for rule in hits.values() for t in rule}
    kept = [t for t in trades if t.opened_ts not in blocked]
    print(f"\n  {label}")
    print("  " + "-" * 68)
    for rule, hit in hits.items():
        share = 100.0 * len(hit) / len(trades) if trades else 0.0
        print(f"    {rule:34s} blockt {len(hit):>4} von {len(trades)}  ({share:4.1f} %)")
    print(f"    {'zusammen (ohne Doppelzaehlung)':34s}        {len(blocked):>4}")
    if kept:
        mean = sum(t.r_multiple for t in kept) / len(kept)
        wins = sum(1 for t in kept if t.r_multiple > 0)
        before = sum(t.r_multiple for t in trades) / len(trades)
        print(f"\n    Mittel vorher  {before:+.4f} R ueber {len(trades)} Trades")
        print(f"    Mittel nachher {mean:+.4f} R ueber {len(kept)} Trades, "
              f"Treffer {wins}/{len(kept)} = {100 * wins / len(kept):.1f} %")
    else:
        print("\n    Jeder Trade waere geblockt worden.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="live", choices=["live", "replay"])
    args = parser.parse_args()

    config = load_config(ROOT / "config")
    limits = config.risk.limits
    trades = load(args.source)
    if not trades:
        print("Keine Trades.")
        return 1

    start_equity = config.engine.simulation.initial_equity
    first = dt.datetime.fromtimestamp(trades[0].opened_ts / 1000, dt.UTC)
    last = dt.datetime.fromtimestamp(trades[-1].closed_ts / 1000, dt.UTC)

    print("=" * 74)
    print("Was wuerde das Scharfschalten der toten Sicherungen kosten?")
    print("=" * 74)
    print(f"\n  Quelle   : {args.source}, {len(trades)} geschlossene Trades")
    print(f"  Zeitraum : {first:%d.%m. %H:%M} bis {last:%d.%m. %H:%M} UTC")
    print(f"  Grenzen  : max_open_positions {limits.max_open_positions}, "
          f"Tag {limits.max_daily_loss_pct:.0%}, Woche {limits.max_weekly_loss_pct:.0%}, "
          f"Cooldown nach {limits.cooldown_after_consecutive_losses} "
          f"({limits.cooldown_hours}h)")
    print(f"  Konto    : {start_equity:,.0f} USDT je Markt "
          f"(Lage zur Zeit der gemessenen Trades; seit 13.10.2026 EIN Konto)")

    tell("JE KONTO -- so, wie der Papierhandel bis zum 13.10.2026 gebaut war "
         "(zwoelf Haendler, ein Platz)",
         trades, would_block(trades, config, portfolio=False, start_equity=start_equity))
    tell("UEBER DAS PORTFOLIO -- so, wie es seit dem 13.10.2026 wirklich ist",
         trades, would_block(trades, config, portfolio=True, start_equity=start_equity))

    print("\n  Die Konfiguration sagt nicht, welche der beiden Lesarten gilt.")
    print("  Das ist kein Detail: je Konto kann max_open_positions gar nicht")
    print("  binden, ueber das Portfolio bindet es sofort.\n")
    print("  UNTERGRENZE, nicht die Veraenderung: eine blockierte Order gibt")
    print("  ihren Platz frei, und ein echter Neulauf naehme danach andere")
    print("  Trades. Gezaehlt ist, was die Regeln an den GENOMMENEN Trades")
    print("  tun -- nicht, was sie erzeugt haetten.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
