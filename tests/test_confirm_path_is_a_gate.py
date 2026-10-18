"""Der Bestätigungspfad muss ein Tor sein, nicht eine Anzeige.

**Der Anlass.** Gefunden beim Kartieren für P1, bestätigt an vier Stellen:

    builder.build()     prueft `limits.check` -- builder.py:260
    builder.adjust()    prueft NICHT
    POST /token         prueft nur die Preisdrift -- app.py:389
    POST /confirm       prueft Kill-Switch, Token, CAS -- app.py:405
    app.py:315          `limits.check` nur fuer die ANZEIGE

Tagesverlust, Wochenverlust, Abkühlung nach Verlustserie und Platzdeckel sind
auf dem Weg vom Vorschlag zur Order also kein Tor. Das Abnahmekriterium von
Stufe 7 des Bauplans lautet aber ausdrücklich: *„Änderung 5x→4x rechnet
Grösse, Risiko und Liquidation sofort neu **und läuft erneut durch den
Guard**."*

**Und der Kontozustand, gegen den geprüft würde, kann nicht auslösen.**
`run_dashboard.py:238` baut `services.account` EINMAL beim Start, mit
gefrorenem `now_ms` und ohne `open_positions`. Die beiden Positionsprüfungen
rechnen damit `0 >= 5` und `0 >= 1`; die Verlustfenster beziehen sich auf den
Startzeitpunkt. Genau dieser Defekt ist für den Papierhändler in
`live/book.py` beschrieben und behoben — der Ausführungspfad hat ihn noch.

Eine Schutzregel, die aus dem falschen Grund hält, ist keine Schutzregel: sie
hielte weiter, still, wenn der Grund wegfiele.
"""

from __future__ import annotations

import pytest

from traidingbrain.config.settings import load_config
from traidingbrain.domain.enums import Side, TradeState
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.domain.proposal import Position
from traidingbrain.risk.limits import AccountState, ClosedTrade, RiskLimits

SYMBOL = "BTCUSDT"
NOW = 1_700_000_000_000
SPEC = SymbolSpec(symbol=SYMBOL, **DEFAULT_SPEC)


def _position(symbol: str = SYMBOL) -> Position:
    return Position(
        symbol=symbol,
        side=Side.LONG,
        qty=0.01,
        entry_price=50_000.0,
        leverage=5.0,
        liquidation_price=40_000.0,
        opened_ts=NOW - 3_600_000,
    )


def _konto(
    *,
    positions: list[Position] | None = None,
    equity: float = 1_000.0,
    tagesstart: float | None = None,
    now_ms: int = NOW,
    serie: list[ClosedTrade] | None = None,
) -> AccountState:
    return AccountState(
        equity=equity,
        starting_equity_today=tagesstart if tagesstart is not None else equity,
        starting_equity_this_week=tagesstart if tagesstart is not None else equity,
        open_positions=positions or [],
        recent_trades=[],
        now_ms=now_ms,
        streak_trades=serie,
    )


# --------------------------------------------------------------------------- #
# Was ein leerer Positionszustand bedeutet
# --------------------------------------------------------------------------- #


def test_ohne_offene_positionen_kann_der_platzdeckel_nicht_ausloesen(
    limits: RiskLimits,
) -> None:
    """Der Zustand, den `run_dashboard.py:238` erzeugt.

    Dieser Test behauptet nicht, dass das richtig ist -- er nagelt fest, was
    der leere Zustand bedeutet, damit der Unterschied zum gefüllten sichtbar
    ist.
    """
    verdict = limits.check(_konto(), symbol=SYMBOL)
    assert verdict.allowed
    assert not any("already open" in b for b in verdict.blockers)


def test_mit_vollen_plaetzen_loest_der_deckel_aus(limits: RiskLimits) -> None:
    voll = [_position(f"SYM{i}USDT") for i in range(limits.config.max_open_positions)]
    verdict = limits.check(_konto(positions=voll), symbol="NEUUSDT")
    assert not verdict.allowed
    assert any("already open" in b for b in verdict.blockers)


