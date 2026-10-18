"""Wahrscheinlichkeit statt einer ausgewählten Kurve.

Das Ziel lautet: 1 000 CHF auf 20 000 CHF in sechs Monaten. Ein Backtest, der
das einmal schafft, beantwortet die Frage nicht -- er ist ein Pfad aus einer
Verteilung, und wer ihn zeigt, hat ihn ausgewählt. Dieses Modul rechnet die
Verteilung und gibt die Zielchance **neben** der Verlustchance aus.

## Woher die Trades kommen

Aus gemessenen R-Werten, in **Wochenblöcken** gezogen. Nicht aus einer
angenommenen Verteilung, und nicht einzeln gemischt: zwölf Märkte bewegen sich
gemeinsam, und ein Trade dauert mehrere Kerzen. Einzelne Trades zu ziehen
zerstört genau die Häufung, die das Ruinrisiko macht -- eine schlechte Woche,
in der alle Positionen zusammen verlieren, ist in einer Zeilenmischung
unsichtbar.

## Was der Hebel wirklich ändert

Nicht die R-Zahl. Bei stopbasiertem Sizing ist die Positionsgrösse durch
`Risiko / Stop-Abstand` bestimmt, und der Hebel steuert nur Margin-Bindung und
Liquidationsabstand. Er wird hier an genau der Stelle wirksam, an der er in der
Praxis wirksam wird:

> Liegt die Liquidation **näher** als der Stop, endet der Trade nicht beim
> geplanten Verlust, sondern beim Verlust der ganzen Margin.

`config/risk.yaml` wählt den Hebel so, dass die Liquidation mindestens 2,5
Stop-Abstaende dahinter liegt -- unter dieser Regel ist der Hebel für das
Ergebnis gleichgültig. Erst wenn man sie überschreitet, bekommt er Zähne, und
dann heissen die Zähne Ruin und nicht Rendite. Darum ist `leverage` hier ein
Szenarioparameter und keine Stellschraube: ein 10x-Lauf ist kein Vorschlag,
zehnmal das Konto zu riskieren.

Gemessen wird das über `max_adverse_r` je Trade -- wie weit der Preis gegen den
Trade lief, in R des ursprünglichen Stops. Ist der Liquidationsabstand kleiner
als diese Zahl, wäre liquidiert worden.

## Was dieses Modul NICHT kann

* **Es erfindet keinen Vorteil.** Zieht man aus gemessenen R-Werten, deren
  Mittel negativ ist, kommt eine Verteilung mit negativem Drift heraus. Ein
  positiver Arm muss als Szenario ausdrücklich hineingegeben werden und heisst
  dann **modellbedingt**, bis Vorwärtsdaten ihn stützen.
* **20 000 synthetische Pfade sind nicht 20 000 neue Marktphasen.** Das
  Monte-Carlo-Intervall deckt die Ziehunsicherheit, nicht die
  Modellunsicherheit. Beide werden getrennt berichtet.
* **Replay und Vorwärts werden nie in einen Pool geworfen.** Ein Replay-Trade
  kennt sein Fenster im Nachhinein; ein Vorwärts-Trade nicht.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Sechs Monate, wie der Auftrag sie definiert.
GOAL_DAYS = 182

#: Die Schwellen aus der Pflichtausgabe des Auftrags, in CHF.
RUIN_LEVEL = 200.0
HALF_LEVEL = 500.0

#: Wartungsmargenrate. Aus `config/risk.yaml`-Grössenordnung; der
#: Liquidationsabstand bei Hebel L ist näherungsweise `1/L - mmr`.
MAINTENANCE_MARGIN = 0.005

#: Unter so vielen Wochenblöcken ist jede Ziehung eine Wiederholung derselben
#: paar Wochen, und die Verteilung sagt mehr über sie als über die Zukunft.
MIN_BLOCKS = 8


@dataclass(frozen=True, slots=True)
class Scenario:
    """Eine benannte Annahmenlage. Jedes Feld ist eine Annahme, keine Messung."""

    name: str
    risk_fraction: float
    leverage: float = 1.0
    #: Verschiebung des mittleren R je Trade. 0.0 heisst: gemessene Verteilung
    #: unverändert. Alles andere ist eine Hypothese und wird so berichtet.
    edge_shift: float = 0.0
    #: Faktor auf die Kosten je Trade, in R. 1.0 heisst: wie gemessen.
    cost_multiplier: float = 1.0
    #: Faktor auf die Streuung. >1 modelliert erhöhte Korrelation, weil
    #: gleichzeitige Verluste wie ein grösserer Einzelverlust wirken.
    spread_multiplier: float = 1.0
    #: Anteil der Trades, der durch Feed- oder Orderausfall nicht zustande kommt.
    failure_rate: float = 0.0
    note: str = ""


@dataclass(frozen=True, slots=True)
class Outcome:
    """Was aus einem Szenario über alle Pfade wurde."""

    scenario: str
    paths: int
    trades_per_path: int
    reached_at_end: float
    reached_ever: float
    below_start: float
    below_half: float
    below_ruin: float
    liquidated: float
    median_end: float
    quantiles: dict[int, float]
    max_drawdown_median: float
    cvar_5: float
    median_trades_to_goal: float | None
    model_dependent: bool = True
    note: str = ""

    def as_row(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "P(Ziel am Ende)": self.reached_at_end,
            "P(Ziel irgendwann)": self.reached_ever,
            "P(unter Start)": self.below_start,
            "P(<= 500)": self.below_half,
            "P(<= 200)": self.below_ruin,
            "P(Liquidation)": self.liquidated,
            "Median Ende": self.median_end,
            "CVaR 5%": self.cvar_5,
        }


def weekly_blocks(stamps: np.ndarray, *, week_ms: int = 7 * 86_400_000) -> dict[int, np.ndarray]:
    """Zeilenindizes je Wochenblock.

    Der Block ist die Ziehungseinheit. Alles, was in derselben Woche passierte,
    bleibt zusammen -- auch über Märkte hinweg, weil gleichzeitige Verluste
    gemeinsam auftreten und genau das das Ruinrisiko trägt.
    """
    blocks = stamps // week_ms
    return {int(b): np.flatnonzero(blocks == b) for b in np.unique(blocks)}


def _draw_sequence(
    values: np.ndarray,
    blocks: dict[int, np.ndarray],
    *,
    length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Eine Folge von `length` R-Werten, aus ganzen Wochen gezogen."""
    keys = np.array(sorted(blocks))
    sizes = np.array([blocks[k].size for k in keys])
    per_draw = max(1, int(np.ceil(length / sizes.mean())) + 1)
    taken: list[np.ndarray] = []
    collected = 0
    while collected < length:
        for key in rng.choice(keys, size=per_draw, replace=True):
            index = blocks[int(key)]
            taken.append(index)
            collected += index.size
            if collected >= length:
                break
    # Benannt statt direkt zurueckgegeben: numpy-Indexierung ist fuer
    # mypy `Any`, und eine Funktion, die `ndarray` verspricht, soll das
    # auch pruefbar halten. Zur Laufzeit identisch.
    gezogen: np.ndarray = values[np.concatenate(taken)[:length]]
    return gezogen


