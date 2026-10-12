"""Die Handelshistorie, die eine Risikobremse lesen darf.

**Warum dieses Modul existiert.** Drei der sechs Sicherungen in
`risk/limits.py` lesen `AccountState.recent_trades`, eine Liste von
`ClosedTrade` — `max_daily_loss_pct`, `max_weekly_loss_pct` und
`cooldown_after_consecutive_losses`. Am 11.10.2026 wurde gemessen, dass
**alle drei Stellen, die einen `AccountState` bauen, dort `[]` übergeben**,
und dass `ClosedTrade` in der Produktion **nirgends** konstruiert wird: der
einzige Konstruktionsaufruf im Baum steht in einem Test. Die Sicherungen
verbrauchen einen Typ ohne Produzenten.

Dieses Modul ist der Produzent, und er sitzt im Journal, weil das Journal
beide Seiten kennt: `JournalEntry` trägt `net_pnl` und `closed_ts` unter
denselben Namen, in denselben Einheiten (Epoch-Millisekunden) und mit
demselben Vorzeichen wie `ClosedTrade`.

**Der Filter ist nicht Beiwerk, er ist der Zweck.** Gemessen am 12.10.2026
über die 25 geschlossenen Live-Trades:

    gelesene Historie            Konten mit Verlustserie >= 2
    alle 25 Zeilen               AVAXUSDT, BTCUSDT
    nur laufende Signatur (7)    keine

Die 25 Zeilen sind **drei Konfigurationsepochen** plus ein Trade aus einer
zerstörten Kontogeneration (`live-BTCUSDT-1790928000000`: zehnfache Grösse,
4,98 % Risiko auf ein 1.000-USDT-Konto gegen einen Deckel von 3 %, und das
Kontobuch kennt ihn nicht). Eine Bremse, die das zusammenzählt, zählt eine
Verlustserie, die so nie stattgefunden hat.

Zeilen **ohne** Signatur werden deshalb verworfen, nicht als „passt schon"
mitgenommen. Rückwirkend füllen wäre Erfindung: welche Konfiguration einen
Trade vom 02.10. erzeugt hat, steht nur in der Git-Historie, und
`journal/record.py` nennt genau das keine aufgezeichnete Eigenschaft.

**Eine dünne richtige Historie schlägt eine dicke falsche.** Sieben Zeilen
sind wenig; sie sind zuordenbar.
"""

from __future__ import annotations

from traidingbrain.domain.enums import STATE_OF_EXIT, Side
from traidingbrain.domain.proposal import ClosedTrade
from traidingbrain.journal.record import JournalEntry, Source
from traidingbrain.journal.store import JournalStore


def as_closed_trade(entry: JournalEntry) -> ClosedTrade | None:
    """Einen Journaleintrag in die Form bringen, die die Bremsen lesen.

    `None`, wenn der Eintrag die Pflichtfelder von `ClosedTrade` nicht
    erfüllt — Preise und Menge müssen echt positiv sein. Ein Eintrag mit
    `entry_price = 0` ist keine Zeile, die man einer Bremse unterschiebt;
    sie fällt lieber heraus als dass die Bremse auf einem Platzhalter zählt.
    """
    if entry.entry_price <= 0 or entry.exit_price <= 0 or entry.qty <= 0:
        return None
    state = STATE_OF_EXIT.get(entry.exit_reason)
    if state is None:
        return None
    return ClosedTrade(
        proposal_id=entry.trade_id,
        symbol=entry.symbol,
        side=Side(entry.reason.side),
        state=state,
        entry_price=entry.entry_price,
        exit_price=entry.exit_price,
        qty=entry.qty,
        opened_ts=entry.opened_ts,
        closed_ts=entry.closed_ts,
        gross_pnl=entry.gross_pnl,
        # `ge=0` auf dem Ziel: eine negative Gebuehr gibt es nicht, und eine
        # gerundete Null kann als -0.0 ankommen.
        fees=max(entry.fees, 0.0),
        funding=entry.funding,
        net_pnl=entry.net_pnl,
        r_multiple=entry.r_multiple,
        snapshot_hash="",
    )


def closed_trades(
    store: JournalStore,
    *,
    signature: str,
    source: Source = Source.LIVE,
    symbol: str | None = None,
) -> list[ClosedTrade]:
    """Die geschlossenen Trades, die zu `signature` gehören.

    `symbol` gesetzt heisst **pro Konto**, weggelassen heisst **über alle**.
    Die Wahl trifft der Aufrufer, weil `risk/limits.py` nichts nach Symbol
    einschränkt — der Geltungsbereich ist eine Entscheidung und keine
    Eigenschaft der Bremse.

    Leere `signature` liefert eine leere Liste. Das ist bewusst: „ich kenne
    meine Konfiguration nicht" ist kein Grund, alles zu lesen, sondern einer,
    nichts zu lesen.
    """
    if not signature:
        return []
    out: list[ClosedTrade] = []
    for entry in store.all(source=source, symbol=symbol):
        if entry.run_signature != signature:
            continue
        trade = as_closed_trade(entry)
        if trade is not None:
            out.append(trade)
    return out
