"""Die zehn Grössen einer Position, zusammen gerechnet und zusammen gespeichert.

**Warum dieses Modul existiert.** Es gibt zwei Richtungen, eine Position zu
bemessen, und sie sind nicht symmetrisch:

* **rückwärts** — `risk/sizing.py`: ein Risikobudget und ein Stopabstand ergeben
  die Menge. Das Risiko ist eine *Eingabe*, also bekannt.
* **vorwärts** — dieses Modul: eine Margin und ein Hebel ergeben das Nominal,
  und der Stopabstand ergibt daraus das Risiko. Das Risiko ist ein
  **Ergebnis**, also unbekannt, bis man es ausrechnet.

Die zweite Richtung ist die, in der Menschen denken („300 Franken, 7-facher
Hebel"), und sie ist die gefährlichere, weil sie die eine Zahl verschweigt, auf
die es ankommt. Gemessen am 19.10.2026 über 7.335 Trades: 300 CHF bei 7x auf
einem 1.000er-Konto riskieren im Median 4,38 % des Kontos, im 95. Perzentil
15,07 % und im 99. **30,62 %** — und bei 1,20 % der Trades liegt der Stop
**jenseits der Liquidation**, die Börse schliesst also vor dem Stop und die
ganze Margin ist weg statt des geplanten Betrags.

Keine dieser Zahlen steht in „300 CHF bei 7x". Alle stehen in `PlanSize`.

**Warum zusammen.** Eine Grösse allein ist eine Behauptung; erst der Satz ist
eine Aussage. Wer Margin und Hebel kennt, aber nicht den Liquidationsabstand,
hat die Position nicht beschrieben. Darum ist dies eine einzige eingefrorene
Aufzeichnung und keine Sammlung von Funktionen, die man einzeln aufrufen kann
und dabei eine vergisst.
"""

from __future__ import annotations

import dataclasses

from traidingbrain.domain.enums import Side

#: Wartungsmargensatz, wenn keiner übergeben wird. Derselbe Wert und dieselbe
#: Begründung wie in `data/exchange.py`: zu hoch angesetzt rückt die
#: Liquidation näher an den Einstieg, macht die Rechnung also vorsichtiger.
STANDARD_MMR = 0.005


class UnsizeablePlanError(ValueError):
    """Die Eingaben beschreiben keine Position, die es geben kann."""


@dataclasses.dataclass(frozen=True, slots=True)
class PlanSize:
    """Eine geplante Position, vollständig -- alle zehn Grössen auf einmal.

    Alles in Kontowährung, ausser den ausdrücklich als Anteil benannten Feldern.
    """

    # -- 1. Konto und Einsatz ---------------------------------------------- #
    equity: float
    margin: float
    margin_share: float
    """Die Margin als Anteil des Kontos. `300/1000 = 0.30`.

    Steht neben `margin`, weil die absolute Zahl beim Aufstocken wandert und
    der Anteil die eigentliche Entscheidung ist.
    """

    leverage: float
    notional: float

    # -- 2. Der Stop ------------------------------------------------------- #
    entry: float
    stop: float
    stop_distance: float
    stop_fraction: float
    """Der Stopabstand als Anteil des Einstiegspreises -- die Zahl, die aus der
    Margin ein Risiko macht."""

    # -- 3. Was der Stop kostet -------------------------------------------- #
    loss_at_stop: float
    loss_at_stop_share: float
    """Der Verlust am Stop als Anteil des KONTOS. **Die wichtigste Zahl hier.**

    Sie ist das, was „wie viel riskiere ich" wirklich bedeutet, und sie kommt in
    der Formulierung „300 CHF bei 7x" nicht vor.
    """

    # -- 4. Die Börse ------------------------------------------------------ #
    liquidation_price: float
    liquidation_distance: float
    liquidation_fraction: float
    stop_beyond_liquidation: bool
    """Ob die Börse vor dem Stop schliesst.

    Ist das wahr, ist der geplante Verlust eine Fiktion: verloren ist dann die
    ganze Margin. `effective_loss` rechnet damit, `loss_at_stop` ohne.
    """

    # -- 5. Kosten --------------------------------------------------------- #
    cost: float
    cost_share_of_risk: float
    """Die Umlaufkosten als Anteil des Risikos -- der Deckel, den
    `max_cost_fraction_of_risk` prüft."""

    def __post_init__(self) -> None:
        for name in ("equity", "margin", "leverage", "notional", "entry"):
            if getattr(self, name) <= 0:
                raise UnsizeablePlanError(f"{name} muss positiv sein")

    # -- Abgeleitet, aber nicht optional ------------------------------------ #

    @property
    def effective_loss(self) -> float:
        """Was wirklich verloren geht -- Stop oder Margin, je nachdem.

        `loss_at_stop` ist der Plan, dies ist das Ergebnis. Bei den 1,20 % der
        gemessenen Trades, deren Stop jenseits der Liquidation liegt, sind die
        beiden verschieden, und nur diese Zahl stimmt.
        """
        return self.margin if self.stop_beyond_liquidation else self.loss_at_stop

    @property
    def effective_loss_share(self) -> float:
        return self.effective_loss / self.equity

    def describe(self) -> str:
        """Die Position in einem Satz, mit der Zahl, die sonst fehlt."""
        warnung = (
            "  ACHTUNG: Stop liegt JENSEITS der Liquidation"
            if self.stop_beyond_liquidation
            else ""
        )
        return (
            f"{self.margin:,.2f} Margin ({self.margin_share:.1%} des Kontos) "
            f"x {self.leverage:g}x = {self.notional:,.2f} Nominal | "
            f"Stop {self.stop_fraction:.2%} entfernt -> Verlust "
            f"{self.effective_loss:,.2f} = {self.effective_loss_share:.2%} des Kontos | "
            f"Liquidation {self.liquidation_fraction:.2%} entfernt{warnung}"
        )