def test_eine_zweite_position_im_selben_symbol_loest_aus(limits: RiskLimits) -> None:
    verdict = limits.check(_konto(positions=[_position()]), symbol=SYMBOL)
    assert not verdict.allowed
    assert any(SYMBOL in b for b in verdict.blockers)


# --------------------------------------------------------------------------- #
# Der Tagesdeckel
# --------------------------------------------------------------------------- #


def test_der_tagesdeckel_liest_die_trades_nicht_das_eigenkapital(
    limits: RiskLimits,
) -> None:
    """`realised_today()` summiert `recent_trades`, nicht die Equity-Differenz.

    Zuerst stand hier ein Test, der `equity=940` gegen
    `starting_equity_today=1000` setzte und ein Blocken erwartete. Er fiel
    durch, und zu Recht: `limits.py:225` rechnet `-state.realised_today()`,
    und das ist eine Summe ueber die Trades. Ein Konto, dessen Eigenkapital
    gefallen ist, ohne dass ein Trade abgeschlossen wurde -- etwa durch
    unrealisierte Verluste -- loest den Tagesdeckel NICHT aus.

    Das ist vertretbar: der Deckel heisst "verliere an einem Tag nicht mehr
    als 5 % REALISIERT". Es ist nur nicht dasselbe wie "das Konto ist um 5 %
    gefallen", und der Unterschied gehoert benannt.
    """
    ohne_trades = limits.check(
        _konto(equity=940.0, tagesstart=1_000.0), symbol=SYMBOL
    )
    assert ohne_trades.allowed, (
        "ohne abgeschlossene Trades greift der Tagesdeckel nicht, auch wenn "
        "das Eigenkapital 6 % gefallen ist"
    )

    # 6 % realisiert verteilt auf sechs Trades.
    verluste = [_verlust(NOW - (i + 1) * 60_000, pnl=-10.0) for i in range(6)]
    mit_trades = AccountState(
        equity=940.0,
        starting_equity_today=1_000.0,
        starting_equity_this_week=1_000.0,
        open_positions=[],
        recent_trades=verluste,
        now_ms=NOW,
        streak_trades=[],
    )
    verdict = limits.check(mit_trades, symbol=SYMBOL)
    assert not verdict.allowed
    assert any("daily limit" in b for b in verdict.blockers), verdict.blockers


def test_ein_knapper_tagesverlust_blockt_nicht(limits: RiskLimits) -> None:
    """4 % realisiert bleibt unter dem 5-%-Deckel."""
    verluste = [_verlust(NOW - (i + 1) * 60_000, pnl=-10.0) for i in range(4)]
    state = AccountState(
        equity=960.0,
        starting_equity_today=1_000.0,
        starting_equity_this_week=1_000.0,
        open_positions=[],
        recent_trades=verluste,
        now_ms=NOW,
        streak_trades=[],
    )
    verdict = limits.check(state, symbol=SYMBOL)
    assert verdict.allowed, verdict.blockers


# --------------------------------------------------------------------------- #
# Die Abkühlung, und warum die Uhr nicht stehen darf
# --------------------------------------------------------------------------- #


def _verlust(ts: int, *, pnl: float = -10.5) -> ClosedTrade:
    """Ein abgeschlossener Verlusttrade, mit allen Pflichtfeldern.

    `ClosedTrade` ist ein Pydantic-Modell mit `extra="forbid"` -- eine
    Teilmenge der Felder zu uebergeben schlaegt fehl statt stillschweigend
    Vorgaben einzusetzen. Das ist richtig so.
    """
    return ClosedTrade(
        proposal_id=f"{SYMBOL}-{ts}",
        snapshot_hash="0" * 16,
        symbol=SYMBOL,
        side=Side.LONG,
        state=TradeState.CLOSED_STOP,
        qty=0.01,
        entry_price=50_000.0,
        exit_price=49_000.0,
        opened_ts=ts - 3_600_000,
        closed_ts=ts,
        gross_pnl=-10.0,
        fees=0.5,
        funding=0.0,
        net_pnl=pnl,
        r_multiple=-1.0,
    )


