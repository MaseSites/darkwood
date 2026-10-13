"""Welche Positionen das EINE Konto gerade hält.

**Was ohne diese Datei nicht ging.** `live/paper.py` baute den Kontozustand
mit `AccountState.from_history(equity=..., history=..., now_ms=...)` — ohne
`open_positions`. `risk/limits.py` setzt dann eine leere Liste ein, und die
beiden Positionsprüfungen rechnen `0 >= 2` und `0 >= 1`. Sie können nicht
auslösen. Drei der vier Kontogrenzen griffen, nicht vier.

Das war unter zwölf getrennten Konten noch verteidigbar: jeder `PaperTrader`
kannte nur sich selbst, und eine Portfoliogrenze hätte Konten gepoolt, die
`live/paper.py` absichtlich getrennt hielt. Seit dem 13.10.2026 ziehen alle
zwölf aus einer Kasse, und damit ist die Trennung weg — zwölf Symbole in
einem Konto sind genau der Fall, für den `max_open_positions` geschrieben
wurde.

**Ein arbeitender Auftrag belegt einen Platz.** Das ist die Entscheidung in
dieser Datei, die man übersehen kann und die alles trägt. Der Deckel wird zur
*Vorschlagszeit* geprüft, eine Position entsteht zur *Füllzeit*. Zählte man
nur gefüllte Positionen, könnten zwölf Aufträge gleichzeitig arbeiten, alle
zwölf füllen, und der Deckel hätte nie etwas gesehen. Ein Platz ist also ab
dem Moment belegt, in dem ein Auftrag im Markt liegt.

Die Werte eines wartenden Auftrags sind seine eigenen — Limitpreis, Menge,
Hebel, und der Liquidationspreis, den er bei diesem Limit hätte. Nichts
daran ist erfunden; es ist der Auftrag, nicht eine Position, die es noch
nicht gibt.
"""

from __future__ import annotations

from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.proposal import Position
from traidingbrain.risk.leverage import liquidation_price
from traidingbrain.sim.broker import SimBroker


class OpenBook:
    """Die offenen Plätze des gepoolten Kontos, über alle Symbole.

    Gefüllt vom Aufrufer, der die Händler baut (`scripts/papertrade.py`), weil
    nur der die Liste kennt. Ein Händler ohne Buch verhält sich wie vorher —
    das ist der Pfad, den der Golden-Test und `tests/test_papertrade.py`
    fahren.
    """

    def __init__(self) -> None:
        self._desks: list[tuple[str, SimBroker, SymbolSpec]] = []

    def attach(self, symbol: str, broker: SimBroker, spec: SymbolSpec) -> None:
        self._desks.append((symbol, broker, spec))

    def __len__(self) -> int:
        return len(self._desks)

    def positions(self) -> list[Position]:
        """Jeder belegte Platz, als `Position`.

        Gefüllte Positionen und arbeitende Aufträge, in dieser Reihenfolge.
        Ein Symbol kann strukturell nur eines von beidem haben: `submit`
        lehnt ab, wenn schon etwas läuft.
        """
        out: list[Position] = []
        for symbol, broker, spec in self._desks:
            position = broker.position
            if position is not None:
                out.append(Position(
                    symbol=symbol,
                    side=position.side,
                    qty=position.qty,
                    entry_price=position.entry_price,
                    leverage=position.leverage,
                    liquidation_price=position.liq_price,
                    opened_ts=position.opened_ts,
                ))
                continue
            pending = broker.pending
            if pending is None:
                continue
            price = pending.limit_price
            out.append(Position(
                symbol=symbol,
                side=pending.side,
                qty=pending.qty,
                entry_price=price,
                leverage=pending.leverage,
                liquidation_price=liquidation_price(
                    pending.side, price, pending.leverage, spec.maintenance_margin_rate
                ),
                # Der Zeitpunkt der Einreichung. Ein Auftrag ist noch keine
                # Position, und `opened_ts` ist das Einzige, was hier
                # ungenau sein KANN -- es wird von keiner Grenze gelesen,
                # die Zaehlungen interessieren sich nur fuer das Dasein.
                opened_ts=pending.created_ts,
            ))
        return out
