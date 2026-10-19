"""Wohin dieses Konto nach der gemessenen Verteilung läuft.

**Warum das auf den Bildschirm gehört.** Das Dashboard zeigt „1'000.00
+0.00 %". Was es verschweigt, ist, was dieselbe Grössenregel über die
gespeicherten Monate getan hat — und genau diese Zahl hätte die Erwartung
Wochen früher richtiggestellt. Sie steht jetzt neben dem Kontostand statt in
einer Unterhaltung.

**Was das IST.** Eine Zusammenfassung dessen, was passiert wäre: die
gespeicherten Monate dieses Systems, zufällig zu Sechs-Monats-Strecken
zusammengesetzt, mit Margin-Buchhaltung und Kontoboden gerechnet.

**Was es NICHT ist: eine Vorhersage.** Die Zukunft hat andere Monate. Und
die Suche nach einem Vorhersager ist gelaufen und gescheitert — über 69
Monate liegt die Autokorrelation der Monatsfaktoren bei -0,1557 im
Zufallsband [-0,2419, +0,2294], und weder BTCs Rendite noch seine Volatilität
im Vormonat sagen etwas (+0,1116 und +0,0940, beide im Band). Nicht einmal
BTCs Bewegung *im* Monat erklärt ihn (+0,0753). Darum steht hier eine
Verteilung und kein Signal: es gibt nichts zu signalisieren.

**Die Eigenschaft, die zehn Millionen Szenarien rechenbar macht.** Bei festem
Margin-Anteil hängt es NICHT vom Kontostand ab, wie viele Positionen
hineinpassen — jede bindet denselben *Anteil*. Die Menge der genommenen
Trades eines Monats ist damit eine Eigenschaft des Monats, nicht des Kontos,
und der Monatsfaktor eine Konstante. Ein Szenario ist ihr Produkt.

Die eine Stelle, an der das bricht, ist der Kontoboden: unter einem Rest
lässt sich keine Position mehr stellen. Darum führt `Monatsfaktoren` je Monat
zusätzlich den tiefsten Zwischenstand, und ein Szenario stirbt, sobald es ihn
unterschreitet. Ohne diesen zweiten Wert wäre die Rechnung zu günstig: sie
liesse Konten weiterhandeln, die längst handlungsunfähig waren.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from traidingbrain.domain.enums import Side
from traidingbrain.risk.plansize import UnsizeablePlanError, plan_size

TAG_MS = 86_400_000

#: Die Länge eines Bausteins. Dreissig Tage, nicht ein Kalendermonat --
#: gleich lange Stücke, damit kein Baustein durch seine Länge schwerer wiegt.
BLOCK_TAGE = 30

#: Ein Monat mit weniger Trades ist kein Monat, sondern eine Lücke in den Daten.
MIN_TRADES_JE_BLOCK = 10

#: Unter diesem Anteil des Starts ist keine Position mehr stellbar.
BODEN = 0.01

#: Ab hier gilt ein Konto als praktisch ausgelöscht.
RUIN = 0.10

#: So viele Monate braucht es mindestens, bevor eine Verteilung behauptet
#: wird. Ein Jahr.
#:
#: Die Schwelle war zuerst „mindestens so viele Bausteine wie Monate im
#: Fenster" -- und das war willkürlich: bei sechs Monaten hätten sechs
#: Bausteine gereicht, und aus sechs Zahlen lässt sich keine Verteilung
#: bilden, nur eine Aufzählung mit Zwischenräumen. Eine feste Zahl ist
#: ebenfalls eine Wahl, aber eine benannte und begründbare.
MIN_BAUSTEINE = 12


@dataclasses.dataclass(frozen=True, slots=True)
class Fill:
    """Ein gespeicherter Trade, getypt.

    Die Fill-Dateien sind JSON, also kommt alles als `object` herein. Einmal
    hier geparst statt an jeder Lesestelle `int(row["opened_ts"])` zu
    schreiben: das Schema steht an einer Stelle, und ein fehlendes Feld faellt
    beim Laden auf statt mitten in einer Rechnung.
    """

    opened_ts: int
    closed_ts: int
    entry: float
    qty: float
    risk_amount: float
    side: Side
    r_multiple: float

    @property
    def stop(self) -> float:
        """Der Stop, aus Risiko und Menge zurueckgerechnet.

        Steht nicht in der Datei: gespeichert sind `risk_amount` und `qty`,
        und ihr Quotient ist die Stopweite in Preiseinheiten.
        """
        weite = self.risk_amount / self.qty
        return self.entry + weite if self.side is Side.SHORT else self.entry - weite

    @classmethod
    def von(cls, row: Mapping[str, object]) -> Fill | None:
        """`None`, wenn die Zeile nicht rechenbar ist -- statt zu raten."""
        try:
            entry = float(row["entry_price"])  # type: ignore[arg-type]
            qty = float(row["qty"])  # type: ignore[arg-type]
            if entry <= 0 or qty <= 0:
                return None
            return cls(
                opened_ts=int(row["opened_ts"]),  # type: ignore[call-overload]
                closed_ts=int(row["closed_ts"]),  # type: ignore[call-overload]
                entry=entry,
                qty=qty,
                risk_amount=float(row["risk_amount"]),  # type: ignore[arg-type]
                side=Side.SHORT if str(row["side"]).lower() == "short" else Side.LONG,
                r_multiple=float(row["r_multiple"]),  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclasses.dataclass(frozen=True, slots=True)
class Monatsfaktoren:
    """Was jeder gespeicherte Monat mit einem Konto macht.

    Teuer zu bauen (ein Durchlauf über alle Fills je Monat), aber nur von der
    Grössenregel abhängig -- nicht vom Kontostand. Darum einmal rechnen und
    behalten, solange `margin_share` und `leverage` gleich bleiben.
    """

    faktor: tuple[float, ...]
    """Endstand eines Monats, auf einem Konto von 1,0 gerechnet."""

    tiefst: tuple[float, ...]
    """Tiefster Zwischenstand desselben Monats. Entscheidet über den Boden."""

    margin_share: float
    leverage: float

    @property
    def gewinnmonate(self) -> int:
        return sum(1 for f in self.faktor if f > 1.0)

    @property
    def anzahl(self) -> int:
        return len(self.faktor)


@dataclasses.dataclass(frozen=True, slots=True)
class Aussicht:
    """Die Verteilung der Endstände -- bewusst ohne Erwartungswert.

    **Warum kein Mittelwert.** Bei multiplikativem Wachstum wird er von wenigen
    sehr guten Pfaden beherrscht und sagt nichts darüber, was EINEM Konto
    passiert. Über zehn Millionen Szenarien lag die Mitte bei 37 CHF, während
    das beste Konto 340.246 erreichte; ein Mittelwert daraus wäre eine Zahl,
    die kein einziges Konto je sieht.
    """

    start: float
    monate: int
    laeufe: int

    p05: float
    p25: float
    median: float
    p75: float
    p95: float
    bestes: float

    chance_plus: float
    """Anteil der Szenarien über dem Startwert."""

    chance_ruin: float
    """Anteil unter `RUIN` mal Start -- praktisch ausgelöscht."""

    gewinnmonate: int
    monate_gesamt: int

    margin_share: float
    leverage: float


def _block_faktor(
    block: list[Fill], *, margin_share: float, leverage: float
) -> tuple[float, float]:
    """Faktor und tiefster Zwischenstand eines Monats, auf Konto 1,0.

    Rechnet mit echter Margin-Buchhaltung: eine offene Position bindet
    `margin_share` des Kontos, und solange sie laeuft, steht dieser Teil fuer
    den naechsten Einstieg nicht zur Verfuegung. Bei 30 % passen darum drei
    Positionen und die vierte findet nichts -- `sim/broker.py:500` lehnt
    genau so ab.
    """
    konto = tief = 1.0
    offen: list[tuple[int, float, float]] = []
    for fill in block:
        for pos in sorted([p for p in offen if p[0] <= fill.opened_ts]):
            konto += pos[2]
            tief = min(tief, konto)
            offen.remove(pos)
        try:
            p = plan_size(
                equity=konto, margin_share=margin_share, leverage=leverage,
                entry=fill.entry, stop=fill.stop, side=fill.side,
            )
        except UnsizeablePlanError:
            continue
        if p.margin > konto - sum(o[1] for o in offen):
            continue
        # Liegt der Stop jenseits der Liquidation, schliesst die Boerse
        # zuerst -- unabhaengig davon, wie der Trade ENDETE. Die strenge
        # Lesart, weil die gespeicherten Fills keine unguenstigste
        # Zwischenbewegung fuehren und ein geschenkter Gewinn hohen Hebel
        # schmeichelt: bei 10 % x 21x waren 401 von 1.134 solcher Trades
        # Gewinner, und die guenstige Lesart machte daraus faelschlich ein
        # besseres Ergebnis als bei weniger Hebel.
        ergebnis = -p.margin if p.stop_beyond_liquidation else p.loss_at_stop * fill.r_multiple
        offen.append((fill.closed_ts, p.margin, ergebnis))
    for pos in offen:
        konto += pos[2]
        tief = min(tief, konto)
    return max(konto, 0.0), max(tief, 0.0)


def monatsfaktoren(
    fills_root: Path, *, margin_share: float, leverage: float
) -> Monatsfaktoren:
    """Jeden gespeicherten Monat einmal durchrechnen. Teuer, aber nur einmal."""
    fills: list[Fill] = []
    for path in sorted(fills_root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            gelesen = Fill.von(row)
            if gelesen is not None:
                fills.append(gelesen)
    if not fills:
        return Monatsfaktoren((), (), margin_share, leverage)
    fills.sort(key=lambda f: f.opened_ts)

    t0, t1 = fills[0].opened_ts, fills[-1].opened_ts
    faktoren: list[float] = []
    tiefen: list[float] = []
    anfang = t0
    while anfang + BLOCK_TAGE * TAG_MS <= t1:
        block = [f for f in fills if anfang <= f.opened_ts < anfang + BLOCK_TAGE * TAG_MS]
        if len(block) >= MIN_TRADES_JE_BLOCK:
            f_, tief = _block_faktor(block, margin_share=margin_share, leverage=leverage)
            faktoren.append(f_)
            tiefen.append(tief)
        anfang += BLOCK_TAGE * TAG_MS
    return Monatsfaktoren(tuple(faktoren), tuple(tiefen), margin_share, leverage)


def aussicht(
    faktoren: Monatsfaktoren,
    *,
    start: float,
    monate: int = 6,
    laeufe: int = 200_000,
    seed: int = 20261019,
) -> Aussicht | None:
    """Die Verteilung nach `monate` Monaten. Billig -- nur Ziehen und Multiplizieren.

    `None` unter `MIN_BAUSTEINE` Monaten. Eine Verteilung aus drei Monaten
    wäre keine Verteilung, sondern drei Zahlen mit Fehlerbalken aus dem Nichts
    -- und sie sähe auf dem Bildschirm genauso aus wie eine belegte.
    """
    if faktoren.anzahl < MIN_BAUSTEINE or start <= 0 or monate < 1:
        return None

    f = np.array(faktoren.faktor)
    t = np.array(faktoren.tiefst)
    rng = np.random.default_rng(seed)
    zug = rng.integers(0, f.size, size=(laeufe, monate))

    konto = np.ones(laeufe)
    lebt = np.ones(laeufe, dtype=bool)
    for m in range(monate):
        idx = zug[:, m]
        # Stirbt das Konto INNERHALB des Monats, an seinem tiefsten Punkt?
        lebt &= (konto * t[idx]) > BODEN
        konto = np.where(lebt, konto * f[idx], konto)
    ende = np.where(lebt, konto, 0.0) * start

    srt = np.sort(ende)

    def perz(q: float) -> float:
        return float(srt[min(srt.size - 1, max(0, round(q * (srt.size - 1))))])

    return Aussicht(
        start=start,
        monate=monate,
        laeufe=laeufe,
        p05=perz(0.05),
        p25=perz(0.25),
        median=perz(0.50),
        p75=perz(0.75),
        p95=perz(0.95),
        bestes=float(srt[-1]),
        chance_plus=float((ende > start).mean()),
        chance_ruin=float((ende < RUIN * start).mean()),
        gewinnmonate=faktoren.gewinnmonate,
        monate_gesamt=faktoren.anzahl,
        margin_share=faktoren.margin_share,
        leverage=faktoren.leverage,
    )
