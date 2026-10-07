"""Verändert ein anderer Stop den Pfad -- oder nur den Nenner?

    python scripts/study_stop_path.py

Der Zustandsbericht schrieb: `net_r = (eingefangene Bewegung minus Gebuehr) /
Stop-Abstand`, daher "Stop, Positionsgrösse und Hebel kürzen sich heraus", und
daraus die zu weite Folgerung, jeder Vorschlag mit anderen Stops sei
arithmetisch erledigt.

Die Positionsgrösse kürzt sich heraus. Der Stop nicht. Er steht im Nenner --
und, das ist der übersehene Teil, er verschiebt den **Ausstiegszeitpunkt**. Ein
Trade, der heute bei -1 R ausgestoppt wird, aber danach gedreht hätte, ist bei
einem weiteren Stop ein anderer Trade: andere Haltezeit, anderes Ergebnis,
anderes Funding, andere Gebührenbilanz.

Dieses Skript misst, für wie viele Trades die Annahme "gleicher Pfad" verletzt
ist. Die Datenquelle ist das Post-Mortem, das das Journal ohnehin je Trade
speichert: `max_adverse_r` sagt, wie weit der Preis gegen den Trade lief, bevor
er sich auflöste.

**Was dieses Skript ausdrücklich NICHT ist.** Es ist keine Exit-Studie und kein
Hinweis, dass weitere Stops besser wären. Ein weiterer Stop bedeutet bei
gleichem CHF-Risiko eine kleinere Position, mehr Zeit im Markt, mehr Funding und
eine andere Verteilung der Verluste -- und ob das in Summe hilft, kann nur ein
vollständig neu simulierter Pfad sagen (E3). Hier wird nur gezeigt, dass die
Frage offen ist, statt sie mit einer Kürzungsrechnung zu schliessen.

`max_adverse_r` ist in R des **ursprünglichen** Stops gemessen. "Stop 1,5x so
weit" heisst also: `max_adverse_r < 1.5`. Dass der Preis innerhalb der Haltezeit
dorthin lief, ist beobachtet; dass der Trade mit dem weiteren Stop bis dahin
offen GEBLIEBEN wäre, ist die konservative Annahme -- Ziel und Zeitausstieg
könnten früher greifen. Darum ist die Zahl eine Obergrenze für "wäre nicht
ausgestoppt worden", und sie ist auch so schon gross genug für die Aussage.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "data" / "journal.sqlite"

#: Stop-Breiten als Vielfache des heutigen Abstands.
WIDENINGS = (1.25, 1.5, 2.0, 3.0)

#: Die Breite, auf die der Schlusstext sich bezieht -- aus WIDENINGS, damit
#: Text und Rechnung nicht auseinanderlaufen koennen.
HEADLINE = 1.5

#: Ab wie viel Gewinn ein ausgestoppter Trade als 'war deutlich im Plus' zaehlt.
PROFIT_MARK = 0.5


def load_stopped() -> tuple[np.ndarray, np.ndarray]:
    """`max_adverse_r` und `max_favourable_r` der ausgestoppten Replay-Trades."""
    if not JOURNAL.is_file():
        raise SystemExit(f"Kein Journal unter {JOURNAL}.")
    with sqlite3.connect(JOURNAL) as conn:
        rows = [r[0] for r in conn.execute("SELECT payload FROM trades WHERE source='replay'")]
    adverse: list[float] = []
    favourable: list[float] = []
    for raw in rows:
        if not raw:
            continue
        trade = json.loads(raw)
        post = trade.get("post_mortem") or {}
        if trade.get("exit_reason") != "stop" or "max_adverse_r" not in post:
            continue
        adverse.append(float(post["max_adverse_r"]))
        favourable.append(float(post.get("max_favourable_r") or 0.0))
    if not adverse:
        raise SystemExit("Keine ausgestoppten Trades mit Post-Mortem im Journal.")
    return np.array(adverse), np.array(favourable)


def main() -> int:
    adverse, favourable = load_stopped()

    print("=" * 78)
    print("Veraendert ein anderer Stop den Pfad?")
    print("=" * 78)
    print(f"\nAusgestoppte Replay-Trades mit Post-Mortem: {adverse.size:,}\n")
    print(f"  max_adverse_r  Median {np.median(adverse):.3f}")
    print(
        f"                 Quantile 25/75/90: {np.percentile(adverse, 25):.3f}"
        f" / {np.percentile(adverse, 75):.3f} / {np.percentile(adverse, 90):.3f}"
    )
    print(f"  vorher im Plus (max_favourable_r > 0):  {100 * (favourable > 0).mean():.1f}%")
    deep = 100 * float((favourable > PROFIT_MARK).mean())
    print(f"  davon ueber +{PROFIT_MARK:.1f} R im Plus:             {deep:.1f}%")

    print("\nEin weiterer Stop haette diese Trades nicht beendet:\n")
    print(f"  {'Stop':>6s}  {'nicht ausgestoppt':>18s}")
    for factor in WIDENINGS:
        share = float((adverse < factor).mean())
        print(f"  {factor:>5.2f}x  {100 * share:>17.1f}%")

    worst = max(WIDENINGS)
    print("\n" + "-" * 78)
    print(
        f"  Schon bei {HEADLINE:.2f}x haetten "
        f"{100 * float((adverse < HEADLINE).mean()):.1f}% der heute "
        f"ausgestoppten Trades\n"
        f"  einen anderen Ausgang, eine andere Haltezeit und ein anderes Funding.\n"
        f"  Bei {worst:.2f}x sind es {100 * float((adverse < worst).mean()):.1f}%.\n"
        f"\n  Die Annahme 'gleicher Pfad' ist damit fuer die Mehrheit der Trades\n"
        f"  verletzt. Die korrekte Formulierung lautet:\n"
        f"\n    Bei festem Pfad aendert ein anderer Stop nur den Nenner und nicht das\n"
        f"    Vorzeichen des Zaehlers. Sobald der Stop den Ausstieg verschiebt, ist der\n"
        f"    Pfad nicht mehr fest, und die Aussage gilt nicht.\n"
        f"\n  'Engerer Stop, gleiche Bewegung angenommen' bleibt widerlegt.\n"
        f"  'Anderer Stop, Pfad neu simuliert' ist eine zulaessige Studie -- E3."
    )
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
