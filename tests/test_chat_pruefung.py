"""Regelpruefung des Chats: acht feste Regeln, `unbekannt` lehnt ab."""

from __future__ import annotations

from traidingbrain.api.chat.modelle import Lage, Regelwerte, Setup, Urteil, Vorschlag
from traidingbrain.api.chat.pruefung import pruefe, regelwerte_aus
from traidingbrain.config.settings import load_config
from traidingbrain.domain.enums import Side
from traidingbrain.domain.proposal import Position
from traidingbrain.risk.limits import AccountState, KillSwitch, LimitVerdict, RiskLimits

JETZT = 1_800_000_000_000
PREIS = 82_597.0
# Abweichung vom Brief: dort 83_400 (0.97 % Abstand). Mit Kosten 0.1 % je Umlauf
# kosten die 10.3 % des Risikos und scheitern an der 8-%-Grenze -- unabhaengig
# von der Groesse. 83_700 (1.34 %) liegt mit 7.5 % knapp darunter.
STOP = 83_700.0


def _konto(positionen: list[Position] | None = None) -> AccountState:
    return AccountState.from_history(
        equity=1_000.0, history=[], now_ms=JETZT, open_positions=positionen or []
    )


def _lage(**ueberschreiben) -> Lage:
    daten = dict(
        symbol="BTCUSDT",
        timeframe="H4",
        preis=PREIS,
        bild="short",
        setups=[Setup(timeframe="H4", side="short", entry=PREIS, stop=STOP, target=81_400.0)],
        folgt=True,
        konto=_konto(),
        quellen={},
        kontext={},
    )
    daten.update(ueberschreiben)
    return Lage(**daten)


def _werte() -> Regelwerte:
    return Regelwerte(
        require_agreement=True,
        timeframes=["D1", "H4", "H1"],
        margin_share=0.3,
        leverage=7.0,
        risk_cap_share=0.015,
        max_cost_fraction=0.08,
        max_leverage=10.0,
        kosten_roundtrip=0.001,
    )


def _limits() -> RiskLimits:
    return RiskLimits(load_config().risk.limits)


def _urteil(lage: Lage | None = None, **vorschlag) -> Urteil:
    v = Vorschlag(symbol="BTCUSDT", **{"side": "short", **vorschlag})
    return pruefe(v, lage or _lage(), _werte(), _limits())


def _regel(u: Urteil, nr: int):
    return next(r for r in u.regeln if r.nr == nr)


def test_regelkonformer_short_wird_angenommen():
    u = _urteil()
    assert u.angenommen is True, [r for r in u.regeln if r.status != "erfuellt"]
    assert [r.nr for r in u.regeln] == list(range(1, 9))
    assert all(r.status == "erfuellt" for r in u.regeln)
    assert u.stop_vom_bot is True
    assert u.order is not None and u.order.sl == STOP
    assert u.preis == PREIS


def test_long_gegen_das_bild_wird_abgelehnt():
    u = _urteil(side="long", sl=81_900.0)
    assert u.angenommen is False
    assert u.order is None
    assert _regel(u, 2).status == "verletzt"
    assert _regel(u, 3).status == "verletzt"


def test_neutrales_bild_stimmt_nicht_zu():
    r = _regel(_urteil(_lage(bild="neutral")), 2)
    assert r.status == "verletzt"
    assert "neutral" in r.hinweis


def test_stop_auf_falscher_seite():
    u = _urteil(sl=81_000.0)
    assert u.angenommen is False
    assert _regel(u, 1).status == "verletzt"


def test_ziel_auf_falscher_seite():
    assert _regel(_urteil(tp=84_000.0), 1).status == "verletzt"


def test_ohne_stop_und_ohne_setup_bleibt_regel_1_verletzt():
    u = _urteil(_lage(setups=[]))
    assert _regel(u, 1).status == "verletzt"
    assert u.stop_vom_bot is False


