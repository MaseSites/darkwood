"""Was beim Ausführen tatsächlich gesendet wird — und was das kostet.

**Der Anlass ist eine Abweichung, die der Simulator selbst vorhergesagt hat.**
`sim/broker.py:741-745` schreibt wörtlich:

    It is also a constraint on the live side, not only a model change. It is
    only true if the executor places a resting limit at the target. A
    take-profit-market order ... crosses the spread and pays taker -- and then
    this line would be quietly optimistic about every winner.

Der Executor wurde nie nachgezogen. `execution/order.py:265` sendet
`timeInForce: GTC` ohne `PostOnly` und `takeProfit` ohne `tpOrderType`; Bybits
Vorgabe für linear ist Market. Der Simulator rechnet trotzdem Maker am
Einstieg (`broker.py:493`, LIMIT ⇒ maker, ohne Kreuzungsprüfung) und Maker am
Target (`broker.py:746`, unbedingt bei `ExitReason.TARGET`).

Gemessene obere Schranke über die 7.335 Fills der Legacy-Population:
**-0.021979 R je Trade**, korrigiert 99.932 % [-0.022488, -0.021477], Summe
-161.21 R. Das ist das 1,7-fache der gesamten gemessenen Erwartung von
-0.0129 R. Die Ausführungs-Semantik ist damit ein grösserer Posten als alle
Ausstiegsregeln, die E14 bis E16 untersucht haben.

**Die Trennung, die dieses Modul durchsetzt: Absicht gegen Beweis.**

Eine Policy erklärt, *was gesendet wird*. Ob die günstigere Gebühr gilt,
entscheidet ein separates Flag — `maker_role_proven`. Ohne Beweis rechnet das
Kostenmodell Taker, auch wenn die Absicht Maker war. Begründung:

* Ein Limit ist kein Maker. Ein GTC-Limit darf sofort ausführbar sein und zahlt
  dann Taker. Nur `PostOnly` verhindert das, indem die Börse den Auftrag
  storniert statt ihn kreuzen zu lassen.
* Ein Limit-TP ist auch kein Maker. Ein nach Trigger erzeugter Limit-TP ruhte
  vorher nicht im Buch, also ist er beim Auslösen genauso marketable wie jede
  andere Order.
* Und der Fill selbst ist historisch nicht beweisbar: bis zu 49 % ruhender
  Aufträge verschwinden je 17 Sekunden unerreicht. Ein Trade-Tape belegt, dass
  am Preis gehandelt wurde, nicht dass unsere Order an der Reihe war. Ohne
  Queue-Position bleibt jedes Fill-Modell eine Annäherung.

Belegt werden kann die Rolle deshalb nur durch **eigene Ausführungsdaten** —
was die Börse für einen konkreten Fill als Maker oder Taker zurückmeldet. Bis
dahin ist `safety-first` die einzige Policy, deren Kosten nicht auf einer
Annahme stehen.

**Slippage wird NICHT frei gesetzt, sondern aus dem Ordertyp abgeleitet.**
Eine Limit-Order hat einen genannten Preis — sie füllt dort oder nicht, aber
sie rutscht nicht. Nur eine Market-Order rutscht. `broker.py:713` sagt das
über den Legacy-Lauf ausdrücklich: *„`sim/plan.py:307` sets `OrderType.LIMIT`
without exception, so no market entry exists in any measurement, and the limit
path never slips at all."* Frei konfigurierbare Slippage würde eine Policy
erlauben, die PostOnly sendet und trotzdem rutscht — ein Zustand, den es nicht
gibt.

**Der Stop ist immer Market.** Ein Limit-Stop kann in einer Lücke unausgeführt
bleiben, und das ist die eine Order, die ausführen muss. Eine Policy, die
etwas anderes behauptet, wird abgelehnt.

**Was dabei herauskommt, ordnet die Legacy-Annahme ein.** Policy B mit
bestätigter Rolle ergibt genau `maker + taker + 1 x Slippage = 0.00105` — das
Legacy-Kostenmodell. Legacy hat also stillschweigend Policy B als bewiesen
behandelt. Policy A ergibt `taker + taker + 1 x Slippage = 0.00140`.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum


class EntryLiquidity(StrEnum):
    """Wie der Einstieg ins Buch geht — Ordertyp UND Liquidity Role in einem.

    Die drei Werte sind die drei Dinge, die man tatsächlich senden kann. Sie
    sind nicht orthogonal zur Slippage: wer einen Preis nennt, rutscht nicht.
    """

    POST_ONLY_MAKER = "post_only_maker"
    """Limit mit `PostOnly`: die Börse storniert, statt kreuzen zu lassen.

    Damit KANN der Fill nur maker sein. Ob er überhaupt zustande kommt, ist
    eine andere Frage und entscheidet, ob der Trade existiert, nicht was er
    kostet. Kein Rutschen -- der Preis steht.
    """

    LIMIT_TAKER_ALLOWED = "limit_taker_allowed"
    """Gewöhnliches Limit, `GTC` ohne `PostOnly` -- der heutige Executor.

    Darf sofort ausführbar sein und zahlt dann Taker. Rutscht nicht: der
    Limitpreis steht, auch wenn er kreuzt.
    """

    MARKET_TAKER = "market_taker"
    """Market-Order: zahlt Taker UND rutscht."""

    @property
    def can_be_maker(self) -> bool:
        return self is EntryLiquidity.POST_ONLY_MAKER

    @property
    def slips(self) -> bool:
        return self is EntryLiquidity.MARKET_TAKER


class ExitOrderType(StrEnum):
    """Womit eine Position geschlossen wird."""

    MARKET = "market"
    """Zahlt Taker und rutscht."""

    RESTING_LIMIT = "resting_limit"
    """Ein reduce-only-Limit, das VOR dem Auslösen im Buch liegt.

    Nicht dasselbe wie ein Limit-TP, den die Börse nach einem Trigger erzeugt:
    der ruhte vorher nicht und ist beim Auslösen marketable. Rutscht nicht.
    """

    @property
    def can_be_maker(self) -> bool:
        return self is ExitOrderType.RESTING_LIMIT

    @property
    def slips(self) -> bool:
        return self is ExitOrderType.MARKET


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """Eine Venue, ihre Ordertypen, ihr Gebührenplan, ihre Slippage.

    Unveränderlich, weil sie in `run_signature` eingeht: zwei Läufe unter
    verschiedenen Policies sind verschiedene Läufe.
    """

    venue: str
    name: str
    entry_liquidity: EntryLiquidity
    take_profit_order_type: ExitOrderType
    stop_order_type: ExitOrderType
    maker_fee: float
    taker_fee: float
    slippage_bps: float
    """Slippage einer MARKET-Order. Limit-Orders rutschen nicht."""

    fee_provenance: str
    """Woher die Gebührenzahlen kommen -- URL oder Dokument, nicht „üblich“."""

    maker_role_proven: bool = False
    """Ob die Liquidity Role aus eigenen Ausführungsdaten bestätigt ist.

    Vorgabe FALSE, und das ist die ganze Idee. Eine Absicht ist kein Beweis.
    """

    def __post_init__(self) -> None:
        if self.stop_order_type is not ExitOrderType.MARKET:
            raise ValueError(
                f"Stop muss Market sein, nicht {self.stop_order_type}. Ein "
                "Limit-Stop kann in einer Luecke unausgefuehrt bleiben, und "
                "das ist die eine Order, die ausfuehren muss."
            )
        if self.maker_fee >= self.taker_fee:
            raise ValueError(
                f"Maker ({self.maker_fee}) muss billiger sein als Taker "
                f"({self.taker_fee}). Gleich oder teurer macht jede "
                "Maker-Annahme wertlos und ist mit grosser Wahrscheinlichkeit "
                "ein Zahlendreher."
            )
        if not self.fee_provenance.strip():
            raise ValueError(
                "Gebuehren ohne Herkunft. In diesem Projekt hat ein Kommentar, "
                "der eine Venue behauptete, eine Forschungsachse einen Tag "
                "lang blockiert -- siehe audit/P0A_LEGACY_FREEZE.md."
            )
        if self.slippage_bps < 0:
            raise ValueError(f"slippage_bps darf nicht negativ sein: {self.slippage_bps}")

    # -- Gebühren, abgeleitet statt angenommen ------------------------------ #

    def entry_fee(self) -> float:
        """Maker nur bei PostOnly UND bestätigter Rolle. Sonst Taker."""
        maker = self.entry_liquidity.can_be_maker and self.maker_role_proven
        return self.maker_fee if maker else self.taker_fee

    def target_fee(self) -> float:
        """Maker nur bei ruhendem Limit UND bestätigter Rolle. Sonst Taker."""
        maker = self.take_profit_order_type.can_be_maker and self.maker_role_proven
        return self.maker_fee if maker else self.taker_fee

    def stop_fee(self) -> float:
        """Immer Taker -- der Stop ist Market, und kein Beweis ändert das."""
        return self.taker_fee

    # -- Slippage, abgeleitet statt gesetzt --------------------------------- #

    def entry_slippage(self) -> float:
        return self.slippage_bps * 1e-4 if self.entry_liquidity.slips else 0.0

    def target_slippage(self) -> float:
        return self.slippage_bps * 1e-4 if self.take_profit_order_type.slips else 0.0

    def stop_slippage(self) -> float:
        """Der Stop ist Market, also rutscht er immer."""
        return self.slippage_bps * 1e-4

    def all_taker(self) -> bool:
        """Ob diese Policy durchgehend Taker rechnet.

        Wahr für `safety-first` und für jede unbewiesene Policy -- der Zustand,
        in dem keine Kostenzahl auf einer Annahme steht.
        """
        return (
            self.entry_fee() == self.taker_fee
            and self.target_fee() == self.taker_fee
            and self.stop_fee() == self.taker_fee
        )

    def with_proven_maker_role(self) -> ExecutionPolicy:
        """Dieselbe Policy mit bestätigter Liquidity Role.

        Nur aufzurufen, wenn eigene Ausführungsdaten die Rolle belegen -- nicht
        weil die Absicht Maker war.
        """
        return dataclasses.replace(self, maker_role_proven=True)

    # -- Was die Policy für die Positionsgrösse bedeutet -------------------- #

    def round_trip_cost_fraction(self) -> float:
        """Kosten eines Umlaufs als Anteil des Notionals.

        Der ungünstigste glaubwürdige Ausgang, nicht der erhoffte: Einstieg
        plus STOP-Ausgang, mit der Slippage beider Beine. Vor dem Trade ist
        unbekannt, ob Ziel oder Stop eintritt, und jeder Trade kann am Stop
        enden. Ein Budget, das den Target-Ausgang unterstellt, kennt die
        Exit-Reason der Zukunft -- das wäre Lookahead.
        """
        return (
            self.entry_fee()
            + self.stop_fee()
            + self.entry_slippage()
            + self.stop_slippage()
        )

    def min_economic_stop_fraction(self, max_cost_fraction_of_risk: float) -> float:
        """Wie weit der Stop stehen muss, damit der Trade bezahlbar ist.

        `d >= c / f`. Die Positionsgrösse ist Risiko durch Stop-Abstand, also
        kauft ein Stop `d` ein Notional von `risk / d`; ein Umlauf kostet
        `notional * c`, und als Anteil des Risikos ist das `c / d`.

        Legacy rechnete 1.3125 %. Unter `safety-first` sind es 1.75 %, und das
        hätte 2.529 von 7.335 Legacy-Fills (34.5 %) nicht zugelassen.
        """
        if max_cost_fraction_of_risk <= 0:
            raise ValueError(
                f"Deckel muss positiv sein, nicht {max_cost_fraction_of_risk}"
            )
        return self.round_trip_cost_fraction() / max_cost_fraction_of_risk

    # -- Identität ---------------------------------------------------------- #

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.name}"

    def fingerprint(self) -> str:
        """Das `policy`-Feld der `ExperimentIdentity` (`journal/identity.py`).

        Nicht `run_signature` -- das stand hier bis zum 18.10.2026 und war nie
        verdrahtet. Die Signatur ist ein Schlüssel über 12.843 vorhandene
        Zeilen und bleibt unverändert; die Identität ist der Ort, an dem Venue,
        Policy und Gebührenplan stehen.

        Die Gebühren stehen mit drin: zwei Läufe auf derselben Venue mit
        verschiedenen Gebührenannahmen sind verschiedene Läufe. **Gemessen am
        18.10.2026**, wie verschieden: dieselben 7.335 Fills unter Bybits und
        unter Binances Takersatz unterscheiden sich um +0.0014 R je Trade mit
        einem Intervall von [+0.001, +0.002] -- reliabel, und in allen zwölf
        Märkten gleichgerichtet. In der Legacy-Population war dieser
        Unterschied unsichtbar.
        """
        bewiesen = "proven" if self.maker_role_proven else "unproven"
        return (
            f"{self.venue}:{self.name}:{self.entry_liquidity}:"
            f"{self.take_profit_order_type}:{self.maker_fee:g}/"
            f"{self.taker_fee:g}:{self.slippage_bps:g}bps:{bewiesen}"
        )


#: Bybit VIP 0 / Standard, USDT-Perpetual.
_BYBIT_MAKER, _BYBIT_TAKER = 0.00020, 0.00055
_BYBIT_QUELLE = (
    "Bybit VIP 0, USDT-Perpetual, maker 0.020 % / taker 0.055 %; "
    "https://www.bybit.com/en/help-center/article/Trading-Fee-Structure"
)

#: Binance USDⓈ-M Standard, OHNE BNB-Rabatt.
#: Die tatsächliche Rate hängt von VIP-Stufe, BNB-Zahlung und Programmen ab und
#: muss für ein echtes Konto auf der persönlichen Gebührenseite bestätigt
#: werden. Ein Rabatt wird hier NICHT unterstellt.
_BINANCE_MAKER, _BINANCE_TAKER = 0.00020, 0.00050
_BINANCE_QUELLE = (
    "Binance USDS-M Standard, maker 0.020 % / taker 0.050 %, ohne BNB-Rabatt; "
    "https://www.binance.com/en/fee/futureFee -- die tatsaechliche Rate des "
    "Kontos ist NICHT bestaetigt und muss vor Live-Betrieb geprueft werden"
)

#: Dieselbe Annahme wie `config/settings.yaml: simulation.slippage_bps`.
SLIPPAGE_BPS = 3.0


def _safety_first(
    venue: str, maker: float, taker: float, quelle: str
) -> ExecutionPolicy:
    """Policy A: Limit-Einstieg der Taker sein darf, Market am Ziel und am Stop.

    Genau das, was `execution/order.py:265` heute sendet -- nur ehrlich
    bepreist. Die einzige Policy, deren KOSTEN heute belegbar sind; ihre
    Fill-Wahrscheinlichkeit ist damit NICHT belegt.
    """
    return ExecutionPolicy(
        venue=venue,
        name="safety-first",
        entry_liquidity=EntryLiquidity.LIMIT_TAKER_ALLOWED,
        take_profit_order_type=ExitOrderType.MARKET,
        stop_order_type=ExitOrderType.MARKET,
        slippage_bps=SLIPPAGE_BPS,
        fee_provenance=quelle,
        maker_fee=maker,
        taker_fee=taker,
    )


def _maker_target(
    venue: str, maker: float, taker: float, quelle: str
) -> ExecutionPolicy:
    """Policy B: PostOnly-Einstieg, ruhendes Limit am Ziel, Market-Stop.

    Die Absicht, die der Simulator schon unterstellt. Rechnet bis zum Beweis
    wie Policy A, weil `maker_role_proven` falsch ist -- und ergibt MIT Beweis
    exakt das Legacy-Kostenmodell (0.00105).
    """
    return ExecutionPolicy(
        venue=venue,
        name="maker-target",
        entry_liquidity=EntryLiquidity.POST_ONLY_MAKER,
        take_profit_order_type=ExitOrderType.RESTING_LIMIT,
        stop_order_type=ExitOrderType.MARKET,
        slippage_bps=SLIPPAGE_BPS,
        fee_provenance=quelle,
        maker_fee=maker,
        taker_fee=taker,
    )


POLICIES: dict[str, ExecutionPolicy] = {
    p.key: p
    for p in (
        _safety_first("bybit", _BYBIT_MAKER, _BYBIT_TAKER, _BYBIT_QUELLE),
        _maker_target("bybit", _BYBIT_MAKER, _BYBIT_TAKER, _BYBIT_QUELLE),
        _safety_first("binance", _BINANCE_MAKER, _BINANCE_TAKER, _BINANCE_QUELLE),
        _maker_target("binance", _BINANCE_MAKER, _BINANCE_TAKER, _BINANCE_QUELLE),
    )
}


def policy_for(venue: str, name: str) -> ExecutionPolicy:
    """Die Policy einer Venue, oder ein Abbruch.

    Kein Rückfall auf eine Vorgabe: eine unbekannte Policy ist der Fall, in dem
    niemand weiss, was gesendet wird. Der Vorgabewert
    `venue_name: str = "bybit"` in `execution/order.py:91` ist der Grund, dass
    diese Funktion keinen hat -- zwei Aufrufstellen übergaben nichts und
    bekamen stillschweigend Bybit, während die Konfiguration Binance sagte.
    """
    key = f"{venue}:{name}"
    if key not in POLICIES:
        raise KeyError(
            f"Keine ExecutionPolicy {key!r}. Bekannt: {sorted(POLICIES)}. Es "
            "gibt keinen Vorgabewert -- eine unbekannte Policy heisst, dass "
            "niemand weiss, was gesendet wird."
        )
    return POLICIES[key]