def test_drei_verluste_hintereinander_loesen_die_abkuehlung_aus(
    limits: RiskLimits,
) -> None:
    n = limits.config.cooldown_after_consecutive_losses
    serie = [_verlust(NOW - (i + 1) * 60_000) for i in range(n)]
    verdict = limits.check(_konto(serie=serie), symbol=SYMBOL)
    assert not verdict.allowed
    assert any("cool" in b.lower() or "abk" in b.lower() for b in verdict.blockers), (
        verdict.blockers
    )


def test_eine_stehende_uhr_blockt_mehr_nicht_weniger(
    limits: RiskLimits,
) -> None:
    """Die Richtung des Startzeit-Defekts, gemessen statt vermutet.

    Zuerst stand hier die Erwartung, eine stehen gebliebene Uhr liesse die
    Abkühlung ablaufen. Der Test fiel durch, und die Messung sagt das
    Gegenteil: liegen die Verluste in der ZUKUNFT des Zustands, ist
    `now_ms - last_loss` negativ und die Restzeit grösser als der Deckel --
    es wird MEHR geblockt, nicht weniger.

    Dasselbe gilt für die Verlustfenster. `limits.py:165` rechnet
    `cutoff = now_ms - DAY_MS` und summiert alles danach; mit gefrorener Uhr
    ist das Fenster `[T0 - 24h, unendlich)`, wächst also unbegrenzt und
    sammelt jeden späteren Verlust ein.

    `run_dashboard.py:238` setzt `now_ms` genau einmal beim Start. Der Defekt
    ist damit real, irrt aber auf die sichere Seite. Der eindeutige Defekt
    desselben Aufrufs ist ein anderer: `open_positions` wird nicht
    übergeben, also ist die Liste leer und die beiden Positionsprüfungen
    rechnen `0 >= 5` und `0 >= 1`.
    """
    n = limits.config.cooldown_after_consecutive_losses
    serie = [_verlust(NOW - (i + 1) * 60_000) for i in range(n)]

    jetzt = limits.check(_konto(serie=serie, now_ms=NOW), symbol=SYMBOL)
    assert not jetzt.allowed

    gefroren = limits.check(
        _konto(serie=serie, now_ms=NOW - 48 * 3_600_000), symbol=SYMBOL
    )
    assert not gefroren.allowed, "eine stehende Uhr blockt ebenfalls"

    rest_jetzt = _reststunden(jetzt.blockers)
    rest_gefroren = _reststunden(gefroren.blockers)
    assert rest_gefroren > rest_jetzt, (
        f"gefroren {rest_gefroren:.1f}h soll groesser sein als jetzt "
        f"{rest_jetzt:.1f}h -- der Defekt ueberblockt"
    )


def _reststunden(blockers: list[str]) -> float:
    for b in blockers:
        if "cooling off for another" in b:
            return float(b.split("another ")[1].rstrip("h"))
    raise AssertionError(f"keine Abkuehlungsmeldung in {blockers}")


def test_das_tagesfenster_waechst_mit_gefrorener_uhr_unbegrenzt(
    limits: RiskLimits,
) -> None:
    """`[now - 24h, unendlich)` ist kein Tagesfenster.

    Ein Verlust, der 10 Tage NACH dem gefrorenen `now_ms` abgeschlossen wurde,
    zaehlt immer noch in den "heutigen" Verlust hinein.
    """
    spaet = _verlust(NOW + 10 * 86_400_000, pnl=-60.0)
    state = AccountState(
        equity=940.0,
        starting_equity_today=1_000.0,
        starting_equity_this_week=1_000.0,
        open_positions=[],
        recent_trades=[spaet],
        now_ms=NOW,
        streak_trades=[],
    )
    assert state.realised_today() == pytest.approx(-60.0), (
        "ein Trade zehn Tage in der Zukunft des Zustands zaehlt als 'heute'"
    )
    assert not limits.check(state, symbol=SYMBOL).allowed


# --------------------------------------------------------------------------- #
# Fixture
# --------------------------------------------------------------------------- #


@pytest.fixture
def limits() -> RiskLimits:
    """Die ECHTE Konfiguration, nicht eine erfundene.

    Ein Deckel, der im Test anders steht als in `config/risk.yaml`, prueft
    nicht die Regel, unter der gehandelt wird.
    """
    return RiskLimits(load_config().risk.limits)
