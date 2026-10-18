"""Was die Börse nicht sagt, darf dieses Projekt nicht erfinden.

**Der Befund.** `data/exchange.py:236` schrieb bis zum 18.10.2026:

    taker_fee=float(market.get("taker") or 0.00055),
    maker_fee=float(market.get("maker") or 0.0002),
    price_tick=float(precision.get("price") or 0.01),
    qty_step=float(precision.get("amount") or 0.001),
    min_qty=float(amount_limits.get("min") or 0.001),
    min_notional=float(cost_limits.get("min") or 0.0),
    max_leverage=float(leverage_limits.get("max") or 25.0),

Der Docstring derselben Funktion lautet: *„Hardcoding these is how orders get
rejected in production for reasons that never showed up in a test."* Die
Funktion verurteilt also ihre eigenen Ausweichwerte, und die Zahlen 0.00055 /
0.0002 sind **Bybits** Gebühren. Auf einer anderen Börse hätte eine schweigende
Marktbeschreibung stillschweigend Bybit-Kosten in das Kostenmodell geschrieben
— genau der Fehler, den Phase 1 im Derivatespeicher behoben hat.

**Zwei verschiedene Defekte, beide hier festgenagelt.**

1. *Erfinden.* Ein fehlendes Feld muss den Lauf anhalten, nicht ersetzt werden.
   In der Simulation lehnt niemand eine Order ab: ein geratener `price_tick`
   rundet jeden Preis still falsch, über den ganzen Backtest, und nichts meldet
   sich. `fetch_symbol_spec` speist `run_backtest.py:192` und
   `papertrade.py:178`, also ist dieser Pfad ein Messpfad und kein Orderpfad.

2. *`or` statt `is None`.* `0.0` ist in Python falsch. Eine Börse, die eine
   Gebühr von **null** meldet, bekam darum Bybits 0.055 % untergeschoben. Dass
   es Venues mit 0 % gibt, ist in diesem Projekt schon einmal gemessen worden
   und steht in `audit/P0A_LEGACY_FREEZE.md`; das Gebührenargument ist
   venue-gebunden. Dieser Fehler zeigt in die andere Richtung als der erste —
   er erfindet Kosten, wo die Börse keine nennt — und ein Test, der nur auf
   fehlende Felder prüft, hätte ihn nicht gesehen.

**Was ausdrücklich einen Ausweichwert behält.** `maintenance_margin_rate`.
Dessen Begründung steht seit dem ersten Tag in `exchange.py:37` und argumentiert
die *Richtung*: ein zu hoher Wert schiebt den berechneten Liquidationspreis
näher an den Einstand, macht die Grösse also vorsichtiger und nicht kühner. Das
ist der Unterschied zwischen einem begründeten Ersatz und einem geratenen.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.fakes import FakeCcxtExchange, synthetic_rows
from traidingbrain.clock import FixedClock
from traidingbrain.config.settings import load_config
from traidingbrain.data.exchange import (
    DEFAULT_MAX_LEVERAGE,
    MarketData,
    UnpublishedSpecError,
)
from traidingbrain.domain.enums import Timeframe

EPOCH = 1_704_067_200_000


def _quelle(market: dict[str, Any]) -> MarketData:
    exchange = FakeCcxtExchange(
        synthetic_rows(EPOCH, Timeframe.H1, 2), market=market
    )
    return MarketData(exchange=exchange, clock=FixedClock(EPOCH))


def _vollstaendig() -> dict[str, Any]:
    """Dieselbe Form wie `tests/fakes.py:91`, hier lokal veränderbar."""
    return {
        "symbol": "BTC/USDT:USDT",
        "precision": {"price": 0.1, "amount": 0.001},
        "limits": {
            "amount": {"min": 0.001},
            "cost": {"min": 5.0},
            "leverage": {"max": 100.0},
        },
        "taker": 0.00055,
        "maker": 0.0002,
        "maintenanceMarginRate": 0.005,
        "info": {},
    }


# --------------------------------------------------------------------------- #
# 1. Ein fehlendes Feld hält den Lauf an
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("pfad", "feldname"),
    [
        (("taker",), "taker_fee"),
        (("maker",), "maker_fee"),
        (("precision", "price"), "price_tick"),
        (("precision", "amount"), "qty_step"),
        (("limits", "amount", "min"), "min_qty"),
        (("limits", "cost", "min"), "min_notional"),
    ],
)
def test_ein_fehlendes_feld_wird_nicht_erfunden(
    pfad: tuple[str, ...], feldname: str
) -> None:
    market = _vollstaendig()
    ziel: Any = market
    for stufe in pfad[:-1]:
        ziel = ziel[stufe]
    del ziel[pfad[-1]]

    with pytest.raises(UnpublishedSpecError) as fehler:
        _quelle(market).fetch_symbol_spec("BTCUSDT")

    text = str(fehler.value)
    assert feldname in text, f"die Meldung nennt das Feld nicht: {text}"
    assert "BTCUSDT" in text, f"die Meldung nennt das Symbol nicht: {text}"


def test_ein_null_feld_wird_auch_nicht_erfunden() -> None:
    """`None` ist dasselbe wie fehlend -- ccxt liefert beides."""
    market = _vollstaendig()
    market["taker"] = None

    with pytest.raises(UnpublishedSpecError, match="taker_fee"):
        _quelle(market).fetch_symbol_spec("BTCUSDT")


def test_die_meldung_nennt_die_boerse() -> None:
    """Wessen Beschreibung unvollständig ist, gehört in die Meldung.

    Ohne den Namen liest sich der Fehler wie ein Codefehler.
    """
    market = _vollstaendig()
    del market["maker"]

    with pytest.raises(UnpublishedSpecError) as fehler:
        _quelle(market).fetch_symbol_spec("BTCUSDT")
    assert "bybit" in str(fehler.value).lower()


# --------------------------------------------------------------------------- #
# 2. Eine gemeldete Null ist eine Antwort
# --------------------------------------------------------------------------- #


def test_eine_gemeldete_nullgebuehr_bleibt_null() -> None:
    """Der `or`-Fehler, in die andere Richtung.

    Bis zum 18.10.2026 wurde hieraus 0.00055 -- Bybits Takergebühr auf einer
    Börse, die ausdrücklich null gemeldet hat.
    """
    market = _vollstaendig()
    market["taker"] = 0.0
    market["maker"] = 0.0

    spec = _quelle(market).fetch_symbol_spec("BTCUSDT")

    assert spec.taker_fee == 0.0
    assert spec.maker_fee == 0.0


def test_ein_gemeldeter_nullmindestwert_bleibt_null() -> None:
    market = _vollstaendig()
    market["limits"]["cost"]["min"] = 0.0

    spec = _quelle(market).fetch_symbol_spec("BTCUSDT")

    assert spec.min_notional == 0.0


# --------------------------------------------------------------------------- #
# 3. Die Gegenprobe und die eine begründete Ausnahme
# --------------------------------------------------------------------------- #


def test_eine_vollstaendige_beschreibung_geht_durch() -> None:
    spec = _quelle(_vollstaendig()).fetch_symbol_spec("BTCUSDT")

    assert spec.price_tick == pytest.approx(0.1)
    assert spec.qty_step == pytest.approx(0.001)
    assert spec.min_qty == pytest.approx(0.001)
    assert spec.min_notional == pytest.approx(5.0)
    assert spec.max_leverage == pytest.approx(100.0)
    assert spec.taker_fee == pytest.approx(0.00055)
    assert spec.maker_fee == pytest.approx(0.0002)


def test_die_wartungsmarge_behaelt_ihren_begruendeten_ersatz() -> None:
    """Die erste von zwei Ausnahmen, und sie steht hier, damit sie eine bleibt.

    Ihre Begründung argumentiert die Richtung des Fehlers: ein zu hoher Wert
    ist vorsichtiger. Bei einer Gebühr gilt das nicht -- zu hoch verwirft
    Trades, zu niedrig behauptet einen Gewinn.
    """
    market = _vollstaendig()
    del market["maintenanceMarginRate"]

    spec = _quelle(market).fetch_symbol_spec("BTCUSDT")

    assert spec.maintenance_margin_rate == pytest.approx(0.005)


def test_der_hebeldeckel_behaelt_seinen_begruendeten_ersatz() -> None:
    """Die zweite Ausnahme, und sie ist eine Messung vom 18.10.2026.

    Binance nennt `limits.leverage.max` für **keines** der zwölf aktiven
    Perpetuals; die Hebelstufen stehen nur hinter einem signierten Endpunkt,
    den diese Direktive nicht anfassen darf. Fail-closed hätte hier den ganzen
    Forschungspfad stillgelegt, ohne irgendetwas richtiger zu machen.
    """
    market = _vollstaendig()
    market["limits"]["leverage"]["max"] = None

    spec = _quelle(market).fetch_symbol_spec("BTCUSDT")

    assert spec.max_leverage == pytest.approx(DEFAULT_MAX_LEVERAGE)


def test_der_ersatzdeckel_bindet_heute_nichts() -> None:
    """Die Wache am Ersatzwert.

    `risk/leverage.py:99` nimmt `min(1/puffer, config.max, spec.max_leverage)`.
    Solange der Konfigurationsdeckel unter dem Ersatzwert liegt, entscheidet
    der Ersatz nichts, und die Begründung in `exchange.py` stimmt. Wird er
    darüber gehoben, fängt eine geratene Zahl an, über echten Hebel zu
    entscheiden -- und dann soll dieser Test fallen und nicht ein Trade
    auffallen.
    """
    config = load_config()
    assert config.risk.leverage.max <= DEFAULT_MAX_LEVERAGE, (
        f"risk.leverage.max = {config.risk.leverage.max} liegt ueber dem "
        f"Ersatzdeckel {DEFAULT_MAX_LEVERAGE}. Damit entscheidet ein "
        f"geratener Wert ueber den Hebel. Entweder den echten Deckel der "
        f"Boerse beschaffen oder den Konfigurationsdeckel senken."
    )
