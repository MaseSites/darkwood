"""Hat das Chart-Urteil recht gehabt? Claudes Schatten-Urteile gegen die echten Ausgaenge.

    python scripts/vision_report.py                 # Plan-Konto (vision_shadow_plan)
    python scripts/vision_report.py --name vision_shadow

Verbindet jedes Urteil ueber `live-<proposal_id>` und die Signatur mit dem
geschlossenen Trade im Journal und vergleicht die mittleren R der Trades, die
Claude genommen haette, mit denen, die es ausgelassen haette.

Was diese Zahl NICHT ist: ein Beweis, solange die Stichprobe klein ist. Das
Intervall ist ein Bootstrap ueber die Differenz; spannt es die Null, hat das
Bild nichts gezeigt, was die Regeln nicht schon haben. Ein Veto ist erst dann
eine Frage, wenn es die Null ausschliesst -- und dann noch eine fuer eine
eigene, vorher angekuendigte Messung.
"""

from __future__ import annotations

import argparse
import random
import sys

from traidingbrain.config.settings import load_config
from traidingbrain.journal.record import Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.vision.schatten import SchattenSpeicher

#: Ziehungen fuer das Intervall der Differenz.
ZIEHUNGEN = 10_000


def _mittel(werte: list[float]) -> float:
    return sum(werte) / len(werte) if werte else float("nan")


def _intervall(a: list[float], b: list[float], rng: random.Random) -> tuple[float, float]:
    """95 % Bootstrap fuer mittel(a) - mittel(b)."""
    diffs = sorted(
        _mittel(rng.choices(a, k=len(a))) - _mittel(rng.choices(b, k=len(b)))
        for _ in range(ZIEHUNGEN)
    )
    return diffs[int(0.025 * ZIEHUNGEN)], diffs[int(0.975 * ZIEHUNGEN) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="vision_shadow_plan")
    args = parser.parse_args()

    config = load_config()
    daten = config.engine.paths.data_dir
    pfad = daten / f"{args.name}.sqlite"
    if not pfad.exists():
        print(f"Noch keine Urteile: {pfad} fehlt.")
        return 0
    urteile = SchattenSpeicher(pfad).alle()
    trades = {
        (e.trade_id, e.run_signature): e
        for e in JournalStore(daten / "journal.sqlite").all(source=Source.LIVE)
    }

    gruppen: dict[str, list[float]] = {"nehmen": [], "auslassen": []}
    offen = fehler = 0
    for u in urteile:
        if u["urteil"] is None:
            fehler += 1
            continue
        trade = trades.get((f"live-{u['proposal_id']}", u["run_signature"]))
        if trade is None:
            offen += 1  # nicht gefuellt, abgelaufen oder noch offen
            continue
        gruppen[u["urteil"]].append(trade.r_multiple)

    print(f"Urteile: {len(urteile)}  (ohne Urteil: {fehler}, ohne geschlossenen Trade: {offen})")
    for name, rs in gruppen.items():
        print(f"  {name:<10} {len(rs):>4} Trades   mittel {_mittel(rs):+.3f} R")
    a, b = gruppen["nehmen"], gruppen["auslassen"]
    if len(a) < 2 or len(b) < 2:
        print("\nZu wenig geschlossene Trades in beiden Gruppen fuer einen Vergleich.")
        return 0
    lo, hi = _intervall(a, b, random.Random(7))
    print(f"\nnehmen - auslassen: {_mittel(a) - _mittel(b):+.3f} R, 95 % [{lo:+.3f}, {hi:+.3f}]")
    print("Spannt das Intervall die Null, hat das Bild nichts Messbares hinzugefuegt."
          if lo <= 0 <= hi else "Das Intervall schliesst die Null aus -- jetzt eine eigene Messung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
