"""Ein Konto, nicht zwölf — und der Test, der gefehlt hat.

**Was am 14.10.2026 auf dem Bildschirm stand.**

    total_equity      144'906.72       = 12 x 12'075.56
    total_change     +132'906.72
    total_change_pct    +1107.6 %

Der Papierhandel führt seit dem 13.10.2026 **eine** Kasse. Die zwölf Zeilen in
der Tabelle `accounts` sind seitdem keine Konten mehr, sondern Arbeitsplätze
je Markt — und jede bekommt beim Speichern den **ganzen** geteilten Stand in
ihre `equity`-Spalte geschrieben, weil `PaperState.capture_from` schlicht
`broker.equity` liest und das der geteilte Stand ist.

`build_portfolio` summierte diese zwölf Zeilen.

**Das Bittere daran:** `tests/test_sizing_basis.py` beschreibt diese Falle
wörtlich — „wer sie beim Umschalten summiert und danach weiter summiert,
bekommt 144.900 statt 12.075" — und prüft sie auf der *Schreibseite*. Auf der
*Leseseite* gab es keinen einzigen Test; die API-Tests fassten
`/api/portfolio` nie an. Eine Falle, die man beschreibt und nur an einem Ende
absichert, ist eine Falle mit einem offenen Ende.

Diese Datei schliesst das andere Ende.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.factories import make_symbol_spec
from tests.test_journal_history import SIG, entry
from traidingbrain.api.portfolio import (
    account_equity,
    build_portfolio,
    reset_account,
    top_up,
)
from traidingbrain.clock import FixedClock
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Side
from traidingbrain.journal.signals import SignalStore
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.book import OpenBook
from traidingbrain.live.paper import PaperTrader
from traidingbrain.live.paperstate import PaperState, PaperStateStore
from traidingbrain.risk.limits import RiskLimits
from traidingbrain.sim.plan import TradeIntent, assess

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOW = 1_791_900_000_000

#: Der gemessene Fall vom 14.10.2026.
POOL = 12_075.56
PER_ACCOUNT = 1_000.0


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config(PROJECT_ROOT / "config")


def with_basis(config: AppConfig, basis: str) -> AppConfig:
    return config.model_copy(update={"risk": config.risk.model_copy(
        update={"sizing": config.risk.sizing.model_copy(update={"basis": basis})}
    )})


def pooled_store(tmp_path: Path, config: AppConfig, *, pool: float = POOL) -> PaperStateStore:
    """Der Zustand, den der laufende Händler wirklich hinterlässt.

    Zwölf Zeilen, jede mit dem GETEILTEN Stand, plus die Portfoliozeile. Genau
    so sieht `data/paper.sqlite` aus, seit die Kassen zusammengelegt sind --
    nachgesehen, nicht angenommen.
    """
    store = PaperStateStore(tmp_path / "paper.sqlite")
    for symbol in config.engine.symbols.active:
        store.save(PaperState(symbol=symbol, equity=pool, last_minute_ts=NOW))
    store.save_portfolio(pool, pool)
    return store


def portfolio_of(tmp_path: Path, config: AppConfig):
    return build_portfolio(
        tmp_path / "paper.sqlite", tmp_path / "journal.sqlite", config, now_ms=NOW
    )


# --------------------------------------------------------------------------- #
# Der Fehler selbst
# --------------------------------------------------------------------------- #


def test_the_account_is_not_the_sum_of_the_markets(tmp_path: Path, config: AppConfig) -> None:
    """Der Test, der am 14.10.2026 gefehlt hat.

    Haette es ihn gegeben, waere die Zusammenlegung am Tag davor rot geworden
    statt mit +1.107 % auf dem Bildschirm zu landen.
    """
    pooled = with_basis(config, "portfolio")
    store = pooled_store(tmp_path, pooled)
    JournalStore(tmp_path / "journal.sqlite")

    view = portfolio_of(tmp_path, pooled)

    markets = len(pooled.engine.symbols.active)
    assert view.equity == pytest.approx(POOL)
    assert view.equity != pytest.approx(markets * POOL), (
        f"die Summe der {markets} Zeilen waere {markets * POOL:,.2f} -- genau "
        f"die Zahl, die das Dashboard gemeldet hat"
    )
    # Und die Vorbedingung: die Zeilen tragen wirklich alle denselben Stand,
    # sonst prueft dieser Test eine Lage, die es nicht gibt.
    assert store.equity_sum() == pytest.approx(markets * POOL)


def test_the_change_is_measured_against_what_was_paid_in(
    tmp_path: Path, config: AppConfig
) -> None:
    """12.000 hinein, 12.075,56 drin, also +0,63 % -- nicht +1.107 %."""
    pooled = with_basis(config, "portfolio")
    pooled_store(tmp_path, pooled)

    view = portfolio_of(tmp_path, pooled)

    assert view.start == pytest.approx(PER_ACCOUNT * len(pooled.engine.symbols.active))
    assert view.change == pytest.approx(POOL - view.start, abs=0.01)
    assert view.change_pct == pytest.approx(0.63, abs=0.01)


def test_no_market_carries_a_balance(tmp_path: Path, config: AppConfig) -> None:
    """Ein Markt hat keinen Kontostand, und das Modell kennt auch keinen.

    Gegen das Feld geprueft und nicht gegen die Anzeige: solange `MarketRow`
    keine Spalte `equity` hat, kann niemand sie versehentlich summieren.
    """
    pooled = with_basis(config, "portfolio")
    pooled_store(tmp_path, pooled)

    view = portfolio_of(tmp_path, pooled)

    assert view.markets, "keine Maerkte -- dann prueft der Test nichts"
    fields = set(type(view.markets[0]).model_fields)
    assert "equity" not in fields
    assert "start_equity" not in fields
    assert "realised" in fields


def test_a_markets_contribution_comes_from_the_journal(
    tmp_path: Path, config: AppConfig
) -> None:
    """Der Beitrag steht im Journal, nicht in der Zustandszeile.

    Die Zustandszeile kennt nur den geteilten Stand; das Journal kennt die
    Trades. Darum ist das die einzige Quelle, aus der ein Beitrag je Markt
    ueberhaupt kommen kann.
    """
    pooled = with_basis(config, "portfolio")
    pooled_store(tmp_path, pooled)
    first, second = pooled.engine.symbols.active[0], pooled.engine.symbols.active[1]
    JournalStore(tmp_path / "journal.sqlite").record([  # type: ignore[arg-type]
        entry("live-1", symbol=first, closed_ts=NOW - 3_600_000, net_pnl=+28.95),
        entry("live-2", symbol=first, closed_ts=NOW - 7_200_000, net_pnl=-8.44),
        entry("live-3", symbol=second, closed_ts=NOW - 3_600_000, net_pnl=-11.17),
    ])

    view = portfolio_of(tmp_path, pooled)
    by_symbol = {row.symbol: row for row in view.markets}

    assert by_symbol[first].realised == pytest.approx(20.51)
    assert by_symbol[first].trades == 2
    assert by_symbol[second].realised == pytest.approx(-11.17)
    assert by_symbol[second].trades == 1


def test_the_gap_between_account_and_journal_is_reported(
    tmp_path: Path, config: AppConfig
) -> None:
    """Die Abstimmung, die am 14.10.2026 +55,05 USDT offen laesst.

    Das Konto haelt ein Ergebnis, das kein journalisierter Trade erklaert --
    ein Trade aus einer zerstoerten Generation. Diese Zahl gehoert auf den
    Bildschirm und nicht in einen Bericht: eine Abstimmung, die nur dann
    sichtbar ist, wenn sie aufgeht, ist keine.
    """
    pooled = with_basis(config, "portfolio")
    pooled_store(tmp_path, pooled)
    JournalStore(tmp_path / "journal.sqlite").record([  # type: ignore[arg-type]
        entry("live-1", symbol=pooled.engine.symbols.active[0],
              closed_ts=NOW - 3_600_000, net_pnl=+20.51),
    ])

    view = portfolio_of(tmp_path, pooled)

    assert view.unexplained == pytest.approx(POOL - 12_000.0 - 20.51, abs=0.01)
    assert view.unexplained == pytest.approx(55.05, abs=0.01)


# --------------------------------------------------------------------------- #
# Die eine Quelle
# --------------------------------------------------------------------------- #


def test_the_portfolio_row_wins_over_the_market_rows(
    tmp_path: Path, config: AppConfig
) -> None:
    """Auch wenn die Marktzeilen etwas anderes sagen."""
    pooled = with_basis(config, "portfolio")
    store = pooled_store(tmp_path, pooled)
    # Eine Zeile laeuft auseinander -- etwa weil der Haendler mitten im Zyklus
    # abgestuerzt ist. Die Portfoliozeile bleibt die Wahrheit.
    store.save(PaperState(symbol=pooled.engine.symbols.active[0], equity=999.0))

    equity, peak, is_pooled = account_equity(store, pooled)

    assert equity == pytest.approx(POOL)
    assert peak == pytest.approx(POOL)
    assert is_pooled is True


def test_without_a_portfolio_row_the_sum_is_right(
    tmp_path: Path, config: AppConfig
) -> None:
    """Der erste Lauf: noch keine Kasse, also IST die Summe der Startwert.

    Genau das bildet `papertrade.shared_ledger` beim einmaligen Umschalten,
    und hier darf nicht dieselbe Zahl zweimal entstehen.
    """
    pooled = with_basis(config, "portfolio")
    store = PaperStateStore(tmp_path / "paper.sqlite")
    for symbol in pooled.engine.symbols.active:
        store.save(PaperState(symbol=symbol, equity=PER_ACCOUNT))

    equity, _peak, _is_pooled = account_equity(store, pooled)

    assert equity == pytest.approx(PER_ACCOUNT * len(pooled.engine.symbols.active))


def test_account_basis_keeps_the_old_meaning(tmp_path: Path, config: AppConfig) -> None:
    """Ohne geteilte Kasse sind es wieder getrennte Konten, und die Summe stimmt."""
    separate = with_basis(config, "account")
    store = PaperStateStore(tmp_path / "paper.sqlite")
    for symbol in separate.engine.symbols.active:
        store.save(PaperState(symbol=symbol, equity=PER_ACCOUNT, last_minute_ts=NOW))

    equity, _peak, is_pooled = account_equity(store, separate)

    assert is_pooled is False
    assert equity == pytest.approx(PER_ACCOUNT * len(separate.engine.symbols.active))


# --------------------------------------------------------------------------- #
# Einzahlen und zuruecksetzen
# --------------------------------------------------------------------------- #


def test_a_deposit_goes_to_the_account_and_not_to_a_market(
    tmp_path: Path, config: AppConfig
) -> None:
    """500 einzahlen heisst 500 mehr -- nicht 6.000, und nicht 500 auf BTC."""
    pooled = with_basis(config, "portfolio")
    store = pooled_store(tmp_path, pooled)

    after = top_up(tmp_path / "paper.sqlite", pooled, 500.0)

    assert after == pytest.approx(POOL + 500.0)
    assert store.load_portfolio()[0] == pytest.approx(POOL + 500.0)  # type: ignore[index]


def test_a_deposit_raises_the_peak_with_it(tmp_path: Path, config: AppConfig) -> None:
    """Sonst meldet die Oberflaeche sofort einen Rueckgang vom Hoechststand,
    der nur aus der Einzahlung kommt."""
    pooled = with_basis(config, "portfolio")
    store = pooled_store(tmp_path, pooled)

    top_up(tmp_path / "paper.sqlite", pooled, 500.0)

    _equity, peak = store.load_portfolio()  # type: ignore[misc]
    assert peak == pytest.approx(POOL + 500.0)


def test_resetting_one_market_leaves_the_account_alone(
    tmp_path: Path, config: AppConfig
) -> None:
    """Der gefaehrliche Klick, entschaerft.

    Unter zwoelf Konten setzte "BTCUSDT zuruecksetzen" ein Konto auf 1.000.
    Unter einer Kasse darf derselbe Klick den Kontostand NICHT anfassen --
    sonst loescht ein Klick auf einen Markt das Geld aller zwoelf.
    """
    pooled = with_basis(config, "portfolio")
    store = pooled_store(tmp_path, pooled)
    first = pooled.engine.symbols.active[0]

    reset_account(tmp_path / "paper.sqlite", pooled, first)

    assert store.load(first) is None, "der Arbeitsstand muss weg sein"
    assert store.load_portfolio()[0] == pytest.approx(POOL)  # type: ignore[index]


def test_resetting_the_account_puts_the_stake_back(
    tmp_path: Path, config: AppConfig
) -> None:
    pooled = with_basis(config, "portfolio")
    store = pooled_store(tmp_path, pooled)
    markets = len(pooled.engine.symbols.active)

    after = reset_account(tmp_path / "paper.sqlite", pooled)

    assert after == pytest.approx(PER_ACCOUNT * markets)
    assert store.load_portfolio()[0] == pytest.approx(PER_ACCOUNT * markets)  # type: ignore[index]
    assert store.equity_sum() == pytest.approx(0.0), "alle Marktzeilen vergessen"


# --------------------------------------------------------------------------- #
# Zwei Geltungsbereiche, und warum sie verschieden sind
# --------------------------------------------------------------------------- #


def trader_on_pool(tmp_path: Path, config: AppConfig, *, book: object, history: list):
    """Ein echter Haendler am gepoolten Konto, mit echtem Journal."""
    journal = JournalStore(tmp_path / "journal.sqlite")
    if history:
        journal.record(history)  # type: ignore[arg-type]
    return PaperTrader(
        "BTCUSDT",
        config,
        source=None,
        store=ParquetStore(tmp_path / "ohlcv"),
        state=PaperStateStore(tmp_path / "paper.sqlite"),
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(NOW),
        signals=SignalStore(tmp_path / "signals.sqlite"),
        run_signature=SIG,
        limits=RiskLimits(config.risk.limits),
        book=book,  # type: ignore[arg-type]
    )


def test_the_day_limit_counts_every_market(tmp_path: Path, config: AppConfig) -> None:
    """Der Fehler, den das Audit am 14.10.2026 gefunden hat.

    Die Tagesgrenze sagt "verliere an einem Tag nicht mehr als 5 % des
    Kontos". Gemessen wurde aber der Verlust EINES Symbols gegen das Kapital
    ALLER zwoelf -- Zaehler und Nenner gehoerten verschiedenen Dingen, und der
    Deckel war dadurch zwoelfmal schwerer auszuloesen, als er dasteht.

    Hier verliert jeder Markt ein Stueck, keiner allein genug. Zusammen
    reissen sie den Deckel, und genau das muss die Bremse sehen.
    """
    pooled = with_basis(config, "portfolio")
    hour = 3_600_000
    # Zwoelf Maerkte, je ein Verlust von 60 USDT: zusammen 720 und damit ueber
    # 5 % von 12.075,56 (= 603,78). Einzeln ist keiner auch nur in der Naehe.
    history = [
        entry(f"live-{symbol}", symbol=symbol, closed_ts=NOW - hour,
              net_pnl=-60.0, run_signature=SIG)
        for symbol in pooled.engine.symbols.active
    ]
    trader = trader_on_pool(tmp_path, pooled, book=OpenBook(), history=history)
    trader.broker.ledger.equity = POOL

    blocked = trader._blocked_by_limits(NOW)

    assert blocked is not None, (
        "zwoelf Maerkte haben zusammen 720 USDT verloren, der Tagesdeckel "
        "liegt bei 603.78 -- die Bremse muss greifen"
    )
    assert "daily limit" in blocked


def test_one_market_alone_does_not_trip_the_day_limit(
    tmp_path: Path, config: AppConfig
) -> None:
    """Die Gegenprobe: ein Markt allein reisst den Kontodeckel nicht."""
    pooled = with_basis(config, "portfolio")
    # Zwei Verluste, nicht drei: drei wuerden die Abkuehlung ausloesen, und
    # dann prueefte dieser Test die andere Grenze. 200 USDT liegen deutlich
    # unter dem Tagesdeckel von 603,78.
    history = [
        entry(f"live-btc-{i}", symbol="BTCUSDT", closed_ts=NOW - 3_600_000,
              net_pnl=-100.0, run_signature=SIG)
        for i in range(2)
    ]
    trader = trader_on_pool(tmp_path, pooled, book=OpenBook(), history=history)
    trader.broker.ledger.equity = POOL

    assert trader._blocked_by_limits(NOW) is None


def test_the_cooldown_stays_a_market_question(tmp_path: Path, config: AppConfig) -> None:
    """Die Verlustserie zaehlt je MARKT, auch unter einem Konto.

    Begruendet und nicht nebenbei: bei einer Erwartung um null ist eine
    Dreierserie ueber zwoelf parallele Maerkte Alltag, und die Abkuehlung
    haette den Handel dauernd angehalten. Ob der richtige Geltungsbereich das
    Konto ist, ist eine Messfrage -- hier steht nur, dass sie nicht
    stillschweigend anders beantwortet wurde.
    """
    pooled = with_basis(config, "portfolio")
    hour = 3_600_000
    # Drei Verluste in Folge, aber auf drei VERSCHIEDENEN Maerkten, und klein
    # genug, dass der Tagesdeckel nicht greift.
    history = [
        entry(f"live-{symbol}", symbol=symbol, closed_ts=NOW - (3 - i) * hour,
              net_pnl=-5.0, run_signature=SIG)
        for i, symbol in enumerate(["ETHUSDT", "SOLUSDT", "XRPUSDT"])
    ]
    trader = trader_on_pool(tmp_path, pooled, book=OpenBook(), history=history)
    trader.broker.ledger.equity = POOL

    assert trader._blocked_by_limits(NOW) is None, (
        "drei Verluste auf drei fremden Maerkten sind keine Verlustserie von "
        "BTCUSDT -- sonst haelt ein Markt alle zwoelf an"
    )


def test_a_streak_on_the_own_market_still_blocks(
    tmp_path: Path, config: AppConfig
) -> None:

    pooled = with_basis(config, "portfolio")
    hour = 3_600_000
    history = [
        entry(f"live-btc-{i}", symbol="BTCUSDT", closed_ts=NOW - (3 - i) * hour,
              net_pnl=-5.0, run_signature=SIG)
        for i in range(3)
    ]
    trader = trader_on_pool(tmp_path, pooled, book=OpenBook(), history=history)
    trader.broker.ledger.equity = POOL

    blocked = trader._blocked_by_limits(NOW)

    assert blocked is not None
    assert "losses in a row" in blocked


# --------------------------------------------------------------------------- #
# Die Groesse, die der Nutzer verlangt hat
# --------------------------------------------------------------------------- #


def test_a_signal_risks_one_percent_of_the_account(config: AppConfig) -> None:
    """Der eigentliche Wunsch, als Test: 1 % vom KONTO, nicht vom Zwoelftel.

    "Anstatt nur mit irgendwie 60 gehst du mit 600 in Trade" -- gemessen sind
    es 805 USDT Margin auf 8.050 Notional, bei 120,75 USDT Risiko.

    Bis zum 13.10.2026 waren es 10,06 USDT, weil jedes Symbol gegen sein
    eigenes Zwoelftel groesste. Dieser Test bindet die Groesse an den
    Kontostand, damit die Umstellung nicht still zurueckfallen kann -- zum
    Beispiel dadurch, dass irgendwer `equity=` wieder aus einer Marktzeile
    holt statt aus dem Broker.
    """
    pool = 12_075.56
    intent = TradeIntent(
        side=Side.LONG, entry=100.0, stop=98.5, target=104.5,
        confidence=70.0, reason="A Momentum-Breakout (V08): Probe",
    )
    verdict = assess(
        intent, None, symbol="BTCUSDT", spec=make_symbol_spec(), config=config,
        equity=pool, created_ts=NOW, expires_ts=NOW + 8 * 15 * 60_000,
    )

    assert verdict.refused_by is None, verdict.detail
    cap = config.risk.sizing.uncalibrated_cap_risk_pct
    assert verdict.risk_amount == pytest.approx(pool * cap, rel=1e-4), (
        f"erwartet {pool * cap:,.2f} USDT Risiko (= {cap:.1%} des Kontos), "
        f"gemessen {verdict.risk_amount:,.2f}"
    )
    # Und die Gegenprobe: an einem Zwoelftel waere es ein Zwoelftel.
    twelfth = assess(
        intent, None, symbol="BTCUSDT", spec=make_symbol_spec(), config=config,
        equity=pool / 12, created_ts=NOW, expires_ts=NOW + 8 * 15 * 60_000,
    )
    assert verdict.risk_amount == pytest.approx(12 * twelfth.risk_amount, rel=1e-3)


def test_the_paper_trader_hands_the_pool_to_the_sizing(tmp_path: Path) -> None:
    """Und die Verdrahtung: `assess` bekommt `broker.equity`, nicht die Zeile.

    Eine Quelltextregel, weil genau diese Stelle der Unterschied zwischen
    10 und 121 USDT je Trade ist und in einem Aufruf mit acht Argumenten
    nicht auffaellt.
    """
    source = (PROJECT_ROOT / "src" / "traidingbrain" / "live" / "paper.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "assess"
    ]
    assert calls, "kein assess-Aufruf in live/paper.py gefunden -- Waechter blind"
    for call in calls:
        equity = next((k.value for k in call.keywords if k.arg == "equity"), None)
        assert equity is not None, f"assess ohne equity= in Zeile {call.lineno}"
        assert ast.unparse(equity) == "self.broker.equity", (
            f"assess bekommt in Zeile {call.lineno} `{ast.unparse(equity)}` statt "
            "`self.broker.equity` -- die Groesse haengt dann nicht mehr an der "
            "geteilten Kasse"
        )


# --------------------------------------------------------------------------- #
# Der Waechter gegen den naechsten Summierer
# --------------------------------------------------------------------------- #


def test_nothing_sums_a_balance_over_markets() -> None:
    """Eine Quelltext-Regel, weil der Fehler zweimal unabhaengig entstand.

    Einmal in `api/portfolio.py` (`sum(row.equity for row in rows)`) und
    einmal in `scripts/goal.py` (`equity += state.equity` in einer Schleife
    ueber die Maerkte). Zwei Dateien, dieselbe Verwechslung, und beide Male
    sah es wie gewoehnliche Arithmetik aus.

    Der Waechter prueft sich zuerst selbst: er muss ein gepflanztes Beispiel
    finden, sonst bestaende er auch an einem geloeschten Baum.
    """
    pattern = re.compile(
        r"sum\s*\(\s*\w+\.equity\s+for|"          # sum(row.equity for ...)
        r"\w+\s*\+=\s*\w+\.equity\b"              # equity += state.equity
    )
    planted = "total = sum(row.equity for row in rows)"
    assert pattern.search(planted), "der Waechter findet nicht einmal sein eigenes Beispiel"

    scanned = 0
    offenders: list[str] = []
    for path in sorted((PROJECT_ROOT / "src").rglob("*.py")) + sorted(
        (PROJECT_ROOT / "scripts").rglob("*.py")
    ):
        text = path.read_text(encoding="utf-8")
        scanned += 1
        # Kommentare und Docstrings zaehlen nicht: diese Datei und mehrere
        # andere BESCHREIBEN den Fehler, und ein Waechter, der seine eigene
        # Erklaerung anzeigt, wird abgeschaltet.
        code = ast.unparse(ast.parse(text))
        for line in code.splitlines():
            if pattern.search(line):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {line.strip()}")

    assert scanned > 100, f"nur {scanned} Dateien gescannt -- Waechter blind"
    assert not offenders, (
        "ein Kontostand wird ueber Maerkte summiert; unter einer geteilten "
        f"Kasse ist das das Zwoelffache: {offenders}"
    )