def liquidation_distance(leverage: float) -> float:
    """Wie weit der Preis laufen darf, bevor liquidiert wird -- als Preisanteil.

    Näherung: die Initial Margin ist `1/leverage` des Notionals, und liquidiert
    wird, wenn davon nur noch die Wartungsmarge übrig ist.
    """
    if leverage <= 0.0:
        raise ValueError(f"Hebel {leverage} ist nicht positiv.")
    return max(1.0 / leverage - MAINTENANCE_MARGIN, 1e-9)


def _apply_scenario(
    r: np.ndarray, scenario: Scenario, *, mean_r: float, rng: np.random.Generator
) -> np.ndarray:
    """Die Szenarioannahmen auf eine gezogene Folge.

    Reihenfolge mit Absicht: erst die Streuung um das gemessene Mittel
    skalieren, dann den hypothetischen Vorteil addieren, dann Kosten abziehen.
    Umgekehrt würde die Streuungsskalierung auch den hypothetischen Vorteil
    streckeln, und dann wäre nicht mehr erkennbar, welcher Teil der Verteilung
    gemessen und welcher angenommen ist.
    """
    out = r
    if scenario.spread_multiplier != 1.0:
        out = mean_r + (out - mean_r) * scenario.spread_multiplier
    out = out + scenario.edge_shift
    if scenario.cost_multiplier != 1.0:
        # Zusaetzliche Kosten treffen jeden Trade gleich, in R.
        out = out - (scenario.cost_multiplier - 1.0) * abs(mean_r)
    if scenario.failure_rate > 0.0:
        # Ein ausgefallener Trade ist kein Verlust, sondern ein Nicht-Ereignis.
        out = np.where(rng.random(out.size) >= scenario.failure_rate, out, 0.0)
    return out


@dataclass(frozen=True, slots=True)
class Walk:
    """Was auf einem einzelnen Pfad passierte."""

    end: float
    low: float
    peak: float
    drawdown: float
    liquidated: bool
    hit_at: int


def _walk_one_path(
    r: np.ndarray,
    *,
    would_liquidate: np.ndarray,
    scenario: Scenario,
    start_equity: float,
    target_equity: float,
) -> Walk:
    """Ein Kapitalpfad, Trade für Trade.

    Getrennt, weil hier die einzige Stelle sitzt, an der der Hebel wirkt: wenn
    die Liquidation vor dem Stop greift, ist die ganze Margin weg und nicht der
    geplante Verlust.
    """
    equity = peak = low = start_equity
    worst = 0.0
    liquidated = False
    hit_at = -1
    for step in range(r.size):
        if would_liquidate[step]:
            equity = max(equity - equity * scenario.risk_fraction * scenario.leverage, 0.0)
            liquidated = True
        else:
            equity *= 1.0 + scenario.risk_fraction * float(r[step])
        if equity <= 0.0:
            return Walk(0.0, 0.0, peak, 1.0, liquidated, hit_at)
        peak = max(peak, equity)
        low = min(low, equity)
        worst = max(worst, 1.0 - equity / peak)
        if equity >= target_equity and hit_at < 0:
            hit_at = step + 1
    return Walk(equity, low, peak, worst, liquidated, hit_at)