def test_risiko_wird_gekuerzt_nicht_abgelehnt():
    u = _urteil(margin_usd=900.0, leverage=10.0)
    r4 = _regel(u, 4)
    assert r4.status == "erfuellt"
    assert "gekürzt auf" in r4.wert
    assert u.order is not None
    assert u.order.margin_usd < 900.0
    assert u.order.margin_usd * u.order.leverage * abs(PREIS - STOP) / PREIS <= 15.0 + 1e-6


def test_kosten_rechnen_mit_der_gekuerzten_margin():
    # Wuerde Regel 5 die ungekuerzte Margin nehmen, laege das Verhaeltnis gleich;
    # der Wert in der Regel muss aber die gekuerzten Kosten nennen.
    u = _urteil(margin_usd=900.0, leverage=10.0)
    kosten = u.order.margin_usd * u.order.leverage * 0.001
    assert f"{kosten:.2f}" in _regel(u, 5).wert


def test_zu_enger_stop_scheitert_an_kosten():
    u = _urteil(sl=82_610.0)
    assert u.angenommen is False
    assert _regel(u, 5).status == "verletzt"


def test_hebel_ueber_10_verletzt():
    u = _urteil(leverage=20.0)
    assert u.angenommen is False
    assert _regel(u, 8).status == "verletzt"


def test_fehlende_daten_sind_unbekannt_und_lehnen_ab():
    u = _urteil(_lage(preis=None))
    assert u.angenommen is False
    assert u.order is None
    assert _regel(u, 1).status == "unbekannt"
    assert _regel(u, 1).hinweis


def test_fehlendes_bild_und_fehlende_setups_sind_unbekannt():
    u = _urteil(_lage(bild=None, setups=None), sl=STOP)
    assert _regel(u, 2).status == "unbekannt"
    assert _regel(u, 3).status == "unbekannt"
    assert u.angenommen is False


def test_nicht_beobachteter_markt_ist_bei_regel_3_unbekannt():
    u = _urteil(_lage(folgt=False), sl=STOP)
    r3 = _regel(u, 3)
    assert r3.status == "unbekannt"
    assert r3.hinweis == "Markt wird nicht beobachtet"
    assert u.angenommen is False


def test_lage_eines_anderen_marktes_ist_unbekannt():
    u = pruefe(Vorschlag(symbol="ETHUSDT", side="short", sl=STOP), _lage(), _werte(), _limits())
    assert u.angenommen is False
    assert _regel(u, 1).status == "unbekannt"


def test_ohne_margin_und_hebel_gilt_die_planregel():
    # 0.3 x 1'000 = 300 USD Margin bei 7x; 2'100 Notional riskieren 28 USD > 15,
    # also wird gekuerzt -- der Hebel bleibt, die Margin faellt proportional.
    u = _urteil()
    assert u.order is not None
    assert u.order.leverage == 7.0
    risiko_ungekuerzt = 300.0 * 7.0 * abs(PREIS - STOP) / PREIS
    assert abs(u.order.margin_usd - 300.0 * 15.0 / risiko_ungekuerzt) < 1e-9


def test_deckel_urteilt_wie_risklimits():
    positionen = [
        Position(
            symbol=s,
            side=Side.LONG,
            qty=1.0,
            entry_price=1.0,
            leverage=1.0,
            liquidation_price=1.0,
            opened_ts=JETZT,
        )
        for s in ("ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT")
    ]
    konto = _konto(positionen)
    u = _urteil(_lage(konto=konto))
    assert _regel(u, 6).status == "verletzt"
    assert u.angenommen is False
    assert _limits().check(konto, symbol="BTCUSDT", side="short").allowed is False


def test_verlustbremse_landet_in_regel_7():
    class _Bremse(RiskLimits):
        def check(self, state, *, symbol, side=None):
            return LimitVerdict(
                allowed=False, blockers=["down 300 today, at or past the 25% daily limit (250)"]
            )

    u = pruefe(
        Vorschlag(symbol="BTCUSDT", side="short"),
        _lage(),
        _werte(),
        _Bremse(load_config().risk.limits),
    )
    assert _regel(u, 7).status == "verletzt"
    assert _regel(u, 6).status == "erfuellt"
    assert u.angenommen is False


