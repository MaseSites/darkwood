"""Wie viele Trades passen ueberhaupt gleichzeitig? -- und was das am Ergebnis aendert.

**Die Luecke, die dieses Skript schliesst.** `run_plan_account.py` und
`study_plan_frontier.py` reihen die gespeicherten Trades hintereinander auf und
nehmen jeden. Das unterstellt, dass immer Platz war. War es nicht:

* Jede Position bindet `Margin-Anteil x Konto` an Margin. Bei 30 % passen
  **drei** Positionen ins Konto, die vierte findet nichts mehr
  (`sim/broker.py:500` lehnt genau so ab).
* `config/risk.yaml` deckelt zusaetzlich bei `max_open_positions`.

Und die Belegung ist nicht selten hoch: ueber die 7.335 gespeicherten Trades
waren **67,9 % der Zeit mehr als drei** Positionen gleichzeitig offen, in der
Spitze zwoelf. Eine Rechnung ohne Platzgrenze beschreibt also ein Konto, das
es nicht gibt.

**Welche Richtung der Fehler hat.** Weniger Trades heisst weniger Drift und
weniger Varianzabzug. Bei negativer Erwartung ist die unbeschraenkte Rechnung
also zu PESSIMISTISCH -- sie laedt Trades auf das Konto, die es nie haette
stellen koennen. Dieses Skript misst, wie gross der Unterschied ist, statt ihn
zu vermuten.

**Was es NICHT behauptet.** Dass die Beschraenkung eine Verbesserung sei. Sie
ist eine Tatsache der Buchhaltung, keine Strategie. Welche drei Positionen man
haelt, entscheidet die Ankunftsreihenfolge und nicht die Qualitaet -- die
Frage, ob ein zweiter Platz sich lohnt, ist anderswo gemessen worden und ihr
Unterschied schliesst null ein.

    python scripts/study_plan_slots.py
    python scripts/study_plan_slots.py --margin-anteil 0.10 --hebel 7
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.domain.enums import Side
from traidingbrain.risk.plansize import UnsizeablePlanError, plan_size

TAG_MS = 86_400_000
START = 1_000.0
BODEN = 0.01


@dataclass(slots=True)
class Offen:
    """Eine laufende Position: was sie bindet und was sie bringen wird."""

    zu_ts: int
    margin: float
    ergebnis: float


def lade(root: Path) -> list[dict[str, object]]:
    zeilen: list[dict[str, object]] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            row["symbol"] = blob["symbol"]
            zeilen.append(row)
    zeilen.sort(key=lambda r: int(r["opened_ts"]))
    return zeilen


def _stop(row: dict[str, object]) -> tuple[float, float, Side] | None:
    entry, qty = float(row["entry_price"]), float(row["qty"])
    if entry <= 0 or qty <= 0:
        return None
    seite = Side.SHORT if str(row["side"]).lower() == "short" else Side.LONG
    weite = float(row["risk_amount"]) / qty
    return entry, entry + weite if seite is Side.SHORT else entry - weite, seite


def lauf(
    fenster: list[dict[str, object]],
    *,
    anteil: float,
    hebel: float,
    max_offen: int | None,
    margin_pruefen: bool,
) -> tuple[float, int, int, int]:
    """Endstand, genommen, abgelehnt-Margin, abgelehnt-Platz.

    **Die Buchhaltung, die hier dazukommt.** Positionen werden erst beim
    SCHLIESSEN abgerechnet, nicht sofort; bis dahin ist ihre Margin gebunden
    und steht fuer nichts anderes zur Verfuegung. Genau daran scheitert die
    vierte Position bei 30 % Anteil.

    **Vereinfachung, benannt:** die Margin wird gegen das REALISIERTE Konto
    geprueft, nicht gegen eine laufende Marktbewertung. Die echte Boerse
    rechnet unrealisierte Gewinne mit, der Simulator fuehrt `reserved` gegen
    `equity`. Der Unterschied verschiebt den Zeitpunkt einer Ablehnung, nicht
    ihre Existenz -- und in die vorsichtige Richtung.
    """
    konto = START
    offen: list[Offen] = []
    genommen = abgelehnt_margin = abgelehnt_platz = 0

    for row in fenster:
        auf = int(row["opened_ts"])
        # Erst alles schliessen, was vor diesem Einstieg faellig war.
        for pos in sorted((p for p in offen if p.zu_ts <= auf), key=lambda p: p.zu_ts):
            konto = max(konto + pos.ergebnis, 0.0)
            offen.remove(pos)
        if konto <= START * BODEN:
            break

        if max_offen is not None and len(offen) >= max_offen:
            abgelehnt_platz += 1
            continue

        gelesen = _stop(row)
        if gelesen is None:
            continue
        entry, stop, seite = gelesen
        try:
            p = plan_size(equity=konto, margin_share=anteil, leverage=hebel,
                          entry=entry, stop=stop, side=seite)
        except UnsizeablePlanError:
            continue

        gebunden = sum(o.margin for o in offen)
        if margin_pruefen and p.margin > konto - gebunden:
            abgelehnt_margin += 1
            continue

        r = float(row["r_multiple"])
        ergebnis = -p.margin if (p.stop_beyond_liquidation and r < 0) else p.loss_at_stop * r
        offen.append(Offen(zu_ts=int(row["closed_ts"]), margin=p.margin, ergebnis=ergebnis))
        genommen += 1

    for pos in offen:
        konto = max(konto + pos.ergebnis, 0.0)
    return konto, genommen, abgelehnt_margin, abgelehnt_platz


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--margin-anteil", type=float, default=0.30)
    parser.add_argument("--hebel", type=float, default=7.0)
    parser.add_argument("--fenster-tage", type=int, default=30)
    parser.add_argument("--min-trades", type=int, default=20)
    args = parser.parse_args(argv)

    cfg = load_config()
    deckel = cfg.risk.limits.max_open_positions
    passen = int(1.0 / args.margin_anteil)

    trades = lade(args.fills)
    t0, t1 = int(trades[0]["opened_ts"]), int(trades[-1]["opened_ts"])
    fenster: list[list[dict[str, object]]] = []
    anfang = t0
    while anfang + args.fenster_tage * TAG_MS <= t1:
        f = [t for t in trades
             if anfang <= int(t["opened_ts"]) < anfang + args.fenster_tage * TAG_MS]
        if len(f) >= args.min_trades:
            fenster.append(f)
        anfang += args.fenster_tage * TAG_MS

    print(f"{args.margin_anteil:.0%} Margin x {args.hebel:g}x, {len(fenster)} Fenster "
          f"a {args.fenster_tage} Tage, Start {START:,.0f}\n")
    print(f"Bei {args.margin_anteil:.0%} Margin je Position passen {passen} Positionen "
          f"ins Konto.")
    print(f"Die Konfiguration deckelt bei {deckel}. Es greift also: "
          f"{min(passen, deckel)}.\n")

    varianten = (
        ("ohne jede Grenze", None, False),
        (f"nur Platzgrenze ({deckel})", deckel, False),
        ("nur Margin", None, True),
        (f"Margin UND Platz ({deckel})", deckel, True),
    )
    print(f"{'Variante':28s} {'Median':>8s} {'>1.0x':>7s} {'genommen':>9s} "
          f"{'abgel. Margin':>14s} {'abgel. Platz':>13s}")
    print("-" * 86)
    for name, max_offen, margin_pruefen in varianten:
        enden = [lauf(f, anteil=args.margin_anteil, hebel=args.hebel,
                      max_offen=max_offen, margin_pruefen=margin_pruefen)
                 for f in fenster]
        faktoren = sorted(k / START for k, _, _, _ in enden)
        print(
            f"{name:28s} {statistics.median(faktoren):8.4f} "
            f"{sum(1 for f in faktoren if f > 1.0)/len(faktoren):7.1%} "
            f"{sum(e[1] for e in enden):9,d} {sum(e[2] for e in enden):14,d} "
            f"{sum(e[3] for e in enden):13,d}"
        )

    print(
        "\nWAS DARAUS FOLGT.\n"
        "Die erste Zeile ist die Rechnung, die `run_plan_account.py` macht --\n"
        "sie nimmt jeden Trade. Die letzte ist das Konto, das wirklich\n"
        "moeglich waere. Der Unterschied zwischen beiden ist kein Effekt der\n"
        "Strategie, sondern Buchhaltung: Margin, die gebunden ist, steht fuer\n"
        "den naechsten Einstieg nicht zur Verfuegung.\n"
        "\n"
        "Die Richtung ist vorhersagbar und daher kein Befund: weniger Trades\n"
        "einer Population mit negativer Erwartung heisst weniger Verlust. Was\n"
        "die Messung liefert, ist die GROESSE des Unterschieds -- und die\n"
        "Erkenntnis, dass die Groessenregel die Platzgrenze still veraendert."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