def simulate(
    *,
    r_values: np.ndarray,
    stamps: np.ndarray,
    adverse_r: np.ndarray,
    stop_fraction: np.ndarray,
    scenario: Scenario,
    start_equity: float,
    target_equity: float,
    trades: int,
    paths: int,
    seed: int,
) -> Outcome:
    """Eine Szenariorechnung über `paths` Pfade.

    `adverse_r` und `stop_fraction` werden gebraucht, um den Hebel ehrlich zu
    modellieren: der Liquidationsabstand ist ein Preisanteil, `max_adverse_r`
    ist in R des Stops, und die Umrechnung braucht den Stop-Abstand des Trades.
    """
    if not (0.0 < scenario.risk_fraction < 1.0):
        raise ValueError(f"Risikofraktion {scenario.risk_fraction} liegt ausserhalb (0,1).")
    sizes = {len(r_values), len(stamps), len(adverse_r), len(stop_fraction)}
    if len(sizes) != 1:
        raise ValueError(f"Ungleiche Laengen: {sizes}")

    blocks = weekly_blocks(stamps)
    if len(blocks) < MIN_BLOCKS:
        raise ValueError(
            f"Nur {len(blocks)} Wochenbloecke. Darunter ist jede Ziehung eine "
            f"Wiederholung derselben paar Wochen."
        )

    rng = np.random.default_rng(seed)
    mean_r = float(r_values.mean())
    liq = liquidation_distance(scenario.leverage)

    # Je Trade: ab welchem max_adverse_r haette die Liquidation vor dem Stop
    # gegriffen? liq ist ein Preisanteil, adverse_r ist in R des Stops.
    liq_in_r = np.where(stop_fraction > 0.0, liq / stop_fraction, np.inf)

    ends = np.empty(paths)
    lows = np.empty(paths)
    highs = np.empty(paths)
    drawdowns = np.empty(paths)
    liquidated = np.zeros(paths, dtype=bool)
    hit_at = np.full(paths, -1, dtype=int)

    index_pool = np.arange(r_values.size)
    for path in range(paths):
        picked = _draw_sequence(index_pool, blocks, length=trades, rng=rng)
        r = _apply_scenario(r_values[picked], scenario, mean_r=mean_r, rng=rng)
        walk = _walk_one_path(
            r,
            would_liquidate=adverse_r[picked] >= liq_in_r[picked],
            scenario=scenario,
            start_equity=start_equity,
            target_equity=target_equity,
        )
        ends[path] = walk.end
        lows[path] = walk.low
        highs[path] = walk.peak
        drawdowns[path] = walk.drawdown
        liquidated[path] = walk.liquidated
        hit_at[path] = walk.hit_at

    reached_ever = highs >= target_equity
    sorted_ends = np.sort(ends)
    tail = sorted_ends[: max(1, int(0.05 * paths))]
    hit = hit_at[hit_at > 0]

    return Outcome(
        scenario=scenario.name,
        paths=paths,
        trades_per_path=trades,
        reached_at_end=float((ends >= target_equity).mean()),
        reached_ever=float(reached_ever.mean()),
        below_start=float((ends < start_equity).mean()),
        below_half=float((lows <= HALF_LEVEL).mean()),
        below_ruin=float((lows <= RUIN_LEVEL).mean()),
        liquidated=float(liquidated.mean()),
        median_end=float(np.median(ends)),
        quantiles={q: float(np.percentile(ends, q)) for q in (5, 25, 50, 75, 95)},
        max_drawdown_median=float(np.median(drawdowns)),
        cvar_5=float(tail.mean()),
        median_trades_to_goal=float(np.median(hit)) if hit.size else None,
        note=scenario.note,
    )


@dataclass
class Running:
    """Laufende Kosten, die aus dem Startkapital bezahlt werden.

    Bei 1 000 CHF ist auch ein Monatsbetrag materiell: 50 CHF über sechs Monate
    sind 300 CHF, also 30 % des Startkapitals. Diese Zeile gehört in jede
    Zielrechnung und nicht in eine Fussnote.
    """

    items: dict[str, float] = field(default_factory=dict)

    def total(self, *, months: float = 6.0) -> float:
        return float(sum(self.items.values()) * months)

    def share_of(self, equity: float, *, months: float = 6.0) -> float:
        return self.total(months=months) / equity if equity else float("nan")
