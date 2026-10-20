"""What the forward paper trader has done, for the screen.

Read-only, and reading from files rather than from the running process. The
trader writes its accounts to `paper.sqlite` and its finished trades to
`journal.sqlite`; this opens both and reports what is in them. Nothing here can
start, stop or influence a trade, which is why the dashboard can show it without
the two programs having to know about each other.

**Only forward trades are counted.** The journal also holds thousands of
replayed ones, and an average over both would describe neither -- the replayed
ones were selected by somebody who knew how that stretch of history went. The
filter is not a display preference; it is the whole reason the column exists.

**Staleness is reported, not hidden.** A screen showing an account that was last
updated six hours ago looks exactly like one showing a working system, which is
the failure mode that wasted an hour of Severin's time on the score panel. So
the age of the last settled minute is part of the payload and the screen says it
out loud.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from traidingbrain.config.settings import AppConfig
from traidingbrain.journal.era import current_era, era_count
from traidingbrain.journal.record import JournalEntry, Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.paperstate import PaperStateStore

#: How many finished trades the screen lists. Newest first.
RECENT = 12

#: Minutes after which an account is called stale.
#:
#: The trader settles every closed minute, so five is already three cycles
#: missed. Generous enough not to flicker on one slow exchange response.
STALE_AFTER_MINUTES = 5


class PaperPosition(BaseModel):
    side: str
    entry: float
    stop: float
    target: float
    qty: float
    leverage: float
    opened_ts: int
    unrealised: float
    risk_amount: float
    stop_moved: bool
    #: Positionsgroesse in der Quote-Waehrung: qty * entry.
    #:
    #: Mitgeliefert statt dem Konsumenten zum Nachrechnen ueberlassen. Wer
    #: es selbst rechnet, rechnet irgendwann mit `exit` oder mit dem
    #: aktuellen Preis -- und beantwortet damit eine andere Frage als "mit
    #: wie viel Geld wurde dieser Trade eroeffnet".
    notional: float
    #: Davon tatsaechlich gebundenes Kapital: notional / leverage.
    #: Nicht dasselbe wie `risk_amount`, siehe config/risk.yaml.
    margin: float


class PaperAccount(BaseModel):
    symbol: str
    realised: float
    """Was dieser Markt dem EINEN Konto eingebracht hat, in USDT.

    Hiess bis zum 14.10.2026 `equity` und trug den Kontostand. Das war
    richtig, solange zwoelf getrennte Konten liefen; seit der Zusammenlegung
    stand in jeder der zwoelf Zeilen derselbe Gesamtstand, und das Panel
    zeigte zwoelfmal 12.075,56 USDT nebeneinander, als haette jeder Markt so
    viel Geld.

    Ein Markt hat kein Geld. Er hat einen Beitrag, und der steht im Journal."""

    trades: int = 0
    last_price: float
    last_minute_ts: int
    stale: bool
    behind_minutes: int
    position: PaperPosition | None = None
    resting_at: float | None = None
    """Where an unfilled order is waiting, if one is."""

    setup: str | None = None
    setup_timeframe: str | None = None
    rating: int | None = None

    activity: str = ""
    """One German sentence on why this account is doing what it is doing.

    The panel's honest answer to "it has been flat all day". Without it the
    screen cannot tell a market that offered no setup from a risk layer that
    refused every one, and those call for opposite responses."""

    bars_seen: int = 0
    proposed: int = 0
    refused_by_risk: int = 0


class PaperTrade(BaseModel):
    closed_ts: int
    opened_ts: int
    symbol: str
    setup: str
    setup_timeframe: str
    side: str
    r_multiple: float
    net_pnl: float
    exit_reason: str
    rating: int
    bars_held: int
    verdict: str


class PaperReadout(BaseModel):
    """Everything the paper-trading panel shows."""

    accounts: list[PaperAccount]
    trades: int
    """Abgeschlossene Trades unter der LAUFENDEN Konfiguration.

    **Nicht alle.** Am 16.10.2026 zeigte diese Zahl 28 und der Mittelwert
    daneben +0.294 R; die 28 zerfielen in drei Konfigurationen, eine davon
    ganz ohne aufgezeichnete Konfiguration. Siehe `journal/era.py`."""

    wins: int
    mean_r: float
    total_net: float

    trades_all: int
    """Alle abgeschlossenen Vorwaertstrades, ueber alle Konfigurationen."""

    eras: int
    """Ueber wie viele (Signatur, Codestand)-Paare sich `trades_all` verteilt."""
    recent: list[PaperTrade]
    running: bool
    """Is anything being settled at all? False when every account is stale,
    which is what a stopped trader looks like from here."""


def _position_view(state: object, last_price: float) -> PaperPosition | None:
    position = getattr(state, "position", None)
    if position is None:
        return None
    return PaperPosition(
        side=str(position.side),
        entry=position.entry_price,
        stop=position.stop,
        target=position.target,
        qty=position.qty,
        leverage=position.leverage,
        opened_ts=position.opened_ts,
        unrealised=round(position.unrealised(last_price), 4) if last_price else 0.0,
        risk_amount=position.risk_amount,
        stop_moved=position.stop_moved,
        notional=position.notional,
        margin=position.margin,
    )


def _gehoert_dazu(signature: str | None):
    """Welche Journaleintraege zu diesem Konto gehoeren.

    Ohne Signatur: alle -- das alte Verhalten, bewusst erhalten fuer Werkzeuge,
    die ueber alles schauen wollen. Mit Signatur: nur die, deren gespeicherte
    `run_signature` passt.

    Der erste Entwurf ging ueber `closed_trades()` und verglich `trade_id`.
    Das war ein Umweg um nichts: `JournalEntry` TRAEGT `run_signature` selbst,
    und `ClosedTrade` hat gar kein `trade_id`. Der direkte Vergleich ist
    kuerzer und hat eine Fehlerquelle weniger.
    """
    if signature is None:
        return lambda _entry: True
    return lambda entry: entry.run_signature == signature


def build_paper_readout(
    state_path: Path,
    journal_path: Path,
    *,
    config: AppConfig,
    now_ms: int,
    symbols: list[str] | None = None,
    signature: str | None = None,
) -> PaperReadout:
    """Read both files and say what the paper trader is doing.

    `now_ms` is passed in rather than read from the clock so a test can pin the
    staleness arithmetic, which is the only thing here with a time dependency.

    **`signature` grenzt auf DIESES Konto ein, und sein Fehlen war ein Fehler.**
    Bis zum 20.10.2026 summierte diese Funktion `journal.all(source=LIVE)`,
    also jeden Live-Trade des Journals -- quer ueber alle Konten und alle
    Konfigurationen. Das Plankonto zeigte dadurch auf BTCUSDT -63.81 USD aus
    zwei Trades, die ein anderes Konto gemacht hatte, waehrend `/api/portfolio`
    fuer denselben Markt korrekt 0.00 aus 0 Trades meldete. Zwei Endpunkte,
    dieselbe Frage, zwei Antworten.

    `portfolio`, `aussicht` und `ledger` gaben die Signatur von Anfang an mit;
    nur dieser Pfad wurde vergessen. Siehe auch `one-account-not-twelve`: das
    Journal haelt mehrere Konten, und wer nicht einschraenkt, mittelt sie.

    `None` bleibt erlaubt, damit Tests und Werkzeuge, die bewusst ueber alles
    schauen wollen, es weiter koennen -- aber die Ansichten geben sie mit.
    """
    states = PaperStateStore(state_path)
    journal = JournalStore(journal_path)

    live_all = journal.all(source=Source.LIVE)
    gehoert_dazu = _gehoert_dazu(signature)
    realised: dict[str, float] = {}
    counted: dict[str, int] = {}
    for entry in live_all:
        if not entry.closed_ts or not gehoert_dazu(entry):
            continue
        realised[entry.symbol] = realised.get(entry.symbol, 0.0) + entry.net_pnl
        counted[entry.symbol] = counted.get(entry.symbol, 0) + 1

    wanted = symbols if symbols is not None else states.symbols()
    accounts: list[PaperAccount] = []
    for symbol in wanted:
        saved = states.load(symbol)
        if saved is None:
            continue
        behind = max(0, (now_ms - saved.last_minute_ts) // 60_000) if saved.last_minute_ts else 0
        reason = saved.reason
        accounts.append(
            PaperAccount(
                symbol=symbol,
                realised=round(realised.get(symbol, 0.0), 2),
                trades=counted.get(symbol, 0),
                last_price=saved.last_price,
                last_minute_ts=saved.last_minute_ts,
                stale=behind > STALE_AFTER_MINUTES,
                behind_minutes=int(behind),
                position=_position_view(saved, saved.last_price),
                resting_at=saved.pending.limit_price if saved.pending is not None else None,
                setup=reason.setup_key if reason is not None else None,
                setup_timeframe=reason.setup_timeframe if reason is not None else None,
                rating=reason.rating if reason is not None else None,
                activity=saved.tally.sentence(),
                bars_seen=saved.tally.bars_seen,
                proposed=saved.tally.proposed,
                refused_by_risk=saved.tally.refused_by_risk,
            )
        )

    live = live_all
    # Die Schlagzeile zaehlt EINE Konfiguration -- dieselbe Quelle wie
    # `api/portfolio.py`, damit die beiden nicht auseinanderlaufen. Genau
    # das ist am 16.10.2026 passiert: `portfolio.py` war repariert, diese
    # Datei nicht, und das Dashboard zeigte die neue Beschriftung ueber den
    # alten Zahlen.
    #
    # Die LISTE der letzten Trades bleibt ungefiltert: sie zeigt, was
    # geschehen ist, und ein Trade aus einer aelteren Konfiguration ist
    # geschehen. Nur die Kennzahlen darueber werden eingeschraenkt.
    current = current_era(live, config)
    rs = [entry.r_multiple for entry in current]
    return PaperReadout(
        accounts=accounts,
        trades=len(current),
        wins=sum(1 for entry in current if entry.won),
        mean_r=round(sum(rs) / len(rs), 4) if rs else 0.0,
        total_net=round(sum(entry.net_pnl for entry in current), 2),
        trades_all=len(live),
        eras=era_count(live),
        recent=[_trade_view(entry) for entry in reversed(live[-RECENT:])],
        running=any(not account.stale for account in accounts),
    )


def _trade_view(entry: JournalEntry) -> PaperTrade:
    return PaperTrade(
        closed_ts=entry.closed_ts,
        opened_ts=entry.opened_ts,
        symbol=entry.symbol,
        setup=entry.reason.setup_key,
        setup_timeframe=entry.reason.setup_timeframe,
        side=entry.reason.side,
        r_multiple=entry.r_multiple,
        net_pnl=entry.net_pnl,
        exit_reason=entry.exit_reason.value,
        rating=entry.reason.rating,
        bars_held=entry.post_mortem.bars_held,
        verdict=entry.post_mortem.verdict,
    )
