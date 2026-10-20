"""The account, the ledger and the curve — what the paper money has done.

Three questions a person actually asks, and the screen answers each on its own
page: *how much have I got*, *what did I trade*, *is it going up or down*.

**The curve is in R, not in francs.** A trade's result in money depends on the
account it was taken on, and that account has changed size: the first forward
trades were taken on ten thousand and the rest on one thousand, because Severin
asked for the number he will actually have. A franc curve across that boundary
would show a cliff that no trade caused. R -- the result as a multiple of what
was risked -- is the same measurement whatever the account, which is why every
other report in this project is already in it. Francs are shown beside it as
the current balance, where they mean something.

**Replay and forward are never added together.** The journal holds thousands of
replayed trades and a handful of forward ones. The replayed decisions are
honest, but the *period* was chosen by somebody who knew how it went, and
mixing them produces a number that describes neither. Every figure here is one
or the other, and the page says which.

Writing is deliberately narrow: top up an account, or start one over. Both are
paper money and neither can touch an exchange. Everything else -- risk per
trade, the cost ceiling, which setups are on -- is shown read-only, because
those are the settings every measurement in this project was taken under, and a
knob that silently invalidates the evidence is worse than no knob.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from traidingbrain.api.chart import Candle
from traidingbrain.config.settings import AppConfig
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Side
from traidingbrain.journal.history import konto_schluessel
from traidingbrain.journal.era import current_era, era_count
from traidingbrain.journal.record import JournalEntry, Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.paperstate import PaperState, PaperStateStore
from traidingbrain.strategy.setups import TRADEABLE

#: Most trades the ledger hands over at once.
#:
#: The replay journal holds thousands and the browser has to draw them. Forward
#: trades are far fewer and are never truncated, because those are the ones the
#: whole exercise is about.
MAX_LEDGER = 400

#: Candles shown behind an open trade.
#:
#: Raised from 90 on 13.10.2026, and the reason is the whole point of the
#: change. Ninety was right for a *picture*: enough to see the approach, not
#: so many that the plan lines smudge at the right-hand edge. It was wrong for
#: something you can zoom and pan -- there, ninety candles means you reach the
#: end of the data on the first drag, and the chart feels broken rather than
#: small.
#:
#: 1,500 M15 candles are about sixteen days; 1,500 H4 candles are about eight
#: months. That is a window a running trade can actually be read in, and it is
#: roughly 90 KB over the wire, which a local dashboard does not notice.
CHART_CANDLES = 1_500

#: The most a caller may ask for.
#:
#: A ceiling rather than "whatever you like", because `?candles=5000000` on a
#: local dashboard is not an attack, it is a typo that looks like a hang.
MAX_CHART_CANDLES = 6_000


#: Minutes behind before an account is called stale.
#:
#: The trader settles every closed minute, so five is three cycles missed --
#: generous enough not to flicker on one slow exchange response, tight enough
#: that a stopped trader is obvious within the time it takes to notice.
STALE_AFTER_MINUTES = 5


class MarketRow(BaseModel):
    """Was EIN Markt auf dem Konto getan hat — nicht, was er besitzt.

    **Hiess bis zum 14.10.2026 `AccountRow` und trug eine Spalte `equity`.**
    Das war richtig, solange zwölf getrennte Konten liefen. Seit der
    Zusammenlegung ist es falsch, und zwar sichtbar falsch: jede der zwölf
    Zeilen bekam den GANZEN geteilten Kontostand in ihre `equity`-Spalte
    geschrieben, und `build_portfolio` summierte sie. Das Dashboard meldete
    144.906,72 USDT statt 12.075,56 und +1.107 % statt +0,63 %.

    Ein Markt hat keinen Kontostand. Er hat einen Beitrag.
    """

    symbol: str
    realised: float
    """Summe der realisierten Ergebnisse dieses Marktes, in USDT.

    Aus dem Journal gelesen und nicht aus der Zustandszeile: die Zeile kennt
    nur den geteilten Stand, das Journal kennt die Trades."""

    trades: int
    open_risk: float
    """What is at stake in an open position right now, in francs. Zero when
    flat. This is the number a person means by "how much can I lose", and it is
    not the position size."""

    unrealised: float
    has_position: bool
    margin: float
    """Wie viel Kapital des EINEN Kontos dieser Markt gerade bindet."""

    stale: bool
    behind_minutes: int
    activity: str


class Portfolio(BaseModel):
    """EIN Konto, und was die zwölf Märkte darauf tun.

    **Die Umstellung, und der Fehler, der sie begleitet hat.** Bis zum
    13.10.2026 führte der Papierhandel zwölf getrennte Konten à 1.000 USDT.
    Seitdem gibt es genau eine Kasse — wie bei einem echten Broker-Konto, von
    dem aus man in mehrere Märkte geht, ohne auf jedem Markt den vollen
    Betrag zu haben.

    Die zwölf Zeilen in der Tabelle `accounts` sind seither keine Konten
    mehr, sondern Arbeitsplätze. Sie zu summieren ergibt das Zwölffache, und
    genau das tat diese Datei bis zum 14.10.2026.

    Darum trägt dieses Modell den Kontostand **einmal** und nicht als Summe.
    """

    equity: float
    """Der Kontostand. Eine Zahl, aus der `portfolio`-Zeile gelesen."""

    start: float
    """Was eingezahlt wurde: `initial_equity` mal Zahl der Märkte.

    Hergeleitet und nicht gespeichert, weil die Kasse beim Umschalten aus der
    Summe der zwölf Konten entstand und jedes davon bei `initial_equity`
    begann."""

    change: float
    change_pct: float
    peak: float
    """Höchststand, mitgeführt, damit der Rückgang ab dem Höchststand misst
    und nicht ab dem Neustart."""

    reserved: float
    """Margin, das offene Positionen gerade binden."""

    available: float
    open_risk: float
    unexplained: float
    """`equity - start - Summe der Markt-Beiträge`.

    Sollte null sein. Ist es nicht, hält das Konto ein Ergebnis, das kein
    journalisierter Trade erklärt — am 14.10.2026 sind das +55,05 USDT aus
    einem Trade, der zu keiner Generation gehört. Diese Zeile steht hier,
    damit die Lücke auf dem Bildschirm steht statt in einem Bericht."""

    markets: list[MarketRow]

    trades: int
    """Abgeschlossene Trades unter der LAUFENDEN Konfiguration.

    **Nicht alle.** Am 16.10.2026 zerfielen die 28 Vorwaertstrades in drei
    Konfigurationen -- 18 ohne aufgezeichnete Signatur, 9 unter der
    Vorgaengerin, 1 unter der laufenden -- und der Mittelwert darueber
    beantwortet keine Frage: unter `portfolio` riskiert ein Trade 120 USDT,
    unter der Vorgaengerin 10. Die Schlagzeile zeigt deshalb eine
    Konfiguration, und `trades_all` sagt, wie viele es insgesamt sind."""

    wins: int
    mean_r: float
    total_r: float

    trades_all: int
    """Alle abgeschlossenen Vorwaertstrades, ueber alle Konfigurationen."""

    eras: int
    """Ueber wie viele (Signatur, Codestand)-Paare sich `trades_all` verteilt.

    Steht hier, damit die Oberflaeche den Unterschied benennen kann. Eins
    heisst: die Schlagzeile deckt alles ab. Mehr heisst: es gibt aeltere
    Trades, die nicht mitzaehlen, und das ist eine Aussage und kein
    Datenverlust."""

    running: bool
    pooled: bool
    """Ob wirklich eine Kasse läuft (`risk.sizing.basis: portfolio`).

    Steht hier, weil der Unterschied sonst nur am Verhalten zu erkennen wäre
    und die Oberfläche ihn benennen können muss."""


class LedgerRow(BaseModel):
    trade_id: str
    source: str
    closed_ts: int
    opened_ts: int
    symbol: str
    setup: str
    setup_name: str
    setup_timeframe: str
    side: str
    entry: float
    exit: float
    stop: float
    target: float
    r_multiple: float
    net_pnl: float
    fees: float
    exit_reason: str
    rating: int
    rating_band: str
    score_direction: str
    agreed_with_score: bool
    bars_held: int
    max_favourable_r: float
    max_adverse_r: float
    stopped_by_wick: bool
    verdict: str


class Ledger(BaseModel):
    rows: list[LedgerRow]
    total: int
    truncated: bool


class CurvePoint(BaseModel):
    ts: int
    cumulative_r: float
    trade: int
    """How many trades had closed by this point. The x-axis a person reads is
    time, but the one that makes the slope meaningful is the trade count."""


class Curve(BaseModel):
    points: list[CurvePoint]
    source: str
    best_r: float
    worst_r: float
    peak_r: float
    drawdown_r: float
    """Furthest the curve has fallen below its own peak, in R. The number that
    says what holding this would have felt like, which the final total never
    does."""

    by_symbol: dict[str, float]
    by_setup: dict[str, float]


class SettingsView(BaseModel):
    """What the engine is configured to do. Read-only on purpose."""

    initial_equity: float
    account_start: float
    sizing_basis: str
    risk_pct_floor: float
    max_leverage: float
    min_reward_risk: float
    max_cost_fraction_of_risk: float
    slippage_bps: float
    setups_on: list[str]
    signal_timeframe: str
    searched_timeframes: list[str]
    note: str


class TopUpRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


class OpenTrade(BaseModel):
    """A position that is still running.

    Its own shape rather than a `LedgerRow` with blanks: a trade that has not
    finished has no exit, no result and no verdict, and a row carrying three
    empty columns invites them to be read as zeroes. What it has instead is
    where it stands right now, which a closed trade does not.
    """

    symbol: str
    side: str
    entry: float
    stop: float
    target: float
    qty: float
    leverage: float
    notional: float
    margin: float
    opened_ts: int
    held_minutes: int
    last_price: float
    #: Die Minute, zu der `last_price` gilt.
    #:
    #: Ergaenzt am 13.10.2026 fuer den interaktiven Chart. Ohne sie koennte
    #: der Browser den Kurs nur an seine EIGENE Uhr haengen -- und ein
    #: Haendler, der zwei Minuten hinterherliegt, wuerde dann eine Kerze in
    #: die Zukunft schreiben, die er noch gar nicht gesehen hat.
    last_minute_ts: int = 0
    unrealised: float
    risk_amount: float
    r_now: float
    """Where it stands in units of the risk. +1.0 means it is a full risk ahead;
    the target sits at the reward-to-risk ratio and the stop at -1.0."""

    progress: float
    """How far along the path from stop to target, 0 to 1, with the entry
    wherever it falls between them. The one number that says "nearly there" or
    "nearly wrong" without needing the prices read off."""

    reward_risk: float
    setup: str
    setup_name: str
    setup_timeframe: str
    signal_timeframe: str
    rating: int
    rating_band: str
    agreed_with_score: bool
    stop_moved: bool


class PositionChart(BaseModel):
    """Candles behind an open trade, with the three lines that decide it."""

    symbol: str
    timeframe: str
    bar_ms: int
    side: str
    entry: float
    stop: float
    target: float
    opened_ts: int
    candles: list[Candle]
    note: str = ""
    #: Welche Zeitebenen fuer diesen Trade abrufbar sind.
    #:
    #: Vom Server beantwortet und nicht im Browser geraten: ob eine Ebene
    #: Daten hat, weiss nur der Speicher. Ein Umschalter, der auf eine leere
    #: Datei zeigt, ist schlimmer als keiner.
    timeframes: list[str] = Field(default_factory=list)
    #: Die Ebene, auf der das Setup gefunden wurde -- nicht zwingend die
    #: gezeigte, wenn der Aufrufer umgeschaltet hat.
    setup_timeframe: str = ""
    #: Der letzte Kurs, den der Haendler gesehen hat, und wann.
    #:
    #: Damit der Chart die rechte Kante fortschreiben kann, ohne alle 1.500
    #: Kerzen erneut zu holen. 0 heisst "noch keiner".
    last_price: float = 0.0
    last_minute_ts: int = 0
    #: Die Liquidation. Gehoert auf einen Chart mit Hebel: Stop ist, wo der
    #: Plan sagt, der Trade ist falsch -- Liquidation ist, wo die Boerse
    #: sagt, der Trade ist vorbei.
    liquidation: float = 0.0
    leverage: float = 0.0
    qty: float = 0.0
    risk_amount: float = 0.0


def _candles(frame: pd.DataFrame) -> list[Candle]:
    """Bars as a list, read off numpy rather than row by row.

    `itertuples` hands back loosely typed rows that the type checker cannot see
    the columns of, and the arrays are what every other reader in this project
    uses anyway.
    """
    ts = frame["ts"].to_numpy(dtype="int64")
    opens = frame["open"].to_numpy(dtype="float64")
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    volumes = frame["volume"].to_numpy(dtype="float64")
    return [
        Candle(
            ts=int(ts[i]),
            open=float(opens[i]),
            high=float(highs[i]),
            low=float(lows[i]),
            close=float(closes[i]),
            volume=float(volumes[i]),
        )
        for i in range(len(ts))
    ]


def build_open(state_path: Path, config: AppConfig, *, now_ms: int) -> list[OpenTrade]:
    """Every position still running, newest first.

    Read from the trader's state file rather than from the journal, because the
    journal only learns about a trade when it ends. These are the ones that have
    not.
    """
    states = PaperStateStore(state_path)
    out: list[OpenTrade] = []
    for symbol in config.engine.symbols.active:
        saved = states.load(symbol)
        if saved is None or saved.position is None:
            continue
        position = saved.position
        reason = saved.reason
        risk = position.risk_price
        price = saved.last_price or position.entry_price
        sign = 1.0 if position.side is Side.LONG else -1.0
        r_now = ((price - position.entry_price) * sign / risk) if risk else 0.0

        low, high = sorted((position.stop, position.target))
        span = high - low
        progress = (price - low) / span if span > 0 else 0.0
        if position.side is Side.SHORT:
            progress = 1.0 - progress

        out.append(
            OpenTrade(
                symbol=symbol,
                side=str(position.side),
                entry=position.entry_price,
                stop=position.stop,
                target=position.target,
                qty=position.qty,
                leverage=position.leverage,
                notional=round(position.notional, 2),
                margin=round(position.margin, 2),
                opened_ts=position.opened_ts,
                held_minutes=int(max(0, (now_ms - position.opened_ts) // 60_000)),
                last_price=price,
                last_minute_ts=saved.last_minute_ts or 0,
                unrealised=round(position.unrealised(price), 2),
                risk_amount=round(position.risk_amount, 2),
                r_now=round(r_now, 3),
                progress=round(min(1.0, max(0.0, progress)), 4),
                reward_risk=round(abs(position.target - position.entry_price) / risk, 2)
                if risk
                else 0.0,
                setup=reason.setup_key if reason else "—",
                setup_name=reason.setup_name if reason else "—",
                setup_timeframe=reason.setup_timeframe if reason else "—",
                signal_timeframe=reason.signal_timeframe if reason else "",
                rating=reason.rating if reason else 0,
                rating_band=reason.rating_band if reason else "",
                agreed_with_score=reason.rating_agreed_with_setup if reason else False,
                stop_moved=position.stop_moved,
            )
        )
    out.sort(key=lambda t: t.opened_ts, reverse=True)
    return out


def build_position_chart(
    state_path: Path,
    config: AppConfig,
    symbol: str,
    *,
    timeframe: str | None = None,
    candles: int = CHART_CANDLES,
) -> PositionChart | None:
    """The recent candles behind one open trade, on the chart it was found on.

    On the setup's own timeframe rather than the decision cadence: a four-hour
    setup read off fifteen-minute candles is noise around a plan drawn from
    something else. Falls back to the signal frame when the setup is unknown.

    `timeframe` overrides that choice, for the switch in the browser. The
    default is unchanged, so the first view a reader gets is still the frame
    the decision was made on -- switching is something they do, not something
    the page does for them.
    """
    saved = PaperStateStore(state_path).load(symbol)
    if saved is None or saved.position is None:
        return None
    position = saved.position
    store = ParquetStore(config.engine.paths.parquet_dir)

    setup_frame = config.engine.timeframes.signal
    if saved.reason is not None:
        for candidate in config.engine.timeframes.context:
            if candidate.value == saved.reason.setup_timeframe:
                setup_frame = candidate
                break

    wanted = setup_frame
    if timeframe:
        for candidate in config.engine.timeframes.context:
            if candidate.value == timeframe:
                wanted = candidate
                break
        else:
            # Eine unbekannte Ebene wird nicht stillschweigend zur
            # Vorgabeebene. Wer M5 anfragt, soll nicht M15 bekommen und
            # glauben, er sehe M5.
            return None

    frame = store.read(symbol, wanted)
    if frame.empty:
        return None
    tail = frame.tail(max(1, min(candles, MAX_CHART_CANDLES)))
    return PositionChart(
        symbol=symbol,
        timeframe=wanted.value,
        bar_ms=wanted.minutes * 60_000,
        side=str(position.side),
        entry=position.entry_price,
        stop=position.stop,
        target=position.target,
        opened_ts=position.opened_ts,
        candles=_candles(tail),
        # An den Partitionen geprueft, nicht am Inhalt. `store.read` fuer
        # jede der fuenf Ebenen hiesse 176.000 M15-Zeilen bei jedem
        # Chartaufruf lesen, um eine Ja/Nein-Frage zu beantworten.
        timeframes=[
            candidate.value
            for candidate in config.engine.timeframes.context
            if store.partitions(symbol, candidate)
        ],
        setup_timeframe=setup_frame.value,
        last_price=saved.last_price or 0.0,
        last_minute_ts=saved.last_minute_ts or 0,
        liquidation=position.liq_price,
        leverage=position.leverage,
        qty=position.qty,
        risk_amount=position.risk_amount,
    )


def _market_row(
    state: PaperState, *, realised: float, trades: int, now_ms: int
) -> MarketRow:
    behind = max(0, (now_ms - state.last_minute_ts) // 60_000) if state.last_minute_ts else 0
    position = state.position
    return MarketRow(
        symbol=state.symbol,
        realised=round(realised, 2),
        trades=trades,
        open_risk=round(position.risk_amount, 2) if position is not None else 0.0,
        unrealised=(
            round(position.unrealised(state.last_price), 2)
            if position is not None and state.last_price
            else 0.0
        ),
        has_position=position is not None,
        margin=round(position.margin, 2) if position is not None else 0.0,
        stale=behind > STALE_AFTER_MINUTES,
        behind_minutes=int(behind),
        activity=state.tally.sentence(),
    )


def account_equity(states: PaperStateStore, config: AppConfig) -> tuple[float, float, bool]:
    """Der Kontostand, der Höchststand, und ob wirklich gepoolt wird.

    **Die eine Stelle, an der diese Frage beantwortet wird.** Vorher stand
    sie an vier Stellen in drei Varianten, und eine davon summierte zwölf
    Zeilen, die alle denselben Stand tragen.

    Unter `basis: portfolio` ist die `portfolio`-Zeile die Wahrheit. Fehlt
    sie, läuft der Handel noch nicht unter der geteilten Kasse und die Summe
    der Einzelkonten ist der richtige Wert — das ist genau der Startwert, den
    `papertrade.shared_ledger` beim einmaligen Umschalten bildet.
    """
    pooled = config.risk.sizing.basis == "portfolio"
    saved = states.load_portfolio()
    if pooled and saved is not None:
        return saved[0], saved[1], True
    total = states.equity_sum()
    return total, total, pooled


def build_portfolio(
    state_path: Path,
    journal_path: Path,
    config: AppConfig,
    *,
    now_ms: int,
    deposit: float | None = None,
    signature: str | None = None,
) -> Portfolio:
    """Ein Konto, und was die Märkte darauf getan haben.

    Der Kontostand kommt aus **einer** Quelle (`account_equity`), die Beiträge
    der Märkte aus dem **Journal**. Keine Summe über Zustandszeilen — die
    tragen seit der Zusammenlegung alle denselben Stand, und ihre Summe war
    der Fehler, den dieses Modell behebt.
    """
    states = PaperStateStore(state_path)
    journal = JournalStore(journal_path)
    per_account = config.engine.simulation.initial_equity
    symbols = list(config.engine.symbols.active)

    live = journal.all(source=Source.LIVE)

    # Gehoert dieses Journal MEHREREN Konten, zaehlt nur das eigene.
    #
    # Ohne `signature` bleibt alles wie bisher -- das bestehende Konto ist das
    # einzige, das je unter seinen Signaturen gehandelt hat, und fuer es ist
    # die Begruendung unten richtig.
    #
    # Mit `signature` nicht: seit dem 19.10.2026 gibt es ein zweites
    # Papierkonto an demselben Journal. Ungefiltert zeigte seine Seite die
    # Marktbeitraege des ANDEREN Kontos -- "BTCUSDT -63,81" auf einem Konto,
    # das noch keinen Trade hatte, und "+279,79 USDT unerklaert" als Differenz.
    if signature:
        live = [entry for entry in live if entry.run_signature == signature]

    # Die Teilmenge, die zur LAUFENDEN Konfiguration gehoert.
    #
    # Beides muss stimmen: `run_signature` deckt die Konfiguration,
    # `decision_version` den Code. Eine Zeile ohne das eine oder das andere
    # faellt heraus, und das ist richtig -- am 16.10.2026 trugen 18 der 28
    # Vorwaertstrades gar keine Signatur, und sie sind aus den Daten keiner
    # Konfiguration zuzuordnen.
    #
    # Die Markt-Beitraege unten rechnen ueber alle Trades DIESES Kontos:
    # sein Kontostand hat sie bezahlt, und eine Tabelle, die nur die
    # laufende Epoche zeigt, wuerde den Kontostand nicht mehr erklaeren.
    # Nur die SCHLAGZEILE wird zusaetzlich auf eine Konfiguration
    # eingeschraenkt.
    current = current_era(live, config)

    closed = [entry for entry in live if entry.closed_ts]
    realised: dict[str, float] = {}
    counted: dict[str, int] = {}
    for entry in closed:
        realised[entry.symbol] = realised.get(entry.symbol, 0.0) + entry.net_pnl
        counted[entry.symbol] = counted.get(entry.symbol, 0) + 1

    rows: list[MarketRow] = []
    for symbol in symbols:
        saved = states.load(symbol)
        if saved is None:
            # Noch nicht gestartet ist ein Zustand, der gezeigt gehoert: der
            # Markt steht in der Konfiguration und hat einfach noch keine
            # Zeile. Ein leerer Bildschirm saehe aus wie ein Ausfall.
            saved = PaperState(symbol=symbol, equity=per_account)
        rows.append(_market_row(
            saved,
            realised=realised.get(symbol, 0.0),
            trades=counted.get(symbol, 0),
            now_ms=now_ms,
        ))

    equity, peak, pooled = account_equity(states, config)
    # Was eingezahlt wurde. Die Kasse entstand aus der Summe der Einzelkonten,
    # und jedes begann bei `initial_equity` -- also ist der Einsatz das
    # Produkt und nicht die Zahl aus der Konfiguration allein.
    # Was eingezahlt wurde.
    #
    # Die Herleitung `per_account * Maerkte` stimmt fuer das bestehende
    # Konto: es entstand aus zwoelf Einzelkonten zu je `initial_equity` und
    # wurde spaeter zusammengelegt. Fuer ein Konto, das von Anfang an EINE
    # Kasse ist, stimmt sie nicht -- das Plankonto startet mit 1.000 gesamt,
    # und die Herleitung machte daraus 12.000 und meldete -91,67 %.
    #
    # Darum uebergebbar. Ohne Angabe bleibt die alte Herleitung, also sieht
    # das bestehende Konto aus wie immer.
    start = deposit if deposit is not None else per_account * len(symbols)
    change = equity - start
    # Die Reservierung wird nicht gespeichert, sondern aus den offenen
    # Positionen hergeleitet -- dieselbe Herleitung wie in
    # `paperstate.restore_into`, damit es nur eine Definition gibt.
    reserved = sum(row.margin for row in rows)
    return Portfolio(
        equity=round(equity, 2),
        start=round(start, 2),
        change=round(change, 2),
        change_pct=round(100.0 * change / start, 3) if start else 0.0,
        peak=round(peak, 2),
        reserved=round(reserved, 2),
        available=round(max(0.0, equity - reserved), 2),
        open_risk=round(sum(row.open_risk for row in rows), 2),
        unexplained=round(change - sum(row.realised for row in rows), 2),
        markets=rows,
        trades=len(current),
        wins=sum(1 for entry in current if entry.won),
        mean_r=(
            round(sum(entry.r_multiple for entry in current) / len(current), 4)
            if current
            else 0.0
        ),
        total_r=round(sum(entry.r_multiple for entry in current), 3),
        trades_all=len(live),
        eras=era_count(live),
        running=any(not row.stale for row in rows),
        pooled=pooled,
    )


def _ledger_row(entry: JournalEntry) -> LedgerRow:
    reason = entry.reason
    post = entry.post_mortem
    return LedgerRow(
        trade_id=entry.trade_id,
        source=str(entry.source),
        closed_ts=entry.closed_ts,
        opened_ts=entry.opened_ts,
        symbol=entry.symbol,
        setup=reason.setup_key,
        setup_name=reason.setup_name,
        setup_timeframe=reason.setup_timeframe,
        side=reason.side,
        entry=entry.entry_price,
        exit=entry.exit_price,
        stop=reason.stop,
        target=reason.target,
        r_multiple=entry.r_multiple,
        net_pnl=entry.net_pnl,
        fees=entry.fees,
        exit_reason=entry.exit_reason.value,
        rating=reason.rating,
        rating_band=reason.rating_band,
        score_direction=reason.score_direction,
        agreed_with_score=reason.rating_agreed_with_setup,
        bars_held=post.bars_held,
        max_favourable_r=post.max_favourable_r,
        max_adverse_r=post.max_adverse_r,
        stopped_by_wick=post.stopped_by_wick,
        verdict=post.verdict,
    )


def _nur_dieses_konto(
    entries: list[JournalEntry], signature: str | None
) -> list[JournalEntry]:
    """Die Zeilen eines Kontos aus einem geteilten Journal.

    **Fuenfmal derselbe Fehler, an fuenf Stellen.** Seit dem 19.10.2026 gibt es
    zwei Papierkonten an EINEM Journal. Gefunden und einzeln behoben wurden:
    die Statusansicht des Papierhaendlers, der Kontostand im Dashboard, die
    Marktbeitraege, und jetzt Hauptbuch und Verlaufskurve.

    Jedes Mal dieselbe Form: ein Leser, der das geteilte Journal fuer sein
    eigenes hielt. Die RISIKOLOGIK hat nie gemischt -- sie filtert seit jeher
    ueber `closed_trades(signature=...)`. Nur die ANSICHTEN taten es, und eine
    Ansicht, die zwei Stichproben zusammenwirft, erzeugt genau die Zahl, die
    hinterher niemand nachrechnen kann.

    `None` heisst ausdruecklich "alles": das bestehende Konto hat unter drei
    Signaturen gehandelt -- 18 Zeilen ohne (von vor der Signatur), 9 vor und 6
    nach der Portfolioumstellung -- und sie gehoeren alle ihm.

    **Sechstes Mal, 20.10.2026 abends: der Name stimmte, die Rechnung nicht.**
    Hier stand ein Vergleich auf die GANZE Signatur, deren letztes Feld die
    Groessenregel traegt. Damit zeigte der Konto-Reiter "Trades 0" und
    "PNL Today +0 USD" fuer ein Konto, das am selben Tag elf Trades und
    -99 USD gemacht hatte -- waehrend der Hoechstrueckgang danebenstand und
    -10 % sagte, weil DER aus der Kapitalkurve kommt und nicht aus dem
    Journal. Zwei Grundgesamtheiten in einer Tafel.

    Der Schluessel kommt jetzt aus `journal/history.konto_schluessel`, also
    aus derselben Funktion, nach der seit heute Abend auch die Verlustbremsen
    zaehlen. Eine Ansicht, die ein anderes Konto zeigt als die Bremse zaehlt,
    waere schlimmer als beide Fehler einzeln.
    """
    if not signature:
        return entries
    schluessel = konto_schluessel(signature)
    return [e for e in entries if konto_schluessel(e.run_signature) == schluessel]


def build_ledger(
    journal_path: Path,
    *,
    source: Source,
    symbol: str | None = None,
    signature: str | None = None,
) -> Ledger:
    """Every trade of one kind, newest first.

    One kind, never both: a list that mixed replayed and forward trades would
    invite exactly the average this project refuses to compute.
    """
    journal = JournalStore(journal_path)
    entries = journal.all(source=source, symbol=symbol)
    # Nur die Zeilen DIESES Kontos, falls eins benannt ist. Siehe
    # `_nur_dieses_konto`.
    entries = _nur_dieses_konto(entries, signature)
    entries.sort(key=lambda e: e.closed_ts, reverse=True)
    shown = entries[:MAX_LEDGER]
    return Ledger(
        rows=[_ledger_row(entry) for entry in shown],
        total=len(entries),
        truncated=len(entries) > len(shown),
    )


def build_curve(
    journal_path: Path, *, source: Source, signature: str | None = None
) -> Curve:
    """The running total in R, oldest first, with how far it fell on the way.

    In R rather than francs because the account changed size: a franc curve
    across that boundary shows a cliff no trade caused.
    """
    journal = JournalStore(journal_path)
    entries = sorted(
        _nur_dieses_konto(journal.all(source=source), signature),
        key=lambda e: e.closed_ts,
    )

    points: list[CurvePoint] = []
    running = 0.0
    peak = 0.0
    drawdown = 0.0
    for index, entry in enumerate(entries, start=1):
        running += entry.r_multiple
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
        points.append(CurvePoint(ts=entry.closed_ts, cumulative_r=round(running, 4), trade=index))

    by_symbol: dict[str, float] = {}
    by_setup: dict[str, float] = {}
    for entry in entries:
        by_symbol[entry.symbol] = round(by_symbol.get(entry.symbol, 0.0) + entry.r_multiple, 3)
        key = entry.reason.setup_key
        by_setup[key] = round(by_setup.get(key, 0.0) + entry.r_multiple, 3)

    rs = [entry.r_multiple for entry in entries]
    return Curve(
        points=points,
        source=str(source),
        best_r=round(max(rs), 3) if rs else 0.0,
        worst_r=round(min(rs), 3) if rs else 0.0,
        peak_r=round(peak, 3),
        drawdown_r=round(drawdown, 3),
        by_symbol=by_symbol,
        by_setup=by_setup,
    )


def build_settings(config: AppConfig) -> SettingsView:
    """What every measurement in this project was taken under.

    Read-only, and the note says why. These are not preferences; they are the
    conditions the recorded results hold under, and a screen that let them be
    changed with a slider would quietly make the journal describe a system that
    no longer exists.
    """
    tiers = config.risk.sizing.tiers
    floor = min((tier.risk_pct for tier in tiers), default=0.0)
    return SettingsView(
        initial_equity=config.engine.simulation.initial_equity,
        account_start=(
            config.engine.simulation.initial_equity * len(config.engine.symbols.active)
        ),
        sizing_basis=config.risk.sizing.basis,
        risk_pct_floor=floor,
        max_leverage=config.risk.leverage.max,
        min_reward_risk=config.risk.limits.min_reward_risk,
        max_cost_fraction_of_risk=config.risk.limits.max_cost_fraction_of_risk,
        slippage_bps=config.engine.simulation.slippage_bps,
        setups_on=[setup.key for setup in TRADEABLE],
        signal_timeframe=config.engine.timeframes.signal.value,
        searched_timeframes=[tf.value for tf in config.engine.timeframes.context],
        note=(
            "Diese Werte sind die Bedingungen, unter denen jede Messung in diesem "
            "Projekt entstanden ist. Sie hier per Schieberegler zu ändern würde das "
            "Journal still zu einem Bericht über ein System machen, das es nicht "
            "mehr gibt. Wenn einer davon geändert werden soll, sag welcher — dann "
            "wird er geändert und neu gemessen."
        ),
    )


def top_up(state_path: Path, config: AppConfig, amount: float) -> float:
    """Papiergeld auf DAS Konto legen. Gibt den neuen Stand zurück.

    **Nahm bis zum 14.10.2026 ein Symbol entgegen.** Das war richtig, solange
    es zwölf Konten gab. Unter einer Kasse ist „500 USDT auf BTCUSDT
    einzahlen" keine Handlung, die es gibt — es gibt ein Konto, und man zahlt
    darauf ein.

    Papier. Es gibt von hier keinen Pfad zu einer Börse, und der Betrag wird
    addiert statt gesetzt, damit eine Einzahlung wie eine Einzahlung liest und
    die Geschichte des Kontos nicht umgeschrieben wird.
    """
    states = PaperStateStore(state_path)
    equity, peak, pooled = account_equity(states, config)
    after = equity + amount
    if pooled:
        # Nur die Portfoliozeile. Die zwölf Zustandszeilen zieht der laufende
        # Händler beim nächsten Zyklus nach -- sie sind Abschriften, keine
        # Quelle.
        states.save_portfolio(after, max(peak, after))
        return after
    # Ohne geteilte Kasse gibt es keinen gemeinsamen Topf; dann ist die
    # Einzahlung gleichmässig auf die bestehenden Konten verteilt, und das
    # wird gesagt statt stillschweigend auf eines gebucht.
    symbols = list(config.engine.symbols.active)
    share = amount / len(symbols) if symbols else 0.0
    for symbol in symbols:
        saved = states.load(symbol) or PaperState(
            symbol=symbol, equity=config.engine.simulation.initial_equity
        )
        saved.equity += share
        states.save(saved)
    return states.equity_sum()


def reset_account(state_path: Path, config: AppConfig, symbol: str | None = None) -> float:
    """Das Konto zurücksetzen, oder den Arbeitsstand eines Marktes.

    **Zwei Handlungen, und sie waren vorher eine.** Unter zwölf Konten war
    „BTCUSDT zurücksetzen" beides zugleich: Kontostand zurück auf 1.000 UND
    Zähler gelöscht. Unter einer Kasse sind es zwei verschiedene Dinge, und
    sie zu vermengen hiesse, dass ein Klick auf einen Markt das ganze Konto
    anfasst oder eben nicht — je nach Modus, und ohne dass es jemand sieht.

    Mit `symbol`: nur dieser Markt vergisst seinen Arbeitsstand (Zähler,
    Position, letzter Kurs). Der Kontostand bleibt.

    Ohne `symbol`: das Konto beginnt von vorn — alle Märkte vergessen, und die
    Kasse zurück auf den Einsatz.

    Das Journal bleibt in beiden Fällen unberührt: was passiert ist, ist
    passiert, und ein Zurücksetzen betrifft das Konto und nicht die Akte.
    """
    states = PaperStateStore(state_path)
    if symbol is not None:
        states.forget(symbol)
        return account_equity(states, config)[0]
    symbols = list(config.engine.symbols.active)
    for each in symbols:
        states.forget(each)
    start = config.engine.simulation.initial_equity * len(symbols)
    if config.risk.sizing.basis == "portfolio":
        states.save_portfolio(start, start)
    return start