def test_kill_switch_landet_in_regel_7(tmp_path):
    datei = tmp_path / "KILL"
    KillSwitch(datei).engage("open positions reconciled wrong")
    limits = RiskLimits(load_config().risk.limits, kill_switch=KillSwitch(datei))
    u = pruefe(Vorschlag(symbol="BTCUSDT", side="short"), _lage(), _werte(), limits)
    assert _regel(u, 7).status == "verletzt"
    assert _regel(u, 6).status == "erfuellt"
    assert u.angenommen is False


def test_sperre_ohne_blocker_landet_in_regel_7():
    class _Stumm(RiskLimits):
        def check(self, state, *, symbol, side=None):
            return LimitVerdict(allowed=False, blockers=[])

    u = pruefe(
        Vorschlag(symbol="BTCUSDT", side="short"),
        _lage(),
        _werte(),
        _Stumm(load_config().risk.limits),
    )
    assert _regel(u, 7).status == "verletzt"
    assert _regel(u, 7).wert == "Sperre ohne Begruendung"
    assert u.angenommen is False


def _abgelehnt_ohne_ausnahme(u: Urteil) -> None:
    assert isinstance(u, Urteil)
    assert u.angenommen is False
    assert u.order is None


def test_hebel_null_wirft_nicht():
    u = _urteil(leverage=0.0)
    _abgelehnt_ohne_ausnahme(u)
    assert _regel(u, 8).status == "verletzt"
    assert _regel(u, 4).status == "unbekannt"
    assert _regel(u, 5).status == "unbekannt"


def test_kurs_null_wirft_nicht():
    u = _urteil(_lage(preis=0.0))
    _abgelehnt_ohne_ausnahme(u)
    assert _regel(u, 1).status == "unbekannt"


def test_negativer_kurs_wirft_nicht_und_besteht_regel_1_nicht():
    u = _urteil(_lage(preis=-82_597.0), sl=STOP)
    _abgelehnt_ohne_ausnahme(u)
    assert _regel(u, 1).status == "unbekannt"


def test_unendlicher_stop_beim_short_wirft_nicht():
    u = _urteil(sl=float("inf"))
    _abgelehnt_ohne_ausnahme(u)
    assert _regel(u, 1).status == "verletzt"
    assert _regel(u, 4).status == "verletzt"


def test_bot_stop_nur_aus_setup_einer_handelsebene():
    setups = [
        Setup(timeframe="M15", side="short", entry=PREIS, stop=82_900.0, target=82_000.0),
        Setup(timeframe="H4", side="short", entry=PREIS, stop=STOP, target=81_400.0),
    ]
    u = _urteil(_lage(setups=setups))
    assert u.angenommen is True
    assert u.stop_vom_bot is True
    assert u.order.sl == STOP


def test_claude_kann_nicht_freigeben():
    v = Vorschlag(symbol="BTCUSDT", side="long", sl=81_900.0)
    a = pruefe(v, _lage(), _werte(), _limits())
    b = pruefe(v, _lage(), _werte(), _limits())
    assert a.model_dump() == b.model_dump()
    assert a.angenommen is False


def test_regelwerte_aus_der_konfiguration():
    config = load_config()
    plan = {"margin_share": 0.3, "leverage": 7.0, "risk_cap_share": 0.015}
    w = regelwerte_aus(config, plan)
    assert w.margin_share == 0.3 and w.leverage == 7.0 and w.risk_cap_share == 0.015
    assert w.require_agreement == config.engine.setups.require_agreement
    assert w.max_cost_fraction == config.risk.limits.max_cost_fraction_of_risk
    assert w.max_leverage == config.risk.leverage.max
    assert w.kosten_roundtrip == 0.001
    assert all(isinstance(t, str) for t in w.timeframes) and w.timeframes
