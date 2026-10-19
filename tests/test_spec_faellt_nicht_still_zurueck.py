"""Ein Haendler, der die Gebuehren nicht erfaehrt, handelt nicht.

**Der Fehler.** `scripts/papertrade.py:_spec` fing jeden Fehlschlag des
Spezifikationsabrufs ab, schrieb eine Zeile auf stderr und lieferte
`DEFAULT_SPEC`. Der Haendler glaubte dann, auf Binance zu sein, und rechnete
mit Bybits Gebuehren.

**Warum das nicht kosmetisch ist.** Das Kostentor beurteilt rund 48 % aller
Signale und reduziert sich auf eine Mindest-Stopweite von
`c / max_cost_fraction_of_risk`:

===================  ==========  ==================
Quelle               c           Mindest-Stopweite
===================  ==========  ==================
Binance live         0,100 %     1,2500 %
`DEFAULT_SPEC`       0,105 %     1,3125 %
===================  ==========  ==================

Ein stiller Rueckfall macht das Tor also um 5 % strenger, ohne dass es irgendwo
steht. Die stderr-Zeile landet im Betrieb in einer Logdatei, die niemand
liest -- und der Schwesterlauf hat ueber 900 Datenabrufe scheitern sehen, der
Pfad ist keine Theorie.

**Die Unterscheidung, die diese Datei festnagelt**, ist die, die
`execution/venuebinding.py` schon trifft: ein inkohaerenter Lauf darf
*messen*, niemals *senden*. `--offline` hat ein Mensch gewaehlt und darf
zurueckfallen; ein gescheiterter Abruf hat niemand gewaehlt und wirft.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import papertrade

from traidingbrain.config.settings import load_config
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.risk.sizing import min_economic_stop_fraction


class BoerseSchweigt:
    """Eine Quelle, deren Abruf dauerhaft scheitert.

    Dauerhaft und nicht voruebergehend: `data/exchange.py` versucht es
    viermal, bevor es durchreicht. Wer in `_spec` ankommt, hat kein
    Netzwerkzucken, sondern ein Problem.
    """

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or RuntimeError("fetch_symbol_spec failed after 4 attempts")
        self.aufrufe = 0

    def fetch_symbol_spec(self, symbol: str) -> SymbolSpec:
        self.aufrufe += 1
        raise self.exc


def test_ein_gescheiterter_abruf_wirft_statt_zu_raten() -> None:
    """Der Kern: kein stiller Ersatz mehr.

    Vorher kam hier eine `SymbolSpec` mit Bybits Takersatz zurueck, und der
    Lauf handelte damit weiter.
    """
    boerse = BoerseSchweigt()

    with pytest.raises(papertrade.VenueSpecUnavailableError) as fehler:
        papertrade._spec(boerse, "BTCUSDT")

    assert boerse.aufrufe == 1, "der Abruf muss ueberhaupt versucht worden sein"
    text = str(fehler.value)
    assert "BTCUSDT" in text, "welcher Markt"
    assert "startet NICHT" in text, "was jetzt passiert"
    assert "offline" in text, "wie man es absichtlich trotzdem tut"


def test_die_ursache_bleibt_lesbar() -> None:
    """Die urspruengliche Ausnahme darf nicht verschwinden.

    Ein Abbruch, der nicht sagt WARUM die Boerse schwieg, verlagert die
    Suche nur -- der Bediener sieht "startet nicht" und hat nichts in der
    Hand. `raise ... from exc` haelt die Kette.
    """
    grund = ValueError("binanceusdm GET /fapi/v1/exchangeInfo: 451")
    with pytest.raises(papertrade.VenueSpecUnavailableError) as fehler:
        papertrade._spec(BoerseSchweigt(grund), "ETHUSDT")

    assert fehler.value.__cause__ is grund
    assert "451" in str(fehler.value), "der Grund steht auch im Text"


def test_offline_darf_zurueckfallen_und_sagt_es(capsys: pytest.CaptureFixture[str]) -> None:
    """`--offline` ist eine Wahl, kein Fehlschlag -- aber keine stille.

    Ohne Boerse gibt es nichts abzurufen; der Rueckfall ist dort die Absicht.
    Die Bedingung ist, dass er ausgesprochen wird, mit der Zahl, auf die es
    ankommt.
    """
    spec = papertrade._spec(None, "SOLUSDT")

    assert spec.taker_fee == DEFAULT_SPEC["taker_fee"]
    gesagt = capsys.readouterr().err
    assert "offline" in gesagt.lower()
    assert "DEFAULT_SPEC" in gesagt
    assert "Bybit" in gesagt, "die Boerse, von der diese Zahlen stammen"


def test_der_lauf_lehnt_ab_statt_abzustuerzen(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Eine Verweigerung sieht anders aus als ein Defekt -- und das ist wichtig.

    Ein Rueckverfolgungsstapel liest sich wie ein Fehler im Programm und
    verleitet dazu, einfach nochmal zu starten. Eine benannte Ablehnung mit
    Rueckgabewert 2 sagt, was zu tun ist -- dieselbe Form, die die
    Einzelinstanz-Sperre schon benutzt.
    """

    def scheitert(*_args: object, **_kw: object) -> object:
        raise papertrade.VenueSpecUnavailableError("BTCUSDT: Boerse schweigt")

    monkeypatch.setattr(papertrade, "build_traders", scheitert)
    monkeypatch.setattr(sys, "argv", ["papertrade.py", "--cycles", "1"])

    code = papertrade.main()

    assert code == 2, "abgelehnt, nicht abgestuerzt und nicht stillschweigend 0"
    gesagt = capsys.readouterr().err
    assert "Start abgelehnt" in gesagt
    assert "--offline" in gesagt, "der Weg, es absichtlich trotzdem zu tun"


def test_warum_es_sich_lohnt_abzubrechen() -> None:
    """Die Messung, die den Abbruch rechtfertigt -- hier statt im Kommentar.

    Ein Test, der nur das Werfen prueft, laesst offen, ob der Abbruch
    verhaeltnismaessig ist. Diese Zeilen rechnen den Unterschied aus, den der
    stille Rueckfall verursacht haette, und scheitern, falls die Gebuehren
    sich je angleichen und die Begruendung damit hinfaellig wird.
    """
    cfg = load_config()
    schlupf = cfg.engine.simulation.slippage_bps
    deckel = cfg.risk.limits.max_cost_fraction_of_risk

    rueckfall = SymbolSpec(symbol="X", **DEFAULT_SPEC)
    # Binance USD-M, veroeffentlicht und am 19.10.2026 live gegengeprueft.
    binance = rueckfall.model_copy(update={"taker_fee": 0.0005, "maker_fee": 0.0002})

    d_rueckfall = min_economic_stop_fraction(rueckfall, schlupf, deckel)
    d_binance = min_economic_stop_fraction(binance, schlupf, deckel)

    assert d_rueckfall > d_binance, (
        "Der Rueckfall muss STRENGER sein als die echte Boerse -- sonst "
        "liesse er Trades durch, die die Boerse nicht traegt, und die "
        "Begruendung dieses Abbruchs waere eine andere."
    )
    assert d_binance == pytest.approx(0.0125, abs=1e-6)
    assert d_rueckfall == pytest.approx(0.013125, abs=1e-6)
    assert d_rueckfall / d_binance == pytest.approx(1.05, abs=1e-3), (
        "5 % strenger -- die Zahl, die in der Begruendung steht"
    )
