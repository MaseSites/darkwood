"""Wie vollstaendig ist das Binance-Tape wirklich? Beide Lesarten, benannt.

Das Auditdokument nennt 94,9 % und begruendet das damit, dass Binances
aggTrade-Kennung `a` JE SYMBOL laeuft, die Zahl also echt ist. Ein
Pruefagent hat 72,0 % nachgezaehlt. Beide koennen stimmen, wenn sie
verschiedene Fragen beantworten -- also werden hier beide gerechnet und
benannt.
"""

from __future__ import annotations

import json
import pathlib
import sys

WURZEL = pathlib.Path("data/quarantine/binance_tape")

#: Die zwei Bruchschwellen, in Kennungen. Bei der gemessenen Rate von
#: 35,1 Trades/s je Markt sind das Luecken von rund 28 s und rund 285 s --
#: und genau zwischen diesen beiden Schwellen liegt der Unterschied zwischen
#: den 94,9 % des Auditdokuments und den 72,0 % der Nachzaehlung.
SCHWELLEN = (1_000, 10_000)

#: Welche Schwelle die ausfuehrliche Kopfzeile bekommt.
ERSTE_SCHWELLE = SCHWELLEN[0]


def lade(symbol: str) -> list[int]:
    """Alle aggTrade-Kennungen in Dateireihenfolge, aufsteigend sortiert."""
    ids: list[int] = []
    for p in sorted((WURZEL / symbol).glob("*.jsonl")):
        with p.open(encoding="utf-8") as fh:
            for rohzeile in fh:
                zeile = rohzeile.strip()
                if not zeile:
                    continue
                try:
                    satz = json.loads(zeile)
                except json.JSONDecodeError:
                    continue
                # Jede ZEILE ist eine Abfrageantwort mit einer Liste darin:
                # {"received_ms": ..., "trades": [{"a": ..., ...}, ...]}.
                # Der erste Entwurf suchte 'a' auf der obersten Ebene und fand
                # nichts -- die Form angenommen statt angesehen.
                satze = satz.get("trades") if isinstance(satz, dict) else None
                if satze is None:
                    satze = [satz]
                for t in satze:
                    if not isinstance(t, dict):
                        continue
                    wert = t.get("a", t.get("agg_id", t.get("id")))
                    if wert is not None:
                        ids.append(int(wert))
    return sorted(set(ids))


def abschnitte(ids: list[int], *, bruch: int) -> list[tuple[int, int]]:
    """Zusammenhaengende Abschnitte, getrennt dort, wo mehr als `bruch` fehlen."""
    if not ids:
        return []
    out: list[tuple[int, int]] = []
    start = vorher = ids[0]
    for i in ids[1:]:
        if i - vorher > bruch:
            out.append((start, vorher))
            start = i
        vorher = i
    out.append((start, vorher))
    return out


def main() -> int:
    if not WURZEL.exists():
        print(f"{WURZEL} fehlt", file=sys.stderr)
        return 2
    symbole = sorted(p.name for p in WURZEL.iterdir() if p.is_dir())
    print(f"{len(symbole)} Symbole unter {WURZEL}\n")

    for symbol in symbole:
        ids = lade(symbol)
        if not ids:
            print(f"{symbol}: keine Kennungen gefunden")
            continue
        spanne = ids[-1] - ids[0] + 1
        # LESART A: ueber die GANZE Spanne von der ersten bis zur letzten
        # Kennung. Beantwortet "wie viel von dem, was in diesem Zeitraum
        # passiert ist, habe ich".
        ganz = len(ids) / spanne

        # LESART B: nur INNERHALB der zusammenhaengenden Abschnitte, die
        # Sammelluecken herausgerechnet. Beantwortet "wenn ich gesammelt
        # habe, wie vollstaendig war es".
        for bruch in SCHWELLEN:
            abs_ = abschnitte(ids, bruch=bruch)
            innen_spanne = sum(b - a + 1 for a, b in abs_)
            innen = len(ids) / innen_spanne if innen_spanne else 0.0
            laengster = max(abs_, key=lambda ab: ab[1] - ab[0]) if abs_ else (0, 0)
            l_ids = [i for i in ids if laengster[0] <= i <= laengster[1]]
            l_spanne = laengster[1] - laengster[0] + 1
            l_quote = len(l_ids) / l_spanne if l_spanne else 0.0
            if bruch == ERSTE_SCHWELLE:
                print(f"{symbol}")
                print(f"  Kennungen gesammelt      {len(ids):>10,}")
                print(f"  Spanne erste..letzte     {spanne:>10,}")
                print(f"  LESART A, ganze Spanne   {ganz:>10.1%}")
            print(
                f"  LESART B, Bruch>{bruch:<6,}  {innen:>10.1%}   "
                f"{len(abs_):3d} Abschnitte, laengster {l_spanne:>8,} Kennungen "
                f"zu {l_quote:.1%}"
            )
        print()

    print(
        "LESEHILFE. A fragt: wie viel vom Marktgeschehen im Zeitraum liegt vor.\n"
        "B fragt: wie dicht war die Aufnahme, wenn sie lief. B ist immer >= A.\n"
        "Welche Zahl gilt, haengt an der Frage -- eine Fill-Messung, die ueber\n"
        "einen Sammelbruch hinweg mittelt, braucht A; eine, die innerhalb eines\n"
        "Abschnitts bleibt, darf B nehmen UND muss sagen, dass sie es tut."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