def plan_size(
    *,
    equity: float,
    margin_share: float,
    leverage: float,
    entry: float,
    stop: float,
    side: Side,
    maintenance_margin_rate: float = STANDARD_MMR,
    cost_fraction: float = 0.0,
) -> PlanSize:
    """Die zehn Grössen aus der VORWÄRTS-Richtung: Margin und Hebel hinein.

    `cost_fraction` ist der Umlaufkostensatz als Anteil des Nominals (Gebühren
    plus Schlupf, beide Seiten). Null ist erlaubt und heisst „Kosten hier nicht
    betrachtet", nicht „keine Kosten" -- der Unterschied steht in
    `cost_share_of_risk`, das dann ebenfalls null ist.
    """
    if not 0.0 < margin_share <= 1.0:
        raise UnsizeablePlanError(
            f"margin_share {margin_share} liegt nicht in (0, 1] -- mehr als das "
            f"ganze Konto als Margin gibt es nicht"
        )
    if leverage <= 0:
        raise UnsizeablePlanError(f"Hebel {leverage} muss positiv sein")
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        raise UnsizeablePlanError(
            "Einstieg und Stop sind gleich -- dann gibt es kein Risiko und "
            "keine Groesse, nur eine Division durch null"
        )
    if side is Side.LONG and stop >= entry:
        raise UnsizeablePlanError(f"Long mit Stop {stop} ueber Einstieg {entry}")
    if side is Side.SHORT and stop <= entry:
        raise UnsizeablePlanError(f"Short mit Stop {stop} unter Einstieg {entry}")

    margin = equity * margin_share
    notional = margin * leverage
    stop_fraction = stop_distance / entry
    loss_at_stop = notional * stop_fraction

    # Die Liquidation: eine Gegenbewegung von (1/Hebel - MMR) loescht die
    # Margin. Als PREIS ausgedrueckt, damit sie neben Einstieg und Stop steht
    # und nicht erst umgerechnet werden muss.
    liq_fraction = max(1.0 / leverage - maintenance_margin_rate, 0.0)
    liq_distance = entry * liq_fraction
    liq_price = (
        entry - liq_distance if side is Side.LONG else entry + liq_distance
    )
    cost = notional * cost_fraction

    return PlanSize(
        equity=equity,
        margin=margin,
        margin_share=margin_share,
        leverage=leverage,
        notional=notional,
        entry=entry,
        stop=stop,
        stop_distance=stop_distance,
        stop_fraction=stop_fraction,
        loss_at_stop=loss_at_stop,
        loss_at_stop_share=loss_at_stop / equity,
        liquidation_price=liq_price,
        liquidation_distance=liq_distance,
        liquidation_fraction=liq_fraction,
        stop_beyond_liquidation=stop_fraction > liq_fraction,
        cost=cost,
        cost_share_of_risk=cost / loss_at_stop if loss_at_stop > 0 else 0.0,
    )


# --------------------------------------------------------------------------- #
# Die beiden Grössen, die eine EINZELNE Position nicht hat
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True, slots=True)
class PortfolioLoad:
    """Was mehrere offene Positionen zusammen binden und zusammen riskieren."""

    positions: int
    bound_margin: float
    bound_margin_share: float
    correlated_loss: float
    correlated_loss_share: float
    """Der Verlust, wenn ALLE Positionen gleichzeitig ihren Stop treffen.

    Das ist keine Prognose, sondern eine Schranke -- und in diesem Markt die
    realistische. Gemessen hat dieses System Beta 1,0 zu BTC: zwölf Positionen
    sind nicht zwölf Wetten, sondern eine, zwölfmal.
    """

    free_margin: float

    @property
    def is_overcommitted(self) -> bool:
        return self.bound_margin > self.equity_implied

    @property
    def equity_implied(self) -> float:
        """Das Konto, aus dem die Anteile gerechnet wurden."""
        return self.bound_margin / self.bound_margin_share if self.bound_margin_share else 0.0


def portfolio_load(plans: list[PlanSize], *, equity: float) -> PortfolioLoad:
    """Die Last mehrerer Positionen -- gebundene Margin und Verlust im Gleichlauf.

    **Der Gleichlauf ist der Punkt.** Ein Konto mit zwölf Positionen zu je 5 %
    Risiko riskiert nicht 5 %, sondern bis zu 60 % -- und in einem Markt mit
    Beta 1,0 ist das keine Randannahme, sondern der Normalfall an einem roten
    Tag. Die Summe wird hier ohne Korrelationsabschlag gebildet, und das ist
    Absicht: ein Abschlag waere eine Schaetzung, die Summe ist eine Schranke.
    """
    if equity <= 0:
        raise UnsizeablePlanError(f"Konto muss positiv sein, nicht {equity}")
    gebunden = sum(p.margin for p in plans)
    verlust = sum(p.effective_loss for p in plans)
    return PortfolioLoad(
        positions=len(plans),
        bound_margin=gebunden,
        bound_margin_share=gebunden / equity,
        correlated_loss=verlust,
        correlated_loss_share=verlust / equity,
        free_margin=equity - gebunden,
    )
