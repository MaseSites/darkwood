"""Das Chartbild zum Chat: was der Markt der Frage gerade zeigt, als PNG.

Derselbe Zeichner wie im Schatten des Haendlers (`vision/render.py`), damit
Chat und Haendler dasselbe Bild sehen. Nur geschlossene Kerzen aus dem
Speicher, dieselben, aus denen das Lagebild rechnet.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from traidingbrain.api.chat.modelle import Lage
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import Timeframe
from traidingbrain.vision.render import Linie, Panel, nur_bis, preisformat, zeichne

#: Hoechstens so viele Setups werden eingezeichnet; mehr ist ein Linienknaeuel.
MAX_SETUPS = 2

#: Bars je Zeitebene lesen: (Symbol, Zeitebene) -> Kerzen.
Lies = Callable[[str, Timeframe], pd.DataFrame]


def ebenen(timeframe: str) -> list[Timeframe]:
    """Die Zeitebene der Frage plus die groben, die das Bild einordnen: drei Panels."""
    try:
        gewaehlt = {Timeframe(timeframe)}
    except ValueError:
        gewaehlt = set()
    gewaehlt |= {Timeframe.H4, Timeframe.D1}
    if len(gewaehlt) < 3:
        gewaehlt.add(Timeframe.H1)
    return sorted(gewaehlt, key=timeframe_ms)


def linien(lage: Lage) -> list[Linie]:
    """Setups der Lage und offene Positionen auf diesem Markt."""
    ergebnis: list[Linie] = []
    for s in (lage.setups or [])[:MAX_SETUPS]:
        kopf = f"{s.timeframe} {s.side}"
        ergebnis += [
            Linie(s.entry, f"{kopf} Einstieg", "entry"),
            Linie(s.stop, f"{kopf} Stop", "stop"),
            Linie(s.target, f"{kopf} Ziel", "target"),
        ]
    for p in lage.konto.open_positions:
        if p.symbol == lage.symbol:
            seite = getattr(p.side, "value", p.side)
            ergebnis.append(Linie(p.entry_price, f"Position {seite}", "liquidation"))
    return ergebnis


def chart_bild(lies: Lies, lage: Lage, *, jetzt_ms: int) -> bytes | None:
    """Das PNG, oder None, wenn fuer keine Zeitebene Kerzen da sind."""
    striche = linien(lage)
    panels = []
    for tf in ebenen(lage.timeframe):
        kerzen = nur_bis(lies(lage.symbol, tf), jetzt_ms, bar_ms=timeframe_ms(tf))
        if not kerzen.empty:
            panels.append(Panel(f"{lage.symbol} {tf.value}", kerzen, striche))
    if not panels:
        return None
    preis = f"  Kurs {preisformat(lage.preis)}" if lage.preis is not None else ""
    return zeichne(panels, titel=f"{lage.symbol}{preis}  (geschlossene Kerzen)")
